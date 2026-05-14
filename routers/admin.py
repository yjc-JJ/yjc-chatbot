"""
管理员路由：用户管理、知识库管理
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from database import get_db
from models import User, KnowledgeFile
from schemas import UserResponse, KnowledgeFileResponse, AdminChangePassword
from auth import hash_password, get_admin_user
from services.rag_service import delete_user_collection as delete_chroma_collection

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.put("/users/{user_id}/password")
async def admin_change_password(
    user_id: int,
    data: AdminChangePassword,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.hashed_password = hash_password(data.new_password)
    await db.commit()
    return {"message": f"用户 {user.email} 的密码已修改"}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己的管理员账号")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    await delete_chroma_collection(user_id)

    await db.delete(user)
    await db.commit()
    return {"message": f"用户 {user.email} 及其所有数据已删除"}


@router.get("/knowledge/files", response_model=list[KnowledgeFileResponse])
async def admin_list_knowledge_files(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(KnowledgeFile).order_by(KnowledgeFile.created_at.desc())
    )
    return result.scalars().all()
