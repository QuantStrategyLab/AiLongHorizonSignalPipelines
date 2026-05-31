#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DEFAULT_THEME_TAXONOMY = ROOT / "config" / "theme_taxonomy.csv"
DEFAULT_THEME_EXPOSURES = ROOT / "config" / "symbol_theme_exposure.csv"

from research_signal_context_pipelines.context_bundle import (  # noqa: E402
    DEFAULT_UNIVERSE,
    build_context_from_source,
    build_error_context_bundle,
    normalize_symbols,
    write_context_bundle,
)
from research_signal_context_pipelines.theme_universe import (  # noqa: E402
    build_theme_context,
    load_symbol_theme_exposure,
    load_theme_taxonomy,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build point-in-time context for long-horizon AI review.")
    parser.add_argument("--symbols", default=",".join(DEFAULT_UNIVERSE), help="Comma-separated symbol universe")
    parser.add_argument("--prices", help="Optional local CSV with symbol,close and date or as_of")
    parser.add_argument("--theme-taxonomy", default=str(DEFAULT_THEME_TAXONOMY), help="Theme taxonomy CSV path")
    parser.add_argument("--theme-exposures", default=str(DEFAULT_THEME_EXPOSURES), help="Symbol-to-theme exposure CSV path")
    parser.add_argument("--no-theme-context", action="store_true", help="Do not embed theme taxonomy/exposure context")
    parser.add_argument("--start-date", help="Optional inclusive YYYY-MM-DD lower bound")
    parser.add_argument("--end-date", help="Optional inclusive YYYY-MM-DD upper bound")
    parser.add_argument("--lookback-days", type=int, default=420)
    parser.add_argument(
        "--strict-downloads",
        action="store_true",
        help="Fail the whole bundle when any downloaded symbol is unavailable",
    )
    parser.add_argument(
        "--allow-download-errors",
        action="store_true",
        help="Write a degraded operator-notification context bundle instead of failing on download errors",
    )
    parser.add_argument(
        "--output",
        default="data/output/context_bundle/latest_context_bundle.json",
        help="Output JSON context bundle path",
    )
    args = parser.parse_args()

    symbols = normalize_symbols(args.symbols)
    theme_context = None
    if not args.no_theme_context:
        theme_taxonomy_path = Path(args.theme_taxonomy)
        theme_exposure_path = Path(args.theme_exposures)
        if theme_taxonomy_path.exists() and theme_exposure_path.exists():
            themes = load_theme_taxonomy(theme_taxonomy_path)
            exposures = load_symbol_theme_exposure(theme_exposure_path, known_theme_ids=themes)
            theme_context = build_theme_context(symbols=symbols, themes=themes, exposures=exposures)

    try:
        bundle = build_context_from_source(
            symbols=symbols,
            prices_path=Path(args.prices) if args.prices else None,
            start_date=args.start_date,
            end_date=args.end_date,
            lookback_days=args.lookback_days,
            theme_context=theme_context,
            allow_partial_downloads=not args.strict_downloads,
        )
    except Exception as exc:
        if not args.allow_download_errors:
            raise
        bundle = build_error_context_bundle(
            symbols=symbols,
            error=f"{type(exc).__name__}: {exc}",
            theme_context=theme_context,
        )
    output_path = Path(args.output)
    write_context_bundle(bundle, output_path)
    print(
        json.dumps(
            {
                "output": str(output_path),
                "as_of": bundle["as_of"],
                "symbols": bundle["universe"],
                "price_context_symbols": sorted(bundle.get("price_context", {})),
                "warnings": bundle.get("data_quality", {}).get("warnings", []),
                "errors": bundle.get("data_quality", {}).get("errors", []),
                "theme_coverage": bundle.get("theme_context", {}).get("coverage", {}),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
