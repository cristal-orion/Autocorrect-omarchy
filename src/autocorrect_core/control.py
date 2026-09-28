"""JSON controller for the native Omarchy panel and the user engine service."""

import argparse
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time

from .engine import latin_word
from .feedback import FeedbackMemory, feedback_word
from .settings import load_settings, validate_patch, write_settings


UNIT = "autocorrect.service"


@dataclass(frozen=True)
class ControlPaths:
    project: Path
    settings: Path
    memory: Path
    runtime: Path
    unit: Path

    @classmethod
    def current(cls):
        home = Path.home()
        config = Path(os.environ.get("XDG_CONFIG_HOME", str(home / ".config")))
        data = Path(os.environ.get("XDG_DATA_HOME", str(home / ".local/share")))
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        project = Path(os.environ.get("AUTOCORRECT_PROJECT_ROOT", str(Path(__file__).resolve().parents[2])))
        return cls(project, config / "autocorrect/settings.json", data / "autocorrect/feedback.sqlite3",
                   runtime / "autocorrect", config / "systemd/user" / UNIT)

    @property
    def socket(self):
        return self.runtime / "engine.sock"


def rpc(path, payload, timeout=.75):
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
    if len(raw) >= 4096:
        raise ValueError("Richiesta troppo grande.")
    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as connection:
        connection.settimeout(timeout)
        connection.connect(str(path))
        connection.sendall(raw)
        data, _, flags, _ = connection.recvmsg(16384)
    if flags & socket.MSG_TRUNC:
        raise ValueError("Risposta del motore troppo grande.")
    result = json.loads(data)
    if not isinstance(result, dict) or result.get("reason") == "invalid_request":
        raise ValueError("Il motore ha rifiutato la richiesta.")
    return result


class Controller:
    def __init__(self, paths=None):
        self.paths = paths or ControlPaths.current()

    def service_state(self):
        result = subprocess.run(["systemctl", "--user", "show", UNIT,
            "--property=LoadState,ActiveState,SubState,UnitFileState"], capture_output=True, text=True, timeout=5)
        values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        return {"loaded": values.get("LoadState", "unknown"), "active": values.get("ActiveState", "unknown"),
                "substate": values.get("SubState", "unknown"), "autostart": values.get("UnitFileState", "").startswith("enabled")}

    def engine_state(self):
        try:
            result = rpc(self.paths.socket, {"op": "status"})
            if result.get("state", {}).get("protocol_version") != 1:
                return None
            return result
        except (OSError, ValueError):
            return None

    def status(self):
        engine = self.engine_state()
        values = engine["state"]["settings"] if engine else load_settings(self.paths.settings)
        memory = engine.get("memory") if engine else None
        memory_error = ""
        if memory is None and self.paths.memory.exists():
            try:
                with FeedbackMemory(self.paths.memory, read_only=True) as stored:
                    memory = stored.status()
            except (OSError, ValueError, sqlite3.Error) as error:
                memory_error = f"Memoria non leggibile: {error}"
        elif memory is None:
            memory = {"confirmations": 0, "rejections": 0, "pair_count": 0}
        return {"ok": True, "connected": engine is not None, "service": self.service_state(),
                "settings": values, "memory": memory, "memory_error": memory_error,
                "scope": "laboratory", "desktop_integration": False,
                "apps": ["BrowserOS", "ZapFast", "Slack"], "terminal_mode": "manual_chat_pending",
                "capabilities": engine["state"]["capabilities"] if engine else {},
                "paths": {"memory": str(self.paths.memory), "settings": str(self.paths.settings)}}

    def configure(self, patch):
        patch = validate_patch(patch)
        if self.engine_state() is not None:
            result = rpc(self.paths.socket, {"op": "configure", "changes": patch})
            if result.get("configured") is not True:
                raise ValueError("Modifica non confermata dal motore. Riavvia il servizio.")
        else:
            # The online engine serializes changes. Offline callers use a file
            # lock so two panels never replace each other's independent edits.
            self.paths.settings.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(self.paths.settings.with_suffix(".lock"), os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                write_settings(self.paths.settings, {**load_settings(self.paths.settings), **patch})
            finally:
                os.close(fd)
        return {**self.status(), "message": "Impostazioni salvate."}

    def forget(self, token):
        token = feedback_word(token.strip())
        if not latin_word(token) or len(token) > 64:
            raise ValueError("Indica una sola parola, per esempio pne.")
        if self.engine_state() is not None:
            result = rpc(self.paths.socket, {"op": "forget", "token": token})
            detail = result.get("feedback", {})
            if detail.get("status") != "forgotten":
                raise ValueError("Dimenticanza non confermata dal motore.")
            count = detail["forgotten_events"]
        elif self.paths.memory.exists():
            with FeedbackMemory(self.paths.memory) as memory:
                count = memory.forget(token)
        else:
            count = 0
        return {**self.status(), "message": f"Dimenticato {token}: {count} eventi rimossi.", "forgotten_events": count}

    def service(self, action):
        if action not in ("start", "stop", "restart", "enable", "disable"):
            raise ValueError("Azione del servizio non valida.")
        if not self.paths.unit.is_file() or not self.paths.unit.read_text().startswith("# Managed by autocorrect-omarchy"):
            raise ValueError("Servizio non installato dal progetto. Esegui l'installer del pannello.")
        completed = subprocess.run(["systemctl", "--user", action, UNIT], capture_output=True, text=True, timeout=15)
        if completed.returncode:
            raise RuntimeError(completed.stderr.strip() or "Comando del servizio fallito.")
        if action in ("start", "restart"):
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if self.engine_state() is not None:
                    break
                time.sleep(.15)
            else:
                raise RuntimeError("Il motore non è pronto. Controlla journalctl --user -u autocorrect.service.")
        return self.status()

    def open_probe(self):
        if self.engine_state() is None:
            self.service("start")
        script = self.paths.project / "scripts/run-fcitx-probe.py"
        if not script.is_file():
            raise ValueError("Launcher di prova non trovato. Reinstalla il pannello dal progetto.")
        subprocess.Popen([sys.executable, str(script), "--client", "qt", "--mode", "surrounding", "--engine", "core",
                          "--shared-engine"], cwd=self.paths.project, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return {**self.status(), "message": "Apertura della prova collegata al pannello."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "start", "stop", "restart", "open-probe"):
        sub.add_parser(name)
    setting = sub.add_parser("set")
    setting.add_argument("key")
    setting.add_argument("value", help="Valore JSON: true, false o numero")
    forget = sub.add_parser("forget")
    forget.add_argument("token")
    auto = sub.add_parser("autostart")
    auto.add_argument("value", choices=("true", "false"))
    args = parser.parse_args(argv)
    try:
        controller = Controller()
        if args.command == "status":
            result = controller.status()
        elif args.command == "set":
            result = controller.configure({args.key: json.loads(args.value)})
        elif args.command == "forget":
            result = controller.forget(args.token)
        elif args.command == "open-probe":
            result = controller.open_probe()
        elif args.command == "autostart":
            result = controller.service("enable" if args.value == "true" else "disable")
        else:
            result = controller.service(args.command)
    except (OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.SubprocessError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
