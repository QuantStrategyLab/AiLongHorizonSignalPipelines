#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research_signal_context_pipelines import SignalValidationError, validate_signal  # noqa: E402


DEFAULT_SIGNAL_PATH = Path("data/output/latest_signal.json")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a long-horizon shadow signal artifact.")
    parser.add_argument("path", nargs="?", default=str(DEFAULT_SIGNAL_PATH), help="Signal JSON path")
    parser.add_argument("--allow-missing", action="store_true", help="Exit successfully when the path does not exist")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        if args.allow_missing:
            print(f"missing optional signal artifact: {path}")
            return 0
        raise SystemExit(f"signal artifact not found: {path}")

    payload = json.loads(path.read_text(encoding="utf-8"))
    try:
        validate_signal(payload)
    except SignalValidationError as exc:
        raise SystemExit(f"invalid signal artifact: {exc}") from exc

    print(f"valid signal artifact: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
