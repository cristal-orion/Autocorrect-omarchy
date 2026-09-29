#!/usr/bin/env python3
"""Open the real BrowserOS trial with its own profile and the desktop Fcitx."""

import json
from pathlib import Path
import subprocess
import time

from autocorrect_core.control import Controller


ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=15).stdout


def main():
    controller = Controller()
    state = controller.status()
    if not state.get("desktop_trial"):
        raise SystemExit("Prima eseguire .venv/bin/python scripts/install-browseros-probe.py")
    if not state["connected"]:
        controller.service("start")
    if not state["settings"]["correction_enabled"]:
        controller.configure({"correction_enabled": True})
    wrapper = Path.home() / ".local/bin/browseros"
    profile = ROOT / "build/browseros-profile"
    profile.mkdir(parents=True, exist_ok=True)
    preferences = profile / "Default/Preferences"
    preferences.parent.mkdir(parents=True, exist_ok=True)
    # Seed only a new profile. Existing/live preferences belong to the browser.
    try:
        with preferences.open("x") as target:
            json.dump({"spellcheck": {"dictionaries": ["it", "en-US"]},
                       "intl": {"selected_languages": "it,en-US,en"}}, target)
    except FileExistsError:
        pass
    command = [str(wrapper), f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check"]
    log_path = ROOT / "build/browseros-probe.log"
    with log_path.open("a") as log:
        subprocess.Popen([*command, "about:blank"], stdin=subprocess.DEVNULL, stdout=log,
                         stderr=log, start_new_session=True)
        # First-run BrowserOS tabs can otherwise steal focus from the test page.
        time.sleep(5)
        subprocess.Popen([*command, "--new-window", (ROOT / "probes/browseros.html").as_uri()],
                         stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        clients = json.loads(run("hyprctl", "-j", "clients"))
        window = next((w for w in clients if w["class"] == "BrowserOS"
                       and "Autocorrect — prova BrowserOS" in w["title"]), None)
        if window:
            if window["xwayland"]:
                raise SystemExit("La prova richiede BrowserOS Wayland; verificare il wrapper.")
            target = "address:" + window["address"]
            run("hyprctl", "dispatch", f"hl.dsp.focus({{window={json.dumps(target)}}})")
            time.sleep(.3)
            run("fcitx5-remote", "-s", "autocorrect-probe-surrounding")
            run("fcitx5-remote", "-o")
            if run("fcitx5-remote", "-n").strip() != "autocorrect-probe-surrounding":
                raise SystemExit("Selezione del metodo di prova non riuscita.")
            print(json.dumps({"opened": True, "app": "BrowserOS", "xwayland": False,
                "profile": str(profile), "page": str(ROOT / "probes/browseros.html"),
                "pause": "Disattiva Correzione automatica o premi Ferma nel pannello Omarchy."}, ensure_ascii=False))
            return
        time.sleep(.2)
    raise SystemExit(f"Finestra non rilevata; consultare {log_path}")


if __name__ == "__main__":
    main()
