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
import socket
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


def exercise(app, status_path, client, env, mode, popup=False, core=None, contextual=False, segmentation=False):
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
                key({" ": "space", "è": "egrave", ".": "period", ",": "comma", "'": "apostrophe",
                     "\n": "Return"}.get(character, character))

    results = []
    # Leipzig-only evidence (no generated corpus): these outcomes stay fixed.
    segmentation_cases = (
        ("segmentation_splits_joined_words", "nonlo ", "non lo "),
        ("segmentation_restores_apostrophe", "allinizio ", "all'inizio "),
        ("segmentation_short_elision_with_accent", "cè ", "c'è "),
        ("segmentation_keeps_trailing_punctuation", "vabene, ", "va bene, "),
        ("segmentation_ambiguous_reading_preserved", "lagente ", "lagente "),
        ("segmentation_preserves_capitalization", "Lacqua ", "Lacqua "),
        ("segmentation_accent_confusion_preserved", "nè ", "nè "),
        ("segmentation_known_word_preserved", "apposto ", "apposto "),
    )

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
    if core is not None and client == "gtk" and contextual:
        # GTK has no settings controls; the test changes its isolated snapshot.
        settings = Path(env["AUTOCORRECT_PROBE_SETTINGS"])
        temporary = settings.with_suffix(".tmp")
        temporary.write_text(json.dumps({"min_score_margin": 1.3, "min_frequency": 5000, "use_context": True}))
        temporary.chmod(0o600)
        temporary.replace(settings)
        key("Tab", "SHIFT")
        key("Tab", "SHIFT")
        wait_for(lambda: status(status_path, client)["normal"]["focus"])
        clear()
        text("una piza ")
        check("gtk_context_recovers_pizza", "normal", "una pizza ")
        key("BackSpace")
        key("space")
        check("gtk_context_undo_then_space", "normal", "una piza ")
        clear()
        text("sono stao ")
        check("gtk_context_recovers_stato", "normal", "sono stato ")
        clear()
        text("ti devo dire una csa ")
        check("gtk_context_recovers_three_letter_csa", "normal", "ti devo dire una cosa ")
        clear()
        text("prosciutto nel pne ")
        check("gtk_article_backoff_recovers_pane", "normal", "prosciutto nel pane ")
        key("BackSpace")
        key("space")
        check("gtk_three_letter_undo", "normal", "prosciutto nel pne ")
        if segmentation:
            for name, value, expected in segmentation_cases[:3]:
                clear()
                text(value)
                check("gtk_" + name, "normal", expected)
            clear()
            text("nonlo ")
            key("BackSpace")
            key("space")
            check("gtk_segmentation_undo_then_space", "normal", "nonlo ")
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
        text("maglioner ")
        check("default_frequency_abstains", "paragraph", "maglioner ")
        diagnostic = wait_for(lambda: (value if "Frequenza minima usata: 100.000" in
                                       (value := status(status_path, client)["decision"]["text"])
                                       and "low_frequency" in value and "44.882" in value else None))
        results.append({"test": "diagnostics_explain_low_frequency", "passed": True, "text": diagnostic})
        key("5", "ALT")
        wait_for(lambda: status(status_path, client)["frequency"]["value"] == 5000)
        key("t", "ALT")
        wait_for(lambda: status(status_path, client)["paragraph"]["focus"])
        check("frequency_change_does_not_rewrite_existing_text", "paragraph", "maglioner ")
        clear()
        text("maglioner ")
        check("live_lower_frequency_corrects", "paragraph", "maglione ")
        diagnostic = wait_for(lambda: (value if "Frequenza minima usata: 5000" in
                                       (value := status(status_path, client)["decision"]["text"]).replace(".", "")
                                       and "richiesto: 1.300" in value and "high_margin" in value else None))
        results.append({"test": "diagnostics_confirm_frequency_and_fixed_margin", "passed": True, "text": diagnostic})
        key("BackSpace")
        key("space")
        check("live_frequency_undo_then_space", "paragraph", "maglioner ")
        clear()
        text("domnai ")
        check("lower_frequency_still_requires_margin", "paragraph", "domnai ")
        clear()
        text("proggeto ")
        check("lower_frequency_keeps_distance_guard", "paragraph", "proggeto ")
        clear()
        text("compilaste ")
        check("lower_frequency_keeps_hunspell_word", "paragraph", "compilaste ")
        # Changing the margin must not erase the frequency from the snapshot.
        key("m", "ALT")
        wait_for(lambda: status(status_path, client)["margin"]["focus"])
        key("Down")
        key("Return")
        key("Up")
        key("Return")
        key("t", "ALT")
        wait_for(lambda: status(status_path, client)["paragraph"]["focus"])
        clear()
        text("maglioner ")
        check("margin_edit_preserves_frequency", "paragraph", "maglione ")
        # Also exercise direct numeric entry and the field mnemonic.
        key("f", "ALT")
        wait_for(lambda: status(status_path, client)["frequency"]["focus"])
        key("a", "CTRL")
        text("20000")
        key("Return")
        wait_for(lambda: status(status_path, client)["frequency"]["value"] == 20000)
        key("t", "ALT")
        wait_for(lambda: status(status_path, client)["paragraph"]["focus"])
        clear()
        text("maglioner ")
        check("typed_frequency_corrects", "paragraph", "maglione ")
        diagnostic = wait_for(lambda: (value if "Frequenza minima usata: 20.000" in
                                       (value := status(status_path, client)["decision"]["text"])
                                       and "richiesto: 1.300" in value else None))
        results.append({"test": "diagnostics_confirm_typed_frequency", "passed": True, "text": diagnostic})
        key("1", "ALT")
        wait_for(lambda: status(status_path, client)["frequency"]["value"] == 100000)
        key("t", "ALT")
        wait_for(lambda: status(status_path, client)["paragraph"]["focus"])
        clear()
        text("maglioner ")
        check("restored_frequency_abstains", "paragraph", "maglioner ")
        if contextual:
            key("5", "ALT")
            wait_for(lambda: status(status_path, client)["frequency"]["value"] == 5000)
            key("t", "ALT")
            wait_for(lambda: status(status_path, client)["paragraph"]["focus"])
            clear()
            text("ieri ho mangiato una piza ")
            check("context_recovers_pizza_beyond_top_three", "paragraph", "ieri ho mangiato una pizza ")
            diagnostic = wait_for(lambda: (value if "context_high_margin" in
                (value := status(status_path, client)["decision"]["text"])
                and "Contesto usato: mangiato una" in value and "posto 16" in value
                and "richiesto: 0.699" in value else None))
            results.append({"test": "diagnostics_confirm_contextual_ranking", "passed": True, "text": diagnostic})
            key("BackSpace")
            key("space")
            check("context_undo_then_space", "paragraph", "ieri ho mangiato una piza ")
            for name, value, expected in (
                ("context_recovers_stato", "sono stao ", "sono stato "),
                ("context_switches_same_typo_to_pisa", "comune di piza ", "comune di pisa "),
                ("context_preserves_known_word", "una pipa ", "una pipa "),
                ("context_without_previous_keeps_short_word", "piza ", "piza "),
                ("context_does_not_cross_newline", "sono\nstao ", "sono\nstao "),
                ("context_does_not_cross_sentence", "sono. stao ", "sono. stao "),
                ("context_long_word_still_needs_margin", "ho lavato il piato ", "ho lavato il piato "),
                ("context_unicode_prefix", "è. ho mangiato una piza ", "è. ho mangiato una pizza "),
            ):
                clear()
                text(value)
                check(name, "paragraph", expected)
            clear()
            text("ti devo dire una csa ")
            check("context_recovers_three_letter_csa", "paragraph", "ti devo dire una cosa ")
            diagnostic = wait_for(lambda: (value if "Evidenza: trigramma esatto" in
                (value := status(status_path, client)["decision"]["text"])
                and "Contesto usato: dire una" in value and "richiesto: 1.300" in value else None))
            results.append({"test": "diagnostics_confirm_three_letter_evidence", "passed": True, "text": diagnostic})
            clear()
            text("oggi ho mangiato del prosciutto nel pne ")
            check("article_backoff_recovers_pane", "paragraph", "oggi ho mangiato del prosciutto nel pane ")
            diagnostic = wait_for(lambda: (value if "Evidenza aggregata dagli articoli: il, del" in
                (value := status(status_path, client)["decision"]["text"])
                and "occorrenze aggregate: 11 / minime: 10" in value else None))
            results.append({"test": "diagnostics_disclose_article_backoff", "passed": True, "text": diagnostic})
            key("BackSpace")
            key("space")
            check("three_letter_undo_then_space", "paragraph", "oggi ho mangiato del prosciutto nel pne ")
            for name, value, expected in (
                ("three_letter_trailing_punctuation", "ti devo dire una csa. ", "ti devo dire una cosa. "),
                ("three_letter_without_context", "csa ", "csa "),
                ("three_letter_sentence_boundary", "dire una. csa ", "dire una. csa "),
                ("three_letter_preserves_tool", "con nvi ", "con nvi "),
                ("three_letter_preserves_capitalization", "ti devo dire una Csa ", "ti devo dire una Csa "),
                ("two_letter_input_still_preserved", "ti devo dire una cs ", "ti devo dire una cs "),
                ("real_word_error_still_preserved", "al sole fa callo ", "al sole fa callo "),
            ):
                clear()
                text(value)
                check(name, "paragraph", expected)
            if segmentation:
                for name, value, expected in segmentation_cases:
                    clear()
                    text(value)
                    check(name, "paragraph", expected)
                clear()
                text("ci vediamo allinizio ")
                key("BackSpace")
                key("space")
                check("segmentation_undo_then_space", "paragraph", "ci vediamo allinizio ")
                text("e nonlo ")
                check("segmentation_after_undo_continues", "paragraph", "ci vediamo allinizio e non lo ")
            key("c", "ALT")
            wait_for(lambda: not status(status_path, client)["context"]["enabled"])
            key("t", "ALT")
            wait_for(lambda: status(status_path, client)["paragraph"]["focus"])
            clear()
            text("una piza ")
            check("context_toggle_off_keeps_short_word", "paragraph", "una piza ")
            key("c", "ALT")
            wait_for(lambda: status(status_path, client)["context"]["enabled"])
            key("t", "ALT")
            wait_for(lambda: status(status_path, client)["paragraph"]["focus"])
            check("context_toggle_does_not_rewrite_text", "paragraph", "una piza ")
            clear()
            text("una piza ")
            check("context_toggle_on_recovers_correction", "paragraph", "una pizza ")
            key("1", "ALT")
            wait_for(lambda: status(status_path, client)["frequency"]["value"] == 100000)
            key("t", "ALT")
            wait_for(lambda: status(status_path, client)["paragraph"]["focus"])
            clear()
            text("una piza ")
            check("context_respects_live_frequency", "paragraph", "una piza ")
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


def exercise_learning(app, status_path, client, env, core, children):
    """Real gestures against a fresh session DB; never the user's persistent memory."""
    clients = lambda: json.loads(command(["hyprctl", "-j", "clients"]))
    window = wait_for(lambda: next((item for item in clients() if item["pid"] == app.pid), None))
    target = "address:" + window["address"]
    focus(target)
    wait_for(lambda: status(status_path, client)["normal"]["focus"])
    command(["fcitx5-remote", "-s", "autocorrect-probe-surrounding"], env=env)
    command(["fcitx5-remote", "-o"], env=env)
    time.sleep(.4)
    results = []
    field = "paragraph" if client == "qt" else "normal"

    def key(name, modifiers=""):
        for state in ("down", "up"):
            command(["hyprctl", "dispatch", f"hl.dsp.send_key_state({{window={json.dumps(target)}, "
                     f"mods={json.dumps(modifiers)}, key={json.dumps(name)}, state=\"{state}\"}})"])
            time.sleep(.03)

    def text(value):
        for char in value:
            key({" ": "space", ".": "period", "è": "egrave"}.get(char.lower(), char.lower()), "SHIFT" if char.isupper() else "")

    def clear():
        key("a", "CTRL")
        key("BackSpace")

    def request(payload):
        with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as connection:
            connection.settimeout(2)
            connection.connect(env["AUTOCORRECT_PROBE_ENGINE_SOCKET"])
            connection.send(json.dumps(payload).encode())
            return json.loads(connection.recv(8192))

    def memory(original=None):
        return request({"op": "status", **({"token": original} if original else {})})["memory"]

    def check(name, callback):
        try:
            value = wait_for(callback, timeout=3)
            results.append({"test": name, "passed": True, "observed": value})
        except RuntimeError:
            results.append({"test": name, "passed": False, "state": status(status_path, client), "memory": memory()})
            (status_path.parent / "learning-progress.json").write_text(json.dumps(results, ensure_ascii=False, indent=2))
            raise RuntimeError(f"Controllo apprendimento fallito: {name}")

    def check_text(name, expected, which=field):
        check(name, lambda: (value if (value := status(status_path, client)[which]["text"]) == expected else None))

    def focus_field(which):
        for _ in range(25):
            if status(status_path, client)[which]["focus"]:
                return
            key("Tab")
        raise RuntimeError(f"Campo non raggiungibile: {which}")

    def settings(**updates):
        path = Path(env["AUTOCORRECT_PROBE_SETTINGS"])
        values = json.loads(path.read_text())
        values.update(updates)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(values))
        temporary.chmod(0o600)
        temporary.replace(path)

    def restart():
        nonlocal core
        arguments = core.args
        core.terminate()
        core.wait(timeout=3)
        ready = status_path.parent / "core-ready.json"
        ready.unlink(missing_ok=True)
        with (status_path.parent / "core-restart.log").open("a") as log:
            core = subprocess.Popen(arguments, cwd=ROOT, stdout=log, stderr=log)
        children.append(core)
        wait_for(lambda: ready.exists() and json.loads(ready.read_text()), timeout=25)

    # Isolate learning from corpus rules: a first pne must be an abstention.
    if client == "qt":
        if status(status_path, client)["context"]["enabled"]:
            key("c", "ALT")
        if status(status_path, client)["learning"]["suggestions"]:
            key("s", "ALT")
        key("1", "ALT")
        key("t", "ALT")
        wait_for(lambda: status(status_path, client)[field]["focus"])
    else:
        settings(use_context=False, suggestions_enabled=False, min_frequency=100000)

    text("con il pne ")
    check_text("unlearned_typo_abstains", "con il pne ")
    for _ in range(4):
        key("BackSpace")
    text("pane ")
    check_text("manual_backspace_retype", "con il pane ")
    check("manual_edit_learns_one_pair", lambda: memory("pne").get("pairs", {}).get("pane", {}).get("confirmations") == 1)
    clear()
    text("vorrei pne ")
    check_text("learned_pair_transfers_to_new_phrase", "vorrei pane ")
    check("automatic_use_does_not_reinforce", lambda: memory("pne")["pairs"]["pane"]["confirmations"] == 1)
    if client == "qt":
        key("l", "ALT")
        wait_for(lambda: not status(status_path, client)["learning"]["enabled"])
        key("t", "ALT")
    else:
        settings(learn_enabled=False)
    clear()
    text("vorrei pne ")
    check_text("paused_memory_does_not_apply", "vorrei pne ")
    for _ in range(4):
        key("BackSpace")
    text("pane ")
    check_text("manual_edit_while_paused", "vorrei pane ")
    check("paused_memory_does_not_learn", lambda: memory("pne")["pairs"]["pane"]["confirmations"] == 1)
    if client == "qt":
        key("l", "ALT")
        wait_for(lambda: status(status_path, client)["learning"]["enabled"])
        key("t", "ALT")
    else:
        settings(learn_enabled=True)
    clear()
    text("vorrei pne ")
    check_text("resumed_memory_applies", "vorrei pane ")
    restart()
    clear()
    text("compro pne ")
    check_text("learned_pair_survives_server_restart", "compro pane ")

    # Annul the automatic application. This must create negative, not positive, feedback.
    key("BackSpace")
    key("space")
    check_text("undo_personal_correction", "compro pne ")
    check("undo_records_rejection", lambda: memory("pne")["pairs"]["pane"]["rejections"] == 1)
    clear()
    text("ancora pne ")
    check_text("rejected_pair_stops_autocorrecting", "ancora pne ")

    # A valid -> valid edit learns usage, never a replacement rule.
    clear()
    text("cane ")
    before = memory()["confirmations"]
    for _ in range(5):
        key("BackSpace")
    text("pane ")
    check_text("valid_word_manually_changed", "pane ")
    check("valid_change_learns_only_usage", lambda: memory()["confirmations"] == before + 1 and memory("cane")["pairs"] == {})
    clear()
    text("cane ")
    check_text("valid_original_is_not_replaced", "cane ")
    check("clearing_field_is_not_a_correction", lambda: memory()["confirmations"] == before + 1)

    # Optional suggestions: absent by default; selecting is itself the confirmation.
    clear()
    text("maglioner ")
    check_text("optional_candidates_initial_abstention", "maglioner ")
    key("F1")
    check_text("candidate_shortcut_inactive_when_disabled", "maglioner ")
    if client == "qt":
        key("s", "ALT")
        wait_for(lambda: status(status_path, client)["learning"]["suggestions"])
        key("t", "ALT")
    else:
        settings(suggestions_enabled=True)
    clear()
    text("maglioner ")
    key("F1")
    check_text("candidate_selection_applies", "maglione ")
    check("candidate_selection_learns", lambda: memory("maglioner")["pairs"].get("maglione", {}).get("confirmations") == 1)
    key("BackSpace")
    key("space")
    check_text("candidate_selection_can_be_undone", "maglioner ")
    check("selection_undo_reverses_confirmation", lambda: memory("maglioner")["pairs"]["maglione"]["confirmations"] == 0
          and memory("maglioner")["pairs"]["maglione"]["rejections"] == 1)
    request({"op": "forget", "token": "maglioner"})
    clear()
    text("maglioner ")
    key("F1")
    check_text("selection_after_forget", "maglione ")
    check("selection_confirmation_once", lambda: memory("maglioner")["pairs"]["maglione"]["confirmations"] == 1)

    # An interior insertion followed by a word-boundary key is also an explicit edit.
    request({"op": "forget", "token": "pne"})
    clear()
    text("con il pne ")
    for _ in range(3):
        key("Left")
    key("a")
    key("End")
    key("space")
    check("interior_edit_learns", lambda: memory("pne")["pairs"].get("pane", {}).get("confirmations") == 1)

    # Both learned application and manual learning must be absent in excluded fields.
    for which in ("password", "code"):
        before = memory()
        focus_field(which)
        clear()
        text("pne ")
        key("F1")
        check_text(f"learned_pair_excluded_{which}", "pne ", which)
        for _ in range(4):
            key("BackSpace")
        text("pane ")
        check_text(f"manual_edit_in_{which}", "pane ", which)
        check(f"no_learning_in_{which}", lambda: memory() == before)
    focus_field(field)

    # Forget through the real Qt control (or the same service API on GTK).
    if client == "qt":
        key("d", "ALT")
        wait_for(lambda: status(status_path, client)["learning"]["forget_focus"])
        text("pne")
        key("Return")
        key("t", "ALT")
    else:
        request({"op": "forget", "token": "pne"})
    check("forget_removes_pair", lambda: memory("pne")["pairs"] == {})
    restart()
    clear()
    text("con il pne ")
    check_text("forget_survives_restart", "con il pne ")
    check("forget_does_not_remove_other_pairs", lambda: memory("maglioner")["pairs"]["maglione"]["confirmations"] == 1)
    return {"client": client, "mode": "surrounding", "xwayland": window.get("xwayland"),
            "tests": results, "all_passed": all(item["passed"] for item in results),
            "memory": memory(), "memory_isolated": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("preedit", "surrounding"), default="preedit")
    parser.add_argument("--client", choices=("qt", "gtk"), default="qt")
    parser.add_argument("--popup", action="store_true", help="Mostra candidati dimostrativi non selezionabili")
    parser.add_argument("--test", action="store_true", help="Invia tasti solo alla finestra di prova tramite Hyprland")
    parser.add_argument("--engine", choices=("fixed", "core"), default="fixed",
                        help="fixed: tre sostituzioni; core: SymSpell + Hunspell persistenti")
    parser.add_argument("--context", action="store_true", help="Abilita il contesto Leipzig sperimentale nel core")
    parser.add_argument("--frequency", type=int, default=100000, help="Frequenza iniziale della sessione core, da 1000 a 100000")
    parser.add_argument("--segmentation", action="store_true",
                        help="Stacca parole attaccate e rimette l'apostrofo; richiede --context")
    parser.add_argument("--colloquial", action="store_true",
                        help="Aggiunge il corpus colloquiale preparato alla separazione (non con --test)")
    parser.add_argument("--learn", action="store_true", help="Apprende gesti espliciti nella memoria personale persistente")
    parser.add_argument("--memory", type=Path, help="Memoria feedback alternativa; --test usa una memoria nuova nella sessione")
    parser.add_argument("--candidates", action="store_true", help="Suggerimenti selezionabili opzionali, solo nelle astensioni; richiede --learn")
    parser.add_argument("--shared-engine", action="store_true", help="Usa il motore utente gestito dal pannello Omarchy")
    args = parser.parse_args()
    if not 1000 <= args.frequency <= 100000 or (args.engine != "core" and (args.context or args.frequency != 100000)):
        parser.error("Contesto e frequenza richiedono --engine core; frequenza ammessa: 1000..100000.")
    if args.engine == "core" and (args.mode != "surrounding" or args.popup):
        parser.error("Il motore reale si prova con --mode surrounding, senza --popup.")
    if (args.learn and args.engine != "core") or ((args.memory or args.candidates) and not args.learn):
        parser.error("L'apprendimento richiede --engine core; memoria e candidati richiedono --learn.")
    if (args.segmentation and not args.context) or (args.colloquial and (not args.segmentation or args.test)):
        parser.error("--segmentation richiede --context; --colloquial richiede --segmentation e non vale con --test.")
    if args.test and args.memory:
        parser.error("Il test usa una memoria isolata e non accetta --memory.")
    if args.shared_engine and (args.engine != "core" or args.test or args.memory or args.learn or args.context
                               or args.segmentation or args.candidates or args.frequency != 100000):
        parser.error("--shared-engine richiede --engine core e usa le impostazioni del pannello; non accetta test o override locali.")
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
    env.pop("AUTOCORRECT_PROBE_CONTEXT_CORPUS", None)
    env.pop("AUTOCORRECT_PROBE_LEARNING", None)
    env.pop("AUTOCORRECT_PROBE_CANDIDATES", None)
    env.pop("AUTOCORRECT_PROBE_SHARED_ENGINE", None)
    env["AUTOCORRECT_PROBE_INITIAL_FREQUENCY"] = str(args.frequency)
    if args.test:
        env["AUTOCORRECT_PROBE_TEST"] = "1"
    previous_focus = json.loads(command(["hyprctl", "-j", "activewindow"])).get("address") if args.test else None
    children = []
    print(f"Sessione isolata: {session}", flush=True)
    try:
        core = None
        if args.shared_engine:
            runtime = Path(original_runtime) / "autocorrect"
            with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as connection:
                connection.settimeout(2)
                connection.connect(str(runtime / "engine.sock"))
                connection.send(b'{"op":"status"}')
                shared = json.loads(connection.recv(16384))
            if shared.get("state", {}).get("protocol_version") != 1:
                raise RuntimeError("Il motore condiviso non supporta il pannello. Riavvia autocorrect.service.")
            config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
            env["AUTOCORRECT_PROBE_ENGINE_SOCKET"] = str(runtime / "engine.sock")
            env["AUTOCORRECT_PROBE_DIAGNOSTICS"] = str(runtime / "decision.json")
            env["AUTOCORRECT_PROBE_SETTINGS"] = str(config_home / "autocorrect/settings.json")
            env["AUTOCORRECT_PROBE_SHARED_ENGINE"] = "1"
            env["AUTOCORRECT_PROBE_INITIAL_FREQUENCY"] = str(shared["state"]["settings"]["min_frequency"])
            if shared["state"]["capabilities"]["context"]:
                env["AUTOCORRECT_PROBE_CONTEXT_CORPUS"] = "shared"
            if shared["state"]["capabilities"]["learning"]:
                env["AUTOCORRECT_PROBE_LEARNING"] = "1"
                env["AUTOCORRECT_PROBE_FEEDBACK"] = str(runtime / "feedback.json")
            print("Collegato al motore del pannello Omarchy.", flush=True)
        elif args.engine == "core":
            socket_path = session / "runtime/e.sock"
            ready = session / "core-ready.json"
            diagnostics = session / "decision.json"
            settings = session / "settings.json"
            settings.write_text(json.dumps({"min_score_margin": 1.3, "min_frequency": args.frequency,
                                           "use_context": args.context, "learn_enabled": args.learn,
                                           "suggestions_enabled": args.candidates}))
            settings.chmod(0o600)
            context_args = []
            if args.context:
                corpus = ROOT / "benchmark-data/leipzig-ita-news-2023-100k"
                context_args = ["--context-corpus", str(corpus)]
                env["AUTOCORRECT_PROBE_CONTEXT_CORPUS"] = str(corpus)
                if args.segmentation:
                    context_args.append("--segmentation")
                if args.colloquial:
                    context_args += ["--colloquial-corpus", str(ROOT / "benchmark-data/colloquial-it-llm/prepared")]
            learning_args = []
            if args.learn:
                memory = session / "feedback.sqlite3" if args.test else (args.memory or
                    Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "autocorrect/feedback.sqlite3")
                feedback = session / "feedback.json"
                learning_args = ["--feedback-memory", str(memory.resolve()), "--feedback-diagnostics", str(feedback)]
                env["AUTOCORRECT_PROBE_LEARNING"] = "1"
                env["AUTOCORRECT_PROBE_FEEDBACK"] = str(feedback)
                if args.candidates:
                    env["AUTOCORRECT_PROBE_CANDIDATES"] = "1"
            with (session / "core.log").open("w") as log:
                core = subprocess.Popen([str(ROOT / ".venv/bin/python"), "-B", "-m", "autocorrect_core.probe_server",
                    "--socket", str(socket_path), "--ready", str(ready), "--diagnostics", str(diagnostics),
                    "--settings", str(settings), "--hunspell", *context_args, *learning_args],
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
            report = (exercise_learning(app, status_path, args.client, env, core, children) if args.learn else
                      exercise(app, status_path, args.client, env, args.mode, args.popup, core, args.context,
                               args.segmentation))
            report["popup_requested"] = args.popup
            report["engine"] = args.engine
            report["context_requested"] = args.context
            report["segmentation_requested"] = args.segmentation
            report["learning_requested"] = args.learn
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
