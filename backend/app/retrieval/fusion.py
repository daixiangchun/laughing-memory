"""RRF（Reciprocal Rank Fusion）：只依赖排名、不依赖分数尺度，融合向量与 BM25 最稳。"""
from dataclasses import dataclass


@dataclass
class FusedHit:
    chunk_id: str
    rrf: float
    vector_score: float | None = None
    bm25_score: float | None = None
    vector_rank: int | None = None
    bm25_rank: int | None = None


def rrf_fuse(
    vector_hits: list[tuple[str, float]],
    bm25_hits: list[tuple[str, float]],
    k: int = 60,
) -> list[FusedHit]:
    """score = Σ 1/(k + rank)，rank 从 1 开始"""
    merged: dict[str, FusedHit] = {}
    for rank, (cid, score) in enumerate(vector_hits, 1):
        item = merged.setdefault(cid, FusedHit(cid, 0.0))
        item.rrf += 1.0 / (k + rank)
        item.vector_score = score
        item.vector_rank = rank
    for rank, (cid, score) in enumerate(bm25_hits, 1):
        item = merged.setdefault(cid, FusedHit(cid, 0.0))
        item.rrf += 1.0 / (k + rank)
        item.bm25_score = score
        item.bm25_rank = rank
    return sorted(merged.values(), key=lambda h: h.rrf, reverse=True)
