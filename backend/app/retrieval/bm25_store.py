"""BM25 关键词索引：补向量检索对「精确符号名」不敏感的短板。

标识符（DataFrame.append、ignore_index）会被拆成多段并同时保留整体，
这样问 "DataFrame.append" 和 "append" 都能命中。
"""
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from backend.app.config import get_settings

TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")


def tokenize(text: str) -> list[str]:
    """英文/标识符切词，标识符额外拆出点号与下划线片段"""
    tokens: list[str] = []
    for raw in TOKEN_RE.findall(text or ""):
        low = raw.lower()
        tokens.append(low)
        parts = [p.lower() for p in re.split(r"[._]+", raw) if p]
        if len(parts) > 1:
            tokens.extend(parts)
    return tokens


@dataclass
class Hit:
    chunk_id: str
    score: float


class BM25Index:
    """经典 BM25（k1=1.5, b=0.75），语料规模几千条以内完全够用"""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.doc_tokens: dict[str, list[str]] = {}
        self._tf: dict[str, Counter] = {}   # 词频表，BM25 打分用
        self.doc_freq: Counter = Counter()
        self.avg_len = 0.0
        self.order: list[str] = []
        self.root = Path(get_settings().INDEX_DIR) / "bm25"

    def _index_text(self, chunk: dict) -> str:
        return " ".join(
            [
                chunk.get("symbol", ""),
                chunk.get("signature", ""),
                chunk.get("section_title", ""),
                (chunk.get("text") or "")[:2000],
            ]
        )

    def build(self, chunks) -> None:
        self.doc_tokens.clear()
        self._tf = {}
        self.doc_freq.clear()
        self.order = []
        for chunk in chunks:
            cid = chunk["chunk_id"]
            toks = tokenize(self._index_text(chunk))
            self.doc_tokens[cid] = toks
            self._tf[cid] = Counter(toks)
            self.order.append(cid)
            for term in set(toks):
                self.doc_freq[term] += 1
        self.avg_len = (
            sum(len(t) for t in self.doc_tokens.values()) / len(self.doc_tokens) if self.doc_tokens else 0.0
        )
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "bm25.json").write_text(
            json.dumps(
                {
                    "k1": self.k1,
                    "b": self.b,
                    "avg_len": self.avg_len,
                    "doc_freq": dict(self.doc_freq),
                    "docs": {cid: Counter(t) for cid, t in self.doc_tokens.items()},
                    "order": self.order,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def load(self) -> bool:
        path = self.root / "bm25.json"
        if not path.exists():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        self.k1, self.b = data["k1"], data["b"]
        self.avg_len = data["avg_len"]
        self.doc_freq = Counter(data["doc_freq"])
        self.order = data["order"]
        self.doc_tokens = {cid: list(tf.keys()) for cid, tf in data["docs"].items()}
        self._tf = {cid: Counter(tf) for cid, tf in data["docs"].items()}
        return True

    @property
    def ready(self) -> bool:
        return bool(self._tf)

    def search(self, query: str, k: int = 20, allowed: set[str] | None = None) -> list[Hit]:
        if not self.ready:
            raise RuntimeError("BM25 索引未构建，请先运行 build_index.py")
        terms = tokenize(query)
        if not terms:
            return []
        n_docs = len(self._tf)
        scores: dict[str, float] = {}
        for cid, tf in self._tf.items():
            if allowed is not None and cid not in allowed:
                continue
            dl = sum(tf.values())
            total = 0.0
            for term in terms:
                freq = tf.get(term, 0)
                if not freq:
                    continue
                df = self.doc_freq.get(term, 0)
                idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
                total += idf * freq * (self.k1 + 1) / (
                    freq + self.k1 * (1 - self.b + self.b * dl / (self.avg_len or 1))
                )
            if total > 0:
                scores[cid] = total
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]
        return [Hit(cid, float(s)) for cid, s in ranked]


bm25_index = BM25Index()
