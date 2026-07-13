#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research_signal_context_pipelines import SignalValidationError, validate_latest_signal  # noqa: E402


DEFAULT_SIGNAL_PATH = Path("data/output/latest_signal.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a long-horizon shadow signal artifact.")
    parser.add_argument("path", nargs="?", default=str(DEFAULT_SIGNAL_PATH), help="Signal JSON path")
    parser.add_argument("--allow-missing", action="store_true", help="Exit successfully when the path does not exist")
    parser.add_argument("--allow-expired", action="store_true", help="Validate schema but do not allow expiry to fail the command")
    parser.add_argument("--reference-date", help="Stable UTC YYYY-MM-DD freshness date")
    parser.add_argument("--theme-artifact", help="Referenced theme momentum snapshot path")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        if args.allow_missing:
            print(f"missing optional signal artifact: {path}")
            return 0
        raise SystemExit(f"signal artifact not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    try:
        reference_date = dt.date.fromisoformat(args.reference_date) if args.reference_date else None
        validate_latest_signal(
            payload,
            reference_date=reference_date,
            theme_artifact_path=args.theme_artifact,
            check_freshness=not args.allow_expired,
        )
    except SignalValidationError as exc:
        raise SystemExit(f"invalid signal artifact: {exc}") from exc

    print(f"valid signal artifact: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
