"""
RAG 服务：文本分段、检索增强生成
使用 SQLite 向量存储替代 ChromaDB，避免 ChromaDB 崩溃问题
"""
import logging
import os
from typing import List, Tuple
from dotenv import load_dotenv

from services.embedding import get_embedding, get_embeddings
from services.vector_store import index_document, delete_document_chunks, retrieve_relevant_chunks, get_file_chunks

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
    relevant_chunks: List[str],
    conversation_history: List[dict],
    use_rag: bool = True,
) -> List[dict]:
    if use_rag and relevant_chunks:
        system_prompt = """你是一个基于知识库的智能聊天机器人。请根据提供的知识库片段来回答用户的问题。

规则：
1. 如果知识库中有相关信息，请基于知识库内容进行回答，并在回答中引用相关片段。
2. 如果知识库中没有相关信息，请如实告知用户，并尝试用你的通用知识提供帮助，但要说明这些信息并非来自知识库。
3. 回答要专业、准确、简洁。
4. 如果用户的问题与知识库无关的闲聊，可以用友好的方式回应。"""

        context_text = "【知识库相关片段】\n\n"
        for i, chunk in enumerate(relevant_chunks, 1):
            context_text += f"[片段{i}]\n{chunk}\n\n"

        user_message = f"{context_text}【用户问题】\n{user_query}"
    else:
        system_prompt = """你是一个友好的智能聊天机器人。请用你的知识来回答用户的问题。

规则：
1. 回答要专业、准确、简洁。
2. 如果不知道答案，请如实告知用户。
3. 可以进行友好的闲聊。"""

        user_message = user_query

    messages = [{"role": "system", "content": system_prompt}]

    if conversation_history:
        messages.extend(conversation_history)

    messages.append({"role": "user", "content": user_message})

    return messages
