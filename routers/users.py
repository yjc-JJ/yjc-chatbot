"""
用户相关路由：注册、登录、个人信息、修改密码、头像上传、用户名修改、操作日志
"""
import os
import io
import uuid
import re
import glob
import logging

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from PIL import Image

from database import get_db
from models import User, OperationLog
from schemas import (
    UserRegister, UserLogin, UserResponse, ChangePassword, TokenResponse,
    UpdateUsername, AvatarUploadResponse, OperationLogResponse,
    JWAccountRequest, JWAccountResponse
)
from auth import hash_password, verify_password, create_access_token, get_current_user

router = APIRouter(prefix="/api", tags=["users"])

AVATAR_DIR = "static/avatars"
MAX_AVATAR_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

os.makedirs(AVATAR_DIR, exist_ok=True)


async def add_operation_log(
    db: AsyncSession,
    user_id: int,
    operation_type: str,
    target_type: str = None,
    target_id: int = None,
    before_value: str = None,
    after_value: str = None,
):
    log = OperationLog(
        user_id=user_id,
        operation_type=operation_type,
        target_type=target_type,
        target_id=target_id,
        before_value=before_value,
        after_value=after_value,
    )
    db.add(log)
    await db.commit()


@router.post("/register", response_model=UserResponse)
async def register(data: UserRegister, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该邮箱已被注册",
        )
    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        is_admin=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await add_operation_log(
        db=db,
        user_id=user.id,
        operation_type="register",
        target_type="user",
        target_id=user.id,
        after_value=f"email={user.email}",
    )
    return user


@router.post("/token", response_model=TokenResponse)
async def login(data: UserLogin, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )
    access_token = create_access_token(data={"user_id": user.id})
    return TokenResponse(
        access_token=access_token,
        user=UserResponse.model_validate(user),
    )


@router.get("/users/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/users/me/password")
async def change_password(
    data: ChangePassword,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(data.old_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="原密码错误",
        )
    current_user.hashed_password = hash_password(data.new_password)
    await db.commit()
    await add_operation_log(
        db=db,
        user_id=current_user.id,
        operation_type="update_password",
        target_type="user",
        target_id=current_user.id,
        before_value="******",
        after_value="******",
    )
    return {"message": "密码修改成功"}


@router.put("/users/me/username", response_model=UserResponse)
async def update_username(
    data: UpdateUsername,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not re.match(r'^[\u4e00-\u9fa5a-zA-Z0-9]{2,20}$', data.username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名只能包含中文、英文和数字，长度2-20个字符",
        )
    
    before_value = current_user.username or "未设置"
    current_user.username = data.username
    await db.commit()
    await db.refresh(current_user)
    
    await add_operation_log(
        db=db,
        user_id=current_user.id,
        operation_type="update_username",
        target_type="user",
        target_id=current_user.id,
        before_value=before_value,
        after_value=data.username,
    )
    return current_user


@router.post("/users/me/avatar", response_model=AvatarUploadResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    filename = file.filename or ""
    
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请选择要上传的图片文件",
        )
    
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的图片格式，仅支持 JPG、PNG、WEBP 格式",
        )
    
    if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"文件MIME类型不正确，请上传有效的图片文件",
        )
    
    content_bytes = await file.read()
    file_size = len(content_bytes)
    
    if file_size == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="上传的文件为空",
        )
    
    if file_size > MAX_AVATAR_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="头像文件大小不能超过10MB",
        )
    
    try:
        image = Image.open(io.BytesIO(content_bytes))
        image.verify()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的图片文件: {str(e)}",
        )
    
    try:
        image = Image.open(io.BytesIO(content_bytes))
        image_format = image.format
        if image_format not in {"JPEG", "PNG", "WEBP"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不支持的图片格式，检测到格式: {image_format}",
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"图片格式检测失败: {str(e)}",
        )
    
    old_avatar_url = current_user.avatar_url
    avatar_base = str(uuid.uuid4())
    
    sizes = {
        "original": None,
        "large": (200, 200),
        "medium": (100, 100),
        "small": (50, 50),
    }
    
    if old_avatar_url:
        try:
            old_filename = old_avatar_url.split('/')[-1]
            old_avatar_base = old_filename.replace('_original', '').rsplit('.', 1)[0]
            print(f"[头像清理] 旧头像URL: {old_avatar_url}, 提取base: {old_avatar_base}")
            deleted_count = 0
            for size_name in sizes.keys():
                old_path_pattern = os.path.join(AVATAR_DIR, f"{old_avatar_base}_{size_name}.*")
                for old_file in glob.glob(old_path_pattern):
                    try:
                        os.remove(old_file)
                        deleted_count += 1
                        print(f"[头像清理] 已删除: {old_file}")
                    except Exception as e:
                        print(f"[头像清理] 删除失败: {old_file}, 错误: {e}")
                        logger.warning(f"删除旧头像文件失败: {old_file}, 错误: {str(e)}")
            print(f"[头像清理] 共删除 {deleted_count} 个旧头像文件")
        except Exception as e:
            print(f"[头像清理] 清理过程出错: {e}")
            logger.warning(f"清理旧头像文件时发生错误: {str(e)}")
    
    for size_name, size in sizes.items():
        img = image.copy()
        if size:
            img.thumbnail(size, Image.Resampling.LANCZOS)
        size_path = os.path.join(AVATAR_DIR, f"{avatar_base}_{size_name}{ext}")
        img.save(size_path, quality=95)
    
    before_value = current_user.avatar_url or "未设置"
    avatar_url = f"/{AVATAR_DIR.replace(os.sep, '/')}/{avatar_base}_original{ext}"
    current_user.avatar_url = avatar_url
    
    try:
        await db.commit()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"数据库更新失败: {str(e)}",
        )
    
    await add_operation_log(
        db=db,
        user_id=current_user.id,
        operation_type="update_avatar",
        target_type="user",
        target_id=current_user.id,
        before_value=before_value,
        after_value=avatar_url,
    )
    
    return {"message": "头像上传成功", "avatar_url": avatar_url}


@router.get("/users/me/avatar")
async def get_my_avatar(
    current_user: User = Depends(get_current_user),
):
    return {"avatar_url": current_user.avatar_url}


@router.get("/users/{user_id}/avatar")
async def get_user_avatar(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问",
        )
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )
    
    return {"avatar_url": user.avatar_url}


@router.get("/users/me/logs", response_model=list[OperationLogResponse])
async def get_operation_logs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(OperationLog)
        .where(OperationLog.user_id == current_user.id)
        .order_by(OperationLog.created_at.desc())
    )
    return result.scalars().all()


@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问",
        )
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )
    return user


# 简单的可逆加密函数（用于存储教务系统密码）
def _simple_encrypt(text: str, key: str = "chatbot_jw_key") -> str:
    """简单的XOR加密，用于存储教务系统密码"""
    result = []
    for i, char in enumerate(text):
        result.append(chr(ord(char) ^ ord(key[i % len(key)])))
    return ''.join(result)

def _simple_decrypt(text: str, key: str = "chatbot_jw_key") -> str:
    """简单的XOR解密"""
    return _simple_encrypt(text, key)


# 教务系统账号密码管理
@router.put("/users/me/jwaccount", response_model=JWAccountResponse)
async def update_jw_account(
    data: JWAccountRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    保存或修改教务系统账号密码
    
    Args:
        data: 包含教务系统账号(jw_account)和密码(jw_password)
        
    Returns:
        更新结果
    """
    # 验证账号格式（通常为学号）
    if not data.jw_account.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="教务系统账号不能为空",
        )
    
    if not data.jw_password.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="教务系统密码不能为空",
        )
    
    # 记录修改前的值
    before_account = current_user.jw_account or "未设置"
    
    # 更新教务系统账号密码（密码使用可逆加密存储）
    current_user.jw_account = data.jw_account.strip()
    current_user.jw_password = _simple_encrypt(data.jw_password.strip())
    
    await db.commit()
    await db.refresh(current_user)
    
    await add_operation_log(
        db=db,
        user_id=current_user.id,
        operation_type="update_jw_account",
        target_type="user",
        target_id=current_user.id,
        before_value=f"jw_account={before_account}, jw_password=******",
        after_value=f"jw_account={current_user.jw_account}, jw_password=******",
    )
    
    return JWAccountResponse(
        jw_account=current_user.jw_account,
        message="教务系统账号密码保存成功"
    )


@router.get("/users/me/jwaccount", response_model=JWAccountResponse)
async def get_jw_account(
    current_user: User = Depends(get_current_user),
):
    """
    获取当前用户的教务系统账号信息（不返回密码）
    
    Returns:
        教务系统账号（仅账号，不含密码）
    """
    return JWAccountResponse(
        jw_account=current_user.jw_account,
        message="获取成功"
    )


@router.delete("/users/me/jwaccount")
async def delete_jw_account(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    删除保存的教务系统账号密码
    
    Returns:
        删除结果
    """
    before_account = current_user.jw_account or "未设置"
    
    current_user.jw_account = None
    current_user.jw_password = None
    
    await db.commit()
    
    await add_operation_log(
        db=db,
        user_id=current_user.id,
        operation_type="delete_jw_account",
        target_type="user",
        target_id=current_user.id,
        before_value=f"jw_account={before_account}, jw_password=******",
        after_value="jw_account=None, jw_password=None",
    )
    
    return {"message": "教务系统账号密码已删除"}