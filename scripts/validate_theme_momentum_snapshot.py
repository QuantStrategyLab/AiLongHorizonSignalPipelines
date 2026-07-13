#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research_signal_context_pipelines import validate_theme_momentum_snapshot  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a theme momentum snapshot artifact.")
    parser.add_argument("path", nargs="?", default="data/output/theme_momentum_snapshot.json")
    parser.add_argument("--allow-expired", action="store_true")
    parser.add_argument("--allow-legacy", action="store_true", help="Allow schema 1 compatibility validation")
    parser.add_argument("--reference-date", help="Stable UTC YYYY-MM-DD freshness date")
    args = parser.parse_args()
    path = Path(args.path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    try:
        validate_theme_momentum_snapshot(
            payload,
            reference_date=None
            if args.allow_expired
            else (dt.date.fromisoformat(args.reference_date) if args.reference_date else dt.datetime.now(dt.UTC).date()),
            compatibility=args.allow_legacy,
        )
    except ValueError as exc:
        raise SystemExit(f"invalid theme momentum snapshot: {exc}") from exc
    print(f"valid theme momentum snapshot: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
