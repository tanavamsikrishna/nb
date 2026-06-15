import base64
import io

import polars as pl
import pytest

from nb.framework import Table, DisplayRecord, _create_display_record


def test_table_dataclass():
    df = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    table = Table(df)
    assert table.df is df


def test_table_serialization():
    df = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
    record = _create_display_record(Table(df))

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


def test_table_auto_dispatch():
    """Table should be dispatched before plain Polars DataFrame."""
    df = pl.DataFrame({"x": [10, 20]})
    record = _create_display_record(Table(df))
    assert record.type == "table"


def test_plain_dataframe_still_html():
    """Plain Polars DataFrame (not wrapped) should still render as table."""
    df = pl.DataFrame({"x": [10, 20]})
    record = _create_display_record(df)
    assert record.type == "table"
