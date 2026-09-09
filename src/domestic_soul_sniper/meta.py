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
    """Prefer graded JPEGs; fall back to raws for tagging masters."""
    graded = sorted(session.graded_dir().glob("*.jpg")) + sorted(
        session.graded_dir().glob("*.JPG")
    )
    if graded:
        return graded
    return session.target_raws()


def run_meta(
    cfg: UserConfig,
    session: Session,
    *,
    keywords: list[str] | None = None,
    gps: str | None = None,
    strip_gps: bool = False,
) -> Session:
    if keywords:
        # merge unique
        merged = list(session.keywords)
        for k in keywords:
            if k not in merged:
                merged.append(k)
        session.keywords = merged
    if gps is not None:
        session.gps = gps
        session.strip_gps = False
    if strip_gps:
        session.strip_gps = True
        session.gps = None

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
    float(parts[0])
    float(parts[1])
    return parts[0], parts[1]


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
