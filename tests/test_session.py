"""Unit tests — no large RAF required."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from domestic_soul_sniper.import_card import build_dest_name
from domestic_soul_sniper.session import (
    Session,
    load_session,
    make_session_dir,
    save_session,
)
from datetime import datetime


def test_build_dest_name():
    dt = datetime(2026, 3, 25, 8, 30, 31)
    name = build_dest_name(dt, "X-E3", "DSCF6123.RAF")
    assert name == "20260325_083031_X-E3_DSCF6123.RAF"


def test_session_roundtrip(tmp_path: Path):
    root = make_session_dir(tmp_path, date(2026, 8, 13), "Smoke Test")
    assert root.name == "2026-08-13-smoke-test"
    s = Session(
        name="smoke-test",
        date="2026-08-13",
        path=str(root),
        source="/tmp/card",
    )
    s.ensure_dirs()
    s.stages.imported = True
    s.counts["raw"] = 0
    save_session(s)
    loaded = load_session(root)
    assert loaded.name == "smoke-test"
    assert loaded.stages.imported is True
    assert loaded.raw_dir().is_dir()


def test_selects_filter(tmp_path: Path):
    root = make_session_dir(tmp_path, date(2026, 8, 13), "sel")
    s = Session(name="sel", date="2026-08-13", path=str(root))
    s.ensure_dirs()
    (s.raw_dir() / "20260325_083031_X-E3_DSCF6123.RAF").write_bytes(b"a")
    (s.raw_dir() / "20260325_083032_X-E3_DSCF6124.RAF").write_bytes(b"b")
    assert len(s.target_raws()) == 2
    (s.selects_dir() / "DSCF6123").write_text("")
    targets = s.target_raws()
    assert len(targets) == 1
    assert "6123" in targets[0].name
