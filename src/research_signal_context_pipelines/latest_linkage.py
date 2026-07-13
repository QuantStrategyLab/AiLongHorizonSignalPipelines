from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .schema import SignalValidationError, validate_signal
from .theme_momentum import validate_theme_momentum_snapshot


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def validate_latest_signal(
    payload: dict[str, Any],
    *,
    signal_base_dir: str | Path | None = None,
    source_override: str | Path | None = None,
) -> None:
    """Validate a v2 signal and its single, point-in-time theme snapshot."""
    try:
        validate_signal(payload)
    except SignalValidationError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise SignalValidationError(f"invalid signal: {exc}") from exc

    if payload.get("schema_version") != "2":
        raise SignalValidationError("latest signal schema_version must be '2'")

    evidence = payload["evidence"]
    sources = evidence["sources"]
    if len(sources) != 1:
        raise SignalValidationError("latest signal evidence.sources must declare exactly one source")
    declared_source = sources[0]
    if not isinstance(declared_source, str) or not declared_source.strip():
        raise SignalValidationError("latest signal evidence.sources must contain a path")

    try:
        base = Path(signal_base_dir).resolve() if signal_base_dir is not None else None
    except OSError as exc:
        raise SignalValidationError("invalid signal_base_dir") from exc
    source_path = _resolve_source_path(declared_source, base)
    if source_override is not None:
        override_path = _resolve_source_path(str(source_override), base)
        if override_path != source_path:
            raise SignalValidationError("source override must be the same declaration file")

    raw = _read_declaration(source_path)
    _validate_source_hash(evidence, payload, declared_source, source_path, raw)
    snapshot = _decode_declaration(raw)
    try:
        validate_theme_momentum_snapshot(snapshot)
    except SignalValidationError:
        raise
    except (TypeError, ValueError, KeyError) as exc:
        raise SignalValidationError(f"invalid theme momentum snapshot: {exc}") from exc

    if snapshot.get("schema_version") != "2":
        raise SignalValidationError("theme momentum snapshot schema_version must be '2'")
    if snapshot.get("mode") != "theme_momentum_snapshot":
        raise SignalValidationError("source must declare theme_momentum_snapshot")
    if snapshot.get("as_of") != payload.get("as_of"):
        raise SignalValidationError("signal and theme snapshot as_of must match")


def _resolve_source_path(source: str, base: Path | None) -> Path:
    raw_path = Path(source)
    if not raw_path.is_absolute() and base is None:
        raise SignalValidationError("relative source requires signal_base_dir")
    try:
        resolved = raw_path.resolve() if raw_path.is_absolute() else (base / raw_path).resolve()
    except OSError as exc:
        raise SignalValidationError("unable to resolve source path") from exc
    if base is not None:
        try:
            resolved.relative_to(base)
        except ValueError as exc:
            raise SignalValidationError("source must remain within signal_base_dir") from exc
    return resolved


def _read_declaration(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise SignalValidationError(f"unable to read declaration file: {path}") from exc


def _decode_declaration(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
        raise SignalValidationError("declaration file must contain valid JSON") from exc
    if not isinstance(value, dict):
        raise SignalValidationError("declaration file must contain a JSON object")
    return value


def _validate_source_hash(
    evidence: dict[str, Any],
    payload: dict[str, Any],
    declared_source: str,
    source_path: Path,
    raw: bytes,
) -> None:
    hashes = evidence.get("source_hashes", payload.get("source_hashes"))
    if hashes is None:
        return
    if not isinstance(hashes, dict):
        raise SignalValidationError("source_hashes must be an object")
    expected = hashes.get(declared_source, hashes.get(str(source_path)))
    if expected is None:
        return
    if not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected):
        raise SignalValidationError("source_hashes must contain a SHA-256 digest")
    actual = hashlib.sha256(raw).hexdigest()
    if actual.lower() != expected.lower():
        raise SignalValidationError("source SHA-256 hash mismatch")
