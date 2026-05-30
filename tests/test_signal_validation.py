from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_long_horizon_signal_pipelines import SignalValidationError, validate_signal


ROOT = Path(__file__).resolve().parents[1]


def load_example() -> dict:
    return json.loads((ROOT / "examples" / "latest_signal.example.json").read_text(encoding="utf-8"))


def test_example_signal_is_valid() -> None:
    payload = load_example()
    validate_signal(payload)
    assert payload["horizon"] == "1-3 years"


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


def test_signal_rejects_invalid_theme_bias() -> None:
    payload = load_example()
    payload["theme_bias"] = {"hbm_memory": "hot"}

    with pytest.raises(SignalValidationError, match="theme_bias"):
        validate_signal(payload)
