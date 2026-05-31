#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DEFAULT_THEME_TAXONOMY = ROOT / "config" / "theme_taxonomy.csv"
DEFAULT_THEME_EXPOSURES = ROOT / "config" / "symbol_theme_exposure.csv"

from ai_long_horizon_signal_pipelines.context_bundle import download_price_rows  # noqa: E402
from ai_long_horizon_signal_pipelines.price_history import parse_price_date, read_price_rows  # noqa: E402
from ai_long_horizon_signal_pipelines.theme_momentum import (  # noqa: E402
    build_theme_momentum_snapshot,
    write_theme_momentum_snapshot,
)
from ai_long_horizon_signal_pipelines.theme_universe import (  # noqa: E402
    load_symbol_theme_exposure,
    load_theme_taxonomy,
)


def display_path(path: str | Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_symbols(value: str | None, default_symbols: list[str]) -> list[str]:
    if not value:
        return default_symbols
    symbols: list[str] = []
    for raw in value.split(","):
        symbol = raw.strip().upper()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    if not symbols:
        raise ValueError("--symbols must include at least one symbol")
    return symbols


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a point-in-time cross-sector theme momentum snapshot.")
    parser.add_argument("--prices", help="Optional price CSV with date/as_of,symbol,close columns. If omitted, Yahoo chart data is downloaded.")
    parser.add_argument("--symbols", help="Optional comma-separated symbols. Defaults to all symbols in theme exposure config.")
    parser.add_argument("--as-of", help="Optional inclusive YYYY-MM-DD cutoff for prices")
    parser.add_argument("--start-date", help="Optional inclusive YYYY-MM-DD lower bound for prices")
    parser.add_argument("--lookback-days", type=int, default=420, help="Calendar-day lookback used when downloading prices")
    parser.add_argument("--strict-downloads", action="store_true", help="Fail when any downloaded symbol is unavailable")
    parser.add_argument("--theme-taxonomy", default=str(DEFAULT_THEME_TAXONOMY), help="Theme taxonomy CSV path")
    parser.add_argument("--theme-exposures", default=str(DEFAULT_THEME_EXPOSURES), help="Symbol-to-theme exposure CSV path")
    parser.add_argument("--top-symbols-per-theme", type=int, default=5)
    parser.add_argument("--output", default="data/output/theme_momentum_snapshot.json", help="Output JSON path")
    args = parser.parse_args()

    themes = load_theme_taxonomy(args.theme_taxonomy)
    exposures = load_symbol_theme_exposure(args.theme_exposures, known_theme_ids=themes)
    symbols = normalize_symbols(args.symbols, sorted(exposures))
    source_artifacts = {
        "theme_taxonomy": display_path(args.theme_taxonomy),
        "theme_exposures": display_path(args.theme_exposures),
    }
    if args.prices:
        prices_path = Path(args.prices)
        rows = read_price_rows(prices_path, symbols=symbols, start_date=args.start_date, end_date=args.as_of)
        source_artifacts["prices"] = display_path(prices_path)
        source_artifacts["prices_sha256"] = sha256_file(prices_path)
    else:
        source_artifacts["prices"] = "yahoo_chart_download"
        end = parse_price_date(args.as_of) if args.as_of else None
        if args.start_date:
            start = parse_price_date(args.start_date)
        elif end:
            start = end - dt.timedelta(days=args.lookback_days)
        else:
            start = dt.date.today() - dt.timedelta(days=args.lookback_days)
        rows = download_price_rows(symbols, start=start, end=end, allow_partial=not args.strict_downloads)
    snapshot = build_theme_momentum_snapshot(
        rows,
        themes=themes,
        exposures={symbol: exposure for symbol, exposure in exposures.items() if symbol in set(symbols)},
        as_of=args.as_of,
        top_symbols_per_theme=args.top_symbols_per_theme,
    )
    snapshot["source_artifacts"] = source_artifacts
    output_path = write_theme_momentum_snapshot(snapshot, args.output)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "as_of": snapshot["as_of"],
                "ranked_theme_count": snapshot["summary"]["ranked_theme_count"],
                "priced_symbol_count": snapshot["summary"]["priced_symbol_count"],
                "top_theme_ids": snapshot["summary"]["top_theme_ids"],
                "price_coverage_ratio": snapshot["data_quality"]["coverage"]["price_coverage_ratio"],
                "missing_price_symbols": snapshot["data_quality"]["missing_price_symbols"],
                "insufficient_history_symbols": snapshot["data_quality"].get("insufficient_history_symbols", []),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
