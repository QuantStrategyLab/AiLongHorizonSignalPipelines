from __future__ import annotations

import os
from pathlib import Path

import pytest

from research_signal_context_pipelines import SignalValidationError, read_bounded_artifact_bytes


def test_reads_relative_source_once_from_base(tmp_path: Path) -> None:
    source = tmp_path / "artifact.json"
    source.write_bytes(b'{"ok": true}')

    assert read_bounded_artifact_bytes("artifact.json", base_dir=tmp_path) == b'{"ok": true}'


def test_reads_absolute_source_through_symlinked_base(tmp_path: Path) -> None:
    release = tmp_path / "releases" / "current"
    release.mkdir(parents=True)
    source = release / "artifact.json"
    source.write_bytes(b"payload")
    deployed = tmp_path / "deploy-current"
    deployed.symlink_to(release, target_is_directory=True)

    assert read_bounded_artifact_bytes(deployed / source.name, base_dir=deployed) == b"payload"


def test_reads_absolute_source_through_lexically_normalized_symlinked_base(tmp_path: Path) -> None:
    deploys = tmp_path / "deploys"
    release = tmp_path / "releases" / "current"
    deploys.mkdir()
    release.mkdir(parents=True)
    source = release / "artifact.json"
    source.write_bytes(b"payload")
    deployed = deploys / "current"
    deployed.symlink_to(release, target_is_directory=True)
    configured_base = deploys / ".." / "deploys" / "current"

    assert read_bounded_artifact_bytes(deployed / source.name, base_dir=configured_base) == b"payload"


def test_reads_absolute_source_under_canonical_base(tmp_path: Path) -> None:
    release = tmp_path / "release"
    release.mkdir()
    source = release / "artifact.json"
    source.write_bytes(b"payload")
    deployed = tmp_path / "deploy-current"
    deployed.symlink_to(release, target_is_directory=True)

    assert read_bounded_artifact_bytes(source, base_dir=deployed) == b"payload"


@pytest.mark.parametrize("source", ["../outside.json", "nested/../../outside.json"])
def test_rejects_relative_escape(tmp_path: Path, source: str) -> None:
    (tmp_path.parent / "outside.json").write_bytes(b"outside")

    with pytest.raises(SignalValidationError, match="beneath base"):
        read_bounded_artifact_bytes(source, base_dir=tmp_path)


def test_rejects_absolute_source_outside_base(tmp_path: Path) -> None:
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"outside")

    with pytest.raises(SignalValidationError, match="beneath base"):
        read_bounded_artifact_bytes(outside, base_dir=base)


def test_rejects_leaf_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_bytes(b"payload")
    (tmp_path / "artifact.json").symlink_to(target)

    with pytest.raises(SignalValidationError, match="readable regular file"):
        read_bounded_artifact_bytes("artifact.json", base_dir=tmp_path)


def test_rejects_intermediate_symlink(tmp_path: Path) -> None:
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "artifact.json").write_bytes(b"payload")
    (tmp_path / "linked").symlink_to(real_dir, target_is_directory=True)

    with pytest.raises(SignalValidationError, match="readable regular file"):
        read_bounded_artifact_bytes("linked/artifact.json", base_dir=tmp_path)


def test_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "artifact.pipe"
    os.mkfifo(fifo)

    with pytest.raises(SignalValidationError, match="regular file"):
        read_bounded_artifact_bytes(fifo.name, base_dir=tmp_path)


def test_rejects_oversized_artifact(tmp_path: Path) -> None:
    source = tmp_path / "artifact.json"
    source.write_bytes(b"12345")

    with pytest.raises(SignalValidationError, match="size limit"):
        read_bounded_artifact_bytes(source.name, base_dir=tmp_path, max_bytes=4)


def test_closes_all_opened_descriptors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "nested" / "artifact.json"
    source.parent.mkdir()
    source.write_bytes(b"payload")
    real_open = os.open
    real_close = os.close
    opened: list[int] = []
    closed: list[int] = []

    def tracking_open(*args, **kwargs) -> int:
        fd = real_open(*args, **kwargs)
        opened.append(fd)
        return fd

    def tracking_close(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "close", tracking_close)

    assert read_bounded_artifact_bytes("nested/artifact.json", base_dir=tmp_path) == b"payload"
    assert set(opened) <= set(closed)
