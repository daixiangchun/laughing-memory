"""问答接口的简单限流（进程内滑动窗口，按客户端 IP 计数）。

目的：公开部署后防止别人刷光 DeepSeek 额度。
取舍：只在单进程内有效；多实例部署需要换成 Redis 之类的共享计数。
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from backend.app.config import get_settings


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            # 防止长期运行时字典无限增长：清理已过期的 key
            if len(self._hits) > 5000:
                for stale in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window]:
                    del self._hits[stale]
            return True


_limiter = SlidingWindowLimiter(limit=get_settings().RATE_LIMIT_PER_MINUTE)


def _client_key(request: Request) -> str:
    settings = get_settings()
    # 只有确认部署在可信反向代理之后才信任 X-Forwarded-For，否则可被伪造绕过限流
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_query_rate_limit(request: Request) -> None:
    """FastAPI 依赖：超过限额返回 429"""
    if _limiter.limit <= 0:  # 0 表示关闭限流（本地开发）
        return
    if not _limiter.allow(_client_key(request)):
        raise HTTPException(status_code=429, detail="提问太频繁，请稍后再试（每分钟有次数限制）")
