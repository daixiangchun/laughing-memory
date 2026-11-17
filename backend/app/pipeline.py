"""问答编排：查询理解 → 版本过滤检索 → 混合召回 → 冲突检测 → 证据判断 → 生成 / 拒答"""
import re
import time
from dataclasses import dataclass, field

from backend.app.reasoning.conflict import resolve_conflicts
from backend.app.reasoning.generator import format_conflict, generate
from backend.app.reasoning.sufficiency import extract_symbols, judge, normalize_symbol
from backend.app.retrieval.hybrid import retrieve
from backend.app.retrieval.vector_store import vector_index

VERSION_IN_QUERY = re.compile(r"\b(\d+\.\d+(?:\.\d+)?)\b")


def settings_threshold() -> float:
    """拒答阈值（来自配置，评测页会展示）"""
    from backend.app.config import get_settings

    return get_settings().MIN_RELEVANCE


@dataclass
class Answer:
    status: str                                   # answer / conflict / refused
    answer: str
    citations: list[dict] = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "answer": self.answer,
            "citations": self.citations,
            "conflicts": self.conflicts,
            "reasons": self.reasons,
            "meta": self.meta,
        }


def detect_versions(query: str, library: str) -> list[str]:
    """从问题里识别版本（只在已知版本范围内生效）"""
    from backend.app.config import LIBRARIES

    known = set(LIBRARIES.get(library, {}))
    found = []
    for token in VERSION_IN_QUERY.findall(query):
        for version in known:
            if version == token or version.startswith(token):
                found.append(version)
    return sorted(set(found))


def answer_question(
    query: str,
    library: str | None = None,
    version: str | None = None,
    mode: str = "pre",
    top_k: int = 4,
) -> Answer:
    started = time.perf_counter()
    if not vector_index.ready:
        raise RuntimeError("索引未构建，请先运行 backend/scripts/build_index.py")

    # 1) 版本解析：显式参数优先，其次从问题文本里识别
    versions = [version] if version else (detect_versions(query, library) if library else [])
    versions_specified = bool(versions)

    # 2) 如果问题点名了符号，直接按符号精确取全部版本（比向量召回可靠）
    all_records = vector_index.all_records()
    direct_symbol = None
    for token in extract_symbols(query):
        resolved = normalize_symbol(token, all_records)
        if resolved:
            direct_symbol = resolved
            break

    result = retrieve(query, library=library, versions=versions or None, mode=mode, top_k=top_k)

    items = list(result.items)
    chunks_for_analysis = [i.chunk for i in items]

    # 检索分数只能来自真正召回的结果：直接取 chunks 字典里的记录没有分数，
    # 早期版本把 result.top_vector_score 换成它会导致「检索到了却判为证据不足」
    top_score = result.top_vector_score

    if direct_symbol:
        symbol_chunks = [
            c for c in all_records.values()
            if c.get("symbol") == direct_symbol and (not library or c["library"] == library)
        ]
        if versions:
            symbol_chunks = [c for c in symbol_chunks if c["version"] in versions]

        if symbol_chunks:
            # 该符号在指定版本里明确不存在：直接给结论，不让模型自由发挥
            if not any(c.get("doc_type") != "missing" for c in symbol_chunks):
                missing_versions = sorted(c["version"] for c in symbol_chunks)
                replacement = next(
                    (i for i in result.items if i.chunk.get("symbol") != direct_symbol),
                    None,
                )
                lines = [
                    f"{direct_symbol} 在 {', '.join(missing_versions)} 的官方 API 索引中不存在"
                    "（依据该版本文档的符号清单，不是页面抓取失败）。",
                ]
                if replacement is not None:
                    lines.append(
                        f"同一版本中更相关的是 {replacement.chunk['symbol']}："
                        f"{replacement.chunk['source_url']}"
                    )
                meta = {
                    "library": library,
                    "versions": versions,
                    "mode": mode,
                    "top_vector_score": top_score,
                    "threshold": settings_threshold(),
                    "retrieved": len(result.items),
                    "mentioned_symbols": [direct_symbol],
                    "elapsed_ms": int((time.perf_counter() - started) * 1000),
                }
                return Answer(
                    status="answer",
                    answer="\n".join(lines),
                    citations=[
                        {
                            "library": c["library"],
                            "version": c["version"],
                            "symbol": c["symbol"],
                            "source_url": c["source_url"],
                            "doc_type": "missing",
                        }
                        for c in sorted(symbol_chunks, key=lambda c: c["version"])
                    ]
                    + ([{
                        "library": replacement.chunk["library"],
                        "version": replacement.chunk["version"],
                        "symbol": replacement.chunk["symbol"],
                        "source_url": replacement.chunk["source_url"],
                        "doc_type": "symbol",
                    }] if replacement else []),
                    reasons=[],
                    meta=meta,
                )

            # 冲突判定需要覆盖全部版本（含 missing 记录）
            chunks_for_analysis = symbol_chunks
            # 但生成上下文只放真实文档块，且把「用户点名的符号」排在最前
            # （向量/BM25 对 SQLAlchemy 这类点号很长的符号会偏向 object_session 之类的子属性）
            real_chunks = [c for c in symbol_chunks if c.get("doc_type") != "missing"]
            if real_chunks:
                from backend.app.retrieval.hybrid import Retrieved

                exact = [
                    Retrieved(chunk=c, rrf=1.0, vector_score=top_score)
                    for c in sorted(real_chunks, key=lambda c: (c["version"], c["symbol"]))
                ]
                seen_ids = {c["chunk_id"] for c in real_chunks}
                items = exact + [i for i in items if i.chunk["chunk_id"] not in seen_ids]

    collisions = resolve_conflicts(chunks_for_analysis)

    # 3) 证据充分性
    sufficiency = judge(
        query=query,
        top_vector_score=top_score,
        retrieved_chunks=chunks_for_analysis,
        conflicts=[c.to_dict() for c in collisions],
        versions_specified=versions_specified,
        chunks_all=all_records,
    )

    meta = {
        "library": library,
        "versions": versions,
        "mode": mode,
        "top_vector_score": sufficiency.top_score,
        "threshold": sufficiency.threshold,
        "retrieved": len(items),
        "mentioned_symbols": sufficiency.mentioned_symbols,
        "elapsed_ms": 0,
    }

    if sufficiency.status == "conflict":
        primary = collisions[0]
        meta["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return Answer(
            status="conflict",
            answer=format_conflict(primary),
            citations=[
                {"library": primary.library, "version": c.version, "symbol": primary.symbol,
                 "source_url": c.source_url, "doc_type": "missing" if not c.exists else "symbol"}
                for c in primary.claims
            ],
            conflicts=[c.to_dict() for c in collisions],
            reasons=sufficiency.reasons,
            meta=meta,
        )

    if sufficiency.status == "refused":
        meta["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        return Answer(
            status="refused",
            answer="文档中没有足够信息回答这个问题，因此不作推测。",
            reasons=sufficiency.reasons,
            meta=meta,
        )

    # 4) 生成
    generation = generate(query, items)
    meta["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
    meta["used_llm"] = generation.used_llm
    if generation.note:
        meta["generation_note"] = generation.note
    return Answer(
        status="answer",
        answer=generation.answer,
        citations=generation.citations,
        conflicts=[c.to_dict() for c in collisions],
        reasons=[],
        meta=meta,
    )
