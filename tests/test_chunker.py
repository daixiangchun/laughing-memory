"""切分器单元测试：不联网，用最小 HTML 片段验证抽取逻辑。

对应「按符号切分」这条技术决策：一个 API 符号一个 chunk，
签名、参数、弃用标记都要能稳定抽出来，否则跨版本对齐无从谈起。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.ingestion.chunker import (  # noqa: E402
    chunk_manifest,
    missing_chunk,
    parse_sqlalchemy_page,
)

PANDAS_HTML = """
<html><body><h1>pandas.DataFrame.append</h1>
<dl class="py method">
  <dt class="sig sig-object py" id="pandas.DataFrame.append">
    <span class="sig-prename descclassname">DataFrame.</span><span class="sig-name descname">append</span>
    <span class="sig-paren">(</span>
    <em class="sig-param"><span class="n">other</span></em>,
    <em class="sig-param"><span class="n">ignore_index</span><span class="o">=</span><span class="default_value">False</span></em>,
    <em class="sig-param"><span class="n">sort</span><span class="o">=</span><span class="default_value">False</span></em>
    <span class="sig-paren">)</span>
  </dt>
  <dd>
    <p>Append rows of <em>other</em> to the end of caller.</p>
    <div class="deprecated"><p>Deprecated since version 1.4.0: Use concat() instead.</p></div>
    <pre>df.append(other)</pre>
  </dd>
</dl></body></html>
"""

SQLALCHEMY_HTML = """
<html><body><h1>Session API</h1>
<dl class="py class">
  <dt class="sig sig-object py" id="sqlalchemy.orm.Session">
    <span class="sig-name descname">Session</span>
    <span class="sig-paren">(</span><em class="sig-param"><span class="n">bind</span></em><span class="sig-paren">)</span>
  </dt>
  <dd><p>The Session class.</p></dd>
</dl>
<dl class="py method">
  <dt class="sig sig-object py" id="sqlalchemy.orm.Session.commit">
    <span class="sig-name descname">commit</span><span class="sig-paren">(</span><span class="sig-paren">)</span>
  </dt>
  <dd><p>Flush and commit.</p></dd>
</dl>
</body></html>
"""


def test_sqlalchemy_page_yields_one_chunk_per_symbol(tmp_path):
    chunks = parse_sqlalchemy_page(SQLALCHEMY_HTML, "sqlalchemy", "2.0", "https://x/orm/session_api.html")
    symbols = {c.symbol for c in chunks}
    assert symbols == {"sqlalchemy.orm.Session", "sqlalchemy.orm.Session.commit"}

    session = next(c for c in chunks if c.symbol == "sqlalchemy.orm.Session")
    assert session.params == ["bind"]
    assert session.source_url.endswith("#sqlalchemy.orm.Session")
    assert session.deprecated is False


def test_params_parsed_from_signature(tmp_path):
    raw = tmp_path / "p.html"
    raw.write_text(PANDAS_HTML, encoding="utf-8")
    manifest = [{
        "library": "pandas", "version": "1.5.3", "name": "pandas.DataFrame.append",
        "kind": "symbol", "url": "https://pandas/x.html", "status": 200,
        "path": "p.html", "bytes": 1,
    }]
    chunks = chunk_manifest(manifest, tmp_path)
    chunk = next(c for c in chunks if c.symbol == "pandas.DataFrame.append")
    assert chunk.params == ["other", "ignore_index", "sort"]
    assert chunk.deprecated is True
    assert "concat" in chunk.deprecation_note
    assert "Append rows" in chunk.text
    assert "df.append(other)" in chunk.code


def test_missing_record_is_marked(tmp_path):
    """某版本缺失的符号必须留痕：doc_type=missing 且给出该版本文档地址"""
    raw = tmp_path
    (raw / "only15.html").write_text(PANDAS_HTML, encoding="utf-8")
    manifest = [
        {"library": "pandas", "version": "1.5.3", "name": "pandas.DataFrame.append",
         "kind": "symbol", "url": "https://pandas/1.5/x.html", "status": 200,
         "path": "only15.html", "bytes": 1},
        {"library": "pandas", "version": "2.2.0", "name": "pandas.DataFrame.append",
         "kind": "symbol", "url": "https://pandas/2.2/x.html", "status": 404,
         "path": "@missing:404", "bytes": 0},
    ]
    chunks = chunk_manifest(manifest, raw)
    missing = [c for c in chunks if c.version == "2.2.0"]
    assert len(missing) == 1
    assert missing[0].doc_type == "missing"
    assert "2.2.0" in missing[0].text
    assert missing[0].source_url.startswith("https://pandas.pydata.org")


def test_missing_chunk_shape():
    chunk = missing_chunk("pandas", "2.2.0", "pandas.DataFrame.append", "https://pandas/2.2/")
    assert chunk.doc_type == "missing"
    assert chunk.symbol == "pandas.DataFrame.append"
    assert chunk.chunk_id == "pandas@2.2.0::pandas.DataFrame.append"
