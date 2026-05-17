"""
聊天路由：RAG 流式对话 (SSE)
"""
import json
import datetime
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models import User, Conversation, Message, SharedKnowledge, KnowledgeFile
from schemas import ChatRequest
from auth import get_current_user
from services.rag_service import retrieve_relevant_chunks_rag as retrieve_relevant_chunks, build_rag_prompt
from services.deepseek_client import stream_chat
from services.search_service import search as perform_search
from services.course_schedule_service import get_today_schedule
from services.emotion_service import analyze_message_emotion

router = APIRouter(prefix="/api/chat", tags=["chat"])

logger = logging.getLogger("chat")


async def get_shared_knowledge_user_ids(user_id: int, db: AsyncSession) -> List[int]:
    """获取用户已添加的共享知识库所属用户ID列表"""
    result = await db.execute(
        select(SharedKnowledge.knowledge_file_id)
        .where(SharedKnowledge.user_id == user_id)
    )
    shared_file_ids = [row[0] for row in result.all()]
    
    if not shared_file_ids:
        return []
    
    result = await db.execute(
        select(KnowledgeFile.user_id)
        .where(KnowledgeFile.id.in_(shared_file_ids))
    )
    return [row[0] for row in result.all()]


@router.post("/{conversation_id}")
async def chat(
    conversation_id: int,
    data: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conversation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问该会话")

    logger.info(f"收到消息: user={current_user.email}, conv_id={conversation_id}, use_rag={data.use_rag}, use_search={data.use_search}, msg_len={len(data.message)}")

    # 情感分析
    emotion_result = await analyze_message_emotion(data.message)
    emotion = emotion_result.get("emotion")
    confidence = emotion_result.get("confidence")
    logger.info(f"情感分析结果: emotion={emotion}, confidence={confidence}")

    # 检查是否为"今日课表"关键词请求
    if "今日课表" in data.message or "今天课表" in data.message or "课表" in data.message:
        logger.info(f"检测到课表查询请求: {data.message}")
        
        # 保存用户消息（包含情感标签）
        user_message = Message(
            conversation_id=conversation_id,
            role="user",
            content=data.message,
            emotion=emotion,
            confidence=confidence,
        )
        db.add(user_message)
        conversation.updated_at = datetime.datetime.utcnow()
        await db.commit()
        
        # 获取今日课表
        schedule_result = await get_today_schedule()
        
        # 保存助理回复
        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=schedule_result.get("message", "获取课表失败"),
        )
        db.add(assistant_message)
        await db.commit()
        
        # 直接返回课表信息（非流式），包含情感标签
        return {
            "success": True,
            "message": schedule_result.get("message", "获取课表失败"),
            "schedule": schedule_result.get("schedule", ""),
            "date": schedule_result.get("date", ""),
            "weekday": schedule_result.get("weekday", ""),
            "emotion": emotion,
            "emotion_confidence": confidence,
        }

    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        content=data.message,
        emotion=emotion,
        confidence=confidence,
    )
    db.add(user_message)
    conversation.updated_at = datetime.datetime.utcnow()
    await db.commit()

    relevant_chunks = []
    search_results = []
    use_rag_enabled = data.use_rag is True
    use_search_enabled = data.use_search is True

    if use_rag_enabled:
        logger.info(f"开始检索知识库: user_id={current_user.id}, query={data.message[:50]}...")

        # 检索当前用户自己的知识库
        user_chunks = await retrieve_relevant_chunks(
            user_id=current_user.id,
            query=data.message,
            top_k=5,
        )
        relevant_chunks.extend(user_chunks)

        # 检索用户已添加的共享知识库
        shared_user_ids = await get_shared_knowledge_user_ids(current_user.id, db)
        for shared_user_id in shared_user_ids:
            if shared_user_id != current_user.id:
                shared_chunks = await retrieve_relevant_chunks(
                    user_id=shared_user_id,
                    query=data.message,
                    top_k=3,
                )
                relevant_chunks.extend(shared_chunks)

        # 去重并保留前10条
        seen = set()
        relevant_chunks = [chunk for chunk in relevant_chunks if chunk not in seen and not seen.add(chunk)][:10]

        logger.info(f"知识库检索完成: 找到 {len(relevant_chunks)} 条相关片段")

    if use_search_enabled and not use_rag_enabled:
        logger.info(f"开始联网搜索: query={data.message[:50]}...")
        try:
            search_result = await perform_search(db, data.message, max_results=10, use_cache=True)
            if search_result.get('success'):
                search_results = search_result.get('results', [])
                logger.info(f"联网搜索完成: {len(search_results)} 条结果")
            else:
                logger.warning(f"联网搜索失败: {search_result.get('error', '未知错误')}")
        except Exception as e:
            logger.error(f"联网搜索异常: {e}", exc_info=True)

    msg_result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    all_messages = msg_result.scalars().all()

    conversation_history = []
    for msg in all_messages[:-1]:
        conversation_history.append({"role": msg.role, "content": msg.content})

    messages = build_rag_prompt(
        user_query=data.message,
        relevant_chunks=relevant_chunks,
        conversation_history=conversation_history,
        use_rag=use_rag_enabled,
        search_results=search_results,
    )

    async def generate():
        full_response = ""
        logger.info(f"开始流式生成: conv_id={conversation_id}")
        try:
            async for token in stream_chat(messages=messages):
                full_response += token
                yield f"data: {json.dumps({'token': token}, ensure_ascii=False)}\n\n"
            logger.info(f"流式生成完成: conv_id={conversation_id}, response_len={len(full_response)}")
        except Exception as e:
            logger.error(f"流式生成错误: conv_id={conversation_id}, error={e}", exc_info=True)
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

        assistant_message = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=full_response,
        )
        db.add(assistant_message)
        await db.commit()

        yield f"data: {json.dumps({'done': True}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
