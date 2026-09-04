from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_signal_context_pipelines import SignalValidationError, validate_signal
from scripts import post_shadow_signal_request as shadow_issue
from scripts import validate_latest_signal as signal_validator


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


def _write_v2_artifact_pair(tmp_path: Path) -> tuple[Path, dict]:
    signal_path = tmp_path / "latest_signal.json"
    signal = load_example()
    signal_bytes = json.dumps(signal, sort_keys=True).encode("utf-8")
    signal_path.write_bytes(signal_bytes)
    manifest = {
        "manifest_type": "research_signal_context",
        "schema_version": 2,
        "artifact": {
            "path": "data/output/latest_signal.json",
            "sha256": hashlib.sha256(signal_bytes).hexdigest(),
        },
        "as_of": signal["as_of"],
        "generated_at": signal["generated_at"],
        "expires_at": signal["expires_at"],
        "mode": signal["mode"],
        "producer": {
            "repository": "QuantStrategyLab/ResearchSignalContextPipelines",
            "commit_sha": "a" * 40,
        },
        "input_digest": "sha256:" + "b" * 64,
        "policy": {"execution_allowed": False},
    }
    return signal_path, manifest


def test_manifest_v2_rejects_stale_signal_digest(tmp_path: Path) -> None:
    signal_path, manifest = _write_v2_artifact_pair(tmp_path)
    manifest["artifact"]["sha256"] = "0" * 64

    with pytest.raises(SignalValidationError, match="artifact.sha256"):
        signal_validator.validate_manifest_v2(signal_path, load_example(), manifest)


def test_manifest_v2_rejects_missing_required_input_digest(tmp_path: Path) -> None:
    signal_path, manifest = _write_v2_artifact_pair(tmp_path)
    del manifest["input_digest"]

    with pytest.raises(SignalValidationError, match="input_digest"):
        signal_validator.validate_manifest_v2(signal_path, load_example(), manifest)


def test_manifest_v2_rejects_mutable_producer_ref(tmp_path: Path) -> None:
    signal_path, manifest = _write_v2_artifact_pair(tmp_path)
    manifest["producer"]["commit_sha"] = "main"

    with pytest.raises(SignalValidationError, match="producer.commit_sha"):
        signal_validator.validate_manifest_v2(signal_path, load_example(), manifest)


def test_manifest_v1_is_explicitly_legacy_untrusted(tmp_path: Path) -> None:
    signal_path, _ = _write_v2_artifact_pair(tmp_path)

    with pytest.raises(SignalValidationError, match="legacy_untrusted"):
        signal_validator.validate_manifest_v2(signal_path, load_example(), {"schema_version": "1"})


def test_shadow_request_binds_context_digest_to_immutable_commit(tmp_path: Path) -> None:
    context_path = tmp_path / "context.json"
    context_path.write_bytes(b'{"as_of":"2026-05-29"}')

    provenance = shadow_issue.build_immutable_provenance(context_path, "c" * 40)

    assert provenance == {
        "producer_commit_sha": "c" * 40,
        "input_digest": "sha256:" + hashlib.sha256(context_path.read_bytes()).hexdigest(),
    }
