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

    logger.info(f"收到消息: user={current_user.email}, conv_id={conversation_id}, use_rag={data.use_rag}, msg_len={len(data.message)}")

    user_message = Message(
        conversation_id=conversation_id,
        role="user",
        content=data.message,
    )
    db.add(user_message)
    conversation.updated_at = datetime.datetime.utcnow()
    await db.commit()

    relevant_chunks = []
    use_rag_enabled = data.use_rag is True
    
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
