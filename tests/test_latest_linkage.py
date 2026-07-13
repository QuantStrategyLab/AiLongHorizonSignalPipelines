from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from research_signal_context_pipelines import SignalValidationError, validate_latest_signal, validate_signal


def signal_payload(source: str = "theme_momentum_snapshot.json") -> dict:
    return {
        "schema_version": "2",
        "model_version": "shadow-v2",
        "scoring_version": "rules-v2",
        "as_of": "2026-06-26",
        "generated_at": "2026-06-27T00:00:00Z",
        "mode": "shadow",
        "horizon": "1-3 years",
        "universe": ["MU"],
        "regime": "mixed",
        "risk_flags": [],
        "candidate_bias": {"MU": "watch"},
        "confidence": 0.5,
        "evidence": {
            "sources": [source],
            "summary": "strict linkage test",
            "data_gaps": [],
        },
        "expires_at": "2026-07-26",
        "policy": {"execution_allowed": False, "downstream_use": "research only"},
    }


def snapshot_payload(as_of: str = "2026-06-26") -> dict:
    return {
        "schema_version": "2",
        "as_of": as_of,
        "generated_at": "2026-06-27T00:00:00Z",
        "expires_at": "2026-07-26",
        "model_version": "theme-v2",
        "scoring_version": "momentum-v2",
        "mode": "theme_momentum_snapshot",
        "artifact_type": "medium_horizon_theme_context",
        "theme_ranks": [],
        "data_quality": {},
        "policy": {},
    }


def write_snapshot(tmp_path: Path, *, as_of: str = "2026-06-26") -> Path:
    path = tmp_path / "theme_momentum_snapshot.json"
    path.write_bytes(json.dumps(snapshot_payload(as_of)).encode())
    return path


def test_validate_latest_signal_accepts_v2_and_matching_snapshot(tmp_path: Path) -> None:
    write_snapshot(tmp_path)

    validate_latest_signal(signal_payload(), signal_base_dir=tmp_path)


def test_validate_latest_signal_rejects_v1_without_changing_legacy_validator(tmp_path: Path) -> None:
    snapshot = write_snapshot(tmp_path)
    payload = copy.deepcopy(signal_payload())
    payload.update({"schema_version": "1"})
    payload.pop("model_version")
    payload.pop("scoring_version")

    validate_signal(payload)
    with pytest.raises(SignalValidationError, match="schema_version"):
        validate_latest_signal(payload, signal_base_dir=tmp_path)


def test_relative_source_requires_base_dir(tmp_path: Path) -> None:
    write_snapshot(tmp_path)

    with pytest.raises(SignalValidationError, match="signal_base_dir"):
        validate_latest_signal(signal_payload())


def test_source_path_escape_and_symlink_escape_are_rejected(tmp_path: Path) -> None:
    write_snapshot(tmp_path)
    outside = tmp_path.parent / "outside.json"
    outside.write_bytes(json.dumps(snapshot_payload()).encode())
    (tmp_path / "link.json").symlink_to(outside)

    for source in ("../outside.json", "link.json"):
        with pytest.raises(SignalValidationError, match="within signal_base_dir"):
            validate_latest_signal(signal_payload(source), signal_base_dir=tmp_path)


def test_override_must_match_declared_source(tmp_path: Path) -> None:
    declared = write_snapshot(tmp_path)
    other = tmp_path / "other.json"
    other.write_bytes(json.dumps(snapshot_payload()).encode())

    with pytest.raises(SignalValidationError, match="override"):
        validate_latest_signal(signal_payload(), signal_base_dir=tmp_path, source_override=other)
    validate_latest_signal(signal_payload(), signal_base_dir=tmp_path, source_override=declared)


def test_declaration_is_read_once_and_same_bytes_are_hashed_and_decoded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_snapshot(tmp_path)
    raw = path.read_bytes()
    payload = signal_payload()
    payload["evidence"]["source_hashes"] = {"theme_momentum_snapshot.json": hashlib.sha256(raw).hexdigest()}
    calls = 0
    original = Path.read_bytes

    def read_once(self: Path) -> bytes:
        nonlocal calls
        if self == path:
            calls += 1
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", read_once)
    validate_latest_signal(payload, signal_base_dir=tmp_path)
    assert calls == 1


def test_bad_hash_and_as_of_mismatch_are_validation_errors(tmp_path: Path) -> None:
    path = write_snapshot(tmp_path)
    payload = signal_payload()
    payload["evidence"]["source_hashes"] = {"theme_momentum_snapshot.json": "0" * 64}
    with pytest.raises(SignalValidationError, match="SHA-256"):
        validate_latest_signal(payload, signal_base_dir=tmp_path)

    payload = signal_payload()
    path.write_bytes(json.dumps(snapshot_payload("2026-06-25")).encode())
    with pytest.raises(SignalValidationError, match="as_of"):
        validate_latest_signal(payload, signal_base_dir=tmp_path)


def test_io_json_and_snapshot_validation_errors_are_normalized(tmp_path: Path) -> None:
    payload = signal_payload()
    with pytest.raises(SignalValidationError):
        validate_latest_signal(payload, signal_base_dir=tmp_path)

    path = tmp_path / "theme_momentum_snapshot.json"
    path.write_bytes(b"not-json")
    with pytest.raises(SignalValidationError, match="JSON"):
        validate_latest_signal(payload, signal_base_dir=tmp_path)
