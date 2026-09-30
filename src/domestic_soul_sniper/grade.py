"""ACROS (and future stock) grading."""

from __future__ import annotations

from .config import UserConfig
from .engines import rawtherapee as rt
from .paths import recipe_pp3
from .session import Session, save_session
from .tune import overlay_pp3

KNOWN_STOCKS = ("acros", "acros-ye", "acros-r", "acros-g")


def run_grade(cfg: UserConfig, session: Session, stock: str | None = None) -> Session:
    stock = (stock or cfg.default_stock or "acros").lower()
    if stock not in KNOWN_STOCKS:
        raise ValueError(f"Unknown stock {stock!r}; known: {', '.join(KNOWN_STOCKS)}")

    targets = session.target_raws()
    if not targets:
        raise FileNotFoundError(
            f"No target RAFs (raw empty or selects matched nothing) in {session.root()}"
        )

    out_dir = session.graded_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    base = recipe_pp3("base-neutral-xe3")
    look = recipe_pp3(stock)
    pp3_stack = [base, look]
    tune = overlay_pp3(session.root())
    if tune is not None:
        pp3_stack.append(tune)
    cli = cfg.tools.get("rawtherapee-cli")

    produced = rt.process(
        inputs=targets,
        output_dir=out_dir,
        pp3_files=pp3_stack,
        cli=cli,
        jpeg_quality=95,
        fast=False,
        log_path=session.logs_dir() / f"grade-{stock}.log",
    )

    session.stock = stock
    session.counts["graded"] = len(produced)
    session.counts["grade_targets"] = len(targets)
    session.stages.graded = True
    save_session(session)
    return session


def run_preview(
    cfg: UserConfig, session: Session, stems: list[str], stock: str | None = None
) -> list[str]:
    """Grade specific stems (by full or short stem) with current tune stack.

    Returns output filenames in graded/. Does not alter selects/stages counts
    except marking graded=True. Used by web UI tune preview.
    """
    from pathlib import Path

    stock = (stock or session.stock or cfg.default_stock or "acros").lower()
    if stock not in KNOWN_STOCKS:
        raise ValueError(f"Unknown stock {stock!r}; known: {', '.join(KNOWN_STOCKS)}")
    wanted = {Path(s).stem for s in stems if s}
    if not wanted:
        raise ValueError("no stems requested")
    targets = []
    for raw in session.list_raws():
        stem = raw.stem
        orig = stem.split("_")[-1] if "_" in stem else stem
        if stem in wanted or orig in wanted or any(stem.endswith(w) for w in wanted):
            targets.append(raw)
    if not targets:
        raise FileNotFoundError(f"no RAF matched {sorted(wanted)}")

    base = recipe_pp3("base-neutral-xe3")
    look = recipe_pp3(stock)
    pp3_stack = [base, look]
    tune = overlay_pp3(session.root())
    if tune is not None:
        pp3_stack.append(tune)
    out_dir = session.graded_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    produced = rt.process(
        inputs=targets,
        output_dir=out_dir,
        pp3_files=pp3_stack,
        cli=cfg.tools.get("rawtherapee-cli"),
        jpeg_quality=90,
        fast=False,
        log_path=session.logs_dir() / "grade-preview.log",
    )
    session.stages.graded = True
    session.counts["graded"] = len(list(out_dir.glob("*.jpg"))) + len(
        list(out_dir.glob("*.JPG"))
    )
    save_session(session)
    return [p.name for p in produced]
