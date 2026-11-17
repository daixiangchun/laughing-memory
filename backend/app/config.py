"""应用配置管理"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置"""

    # 应用基础配置
    APP_NAME: str = "Python 版本感知文档问答"
    APP_VERSION: str = "0.2.0"
    DEBUG: bool = True

    # 数据库配置（当前仅用于连通性检查，检索走 FAISS）
    DATABASE_URL: str = "postgresql://py_dev:py_dev@127.0.0.1:5432/python_ecosystem_assistant"

    # LLM 配置（OpenAI 兼容接口）
    OPENAI_API_KEY: str = ""
    OPENAI_API_BASE: str = "https://api.deepseek.com"
    OPENAI_MODEL: str = "deepseek-flash"
    LLM_TIMEOUT: int = 60  # 秒
    LLM_MAX_TOKENS: int = 800

    # 检索索引
    INDEX_DIR: str = "./backend/data/index"
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    HF_ENDPOINT: str = ""

    # 语料与评测
    RAW_DIR: str = "./backend/data/raw"
    PROCESSED_DIR: str = "./backend/data/processed"
    EVAL_DIR: str = "./backend/data/eval"

    # 检索参数
    TOP_K_RESULTS: int = 4
    VECTOR_CANDIDATES: int = 20   # post-filter 时先多取再过滤
    BM25_CANDIDATES: int = 20
    RRF_K: int = 60
    # 相关性下限（归一化向量内积，即余弦相似度）。低于此值视为证据不足
    MIN_RELEVANCE: float = 0.40  # 依据实测：相关问句 0.53~0.84，无关问句 ≤0.26，取中间值

    # 公开部署防护：每个 IP 每分钟最多提问次数（0 = 关闭）
    RATE_LIMIT_PER_MINUTE: int = 20
    # 部署在反向代理（Nginx/平台网关）之后时设为 true，才会读取 X-Forwarded-For
    TRUST_PROXY_HEADERS: bool = False

    # 文件上传（旧功能保留）
    UPLOAD_DIR: str = "./backend/data/documents"
    MAX_UPLOAD_SIZE: int = 10 * 1024 * 1024
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


# 版本白名单：display 版本名 -> 文档站 URL 片段
LIBRARIES: dict[str, dict[str, str]] = {
    "pandas": {"1.5.3": "1.5", "2.2.0": "2.2"},
    "sqlalchemy": {"1.4": "14", "2.0": "20"},
}

PANDAS_BASE = "https://pandas.pydata.org/pandas-docs/version/{seg}/"
SQLALCHEMY_BASE = "https://docs.sqlalchemy.org/en/{seg}/"

# SQLAlchemy 文档按「章节页」组织，一页包含多个符号
SQLALCHEMY_SECTIONS = [
    "core/sqlelement.html",
    "core/selectable.html",
    "core/connections.html",
    "core/engines.html",
    "core/type_basics.html",
    "orm/session_api.html",
    "orm/mapping_api.html",
    "orm/query.html",
    "orm/queryguide/query.html",  # 2.0 起 Query 文档迁到这里
]
