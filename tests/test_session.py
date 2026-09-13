"""Unit tests — no large RAF required."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from domestic_soul_sniper.import_card import _copy_hashed, build_dest_name
from domestic_soul_sniper.proof import extract_previews
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


def test_copy_hashed_roundtrip(tmp_path: Path):
    from domestic_soul_sniper.import_card import _sha256

    src = tmp_path / "a.RAF"
    src.write_bytes(b"x" * 100_000 + b"raw-bytes")
    dest = tmp_path / "b.RAF"
    digest = _copy_hashed(src, dest)
    assert dest.is_file()
    assert digest == _sha256(src) == _sha256(dest)


def test_extract_previews_no_exiftool(tmp_path: Path):
    # no inputs -> empty, no crash without exiftool
    produced, missing = extract_previews([], tmp_path, exiftool="/nonexistent/exiftool")
    assert produced == [] and missing == []
    fake = tmp_path / "x.RAF"
    fake.write_bytes(b"not-a-raf")
    produced, missing = extract_previews([fake], tmp_path / "out", exiftool="/nonexistent/exiftool")
    assert produced == [] and missing == [fake]


def test_parse_gps_inputs():
    from domestic_soul_sniper.meta import parse_gps_input

    assert parse_gps_input("37.7749,-122.4194") == ("37.7749", "-122.4194")
    assert parse_gps_input("https://www.google.com/maps/@37.7749,-122.4194,15z") == (
        "37.7749", "-122.4194")
    assert parse_gps_input(
        "https://www.google.com/maps/place/Paris/@48.8566,2.3522,12z") == (
        "48.8566", "2.3522")
    assert parse_gps_input("https://maps.google.com/?q=48.8566,2.3522") == (
        "48.8566", "2.3522")
    try:
        parse_gps_input("https://www.google.com/maps/search/?api=1&query=Eiffel+Tower")
    except ValueError as e:
        assert "place name" in str(e)
    else:
        raise AssertionError("place-name link should error")


def test_normalize_time_shift():
    from domestic_soul_sniper.meta import normalize_time_shift

    assert normalize_time_shift("+2h") == "+2:00:00"
    assert normalize_time_shift("-90m") == "-1:30:00"
    assert normalize_time_shift("+1:30") == "+1:30:00"
    assert normalize_time_shift("-05:00:00") == "-5:00:00"
    try:
        normalize_time_shift("tomorrow")
    except ValueError:
        pass
    else:
        raise AssertionError("garbage shift should error")
