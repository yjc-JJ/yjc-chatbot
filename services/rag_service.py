"""
RAG 服务：文本分段、检索增强生成
使用 SQLite 向量存储替代 ChromaDB，避免 ChromaDB 崩溃问题
"""
import logging
import os
from typing import List, Tuple
from dotenv import load_dotenv

from services.embedding import get_embedding, get_embeddings
from services.vector_store import index_document, delete_document_chunks, retrieve_relevant_chunks, get_file_chunks, get_all_user_chunks

load_dotenv()

logger = logging.getLogger("rag_service")


def get_user_collection_name(user_id: int) -> str:
    return f"user_{user_id}_kb"


async def delete_user_collection(user_id: int):
    logger.info(f"删除用户集合: user_id={user_id}")


def split_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[str]:
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk.strip())
        start += (chunk_size - overlap)
        if start >= text_len:
            break
    return chunks


async def index_document_rag(
    user_id: int,
    filename: str,
    content: str,
) -> Tuple[int, List[str]]:
    logger.info(f"开始索引文档: user_id={user_id}, filename={filename}, content_length={len(content)}")

    chunks = split_text(content)
    if not chunks:
        logger.warning(f"文档分块为空: {filename}")
        return 0, []
    logger.info(f"文档分块完成: {len(chunks)} 个块")

    logger.info(f"开始获取嵌入向量: {len(chunks)} 个块")
    embeddings = await get_embeddings(chunks)
    logger.info(f"嵌入向量获取完成: {len(embeddings)} 个向量")

    count, chunks = await index_document(user_id, filename, content, chunks, embeddings)
    return count, chunks


async def retrieve_relevant_chunks_rag(
    user_id: int,
    query: str,
    top_k: int = 5,
) -> List[str]:
    logger.info(f"开始检索知识库: user_id={user_id}, query={query[:50]}...")
    
    query_embedding = await get_embedding(query)
    relevant_chunks = await retrieve_relevant_chunks(user_id, query_embedding, top_k)
    
    logger.info(f"知识库检索完成: 找到 {len(relevant_chunks)} 条相关片段")
    return relevant_chunks


def build_rag_prompt(
    user_query: str,
    relevant_chunks: List[str] = None,
    conversation_history: List[dict] = None,
    use_rag: bool = True,
    search_results: List[dict] = None,
) -> List[dict]:
    if relevant_chunks is None:
        relevant_chunks = []
    if conversation_history is None:
        conversation_history = []
    if search_results is None:
        search_results = []

    # 构建上下文内容
    context_parts = []

    # 知识库检索结果
    if use_rag and relevant_chunks:
        kb_context = "【知识库相关片段】\n\n"
        for i, chunk in enumerate(relevant_chunks, 1):
            kb_context += f"[片段{i}]\n{chunk}\n\n"
        context_parts.append(kb_context)

    # 联网搜索结果
    if search_results:
        search_context = "【联网搜索结果】\n\n"
        for i, result in enumerate(search_results, 1):
            search_context += f"[搜索结果{i}]\n标题：{result.get('title', '')}\n来源：{result.get('source', '')}\n内容：{result.get('snippet', '')}\n"
            url = result.get('url', '')
            if url:
                search_context += f"链接：{url}\n"
            search_context += "\n"
        context_parts.append(search_context)

    # 根据上下文类型选择 system prompt
    if use_rag and relevant_chunks:
        system_prompt = """你是一个基于知识库的智能聊天机器人。请根据提供的知识库片段来回答用户的问题。

规则：
1. 优先基于知识库内容进行回答，并在回答中引用相关片段。
2. 如果知识库中没有相关信息，请如实告知用户。
3. 回答要专业、准确、简洁。
4. 可以进行友好的闲聊。"""
    elif search_results:
        system_prompt = """你是一个具备联网搜索能力的智能聊天机器人。请根据提供的联网搜索结果来回答用户的问题。

规则：
1. 优先基于搜索结果中的信息进行回答，确保信息的准确性和时效性。
2. 如果搜索结果中有具体的链接，可以在回答中引用。
3. 如果搜索结果不足以回答问题，请如实告知用户。
4. 回答要专业、准确、简洁。
5. 可以进行友好的闲聊。"""
    else:
        system_prompt = """你是一个友好的智能聊天机器人。请用你的知识来回答用户的问题。

规则：
1. 回答要专业、准确、简洁。
2. 如果不知道答案，请如实告知用户。
3. 可以进行友好的闲聊。"""

    # 拼接所有上下文和用户问题
    if context_parts:
        user_message = "".join(context_parts) + f"【用户问题】\n{user_query}"
    else:
        user_message = user_query

    messages = [{"role": "system", "content": system_prompt}]

    if conversation_history:
        messages.extend(conversation_history)

    messages.append({"role": "user", "content": user_message})

    return messages
