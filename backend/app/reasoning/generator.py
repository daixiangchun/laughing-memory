"""答案生成：强制每条结论带 source_url + version；冲突未解决时不让模型自己选。"""
import re
from dataclasses import dataclass

from langchain_core.messages import HumanMessage, SystemMessage

from backend.app.config import get_settings
from backend.app.core.llm_client import llm_client
from backend.app.core.exceptions import ConfigurationError

SYSTEM_PROMPT = """你是 Python 官方文档问答助手。规则：
1. 只能依据「上下文」回答，不得使用上下文之外的知识。
2. 每条结论后必须标注来源，格式为 [版本: source_url]。
3. 上下文不足以回答时，明确说「文档中没有足够信息」，不要猜测。
4. 如果不同版本的说法不同，逐版本分别陈述，不要合并成一句，也不要推荐「最新版本」。
5. 用中文回答，代码原样保留。"""


@dataclass
class Generation:
    answer: str
    citations: list[dict]
    used_llm: bool
    note: str = ""


def build_context(items: list) -> str:
    """把检索结果拼成带版本与来源的上下文"""
    blocks = []
    for i, item in enumerate(items, 1):
        chunk = item.chunk if hasattr(item, "chunk") else item
        version = chunk.get("version", "")
        symbol = chunk.get("symbol", "")
        url = chunk.get("source_url", "")
        body = chunk.get("text") or ""
        if chunk.get("code"):
            body += "\n代码示例：\n" + chunk["code"][:800]
        blocks.append(
            f"[片段{i}] library={chunk.get('library','')} version={version} symbol={symbol}\n"
            f"来源：{url}\n{body[:1600]}"
        )
    return "\n\n".join(blocks)


def collect_citations(items: list) -> list[dict]:
    citations = []
    seen = set()
    for item in items:
        chunk = item.chunk if hasattr(item, "chunk") else item
        key = chunk.get("chunk_id") or f"{chunk.get('symbol')}@{chunk.get('version')}"
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            {
                "library": chunk.get("library"),
                "version": chunk.get("version"),
                "symbol": chunk.get("symbol"),
                "source_url": chunk.get("source_url"),
                "doc_type": chunk.get("doc_type", "symbol"),
            }
        )
    return citations


def extractive_answer(items: list) -> str:
    """没有可用大模型时的兜底：直接摘录文档原文并标注来源（不编造）"""
    lines = ["（未配置可用的大模型，以下为文档原文摘录）", ""]
    for item in items:
        chunk = item.chunk if hasattr(item, "chunk") else item
        head = f"【{chunk.get('library')} {chunk.get('version')} · {chunk.get('symbol')}】"
        text = (chunk.get("text") or "")[:500].replace("\n", " ")
        lines.append(f"{head} {text}")
        lines.append(f"来源：{chunk.get('source_url')}")
        lines.append("")
    return "\n".join(lines).strip()


def _validate_citations(answer: str, items: list) -> tuple[str, list[str]]:
    """检查模型输出里是否带版本与来源标注，缺失则在末尾补充说明"""
    versions = sorted({(i.chunk if hasattr(i, "chunk") else i).get("version", "") for i in items})
    warnings = []
    if versions and not any(v in answer for v in versions if v):
        warnings.append("模型回答未包含版本标注，已附加检索片段的版本信息")
        answer += "\n\n涉及版本：" + "、".join(v for v in versions if v)
    if "http" not in answer and items:
        warnings.append("模型回答未包含来源链接，已附加引用列表")
        refs = []
        for item in items[:4]:
            chunk = item.chunk if hasattr(item, "chunk") else item
            refs.append(f"- {chunk.get('symbol')}（{chunk.get('version')}）：{chunk.get('source_url')}")
        answer += "\n\n参考来源：\n" + "\n".join(refs)
    return answer, warnings


def generate(question: str, items: list) -> Generation:
    settings = get_settings()
    citations = collect_citations(items)

    try:
        llm = llm_client.get_client()
    except ConfigurationError as exc:
        return Generation(
            answer=extractive_answer(items),
            citations=citations,
            used_llm=False,
            note=f"{exc.message}，已改用文档摘录模式",
        )

    context = build_context(items)
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"上下文：\n{context}\n\n用户问题：{question}"),
    ]
    try:
        resp = llm.invoke(messages)
        answer = resp.content if hasattr(resp, "content") else str(resp)
    except Exception as exc:
        # 网络抖动、代理证书、密钥或模型名错误都不应该让问答整体失败：
        # 退化为「文档原文摘录」，并在 note 里说明原因，用户能看出答案来源不同。
        return Generation(
            answer=extractive_answer(items),
            citations=citations,
            used_llm=False,
            note=f"大模型调用失败（{type(exc).__name__}），已改用文档摘录模式",
        )

    answer, warnings = _validate_citations(answer.strip(), items)
    return Generation(answer=answer, citations=citations, used_llm=True, note="；".join(warnings))


def format_conflict(conflict) -> str:
    """把结构化冲突渲染成可直接展示的文本（不做结论）"""
    lines = [f"符号 {conflict.symbol} 在不同版本间不一致："]
    for reason in conflict.reasons:
        lines.append(f"- {reason}")
    lines.append("")
    for claim in conflict.claims:
        if not claim.exists:
            lines.append(f"**{claim.version}**：该版本官方 API 索引中不存在此符号。来源：{claim.source_url}")
            continue
        state = "已弃用" if claim.deprecated else "可用"
        lines.append(f"**{claim.version}**（{state}）：{claim.text[:220]}")
        if claim.deprecation_note:
            lines.append(f"  弃用说明：{claim.deprecation_note[:200]}")
        lines.append(f"  来源：{claim.source_url}")
        lines.append("")
    return "\n".join(lines).strip()
