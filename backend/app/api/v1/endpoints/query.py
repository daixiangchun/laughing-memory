"""版本感知问答接口"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.core.rate_limit import enforce_query_rate_limit
from backend.app.db import repository as query_log
from backend.app.pipeline import answer_question
from backend.app.retrieval.hybrid import ensure_indexes_loaded
from backend.app.schemas.query import QueryRequest, QueryResponse

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "",
    response_model=QueryResponse,
    summary="版本感知问答",
    dependencies=[Depends(enforce_query_rate_limit)],
)
def query(request: QueryRequest):
    """
    - 指定 `version` / `library` 时只在对应范围内检索
    - 不指定且检索结果跨版本冲突时返回 `status=conflict`，各版本说法分开列出
    - 证据不足（相关性低于阈值 / 符号未覆盖）返回 `status=refused`
    """
    ensure_indexes_loaded()
    try:
        result = answer_question(
            query=request.query,
            library=request.library,
            version=request.version,
            mode=request.mode,
            top_k=request.top_k,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    meta = result.meta or {}
    # 日志写入是 best-effort：数据库不可用时问答照常返回
    query_log.log_query(
        request.query,
        library=request.library,
        request_version=request.version,
        mode=request.mode,
        status=result.status,
        resolved_versions=meta.get("versions"),
        top_score=meta.get("top_vector_score"),
        retrieved=meta.get("retrieved"),
        elapsed_ms=meta.get("elapsed_ms"),
        used_llm=meta.get("used_llm"),
    )
    return QueryResponse(**result.to_dict())


@router.get("/logs", summary="最近查询记录")
def recent(limit: int = Query(20, ge=1, le=200)):
    """管理页用：最近的查询及其判定结果（数据来自 PostgreSQL）"""
    try:
        return {"summary": query_log.summary(), "items": query_log.recent_logs(limit)}
    except Exception as exc:  # 数据库不可用不应影响其他接口
        raise HTTPException(status_code=503, detail=f"查询日志不可用：{exc}") from exc
