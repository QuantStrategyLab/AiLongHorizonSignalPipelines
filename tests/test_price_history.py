from __future__ import annotations

import csv

from research_signal_context_pipelines.price_history import (
    parse_price_date,
    read_price_rows,
    write_filtered_price_history,
)


def test_parse_price_date_accepts_timestamp_text() -> None:
    assert parse_price_date("2026-01-02 00:00:00").isoformat() == "2026-01-02"
    assert parse_price_date("2026-01-02T21:00:00Z").isoformat() == "2026-01-02"


def test_write_filtered_price_history_extracts_compact_schema(tmp_path) -> None:
    source = tmp_path / "source.csv"
    source.write_text(
        "\n".join(
            [
                "symbol,as_of,close,open",
                "QQQ,2026-01-02,100,99",
                "SPY,2026-01-02,90,89",
                "QQQ,2026-01-05,101,100",
                "QQQ,2026-01-06,102,101",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    target = tmp_path / "out" / "prices.csv"

    summary = write_filtered_price_history(
        source,
        target,
        symbols="qqq",
        start_date="2026-01-03",
        end_date="2026-01-06",
    )

    with target.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    assert summary.input_rows == 4
    assert summary.output_rows == 2
    assert summary.symbols == ["QQQ"]
    assert rows == [
        {"date": "2026-01-05", "symbol": "QQQ", "close": "101.0"},
        {"date": "2026-01-06", "symbol": "QQQ", "close": "102.0"},
    ]


def test_read_price_rows_keeps_last_duplicate_date_symbol(tmp_path) -> None:
    source = tmp_path / "source.csv"
    source.write_text(
        "\n".join(
            [
                "date,symbol,close",
                "2026-01-02,QQQ,100",
                "2026-01-02,QQQ,101",
                "2026-01-05,QQQ,102",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = read_price_rows(source, symbols=["QQQ"])

    assert [row.close for row in rows] == [101.0, 102.0]
