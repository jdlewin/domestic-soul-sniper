"""Resolve package and recipe paths."""

from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_ROOT.parent.parent
RECIPES_DIR = REPO_ROOT / "recipes"
RT_RECIPES = RECIPES_DIR / "rawtherapee"
EXPORT_RECIPES = RECIPES_DIR / "exports"

CONFIG_DIR = Path.home() / ".config" / "domestic-soul-sniper"
CONFIG_PATH = CONFIG_DIR / "config.yaml"

DEFAULT_ARCHIVE = Path.home() / "Pictures" / "archive"


def recipe_pp3(name: str) -> Path:
    path = RT_RECIPES / f"{name}.pp3"
    if not path.is_file():
        raise FileNotFoundError(f"Missing PP3 recipe: {path}")
    return path


def export_recipe(name: str = "default") -> Path:
    path = EXPORT_RECIPES / f"{name}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Missing export recipe: {path}")
    return path
