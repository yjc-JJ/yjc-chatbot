"""
FastAPI 主入口
启动时自动初始化数据库和默认管理员账号
"""
import logging
import os
import traceback
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from dotenv import load_dotenv

from database import init_db, async_session, Base, engine
from models import User
from auth import hash_password

from routers import users, conversations, chat, knowledge, admin

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger("main")

templates = Jinja2Templates(directory="templates")
templates.env.cache = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await create_default_admin()
    yield
    logger.info("应用关闭完成")


async def create_default_admin():
    import asyncio
    admin_email = os.getenv("ADMIN_EMAIL", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", "admin123")

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.email == admin_email)
        )
        existing_admin = result.scalar_one_or_none()
        if not existing_admin:
            admin_user = User(
                email=admin_email,
                hashed_password=hash_password(admin_password),
                is_admin=True,
            )
            session.add(admin_user)
            await session.commit()
            print(f"[初始化] 默认管理员账号已创建: {admin_email}")
        else:
            print(f"[初始化] 管理员账号已存在: {admin_email}")


app = FastAPI(
    title="RAG 知识库对话系统",
    description="基于知识库检索增强的对话系统，使用 FastAPI + ChromaDB + DeepSeek",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"未捕获的异常: {type(exc).__name__}: {exc}")
    logger.error(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误，请查看日志"},
    )

app.include_router(users.router)
app.include_router(conversations.router)
app.include_router(chat.router)
app.include_router(knowledge.router)
app.include_router(admin.router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})


@app.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})


@app.get("/knowledge", response_class=HTMLResponse)
async def knowledge_page(request: Request):
    return templates.TemplateResponse("knowledge.html", {"request": request})


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return templates.TemplateResponse("admin.html", {"request": request})


@app.get("/system", response_class=HTMLResponse)
async def system_page(request: Request):
    return templates.TemplateResponse("system.html", {"request": request})


@app.get("/shared-knowledge", response_class=HTMLResponse)
async def shared_knowledge_page(request: Request):
    return templates.TemplateResponse("shared_knowledge.html", {"request": request})


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("UVICORN_RELOAD", "false").lower() == "true"
    uvicorn.run("main:app", host=host, port=port, reload=reload)
