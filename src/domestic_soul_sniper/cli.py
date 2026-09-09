"""photo CLI entrypoint."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from . import __version__
from .config import require_config, run_setup
from .export import run_export
from .grade import run_grade
from .import_card import import_photos
from .meta import run_meta
from .proof import run_proof
from .session import load_session
from .status import build_status, format_human, to_json


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="photo",
        description="domestic-soul-sniper — X-E3 ACROS photography pipeline",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup", help="Create or update user config (interactive)")
    setup.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing identity fields via prompts",
    )

    imp = sub.add_parser("import", help="Import RAF from card or folder into a session")
    imp.add_argument("path", type=Path, help="Card mount or folder of RAF files")
    imp.add_argument("--name", dest="name", default=None, help="Session slug")
    imp.add_argument(
        "--date",
        type=_parse_date,
        default=None,
        help="Session date YYYY-MM-DD (default: from first RAF)",
    )
    imp.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Import at most N RAF files (smoke/dev)",
    )

    proof = sub.add_parser("proof", help="Write neutral fast proof JPEGs")
    proof.add_argument("session", type=Path, help="Session directory")

    grade = sub.add_parser("grade", help="Grade with film stock (default: acros)")
    grade.add_argument("session", type=Path, help="Session directory")
    grade.add_argument(
        "--stock",
        default=None,
        help="Stock id (default: acros)",
    )

    meta = sub.add_parser("meta", help="Apply metadata to graded files (or raws)")
    meta.add_argument("session", type=Path, help="Session directory")
    meta.add_argument(
        "--keyword",
        action="append",
        default=[],
        dest="keywords",
        help="Keyword (repeatable)",
    )
    meta.add_argument("--gps", default=None, help="LAT,LON")
    meta.add_argument(
        "--strip-gps",
        action="store_true",
        help="Strip GPS from session policy / tagged files",
    )

    export = sub.add_parser("export", help="Export print + web JPEGs")
    export.add_argument("session", type=Path, help="Session directory")
    export.add_argument(
        "--pack",
        default="default",
        help="Export pack name (default)",
    )

    status = sub.add_parser("status", help="Show session status")
    status.add_argument("session", type=Path, help="Session directory")
    status.add_argument("--json", action="store_true", dest="as_json")

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "setup":
            run_setup(force=bool(args.force))
            return 0

        cfg = require_config()

        if args.command == "import":
            session = import_photos(
                cfg,
                args.path,
                name=args.name,
                shoot_date=args.date,
                limit=args.limit,
            )
            print(f"Imported session: {session.path}")
            print(
                f"  raw={session.counts.get('raw')} "
                f"copied={session.counts.get('imported_copied')} "
                f"skipped={session.counts.get('imported_skipped')}"
            )
            return 0

        session = load_session(args.session)

        if args.command == "proof":
            session = run_proof(cfg, session)
            print(f"Proofs: {session.counts.get('proof_neutral')} -> {session.proof_neutral_dir()}")
            return 0

        if args.command == "grade":
            session = run_grade(cfg, session, stock=args.stock)
            print(
                f"Graded stock={session.stock} "
                f"targets={session.counts.get('grade_targets')} "
                f"out={session.counts.get('graded')} -> {session.graded_dir()}"
            )
            return 0

        if args.command == "meta":
            session = run_meta(
                cfg,
                session,
                keywords=list(args.keywords or []),
                gps=args.gps,
                strip_gps=bool(args.strip_gps),
            )
            print(f"Tagged {session.counts.get('meta_tagged')} files")
            return 0

        if args.command == "export":
            session = run_export(cfg, session, pack=args.pack)
            print(
                f"Export print={session.counts.get('export_print')} "
                f"web={session.counts.get('export_web')}"
            )
            print(f"  {session.export_print_dir()}")
            print(f"  {session.export_web_dir()}")
            return 0

        if args.command == "status":
            st = build_status(session)
            if args.as_json:
                print(to_json(st))
            else:
                print(format_human(st))
            return 0

        parser.error(f"unknown command {args.command}")
        return 2
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
