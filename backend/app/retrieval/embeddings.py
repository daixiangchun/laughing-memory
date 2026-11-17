"""本地文本嵌入：sentence-transformers MiniLM（384 维，归一化后内积=余弦）

为什么用本地模型做嵌入：建库时要处理几千个文档块，走 API 既有成本又有延迟，
而且文档内容不出本机。只用大模型做最后的「组织语言」。
"""
from typing import List

from langchain_community.embeddings import HuggingFaceEmbeddings

from backend.app.config import get_settings


class EmbeddingService:
    """嵌入向量服务（懒加载，首次调用时才加载模型）"""

    def __init__(self):
        self.settings = get_settings()
        self._embeddings = None

    def get_embeddings(self) -> HuggingFaceEmbeddings:
        if self._embeddings is None:
            self._embeddings = HuggingFaceEmbeddings(
                model_name=self.settings.EMBEDDING_MODEL,
                model_kwargs={"device": "cpu"},
                encode_kwargs={"normalize_embeddings": True},
            )
        return self._embeddings

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self.get_embeddings().embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        return self.get_embeddings().embed_query(text)


embedding_service = EmbeddingService()
