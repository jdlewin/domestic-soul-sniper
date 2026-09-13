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


def _exiftool_batch(paths: list[Path], exiftool: str) -> dict[str, dict[str, str]]:
    """Single exiftool spawn for all paths. Returns {str(path): tags}."""
    import json as _json

    if not paths:
        return {}
    cmd = [
        exiftool,
        "-j",
        "-fast",
        "-DateTimeOriginal",
        "-CreateDate",
        "-Model",
        "-FileName",
        *(str(p) for p in paths),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as e:
        raise RuntimeError("exiftool not found") from e
    try:
        arr = _json.loads(proc.stdout or "[]")
    except ValueError:
        arr = []
    out: dict[str, dict[str, str]] = {}
    for entry in arr:
        src = str(entry.get("SourceFile", ""))
        out[src] = {k: str(v) for k, v in entry.items() if isinstance(v, str)}
    return out


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


def _copy_hashed(src: Path, dest: Path, chunk: int = 1024 * 1024) -> str:
    """Copy src->dest while hashing the bytes written. Returns sha256 hex."""
    import hashlib as _hashlib

    h = _hashlib.sha256()
    with src.open("rb") as fin, dest.open("wb") as fout:
        while True:
            block = fin.read(chunk)
            if not block:
                break
            h.update(block)
            fout.write(block)
    shutil.copystat(src, dest)
    digest = h.hexdigest()
    # single verification read of dest (was: read src + dest separately)
    if _sha256(dest) != digest:
        dest.unlink(missing_ok=True)
        raise IOError(f"Checksum mismatch after copy: {src} -> {dest}")
    return digest


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

    # One exiftool spawn for the whole batch (was: 2 spawns per file).
    batch = _exiftool_batch(rafs, exiftool)

    def _meta_for(p: Path) -> dict[str, str]:
        if str(p) in batch:
            return batch[str(p)]
        # fallback for files exiftool skipped (single-file path)
        return _exiftool_json(p, exiftool)

    def _tag(meta: dict[str, str], *keys: str) -> str | None:
        for k in keys:
            if meta.get(k):
                return meta[k]
        # legacy "Key: value" spaced names from _exiftool_json fallback
        return None

    # Determine session date from first file if not provided
    first_meta = _meta_for(rafs[0])
    first_dt = _parse_dt(
        _tag(first_meta, "DateTimeOriginal", "Date/Time Original", "CreateDate", "Create Date")
    )
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
        meta = _meta_for(src)
        dt = _parse_dt(
            _tag(meta, "DateTimeOriginal", "Date/Time Original", "CreateDate", "Create Date")
        )
        if dt is None:
            dt = datetime.fromtimestamp(src.stat().st_mtime)
            log_lines.append(f"WARN no EXIF date for {src.name}; using mtime")
        camera = _camera_token(
            _tag(meta, "Model", "Camera Model Name")
            or meta.get("Model")
            or meta.get("Camera Model Name")
        )
        dest_name = build_dest_name(dt, camera, src.name)
        dest = session.raw_dir() / dest_name

        if dest.exists():
            # verify existing (dest read once; src read once)
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

        digest = _copy_hashed(src, dest)
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
