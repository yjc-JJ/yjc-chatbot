"""
DeepSeek 大模型客户端：流式对话生成
通过 OpenAI 兼容接口调用 DeepSeek-v4-pro
"""
import os
from typing import AsyncGenerator, List, Dict
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

deepseek_client = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=LLM_BASE_URL,
)


async def stream_chat(
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 2048,
) -> AsyncGenerator[str, None]:
    response = await deepseek_client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    async for chunk in response:
        if chunk.choices and len(chunk.choices) > 0:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content
