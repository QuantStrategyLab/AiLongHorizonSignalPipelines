from __future__ import annotations

import hashlib
import json
import datetime as dt
import errno
import os
import re
import stat
from pathlib import Path
from typing import Any

from .schema import SignalValidationError, validate_signal
from .theme_momentum import validate_theme_momentum_snapshot


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_OPEN_SUPPORTS_DIR_FD = os.open in getattr(os, "supports_dir_fd", set())
MAX_JSON_ARTIFACT_BYTES = 4 * 1024 * 1024


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

    raw = _read_declaration(source_path, base, declared_source)
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
    if snapshot.get("artifact_type") != "medium_horizon_theme_context":
        raise SignalValidationError("theme snapshot artifact_type must be 'medium_horizon_theme_context'")
    if snapshot.get("as_of") != payload.get("as_of"):
        raise SignalValidationError("signal and theme snapshot as_of must match")
    if _parse_datetime(snapshot["generated_at"], "theme snapshot generated_at") > _parse_datetime(
        payload["generated_at"], "signal generated_at"
    ):
        raise SignalValidationError("theme snapshot generated_at must not be later than signal generated_at")


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


def _read_declaration(path: Path, base: Path | None, declared_source: str) -> bytes:
    if (
        getattr(os, "O_NOFOLLOW", None) is None
        or getattr(os, "O_DIRECTORY", None) is None
        or getattr(os, "O_NONBLOCK", None) is None
    ):
        raise SignalValidationError("secure descriptor-based source reading is unavailable")
    if not _OPEN_SUPPORTS_DIR_FD:
        raise SignalValidationError("secure openat source reading is unavailable")
    fd = -1
    try:
        if base is None:
            fd = os.open(Path(declared_source), os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))
        else:
            raw_path = Path(declared_source)
            try:
                relative = raw_path.relative_to(base) if raw_path.is_absolute() else raw_path
            except ValueError as exc:
                raise SignalValidationError("absolute source must be beneath signal_base_dir") from exc
            parts = relative.parts
            if not parts or any(part in {"", ".", ".."} for part in parts):
                raise SignalValidationError("source path must be a file beneath signal_base_dir")
            fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            for part in parts[:-1]:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            final_fd = -1
            try:
                final_fd = os.open(
                    parts[-1], os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0), dir_fd=fd
                )
            finally:
                parent_fd = fd
                fd = final_fd
                os.close(parent_fd)
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise SignalValidationError("declaration source must be a regular file")
        if metadata.st_size > MAX_JSON_ARTIFACT_BYTES:
            raise SignalValidationError("declaration source exceeds maximum size")
        with os.fdopen(fd, "rb") as stream:
            fd = -1
            return stream.read()
    except SignalValidationError:
        raise
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise SignalValidationError("no-follow source read rejected a symlink") from exc
        raise SignalValidationError(f"unable to securely read declaration file: {path}") from exc
    finally:
        if fd >= 0:
            os.close(fd)


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
    locations = [container["source_hashes"] for container in (evidence, payload) if "source_hashes" in container]
    if not locations:
        return
    if len(locations) != 1:
        raise SignalValidationError("source_hashes must be declared in exactly one location")
    hashes = locations[0]
    if not isinstance(hashes, dict):
        raise SignalValidationError("source_hashes must be an object")
    allowed_keys = {declared_source, str(source_path)}
    if len(hashes) != 1 or not set(hashes).issubset(allowed_keys):
        raise SignalValidationError("source_hashes must cover only the declared source")
    expected = next(iter(hashes.values()))
    if not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected):
        raise SignalValidationError("source_hashes must contain a SHA-256 digest")
    actual = hashlib.sha256(raw).hexdigest()
    if actual.lower() != expected.lower():
        raise SignalValidationError("source SHA-256 hash mismatch")


def _parse_datetime(value: Any, name: str) -> dt.datetime:
    if not isinstance(value, str) or not value.strip():
        raise SignalValidationError(f"{name} must be an ISO datetime")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SignalValidationError(f"{name} must be an ISO datetime") from exc
    if parsed.tzinfo is None:
        raise SignalValidationError(f"{name} must be an ISO datetime with an explicit timezone")
    return parsed.astimezone(dt.timezone.utc)
