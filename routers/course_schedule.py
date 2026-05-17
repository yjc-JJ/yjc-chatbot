"""
课程表API路由：提供课表查询接口
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import date, timedelta

from database import get_db
from auth import get_current_user
from models import User
from services.course_schedule_service import get_today_schedule, get_schedule_by_date

router = APIRouter(prefix="/api/schedule", tags=["schedule"])

# 简单的可逆加密/解密函数（与users.py中保持一致）
def _simple_decrypt(text: str, key: str = "chatbot_jw_key") -> str:
    """简单的XOR解密"""
    result = []
    for i, char in enumerate(text):
        result.append(chr(ord(char) ^ ord(key[i % len(key)])))
    return ''.join(result)


@router.get("/today")
async def get_today_class_schedule(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取今日课表
    
    优先使用用户保存的教务系统账号密码，如果未保存则使用默认配置
    
    Returns:
        今日课表信息，包含日期、星期和课程列表
    """
    try:
        # 获取用户保存的教务系统账号密码
        jw_account = current_user.jw_account
        jw_password_encrypted = current_user.jw_password
        
        username = None
        password = None
        
        # 如果用户已保存教务系统账号密码，解密后使用
        if jw_account and jw_password_encrypted:
            try:
                username = jw_account
                password = _simple_decrypt(jw_password_encrypted)
                logger = __import__("logging").getLogger("schedule")
                logger.info(f"用户 {current_user.email} 使用保存的教务账号: {username}")
            except Exception as e:
                logger = __import__("logging").getLogger("schedule")
                logger.error(f"解密教务密码失败: {e}")
        
        # 调用课表服务（使用用户保存的账号密码或默认配置）
        result = await get_today_schedule(username=username, password=password)
        
        if not result.get("success"):
            error_type = result.get("error_type")
            error_msg = result.get("error", "获取课表失败")
            
            # 如果是密码错误，给出明确提示
            if error_type == "password_error":
                raise HTTPException(
                    status_code=401, 
                    detail="密码错误，请在个人资料中更新您的教务系统账号密码"
                )
            
            raise HTTPException(status_code=500, detail=error_msg)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取今日课表失败: {str(e)}")


@router.post("/today")
async def get_today_class_schedule_with_credentials(
    credentials: dict,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    使用提供的账号密码获取今日课表
    
    Args:
        credentials: 包含 jw_account 和 jw_password 的字典
        
    Returns:
        今日课表信息，包含日期、星期和课程列表
    """
    try:
        jw_account = credentials.get("jw_account")
        jw_password = credentials.get("jw_password")
        
        if not jw_account or not jw_password:
            raise HTTPException(status_code=400, detail="请提供教务系统账号和密码")
        
        # 调用课表服务
        result = await get_today_schedule(username=jw_account, password=jw_password)
        
        if not result.get("success"):
            error_type = result.get("error_type")
            error_msg = result.get("error", "获取课表失败")
            
            # 如果是密码错误，给出明确提示
            if error_type == "password_error":
                raise HTTPException(
                    status_code=401, 
                    detail="密码错误，请检查您的教务系统账号密码"
                )
            
            raise HTTPException(status_code=500, detail=error_msg)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取今日课表失败: {str(e)}")


@router.get("/date/{target_date}")
async def get_class_schedule_by_date(
    target_date: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取指定日期的课表
    
    Args:
        target_date: 查询日期，格式YYYY-MM-DD
        
    Returns:
        指定日期的课表信息
    """
    try:
        result = await get_schedule_by_date(target_date)
        
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "查询失败"))
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取课表失败: {str(e)}")


@router.get("/week")
async def get_week_schedule(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取本周课表
    
    Returns:
        本周每天的课表信息
    """
    try:
        today = date.today()
        # 获取本周一
        monday = today - timedelta(days=today.weekday())
        
        week_schedule = []
        for i in range(7):
            target_date = (monday + timedelta(days=i)).strftime("%Y-%m-%d")
            result = await get_schedule_by_date(target_date)
            week_schedule.append(result)
        
        return {
            "success": True,
            "week_start": monday.strftime("%Y-%m-%d"),
            "week_end": (monday + timedelta(days=6)).strftime("%Y-%m-%d"),
            "schedule": week_schedule
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取本周课表失败: {str(e)}")