"""FAISS 向量索引：全局索引 + 每个 (library, version) 的子索引。

- 全局索引：用于 post-filter（先召回再按版本过滤）和无过滤基线；
- 子索引：用于 pre-filter（先在版本子集里召回），子集小、召回质量更稳。
向量均为归一化后的 MiniLM 输出，内积等价于余弦相似度。
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import faiss
import numpy as np

from backend.app.config import get_settings
from backend.app.retrieval.embeddings import embedding_service


@dataclass
class Hit:
    """一次召回结果"""
    chunk_id: str
    score: float          # 余弦相似度（越大越相关）


def chunk_embed_text(chunk: dict) -> str:
    """用于生成向量的文本：符号名 + 签名 + 正文摘要，让「问符号名」和「问语义」都能命中"""
    parts = [chunk.get("symbol", ""), chunk.get("signature", "")]
    text = (chunk.get("text") or "")[:1200]
    parts.append(text)
    if chunk.get("deprecated"):
        parts.append("deprecated 已弃用")
    return "\n".join(p for p in parts if p)


class VectorIndex:
    """FAISS 索引集合"""

    def __init__(self, root: Path | None = None):
        settings = get_settings()
        self.root = Path(root or settings.INDEX_DIR) / "vector"
        self.chunks: dict[str, dict] = {}      # 真实文档块（参与检索）
        self.missing: dict[str, dict] = {}     # 缺失记录（只用于冲突判定）
        self._global: faiss.Index | None = None
        self._sub: dict[str, tuple[faiss.Index, list[str]]] = {}
        self._order_cache: list[str] = []
        self._dim = 0

    # ---------- 构建 ----------

    def build(self, chunks: Iterable[dict], batch_size: int = 32) -> None:
        all_items = list(chunks)
        if not all_items:
            raise ValueError("没有可索引的 chunk")

        # 缺失记录不进入向量/BM25 索引：
        # 它们只是为了「该符号在这个版本不存在」保留证据，
        # 一旦进索引就会在检索里压过真实文档块，导致「检索到了却判证据不足」。
        items = [c for c in all_items if c.get("doc_type") != "missing"]
        self.missing = {c["chunk_id"]: c for c in all_items if c.get("doc_type") == "missing"}
        if not items:
            raise ValueError("除缺失记录外没有可索引的 chunk")

        texts = [chunk_embed_text(c) for c in items]
        vectors: list[np.ndarray] = []
        for start in range(0, len(texts), batch_size):
            vectors.append(np.asarray(embedding_service.embed_documents(texts[start:start + batch_size]), dtype="float32"))
        matrix = np.vstack(vectors)
        self._dim = matrix.shape[1]

        self.chunks = {c["chunk_id"]: c for c in items}
        order = [c["chunk_id"] for c in items]
        self._order_cache = order

        self._global = faiss.IndexFlatIP(self._dim)
        self._global.add(matrix)

        # 按 library+version 建子索引
        self._sub = {}
        groups: dict[str, list[int]] = {}
        for i, chunk in enumerate(items):
            groups.setdefault(f"{chunk['library']}@{chunk['version']}", []).append(i)
        for key, idxs in groups.items():
            sub = faiss.IndexFlatIP(self._dim)
            sub.add(matrix[idxs])
            self._sub[key] = (sub, [items[i]["chunk_id"] for i in idxs])

        self._save(order)

    def _save(self, order: list[str]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._global, str(self.root / "global.faiss"))
        for key, (sub, _) in self._sub.items():
            faiss.write_index(sub, str(self.root / f"sub_{key.replace('@', '_')}.faiss"))
        meta = {
            "dim": self._dim,
            "order": order,
            "subs": {k: v[1] for k, v in self._sub.items()},
        }
        (self.root / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        (self.root / "chunks.jsonl").write_text(
            "\n".join(json.dumps(self.chunks[cid], ensure_ascii=False) for cid in order),
            encoding="utf-8",
        )
        (self.root / "missing.jsonl").write_text(
            "\n".join(json.dumps(c, ensure_ascii=False) for c in self.missing.values()),
            encoding="utf-8",
        )

    # ---------- 加载 ----------

    def load(self) -> bool:
        meta_path = self.root / "meta.json"
        if not meta_path.exists():
            return False
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self._dim = meta["dim"]
        self._order_cache = meta["order"]
        self._global = faiss.read_index(str(self.root / "global.faiss"))
        self._sub = {
            key: (faiss.read_index(str(self.root / f"sub_{key.replace('@', '_')}.faiss")), cids)
            for key, cids in meta["subs"].items()
        }
        self.chunks = {}
        with (self.root / "chunks.jsonl").open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    chunk = json.loads(line)
                    self.chunks[chunk["chunk_id"]] = chunk

        self.missing = {}
        missing_path = self.root / "missing.jsonl"
        if missing_path.exists():
            with missing_path.open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        chunk = json.loads(line)
                        self.missing[chunk["chunk_id"]] = chunk
        return True

    def all_records(self) -> dict[str, dict]:
        """真实块 + 缺失记录，冲突检测与符号覆盖判断都要用全量"""
        merged = dict(self.missing)
        merged.update(self.chunks)
        return merged

    @property
    def ready(self) -> bool:
        return self._global is not None and bool(self.chunks)

    # ---------- 查询 ----------

    def _query_vector(self, query: str) -> np.ndarray:
        vec = np.asarray([embedding_service.embed_query(query)], dtype="float32")
        return vec

    def search(
        self,
        query: str,
        k: int,
        library: str | None = None,
        versions: list[str] | None = None,
        mode: str = "pre",
    ) -> list[Hit]:
        """mode: pre（子索引内召回）/ post（全局召回后过滤）/ none（不过滤）"""
        if not self.ready:
            raise RuntimeError("向量索引未构建，请先运行 build_index.py")
        vec = self._query_vector(query)

        if mode == "pre" and versions:
            hits: list[Hit] = []
            for version in versions:
                if not library:
                    keys = [key for key in self._sub if key.endswith(f"@{version}")]
                else:
                    keys = [f"{library}@{version}"] if f"{library}@{version}" in self._sub else []
                for key in keys:
                    sub, cids = self._sub[key]
                    scores, idxs = sub.search(vec, min(k, len(cids)))
                    hits.extend(Hit(cids[i], float(s)) for s, i in zip(scores[0], idxs[0]) if i >= 0)
            hits.sort(key=lambda h: h.score, reverse=True)
            return hits[:k]

        fetch = k if mode == "none" or not versions else max(k * 5, get_settings().VECTOR_CANDIDATES)
        scores, idxs = self._global.search(vec, min(fetch, len(self.chunks)))
        results: list[Hit] = []
        for score, idx in zip(scores[0], idxs[0]):
            if idx < 0:
                continue
            chunk_id = self._order[idx]
            chunk = self.chunks[chunk_id]
            if mode == "post":
                if versions and chunk["version"] not in versions:
                    continue
                if library and chunk["library"] != library:
                    continue
            results.append(Hit(chunk_id, float(score)))
            if len(results) >= k:
                break
        return results

    # 全局索引的行顺序（构建时与 meta 一起落盘）
    @property
    def _order(self) -> list[str]:
        return self._order_cache

    def stats(self) -> dict:
        if not self.ready:
            return {"ready": False}
        counts: dict[str, int] = {}
        for chunk in self.chunks.values():
            key = f"{chunk['library']}@{chunk['version']}"
            counts[key] = counts.get(key, 0) + 1
        return {
            "ready": True,
            "total_chunks": len(self.chunks),
            "dim": self._dim,
            "by_version": counts,
            "missing_records": sum(1 for c in self.chunks.values() if c.get("doc_type") == "missing"),
        }


vector_index = VectorIndex()
