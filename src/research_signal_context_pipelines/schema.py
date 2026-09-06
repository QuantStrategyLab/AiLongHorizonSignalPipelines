from __future__ import annotations

import math

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any


class SignalValidationError(ValueError):
    """Raised when a shadow signal artifact violates the stable contract."""


REQUIRED_TOP_LEVEL_KEYS = (
    "schema_version",
    "as_of",
    "generated_at",
    "mode",
    "horizon",
    "universe",
    "regime",
    "risk_flags",
    "candidate_bias",
    "confidence",
    "evidence",
    "expires_at",
    "policy",
)

ALLOWED_REGIMES = frozenset({"risk_on", "risk_off", "neutral", "mixed", "unknown"})
ALLOWED_BIAS_VALUES = frozenset({"positive", "negative", "neutral", "watch", "avoid"})
REQUIRED_SIGNAL_HORIZON = "1-3 years"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1", "2"})


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SignalValidationError(f"{name} must be an object")
    return value


def _require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SignalValidationError(f"{name} must be a non-empty string")
    return value.strip()


def _require_iso_date(value: Any, name: str) -> str:
    text = _require_string(value, name)
    try:
        dt.date.fromisoformat(text)
    except ValueError as exc:
        raise SignalValidationError(f"{name} must be an ISO date") from exc
    return text


def _require_iso_datetime(value: Any, name: str) -> str:
    text = _require_string(value, name)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SignalValidationError(f"{name} must be an ISO datetime") from exc
    return text


def _parse_iso_datetime_utc(value: Any, name: str) -> dt.datetime:
    text = _require_iso_datetime(value, name)
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    parsed = dt.datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _require_string_list(value: Any, name: str, *, allow_empty: bool = False) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise SignalValidationError(f"{name} must be a list of strings")
    result = [_require_string(item, f"{name}[]") for item in value]
    if not allow_empty and not result:
        raise SignalValidationError(f"{name} must not be empty")
    return result


def _require_number_0_1(value: Any, name: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise SignalValidationError(f"{name} must be numeric")
    if not math.isfinite(value):
        raise SignalValidationError(f"{name} must be a finite number between 0 and 1")
    if value < 0 or value > 1:
        raise SignalValidationError(f"{name} must be between 0 and 1")


def validate_signal(payload: Mapping[str, Any]) -> None:
    missing = [key for key in REQUIRED_TOP_LEVEL_KEYS if key not in payload]
    if missing:
        raise SignalValidationError(f"missing required keys: {', '.join(missing)}")

    schema_version = _require_string(payload["schema_version"], "schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise SignalValidationError("schema_version must be '1' or '2'")
    _require_iso_date(payload["as_of"], "as_of")
    generated_at = _parse_iso_datetime_utc(payload["generated_at"], "generated_at")
    _require_iso_date(payload["expires_at"], "expires_at")
    if "available_at" in payload:
        available_at = _parse_iso_datetime_utc(payload["available_at"], "available_at")
        if available_at < generated_at:
            raise SignalValidationError("available_at must be >= generated_at")
    if schema_version == "2":
        _require_string(payload.get("model_version"), "model_version")
        _require_string(payload.get("scoring_version"), "scoring_version")

    if payload["mode"] != "shadow":
        raise SignalValidationError("mode must be 'shadow'")
    if _require_string(payload["regime"], "regime") not in ALLOWED_REGIMES:
        raise SignalValidationError(f"regime must be one of: {', '.join(sorted(ALLOWED_REGIMES))}")

    if _require_string(payload["horizon"], "horizon") != REQUIRED_SIGNAL_HORIZON:
        raise SignalValidationError(f"horizon must be {REQUIRED_SIGNAL_HORIZON!r}")
    _require_string_list(payload["universe"], "universe")
    _require_string_list(payload["risk_flags"], "risk_flags", allow_empty=True)

    candidate_bias = _require_mapping(payload["candidate_bias"], "candidate_bias")
    _validate_bias_mapping(candidate_bias, "candidate_bias")

    if "theme_bias" in payload:
        _validate_bias_mapping(_require_mapping(payload["theme_bias"], "theme_bias"), "theme_bias")
    if "symbol_bias" in payload:
        _validate_bias_mapping(_require_mapping(payload["symbol_bias"], "symbol_bias"), "symbol_bias")
    if "symbol_theme_exposure" in payload:
        symbol_theme_exposure = _require_mapping(payload["symbol_theme_exposure"], "symbol_theme_exposure")
        for symbol, theme_ids in symbol_theme_exposure.items():
            _require_string(symbol, "symbol_theme_exposure key")
            _require_string_list(theme_ids, f"symbol_theme_exposure[{symbol!r}]")

    _require_number_0_1(payload["confidence"], "confidence")

    evidence = _require_mapping(payload["evidence"], "evidence")
    _require_string_list(evidence.get("sources"), "evidence.sources")
    _require_string(evidence.get("summary"), "evidence.summary")
    if not isinstance(evidence.get("data_gaps", []), Sequence) or isinstance(evidence.get("data_gaps", []), str):
        raise SignalValidationError("evidence.data_gaps must be a list")

    policy = _require_mapping(payload["policy"], "policy")
    if policy.get("execution_allowed") is not False:
        raise SignalValidationError("policy.execution_allowed must be false")
    _require_string(policy.get("downstream_use"), "policy.downstream_use")


def _validate_bias_mapping(mapping: Mapping[str, Any], name: str) -> None:
    for key, bias in mapping.items():
        _require_string(key, f"{name} key")
        _validate_bias_value(bias, f"{name}[{key!r}]")


def _validate_bias_value(value: Any, name: str) -> None:
    if isinstance(value, str):
        bias = value
    else:
        raw = _require_mapping(value, name)
        bias = _require_string(raw.get("bias"), f"{name}.bias")
        if "confidence" in raw:
            _require_number_0_1(raw["confidence"], f"{name}.confidence")
        for optional_key in ("rationale", "horizon"):
            if optional_key in raw:
                _require_string(raw[optional_key], f"{name}.{optional_key}")
        for optional_list_key in ("risk_flags", "linked_themes"):
            if optional_list_key in raw:
                _require_string_list(raw[optional_list_key], f"{name}.{optional_list_key}", allow_empty=True)
    if bias not in ALLOWED_BIAS_VALUES:
        raise SignalValidationError(f"{name} must be one of: {', '.join(sorted(ALLOWED_BIAS_VALUES))}")
