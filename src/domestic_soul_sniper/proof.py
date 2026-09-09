"""Neutral proof generation."""

from __future__ import annotations

from .config import UserConfig
from .engines import rawtherapee as rt
from .paths import recipe_pp3
from .session import Session, save_session


def run_proof(cfg: UserConfig, session: Session) -> Session:
    raws = session.list_raws()
    if not raws:
        raise FileNotFoundError(f"No RAF in {session.raw_dir()}")

    out_dir = session.proof_neutral_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    base = recipe_pp3("base-neutral-xe3")
    cli = cfg.tools.get("rawtherapee-cli")

    produced = rt.process(
        inputs=raws,
        output_dir=out_dir,
        pp3_files=[base],
        cli=cli,
        jpeg_quality=85,
        fast=True,
        log_path=session.logs_dir() / "proof.log",
    )
    session.counts["proof_neutral"] = len(produced)
    session.stages.proofed = True
    save_session(session)
    return session
