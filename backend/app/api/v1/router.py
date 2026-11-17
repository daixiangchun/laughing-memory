"""API v1 路由"""
from fastapi import APIRouter

from backend.app.api.v1.endpoints import eval as eval_endpoint, query, versions

router = APIRouter()

router.include_router(query.router, prefix="/query", tags=["版本感知问答"])
router.include_router(versions.router, tags=["版本与索引"])
router.include_router(eval_endpoint.router, tags=["评测"])
