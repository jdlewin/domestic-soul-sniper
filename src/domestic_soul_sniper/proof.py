"""Fast proof generation via embedded previews, RT fallback."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .config import UserConfig
from .engines import rawtherapee as rt
from .paths import recipe_pp3
from .session import Session, save_session


def _exiftool(cfg: UserConfig) -> str | None:
    return cfg.tools.get("exiftool") or shutil.which("exiftool")


def extract_previews(
    inputs: list[Path], output_dir: Path, exiftool: str | None = None
) -> tuple[list[Path], list[Path]]:
    """Extract embedded PreviewImage JPEGs in a single exiftool spawn.

    Returns (produced, missing). Produced files are named <stem>.jpg.
    Missing = inputs with no extractable preview (caller falls back to RT).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    if not inputs:
        return [], []
    et = exiftool or shutil.which("exiftool")
    if not et:
        return [], list(inputs)
    # -w %f.jpg writes <basename>.jpg into output_dir; -overwrite avoids prompts.
    cmd = [et, "-q", "-b", "-PreviewImage", "-w", str(output_dir / "%f.jpg"), "-overwrite_original"]
    cmd.extend(str(p) for p in inputs)
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return [], list(inputs)
    produced: list[Path] = []
    missing: list[Path] = []
    for src in inputs:
        for ext in (".jpg", ".JPG"):
            cand = output_dir / f"{src.stem}{ext}"
            if cand.is_file() and cand.stat().st_size > 0:
                produced.append(cand)
                break
        else:
            missing.append(src)
    return produced, missing


def run_proof(
    cfg: UserConfig, session: Session, *, selects_only: bool = False, use_rt_fallback: bool = True
) -> Session:
    if selects_only and session.select_stems() is not None:
        raws = session.target_raws()
    else:
        raws = session.list_raws()
    if not raws:
        raise FileNotFoundError(f"No RAF in {session.raw_dir()}")

    out_dir = session.proof_neutral_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    et = _exiftool(cfg)
    produced, missing = extract_previews(raws, out_dir, exiftool=et)
    (session.logs_dir() / "proof.log").write_text(
        f"previews: extracted={len(produced)} missing={len(missing)} of {len(raws)}\n",
        encoding="utf-8",
    )

    if missing and use_rt_fallback:
        base = recipe_pp3("base-neutral-xe3")
        cli = cfg.tools.get("rawtherapee-cli")
        rt_produced = rt.process(
            inputs=missing,
            output_dir=out_dir,
            pp3_files=[base],
            cli=cli,
            jpeg_quality=85,
            fast=True,
            log_path=session.logs_dir() / "proof-rt-fallback.log",
        )
        produced = produced + rt_produced

    session.counts["proof_neutral"] = len(produced)
    session.counts["proof_rt_fallback"] = len(missing) if use_rt_fallback else 0
    session.stages.proofed = True
    save_session(session)
    tag_proof_metadata(cfg, session, produced)
    return session


def tag_proof_metadata(
    cfg: UserConfig, session: Session, files: list[Path] | None = None
) -> int:
    """Write import correction (dates) + session GPS into proof JPEGs.

    RAF masters stay pristine (checksummed); proofs are derivatives, so the
    cull UI reads corrected capture datetimes and locations straight away.
    Returns number of files updated.
    """
    from .meta import gps_args, offset_shift_args

    targets = files if files is not None else sorted(
        session.proof_neutral_dir().glob("*.jpg")
    ) + sorted(session.proof_neutral_dir().glob("*.JPG"))
    if not targets:
        return 0
    args = offset_shift_args(int(getattr(session, "dt_offset_seconds", 0) or 0))
    args.extend(gps_args(session.gps))
    if not args:
        return 0
    et = _exiftool(cfg)
    if not et:
        return 0
    cmd = [et, "-overwrite_original", "-P", "-q", *args, *(str(p) for p in targets)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return 0
    (session.logs_dir() / "proof-meta.log").write_text(
        f"tagged={len(targets)} offset={getattr(session, 'dt_offset_seconds', 0)} "
        f"gps={session.gps}\n{(proc.stdout or '')}\n{(proc.stderr or '')}\n"
        f"exit={proc.returncode}\n",
        encoding="utf-8",
    )
    return len(targets) if proc.returncode == 0 else 0
