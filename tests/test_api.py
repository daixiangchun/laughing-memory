"""API 层测试：请求校验、静态页面、以及不依赖索引的分支。

注意：这里不跑真实索引（索引由 build_index.py 生成，体积大、依赖嵌入模型），
索引缺失时接口应返回 503 而不是 500。
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.main import app  # noqa: E402
from backend.app.reasoning.sufficiency import (  # noqa: E402
    extract_symbols,
    normalize_symbol,
)

client = TestClient(app)


def test_index_page_served():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Python 版本感知文档问答" in resp.text


def test_admin_page_served():
    assert client.get("/admin.html").status_code == 200


def test_static_assets_served():
    assert client.get("/js/common.js").status_code == 200
    assert client.get("/js/chat.js").status_code == 200


def test_rate_limiter_blocks_then_recovers():
    from backend.app.core.rate_limit import SlidingWindowLimiter

    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
    assert limiter.allow("ip", now=0)
    assert limiter.allow("ip", now=1)
    assert not limiter.allow("ip", now=2)          # 超限
    assert limiter.allow("other-ip", now=2)         # 不同 IP 互不影响
    assert limiter.allow("ip", now=61)              # 窗口滑过后恢复


def test_query_requires_query_field():
    assert client.post("/api/v1/query", json={}).status_code == 422


def test_query_rejects_unknown_library():
    resp = client.post("/api/v1/query", json={"query": "x", "library": "numpy"})
    assert resp.status_code == 422


def test_query_rejects_bad_mode():
    resp = client.post("/api/v1/query", json={"query": "x", "mode": "magic"})
    assert resp.status_code == 422


def test_query_returns_503_when_index_missing():
    """索引未构建时给 503（服务不可用），而不是 500 堆栈"""
    resp = client.post("/api/v1/query", json={"query": "DataFrame.append 怎么用？"})
    assert resp.status_code in (200, 503)
    if resp.status_code == 503:
        assert "索引" in resp.json()["detail"]


def test_symbol_extraction():
    assert extract_symbols("DataFrame.append 怎么用？") == ["DataFrame.append"]
    assert extract_symbols("怎么用 pandas 读文件") == []
    assert "e.g" not in extract_symbols("e.g. this")


def test_symbol_normalization_matches_suffix():
    chunks = {
        "a": {"symbol": "sqlalchemy.orm.Session"},
        "b": {"symbol": "pandas.DataFrame.append"},
    }
    assert normalize_symbol("sqlalchemy.orm.Session", chunks) == "sqlalchemy.orm.Session"
    assert normalize_symbol("Session", chunks) == "sqlalchemy.orm.Session"
    assert normalize_symbol("DataFrame.append", chunks) == "pandas.DataFrame.append"
    assert normalize_symbol("DataFrame.nope", chunks) is None
