"""GTD-63: never modify or delete the source tree.

The import may READ the source tree, never WRITE into it. These tests run
without exiftool / RawTherapee (monkeypatched batch metadata + fake RAFs).
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest

from domestic_soul_sniper import import_card
from domestic_soul_sniper.config import UserConfig
from domestic_soul_sniper.import_card import (
    ensure_dest_outside_source,
    import_photos,
)

FAKE_TAGS = {"DateTimeOriginal": "2026:03:25 08:30:31", "Model": "X-E3"}


@pytest.fixture()
def fake_exiftool(monkeypatch):
    monkeypatch.setattr(
        import_card,
        "_exiftool_batch",
        lambda paths, exiftool: {str(p): dict(FAKE_TAGS) for p in paths},
    )


def _cfg(archive_root: Path) -> UserConfig:
    return UserConfig(
        creator="t",
        copyright="",
        contact="",
        archive_root=str(archive_root),
        default_stock="acros",
        tools={"exiftool": "fake-exiftool"},
    )


def _snapshot_tree(root: Path) -> dict[str, str]:
    """relpath -> sha256 hex (dirs recorded as '<DIR>')."""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_file() and not p.is_symlink():
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
        elif p.is_dir():
            out[rel] = "<DIR>"
    return out


def _make_source(source: Path) -> list[Path]:
    source.mkdir(parents=True, exist_ok=True)
    rafs = [
        source / "DSCF6123.RAF",
        source / "DSCF6124.RAF",
        source / "DCIM" / "100FUJI" / "DSCF6125.RAF",
    ]
    for i, p in enumerate(rafs):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"fake-raf-bytes-%d" % i + b"x" * 10_000)
    (source / "notes.txt").write_text("leave me alone")
    return rafs


def test_import_leaves_source_tree_untouched(tmp_path: Path, fake_exiftool) -> None:
    source = tmp_path / "card"
    _make_source(source)
    archive = tmp_path / "archive"
    before = _snapshot_tree(source)

    session = import_photos(
        _cfg(archive),
        source,
        name="gtd63",
        shoot_date=date(2026, 3, 25),
        prompt=False,
    )

    assert session.counts.get("imported_copied") == 3
    assert Path(session.path).is_relative_to(archive.resolve())
    assert _snapshot_tree(source) == before


def test_dest_inside_source_refused(tmp_path: Path, fake_exiftool) -> None:
    source = tmp_path / "card"
    _make_source(source)
    before = _snapshot_tree(source)

    with pytest.raises(RuntimeError, match="inside the source tree"):
        import_photos(
            _cfg(source / "archive"),
            source,
            name="gtd63",
            shoot_date=date(2026, 3, 25),
            prompt=False,
        )
    # Guard fires before make_session_dir mkdirs: nothing created in source.
    assert _snapshot_tree(source) == before
    assert not (source / "archive").exists()


def test_dest_equal_to_source_refused(tmp_path: Path, fake_exiftool) -> None:
    source = tmp_path / "card"
    _make_source(source)

    with pytest.raises(RuntimeError, match="inside the source tree"):
        import_photos(
            _cfg(source),
            source,
            name="gtd63",
            shoot_date=date(2026, 3, 25),
            prompt=False,
        )
    assert not (source / "2026").exists()


def test_ensure_dest_outside_source_unit(tmp_path: Path) -> None:
    src = tmp_path / "card"
    src.mkdir()
    with pytest.raises(RuntimeError):
        ensure_dest_outside_source(src, src)
    with pytest.raises(RuntimeError):
        ensure_dest_outside_source(src, src / "sub" / "sess")
    # dot-dot tricks resolving back inside still raise
    with pytest.raises(RuntimeError):
        ensure_dest_outside_source(src, src / ".." / "card" / "sess")
    # sibling / parent destinations are fine
    ensure_dest_outside_source(src, tmp_path / "archive" / "2026" / "x")
    ensure_dest_outside_source(src, src.parent / "other")
