"""Session folder model and session.yaml."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

SESSION_FILENAME = "session.yaml"
RAW_DIR = "raw"
PROOF_NEUTRAL_DIR = "proof/neutral"
SELECTS_DIR = "selects"
EXPORT_PRINT_DIR = "export/print"
EXPORT_WEB_DIR = "export/web"
LOGS_DIR = "logs"
GRADED_DIR = "graded"  # intermediate full-res graded JPEG before meta/export split


@dataclass
class SessionStages:
    imported: bool = False
    proofed: bool = False
    graded: bool = False
    meta_applied: bool = False
    exported: bool = False


@dataclass
class Session:
    name: str
    date: str  # YYYY-MM-DD
    path: str  # absolute session dir
    camera: str = "X-E3"
    stock: str = "acros"
    source: str = ""
    keywords: list[str] = field(default_factory=list)
    gps: str | None = None  # "lat,lon" or None
    strip_gps: bool = False
    stages: SessionStages = field(default_factory=SessionStages)
    counts: dict[str, int] = field(default_factory=dict)
    checksums: dict[str, str] = field(default_factory=dict)  # basename -> sha256
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def root(self) -> Path:
        return Path(self.path)

    def raw_dir(self) -> Path:
        return self.root() / RAW_DIR

    def proof_neutral_dir(self) -> Path:
        return self.root() / PROOF_NEUTRAL_DIR

    def selects_dir(self) -> Path:
        return self.root() / SELECTS_DIR

    def export_print_dir(self) -> Path:
        return self.root() / EXPORT_PRINT_DIR

    def export_web_dir(self) -> Path:
        return self.root() / EXPORT_WEB_DIR

    def logs_dir(self) -> Path:
        return self.root() / LOGS_DIR

    def graded_dir(self) -> Path:
        return self.root() / GRADED_DIR

    def ensure_dirs(self) -> None:
        for d in (
            self.raw_dir(),
            self.proof_neutral_dir(),
            self.selects_dir(),
            self.export_print_dir(),
            self.export_web_dir(),
            self.logs_dir(),
            self.graded_dir(),
        ):
            d.mkdir(parents=True, exist_ok=True)

    def list_raws(self) -> list[Path]:
        files = sorted(self.raw_dir().glob("*.RAF")) + sorted(self.raw_dir().glob("*.raf"))
        # de-dupe case
        seen: set[str] = set()
        out: list[Path] = []
        for p in files:
            key = p.name.lower()
            if key not in seen:
                seen.add(key)
                out.append(p)
        return out

    def select_stems(self) -> list[str] | None:
        """Return stems to process, or None meaning all raws."""
        sel = self.selects_dir()
        if not sel.is_dir():
            return None
        entries = [
            p
            for p in sel.iterdir()
            if p.is_file() or p.is_symlink()
        ]
        # ignore hidden and session junk
        entries = [p for p in entries if not p.name.startswith(".")]
        if not entries:
            return None
        stems: list[str] = []
        for p in entries:
            name = p.name
            # allow DSCF6123, full renamed stem, or foo.RAF
            stem = Path(name).stem
            # if someone dropped .jpg proofs, still use stem
            stems.append(stem)
        return sorted(set(stems))

    def target_raws(self) -> list[Path]:
        raws = self.list_raws()
        stems = self.select_stems()
        if stems is None:
            return raws
        # match if select stem equals full stem or original DSCF part or is contained
        matched: list[Path] = []
        for raw in raws:
            stem = raw.stem
            orig = stem.split("_")[-1] if "_" in stem else stem
            for s in stems:
                if s == stem or s == orig or stem.endswith(s) or s in stem:
                    matched.append(raw)
                    break
        return matched

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        stages_data = data.get("stages") or {}
        stages = SessionStages(
            imported=bool(stages_data.get("imported")),
            proofed=bool(stages_data.get("proofed")),
            graded=bool(stages_data.get("graded")),
            meta_applied=bool(stages_data.get("meta_applied")),
            exported=bool(stages_data.get("exported")),
        )
        return cls(
            name=str(data["name"]),
            date=str(data["date"]),
            path=str(data["path"]),
            camera=str(data.get("camera") or "X-E3"),
            stock=str(data.get("stock") or "acros"),
            source=str(data.get("source") or ""),
            keywords=list(data.get("keywords") or []),
            gps=data.get("gps"),
            strip_gps=bool(data.get("strip_gps") or False),
            stages=stages,
            counts=dict(data.get("counts") or {}),
            checksums=dict(data.get("checksums") or {}),
            created_at=str(data.get("created_at") or datetime.now().isoformat(timespec="seconds")),
        )


def session_yaml_path(root: Path) -> Path:
    return root / SESSION_FILENAME


def save_session(session: Session) -> None:
    root = session.root()
    root.mkdir(parents=True, exist_ok=True)
    path = session_yaml_path(root)
    path.write_text(
        yaml.safe_dump(session.to_dict(), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def load_session(path: str | Path) -> Session:
    root = Path(path).expanduser().resolve()
    if root.is_file() and root.name == SESSION_FILENAME:
        root = root.parent
    yml = session_yaml_path(root)
    if not yml.is_file():
        raise FileNotFoundError(f"Not a session (missing {SESSION_FILENAME}): {root}")
    data = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
    # keep path current if moved
    data["path"] = str(root)
    return Session.from_dict(data)


def make_session_dir(archive_root: Path, shoot_date: date, slug: str) -> Path:
    slug = _slugify(slug)
    folder = f"{shoot_date.isoformat()}-{slug}"
    path = archive_root / f"{shoot_date.year:04d}" / folder
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _slugify(value: str) -> str:
    out = []
    for ch in value.strip().lower().replace(" ", "-"):
        if ch.isalnum() or ch in "-_":
            out.append(ch)
    slug = "".join(out).strip("-_") or "shoot"
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug
