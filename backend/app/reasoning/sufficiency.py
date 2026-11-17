"""证据充分性判断：决定「回答」还是「拒答」。

三个拒答条件（任一成立即拒答，并给出可解释原因）：
1. 相关性不足：最佳向量相似度低于阈值（阈值应来自评测，不拍脑袋）
2. 符号未覆盖：查询点名了某个 API 符号，但知识库里没有
3. 跨版本冲突且用户未指定版本：不替用户选择，返回结构化冲突
"""
import re
from dataclasses import dataclass, field

from backend.app.config import get_settings

# 形似 API 符号的 token：至少含一个点，两侧是标识符
SYMBOL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+)\b")

# 常见但并非 API 符号的写法
STOPWORDS = {"e.g", "i.e", "etc", "vs", "v1", "v2", "u.s"}


@dataclass
class Sufficiency:
    ok: bool
    status: str                       # answer / refused / conflict
    reasons: list[str] = field(default_factory=list)
    mentioned_symbols: list[str] = field(default_factory=list)
    unknown_symbols: list[str] = field(default_factory=list)
    top_score: float | None = None
    threshold: float = 0.0


def extract_symbols(query: str) -> list[str]:
    """从自然语言里抽取可能被点名的符号"""
    found = []
    for match in SYMBOL_RE.findall(query):
        if match.lower() in STOPWORDS:
            continue
        found.append(match)
    return found


def known_symbols(chunks_all: dict[str, dict]) -> set[str]:
    return {c["symbol"] for c in chunks_all.values() if c.get("symbol")}


def normalize_symbol(token: str, chunks_all: dict[str, dict]) -> str | None:
    """把用户写法对齐到知识库符号：忽略大小写，允许只写「类名.方法名」"""
    symbols = known_symbols(chunks_all)
    if token in symbols:
        return token
    low = token.lower()
    for sym in symbols:
        if sym.lower() == low or sym.lower().endswith("." + low):
            return sym
    return None


def judge(
    query: str,
    top_vector_score: float | None,
    retrieved_chunks: list[dict],
    conflicts: list[dict],
    versions_specified: bool,
    chunks_all: dict[str, dict],
) -> Sufficiency:
    settings = get_settings()
    threshold = settings.MIN_RELEVANCE
    reasons: list[str] = []

    mentioned = extract_symbols(query)
    unknown = [s for s in mentioned if normalize_symbol(s, chunks_all) is None]

    # 用户直接点名了知识库里的符号：这是比相似度更强的相关性证据
    # （例如 "engine.Engine 的 echo 参数" 的向量分可能只比阈值低一点，
    #  但文档块确实存在，此时拒答属于误伤）
    symbol_covered = bool(mentioned) and not unknown

    score_text = (
        f"检索到的最佳片段相似度 {top_vector_score:.3f}"
        if top_vector_score is not None
        else "没有检索到任何片段"
    )
    low_relevance = (top_vector_score is None or top_vector_score < threshold) and not symbol_covered

    # 条件 2：点名了符号，但知识库没有
    if unknown:
        libraries = sorted({c["library"] for c in chunks_all.values()})
        reasons.append(
            f"查询中的符号 {', '.join(unknown[:3])} 不在当前知识库覆盖范围内"
            f"（已索引库：{', '.join(libraries)}）"
        )

    # 条件 1：相关性不足
    if low_relevance:
        reasons.append(score_text)
        reasons.append(f"低于相关性下限 {threshold}，无法保证答案有据可依")

    # 条件 3：冲突且未指定版本 —— 优先级最高，返回结构化冲突而不是拒答
    if conflicts and not versions_specified:
        reasons.append(
            f"检索结果中 {len(conflicts)} 个符号在不同版本间存在不一致，且未指定版本；"
            "不替你选择「最新版本」"
        )
        return Sufficiency(
            ok=False,
            status="conflict",
            reasons=reasons,
            mentioned_symbols=mentioned,
            unknown_symbols=unknown,
            top_score=top_vector_score,
            threshold=threshold,
        )

    if unknown or low_relevance or not retrieved_chunks:
        if not retrieved_chunks and not reasons:
            reasons.append("没有检索到任何片段")
        return Sufficiency(
            ok=False,
            status="refused",
            reasons=reasons,
            mentioned_symbols=mentioned,
            unknown_symbols=unknown,
            top_score=top_vector_score,
            threshold=threshold,
        )

    return Sufficiency(
        ok=True,
        status="answer",
        mentioned_symbols=mentioned,
        top_score=top_vector_score,
        threshold=threshold,
    )
