#!/usr/bin/python3
"""Local input recovery. Standard library only; never run as root."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone


# Experimental installs must stay in these locations. Packages and /etc require
# separate recovery via the Omarchy snapshot, not this user-level tool.
PATHS = (
    ".config/fcitx5",
    ".local/share/fcitx5",
    ".config/hypr",
    ".config/uwsm",
    ".config/environment.d",
    ".XCompose",
    ".config/autostart/org.fcitx.Fcitx5.desktop",
    ".config/systemd/user/omarchy-fcitx5.service",
    ".config/systemd/user/omarchy-fcitx5.service.d",
    ".config/systemd/user/graphical-session.target.wants/omarchy-fcitx5.service",
    ".config/systemd/user/autocorrect.service",
    ".config/systemd/user/autocorrect.service.d",
    ".config/systemd/user/default.target.wants/autocorrect.service",
    ".config/systemd/user/graphical-session.target.wants/autocorrect.service",
    ".config/autostart/autocorrect.desktop",
    ".config/autocorrect",
    ".local/share/autocorrect",
    ".local/lib/autocorrect",
)
SERVICE = "omarchy-fcitx5.service"
HOTKEY_MARKER = "-- autocorrect input-rescue: emergency binding"
HOTKEY = (
    "\n" + HOTKEY_MARKER + "\n"
    'o.bind("SUPER + CTRL + ALT + F12", "Ripristino input (red button)", '
    'os.getenv("HOME") .. "/.local/bin/input-rescue")\n'
)


def exists(path):
    return path.exists() or path.is_symlink()


def copy_path(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        destination.symlink_to(os.readlink(source))
    elif source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    else:
        shutil.copy2(source, destination)


def fingerprint(path):
    if path.is_symlink():
        return {"link": os.readlink(path)}
    if not path.exists():
        return None
    mode = path.stat().st_mode & 0o777
    if path.is_dir():
        return {"mode": mode, "children": {
            p.name: fingerprint(p) for p in sorted(path.iterdir())
        }}
    if not path.is_file():
        raise RuntimeError(f"Tipo di file non supportato: {path}")
    return {"mode": mode, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def run(*args, required=True):
    result = subprocess.run(args, text=True, capture_output=True, timeout=20)
    if required and result.returncode:
        raise RuntimeError(f"{' '.join(args)}: {result.stderr.strip()}")
    return result


class Recovery:
    def __init__(self, home):
        self.home = Path(home).resolve()
        self.state = self.home / ".local/state/autocorrect-recovery"
        self.baseline = self.state / "baseline"

    def check_parents(self, relative):
        # Never write through a redirected parent into another tree.
        parent = (self.home / relative).parent
        while parent != self.home:
            if parent.is_symlink():
                raise RuntimeError(f"Directory padre simbolica: {parent}")
            parent = parent.parent

    def capture(self):
        if exists(self.baseline):
            raise RuntimeError("Il baseline esiste già: non verrà sovrascritto.")
        temporary = self.state / "capture-in-progress"
        temporary.mkdir(mode=0o700)
        manifest = {"version": 1, "home": str(self.home),
                    "created": datetime.now(timezone.utc).isoformat(), "paths": {}}
        try:
            for relative in PATHS:
                self.check_parents(relative)
                source = self.home / relative
                before = fingerprint(source)
                if exists(source):
                    copy_path(source, temporary / "files" / relative)
                saved = fingerprint(temporary / "files" / relative)
                if saved != before or fingerprint(source) != before:
                    raise RuntimeError(f"File cambiato durante il backup: {relative}")
                manifest["paths"][relative] = saved
            (temporary / "manifest.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
            temporary.rename(self.baseline)
        except Exception:
            shutil.rmtree(temporary)
            raise
        print(f"Baseline creato: {self.baseline}")

    def verify(self):
        manifest = json.loads((self.baseline / "manifest.json").read_text())
        if (manifest.get("version") != 1 or manifest.get("home") != str(self.home)
                or set(manifest.get("paths", {})) != set(PATHS)):
            raise RuntimeError("Manifest del baseline non valido per questa installazione.")
        for relative, expected in manifest["paths"].items():
            self.check_parents(relative)
            if fingerprint(self.baseline / "files" / relative) != expected:
                raise RuntimeError(f"Backup danneggiato: {relative}")
        return manifest

    def restore_files(self):
        # Validate everything before moving any current file.
        self.verify()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        saved = self.state / "rescues" / stamp
        saved.mkdir(parents=True, mode=0o700)
        print(f"Stato precedente conservato in: {saved}", flush=True)
        for relative in PATHS:
            current = self.home / relative
            original = self.baseline / "files" / relative
            if exists(current):
                destination = saved / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(current), str(destination))
            if exists(original):
                copy_path(original, current)
        return saved

    def ensure_hotkey(self):
        path = self.home / ".config/hypr/bindings.lua"
        if path.is_symlink():
            raise RuntimeError("bindings.lua è un link: installare il bind manualmente.")
        text = path.read_text()
        if HOTKEY_MARKER not in text:
            path.write_text(text + HOTKEY)


def stop_input():
    # Explicit stop defeats Restart=always. Mask prevents fresh activation.
    for service in (SERVICE, "autocorrect.service"):
        run("systemctl", "--user", "stop", service, required=service == SERVICE)
        run("systemctl", "--user", "mask", "--runtime", service)
    # Catch an instance started manually outside systemd, for this user only.
    run("pkill", "-TERM", "-u", str(os.getuid()), "-x", "fcitx5", required=False)
    for _ in range(20):
        result = run("pgrep", "-u", str(os.getuid()), "-x", "fcitx5", required=False)
        if result.returncode == 1:
            return
        if result.returncode != 0:
            raise RuntimeError("Impossibile verificare l'arresto di Fcitx.")
        time.sleep(0.1)
    run("pkill", "-KILL", "-u", str(os.getuid()), "-x", "fcitx5", required=False)
    time.sleep(0.2)
    if run("pgrep", "-u", str(os.getuid()), "-x", "fcitx5", required=False).returncode != 1:
        raise RuntimeError("Fcitx è ancora attivo: ripristino dei file interrotto.")


def reload_hyprland():
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        print("Da TTY: rientra nella sessione grafica o esegui logout/login per applicare tutto.")
        return
    run("hyprctl", "reload")
    errors = run("hyprctl", "configerrors").stdout.strip()
    if errors:
        raise RuntimeError(f"Hyprland segnala errori dopo il ripristino: {errors}")


def notify(message, urgent=False):
    if shutil.which("notify-send"):
        try:
            run("notify-send", "-u", "critical" if urgent else "normal",
                "Input rescue", message, required=False)
        except (OSError, subprocess.TimeoutExpired):
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", default="restore",
                        choices=("capture", "status", "restore", "stop", "resume", "hotkey"))
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error("Usa il tuo utente, senza sudo.")
    os.umask(0o077)
    recovery = Recovery(Path.home())
    recovery.state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (recovery.state / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "capture":
            recovery.capture()
        elif args.action == "status":
            manifest = recovery.verify()
            print(f"Backup integro: {recovery.baseline}\nCreato: {manifest['created']}")
            print(f"Percorsi coperti: {len(PATHS)} (compresi quelli inizialmente assenti)")
            print(run("systemctl", "--user", "is-active", SERVICE, required=False).stdout.strip())
        elif args.action == "hotkey":
            recovery.verify()
            recovery.ensure_hotkey()
            reload_hyprland()
        elif args.action == "stop":
            stop_input()
            print("Fcitx fermato e mascherato fino al riavvio o a input-rescue resume.")
            notify("Fcitx fermato. Digitazione diretta; input-rescue per ripristinare.")
        elif args.action == "resume":
            recovery.verify()
            run("systemctl", "--user", "unmask", "--runtime", SERVICE)
            run("systemctl", "--user", "daemon-reload")
            run("systemctl", "--user", "reset-failed", SERVICE, required=False)
            run("systemctl", "--user", "start", SERVICE)
            run("systemctl", "--user", "is-active", "--quiet", SERVICE)
            print("Fcitx riavviato. Il servizio sperimentale resta disattivato.")
            notify("Fcitx riavviato.")
        else:
            # Even a damaged backup must not leave a faulty IME running.
            stop_input()
            recovery.restore_files()
            recovery.ensure_hotkey()
            run("systemctl", "--user", "daemon-reload")
            reload_hyprland()
            message = "Baseline ripristinato; Fcitx spento. Per riattivarlo: input-rescue resume"
            print(message)
            notify(message)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        message = f"Operazione non completata: {error}"
        print(message, file=sys.stderr)
        notify(message + ". Se necessario usa la console TTY.", urgent=True)
        sys.exit(1)
