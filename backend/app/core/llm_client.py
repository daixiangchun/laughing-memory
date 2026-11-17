"""LLM客户端封装"""
from typing import Optional
from langchain_openai import ChatOpenAI
from backend.app.config import get_settings
from backend.app.core.exceptions import ConfigurationError


class LLMClient:
    """LLM客户端管理类"""

    def __init__(self):
        self.settings = get_settings()
        self._client: Optional[ChatOpenAI] = None

    def ensure_configured(self) -> None:
        """未配置真实密钥时提前报错，避免请求挂到超时"""
        key = (self.settings.OPENAI_API_KEY or "").strip()
        if not key or key.startswith("sk-your-") or key == "your-api-key-here":
            raise ConfigurationError(
                "尚未配置 OPENAI_API_KEY，请在 .env 中填入真实密钥后重启服务"
            )

    def get_client(self) -> ChatOpenAI:
        """获取或创建LLM客户端"""
        self.ensure_configured()
        if self._client is None:
            self._client = ChatOpenAI(
                model=self.settings.OPENAI_MODEL,
                openai_api_key=self.settings.OPENAI_API_KEY,
                openai_api_base=self.settings.OPENAI_API_BASE,
                temperature=0.7,
                # 没有超时时，错配的地址或密钥会让请求挂住很久
                request_timeout=self.settings.LLM_TIMEOUT,
                max_retries=1,
            )
        return self._client


# 全局LLM客户端实例
llm_client = LLMClient()
