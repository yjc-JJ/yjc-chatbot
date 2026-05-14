"""
嵌入服务：调用阿里云 text-embedding-v3 模型
通过 OpenAI 兼容接口
"""
import asyncio
import logging
import os
from typing import List
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("embedding")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")

embedding_client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=EMBEDDING_BASE_URL,
    timeout=60.0,
)

MAX_BATCH_SIZE = 10


def _sync_get_embedding(text: str) -> List[float]:
    response = embedding_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
        encoding_format="float",
    )
    return response.data[0].embedding


async def get_embedding(text: str) -> List[float]:
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _sync_get_embedding, text)
    except Exception as e:
        logger.error(f"获取嵌入向量失败: {e}")
        raise


def _sync_get_embeddings(texts: List[str]) -> List[List[float]]:
    response = embedding_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=texts,
        encoding_format="float",
    )
    return [item.embedding for item in response.data]


async def get_embeddings(texts: List[str]) -> List[List[float]]:
    all_embeddings = []
    loop = asyncio.get_running_loop()

    for i in range(0, len(texts), MAX_BATCH_SIZE):
        batch = texts[i:i + MAX_BATCH_SIZE]
        logger.info(f"正在获取嵌入向量: 批次 {i // MAX_BATCH_SIZE + 1}, 共 {len(batch)} 条文本")
        try:
            embeddings = await loop.run_in_executor(None, _sync_get_embeddings, batch)
            all_embeddings.extend(embeddings)
            logger.info(f"嵌入向量获取成功: 批次 {i // MAX_BATCH_SIZE + 1}")
        except Exception as e:
            logger.error(f"获取嵌入向量失败 (批次 {i // MAX_BATCH_SIZE + 1}): {e}")
            raise

    return all_embeddings
