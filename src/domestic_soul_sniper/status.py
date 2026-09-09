"""Session status reporting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .session import Session


def build_status(session: Session) -> dict[str, Any]:
    raws = session.list_raws()
    selects = session.select_stems()
    graded = list(session.graded_dir().glob("*.jpg")) + list(session.graded_dir().glob("*.JPG"))
    proofs = list(session.proof_neutral_dir().glob("*.jpg")) + list(
        session.proof_neutral_dir().glob("*.JPG")
    )
    prints = list(session.export_print_dir().glob("*.jpg"))
    webs = list(session.export_web_dir().glob("*.jpg"))

    return {
        "name": session.name,
        "date": session.date,
        "path": session.path,
        "camera": session.camera,
        "stock": session.stock,
        "source": session.source,
        "keywords": session.keywords,
        "gps": session.gps,
        "strip_gps": session.strip_gps,
        "stages": {
            "imported": session.stages.imported,
            "proofed": session.stages.proofed,
            "graded": session.stages.graded,
            "meta_applied": session.stages.meta_applied,
            "exported": session.stages.exported,
        },
        "counts": {
            "raw": len(raws),
            "proof_neutral": len(proofs),
            "selects": None if selects is None else len(selects),
            "grade_targets": len(session.target_raws()),
            "graded": len(graded),
            "export_print": len(prints),
            "export_web": len(webs),
            **session.counts,
        },
        "selects_active": selects is not None,
    }


def format_human(status: dict[str, Any]) -> str:
    stages = status["stages"]
    done = [k for k, v in stages.items() if v]
    pending = [k for k, v in stages.items() if not v]
    lines = [
        f"session: {status['name']} ({status['date']})",
        f"path:    {status['path']}",
        f"camera:  {status['camera']}  stock: {status['stock']}",
        f"stages:  done=[{', '.join(done) or '—'}]  pending=[{', '.join(pending) or '—'}]",
        f"counts:  raw={status['counts'].get('raw')}  "
        f"proof={status['counts'].get('proof_neutral')}  "
        f"targets={status['counts'].get('grade_targets')}  "
        f"graded={status['counts'].get('graded')}  "
        f"print={status['counts'].get('export_print')}  "
        f"web={status['counts'].get('export_web')}",
    ]
    if status.get("keywords"):
        lines.append(f"keywords: {', '.join(status['keywords'])}")
    if status.get("selects_active"):
        lines.append(f"selects:  active ({status['counts'].get('selects')} entries)")
    return "\n".join(lines)


def to_json(status: dict[str, Any]) -> str:
    return json.dumps(status, indent=2, sort_keys=False)
