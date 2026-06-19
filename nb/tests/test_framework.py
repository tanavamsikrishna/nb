import base64
import io

import polars as pl

from nb.framework import DisplayRecord, _create_display_record


def test_table_serialization() -> None:
    df = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    record = _create_display_record(df, "table")

    assert isinstance(record, DisplayRecord)
    assert record.type == "table"

    payload = record.payload
    assert "data" in payload
    assert "total_rows" in payload
    assert payload["total_rows"] == 3

    # Verify it's valid base64-encoded Parquet
    raw = base64.b64decode(payload["data"])
    buf = io.BytesIO(raw)
    result = pl.read_parquet(buf)
    assert result.equals(df)


def test_table_options_passed_through() -> None:
    df = pl.DataFrame({"x": [10, 20]})
    record = _create_display_record(df, "table", label="My table")
    assert record.payload["label"] == "My table"


def test_plain_dataframe_auto_table() -> None:
    """Plain Polars DataFrame should auto-detect as a table."""
    df = pl.DataFrame({"x": [10, 20]})
    record = _create_display_record(df)
    assert record.type == "table"


def test_str_defaults_to_text() -> None:
    record = _create_display_record("hello")
    assert record.type == "text"
    assert record.payload == "hello"


def test_explicit_md_and_html() -> None:
    assert _create_display_record("# h", "md") == DisplayRecord(type="md", payload="# h")
    assert _create_display_record("<p>", "html") == DisplayRecord(type="html", payload="<p>")
    assert _create_display_record("# h", "text") == DisplayRecord(type="text", payload="# h")


def test_object_fallback() -> None:
    """Non-str, non-special objects fall back to a serialized object record."""
    record = _create_display_record({"k": "v", "n": [1, 2]})
    assert record.type == "object"
    assert record.payload == {"k": "v", "n": [1, 2]}


def test_explicit_object() -> None:
    record = _create_display_record({"a": 1}, "object")
    assert record.type == "object"
    assert record.payload == {"a": 1}
