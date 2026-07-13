from __future__ import annotations

import json
import datetime as dt
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
    assert payload["model_version"]
    assert payload["scoring_version"]


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


def test_signal_requires_versioned_scoring_metadata() -> None:
    payload = load_example()
    payload["schema_version"] = "2"
    payload.pop("model_version")

    with pytest.raises(SignalValidationError, match="model_version"):
        validate_signal(payload)


def test_signal_rejects_expiry_before_as_of() -> None:
    payload = load_example()
    payload["expires_at"] = "2026-05-27"

    with pytest.raises(SignalValidationError, match="expires_at"):
        validate_signal(payload)


def test_public_signal_validation_preserves_historical_compatibility() -> None:
    payload = load_example()
    payload["expires_at"] = "2026-06-30"
    validate_signal(payload)

    with pytest.raises(SignalValidationError, match="expired"):
        validate_latest_signal(payload, reference_date=dt.date(2026, 7, 13))


def test_committed_latest_signal_covers_advisor_long_context() -> None:
    payload = json.loads((ROOT / "data" / "output" / "latest_signal.json").read_text(encoding="utf-8"))

    validate_signal(payload, check_freshness=False)

    assert payload["horizon"] == "1-3 years"
    assert payload.get("theme_bias")
    assert payload.get("symbol_theme_exposure")
    covered_symbols = set(payload.get("symbol_bias", {})) | set(payload.get("symbol_theme_exposure", {}))
    assert {"MU", "INTC", "AMD", "VRT", "DELL"} <= covered_symbols


def test_strict_latest_signal_rejects_blocked_theme_gate() -> None:
    payload = json.loads((ROOT / "data" / "output" / "latest_signal.json").read_text(encoding="utf-8"))

    with pytest.raises(SignalValidationError, match="blocked"):
        validate_latest_signal(
            payload,
            reference_date=dt.date(2026, 6, 30),
            theme_artifact_path=ROOT / "data" / "output" / "theme_momentum_snapshot.json",
        )


def test_allow_expired_only_skips_freshness_not_theme_gate() -> None:
    payload = json.loads((ROOT / "data" / "output" / "latest_signal.json").read_text(encoding="utf-8"))

    with pytest.raises(SignalValidationError, match="blocked"):
        validate_latest_signal(
            payload,
            reference_date=dt.date(2026, 7, 13),
            check_freshness=False,
            theme_artifact_path=ROOT / "data" / "output" / "theme_momentum_snapshot.json",
        )
