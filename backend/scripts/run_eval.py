"""第 6 步：版本敏感评测

对比三种版本过滤方式（pre / post / none）的：
- Recall@K：期望符号是否出现在前 K 条检索结果里
- 状态准确率：answer / conflict / refused 是否符合预期
- 拒答率、冲突误报率

结果写入 backend/data/eval/results.json，评测页读取展示。

用法：
    python backend/scripts/run_eval.py
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.app.config import get_settings  # noqa: E402
from backend.app.pipeline import answer_question  # noqa: E402
from backend.app.retrieval.hybrid import ensure_indexes_loaded, retrieve  # noqa: E402
from backend.app.retrieval.vector_store import vector_index  # noqa: E402

MODES = ["pre", "post", "none"]
TOP_K = 4


def load_cases(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def recall_at_k(case: dict, mode: str) -> tuple[bool | None, list[str]]:
    """期望符号是否出现在前 K 条检索结果中（无期望符号的题不计入 Recall）"""
    symbol = case.get("expect_symbol")
    if not symbol:
        return None, []
    result = retrieve(
        case["query"],
        library=case.get("library"),
        versions=[case["version"]] if case.get("version") else None,
        mode=mode,
        top_k=TOP_K,
    )
    symbols = [item.chunk["symbol"] for item in result.items]
    hit = symbol in symbols
    return hit, symbols


def main() -> None:
    settings = get_settings()
    ensure_indexes_loaded()
    cases_path = Path(settings.EVAL_DIR) / "questions.jsonl"
    if not cases_path.exists():
        print(f"[ERROR] 找不到评测集 {cases_path}")
        sys.exit(1)
    cases = load_cases(cases_path)
    print(f"[eval] {len(cases)} 道题，模式 {MODES}")

    started = time.perf_counter()
    per_mode: dict[str, dict] = {}
    detail_rows = []

    for mode in MODES:
        recall_hits = recall_total = 0
        status_ok = 0
        conflicts = refusals = 0
        for case in cases:
            hit, symbols = recall_at_k(case, mode)
            if hit is not None:
                recall_total += 1
                recall_hits += int(hit)

            answer = answer_question(
                case["query"],
                library=case.get("library"),
                version=case.get("version"),
                mode=mode,
                top_k=TOP_K,
            )
            ok = answer.status == case["expect_status"]
            status_ok += int(ok)
            conflicts += int(answer.status == "conflict")
            refusals += int(answer.status == "refused")
            if mode == "pre":
                detail_rows.append(
                    {
                        "id": case["id"],
                        "query": case["query"],
                        "library": case.get("library"),
                        "version": case.get("version"),
                        "expect_status": case["expect_status"],
                        "actual_status": answer.status,
                        "status_ok": ok,
                        "expect_symbol": case.get("expect_symbol"),
                        "recall_hit": hit,
                        "top_symbols": symbols[:TOP_K],
                        "top_score": answer.meta.get("top_vector_score"),
                        "used_llm": answer.meta.get("used_llm"),
                        "note": answer.meta.get("generation_note"),
                        "reasons": answer.reasons,
                    }
                )

        per_mode[mode] = {
            "recall_at_k": round(recall_hits / recall_total, 3) if recall_total else None,
            "recall_evaluated": recall_total,
            "status_accuracy": round(status_ok / len(cases), 3),
            "conflict_rate": round(conflicts / len(cases), 3),
            "refusal_rate": round(refusals / len(cases), 3),
        }
        print(f"   {mode:5} recall@{TOP_K}={per_mode[mode]['recall_at_k']} "
              f"status_acc={per_mode[mode]['status_accuracy']} "
              f"conflict={per_mode[mode]['conflict_rate']} refusal={per_mode[mode]['refusal_rate']}")

    # 冲突误报：期望不是 conflict，但实际返回了 conflict
    false_conflicts = [r for r in detail_rows if r["actual_status"] == "conflict" and r["expect_status"] != "conflict"]
    missed_conflicts = [r for r in detail_rows if r["expect_status"] == "conflict" and r["actual_status"] != "conflict"]
    expected_answers = [r for r in detail_rows if r["expect_status"] == "answer"]
    false_refusals = [r for r in expected_answers if r["actual_status"] == "refused"]

    # 生成模式统计：区分「真实模型回答」与「模型不可用的文档摘录兜底」
    answered_rows = [r for r in detail_rows if r["actual_status"] == "answer"]
    llm_calls = sum(1 for r in answered_rows if r["used_llm"] is True)
    fallbacks = sum(1 for r in answered_rows if r["used_llm"] is False)

    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cases": len(cases),
        "top_k": TOP_K,
        "threshold": settings.MIN_RELEVANCE,
        "embedding_model": settings.EMBEDDING_MODEL,
        "llm_model": settings.OPENAI_MODEL,
        "index": vector_index.stats(),
        "modes": per_mode,
        "errors": {
            "conflict_false_positive": len(false_conflicts),
            "conflict_missed": len(missed_conflicts),
            "false_refusal": len(false_refusals),
        },
        "details": detail_rows,
        "generation": {
            "answers": len(answered_rows),
            "llm_calls": llm_calls,
            "fallbacks": fallbacks,
        },
        "elapsed_s": round(time.perf_counter() - started, 1),
    }

    out = Path(settings.EVAL_DIR) / "results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[eval] 误报冲突 {len(false_conflicts)}，漏报冲突 {len(missed_conflicts)}，误拒答 {len(false_refusals)}")
    print(f"[eval] 生成：{llm_calls} 次真实模型调用，{fallbacks} 次退化为文档摘录")
    print(f"[eval] 结果写入 {out}（耗时 {summary['elapsed_s']}s）")


if __name__ == "__main__":
    main()
