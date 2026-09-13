"""Export print and web JPEGs from graded output."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import yaml

from .config import UserConfig
from .meta import strip_sensitive
from .paths import export_recipe
from .session import Session, save_session


def _magick(cfg: UserConfig) -> str | None:
    return cfg.tools.get("magick") or shutil.which("magick") or cfg.tools.get("convert") or shutil.which(
        "convert"
    )


def _load_export_spec(name: str = "default") -> dict:
    data = yaml.safe_load(export_recipe(name).read_text(encoding="utf-8")) or {}
    return data


def _resize_long_edge(magick: str, src: Path, dest: Path, long_edge: int, quality: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # ImageMagick geometry: long edge via '>' only shrink
    geom = f"{long_edge}x{long_edge}>"
    cmd = [
        magick,
        str(src),
        "-colorspace",
        "sRGB",
        "-filter",
        "Lanczos",
        "-resize",
        geom,
        "-quality",
        str(quality),
        "-sharpen",
        "0x0.5",
        str(dest),
    ]
    # older convert uses same argv0
    if Path(magick).name == "convert":
        cmd = [magick, str(src), "-colorspace", "sRGB", "-resize", geom, "-quality", str(quality), str(dest)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not dest.is_file():
        raise RuntimeError(f"resize failed: {proc.stderr or proc.stdout}")


def run_export(cfg: UserConfig, session: Session, pack: str = "default") -> Session:
    graded = sorted(session.graded_dir().glob("*.jpg")) + sorted(
        session.graded_dir().glob("*.JPG")
    )
    if not graded:
        raise FileNotFoundError("No graded JPEGs — run photo grade first")

    # If selects exist, only export graded files that match targets
    targets = {p.stem for p in session.target_raws()}
    if session.select_stems() is not None:
        graded = [g for g in graded if g.stem in targets]

    spec = _load_export_spec(pack)
    web_spec = spec.get("web") or {}
    web_q = int(web_spec.get("quality") or 88)
    web_edge = int(web_spec.get("long_edge") or 2048)
    strip = bool(spec.get("strip_sensitive", True))

    magick = _magick(cfg)
    web_fullres_fallback = False
    print_dir = session.export_print_dir()
    web_dir = session.export_web_dir()
    print_dir.mkdir(parents=True, exist_ok=True)
    web_dir.mkdir(parents=True, exist_ok=True)

    print_outs: list[Path] = []
    web_outs: list[Path] = []

    for src in graded:
        print_dest = print_dir / f"{src.stem}_print.jpg"
        web_dest = web_dir / f"{src.stem}_web.jpg"

        # print: graded JPEG is already full-res sRGB q95 from RT — copy,
        # don't decompress/re-encode (pure generation loss). Was: magick
        # re-encode at q95 on every export.
        shutil.copy2(src, print_dest)
        print_outs.append(print_dest)

        if magick:
            _resize_long_edge(magick, src, web_dest, web_edge, web_q)
        else:
            # no magick: full-res copy is NOT a 2048 web file — flag loudly.
            shutil.copy2(src, web_dest)
            web_fullres_fallback = True
        web_outs.append(web_dest)

    if strip:
        strip_sensitive(
            cfg,
            print_outs + web_outs,
            log_path=session.logs_dir() / "export-strip.log",
        )

    # Re-apply non-sensitive identity after strip if needed
    _restamp_identity(cfg, session, print_outs + web_outs)

    session.counts["export_print"] = len(print_outs)
    session.counts["export_web"] = len(web_outs)
    session.counts["export_web_fullres_fallback"] = int(web_fullres_fallback)
    session.stages.exported = True
    save_session(session)
    if web_fullres_fallback:
        print("WARNING: magick not found — web exports are full-res copies, NOT 2048px")
    return session


def _restamp_identity(cfg: UserConfig, session: Session, files: list[Path]) -> None:
    if not files:
        return
    et = cfg.tools.get("exiftool") or shutil.which("exiftool")
    if not et:
        return
    cmd = [et, "-overwrite_original", "-P", "-sep", ", "]
    if cfg.creator:
        cmd.append(f"-Artist={cfg.creator}")
        cmd.append(f"-Creator={cfg.creator}")
    if cfg.copyright:
        cmd.append(f"-Copyright={cfg.copyright}")
        cmd.append(f"-Rights={cfg.copyright}")
    if session.keywords:
        joined = ", ".join(session.keywords)
        cmd.append(f"-Keywords={joined}")
        cmd.append(f"-Subject={joined}")
    cmd.extend(str(p) for p in files)
    subprocess.run(cmd, capture_output=True, text=True, check=False)
