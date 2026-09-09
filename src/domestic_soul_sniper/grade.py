"""ACROS (and future stock) grading."""

from __future__ import annotations

from .config import UserConfig
from .engines import rawtherapee as rt
from .paths import recipe_pp3
from .session import Session, save_session

KNOWN_STOCKS = ("acros",)


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
    cli = cfg.tools.get("rawtherapee-cli")

    produced = rt.process(
        inputs=targets,
        output_dir=out_dir,
        pp3_files=[base, look],
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
