"""按版本抓取文档（第 1 步）

用法：
    python backend/scripts/fetch_docs.py --lib pandas --limit 8      # 试跑
    python backend/scripts/fetch_docs.py --lib all                   # 全量
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.config import LIBRARIES  # noqa: E402
from backend.app.ingestion.fetcher import fetch_library, save_manifest  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lib", default="all", choices=["all", "pandas", "sqlalchemy"])
    parser.add_argument("--limit", type=int, default=None, help="pandas 每版本最多抓多少个符号（试跑用）")
    args = parser.parse_args()

    libraries = list(LIBRARIES) if args.lib == "all" else [args.lib]
    pages = []
    for lib in libraries:
        print(f"[fetch] {lib} versions={list(LIBRARIES[lib])}")
        result = fetch_library(lib, LIBRARIES[lib], limit_pandas=args.limit if lib == "pandas" else None)
        pages.extend(result)
        stat = Counter((p.library, p.version, p.status) for p in result)
        for key, n in sorted(stat.items()):
            print(f"   {key[0]:10} {key[1]:8} HTTP {key[2]:<3} -> {n}")

    path = save_manifest(pages)
    ok = sum(1 for p in pages if p.status == 200)
    print(f"[done] {ok}/{len(pages)} 页成功，清单：{path}")


if __name__ == "__main__":
    main()
