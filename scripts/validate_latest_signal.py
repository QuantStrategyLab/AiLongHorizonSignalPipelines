#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from research_signal_context_pipelines import SignalValidationError, validate_signal  # noqa: E402


DEFAULT_SIGNAL_PATH = Path("data/output/latest_signal.json")
EXPECTED_MANIFEST_TYPE = "research_signal_context"
EXPECTED_ARTIFACT_PATH = "data/output/latest_signal.json"
EXPECTED_PRODUCER_REPOSITORY = "QuantStrategyLab/ResearchSignalContextPipelines"
COMMIT_SHA_PATTERN = re.compile(r"[0-9a-fA-F]{40}")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SignalValidationError(f"{name} must be an object")
    return value


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SignalValidationError(f"{name} must be a non-empty string")
    return value


def validate_manifest_v2(
    signal_path: Path,
    signal: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> None:
    schema_version = manifest.get("schema_version")
    if schema_version in ("1", 1):
        raise SignalValidationError("legacy_untrusted: manifest schema_version 1 cannot satisfy immutable provenance")
    if schema_version != 2 or isinstance(schema_version, bool):
        raise SignalValidationError("manifest schema_version must be 2")
    if manifest.get("manifest_type") != EXPECTED_MANIFEST_TYPE:
        raise SignalValidationError(f"manifest_type must be {EXPECTED_MANIFEST_TYPE!r}")

    artifact = _require_mapping(manifest.get("artifact"), "artifact")
    if artifact.get("path") != EXPECTED_ARTIFACT_PATH:
        raise SignalValidationError(f"artifact.path must be {EXPECTED_ARTIFACT_PATH!r}")
    artifact_sha256 = _require_string(artifact.get("sha256"), "artifact.sha256")
    if not SHA256_PATTERN.fullmatch(artifact_sha256):
        raise SignalValidationError("artifact.sha256 must be a lowercase SHA-256 hex digest")
    if artifact_sha256 != hashlib.sha256(signal_path.read_bytes()).hexdigest():
        raise SignalValidationError("artifact.sha256 does not match signal bytes")

    for field in ("as_of", "generated_at", "expires_at", "mode"):
        if manifest.get(field) != signal.get(field):
            raise SignalValidationError(f"{field} must exactly match the signal")

    producer = _require_mapping(manifest.get("producer"), "producer")
    if producer.get("repository") != EXPECTED_PRODUCER_REPOSITORY:
        raise SignalValidationError(f"producer.repository must be {EXPECTED_PRODUCER_REPOSITORY!r}")
    producer_commit_sha = _require_string(producer.get("commit_sha"), "producer.commit_sha")
    if not COMMIT_SHA_PATTERN.fullmatch(producer_commit_sha):
        raise SignalValidationError("producer.commit_sha must be an immutable 40-hex commit")

    input_digest = _require_string(manifest.get("input_digest"), "input_digest")
    if not input_digest.startswith("sha256:") or not SHA256_PATTERN.fullmatch(input_digest.removeprefix("sha256:")):
        raise SignalValidationError("input_digest must be sha256:<64 lowercase hex>")

    policy = _require_mapping(manifest.get("policy"), "policy")
    if policy.get("execution_allowed") is not False:
        raise SignalValidationError("policy.execution_allowed must be false")

    for field in ("publication_commit", "artifact_commit", "publisher_commit"):
        if field in manifest or field in producer:
            raise SignalValidationError(f"{field} is not permitted in immutable provenance manifests")


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
        manifest_path = path.with_suffix(".manifest.json")
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            validate_manifest_v2(path, payload, manifest)
    except SignalValidationError as exc:
        raise SystemExit(f"invalid or untrusted signal artifact: {exc}") from exc

    if path.with_suffix(".manifest.json").exists():
        print(f"valid signal artifact with immutable provenance: {path}")
    else:
        print(f"valid signal schema only; immutable provenance unavailable: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
