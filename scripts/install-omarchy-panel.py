#!/usr/bin/env python3
"""Install the user-owned Omarchy panel and an initially non-autostarting engine."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from autocorrect_core.settings import DEFAULT_SETTINGS, load_settings, write_settings


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ID = "michele.autocorrect"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unit_argument(value):
    return '"' + str(value).replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"') + '"'


def unit_text(project, config, data):
    if any("\n" in str(path) or "\r" in str(path) for path in (project, config, data)):
        raise ValueError("I percorsi del servizio non possono contenere nuove righe.")
    args = [project / ".venv/bin/python", "-B", "-m", "autocorrect_core.probe_server",
            "--settings", config / "autocorrect/settings.json", "--context-corpus",
            project / "benchmark-data/leipzig-ita-news-2023-100k", "--feedback-memory",
            data / "autocorrect/feedback.sqlite3", "--hunspell"]
    command = " ".join(unit_argument(arg) for arg in args)
    command += " --socket %t/autocorrect/engine.sock --ready %t/autocorrect/ready.json"
    command += " --diagnostics %t/autocorrect/decision.json --feedback-diagnostics %t/autocorrect/feedback.json"
    return ("# Managed by autocorrect-omarchy\n[Unit]\nDescription=Autocorrect Italian engine\n"
            "After=graphical-session.target\nPartOf=graphical-session.target\n\n[Service]\nType=simple\n"
            f"WorkingDirectory={str(project).replace('%', '%%')}\nExecStart={command}\n"
            "RuntimeDirectory=autocorrect\nRuntimeDirectoryMode=0700\nUMask=0077\n"
            "Restart=on-failure\nRestartSec=2\nTimeoutStopSec=3\n\n[Install]\nWantedBy=graphical-session.target\n")


def atomic_write(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as target:
            temporary = Path(target.name)
            target.write(raw)
        temporary.chmod(mode)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def install(project, home, *, enable=True):
    project, home = project.resolve(), home.resolve()
    config, data, state = home / ".config", home / ".local/share", home / ".local/state"
    plugin = config / "omarchy/plugins" / PLUGIN_ID
    marker = plugin / ".autocorrect-install.json"
    settings = config / "autocorrect/settings.json"
    unit = config / "systemd/user/autocorrect.service"
    command = home / ".local/bin/autocorrect-control"
    desktop = data / "applications/autocorrect-control.desktop"
    for needed in (project / ".venv/bin/python", project / "benchmark-data/leipzig-ita-news-2023-100k/ngrams.sqlite3",
                   project / "build/fcitx-probe/libautocorrectprobe.so"):
        if not needed.is_file():
            raise ValueError(f"Prima completare setup, corpus e build Fcitx: manca {needed}")
    if settings.exists():
        load_settings(settings)  # Validate, preserve the user's values.
    if plugin.exists() and not marker.is_file():
        raise ValueError(f"Cartella plugin esistente non gestita dall'installer: {plugin}")
    previous = json.loads(marker.read_text()).get("files", {}) if marker.exists() else {}
    files = {}
    for source in (project / "shell/omarchy").iterdir():
        if source.is_file():
            files[plugin / source.name] = (source.read_bytes(), 0o755 if source.name == "autocorrectctl" else 0o644)
    files[plugin / "backend.json"] = ((json.dumps({"project": str(project), "python": str(project / ".venv/bin/python")}, indent=2) + "\n").encode(), 0o644)
    files[unit] = (unit_text(project, config, data).encode(), 0o644)
    files[command] = (b"#!/usr/bin/env bash\nexec omarchy-shell shell toggle michele.autocorrect '{}'\n", 0o755)
    escaped_command = str(command).replace("\\", "\\\\").replace('"', '\\"')
    files[desktop] = (("[Desktop Entry]\nType=Application\nName=Autocorrect\n"
                      "Comment=Contesto e memoria del correttore italiano\n"
                      f'Exec="{escaped_command}"\nIcon=input-keyboard\nTerminal=false\n'
                      "Categories=Settings;Utility;\nKeywords=autocorrect;correzione;memoria;\n").encode(), 0o644)
    for path in files:
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_file() or previous.get(str(path)) != digest(path):
                raise ValueError(f"File esistente o modificato dall'utente; non sovrascrivo: {path}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = state / "autocorrect/panel-backups" / stamp
    backup.mkdir(mode=0o700, parents=True)
    backed_up = []
    for path in (*files.keys(), settings, config / "omarchy/shell.json", marker):
        if path.is_file():
            destination = backup / path.relative_to(home)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            backed_up.append(str(path.relative_to(home)))
    for path, (raw, mode) in files.items():
        if not path.is_file() or path.read_bytes() != raw:
            atomic_write(path, raw, mode)
    if not settings.exists():
        write_settings(settings, DEFAULT_SETTINGS)
    atomic_write(marker, (json.dumps({"files": {str(path): digest(path) for path in files}}, indent=2) + "\n").encode(), 0o600)
    atomic_write(backup / "manifest.json", (json.dumps({"backed_up": backed_up, "managed": [str(p) for p in files]}, indent=2) + "\n").encode(), 0o600)
    if enable:
        subprocess.run(["omarchy", "plugin", "validate", str(plugin)], check=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["omarchy-shell", "shell", "rescanPlugins"], check=True)
        subprocess.run(["omarchy", "plugin", "enable", PLUGIN_ID], check=True)
    return {"plugin": str(plugin), "service": str(unit), "backup": str(backup), "settings": str(settings),
            "autostart": "not changed", "desktop_integration": "not installed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home(), help="Home alternativa per verifiche isolate")
    parser.add_argument("--no-enable", action="store_true")
    args = parser.parse_args()
    if args.home.resolve() != Path.home().resolve() and not args.no_enable:
        parser.error("Una home di prova richiede --no-enable.")
    print(json.dumps(install(ROOT, args.home, enable=not args.no_enable), indent=2))


if __name__ == "__main__":
    main()
