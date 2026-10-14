"""Build the Windows executable and explicitly bundle Qt's ICU DLLs.

CrossOver/Wine reports only a generic QtCore import failure when these are
missing; native Windows can mask the omission if ICU exists elsewhere on PATH.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_SIDE = Path(__import__("PySide6").__file__).resolve().parent
REQUIRED_ICU_PREFIXES = ("icudt", "icuin", "icuuc")


def collect_icu_binaries(pyside_root: Path) -> list[Path]:
    """Return ICU DLLs from the PySide6 wheel or fail closed if absent."""
    dlls = sorted(
        p for p in pyside_root.rglob("*.dll")
        if p.name.casefold().startswith(REQUIRED_ICU_PREFIXES)
    )
    missing = [prefix for prefix in REQUIRED_ICU_PREFIXES
               if not any(p.name.casefold().startswith(prefix) for p in dlls)]
    if missing:
        raise RuntimeError(
            f"PySide6 wheel is missing required Qt ICU DLLs: {', '.join(missing)}"
        )
    return dlls


def build(pyside_root: Path = PY_SIDE) -> None:
    icu_dlls = collect_icu_binaries(pyside_root)
    print("Bundling Qt ICU DLLs:")
    for dll in icu_dlls:
        print(f"  {dll}")
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--windowed", "--onefile", "--name", "Tempo-Map-Extractor",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build" / "windows"),
        "--specpath", str(ROOT / "build" / "windows"),
        str(ROOT / "app.py"),
    ]
    for dll in icu_dlls:
        command.extend(["--add-binary", f"{dll};PySide6"])
    subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    build()
