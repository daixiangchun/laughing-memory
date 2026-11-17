"""第 3 步：由抓取结果切分文档并建立双索引（向量 + BM25）

用法：
    python backend/scripts/build_index.py
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.ingestion.chunker import chunk_manifest  # noqa: E402
from backend.app.retrieval.bm25_store import bm25_index  # noqa: E402
from backend.app.retrieval.vector_store import vector_index  # noqa: E402


def main() -> None:
    settings = get_settings()
    raw = Path(settings.RAW_DIR)
    manifest_path = raw / "manifest.json"
    if not manifest_path.exists():
        print("[ERROR] 没有抓取结果，请先运行 fetch_docs.py")
        sys.exit(1)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(f"[chunk] 读取 {len(manifest)} 条抓取记录")
    chunks = chunk_manifest(manifest, raw)
    records = [c.to_dict() for c in chunks]
    for record in records:
        record["chunk_id"] = f"{record['library']}@{record['version']}::{record['symbol']}"

    stat = Counter((r["library"], r["version"], r["doc_type"]) for r in records)
    for key, count in sorted(stat.items()):
        print(f"   {key[0]:10} {key[1]:8} {key[2]:8} -> {count}")
    print(f"[chunk] 共 {len(records)} 个块")

    processed = Path(settings.PROCESSED_DIR)
    processed.mkdir(parents=True, exist_ok=True)
    out = processed / "chunks.jsonl"
    out.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
    print(f"[chunk] 已写入 {out}")

    t0 = time.perf_counter()
    vector_index.build(records)
    print(f"[vector] 向量索引完成，耗时 {time.perf_counter() - t0:.1f}s，维度 {vector_index.stats()['dim']}")

    t0 = time.perf_counter()
    bm25_index.build(records)
    print(f"[bm25] 关键词索引完成，耗时 {time.perf_counter() - t0:.1f}s")

    print("[done] 索引就绪")


if __name__ == "__main__":
    main()
