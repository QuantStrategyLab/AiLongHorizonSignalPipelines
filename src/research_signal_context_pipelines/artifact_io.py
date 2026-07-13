from __future__ import annotations

import os
import stat
from pathlib import Path

from .schema import SignalValidationError


DEFAULT_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
_OPEN_SUPPORTS_DIR_FD = os.open in os.supports_dir_fd


def read_bounded_artifact_bytes(
    source_path: str | Path,
    *,
    base_dir: str | Path,
    max_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
) -> bytes:
    """Read one regular artifact beneath a directory without following symlinks."""
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise SignalValidationError("artifact size limit must be a positive integer")
    _require_safe_open_support()

    raw_base = Path(base_dir).absolute()
    try:
        canonical_base = raw_base.resolve(strict=True)
    except OSError as exc:
        raise SignalValidationError("artifact base directory is unavailable") from exc
    if not canonical_base.is_dir():
        raise SignalValidationError("artifact base must be a directory")

    parts = _relative_source_parts(source_path, raw_base=raw_base, canonical_base=canonical_base)
    opened_fds: list[int] = []
    try:
        base_fd = os.open(
            canonical_base,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        opened_fds.append(base_fd)
        parent_fd = base_fd
        for part in parts[:-1]:
            parent_fd = os.open(
                part,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=parent_fd,
            )
            opened_fds.append(parent_fd)
        artifact_fd = os.open(
            parts[-1],
            os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
        opened_fds.append(artifact_fd)
        metadata = os.fstat(artifact_fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise SignalValidationError("artifact source must be a regular file")
        if metadata.st_size > max_bytes:
            raise SignalValidationError("artifact exceeds the configured size limit")
        with os.fdopen(artifact_fd, "rb", closefd=False) as stream:
            payload = stream.read(max_bytes + 1)
        if len(payload) > max_bytes:
            raise SignalValidationError("artifact exceeds the configured size limit")
        return payload
    except SignalValidationError:
        raise
    except (OSError, ValueError) as exc:
        raise SignalValidationError("artifact source must be a readable regular file beneath base") from exc
    finally:
        for fd in reversed(opened_fds):
            try:
                os.close(fd)
            except OSError:
                pass


def _require_safe_open_support() -> None:
    required_flags = ("O_CLOEXEC", "O_DIRECTORY", "O_NOFOLLOW", "O_NONBLOCK")
    if any(not hasattr(os, flag) for flag in required_flags) or not _OPEN_SUPPORTS_DIR_FD:
        raise SignalValidationError("safe descriptor-relative artifact reads are unsupported")


def _relative_source_parts(
    source_path: str | Path,
    *,
    raw_base: Path,
    canonical_base: Path,
) -> tuple[str, ...]:
    source = Path(source_path)
    if source.is_absolute():
        relative = _relative_to_either_base(source, raw_base=raw_base, canonical_base=canonical_base)
    else:
        relative = source
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise SignalValidationError("artifact source must remain beneath base")
    return parts


def _relative_to_either_base(source: Path, *, raw_base: Path, canonical_base: Path) -> Path:
    for base in (raw_base, canonical_base):
        try:
            return source.relative_to(base)
        except ValueError:
            continue
    raise SignalValidationError("artifact source must remain beneath base")
