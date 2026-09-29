#!/usr/bin/env python3
"""Install the shared-engine Fcitx trial, restricted to the BrowserOS app ID."""

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
METHOD = "autocorrect-probe-surrounding"
SERVICE = "omarchy-fcitx5.service"


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=20).stdout


def controller(method, *args):
    return run("busctl", "--user", "--json=short", "call", "org.fcitx.Fcitx5", "/controller",
               "org.fcitx.Fcitx.Controller1", method, *args)


def install():
    spec = importlib.util.spec_from_file_location("panel_installer", ROOT / "scripts/install-omarchy-panel.py")
    panel = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(panel)
    home = Path.home()
    library = home / ".local/lib/autocorrect/libautocorrectprobe.so"
    addon = home / ".local/share/fcitx5/addon/autocorrectprobe.conf"
    method = home / f".local/share/fcitx5/inputmethod/{METHOD}.conf"
    dropin = home / f".config/systemd/user/{SERVICE}.d/autocorrect.conf"
    marker = home / ".config/autocorrect/desktop-install.json"
    old = json.loads(marker.read_text()).get("files", {}) if marker.exists() else {}
    files = {
        library: (ROOT / "build/fcitx-probe/libautocorrectprobe.so").read_bytes(),
        addon: ("[Addon]\nName=Autocorrect BrowserOS trial\nType=SharedLibrary\n"
                f"Library={str(library)[:-3]}\nCategory=InputMethod\nOnDemand=False\n"
                "\n[Addon/Dependencies]\n0=core\n").encode(),
        method: ("[InputMethod]\nName=Autocorrect - BrowserOS\nLangCode=it\n"
                 "Addon=autocorrectprobe\nConfigurable=False\n").encode(),
        dropin: ("# Managed by autocorrect-omarchy BrowserOS trial\n[Service]\n"
                 'Environment="AUTOCORRECT_PROBE_ENGINE_SOCKET=%t/autocorrect/engine.sock"\n'
                 'Environment="AUTOCORRECT_PROBE_ALLOWED_PROGRAM=BrowserOS"\n'
                 'Environment="AUTOCORRECT_PROBE_AUTO_ACTIVATE=1"\n'
                 'Environment="AUTOCORRECT_PROBE_WAYLAND_ACK=1"\n'
                 'Environment="AUTOCORRECT_PROBE_LEARNING=1"\n').encode(),
    }
    for name in ("manifest.json", "ime-fields.js"):
        files[home / ".local/share/autocorrect/browser-ime" / name] = (ROOT / "shell/browseros" / name).read_bytes()
    for path in files:
        if path.is_symlink() or (path.exists() and
                (not path.is_file() or old.get(str(path)) != panel.digest(path))):
            raise ValueError(f"File esistente non gestito o modificato: {path}")
    group = run("fcitx5-remote", "-q").strip()
    layout, entries = json.loads(controller("InputMethodGroupInfo", "s", group))["data"]
    current = run("fcitx5-remote", "-n").strip()
    # Ask Fcitx to flush its own profile before taking a recoverable snapshot.
    controller("Save")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = home / ".local/state/autocorrect/desktop-backups" / stamp
    backup.mkdir(mode=0o700, parents=True)
    for path in (*files, marker, home / ".config/fcitx5/profile"):
        if path.is_file():
            target = backup / path.relative_to(home)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    panel.atomic_write(backup / "state.json", (json.dumps({
        "group": group, "layout": layout, "entries": entries, "current": current,
        "previously_present": [str(p) for p in files if p.exists()],
        "managed": [str(p) for p in files],
    }, indent=2) + "\n").encode(), 0o600)
    for path, raw in files.items():
        panel.atomic_write(path, raw)
    panel.atomic_write(marker, (json.dumps({"files": {str(p): hashlib.sha256(raw).hexdigest()
        for p, raw in files.items()}, "backup": str(backup), "allowed_program": "BrowserOS"}, indent=2)
        + "\n").encode(), 0o600)
    run("systemctl", "--user", "daemon-reload")
    run("systemctl", "--user", "restart", SERVICE)
    import time
    for _ in range(50):
        try:
            if run("fcitx5-remote", "--check") in ("1\n", "2\n"):
                break
        except subprocess.SubprocessError:
            pass
        time.sleep(.1)
    else:
        raise RuntimeError("Fcitx non è pronto; consultare il journal del servizio.")
    if not any(item[0] == METHOD for item in entries):
        entries.append([METHOD, ""])
    arguments = [group, layout, str(len(entries))]
    for name, variant in entries:
        arguments.extend((name, variant))
    controller("SetInputMethodGroupInfo", "ssa(ss)", *arguments)
    controller("Save")
    print(json.dumps({"installed": METHOD, "allowed_program": "BrowserOS",
                      "backup": str(backup), "activation": "automatic on BrowserOS focus"}, indent=2))


if __name__ == "__main__":
    install()
