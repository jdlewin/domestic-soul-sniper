"""RawTherapee CLI wrapper."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class RawTherapeeError(RuntimeError):
    pass


def find_cli(configured: str | None = None) -> str:
    path = configured or shutil.which("rawtherapee-cli")
    if not path:
        raise RawTherapeeError("rawtherapee-cli not found on PATH")
    return path


def process(
    *,
    inputs: list[Path],
    output_dir: Path,
    pp3_files: list[Path],
    cli: str | None = None,
    jpeg_quality: int = 92,
    fast: bool = False,
    log_path: Path | None = None,
) -> list[Path]:
    """Batch-process inputs to JPEG in output_dir. Returns output paths."""
    if not inputs:
        return []
    rt = find_cli(cli)
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = [rt, "-Y", "-o", str(output_dir)]
    if fast:
        cmd.append("-f")
    for pp3 in pp3_files:
        if not pp3.is_file():
            raise RawTherapeeError(f"PP3 not found: {pp3}")
        cmd.extend(["-p", str(pp3)])
    q = max(1, min(100, jpeg_quality))
    cmd.append(f"-j{q}")
    cmd.append("-js3")  # best chroma quality (irrelevant for B&W but fine)
    cmd.append("-c")
    cmd.extend(str(p) for p in inputs)

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "CMD: "
            + " ".join(cmd)
            + "\n\nSTDOUT:\n"
            + (proc.stdout or "")
            + "\n\nSTDERR:\n"
            + (proc.stderr or "")
            + f"\n\nexit={proc.returncode}\n",
            encoding="utf-8",
        )
    if proc.returncode != 0:
        raise RawTherapeeError(
            f"rawtherapee-cli failed ({proc.returncode}): {(proc.stderr or proc.stdout or '')[:500]}"
        )

    outs: list[Path] = []
    for src in inputs:
        # RT writes basename.jpg next to -o dir
        candidate = output_dir / f"{src.stem}.jpg"
        if not candidate.is_file():
            # sometimes .JPG
            alt = output_dir / f"{src.stem}.JPG"
            if alt.is_file():
                candidate = alt
            else:
                continue
        outs.append(candidate)
    return outs
