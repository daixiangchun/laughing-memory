"""按「符号」切分 Sphinx 文档：一个 API 符号一个 chunk。

为什么不用固定 token 切分：
- 固定长度会切断代码示例和参数表，检索到的片段自相矛盾；
- 按符号切天然对齐版本：同一 symbol 在不同版本可逐字段比较，这是冲突检测的前提。
"""
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from backend.app.config import LIBRARIES, PANDAS_BASE, SQLALCHEMY_BASE

DEPRECATION_HINTS = (
    "deprecated",
    "will be removed",
    "has been removed",
    "no longer available",
    "removed in",
)


@dataclass
class Chunk:
    """一个符号在一个版本下的文档块"""
    library: str
    version: str
    symbol: str
    role: str
    signature: str
    params: list[str] = field(default_factory=list)
    text: str = ""
    code: str = ""
    deprecated: bool = False
    deprecation_note: str = ""
    source_url: str = ""
    section_title: str = ""
    doc_type: str = "symbol"

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def chunk_id(self) -> str:
        return f"{self.library}@{self.version}::{self.symbol}"


def _norm_signature(dt) -> str:
    if dt is None:
        return ""
    text = dt.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).replace(" ( ", "(").replace(" )", ")")


def _parse_params(dt) -> list[str]:
    if dt is None:
        return []
    params = []
    for em in dt.select("em.sig-param"):
        name_span = em.select_one("span.n")
        raw = (name_span or em).get_text("", strip=True)
        name = raw.split("=")[0].strip().strip("*").strip()
        if name:
            params.append(name)
    return params


def _clean_text(dd) -> str:
    if dd is None:
        return ""
    clone = BeautifulSoup(str(dd), "lxml")
    for tag in clone.select("pre, dl, table, script, style"):
        tag.decompose()
    text = clone.get_text("\n", strip=True)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def _extract_code(dd) -> str:
    if dd is None:
        return ""
    blocks = []
    for pre in dd.select("pre"):
        code = pre.get_text("\n", strip=True)
        if code:
            blocks.append(code)
        if len(blocks) >= 3:
            break
    return "\n\n".join(blocks)


def _deprecation(dd, soup) -> tuple[bool, str]:
    if dd is None:
        return False, ""
    for tag in dd.select(".deprecated, .versionmodified"):
        note = tag.get_text(" ", strip=True)
        return True, note[:400]
    text = dd.get_text(" ", strip=True)[:2000].lower()
    if any(h in text for h in DEPRECATION_HINTS):
        for para in dd.find_all("p", limit=6):
            p = para.get_text(" ", strip=True)
            if any(h in p.lower() for h in DEPRECATION_HINTS):
                return True, p[:400]
        return True, ""
    return False, ""


def _section_title(soup) -> str:
    h1 = soup.find("h1")
    return h1.get_text(" ", strip=True) if h1 else ""


def parse_pandas_page(html: str, library: str, version: str, symbol: str, url: str) -> list[Chunk]:
    """pandas：一个符号一页，取 id 匹配的那个 dl"""
    soup = BeautifulSoup(html, "lxml")
    dls = soup.select("dl.py")
    if not dls:
        return []
    target = None
    for dl in dls:
        dt = dl.find("dt")
        if dt and dt.get("id") == symbol:
            target = dl
            break
    target = target or dls[0]
    dt = target.find("dt")
    dd = target.find("dd")
    deprecated, note = _deprecation(dd, soup)
    return [
        Chunk(
            library=library,
            version=version,
            symbol=symbol,
            role="method" if "." in symbol.split("pandas.")[-1] else "object",
            signature=_norm_signature(dt),
            params=_parse_params(dt),
            text=_clean_text(dd),
            code=_extract_code(dd),
            deprecated=deprecated,
            deprecation_note=note,
            source_url=url,
            section_title=_section_title(soup),
        )
    ]


def parse_sqlalchemy_page(html: str, library: str, version: str, url: str) -> list[Chunk]:
    """SQLAlchemy：章节页包含多个 dl.py，每个符号一块"""
    soup = BeautifulSoup(html, "lxml")
    title = _section_title(soup)
    chunks = []
    for dl in soup.select("dl.py"):
        dt = dl.find("dt")
        if dt is None:
            continue
        symbol = dt.get("id") or ""
        if not symbol.startswith("sqlalchemy"):
            continue
        dd = dl.find("dd")
        deprecated, note = _deprecation(dd, soup)
        classes = " ".join(dl.get("class", []))
        role = "class" if "class" in classes else "function" if "function" in classes else "method"
        chunks.append(
            Chunk(
                library=library,
                version=version,
                symbol=symbol,
                role=role,
                signature=_norm_signature(dt),
                params=_parse_params(dt),
                text=_clean_text(dd),
                code=_extract_code(dd),
                deprecated=deprecated,
                deprecation_note=note,
                source_url=f"{url}#{symbol}",
                section_title=title,
            )
        )
    return chunks


def missing_chunk(library: str, version: str, symbol: str, version_url: str) -> Chunk:
    """符号在该版本不存在时的占位块。

    证据来自该版本官方的 objects.inv 符号清单（权威），而不是「页面打不开」。
    """
    return Chunk(
        library=library,
        version=version,
        symbol=symbol,
        role="missing",
        signature="",
        text=f"该版本（{version}）的官方 API 索引中不存在符号 {symbol}。",
        source_url=version_url,
        doc_type="missing",
    )


def version_base(library: str, version: str) -> str:
    seg = LIBRARIES[library][version]
    return PANDAS_BASE.format(seg=seg) if library == "pandas" else SQLALCHEMY_BASE.format(seg=seg)


def chunk_manifest(manifest: list[dict], raw_root: Path) -> list[Chunk]:
    """遍历抓取清单，生成全部 chunk（含缺失符号的占位块）"""
    chunks: list[Chunk] = []
    present: dict[tuple[str, str], set[str]] = {}
    expected: dict[tuple[str, str], set[str]] = {}

    for item in manifest:
        key = (item["library"], item["version"])
        expected.setdefault(key, set()).add(item["name"])
        if item["status"] != 200 or item["path"].startswith("@"):
            continue
        html = (raw_root / item["path"]).read_text(encoding="utf-8", errors="ignore")
        if item["library"] == "pandas":
            parsed = parse_pandas_page(html, item["library"], item["version"], item["name"], item["url"])
        else:
            parsed = parse_sqlalchemy_page(html, item["library"], item["version"], item["url"])
        if parsed:
            present.setdefault(key, set()).update(c.symbol for c in parsed)
            chunks.extend(parsed)

    # 该库所有版本出现过的符号，若在某版本缺失，补占位块
    for (library, version), _ in expected.items():
        all_versions = [v for (lib, v) in expected if lib == library]
        union: set[str] = set()
        for v in all_versions:
            union |= present.get((library, v), set())
        for symbol in sorted(union - present.get((library, version), set())):
            chunks.append(missing_chunk(library, version, symbol, version_base(library, version)))

    return chunks
