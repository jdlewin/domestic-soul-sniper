"""Metadata apply via exiftool."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .config import UserConfig
from .session import Session, save_session


def _exiftool(cfg: UserConfig) -> str:
    path = cfg.tools.get("exiftool") or shutil.which("exiftool")
    if not path:
        raise RuntimeError("exiftool not found")
    return path


def _targets(session: Session) -> list[Path]:
    """Graded JPEGs only. Refuses to tag RAF masters (destructive)."""
    graded = sorted(session.graded_dir().glob("*.jpg")) + sorted(
        session.graded_dir().glob("*.JPG")
    )
    if session.select_stems() is not None:
        targets = {p.stem for p in session.target_raws()}
        graded = [g for g in graded if g.stem in targets]
    if not graded:
        raise FileNotFoundError("No graded JPEGs — run photo grade first (raws are never tagged)")
    return graded


def run_meta(
    cfg: UserConfig,
    session: Session,
    *,
    keywords: list[str] | None = None,
    gps: str | None = None,
    strip_gps: bool = False,
    time_shift: str | None = None,
) -> Session:
    if keywords:
        # merge unique
        merged = list(session.keywords)
        for k in keywords:
            if k not in merged:
                merged.append(k)
        session.keywords = merged
    if gps is not None:
        lat_s, lon_s = parse_gps_input(gps)
        session.gps = f"{lat_s},{lon_s}"
        session.strip_gps = False
    if strip_gps:
        session.strip_gps = True
        session.gps = None
    shift = normalize_time_shift(time_shift) if time_shift else None
    if shift:
        session.time_shift = shift

    files = _targets(session)
    if not files:
        raise FileNotFoundError("No files to tag (grade first or import raws)")

    et = _exiftool(cfg)
    cmd: list[str] = [et, "-overwrite_original", "-P"]

    if cfg.creator:
        cmd.append(f"-Artist={cfg.creator}")
        cmd.append(f"-Creator={cfg.creator}")
        cmd.append(f"-By-line={cfg.creator}")
    if cfg.copyright:
        cmd.append(f"-Copyright={cfg.copyright}")
        cmd.append(f"-Rights={cfg.copyright}")
        cmd.append(f"-CopyrightNotice={cfg.copyright}")
    if cfg.contact:
        cmd.append(f"-XPAuthor={cfg.contact}")
        cmd.append(f"-Contact={cfg.contact}")

    if session.keywords:
        joined = ", ".join(session.keywords)
        cmd.extend(["-sep", ", ", f"-Keywords={joined}", f"-Subject={joined}"])

    if session.strip_gps:
        cmd.extend(["-GPS:all=", "-xmp:geotag="])
    elif session.gps:
        lat_s, lon_s = _parse_gps(session.gps)
        cmd.append(f"-GPSLatitude={lat_s}")
        cmd.append(f"-GPSLongitude={lon_s}")
        cmd.append(f"-GPSLatitudeRef={'N' if float(lat_s) >= 0 else 'S'}")
        cmd.append(f"-GPSLongitudeRef={'E' if float(lon_s) >= 0 else 'W'}")

    if shift:
        sign = "+" if shift.startswith("+") else "-"
        mag = shift[1:]  # H:MM:SS
        for tag in ("DateTimeOriginal", "CreateDate", "ModifyDate"):
            cmd.append(f"-{tag}{sign}={mag}")

    cmd.extend(str(p) for p in files)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    log = session.logs_dir() / "meta.log"
    log.write_text(
        "CMD: "
        + " ".join(cmd[:20])
        + f" … ({len(files)} files)\n\n"
        + (proc.stdout or "")
        + "\n"
        + (proc.stderr or "")
        + f"\nexit={proc.returncode}\n",
        encoding="utf-8",
    )
    if proc.returncode not in (0,):  # exiftool 0 = success
        # exiftool returns 0 even with minor warnings usually
        if proc.returncode > 1:
            raise RuntimeError(f"exiftool failed: {proc.stderr or proc.stdout}")

    session.stages.meta_applied = True
    session.counts["meta_tagged"] = len(files)
    save_session(session)
    return session


def _parse_gps(value: str) -> tuple[str, str]:
    parts = value.replace(" ", "").split(",")
    if len(parts) != 2:
        raise ValueError("GPS must be LAT,LON")
    lat, lon = float(parts[0]), float(parts[1])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError(f"GPS out of range: {value}")
    return parts[0], parts[1]


_COORD_RE = r"(-?\d{1,3}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)"


def _coords_in_text(text: str) -> tuple[str, str] | None:
    """Find first plausible lat,lon pair (handles /@lat,lon and !3d/!4d)."""
    import re as _re

    m = _re.search(r"/@\s*" + _COORD_RE, text)
    if m:
        return m.group(1), m.group(2)
    m = _re.search(r"!3d" + r"(-?\d+(?:\.\d+)?)" + r"!4d" + r"(-?\d+(?:\.\d+)?)", text)
    if m:
        return m.group(1), m.group(2)
    return None


class _Redirected(Exception):
    def __init__(self, url: str):
        super().__init__(url)
        self.url = url


def _resolve_short_link(url: str, timeout: int = 10) -> str:
    """Follow goo.gl / maps.app.goo.gl redirects to the full maps URL."""
    import urllib.error as _err
    import urllib.request as _req

    class _Capture(_req.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise _Redirected(newurl)

    last_error: Exception | None = None
    for method in ("HEAD", "GET"):
        try:
            opener = _req.build_opener(_Capture())
            opener.open(_req.Request(url, method=method), timeout=timeout)
        except _Redirected as r:
            # chase chains (shortener -> consent -> maps) up to a point
            if "google." in r.url and "/maps" in r.url:
                return r.url
            url = r.url
            last_error = None
        except (_err.HTTPError, _err.URLError, OSError) as e:
            last_error = e
    # url may now be the final maps URL after chasing
    if "google." in url and "/maps" in url:
        return url
    raise ValueError(f"could not resolve short link{': ' + str(last_error) if last_error else ''}")


def parse_gps_input(value: str) -> tuple[str, str]:
    """Accept 'LAT,LON' or a Google Maps link; return (lat, lon) strings.

    Handles full URLs (/@lat,lon / !3d/!4d / ?q=lat,lon / ?query= / ll=)
    and short links (goo.gl/maps, maps.app.goo.gl) via redirect resolve.
    A place-name query (q=Eiffel+Tower) cannot be geocoded offline and errors.
    """
    import re as _re
    from urllib.parse import parse_qs, urlparse

    text = (value or "").strip()
    if not text:
        raise ValueError("empty GPS input")
    if "://" not in text and _re.fullmatch(r"\s*" + _COORD_RE + r"\s*", text):
        return _parse_gps(text)

    parsed = urlparse(text if "://" in text else "https://" + text)
    host = (parsed.hostname or "").lower()
    if "goo.gl" in host or "maps.app.goo.gl" in host:
        return parse_gps_input(_resolve_short_link(text))

    coords = _coords_in_text(parsed.path + "?" + (parsed.query or ""))
    if coords:
        try:
            return _parse_gps(f"{coords[0]},{coords[1]}")
        except ValueError:
            pass
    qs = parse_qs(parsed.query)
    for key in ("q", "query", "ll", "destination", "daddr", "saddr"):
        for v in qs.get(key, []):
            v = v.strip()
            if _re.fullmatch(_COORD_RE, v):
                return _parse_gps(v)
            if _coords_in_text(v):
                c = _coords_in_text(v)
                assert c is not None
                return _parse_gps(f"{c[0]},{c[1]}")
            if v:
                raise ValueError(
                    f"query is a place name ({v!r}), not coordinates — "
                    "right-click the map point and copy its coordinates link"
                )
    raise ValueError("no coordinates found in that link (want /@LAT,LON or ?q=LAT,LON)")


def normalize_time_shift(value: str) -> str:
    """Normalize friendly shifts ('+2h', '-90m', '+1:30') to exiftool 'H:MM:SS'.

    Returns e.g. '+2:00:00'. Raises ValueError on garbage.
    """
    import re as _re

    text = (value or "").strip().lower().replace(" ", "")
    m = _re.fullmatch(r"([+-])(\d+)(h|m|s?)", text)
    if m:
        sign, num, unit = m.groups()
        total = int(num) * {"h": 3600, "m": 60, "s": 1, "": 60}[unit or "m"]
        # bare number defaults to minutes (most common: timezone fixes)
    else:
        m = _re.fullmatch(r"([+-])(\d{1,3})(?::(\d{1,2}))?(?::(\d{1,2}))?", text)
        if not m:
            raise ValueError("time shift: want e.g. +2h, -90m, +1:30, -05:00:00")
        sign, h, mi, se = m.groups()
        total = int(h) * 3600 + int(mi or 0) * 60 + int(se or 0)
    h, rem = divmod(total, 3600)
    mi, se = divmod(rem, 60)
    return f"{sign}{h}:{mi:02d}:{se:02d}"


def strip_sensitive(cfg: UserConfig, files: list[Path], log_path: Path | None = None) -> None:
    """Strip serials/GPS from delivery files."""
    if not files:
        return
    et = _exiftool(cfg)
    cmd = [
        et,
        "-overwrite_original",
        "-P",
        "-GPS:all=",
        "-SerialNumber=",
        "-InternalSerialNumber=",
        "-LensSerialNumber=",
        "-BodySerialNumber=",
        "-CameraSerialNumber=",
    ]
    cmd.extend(str(p) for p in files)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if log_path is not None:
        log_path.write_text(
            (proc.stdout or "") + "\n" + (proc.stderr or "") + f"\nexit={proc.returncode}\n",
            encoding="utf-8",
        )
