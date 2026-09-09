"""User config and first-run setup."""

from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .paths import CONFIG_DIR, CONFIG_PATH, DEFAULT_ARCHIVE


@dataclass
class UserConfig:
    creator: str = ""
    copyright: str = ""
    contact: str = ""
    archive_root: str = str(DEFAULT_ARCHIVE)
    default_stock: str = "acros"
    tools: dict[str, str] = field(default_factory=dict)

    def archive_path(self) -> Path:
        return Path(self.archive_root).expanduser().resolve()


def _which(name: str) -> str | None:
    return shutil.which(name)


def detect_tools() -> dict[str, str]:
    found: dict[str, str] = {}
    for name in ("rawtherapee-cli", "exiftool", "magick", "convert"):
        path = _which(name)
        if path:
            found[name] = path
    return found


def load_config(path: Path = CONFIG_PATH) -> UserConfig | None:
    if not path.is_file():
        return None
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tools = data.get("tools") or {}
    return UserConfig(
        creator=str(data.get("creator") or ""),
        copyright=str(data.get("copyright") or ""),
        contact=str(data.get("contact") or ""),
        archive_root=str(data.get("archive_root") or DEFAULT_ARCHIVE),
        default_stock=str(data.get("default_stock") or "acros"),
        tools=dict(tools),
    )


def save_config(cfg: UserConfig, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = asdict(cfg)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _prompt(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{label}{suffix}: ").strip()
    except EOFError:
        value = ""
    return value or default


def run_setup(force: bool = False) -> UserConfig:
    """Interactive setup; writes config.yaml."""
    existing = load_config()
    if existing and not force:
        print(f"Config already exists: {CONFIG_PATH}")
        print("Re-run with intent to overwrite via photo setup --force")
        tools = detect_tools()
        existing.tools = tools
        save_config(existing)
        _print_tools(tools)
        return existing

    print("domestic-soul-sniper setup")
    print("Identity metadata (applied on meta/export). Leave blank to skip.")
    base = existing or UserConfig()
    creator = _prompt("Creator / by-line", base.creator)
    copyright_ = _prompt("Copyright notice", base.copyright or _default_copyright(creator))
    contact = _prompt("Contact (email/url, optional)", base.contact)
    archive = _prompt("Archive root", base.archive_root or str(DEFAULT_ARCHIVE))

    tools = detect_tools()
    cfg = UserConfig(
        creator=creator,
        copyright=copyright_,
        contact=contact,
        archive_root=str(Path(archive).expanduser()),
        default_stock="acros",
        tools=tools,
    )
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg.archive_path().mkdir(parents=True, exist_ok=True)
    save_config(cfg)
    print(f"Wrote {CONFIG_PATH}")
    _print_tools(tools)
    if "rawtherapee-cli" not in tools:
        print("WARNING: rawtherapee-cli not found on PATH")
    if "exiftool" not in tools:
        print("WARNING: exiftool not found on PATH")
    return cfg


def _default_copyright(creator: str) -> str:
    if not creator:
        return ""
    from datetime import date

    return f"© {date.today().year} {creator}. All rights reserved."


def _print_tools(tools: dict[str, str]) -> None:
    print("Tools:")
    for name in ("rawtherapee-cli", "exiftool", "magick", "convert"):
        print(f"  {name}: {tools.get(name, 'NOT FOUND')}")


def require_config() -> UserConfig:
    cfg = load_config()
    if cfg is None:
        print("No config found — running first-time setup.")
        cfg = run_setup(force=True)
    else:
        # refresh tool paths
        tools = detect_tools()
        if tools != cfg.tools:
            cfg.tools = tools
            save_config(cfg)
    return cfg
