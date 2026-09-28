#!/usr/bin/env python3
"""Render the native control's eight states without loading it into the desktop shell."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, choices=(320, 375, 414, 768), default=414)
    parser.add_argument("--capture", action="store_true")
    args = parser.parse_args()
    destination = ROOT / "build/omarchy-panel-preview"
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("Commons", "Ui"):
        link = destination / name
        target = Path("/usr/share/omarchy/shell") / name
        if not link.exists():
            link.symlink_to(target, target_is_directory=True)
        elif not link.is_symlink() or link.resolve() != target:
            raise ValueError(f"Percorso di anteprima inatteso: {link}")
    shutil.copyfile(ROOT / "shell/omarchy/ControlRow.qml", destination / "ControlRow.qml")
    shutil.copyfile(ROOT / "shell/omarchy/Controls.preview.qml", destination / "shell.qml")
    env = dict(os.environ, AUTOCORRECT_PREVIEW_WIDTH=str(args.width))
    image = destination / f"controls-{args.width}.png"
    if args.capture:
        env.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", AUTOCORRECT_PREVIEW_IMAGE=str(image))
    subprocess.run(["quickshell", "--no-color", "-p", str(destination)], env=env, check=True, timeout=20 if args.capture else None)
    if args.capture and (not image.is_file() or not image.stat().st_size):
        raise RuntimeError("Anteprima non generata.")
    if args.capture:
        print(image)


if __name__ == "__main__":
    main()
