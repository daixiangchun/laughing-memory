"""解析 Sphinx objects.inv：拿到「某版本有哪些 API 符号、各自在哪个页面」。

objects.inv 是 zlib 压缩的符号清单，比抓 HTML 页面再猜符号可靠得多，
也是判定「某符号在某版本是否存在」的权威依据。
"""
import zlib
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from backend.app.config import LIBRARIES, PANDAS_BASE, SQLALCHEMY_BASE

ROLE_PREFIXES = ("py:method", "py:function", "py:class", "py:attribute", "py:exception", "py:data")


@dataclass(frozen=True)
class Symbol:
    """一个 API 符号在文档中的位置"""
    name: str      # 例如 pandas.DataFrame.append
    role: str      # py:method / py:class ...
    page: str      # 相对页面路径，例如 reference/api/pandas.DataFrame.append.html


def _read_inventory(body: bytes) -> dict[str, Symbol]:
    """解压并解析 objects.inv（前 4 行为头部）"""
    pos = 0
    for _ in range(4):
        pos = body.find(b"\n", pos) + 1
    text = zlib.decompress(body[pos:]).decode("utf-8", "replace")

    symbols: dict[str, Symbol] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 5 or not parts[1].startswith(ROLE_PREFIXES):
            continue
        name, role, uri = parts[0], parts[1], parts[3]
        if "#" in uri:          # 去掉锚点，只保留页面
            uri = uri.split("#")[0]
        if not uri.endswith(".html"):
            continue
        symbols[name] = Symbol(name=name, role=role, page=uri)
    return symbols


def base_url(library: str, version: str) -> str:
    seg = LIBRARIES[library][version]
    return PANDAS_BASE.format(seg=seg) if library == "pandas" else SQLALCHEMY_BASE.format(seg=seg)


def fetch_inventory(library: str, version: str, client: httpx.Client | None = None) -> dict[str, Symbol]:
    """下载并解析某库某版本的符号清单"""
    url = urljoin(base_url(library, version), "objects.inv")
    own = client is None
    client = client or httpx.Client(timeout=60, follow_redirects=True)
    try:
        resp = client.get(url)
        resp.raise_for_status()
        return _read_inventory(resp.content)
    finally:
        if own:
            client.close()


def api_symbols(library: str, version: str) -> dict[str, Symbol]:
    """只保留公开 API 的符号（排除开发文档、教程等）"""
    symbols = fetch_inventory(library, version)
    if library == "pandas":
        return {k: v for k, v in symbols.items() if v.page.startswith("reference/api/")}
    return symbols
