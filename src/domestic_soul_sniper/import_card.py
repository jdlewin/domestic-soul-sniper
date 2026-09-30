"""Import RAF from card or folder into a session."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from collections.abc import Callable
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


def parse_correct_dt(value: str | None, fallback_time: datetime | None = None) -> datetime | None:
    """Parse user-supplied correct datetime for the first frame.

    Accepts 'YYYY-MM-DD HH:MM[:SS]', 'YYYY/MM/DD HH:MM', EXIF 'YYYY:MM:DD HH:MM:SS',
    or a bare date (time taken from fallback_time or 00:00). Returns naive datetime.
    """
    if value is None:
        return None
    text = value.strip().replace("/", "-").replace(":", "-", 2) if False else value.strip()
    # normalize separators: allow YYYY:MM:DD and YYYY/MM/DD
    import re as _re

    text = _re.sub(r"^(\d{4})[/:](\d{2})[/:](\d{2})", r"\1-\2-\3", text)
    text = _re.sub(r"T", " ", text).strip()
    fmts = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y-%m-%d %H%M",
    )
    for fmt in fmts:
        try:
            dt = datetime.strptime(text, fmt)
            if fmt == "%Y-%m-%d" and fallback_time is not None:
                dt = dt.replace(
                    hour=fallback_time.hour,
                    minute=fallback_time.minute,
                    second=fallback_time.second,
                )
            return dt
        except ValueError:
            continue
    raise ValueError(
        f"bad datetime {value!r}: want 'YYYY-MM-DD HH:MM[:SS]' e.g. 2026-09-25 17:07"
    )


def resolve_correction(
    first_name: str,
    first_dt: datetime,
    *,
    correct_dt: datetime | None = None,
    prompt: bool = True,
) -> tuple[datetime, int]:
    """Return (effective_first_dt, offset_seconds).

    If correct_dt given, delta = correct - EXIF. Else if prompt and a TTY,
    ask to confirm; on 'n' loop for a replacement datetime. Non-TTY or
    --yes path returns EXIF unchanged.
    """
    import sys

    if correct_dt is not None:
        return correct_dt, int((correct_dt - first_dt).total_seconds())
    if not prompt or not sys.stdin.isatty():
        return first_dt, 0
    print(f"First image: {first_name}  EXIF capture: {first_dt:%Y-%m-%d %H:%M:%S}")
    try:
        ans = input("Is this date/time correct? [Y/n] ").strip().lower()
    except EOFError:
        return first_dt, 0
    if ans in ("", "y", "yes"):
        return first_dt, 0
    while True:
        try:
            raw = input(
                "Enter CORRECT date/time for FIRST image [YYYY-MM-DD HH:MM]: "
            ).strip()
        except EOFError:
            return first_dt, 0
        if not raw:
            print("Keeping EXIF datetime.")
            return first_dt, 0
        try:
            fixed = parse_correct_dt(raw, fallback_time=first_dt)
        except ValueError as e:
            print(f"  {e}")
            continue
        delta = int((fixed - first_dt).total_seconds())
        print(f"  Correction: {delta:+d}s ({delta / 3600:+.2f}h) applied to all {first_name}…")
        return fixed, delta


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
    correct_dt: datetime | str | None = None,
    prompt: bool = True,
    gps: str | None = None,
    only_basenames: list[str] | set[str] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> Session:
    exiftool = cfg.tools.get("exiftool") or shutil.which("exiftool")
    if not exiftool:
        raise RuntimeError("exiftool is required for import")

    source = source.expanduser().resolve()
    rafs = list_source_rafs(source)
    if not rafs:
        raise FileNotFoundError(f"No RAF files under {source}")
    if only_basenames:
        want = {n for n in only_basenames}
        rafs = [p for p in rafs if p.name in want]
        if not rafs:
            raise FileNotFoundError("Selected files matched nothing under source")
    if limit is not None:
        if limit < 1:
            raise ValueError("--limit must be >= 1")
        rafs = rafs[:limit]

    gps_norm: str | None = None
    if gps:
        from .meta import parse_gps_input

        lat_s, lon_s = parse_gps_input(gps)
        gps_norm = f"{lat_s},{lon_s}"

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

    if isinstance(correct_dt, str):
        correct_dt = parse_correct_dt(correct_dt, fallback_time=first_dt)
    effective_first, offset = resolve_correction(
        rafs[0].name, first_dt, correct_dt=correct_dt, prompt=prompt
    )
    from datetime import timedelta as _td

    _delta = _td(seconds=offset)

    sess_date = shoot_date or effective_first.date()
    slug = name or "shoot"
    session_path = make_session_dir(cfg.archive_path(), sess_date, slug)

    session = Session(
        name=_slug_from_path(session_path),
        date=sess_date.isoformat(),
        path=str(session_path),
        camera="X-E3",
        stock=cfg.default_stock or "acros",
        source=str(source),
        original_first_dt=first_dt.isoformat(timespec="seconds"),
        corrected_first_dt=effective_first.isoformat(timespec="seconds"),
        dt_offset_seconds=offset,
        gps=gps_norm,
    )
    session.ensure_dirs()

    checksums: dict[str, str] = {}
    copied = 0
    skipped = 0
    log_lines: list[str] = []
    if offset:
        log_lines.append(
            f"CORRECTION first={first_dt:%Y-%m-%d %H:%M:%S} "
            f"corrected={effective_first:%Y-%m-%d %H:%M:%S} offset={offset:+d}s"
        )

    for idx, src in enumerate(rafs, 1):
        meta = _meta_for(src)
        dt = _parse_dt(
            _tag(meta, "DateTimeOriginal", "Date/Time Original", "CreateDate", "Create Date")
        )
        if dt is None:
            dt = datetime.fromtimestamp(src.stat().st_mtime)
            log_lines.append(f"WARN no EXIF date for {src.name}; using mtime")
        if offset:
            dt = dt + _delta
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
                if progress is not None:
                    try:
                        progress(idx, len(rafs), dest_name)
                    except Exception:
                        pass
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
        if progress is not None:
            try:
                progress(idx, len(rafs), dest_name)
            except Exception:
                pass

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


def scan_source(
    cfg: UserConfig, source: Path, *, correct_dt: datetime | str | None = None
) -> dict:
    """List RAFs under source with EXIF datetimes + per-day groups.

    Applies correct_dt delta (if given) to corrected_dts for preview.
    Used by web UI pre-import planning. Read-only, no copies.
    """
    import shutil as _shutil

    exiftool = cfg.tools.get("exiftool") or _shutil.which("exiftool")
    if not exiftool:
        raise RuntimeError("exiftool is required for scan")
    source = source.expanduser().resolve()
    rafs = list_source_rafs(source)
    if not rafs:
        raise FileNotFoundError(f"No RAF files under {source}")
    batch = _exiftool_batch(rafs, exiftool)

    files: list[dict] = []
    for p in rafs:
        meta = batch.get(str(p), {})
        dt = _parse_dt(
            meta.get("DateTimeOriginal") or meta.get("CreateDate") or ""
        )
        if dt is None:
            dt = datetime.fromtimestamp(p.stat().st_mtime)
        files.append({"name": p.name, "dt": dt.isoformat(timespec="seconds")})

    first_dt = datetime.fromisoformat(files[0]["dt"])
    corr: datetime | None = None
    if isinstance(correct_dt, str) and correct_dt.strip():
        corr = parse_correct_dt(correct_dt, fallback_time=first_dt)
    elif isinstance(correct_dt, datetime):
        corr = correct_dt
    offset = int((corr - first_dt).total_seconds()) if corr else 0

    from datetime import timedelta as _td

    groups: dict[str, list[dict]] = {}
    for f in files:
        dt = datetime.fromisoformat(f["dt"])
        cdt = dt + _td(seconds=offset) if offset else dt
        f["corrected_dt"] = cdt.isoformat(timespec="seconds")
        day = cdt.date().isoformat()
        groups.setdefault(day, []).append(f)

    out_groups = []
    for day in sorted(groups):
        fs = groups[day]
        out_groups.append(
            {
                "date": day,
                "count": len(fs),
                "first": fs[0]["name"],
                "last": fs[-1]["name"],
                "first_dt": fs[0]["corrected_dt"],
                "last_dt": fs[-1]["corrected_dt"],
                "files": [f["name"] for f in fs],
                "suggest_slug": f"shoot-{day[5:].replace('-', '')}",
            }
        )
    return {
        "source": str(source),
        "count": len(files),
        "first_name": files[0]["name"],
        "first_dt": files[0]["dt"],
        "corrected_first_dt": (corr or first_dt).isoformat(timespec="seconds"),
        "offset_seconds": offset,
        "groups": out_groups,
    }


def _slug_from_path(path: Path) -> str:
    # folder is YYYY-MM-DD-slug
    name = path.name
    parts = name.split("-", 3)
    if len(parts) >= 4:
        return parts[3]
    return name
