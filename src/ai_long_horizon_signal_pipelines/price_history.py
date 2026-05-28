from __future__ import annotations

import csv
import datetime as dt
from dataclasses import dataclass
from pathlib import Path


DATE_COLUMNS = ("date", "as_of")


@dataclass(frozen=True)
class PriceRow:
    date: dt.date
    symbol: str
    close: float


@dataclass(frozen=True)
class PriceExtractionSummary:
    source: str
    target: str
    input_rows: int
    output_rows: int
    symbols: list[str]
    start_date: str | None
    end_date: str | None


def parse_price_date(value: object) -> dt.date:
    text = str(value or "").strip()
    if not text:
        raise ValueError("price date is required")
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return dt.datetime.fromisoformat(text).date()


def _resolve_date_column(fieldnames: list[str] | None) -> str:
    fields = set(fieldnames or [])
    for column in DATE_COLUMNS:
        if column in fields:
            return column
    expected = " or ".join(DATE_COLUMNS)
    raise ValueError(f"price history missing date column: expected {expected}")


def _normalize_symbols(symbols: list[str] | tuple[str, ...] | set[str] | str) -> list[str]:
    if isinstance(symbols, str):
        raw_symbols = symbols.split(",")
    else:
        raw_symbols = list(symbols)
    normalized: list[str] = []
    for symbol in raw_symbols:
        text = str(symbol or "").strip().upper()
        if text and text not in normalized:
            normalized.append(text)
    if not normalized:
        raise ValueError("at least one symbol is required")
    return normalized


def read_price_rows(
    path: str | Path,
    *,
    symbols: list[str] | tuple[str, ...] | set[str] | str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[PriceRow]:
    selected_symbols = set(_normalize_symbols(symbols))
    start = parse_price_date(start_date) if start_date else None
    end = parse_price_date(end_date) if end_date else None
    rows_by_key: dict[tuple[dt.date, str], PriceRow] = {}

    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"symbol", "close"}
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"price history missing columns: {', '.join(sorted(missing))}")
        date_column = _resolve_date_column(reader.fieldnames)

        for raw_row in reader:
            symbol = str(raw_row["symbol"]).strip().upper()
            if symbol not in selected_symbols:
                continue
            row_date = parse_price_date(raw_row[date_column])
            if start and row_date < start:
                continue
            if end and row_date > end:
                continue
            close = float(raw_row["close"])
            if close <= 0:
                raise ValueError(f"close must be positive for {symbol} on {row_date.isoformat()}")
            rows_by_key[(row_date, symbol)] = PriceRow(date=row_date, symbol=symbol, close=close)

    return [rows_by_key[key] for key in sorted(rows_by_key)]


def write_filtered_price_history(
    source: str | Path,
    target: str | Path,
    *,
    symbols: list[str] | tuple[str, ...] | set[str] | str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> PriceExtractionSummary:
    selected_symbols = _normalize_symbols(symbols)
    start = parse_price_date(start_date) if start_date else None
    end = parse_price_date(end_date) if end_date else None
    rows_by_key: dict[tuple[dt.date, str], PriceRow] = {}
    input_rows = 0

    with Path(source).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"symbol", "close"}
        missing = required.difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"price history missing columns: {', '.join(sorted(missing))}")
        date_column = _resolve_date_column(reader.fieldnames)

        for raw_row in reader:
            input_rows += 1
            symbol = str(raw_row["symbol"]).strip().upper()
            if symbol not in selected_symbols:
                continue
            row_date = parse_price_date(raw_row[date_column])
            if start and row_date < start:
                continue
            if end and row_date > end:
                continue
            close = float(raw_row["close"])
            if close <= 0:
                raise ValueError(f"close must be positive for {symbol} on {row_date.isoformat()}")
            rows_by_key[(row_date, symbol)] = PriceRow(date=row_date, symbol=symbol, close=close)

    output_path = Path(target)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [rows_by_key[key] for key in sorted(rows_by_key)]
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "symbol", "close"])
        writer.writeheader()
        for row in rows:
            writer.writerow({"date": row.date.isoformat(), "symbol": row.symbol, "close": row.close})

    return PriceExtractionSummary(
        source=str(source),
        target=str(target),
        input_rows=input_rows,
        output_rows=len(rows),
        symbols=selected_symbols,
        start_date=start.isoformat() if start else None,
        end_date=end.isoformat() if end else None,
    )
