"""查询日志的数据访问层。

设计取舍：
- 用 psycopg3 直连而不是连接池：本项目的写入频率是「每次问答一条」，
  单机开发环境下每次建连约 1~2ms，池化收益可以忽略；上生产再换 psycopg_pool。
- 所有写入都是 best-effort：数据库不可用时问答照常返回，
  只记一条 warning。日志不该成为主链路单点。
"""
import logging
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from backend.app.config import get_settings

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _dsn() -> str:
    return get_settings().DATABASE_URL


def connect():
    """建立短连接（autocommit，够用且避免漏提交）"""
    return psycopg.connect(_dsn(), connect_timeout=3, autocommit=True, row_factory=dict_row)


def init_schema() -> int:
    """建表（幂等）。返回执行的语句数，便于脚本打印结果"""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    statements = [s.strip() for s in sql.split(";") if s.strip()]
    with connect() as conn, conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)
    return len(statements)


def available() -> bool:
    """数据库是否可写（用于健康检查与管理页降级）"""
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except psycopg.Error:
        logger.warning("database not available")
        return False


def log_query(
    question: str,
    *,
    library: str | None,
    request_version: str | None,
    mode: str,
    status: str,
    resolved_versions: list[str] | None,
    top_score: float | None,
    retrieved: int | None,
    elapsed_ms: int | None,
    used_llm: bool | None,
) -> bool:
    """写入一条查询日志；失败不影响问答主流程"""
    try:
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO query_logs
                    (question, library, request_version, mode, status,
                     resolved_versions, top_score, retrieved, elapsed_ms, used_llm)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    question[:2000],
                    library,
                    request_version,
                    mode,
                    status,
                    resolved_versions or [],
                    top_score,
                    retrieved,
                    elapsed_ms,
                    used_llm,
                ),
            )
        return True
    except psycopg.Error as exc:
        logger.warning("failed to write query log: %s", exc)
        return False


def recent_logs(limit: int = 20) -> list[dict[str, Any]]:
    """最近若干条查询（管理页用）"""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, question, library, request_version, mode, status,
                   resolved_versions, top_score, retrieved, elapsed_ms,
                   used_llm, created_at
            FROM query_logs
            ORDER BY id DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    for row in rows:
        row["created_at"] = row["created_at"].isoformat(timespec="seconds")
    return rows


def summary() -> dict[str, Any]:
    """按状态聚合 + 拒答率 + 平均耗时（管理页顶部指标）"""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                count(*)                                            AS total,
                count(*) FILTER (WHERE status = 'answer')            AS answered,
                count(*) FILTER (WHERE status = 'conflict')          AS conflicted,
                count(*) FILTER (WHERE status = 'refused')           AS refused,
                round(avg(elapsed_ms))::int                          AS avg_elapsed_ms,
                max(created_at)                                      AS last_at
            FROM query_logs
            """
        )
        row = cur.fetchone() or {}

    total = row.get("total") or 0
    row["refusal_rate"] = round(row["refused"] / total, 3) if total else None
    row["last_at"] = row["last_at"].isoformat(timespec="seconds") if row.get("last_at") else None
    return row
