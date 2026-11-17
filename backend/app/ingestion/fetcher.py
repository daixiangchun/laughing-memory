"""按版本抓取文档原始页面并落盘（带缓存，可重复运行）"""
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin

import httpx

from backend.app.config import SQLALCHEMY_SECTIONS, get_settings
from backend.app.ingestion.inventory import Symbol, api_symbols, base_url


@dataclass
class RawPage:
    """一次抓取的结果"""
    library: str
    version: str
    kind: str          # symbol / section
    name: str          # 符号名或章节路径
    url: str
    status: int
    path: str          # 落盘相对路径（404 时为 @missing）
    bytes: int


def _cache_path(library: str, version: str, name: str) -> Path:
    safe = name.replace("/", "__").replace(":", "_")
    digest = hashlib.md5(name.encode()).hexdigest()[:8]
    return Path(get_settings().RAW_DIR) / library / version / f"{safe}.{digest}.html"


def _download(client: httpx.Client, url: str, dest: Path) -> tuple[int, int]:
    if dest.exists() and dest.stat().st_size > 0:
        return 200, dest.stat().st_size
    resp = client.get(url)
    if resp.status_code == 200:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
    return resp.status_code, len(resp.content)


def select_pandas_symbols(
    symbols: dict[str, Symbol],
    other: dict[str, Symbol],
    max_removed: int = 200,
    max_added: int = 100,
    max_shared: int = 150,
    max_top_level: int = 200,
) -> list[Symbol]:
    """优先选择跨版本有差异的符号：只在本版 + 只在对方版 + 共有热门方法"""
    only_here = sorted(set(symbols) - set(other))
    only_there = sorted(set(other) - set(symbols))
    shared = sorted(set(symbols) & set(other))

    # 覆盖三类：跨版本有差异的符号、顶层函数（pandas.concat 等）、常用类方法
    top_level = [s for s in shared if s.count(".") == 1]
    methods = [s for s in shared if s.startswith(("pandas.DataFrame.", "pandas.Series."))]
    picked = (
        [symbols[n] for n in only_here[:max_removed]]
        + [symbols[n] for n in top_level[:max_top_level]]
        + [symbols[n] for n in methods[:max_shared]]
    )
    seen, unique = set(), []
    for sym in picked:
        if sym.name not in seen:
            seen.add(sym.name)
            unique.append(sym)
    return unique


def fetch_library(
    library: str,
    versions: dict[str, str],
    workers: int = 8,
    limit_pandas: int | None = None,
) -> list[RawPage]:
    """抓取一个库的全部版本页面"""
    inventories = {v: api_symbols(library, v) for v in versions}
    results: list[RawPage] = []

    for version in versions:
        if library == "pandas":
            others = [inv for v, inv in inventories.items() if v != version]
            merged_other: dict[str, Symbol] = {}
            for other in others:
                merged_other.update(other)
            targets = select_pandas_symbols(inventories[version], merged_other)
            if limit_pandas:
                targets = targets[:limit_pandas]
            jobs = [(sym.name, urljoin(base_url(library, version), sym.page)) for sym in targets]
        else:
            jobs = [(sec, urljoin(base_url(library, version), sec)) for sec in SQLALCHEMY_SECTIONS]

        def work(job: tuple[str, str]) -> RawPage:
            name, url = job
            dest = _cache_path(library, version, name)
            try:
                with httpx.Client(timeout=60, follow_redirects=True) as client:
                    status, size = _download(client, url, dest)
            except Exception as exc:  # 单页失败不影响整体
                return RawPage(library, version, "symbol", name, url, 0, f"@{type(exc).__name__}", 0)
            kind = "symbol" if library == "pandas" else "section"
            rel = str(dest.relative_to(Path(get_settings().RAW_DIR))) if status == 200 else f"@missing:{status}"
            return RawPage(library, version, kind, name, url, status, rel, size)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            results.extend(pool.map(work, jobs))
        time.sleep(0.2)

    return results


def save_manifest(pages: list[RawPage]) -> Path:
    """写入抓取清单。

    合并而不是覆盖：按 (library, version, name) 去重。
    否则单独补抓一个库（--lib pandas）会把另一个库的记录整条抹掉，
    导致重建索引后对方库的 chunk 全部消失。
    """
    path = Path(get_settings().RAW_DIR) / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)

    merged: dict[tuple[str, str, str], dict] = {}
    if path.exists():
        try:
            for item in json.loads(path.read_text(encoding="utf-8")):
                merged[(item["library"], item["version"], item["name"])] = item
        except (json.JSONDecodeError, KeyError):
            merged = {}  # 旧清单损坏则重新开始
    for page in pages:
        record = asdict(page)
        merged[(record["library"], record["version"], record["name"])] = record

    ordered = sorted(merged.values(), key=lambda r: (r["library"], r["version"], r["name"]))
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
