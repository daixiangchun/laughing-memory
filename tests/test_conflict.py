"""冲突检测单元测试：构造跨版本记录，断言"什么算冲突、什么不算"。

对应「冲突不合并」这条决策：只比结构化事实（存在性、弃用标记、参数集合、签名），
不做语义猜测；任何一项不一致就返回冲突，而不是选最新版本。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.reasoning.conflict import compare_versions, resolve_conflicts  # noqa: E402


def chunk(version, *, exists=True, deprecated=False, params=None, signature="", library="pandas"):
    return {
        "library": library,
        "version": version,
        "symbol": "pandas.DataFrame.append",
        "doc_type": "symbol" if exists else "missing",
        "deprecated": deprecated,
        "params": params or [],
        "signature": signature,
        "text": "text",
        "source_url": f"https://example/{version}",
        "deprecation_note": "deprecated" if deprecated else "",
    }


def test_removed_in_newer_version_is_conflict():
    """2.2 已移除 append：存在性不一致必须判冲突"""
    conflict = compare_versions({
        "1.5.3": chunk("1.5.3", deprecated=True, params=["other", "sort"]),
        "2.2.0": chunk("2.2.0", exists=False),
    })
    assert conflict is not None
    assert any("存在性不一致" in r for r in conflict.reasons)
    assert {c.version for c in conflict.claims} == {"1.5.3", "2.2.0"}


def test_param_difference_is_conflict():
    conflict = compare_versions({
        "1.4": chunk("1.4", params=["bind"], library="sqlalchemy"),
        "2.0": chunk("2.0", params=["bind", "autobegin"], library="sqlalchemy"),
    })
    assert conflict is not None
    assert any("参数集合不一致" in r for r in conflict.reasons)


def test_deprecation_flag_difference_is_conflict():
    conflict = compare_versions({
        "1.5.3": chunk("1.5.3", deprecated=True),
        "2.2.0": chunk("2.2.0", deprecated=False),
    })
    assert conflict is not None
    assert any("弃用状态不一致" in r for r in conflict.reasons)


def test_identical_records_are_not_conflict():
    same = dict(params=["other"], signature="DataFrame.append(other)")
    assert compare_versions({"1.5.3": chunk("1.5.3", **same), "2.2.0": chunk("2.2.0", **same)}) is None


def test_single_version_is_never_conflict():
    assert compare_versions({"2.2.0": chunk("2.2.0")}) is None


def test_resolve_conflicts_groups_by_symbol_and_library():
    chunks = [
        chunk("1.5.3", deprecated=True),
        chunk("2.2.0", exists=False),
        # 另一个库的同名符号，不应与 pandas 混在一起比较
        chunk("1.4", library="sqlalchemy"),
        chunk("2.0", library="sqlalchemy"),
    ]
    conflicts = resolve_conflicts(chunks)
    assert len(conflicts) == 1
    assert conflicts[0].library == "pandas"
    assert len(conflicts[0].claims) == 2
