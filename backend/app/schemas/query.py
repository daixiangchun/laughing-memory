"""版本感知问答的请求 / 响应模型"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000, description="用户问题")
    library: Optional[Literal["pandas", "sqlalchemy"]] = Field(None, description="限定库")
    version: Optional[str] = Field(None, description="限定版本，例如 2.2.0")
    mode: Literal["pre", "post", "none"] = Field("pre", description="版本过滤方式")
    top_k: int = Field(4, ge=1, le=10)


class Citation(BaseModel):
    library: Optional[str] = None
    version: Optional[str] = None
    symbol: Optional[str] = None
    source_url: Optional[str] = None
    doc_type: Optional[str] = None


class ConflictClaim(BaseModel):
    version: str
    exists: bool
    deprecated: bool
    signature: str = ""
    params: list[str] = []
    text: str = ""
    source_url: str = ""
    deprecation_note: str = ""


class ConflictPayload(BaseModel):
    symbol: str
    library: str
    reasons: list[str] = []
    claims: list[ConflictClaim] = []


class QueryResponse(BaseModel):
    status: Literal["answer", "conflict", "refused"]
    answer: str
    citations: list[Citation] = []
    conflicts: list[ConflictPayload] = []
    reasons: list[str] = []
    meta: dict = {}
