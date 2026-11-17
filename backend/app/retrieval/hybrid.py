"""混合检索：版本过滤（pre / post / none）+ 向量 + BM25 + RRF 融合"""
from dataclasses import dataclass, field

from backend.app.config import get_settings
from backend.app.retrieval.bm25_store import bm25_index
from backend.app.retrieval.fusion import FusedHit, rrf_fuse
from backend.app.retrieval.vector_store import vector_index


@dataclass
class Retrieved:
    """一条融合后的检索结果，附带原始 chunk"""
    chunk: dict
    rrf: float
    vector_score: float | None = None
    bm25_score: float | None = None
    vector_rank: int | None = None
    bm25_rank: int | None = None


@dataclass
class RetrievalResult:
    query: str
    library: str | None
    versions: list[str]
    mode: str
    items: list[Retrieved] = field(default_factory=list)

    @property
    def top_vector_score(self) -> float | None:
        scores = [i.vector_score for i in self.items if i.vector_score is not None]
        return max(scores) if scores else None


def _allowed_ids(library: str | None, versions: list[str] | None) -> set[str] | None:
    """post / pre 共用的版本过滤集合（pre 用于 BM25 侧，保持两侧口径一致）"""
    if not versions and not library:
        return None
    allowed: set[str] = set()
    for cid, chunk in vector_index.chunks.items():
        if versions and chunk["version"] not in versions:
            continue
        if library and chunk["library"] != library:
            continue
        allowed.add(cid)
    return allowed


def retrieve(
    query: str,
    library: str | None = None,
    versions: list[str] | None = None,
    mode: str = "pre",
    top_k: int | None = None,
) -> RetrievalResult:
    """mode=pre 版本过滤下召回；post 先召回再过滤；none 不做版本过滤（评测基线）"""
    settings = get_settings()
    k = top_k or settings.TOP_K_RESULTS
    if not vector_index.ready or not bm25_index.ready:
        raise RuntimeError("索引未构建，请先运行 backend/scripts/build_index.py")

    allowed = _allowed_ids(library, versions) if mode in {"pre", "post"} else None

    vector_hits = vector_index.search(
        query,
        k=max(settings.VECTOR_CANDIDATES, k),
        library=library,
        versions=versions,
        mode=mode,
    )
    bm25_raw = bm25_index.search(query, k=settings.BM25_CANDIDATES, allowed=allowed)

    fused: list[FusedHit] = rrf_fuse(
        [(h.chunk_id, h.score) for h in vector_hits],
        [(h.chunk_id, h.score) for h in bm25_raw],
        k=settings.RRF_K,
    )

    items = [
        Retrieved(
            chunk=vector_index.chunks[f.chunk_id],
            rrf=f.rrf,
            vector_score=f.vector_score,
            bm25_score=f.bm25_score,
            vector_rank=f.vector_rank,
            bm25_rank=f.bm25_rank,
        )
        for f in fused
        if f.chunk_id in vector_index.chunks
        # 缺失记录只用于冲突检测，不进生成上下文、不参与相关性打分：
        # 否则「某版本不存在该符号」这条文本会被当成相关片段回答无关问题
        and vector_index.chunks[f.chunk_id].get("doc_type") != "missing"
    ][:k]

    # 用户明确点名了符号时，把它自己的文档块提到最前。
    # 向量和 BM25 对长点号符号都不稳（sqlalchemy.orm.Session 会被
    # object_session / ORMExecuteState.session 之类更细的属性抢走），
    # 而「用户写了符号名」本身就是最强的相关性信号。
    exact = exact_symbol_items(query, library, versions)
    if exact:
        head_ids = {item.chunk["chunk_id"] for item in exact}
        items = exact + [i for i in items if i.chunk["chunk_id"] not in head_ids]
        items = items[: max(k, len(exact))]

    return RetrievalResult(query=query, library=library, versions=versions or [], mode=mode, items=items)


def exact_symbol_items(
    query: str,
    library: str | None,
    versions: list[str] | None,
) -> list[Retrieved]:
    """查询里点名的符号若在知识库中存在，直接取出其文档块（不含 missing 记录）"""
    from backend.app.reasoning.sufficiency import extract_symbols, normalize_symbol

    records = vector_index.chunks
    found: dict[str, dict] = {}
    for token in extract_symbols(query):
        symbol = normalize_symbol(token, records)
        if not symbol:
            continue
        for chunk in records.values():
            if chunk.get("symbol") != symbol:
                continue
            if library and chunk["library"] != library:
                continue
            if versions and chunk["version"] not in versions:
                continue
            found.setdefault(chunk["chunk_id"], chunk)
    return [
        Retrieved(chunk=chunk, rrf=1.0)
        for chunk in sorted(found.values(), key=lambda c: (c["library"], c["version"]))
    ]


_loaded = False


def ensure_indexes_loaded() -> None:
    """首次使用时加载索引（服务启动调用一次即可）"""
    global _loaded
    if _loaded and vector_index.ready and bm25_index.ready:
        return
    ok_vec = vector_index.load() if not vector_index.ready else True
    ok_bm25 = bm25_index.load() if not bm25_index.ready else True
    _loaded = bool(ok_vec and ok_bm25)
