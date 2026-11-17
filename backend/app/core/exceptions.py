"""自定义异常"""


class BaseAPIException(Exception):
    """API基础异常"""
    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


class DocumentNotFoundError(BaseAPIException):
    """文档未找到异常"""
    def __init__(self, doc_id: str):
        super().__init__(f"Document {doc_id} not found", 404)


class EmbeddingError(BaseAPIException):
    """嵌入向量生成异常"""
    def __init__(self, message: str):
        super().__init__(f"Embedding error: {message}", 500)


class LLMError(BaseAPIException):
    """LLM调用异常"""
    def __init__(self, message: str):
        super().__init__(f"LLM error: {message}", 500)


class ConfigurationError(BaseAPIException):
    """配置缺失（例如未填 API Key），属于部署问题而非请求问题"""
    def __init__(self, message: str):
        super().__init__(message, 503)


class VectorStoreError(BaseAPIException):
    """向量数据库异常"""
    def __init__(self, message: str):
        super().__init__(f"Vector store error: {message}", 500)
