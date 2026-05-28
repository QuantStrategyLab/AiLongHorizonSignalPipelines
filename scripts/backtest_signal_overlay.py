#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_long_horizon_signal_pipelines.overlay_backtest import (  # noqa: E402
    OverlayPolicy,
    backtest_overlay,
    load_price_history,
    load_signals,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay shadow AI signals as a deterministic risk overlay.")
    parser.add_argument("--prices", default="examples/price_history.example.csv", help="CSV with date,symbol,close")
    parser.add_argument("--signals", default="examples/signal_history", help="Signal JSON file or directory")
    parser.add_argument("--symbol", default="QQQ", help="Risk asset symbol to test")
    parser.add_argument("--min-confidence", type=float, default=0.55)
    parser.add_argument("--mixed-exposure", type=float, default=0.8)
    parser.add_argument("--risk-off-exposure", type=float, default=0.5)
    parser.add_argument("--severe-flag-exposure", type=float, default=0.6)
    parser.add_argument("--output", default="", help="Optional JSON summary path")
    args = parser.parse_args()

    policy = OverlayPolicy(
        min_confidence=args.min_confidence,
        mixed_exposure=args.mixed_exposure,
        risk_off_exposure=args.risk_off_exposure,
        severe_flag_exposure=args.severe_flag_exposure,
    )
    prices = load_price_history(Path(args.prices), symbol=args.symbol)
    signals = load_signals(Path(args.signals))
    summary = backtest_overlay(prices, signals, policy=policy)
    summary["symbol"] = args.symbol.upper()

    text = json.dumps(summary, ensure_ascii=True, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
