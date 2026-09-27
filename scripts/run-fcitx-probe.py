#!/usr/bin/env python3
"""Run a dedicated Fcitx + toolkit client on a private D-Bus and XDG profile.

No addon is installed in the user's running Fcitx. The Wayland input-method
frontend is disabled: this probes toolkit modules, not text-input-v3 coverage.
"""

import argparse
import base64
import configparser
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parent.parent


def command(args, *, env=None):
    result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError(f"{args[0]}: {result.stdout.strip()} {result.stderr.strip()}")
    return result.stdout.strip()


def focus(target):
    return command(["hyprctl", "dispatch", f"hl.dsp.focus({{window={json.dumps(target)}}})"])


def wait_for(callback, timeout=6):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            result = callback()
            if result:
                return result
        except (OSError, ValueError, KeyError, RuntimeError, configparser.Error, subprocess.SubprocessError):
            pass
        time.sleep(.1)
    raise RuntimeError("Timeout durante la prova Fcitx.")


def status(path, client):
    if client == "qt":
        return json.loads(path.read_text())
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(path, encoding="utf-8")
    return {name: {"text": base64.b64decode(parser[name]["text_base64"]).decode("utf-8"), "cursor": parser.getint(name, "cursor"),
                   "focus": parser.getboolean(name, "focus")}
            for name in ("normal", "password", "code", "second")}


def exercise(app, status_path, client, env, mode, popup=False, core=None):
    clients = lambda: json.loads(command(["hyprctl", "-j", "clients"]))
    window = wait_for(lambda: next((item for item in clients() if item["pid"] == app.pid), None))
    target = "address:" + window["address"]
    focus(target)
    wait_for(lambda: status(status_path, client)["normal"]["focus"])
    command(["fcitx5-remote", "-s", f"autocorrect-probe-{mode}"], env=env)
    command(["fcitx5-remote", "-o"], env=env)
    time.sleep(.4)

    def key(name, modifiers=""):
        for state in ("down", "up"):
            expression = (f"hl.dsp.send_key_state({{window={json.dumps(target)}, "
                          f"mods={json.dumps(modifiers)}, key={json.dumps(name)}, state=\"{state}\"}})")
            command(["hyprctl", "dispatch", expression])
            time.sleep(.03)

    def text(value):
        for character in value:
            if character.isupper():
                key(character.lower(), "SHIFT")
            else:
                key({" ": "space", "è": "egrave", ".": "period", "\n": "Return"}.get(character, character))

    results = []

    def check(name, field, expected):
        try:
            observed = wait_for(lambda: (state if (state := status(status_path, client))[field]["text"] == expected else None), 2)
            results.append({"test": name, "passed": True, "text": observed[field]["text"]})
        except RuntimeError:
            results.append({"test": name, "passed": False, "expected": expected,
                            "state": status(status_path, client)})

    def clear():
        key("a", "CTRL")
        key("BackSpace")

    text("quesot")
    popup_capture = None
    if popup:
        time.sleep(.4)
        window = next(item for item in clients() if item["pid"] == app.pid)
        x, y = window["at"]
        width, height = window["size"]
        popup_capture = str(status_path.parent / "popup.png")
        command(["grim", "-g", f"{x},{y} {width}x{height}", popup_capture])
    key("space")
    check("correction_on_space", "normal", "questo ")
    key("BackSpace")
    key("space")
    check("undo_then_space_does_not_reapply", "normal", "quesot ")

    clear()
    text("è quesot ")
    check("unicode_prefix_offsets", "normal", "è questo ")
    key("BackSpace")
    key("space")
    check("undo_with_unicode_prefix", "normal", "è quesot ")

    clear()
    text("quesot ")
    key("Left")
    key("BackSpace")
    check("cursor_move_invalidates_undo", "normal", "quest ")

    clear()
    text("qaundo ")
    text("x")
    key("BackSpace")
    check("typing_invalidates_undo", "normal", "quando ")

    key("Tab")
    wait_for(lambda: status(status_path, client)["password"]["focus"])
    text("quesot ")
    check("password_preserved", "password", "quesot ")
    key("Tab")
    wait_for(lambda: status(status_path, client)["code"]["focus"])
    text("quesot ")
    check("no_spellcheck_preserved", "code", "quesot ")
    key("Tab")
    wait_for(lambda: status(status_path, client)["second"]["focus"])
    text("quesot")
    key("Tab", "SHIFT")
    check("focus_out_commits_original", "second", "quesot")
    if core is not None and client == "qt":
        key("Tab")
        key("Tab")
        wait_for(lambda: status(status_path, client)["paragraph"]["focus"])
        text("oggi provo quesot sistema qaundo scrivo un progeto interesasnte. \nLa seconda riga resta normale. ")
        expected = "oggi provo questo sistema quando scrivo un progetto interessante. \nLa seconda riga resta normale. "
        check("real_engine_multiline_paragraph", "paragraph", expected)
        text("quesot ")
        check("real_engine_last_word", "paragraph", expected + "questo ")
        key("BackSpace")
        key("space")
        check("real_engine_multiline_undo", "paragraph", expected + "quesot ")
        clear()
        text("proggeto ")
        check("real_engine_abstains_on_two_edits", "paragraph", "proggeto ")
        diagnostic = wait_for(lambda: (value if "edit_distance" in (value := status(status_path, client)["decision"]["text"])
                                      and "proggeto" in value else None))
        results.append({"test": "diagnostics_explain_abstention", "passed": True, "text": diagnostic})
        clear()
        text("domnai ")
        check("default_margin_abstains", "paragraph", "domnai ")
        key("m", "ALT")
        wait_for(lambda: status(status_path, client)["margin"]["focus"])
        for _ in range(3):
            key("Down")
        key("Return")
        wait_for(lambda: status(status_path, client)["margin"]["value"] == 1.0)
        key("t", "ALT")
        wait_for(lambda: status(status_path, client)["paragraph"]["focus"])
        clear()
        text("domnai ")
        check("live_lower_margin_corrects", "paragraph", "domani ")
        diagnostic = wait_for(lambda: (value if "richiesto: 1.000" in (value := status(status_path, client)["decision"]["text"])
                                      and "high_margin" in value else None))
        results.append({"test": "diagnostics_confirm_live_margin", "passed": True, "text": diagnostic})
        key("BackSpace")
        key("space")
        check("live_margin_undo_then_space", "paragraph", "domnai ")
        key("m", "ALT")
        wait_for(lambda: status(status_path, client)["margin"]["focus"])
        for _ in range(3):
            key("Up")
        key("Return")
        key("t", "ALT")
        wait_for(lambda: status(status_path, client)["paragraph"]["focus"])
        clear()
        text("domnai ")
        check("restored_margin_abstains", "paragraph", "domnai ")
        clear()
        text("proggeto ")
        core.send_signal(signal.SIGSTOP)
        try:
            text("quesot ")
            check("stalled_engine_preserves_input", "paragraph", "proggeto quesot ")
        finally:
            core.send_signal(signal.SIGCONT)
        text("qaundo ")
        check("engine_recovers_without_stale_reply", "paragraph", "proggeto quesot quando ")
        core.terminate()
        core.wait(timeout=3)
        text("quesot ")
        check("unavailable_engine_preserves_input", "paragraph", "proggeto quesot quando quesot ")
    return {"client": client, "mode": mode, "xwayland": window.get("xwayland"),
            "input_method": command(["fcitx5-remote", "-n"], env=env), "tests": results,
            "all_passed": all(item["passed"] for item in results), "popup_capture": popup_capture}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preedit", "surrounding"), default="preedit")
    parser.add_argument("--client", choices=("qt", "gtk"), default="qt")
    parser.add_argument("--popup", action="store_true", help="Mostra candidati dimostrativi non selezionabili")
    parser.add_argument("--test", action="store_true", help="Invia tasti solo alla finestra di prova tramite Hyprland")
    parser.add_argument("--engine", choices=("fixed", "core"), default="fixed",
                        help="fixed: tre sostituzioni; core: SymSpell + Hunspell persistenti")
    args = parser.parse_args()
    if args.engine == "core" and (args.mode != "surrounding" or args.popup):
        parser.error("Il motore reale si prova con --mode surrounding, senza --popup.")
    binary = ROOT / "build/fcitx-probe" / f"autocorrect-probe-{args.client}"
    library = ROOT / "build/fcitx-probe/libautocorrectprobe.so"
    if not binary.exists() or not library.exists():
        parser.error("Prima eseguire bash scripts/build-fcitx-probe.sh")
    sessions = ROOT / "build/fcitx-probe-sessions"
    sessions.mkdir(exist_ok=True)
    session = Path(tempfile.mkdtemp(prefix=f"{args.client}-{args.mode}-", dir=sessions))
    env = dict(os.environ)
    original_runtime = env.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    wayland = env.get("WAYLAND_DISPLAY", "wayland-0")
    env["WAYLAND_DISPLAY"] = wayland if wayland.startswith("/") else str(Path(original_runtime) / wayland)
    for variable, directory in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                                ("XDG_CACHE_HOME", "cache"), ("XDG_RUNTIME_DIR", "runtime")):
        path = session / directory
        path.mkdir(mode=0o700)
        env[variable] = str(path)
    for key in ("DBUS_SESSION_BUS_PID", "DBUS_STARTER_ADDRESS", "DBUS_STARTER_BUS_TYPE", "FCITX_DBUS_ADDRESS"):
        env.pop(key, None)
    data = session / "data/fcitx5"
    (data / "addon").mkdir(parents=True)
    (data / "inputmethod").mkdir()
    (data / "addon/autocorrectprobe.conf").write_text(
        f"[Addon]\nName=Autocorrect Probe\nType=SharedLibrary\nLibrary={str(library)[:-3]}\n"
        "Category=InputMethod\nOnDemand=True\n\n[Addon/Dependencies]\n0=core\n")
    for mode in ("preedit", "surrounding"):
        (data / f"inputmethod/autocorrect-probe-{mode}.conf").write_text(
            f"[InputMethod]\nName=Autocorrect Probe {mode}\nLangCode=it\nAddon=autocorrectprobe\nConfigurable=False\n")
    config = session / "config/fcitx5"
    config.mkdir()
    config.joinpath("profile").write_text(
        f"[Groups/0]\nName=Probe\nDefault Layout=us\nDefaultIM=autocorrect-probe-{args.mode}\n"
        "\n[Groups/0/Items/0]\nName=keyboard-us\n"
        f"\n[Groups/0/Items/1]\nName=autocorrect-probe-{args.mode}\n\n[GroupOrder]\n0=Probe\n")
    config.joinpath("config").write_text(
        "[Behavior]\nActiveByDefault=True\nShareInputState=All\n"
        "ShowInputMethodInformation=False\nShowFirstInputMethodInformation=False\n"
        "\n[Hotkey/AltTriggerKeys]\n")
    if args.popup:
        env["AUTOCORRECT_PROBE_POPUP"] = "1"
    else:
        env.pop("AUTOCORRECT_PROBE_POPUP", None)
    status_path = session / ("status.json" if args.client == "qt" else "status.ini")
    env.update({"QT_IM_MODULE": "fcitx", "GTK_IM_MODULE": "fcitx", "QT_QPA_PLATFORM": "wayland",
                "GDK_BACKEND": "wayland", "AUTOCORRECT_PROBE_STATUS": str(status_path)})
    env.pop("AUTOCORRECT_PROBE_ENGINE_SOCKET", None)
    if args.test:
        env["AUTOCORRECT_PROBE_TEST"] = "1"
    previous_focus = json.loads(command(["hyprctl", "-j", "activewindow"])).get("address") if args.test else None
    children = []
    print(f"Sessione isolata: {session}", flush=True)
    try:
        core = None
        if args.engine == "core":
            socket_path = session / "runtime/e.sock"
            ready = session / "core-ready.json"
            diagnostics = session / "decision.json"
            settings = session / "settings.json"
            settings.write_text(json.dumps({"min_score_margin": 1.3}))
            settings.chmod(0o600)
            with (session / "core.log").open("w") as log:
                core = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-B", "-m", "autocorrect_core.probe_server",
                    "--socket", str(socket_path), "--ready", str(ready), "--diagnostics", str(diagnostics),
                    "--settings", str(settings), "--hunspell"],
                    cwd=ROOT, stdout=log, stderr=log)
            children.append(core)
            wait_for(lambda: ready.exists() and json.loads(ready.read_text()), timeout=25)
            env["AUTOCORRECT_PROBE_ENGINE_SOCKET"] = str(socket_path)
            env["AUTOCORRECT_PROBE_DIAGNOSTICS"] = str(diagnostics)
            env["AUTOCORRECT_PROBE_SETTINGS"] = str(settings)
            print("Motore reale caricato: SymSpell + Hunspell.", flush=True)
        bus = subprocess.Popen(["dbus-daemon", "--session", "--nofork", "--print-address=1"],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        children.append(bus)
        env["DBUS_SESSION_BUS_ADDRESS"] = bus.stdout.readline().strip()
        if not env["DBUS_SESSION_BUS_ADDRESS"].startswith("unix:"):
            raise RuntimeError("Avvio del bus isolato fallito.")
        with (session / "fcitx.log").open("w") as log:
            daemon = subprocess.Popen(["fcitx5", "-D", "-k", "--disable=all",
                "--enable=dbus,dbusfrontend,keyboard,autocorrectprobe,classicui,wayland", "-u", "classicui"],
                env=env, stdout=log, stderr=log)
        children.append(daemon)
        wait_for(lambda: command(["fcitx5-remote", "--check"], env=env) in ("1", "2"))
        with (session / "client.log").open("w") as log:
            app = subprocess.Popen([str(binary)], env=env, stdout=log, stderr=log)
        children.append(app)
        if args.test:
            report = exercise(app, status_path, args.client, env, args.mode, args.popup, core)
            report["popup_requested"] = args.popup
            report["engine"] = args.engine
            (session / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0 if report["all_passed"] else 1
        print("Chiudi la finestra di prova per terminare questa istanza Fcitx.", flush=True)
        return app.wait()
    finally:
        for process in reversed(children):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        if previous_focus:
            subprocess.run(["hyprctl", "dispatch", f"hl.dsp.focus({{window=\"address:{previous_focus}\"}})"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(f"Prova fallita: {error}")
