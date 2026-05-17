"""
向量存储服务：使用 SQLite 直接存储向量数据
作为 ChromaDB 的替代方案，避免 ChromaDB 崩溃问题
"""
import asyncio
import logging
import os
import sqlite3
import threading
from typing import List, Tuple

logger = logging.getLogger("vector_store")

VECTOR_DB_PATH = os.getenv("VECTOR_DB_PATH", "./vector_data.db")

_db_lock = threading.Lock()


def _init_db():
    with _db_lock:
        conn = sqlite3.connect(VECTOR_DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vectors (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding BLOB NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_vectors_user_id ON vectors(user_id)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_vectors_filename ON vectors(filename)
        ''')
        conn.commit()
        conn.close()


def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = sum(a * a for a in vec1) ** 0.5
    norm2 = sum(b * b for b in vec2) ** 0.5
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot_product / (norm1 * norm2)


def _serialize_embedding(embedding: List[float]) -> bytes:
    import struct
    return struct.pack(f'{len(embedding)}f', *embedding)


def _deserialize_embedding(data: bytes) -> List[float]:
    import struct
    count = len(data) // 4
    return list(struct.unpack(f'{count}f', data))


async def index_document(
    user_id: int,
    filename: str,
    content: str,
    chunks: List[str],
    embeddings: List[List[float]],
) -> Tuple[int, List[str]]:
    logger.info(f"开始索引文档: user_id={user_id}, filename={filename}")

    def _index():
        _init_db()
        with _db_lock:
            conn = sqlite3.connect(VECTOR_DB_PATH)
            cursor = conn.cursor()
            
            cursor.execute(
                'DELETE FROM vectors WHERE user_id = ? AND filename = ?',
                (user_id, filename)
            )
            
            chunk_ids = []
            for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
                chunk_id = f"{filename}_chunk_{i}"
                chunk_ids.append(chunk_id)
                cursor.execute(
                    '''
                    INSERT INTO vectors (id, user_id, filename, chunk_index, content, embedding)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    (chunk_id, user_id, filename, i, chunk, _serialize_embedding(embedding))
                )
            
            conn.commit()
            conn.close()
            return len(chunk_ids)

    loop = asyncio.get_running_loop()
    count = await loop.run_in_executor(None, _index)
    logger.info(f"文档索引完成: {filename}, {count} 个块")
    return count, chunks


async def delete_document_chunks(user_id: int, filename: str):
    def _delete():
        with _db_lock:
            conn = sqlite3.connect(VECTOR_DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM vectors WHERE user_id = ? AND filename = ?',
                (user_id, filename)
            )
            conn.commit()
            conn.close()

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _delete)


async def retrieve_relevant_chunks(
    user_id: int,
    query_embedding: List[float],
    top_k: int = 5,
) -> List[str]:
    def _retrieve():
        with _db_lock:
            conn = sqlite3.connect(VECTOR_DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                'SELECT content, embedding FROM vectors WHERE user_id = ?',
                (user_id,)
            )
            
            results = []
            for content, embedding_data in cursor.fetchall():
                embedding = _deserialize_embedding(embedding_data)
                similarity = _cosine_similarity(query_embedding, embedding)
                results.append((similarity, content))
            
            conn.close()
            
            results.sort(key=lambda x: x[0], reverse=True)
            return [r[1] for r in results[:top_k]]

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _retrieve)


async def get_file_chunks(user_id: int, filename: str) -> list:
    def _get_chunks():
        with _db_lock:
            conn = sqlite3.connect(VECTOR_DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, content, chunk_index FROM vectors WHERE user_id = ? AND filename = ? ORDER BY chunk_index',
                (user_id, filename)
            )
            
            chunks = []
            for chunk_id, content, chunk_index in cursor.fetchall():
                chunks.append({
                    "chunk_id": chunk_id,
                    "filename": filename,
                    "content": content,
                    "index": chunk_index,
                })
            
            conn.close()
            return chunks

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _get_chunks)


async def get_all_user_chunks(user_id: int) -> List[dict]:
    def _get_chunks():
        with _db_lock:
            conn = sqlite3.connect(VECTOR_DB_PATH)
            cursor = conn.cursor()
            cursor.execute(
                'SELECT id, filename, content, chunk_index FROM vectors WHERE user_id = ? ORDER BY filename, chunk_index',
                (user_id,)
            )

            chunks = []
            for chunk_id, filename, content, chunk_index in cursor.fetchall():
                chunks.append({
                    "chunk_id": chunk_id,
                    "filename": filename,
                    "content": content,
                    "index": chunk_index,
                })

            conn.close()
            return chunks

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _get_chunks)