"""Python生态助手 - FastAPI应用入口"""
import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from backend.app.config import get_settings
from backend.app.api.v1.router import router as api_v1_router

# 加载环境变量
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

settings = get_settings()
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    logger.info("Starting Python Ecosystem Tech Assistant API...")
    yield
    # 关闭时清理
    logger.info("Shutting down...")


# 创建FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="基于RAG的Python生态技术助手API",
    lifespan=lifespan
)

# 注册API路由
app.include_router(api_v1_router, prefix="/api/v1")


@app.get("/api/health")
def health():
    """健康检查"""
    return {
        "status": "ok",
        "service": "python-ecosystem-assistant",
        "version": settings.APP_VERSION
    }


@app.get("/api/health/db")
def database_health():
    """数据库健康检查"""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise HTTPException(status_code=503, detail="尚未配置 DATABASE_URL")
    try:
        with psycopg.connect(database_url, connect_timeout=3) as connection:
            connection.execute("SELECT 1").fetchone()
    except psycopg.Error:
        logger.warning("Database health check failed")
        raise HTTPException(
            status_code=503,
            detail="数据库未就绪，请检查 PostgreSQL 服务"
        ) from None
    return {"status": "ok", "database": "postgresql"}


# 前端为原生 HTML/JS，由后端直接托管（与接口同源，无需 CORS）
# 必须放在所有 API 路由之后，否则会抢走 /api 开头的请求
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
else:  # 静态目录缺失时仍保证接口可用
    logger.warning("Static directory not found: %s", STATIC_DIR)
