# RAG 知识库对话系统

基于知识库检索增强的对话系统，后端使用 FastAPI，前端使用 Jinja2 模板 + Bootstrap 5，无需前后端分离。使用 SQLite 作为主数据库，ChromaDB 作为向量数据库。

## 功能特性

- ✅ 基于 RAG 的智能对话，流式输出
- ✅ 知识库管理（文件上传、分段、向量化、检索）
- ✅ 用户系统（注册、登录、JWT 认证）
- ✅ 会话管理（多会话、切换、删除）
- ✅ 语音输入（浏览器 Web Speech API）
- ✅ 管理员控制台
- ✅ 详细的系统结构展示页面

## 技术栈

**后端**
- FastAPI
- SQLAlchemy 2.0 + aiosqlite
- ChromaDB
- python-jose (JWT)
- passlib (bcrypt)
- openai (API 客户端)

**前端**
- Bootstrap 5
- Jinja2
- 原生 JavaScript

**外部服务**
- 阿里云 DashScope (text-embedding-v3)
- DeepSeek (DeepSeek-v4-pro)

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，并填写必要的 API Key：

```bash
cp .env.example .env
```

编辑 `.env`：

```env
DASHSCOPE_API_KEY=你的阿里云APIKey
DEEPSEEK_API_KEY=你的DeepSeekAPIKey
SECRET_KEY=修改为随机字符串
ADMIN_EMAIL=admin
ADMIN_PASSWORD=admin123
```

### 3. 启动服务

```bash
python main.py
```

服务将在 `http://localhost:8000` 启动。

### 4. 访问系统

- 打开浏览器访问 `http://localhost:8000`
- 使用默认管理员账号登录：
  - 邮箱：`admin`
  - 密码：`admin123`

## 项目结构

```
.
├── main.py                 # FastAPI 主入口
├── database.py             # 数据库引擎与会话
├── models.py               # ORM 模型
├── schemas.py              # Pydantic 模型
├── auth.py                 # 认证与授权
├── requirements.txt        # 依赖列表
├── .env.example            # 环境变量示例
├── routers/                # 路由
│   ├── users.py
│   ├── conversations.py
│   ├── chat.py
│   ├── knowledge.py
│   └── admin.py
├── services/               # 业务逻辑
│   ├── embedding.py
│   ├── deepseek_client.py
│   └── rag_service.py
└── templates/              # 页面模板
    ├── base.html
    ├── login.html
    ├── register.html
    ├── chat.html
    ├── knowledge.html
    ├── admin.html
    └── system.html
```

## 主要功能说明

### 1. 对话功能

- 使用 RAG 模式，先从用户知识库检索相关内容
- 流式输出，支持逐词渲染
- 支持多会话切换

### 2. 知识库管理

- 上传 .txt 或 .md 文件
- 自动分段（每段约 500 字符，重叠 50 字符）
- 使用阿里云 text-embedding-v3 生成向量
- 用户数据完全隔离

### 3. 系统结构展示

访问 `/system` 页面查看极其详细的系统架构文档，包含：
- 系统架构图
- 数据库模型关系
- API 列表
- 实现原理说明
- 部署指南

## 部署

### 云服务器部署

推荐使用 `uvicorn` 直接运行：

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

或使用 Gunicorn + Uvicorn：

```bash
gunicorn main:app --workers 1 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### 使用 Systemd 管理（Linux）

创建 `/etc/systemd/system/rag-app.service`：

```ini
[Unit]
Description=RAG 知识库对话系统
After=network.target

[Service]
User=www-data
WorkingDirectory=/path/to/project
ExecStart=/path/to/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable rag-app
sudo systemctl start rag-app
```

## 注意事项

- 生产环境请务必修改 `SECRET_KEY`
- 可以考虑使用 PostgreSQL 替代 SQLite
- ChromaDB 数据会持久化到 `./chroma_data`
- SQLite 数据库文件为 `./app.db`

## 许可证

MIT License
