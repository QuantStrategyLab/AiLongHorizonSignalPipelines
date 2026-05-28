#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_long_horizon_signal_pipelines.price_history import write_filtered_price_history  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract a compact date,symbol,close CSV for overlay replay."
    )
    parser.add_argument("--source", required=True, help="Input CSV with symbol,close and date or as_of")
    parser.add_argument("--target", default="data/input/price_history.csv", help="Output CSV path")
    parser.add_argument("--symbols", default="QQQ", help="Comma-separated symbols to keep")
    parser.add_argument("--start-date", help="Optional inclusive YYYY-MM-DD lower bound")
    parser.add_argument("--end-date", help="Optional inclusive YYYY-MM-DD upper bound")
    args = parser.parse_args()

    summary = write_filtered_price_history(
        args.source,
        args.target,
        symbols=args.symbols,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    print(json.dumps(summary.__dict__, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
