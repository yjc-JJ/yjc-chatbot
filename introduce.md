# AI 智能助手系统项目介绍

## 1. 系统架构

### 1.1 整体架构概述

本项目是一个基于 **FastAPI** 构建的 AI 智能助手系统，采用典型的三层架构设计：表示层、业务逻辑层和数据访问层。系统集成了大语言模型（LLM）和检索增强生成（RAG）技术，为用户提供智能对话服务。

### 1.2 架构层次图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          表示层 (Presentation Layer)                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │  Login Page  │  │  Chat Page   │  │ Knowledge Mgmt│  │ Admin Page │ │
│  │  Register    │  │  Conversation│  │  Document    │  │ User Mgmt  │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘ │
│         │                 │                  │                 │       │
└─────────┼─────────────────┼──────────────────┼─────────────────┼───────┘
          ▼                 ▼                  ▼                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          业务逻辑层 (Application Layer)                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │   Auth API   │  │  Chat API    │  │ Knowledge API│  │ Admin API  │ │
│  │   Users API  │  │Conversation  │  │  Vector Store│  │ Sys Config │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘ │
│         │                 │                  │                 │       │
│         └─────────────────┼──────────────────┴─────────────────┘       │
│                           ▼                                            │
│                 ┌──────────────────┐                                   │
│                 │   RAG Service    │                                   │
│                 │ (LLM + Embedding)│                                   │
│                 └────────┬─────────┘                                   │
└──────────────────────────┼──────────────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          数据访问层 (Data Layer)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │   SQLite     │  │  Vector DB   │  │   Files      │  │  Logs      │ │
│  │  (app.db)    │  │  (Chroma)    │  │ (avatars/)   │  │ (logs/)    │ │
│  └──────────────┘  └──────────────┘  └──────────────┘  └────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.3 核心组件交互关系

| 组件 | 职责 | 关键文件 |
|------|------|----------|
| **认证模块** | 用户注册、登录、JWT令牌管理 | `auth.py`, `routers/users.py` |
| **聊天模块** | 对话管理、消息收发、上下文维护 | `routers/chat.py`, `routers/conversations.py` |
| **RAG服务** | 文档检索、向量嵌入、LLM调用 | `services/rag_service.py`, `services/embedding.py` |
| **知识管理** | 文档上传、解析、向量化存储 | `routers/knowledge.py`, `services/vector_store.py` |
| **管理员模块** | 用户管理、系统配置、日志查看 | `routers/admin.py` |

### 1.4 技术栈

| 分类 | 技术 | 版本/说明 |
|------|------|-----------|
| **框架** | FastAPI | 现代 Python Web 框架 |
| **服务器** | Uvicorn | ASGI 服务器 |
| **数据库** | SQLite | 轻量级关系型数据库 |
| **ORM** | SQLAlchemy | 数据库对象映射 |
| **认证** | JWT (PyJWT) | 无状态身份认证 |
| **前端** | Bootstrap 5 | 响应式 UI 框架 |
| **LLM** | DeepSeek API | 大语言模型服务 |
| **向量数据库** | Chroma | 轻量级向量存储 |
| **嵌入模型** | sentence-transformers | 文本向量化 |
| **图片处理** | Pillow | 头像压缩处理 |

### 1.5 数据流程图

**用户认证流程：**
```
用户 → 登录/注册 → JWT令牌 → 请求API → 令牌验证 → 业务处理 → 返回响应
```

**聊天对话流程：**
```
用户消息 → Chat API → RAG检索 → DeepSeek LLM → 生成响应 → 存储对话 → 返回结果
```

**知识上传流程：**
```
文档上传 → 格式验证 → 内容提取 → 向量化 → 向量存储 → 记录元数据
```

---

## 2. 功能组件

### 2.1 功能总览

| 功能模块 | 子功能 | 状态 |
|----------|--------|------|
| 用户认证 | 注册、登录、密码重置 | ✅ 已实现 |
| 用户管理 | 个人信息、头像上传、角色管理 | ✅ 已实现 |
| 聊天对话 | 创建会话、发送消息、历史记录 | ✅ 已实现 |
| RAG知识库 | 文档上传、知识检索、向量管理 | ✅ 已实现 |
| 系统管理 | 用户管理、配置管理、日志查看 | ✅ 已实现 |

### 2.2 用户认证模块

**功能描述：**
- 用户注册：邮箱、密码、用户名创建账户
- 用户登录：邮箱密码验证，返回JWT令牌
- 令牌刷新：自动续期机制
- 密码管理：支持密码重置（预留接口）

**关键代码示例** (`auth.py`):
```python
async def authenticate_user(db: Session, email: str, password: str):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        return False
    return user
```

**用户流程：**
```
访问登录页 → 输入凭证 → 验证成功 → 获取令牌 → 跳转首页
```

### 2.3 用户管理模块

**功能描述：**
- 个人信息查看/编辑
- 头像上传（支持JPG/PNG/WEBP，2MB限制）
- 多尺寸头像生成（original/large/medium/small）
- 旧头像文件自动清理

**头像上传处理流程** (`routers/users.py`):
```python
# 文件验证
if not file.content_type.startswith('image/'):
    raise HTTPException(status_code=400, detail="不支持的图片格式")

# 尺寸处理
sizes = {
    "original": None,
    "large": (200, 200),
    "medium": (100, 100),
    "small": (50, 50)
}
```

### 2.4 聊天对话模块

**功能描述：**
- 创建/删除对话会话
- 发送消息并获取AI响应
- 查看对话历史
- 会话列表管理

**对话数据模型：**
```python
# Conversation: 会话实体
# ChatMessage: 消息实体（关联会话和用户）
# 消息类型：user(用户消息), assistant(AI响应), system(系统消息)
```

**RAG检索流程：**
```python
# 1. 用户提问向量化
query_embedding = embedding.encode(query)

# 2. 向量数据库检索
results = vector_store.similarity_search(query_embedding, k=3)

# 3. 构建prompt上下文
context = "\n".join([doc.page_content for doc in results])

# 4. 调用LLM生成响应
response = deepseek_client.generate(context + query)
```

### 2.5 知识库管理模块

**功能描述：**
- 文档上传（支持TXT/PDF等格式）
- 文档解析和内容提取
- 向量嵌入和存储
- 知识库列表管理
- 共享知识库功能

**支持的文档格式：**
- 纯文本文件 (.txt)
- PDF文档 (.pdf) - 需安装PyPDF2
- Markdown文件 (.md)

### 2.6 管理员模块

**功能描述：**
- 用户列表管理（查看、禁用、角色变更）
- 系统配置管理
- 操作日志查看
- 知识库统计

**管理员权限控制：**
```python
async def get_current_admin(current_user: User = Depends(get_current_active_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="无管理员权限")
    return current_user
```

### 2.7 错误处理机制

| 错误类型 | HTTP状态码 | 处理策略 |
|----------|-----------|----------|
| 认证失败 | 401 | 返回未授权，前端跳转登录 |
| 权限不足 | 403 | 返回禁止访问提示 |
| 参数错误 | 400 | 详细错误信息 |
| 文件过大 | 413 | 限制2MB，提示用户 |
| 服务器错误 | 500 | 记录日志，返回友好提示 |
| 资源不存在 | 404 | 明确提示资源位置 |

---

## 3. 附加文档

### 3.1 关键模块职责

#### 3.1.1 `main.py` - 应用入口
- FastAPI应用实例创建
- 路由注册
- 中间件配置（CORS、静态文件）
- 数据库连接初始化

#### 3.1.2 `database.py` - 数据库配置
- SQLAlchemy引擎创建
- 数据库会话管理
- 依赖注入函数

#### 3.1.3 `models.py` - 数据模型
- User: 用户实体
- Conversation: 会话实体
- ChatMessage: 消息实体
- KnowledgeBase: 知识库实体
- OperationLog: 操作日志

#### 3.1.4 `auth.py` - 认证逻辑
- JWT令牌生成/验证
- 密码加密/验证
- 认证依赖函数

#### 3.1.5 `schemas.py` - 数据模式
- Pydantic模型定义
- 请求/响应结构
- 数据验证规则

#### 3.1.6 `services/` - 业务服务
- `rag_service.py`: RAG核心逻辑
- `deepseek_client.py`: LLM API调用
- `vector_store.py`: 向量数据库操作
- `embedding.py`: 文本嵌入处理

### 3.2 配置与环境

#### 3.2.1 环境变量（`.env`）
```env
# 数据库配置
DATABASE_URL=sqlite:///./app.db

# JWT配置
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# DeepSeek API配置
DEEPSEEK_API_KEY=your-api-key
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

# 上传配置
MAX_FILE_SIZE=2097152  # 2MB
ALLOWED_EXTENSIONS=jpg,jpeg,png,webp
```

#### 3.2.2 启动方式

**开发模式：**
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**生产模式：**
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 3.3 安全考虑

#### 3.3.1 认证安全
- JWT令牌存储：HttpOnly Cookie
- 密码加密：bcrypt算法（10轮）
- 令牌过期机制：30分钟自动失效
- CSRF防护：预留接口

#### 3.3.2 文件上传安全
- 文件类型白名单验证
- 文件大小限制（2MB）
- 文件内容校验（图片完整性检查）
- 存储路径随机化（UUID命名）
- 禁止执行权限设置

#### 3.3.3 输入验证
- Pydantic模型强制验证
- SQL注入防护（ORM参数化查询）
- XSS防护（前端模板自动转义）
- 路径遍历防护

#### 3.3.4 访问控制
- 基于角色的访问控制（RBAC）
- 用户只能访问自己的资源
- 管理员权限隔离

### 3.4 性能优化

#### 3.4.1 数据库优化
- 索引优化：常用查询字段建立索引
- 批量操作：减少数据库往返
- 连接池配置：复用数据库连接

#### 3.4.2 缓存策略
- 向量嵌入结果缓存
- 会话上下文缓存
- 静态资源缓存（浏览器缓存头）

#### 3.4.3 异步处理
- FastAPI异步端点
- 数据库异步操作
- 长任务后台处理

#### 3.4.4 资源管理
- 头像多尺寸生成（按需加载）
- 图片压缩处理
- 旧文件自动清理

### 3.5 可扩展性

#### 3.5.1 当前架构优势
- 模块化设计：各组件松耦合
- 配置化管理：通过环境变量配置
- API标准化：RESTful接口设计

#### 3.5.2 扩展方向
- **数据库扩展**：支持PostgreSQL/MySQL
- **向量数据库扩展**：支持Pinecone/Weaviate
- **LLM扩展**：支持多LLM提供商
- **部署扩展**：支持Docker/Kubernetes

#### 3.5.3 限制与建议
- SQLite不适合高并发场景，建议生产环境使用PostgreSQL
- 向量数据库Chroma适合单机部署，大规模场景需考虑分布式方案
- 文件存储当前为本地文件系统，建议使用云存储（S3等）

---

## 4. 项目文件结构

```
project/
├── main.py                 # 应用入口
├── database.py             # 数据库配置
├── models.py               # SQLAlchemy模型
├── auth.py                 # 认证逻辑
├── schemas.py              # Pydantic模式
├── requirements.txt        # 依赖列表
├── .env.example            # 环境变量示例
├── app.db                  # SQLite数据库文件
├── routers/
│   ├── users.py            # 用户管理路由
│   ├── chat.py             # 聊天消息路由
│   ├── conversations.py    # 会话管理路由
│   ├── knowledge.py        # 知识库路由
│   └── admin.py            # 管理员路由
├── services/
│   ├── rag_service.py      # RAG服务
│   ├── deepseek_client.py  # LLM客户端
│   ├── vector_store.py     # 向量存储
│   └── embedding.py        # 嵌入服务
├── templates/
│   ├── base.html           # 基础模板
│   ├── login.html          # 登录页
│   ├── register.html       # 注册页
│   ├── chat.html           # 聊天页
│   ├── knowledge.html      # 知识库管理页
│   ├── shared_knowledge.html # 共享知识页
│   ├── system.html         # 系统配置页
│   └── admin.html          # 管理员页
├── static/
│   ├── avatars/            # 头像存储
│   ├── css/                # 样式文件
│   └── js/                 # JavaScript文件
└── tests/
    ├── test_avatar.py      # 头像测试
    └── ...                 # 其他测试文件
```

---

## 5. API接口汇总

| 模块 | 端点 | 方法 | 描述 |
|------|------|------|------|
| 认证 | `/api/auth/login` | POST | 用户登录 |
| 认证 | `/api/auth/register` | POST | 用户注册 |
| 用户 | `/api/users/me` | GET | 获取当前用户 |
| 用户 | `/api/users/me/avatar` | POST | 上传头像 |
| 用户 | `/api/users/me/avatar` | GET | 获取头像 |
| 会话 | `/api/conversations` | GET | 获取会话列表 |
| 会话 | `/api/conversations` | POST | 创建会话 |
| 会话 | `/api/conversations/{id}` | DELETE | 删除会话 |
| 消息 | `/api/chat/messages` | POST | 发送消息 |
| 消息 | `/api/chat/messages/{conversation_id}` | GET | 获取消息列表 |
| 知识 | `/api/knowledge/upload` | POST | 上传文档 |
| 知识 | `/api/knowledge/list` | GET | 获取知识库列表 |
| 知识 | `/api/knowledge/{id}` | DELETE | 删除知识库 |
| 管理 | `/api/admin/users` | GET | 获取用户列表 |
| 管理 | `/api/admin/users/{id}` | PUT | 更新用户 |
| 管理 | `/api/admin/logs` | GET | 获取操作日志 |

---

## 6. 总结

本项目是一个功能完整的AI智能助手系统，具备以下特点：

**技术亮点：**
- 现代化技术栈（FastAPI + Bootstrap 5）
- 完整的RAG检索增强生成能力
- 安全的认证和权限管理
- 模块化、可扩展的架构设计

**功能完整性：**
- 用户认证与管理
- 智能聊天对话
- 知识库管理
- 管理员后台

**适用场景：**
- 企业内部智能助手
- 客服聊天机器人
- 知识库问答系统
- 个人AI助手

**后续建议：**
- 添加单元测试覆盖关键路径
- 引入消息队列处理异步任务
- 考虑分布式部署方案
- 增加国际化支持