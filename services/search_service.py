"""
联网搜索服务：集成百度千帆AI搜索 v2
参考文档：https://cloud.baidu.com/doc/qianfan/s/2mh4su4uy

鉴权方式：Bearer <API Key>（直接使用API Key，无需Secret Key）
"""
import json
import logging
import os
import httpx
from typing import List, Dict, Optional, Any
from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import SearchCache

logger = logging.getLogger("search")

# 缓存过期时间（分钟）
CACHE_EXPIRE_MINUTES = 30

# 百度千帆AI搜索API配置 - 只需API Key
BAIDU_API_KEY = os.getenv("BAIDU_API_KEY", "")

# 百度千帆AI搜索 v2 端点
BAIDU_SEARCH_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"

# 搜索源
SEARCH_SOURCE = "baidu_search_v2"


async def search_with_baidu(query: str, max_results: int = 20) -> Dict[str, Any]:
    """
    使用百度千帆AI搜索 v2 进行联网搜索
    
    Args:
        query: 搜索查询词
        max_results: 最大返回结果数（默认20）
        
    Returns:
        搜索结果字典，包含results列表和metadata
    """
    # 检查API配置
    if not BAIDU_API_KEY:
        logger.error("百度API Key未配置")
        return {
            'success': False,
            'query': query,
            'error': '搜索服务未配置',
            'error_type': 'config_error',
            'suggestion': '请在.env文件中配置BAIDU_API_KEY'
        }

    try:
        logger.info(f"发起百度AI搜索请求: {query}")

        request_body = {
            "messages": [
                {
                    "content": query,
                    "role": "user"
                }
            ],
            "search_source": SEARCH_SOURCE,
            "resource_type_filter": [
                {
                    "type": "web",
                    "top_k": max_results
                }
            ],
            "search_recency_filter": "year"
        }

        async with httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5)
        ) as client:
            response = await client.post(
                BAIDU_SEARCH_URL,
                json=request_body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {BAIDU_API_KEY}"
                }
            )
            response.raise_for_status()
            data = response.json()

        # 解析百度API响应
        return _parse_baidu_response(data, query)

    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code
        logger.error(f"百度搜索HTTP错误: {query}, 状态码: {status_code}")

        try:
            error_body = e.response.json()
            error_msg = error_body.get('error_msg', str(error_body))
        except Exception:
            error_msg = f"HTTP错误 {status_code}"

        if status_code == 401:
            return {
                'success': False,
                'query': query,
                'error': 'API Key无效或已过期',
                'error_type': 'auth_error',
                'suggestion': '请检查.env中的BAIDU_API_KEY是否正确'
            }
        elif status_code == 429:
            return {
                'success': False,
                'query': query,
                'error': 'API调用频率超限',
                'error_type': 'rate_limit_error',
                'suggestion': '请稍后重试'
            }
        else:
            return {
                'success': False,
                'query': query,
                'error': error_msg,
                'error_type': 'http_error',
                'status_code': status_code
            }

    except httpx.ConnectError:
        logger.error(f"百度搜索连接失败: {query}")
        return {
            'success': False,
            'query': query,
            'error': '网络连接异常，无法访问搜索引擎',
            'error_type': 'network_error',
            'suggestion': '请检查网络连接后重试'
        }
    except httpx.TimeoutException:
        logger.error(f"百度搜索超时: {query}")
        return {
            'success': False,
            'query': query,
            'error': '搜索请求超时',
            'error_type': 'timeout_error',
            'suggestion': '请稍后重试或缩短查询词'
        }
    except json.JSONDecodeError:
        logger.error(f"百度搜索响应解析失败: {query}")
        return {
            'success': False,
            'query': query,
            'error': '搜索响应解析失败',
            'error_type': 'parse_error'
        }
    except Exception as e:
        logger.error(f"百度搜索发生错误: {query}, 错误: {e}", exc_info=True)
        return {
            'success': False,
            'query': query,
            'error': f'搜索失败: {str(e)}',
            'error_type': 'unknown_error'
        }


def _parse_baidu_response(data: Dict, query: str) -> Dict[str, Any]:
    """
    解析百度千帆AI搜索 v2 响应
    
    实际响应结构：
    {
        "request_id": "...",
        "references": [
            {
                "id": 1,
                "url": "...",
                "title": "...",
                "date": "2026-05-14 19:55:09",
                "content": "...",
                "snippet": "...",
                "website": "网易",
                "rerank_score": 1,
                "authority_score": 0.5,
                "type": "web"
            }
        ]
    }
    """
    # 检查API层错误（code字段可选，不存在时表示成功）
    if 'code' in data and data['code'] != 0:
        error_msg = data.get('msg', data.get('error_msg', '未知错误'))
        error_code = data.get('code', -1)
        logger.error(f"百度API返回错误[code={error_code}]: {error_msg}")
        return {
            'success': False,
            'query': query,
            'error': error_msg,
            'error_type': 'api_error',
            'error_code': error_code,
            'suggestion': '搜索服务暂时不可用，请稍后重试'
        }

    # 提取搜索结果 - 新API使用 references 字段
    references = data.get('references', [])

    if not references:
        logger.info(f"百度搜索无结果: {query}")
        return {
            'success': True,
            'query': query,
            'results': [],
            'total_results': 0,
            'search_time': datetime.utcnow().isoformat(),
            'message': '未找到相关结果，请尝试更换搜索词'
        }

    formatted_results = []

    for idx, item in enumerate(references):
        title = (item.get('title') or '').strip()
        url = item.get('url', '')
        content = (item.get('content') or '').strip()
        snippet = (item.get('snippet') or '').strip()
        website = item.get('website', '')
        rerank_score = item.get('rerank_score', 0)
        authority_score = item.get('authority_score', 0)

        if not title:
            title = f'搜索结果 {idx + 1}'

        text = snippet or content or ''
        if len(text) > 500:
            text = text[:500]

        formatted_results.append({
            'title': title,
            'url': url,
            'snippet': text,
            'source': website or '百度搜索',
            'relevance': rerank_score,
            'type': 'web',
            'site_name': website,
            'date': item.get('date', '')
        })

    # 按重排分数排序
    formatted_results.sort(key=lambda x: x.get('relevance', 0), reverse=True)

    logger.info(f"百度搜索完成: {len(formatted_results)} 条结果")
    return {
        'success': True,
        'query': query,
        'results': formatted_results,
        'total_results': len(formatted_results),
        'search_time': datetime.utcnow().isoformat(),
        'source': '百度千帆AI搜索'
    }


async def get_cached_search(db: AsyncSession, query: str) -> Optional[Dict]:
    """
    从缓存中获取搜索结果
    
    Args:
        db: 数据库会话
        query: 搜索查询词
        
    Returns:
        缓存的搜索结果，如果不存在或已过期则返回None
    """
    try:
        result = await db.execute(
            select(SearchCache).where(SearchCache.query == query)
        )
        cache = result.scalar_one_or_none()

        if cache:
            # 检查缓存是否过期
            if cache.created_at + timedelta(minutes=CACHE_EXPIRE_MINUTES) > datetime.utcnow():
                try:
                    data = json.loads(cache.result)
                    data['cached'] = True
                    data['cache_age'] = max(0, int((datetime.utcnow() - cache.created_at).total_seconds() / 60))
                    return data
                except json.JSONDecodeError:
                    logger.error(f"缓存数据解析失败: {query}")
            else:
                logger.debug(f"缓存已过期: {query}")

        return None
    except Exception as e:
        logger.error(f"获取缓存失败: {query}, 错误: {e}")
        return None


async def save_search_cache(db: AsyncSession, query: str, result: Dict):
    """
    将搜索结果保存到缓存
    
    Args:
        db: 数据库会话
        query: 搜索查询词
        result: 搜索结果
    """
    try:
        result_to_save = result.copy()
        result_to_save.pop('cached', None)
        result_to_save.pop('cache_age', None)

        existing_result = await db.execute(
            select(SearchCache).where(SearchCache.query == query)
        )
        existing_cache = existing_result.scalar_one_or_none()

        if existing_cache:
            existing_cache.result = json.dumps(result_to_save)
            existing_cache.created_at = datetime.utcnow()
        else:
            new_cache = SearchCache(
                query=query,
                result=json.dumps(result_to_save)
            )
            db.add(new_cache)

        await db.commit()
        logger.debug(f"搜索结果已缓存: {query}")
    except Exception as e:
        logger.error(f"保存缓存失败: {query}, 错误: {e}")


async def search(db: AsyncSession, query: str, max_results: int = 20, use_cache: bool = True) -> Dict[str, Any]:
    """
    执行搜索，优先使用缓存
    
    Args:
        db: 数据库会话
        query: 搜索查询词
        max_results: 最大返回结果数（默认20）
        use_cache: 是否使用缓存
        
    Returns:
        搜索结果字典
    """
    # 参数验证
    if not query or not query.strip():
        return {
            'success': False,
            'query': query,
            'error': '搜索查询词不能为空',
            'error_type': 'validation_error'
        }

    query = query.strip()

    # 首先尝试从缓存获取
    if use_cache:
        cached_result = await get_cached_search(db, query)
        if cached_result:
            logger.info(f"使用缓存结果: {query}")
            return cached_result

    # 如果缓存未命中或不使用缓存，执行实际搜索
    result = await search_with_baidu(query, max_results)

    # 如果搜索成功，保存到缓存
    if result.get('success') and use_cache:
        await save_search_cache(db, query, result)

    return result


async def clear_cache(db: AsyncSession, query: Optional[str] = None):
    """
    清除搜索缓存
    
    Args:
        db: 数据库会话
        query: 指定查询词（可选，不指定则清除全部）
    """
    try:
        if query:
            result = await db.execute(
                select(SearchCache).where(SearchCache.query == query)
            )
            cache = result.scalar_one_or_none()
            if cache:
                await db.delete(cache)
                logger.info(f"清除缓存: {query}")
        else:
            await db.execute(SearchCache.__table__.delete())
            logger.info("清除所有缓存")

        await db.commit()
    except Exception as e:
        logger.error(f"清除缓存失败: {e}", exc_info=True)


async def get_search_stats(db: AsyncSession) -> Dict[str, Any]:
    """
    获取搜索统计信息
    
    Returns:
        统计信息字典
    """
    try:
        result = await db.execute(select(SearchCache))
        caches = result.scalars().all()

        total_cached = len(caches)
        total_size = sum(len(cache.result) for cache in caches)
        avg_age = 0
        if total_cached > 0:
            avg_age = int(sum(
                (datetime.utcnow() - cache.created_at).total_seconds()
                for cache in caches
            ) / total_cached / 60)

        return {
            'total_cached_queries': total_cached,
            'total_cache_size_bytes': total_size,
            'average_cache_age_minutes': avg_age,
            'cache_expire_minutes': CACHE_EXPIRE_MINUTES,
            'api_configured': bool(BAIDU_API_KEY)
        }
    except Exception as e:
        logger.error(f"获取搜索统计失败: {e}", exc_info=True)
        return {'error': str(e)}
