"""
搜索API路由：提供联网搜索功能
参考文档：https://cloud.baidu.com/doc/qianfan/s/2mh4su4uy
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from database import get_db
from auth import get_current_user
from models import User
from services.search_service import search, clear_cache, get_search_stats

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/web")
async def web_search(
    query: str = Query(..., description="搜索查询词"),
    max_results: int = Query(20, description="最大返回结果数", ge=1, le=50),
    use_cache: bool = Query(True, description="是否使用缓存"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    执行联网搜索（百度千帆AI搜索 v2，Bearer API Key 鉴权）
    
    Args:
        query: 搜索查询词
        max_results: 最大返回结果数（1-50，默认20）
        use_cache: 是否使用缓存
    
    Returns:
        搜索结果字典
    """
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="搜索查询词不能为空")
    
    try:
        result = await search(db, query.strip(), max_results, use_cache)
        
        # 如果搜索失败，返回相应的HTTP状态码
        if not result.get('success'):
            error_type = result.get('error_type', 'unknown_error')
            status_code = {
                'config_error': 503,
                'auth_error': 401,
                'network_error': 503,
                'timeout_error': 504,
            }.get(error_type, 500)
            raise HTTPException(status_code=status_code, detail=result.get('error', '搜索失败'))
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")


@router.get("/status")
async def get_search_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取搜索功能状态和统计信息
    
    Returns:
        搜索功能状态信息，包含缓存统计
    """
    stats = await get_search_stats(db)
    
    return {
        "enabled": True,
        "engine": "百度千帆AI搜索 v2",
        "description": "联网搜索已启用（百度千帆AI搜索 v2，Bearer鉴权，仅需API Key）",
        "api_configured": stats.get('api_configured', False),
        "cache_stats": {
            "total_cached_queries": stats.get('total_cached_queries', 0),
            "cache_expire_minutes": stats.get('cache_expire_minutes', 30),
            "average_cache_age_minutes": stats.get('average_cache_age_minutes', 0)
        }
    }


@router.delete("/cache")
async def delete_search_cache(
    query: Optional[str] = Query(None, description="要清除的查询词（不指定则清除全部）"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    清除搜索缓存
    
    Args:
        query: 指定查询词（可选，不指定则清除全部缓存）
    
    Returns:
        清除结果
    """
    await clear_cache(db, query)
    
    if query:
        return {"message": f"已清除查询 '{query}' 的缓存"}
    else:
        return {"message": "已清除所有搜索缓存"}
