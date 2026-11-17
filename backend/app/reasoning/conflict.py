"""跨版本一致性校验：以「结构化字段」为主，不做语义猜测。

可选的结构化事实（都能从文档稳定抽取）：
- 符号是否存在（doc_type=missing 表示该版本官方索引中不存在）
- 是否标记为 deprecated / 已移除
- 参数集合是否一致（增删参数往往就是行为变化）
- 签名是否一致（作为补充信号）

任一事实不一致即判定为冲突；不选「最新版本」替用户做决定。
"""
from dataclasses import asdict, dataclass, field
from itertools import combinations

# 参数差异中这些词表明「只是新增可选参数」，仍算差异，但会在说明里区分
OPTIONAL_HINTS = ("=", "none", "false", "true")


@dataclass
class Claim:
    """某版本对某符号的说法"""
    version: str
    exists: bool
    deprecated: bool
    signature: str
    params: list[str]
    text: str
    source_url: str
    deprecation_note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Conflict:
    symbol: str
    library: str
    reasons: list[str] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "library": self.library,
            "reasons": self.reasons,
            "claims": [c.to_dict() for c in self.claims],
        }


def _claim_from_chunk(chunk: dict) -> Claim:
    return Claim(
        version=chunk["version"],
        exists=chunk.get("doc_type") != "missing",
        deprecated=bool(chunk.get("deprecated")),
        signature=chunk.get("signature", ""),
        params=list(chunk.get("params", [])),
        text=(chunk.get("text") or "")[:600],
        source_url=chunk.get("source_url", ""),
        deprecation_note=chunk.get("deprecation_note", ""),
    )


def compare_versions(chunks_by_version: dict[str, dict]) -> Conflict | None:
    """输入 {version: chunk}，返回冲突（无冲突返回 None）"""
    if len(chunks_by_version) < 2:
        return None

    versions = sorted(chunks_by_version)
    claims = [_claim_from_chunk(chunks_by_version[v]) for v in versions]
    library = next(iter(chunks_by_version.values()))["library"]
    symbol = next(iter(chunks_by_version.values()))["symbol"]

    reasons: list[str] = []
    existence = {c.version: c.exists for c in claims}
    if len(set(existence.values())) > 1:
        missing = [v for v, ok in existence.items() if not ok]
        present = [v for v, ok in existence.items() if ok]
        reasons.append(
            f"符号存在性不一致：{', '.join(present)} 中存在，{', '.join(missing)} 中已不存在"
        )

    deprecated = {c.version: c.deprecated for c in claims}
    if len(set(deprecated.values())) > 1:
        yes = [v for v, d in deprecated.items() if d]
        reasons.append(f"弃用状态不一致：{', '.join(yes)} 标记为 deprecated，其余版本没有")

    # 只比较「两个版本都存在」的符号的参数，避免拿缺失版本空参数集误报
    existing = [c for c in claims if c.exists]
    if len(existing) >= 2:
        param_sets = {c.version: set(c.params) for c in existing}
        union = set().union(*param_sets.values())
        if union and any(param_sets[v] != union for v in param_sets):
            detail = []
            for a, b in combinations(sorted(param_sets), 2):
                only_a = sorted(param_sets[a] - param_sets[b])
                only_b = sorted(param_sets[b] - param_sets[a])
                if only_a or only_b:
                    bits = []
                    if only_a:
                        bits.append(f"仅 {a} 有 {', '.join(only_a)}")
                    if only_b:
                        bits.append(f"仅 {b} 有 {', '.join(only_b)}")
                    detail.append("；".join(bits))
            if detail:
                reasons.append("参数集合不一致：" + " | ".join(detail))

        sigs = {c.version: c.signature for c in existing if c.signature}
        if len(set(sigs.values())) > 1 and not any("参数集合不一致" in r for r in reasons):
            reasons.append("签名不一致（参数集合相同，但签名文本不同）")

    if not reasons:
        return None
    return Conflict(symbol=symbol, library=library, reasons=reasons, claims=claims)


def resolve_conflicts(chunks: list[dict]) -> list[Conflict]:
    """把同一批检索结果按 (library, symbol) 分组，逐符号做跨版本比较"""
    grouped: dict[tuple[str, str], dict[str, dict]] = {}
    for chunk in chunks:
        if chunk.get("doc_type") == "missing" and not chunk.get("symbol"):
            continue
        key = (chunk["library"], chunk["symbol"])
        grouped.setdefault(key, {})[chunk["version"]] = chunk

    conflicts = []
    for (_, symbol), by_version in grouped.items():
        conflict = compare_versions(by_version)
        if conflict:
            conflicts.append(conflict)
    conflicts.sort(key=lambda c: (-len(c.reasons), c.symbol))
    return conflicts


def conflicts_for_symbol(symbol: str, chunks_all: dict[str, dict]) -> Conflict | None:
    """精确查询某符号的全部版本记录（不依赖检索），用于「用户点名了符号」的场景"""
    by_version = {
        chunk["version"]: chunk
        for chunk in chunks_all.values()
        if chunk.get("symbol") == symbol
    }
    return compare_versions(by_version)
