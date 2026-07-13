from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from research_signal_context_pipelines import SignalValidationError, validate_latest_signal, validate_signal


ROOT = Path(__file__).resolve().parents[1]


def load_example() -> dict:
    return json.loads((ROOT / "examples" / "latest_signal.example.json").read_text(encoding="utf-8"))


def test_example_signal_is_valid() -> None:
    payload = load_example()
    validate_signal(payload)
    assert payload["horizon"] == "1-3 years"


def test_v2_signal_requires_versioned_model_metadata() -> None:
    payload = load_example()
    payload.update(
        {
            "schema_version": "2",
            "model_version": "shadow-v2",
            "scoring_version": "rules-v2",
        }
    )

    validate_signal(payload)


def test_v1_signal_remains_readable_without_v2_metadata() -> None:
    payload = load_example()

    validate_signal(payload)


def test_v2_signal_requires_model_and_scoring_versions() -> None:
    payload = load_example()
    payload["schema_version"] = "2"

    with pytest.raises(SignalValidationError, match="model_version"):
        validate_signal(payload)


def _strict_signal(*, source: str, as_of: str = "2026-01-01", source_sha256: str | None = None) -> dict:
    payload = load_example()
    payload.update(
        {
            "schema_version": "2",
            "as_of": as_of,
            "model_version": "shadow-v2",
            "scoring_version": "rules-v2",
        }
    )
    payload["evidence"]["sources"] = [source]
    if source_sha256:
        payload["evidence"]["source_hashes"] = {source: source_sha256}
    return payload


def _theme_snapshot(*, as_of: str = "2026-01-01") -> dict:
    return {
        "schema_version": "2",
        "as_of": as_of,
        "generated_at": f"{as_of}T00:00:00Z",
        "expires_at": "2026-12-31",
        "model_version": "theme-v1",
        "scoring_version": "rules-v1",
        "mode": "theme_momentum_snapshot",
        "artifact_type": "medium_horizon_theme_context",
        "theme_ranks": [],
        "data_quality": {},
        "policy": {},
    }


def test_strict_latest_rejects_override_not_declared_by_signal(tmp_path) -> None:
    declared = tmp_path / "declared-theme_momentum_snapshot.json"
    override = tmp_path / "other-theme_momentum_snapshot.json"
    declared.write_text(json.dumps(_theme_snapshot()), encoding="utf-8")
    override.write_text(json.dumps(_theme_snapshot()), encoding="utf-8")
    payload = _strict_signal(
        source=str(declared),
        source_sha256=hashlib.sha256(declared.read_bytes()).hexdigest(),
    )

    with pytest.raises(SignalValidationError, match="declared theme source"):
        validate_latest_signal(payload, theme_artifact_path=override)


def test_strict_latest_rejects_linked_theme_as_of_mismatch(tmp_path) -> None:
    theme_path = tmp_path / "theme_momentum_snapshot.json"
    theme_path.write_text(json.dumps(_theme_snapshot(as_of="2025-12-31")), encoding="utf-8")
    payload = _strict_signal(source=str(theme_path))

    with pytest.raises(SignalValidationError, match="as_of"):
        validate_latest_signal(payload, theme_artifact_path=theme_path)


def test_strict_latest_rejects_present_but_invalid_source_hash(tmp_path) -> None:
    theme_path = tmp_path / "theme_momentum_snapshot.json"
    theme_path.write_text(json.dumps(_theme_snapshot()), encoding="utf-8")
    payload = _strict_signal(source=str(theme_path))
    payload["evidence"]["source_hashes"] = {str(theme_path): ""}

    with pytest.raises(SignalValidationError, match="source_hashes"):
        validate_latest_signal(payload, theme_artifact_path=theme_path)


def test_strict_latest_resolves_relative_source_from_signal_base_dir(tmp_path) -> None:
    theme_path = tmp_path / "theme_momentum_snapshot.json"
    theme_path.write_text(json.dumps(_theme_snapshot()), encoding="utf-8")
    relative_source = "theme_momentum_snapshot.json"
    payload = _strict_signal(
        source=relative_source,
        source_sha256=hashlib.sha256(theme_path.read_bytes()).hexdigest(),
    )

    validate_latest_signal(
        payload,
        theme_artifact_path=relative_source,
        signal_base_dir=tmp_path,
    )


def test_signal_requires_long_horizon_contract() -> None:
    payload = load_example()
    payload["horizon"] = "1-3 months"

    with pytest.raises(SignalValidationError, match="horizon"):
        validate_signal(payload)


def test_signal_must_be_shadow_mode() -> None:
    payload = load_example()
    payload["mode"] = "live"

    with pytest.raises(SignalValidationError, match="mode must be 'shadow'"):
        validate_signal(payload)


def test_policy_must_block_execution() -> None:
    payload = load_example()
    payload["policy"]["execution_allowed"] = True

    with pytest.raises(SignalValidationError, match="execution_allowed"):
        validate_signal(payload)


def test_confidence_must_be_bounded() -> None:
    payload = load_example()
    payload["confidence"] = 1.5

    with pytest.raises(SignalValidationError, match="between 0 and 1"):
        validate_signal(payload)


def test_signal_accepts_optional_theme_bias_and_exposure() -> None:
    payload = load_example()
    payload["theme_bias"] = {"hbm_memory": "positive", "healthcare_policy": "watch"}
    payload["symbol_theme_exposure"] = {"MU": ["hbm_memory"], "UNH": ["healthcare_policy"]}

    validate_signal(payload)


def test_signal_accepts_structured_theme_and_symbol_bias() -> None:
    payload = load_example()
    payload["theme_bias"] = {
        "hbm_memory": {
            "bias": "positive",
            "confidence": 0.62,
            "horizon": "1-3 years",
            "rationale": "HBM demand remains a long-horizon research context.",
            "risk_flags": ["cycle_risk"],
        }
    }
    payload["symbol_bias"] = {
        "MU": {
            "bias": "watch",
            "confidence": 0.55,
            "linked_themes": ["hbm_memory"],
            "rationale": "Symbol-level shadow context remains watch-only.",
        }
    }

    validate_signal(payload)


def test_signal_rejects_invalid_theme_bias() -> None:
    payload = load_example()
    payload["theme_bias"] = {"hbm_memory": "hot"}

    with pytest.raises(SignalValidationError, match="theme_bias"):
        validate_signal(payload)


def test_signal_rejects_invalid_structured_bias_confidence() -> None:
    payload = load_example()
    payload["symbol_bias"] = {"MU": {"bias": "watch", "confidence": 1.5}}

    with pytest.raises(SignalValidationError, match="confidence"):
        validate_signal(payload)


def test_committed_latest_signal_covers_advisor_long_context() -> None:
    payload = json.loads((ROOT / "data" / "output" / "latest_signal.json").read_text(encoding="utf-8"))

    validate_signal(payload)

    assert payload["horizon"] == "1-3 years"
    assert payload.get("theme_bias")
    assert payload.get("symbol_theme_exposure")
    covered_symbols = set(payload.get("symbol_bias", {})) | set(payload.get("symbol_theme_exposure", {}))
    assert {"MU", "INTC", "AMD", "VRT", "DELL"} <= covered_symbols
