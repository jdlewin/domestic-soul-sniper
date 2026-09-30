"""Per-session grade tuning overlay.

Proofs are Fuji in-camera ACROS JPEGs (embedded previews); our RT
acros.pp3 is an approximation. This module stores small user-tunable
deltas as session/tune.yaml and renders them as session/tune.pp3,
layered after base + stock in grade (and single-frame preview).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

TUNE_FILENAME = "tune.yaml"
TUNE_PP3NAME = "tune.pp3"

# name -> (default, min, max, step, pp3 section/key hint)
PARAMS: dict[str, tuple[float, float, float, float]] = {
    "exposure": (0.0, -2.0, 2.0, 0.1),      # [Exposure] Compensation
    "brightness": (0.0, -50.0, 50.0, 1.0),  # [Exposure] Brightness
    "contrast": (12.0, 0.0, 50.0, 1.0),     # [Exposure] Contrast (acros base 12)
    "black": (0.0, -20.0, 20.0, 1.0),       # [Exposure] Black
    "highlights": (10.0, -100.0, 100.0, 1.0),  # [Shadows & Highlights] Highlights
    "shadows": (8.0, -100.0, 100.0, 1.0),      # [Shadows & Highlights] Shadows
}


def defaults() -> dict[str, float]:
    return {k: v[0] for k, v in PARAMS.items()}


def tune_yaml_path(root: Path) -> Path:
    return root / TUNE_FILENAME


def tune_pp3_path(root: Path) -> Path:
    return root / TUNE_PP3NAME


def load_tune(root: Path) -> dict[str, float]:
    params = defaults()
    yml = tune_yaml_path(root)
    if yml.is_file():
        try:
            data = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
        for k in params:
            try:
                v = float(data.get(k, params[k]))
            except (TypeError, ValueError):
                continue
            lo, hi = PARAMS[k][1], PARAMS[k][2]
            params[k] = max(lo, min(hi, v))
    return params


def save_tune(root: Path, params: dict[str, Any]) -> dict[str, float]:
    clean = defaults()
    for k in clean:
        if k in params:
            try:
                v = float(params[k])
            except (TypeError, ValueError):
                raise ValueError(f"bad value for {k!r}: {params[k]!r}")
            lo, hi = PARAMS[k][1], PARAMS[k][2]
            if not (lo <= v <= hi):
                raise ValueError(f"{k} out of range [{lo}, {hi}]: {v}")
            clean[k] = v
    root.mkdir(parents=True, exist_ok=True)
    tune_yaml_path(root).write_text(
        yaml.safe_dump(clean, sort_keys=False), encoding="utf-8"
    )
    tune_pp3_path(root).write_text(render_pp3(clean), encoding="utf-8")
    return clean


def render_pp3(params: dict[str, float]) -> str:
    return f"""[Version]
AppVersion=5.12
Version=352

[Exposure]
Compensation={params['exposure']}
Brightness={params['brightness']:.0f}
Contrast={params['contrast']:.0f}
Black={params['black']:.0f}

[Shadows & Highlights]
Enabled=true
Highlights={params['highlights']:.0f}
Shadows={params['shadows']:.0f}
"""


def overlay_pp3(root: Path) -> Path | None:
    """Return tune.pp3 path if user has tuned (yaml exists), else None."""
    if tune_yaml_path(root).is_file() and tune_pp3_path(root).is_file():
        return tune_pp3_path(root)
    return None
