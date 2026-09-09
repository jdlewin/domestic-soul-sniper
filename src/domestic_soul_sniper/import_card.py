"""Import RAF from card or folder into a session."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from datetime import date, datetime
from pathlib import Path

from .config import UserConfig
from .session import Session, make_session_dir, save_session


RAF_RE = re.compile(r"\.raf$", re.IGNORECASE)


def _sha256(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _exiftool_json(path: Path, exiftool: str) -> dict[str, str]:
    cmd = [
        exiftool,
        "-s",
        "-s",
        "-s",
        "-DateTimeOriginal",
        "-CreateDate",
        "-Model",
        "-FileName",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as e:
        raise RuntimeError("exiftool not found") from e
    lines = (proc.stdout or "").strip().splitlines()
    # With -s -s -s, values only in order requested — fragile if missing tags.
    # Prefer tag=value form:
    cmd2 = [
        exiftool,
        "-DateTimeOriginal",
        "-CreateDate",
        "-Model",
        "-n",
        str(path),
    ]
    proc2 = subprocess.run(cmd2, capture_output=True, text=True, check=False)
    data: dict[str, str] = {}
    for line in (proc2.stdout or "").splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        data[key.strip()] = val.strip()
    return data


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S%z"):
        try:
            return datetime.strptime(value[:19], fmt[: len("%Y:%m:%d %H:%M:%S")])
        except ValueError:
            continue
    return None


def _camera_token(model: str | None) -> str:
    if not model:
        return "X-E3"
    m = model.upper().replace(" ", "")
    if "X-E3" in m or "XE3" in m:
        return "X-E3"
    # sanitize
    token = re.sub(r"[^A-Za-z0-9-]+", "", model.replace(" ", "-"))
    return token or "X-E3"


def list_source_rafs(source: Path) -> list[Path]:
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise NotADirectoryError(f"Import source is not a directory: {source}")
    files = [p for p in source.rglob("*") if p.is_file() and RAF_RE.search(p.name)]
    # Prefer top-level-ish; still include nested card DCIM
    # Skip already-odd paths under archive if user points wrong — still ok
    return sorted(files, key=lambda p: p.name.lower())


def build_dest_name(dt: datetime, camera: str, original_name: str) -> str:
    stem = Path(original_name).stem
    # keep original stem only (DSCF6123)
    return f"{dt.strftime('%Y%m%d_%H%M%S')}_{camera}_{stem}.RAF"


def import_photos(
    cfg: UserConfig,
    source: Path,
    *,
    name: str | None = None,
    shoot_date: date | None = None,
    limit: int | None = None,
) -> Session:
    exiftool = cfg.tools.get("exiftool") or shutil.which("exiftool")
    if not exiftool:
        raise RuntimeError("exiftool is required for import")

    source = source.expanduser().resolve()
    rafs = list_source_rafs(source)
    if not rafs:
        raise FileNotFoundError(f"No RAF files under {source}")
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit must be >= 1")
        rafs = rafs[:limit]

    # Determine session date from first file if not provided
    first_meta = _exiftool_json(rafs[0], exiftool)
    first_dt = _parse_dt(first_meta.get("Date/Time Original") or first_meta.get("Create Date"))
    if first_dt is None:
        first_dt = datetime.fromtimestamp(rafs[0].stat().st_mtime)

    sess_date = shoot_date or first_dt.date()
    slug = name or "shoot"
    session_path = make_session_dir(cfg.archive_path(), sess_date, slug)

    session = Session(
        name=_slug_from_path(session_path),
        date=sess_date.isoformat(),
        path=str(session_path),
        camera="X-E3",
        stock=cfg.default_stock or "acros",
        source=str(source),
    )
    session.ensure_dirs()

    checksums: dict[str, str] = {}
    copied = 0
    skipped = 0
    log_lines: list[str] = []

    for src in rafs:
        meta = _exiftool_json(src, exiftool)
        dt = _parse_dt(meta.get("Date/Time Original") or meta.get("Create Date"))
        if dt is None:
            dt = datetime.fromtimestamp(src.stat().st_mtime)
        camera = _camera_token(meta.get("Camera Model Name") or meta.get("Model"))
        dest_name = build_dest_name(dt, camera, src.name)
        dest = session.raw_dir() / dest_name

        if dest.exists():
            # verify existing
            existing_hash = _sha256(dest)
            src_hash = _sha256(src)
            if existing_hash == src_hash:
                checksums[dest_name] = existing_hash
                skipped += 1
                log_lines.append(f"SKIP exists {src.name} -> {dest_name}")
                continue
            # collision different content
            stem = dest.stem
            n = 2
            while dest.exists():
                dest = session.raw_dir() / f"{stem}_{n}.RAF"
                n += 1
            dest_name = dest.name

        shutil.copy2(src, dest)
        digest = _sha256(dest)
        src_digest = _sha256(src)
        if digest != src_digest:
            dest.unlink(missing_ok=True)
            raise IOError(f"Checksum mismatch after copy: {src} -> {dest}")
        checksums[dest_name] = digest
        copied += 1
        log_lines.append(f"OK {src.name} -> {dest_name} sha256={digest[:12]}…")

    session.checksums = checksums
    session.counts = {
        "raw": len(session.list_raws()),
        "imported_copied": copied,
        "imported_skipped": skipped,
    }
    session.stages.imported = True
    session.camera = "X-E3"
    save_session(session)

    log_path = session.logs_dir() / "import.log"
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return session


def _slug_from_path(path: Path) -> str:
    # folder is YYYY-MM-DD-slug
    name = path.name
    parts = name.split("-", 3)
    if len(parts) >= 4:
        return parts[3]
    return name
