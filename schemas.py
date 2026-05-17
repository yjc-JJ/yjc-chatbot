"""
Pydantic 请求/响应模型
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, List
from datetime import datetime
import re


class UserRegister(BaseModel):
    email: str = Field(..., min_length=1, max_length=255)
    password: str = Field(..., min_length=4, max_length=128)


class UserLogin(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: int
    email: str
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    is_admin: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChangePassword(BaseModel):
    old_password: str
    new_password: str = Field(..., min_length=4, max_length=128)


class AdminChangePassword(BaseModel):
    new_password: str = Field(..., min_length=4, max_length=128)


class UpdateUsername(BaseModel):
    username: str = Field(..., min_length=2, max_length=20)

    @field_validator('username')
    def validate_username(cls, v):
        if not re.match(r'^[\u4e00-\u9fa5a-zA-Z0-9]{2,20}$', v):
            raise ValueError('用户名只能包含中文、英文和数字，长度2-20个字符')
        return v


class AvatarUploadResponse(BaseModel):
    message: str
    avatar_url: str


class OperationLogResponse(BaseModel):
    id: int
    operation_type: str
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    before_value: Optional[str] = None
    after_value: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationCreate(BaseModel):
    title: Optional[str] = "新对话"


class ConversationResponse(BaseModel):
    id: int
    title: str
    user_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MessageResponse(BaseModel):
    id: int
    role: str
    content: str
    emotion: Optional[str] = None
    confidence: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


class JWAccountRequest(BaseModel):
    jw_account: str = Field(..., min_length=1, max_length=50)
    jw_password: str = Field(..., min_length=1, max_length=128)


class JWAccountResponse(BaseModel):
    jw_account: Optional[str] = None
    message: str


class ChatRequest(BaseModel):
    message: str
    use_rag: Optional[bool] = True
    use_search: Optional[bool] = False


class KnowledgeFileResponse(BaseModel):
    id: int
    user_id: int
    filename: str
    original_filename: str
    name: Optional[str] = None
    file_size: int
    chunk_count: int
    is_shared: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class UpdateKnowledgeName(BaseModel):
    name: str = Field(..., min_length=2, max_length=50)


class KnowledgeShareResponse(BaseModel):
    id: int
    knowledge_file_id: int
    name: str
    original_filename: str
    user_id: int
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SharedKnowledgeResponse(BaseModel):
    id: int
    knowledge_file_id: int
    knowledge_name: str
    original_filename: str
    shared_user_id: int
    shared_username: Optional[str] = None
    shared_avatar_url: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ShareKnowledgeRequest(BaseModel):
    knowledge_file_id: int


class SearchSharedKnowledgeRequest(BaseModel):
    keyword: Optional[str] = None
    page: int = 1
    page_size: int = 20