"""Persistent local engine for the isolated Fcitx probe, one token per packet."""

import argparse
from contextlib import ExitStack
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import re
import signal
import socket
import sqlite3
import time

from .cli import add_engine_arguments, load_engine
from .engine import CONTEXTS


PACKET_LIMIT = 4096
TRAILING_PUNCTUATION = re.compile(r"([^\W\d_]+)([,.!?;:]+)", re.UNICODE)


def decide(engine, request: bytes, contextual=None, learner=None) -> dict:
    payload = json.loads(request)
    if not isinstance(payload, dict) or not isinstance(payload.get("token"), str):
        raise ValueError("Atteso un token testuale.")
    token = payload["token"]
    if len(token) > 128 or "\0" in token:
        raise ValueError("Token non valido o troppo lungo.")
    previous = payload.get("previous", "")
    if not isinstance(previous, str) or len(previous) > 1024 or "\0" in previous:
        raise ValueError("Testo precedente non valido o troppo lungo.")
    field_context = payload.get("context", "text")
    if field_context not in CONTEXTS:
        raise ValueError("Contesto del campo non valido.")
    # Strip only trailing punctuation from an otherwise plain alphabetic token.
    # URLs, paths, numbers, apostrophes and mixed punctuation remain whole.
    match = TRAILING_PUNCTUATION.fullmatch(token)
    word, suffix = (match[1], match[2]) if match else (token, "")
    context_info = {"enabled": False, "used": False}
    if contextual is None:
        decision = engine.evaluate(word, context=field_context)
    else:
        decision, context_info = contextual.evaluate(word, previous, context=field_context)
    personal_info = {"enabled": False, "used": False}
    if learner is not None:
        decision, personal_info = learner.apply(word, previous, decision, context=field_context)
    required_margin = context_info["required_margin"] if context_info["used"] else engine.policy.min_score_margin
    if personal_info["used"]:
        required_margin = None  # Explicit feedback is not a calibrated language-model margin.
    return {"original": token, "output": decision.output + suffix,
            "action": decision.action, "reason": decision.reason,
            "candidates": [asdict(candidate) for candidate in decision.candidates[:3]],
            "score_margin": decision.score_margin,
            "required_margin": required_margin,
            "baseline_required_margin": engine.policy.min_score_margin,
            "required_frequency": engine.policy.min_frequency, "context": context_info, "personal": personal_info,
            "blocked_context": field_context != "text",
            "suggestions_enabled": bool(learner and learner.suggestions_enabled and field_context == "text"),
            "candidate_outputs": [c.term + suffix for c in decision.candidates[:3]] if decision.action == "keep" else []}


def handle_request(engine, request, contextual=None, learner=None):
    payload = json.loads(request)
    if not isinstance(payload, dict):
        raise ValueError("Richiesta non valida.")
    operation = payload.get("op", "decide")
    if operation == "decide":
        return decide(engine, request, contextual, learner)
    if learner is None:
        return {"feedback": {"status": "learning_unavailable"}}
    if operation == "feedback":
        return {"feedback": learner.feedback(payload)}
    if payload.get("context", "text") != "text":
        return {"feedback": {"status": "ignored_context"}}
    if operation == "status":
        token = payload.get("token")
        if token is not None and (not isinstance(token, str) or len(token) > 128):
            raise ValueError("Input di stato non valido.")
        return {"memory": learner.memory.status(token)}
    if operation == "forget":
        from .feedback import feedback_word
        original = feedback_word(payload.get("token"))
        if not original:
            raise ValueError("Indicare il typo da dimenticare.")
        count = learner.memory.forget(original)
        return {"feedback": {"status": "forgotten", "original": original,
                             "forgotten_events": count, **learner.memory.status()}}
    raise ValueError("Operazione non riconosciuta.")


def refresh_policy(engine, settings: Path | None, contextual=None, learner=None) -> bool:
    """Apply a session-local override; malformed writes retain the last policy."""
    if settings is None:
        return False
    try:
        with settings.open("rb") as source:
            raw = source.read(1025)
        if len(raw) > 1024:
            return False
        payload = json.loads(raw)
        if (not isinstance(payload, dict) or not payload
                or not set(payload) <= {"min_score_margin", "min_frequency", "use_context", "learn_enabled", "suggestions_enabled"}):
            return False
        overrides = {}
        if "min_score_margin" in payload:
            value = payload["min_score_margin"]
            if type(value) not in (int, float) or not 0.01 <= value <= 5.0:
                return False
            overrides["min_score_margin"] = float(value)
        if "min_frequency" in payload:
            value = payload["min_frequency"]
            if type(value) is not int or not 1000 <= value <= 100000:
                return False
            overrides["min_frequency"] = value
        if "use_context" in payload:
            if type(payload["use_context"]) is not bool or (payload["use_context"] and contextual is None):
                return False
        for name in ("learn_enabled", "suggestions_enabled"):
            if name in payload and (type(payload[name]) is not bool or (payload[name] and learner is None)):
                return False
        # Validate the entire snapshot before applying either setting.
        engine.policy = replace(engine.policy, **overrides)
        if contextual is not None and "use_context" in payload:
            contextual.enabled = payload["use_context"]
        if learner is not None:
            if "learn_enabled" in payload:
                learner.enabled = payload["learn_enabled"]
            if "suggestions_enabled" in payload:
                learner.suggestions_enabled = payload["suggestions_enabled"]
        return True
    except (OSError, ValueError):
        return False


def serve(engine, path: Path, ready: Path, diagnostics: Path | None = None,
          settings: Path | None = None, contextual=None, learner=None, feedback_diagnostics: Path | None = None):
    if len(os.fsencode(path)) >= 108:
        raise ValueError("Percorso del socket troppo lungo.")
    # Refuse to overwrite a socket from another running session.
    if path.exists() or path.is_symlink():
        raise ValueError("Il socket esiste già.")
    running = True

    def stop(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as server:
        server.bind(str(path))
        path.chmod(0o600)
        try:
            server.listen(4)
            server.settimeout(.2)
            refresh_policy(engine, settings, contextual, learner)
            ready.write_text(json.dumps({"dictionary_sha256": engine.dictionary_sha256,
                                        "policy": asdict(engine.policy),
                                        "context_model": contextual.model.metadata if contextual else None,
                                        "feedback_memory": str(learner.memory.path) if learner else None,
                                        "word_validator": engine.word_validator.metadata if engine.word_validator else None}),
                             encoding="utf-8")
            ready.chmod(0o600)
            while running:
                try:
                    client, _ = server.accept()
                except socket.timeout:
                    continue
                with client:
                    client.settimeout(.1)
                    try:
                        packet, _, flags, _ = client.recvmsg(PACKET_LIMIT)
                        if flags & socket.MSG_TRUNC:
                            raise ValueError("Pacchetto troppo grande.")
                        refresh_policy(engine, settings, contextual, learner)
                        response = handle_request(engine, packet, contextual, learner)
                    except (ValueError, OSError, sqlite3.Error):
                        response = {"action": "keep", "reason": "invalid_request", "feedback": {"status": "error"}}
                    try:
                        client.send(json.dumps(response, ensure_ascii=False).encode("utf-8"))
                    except OSError:
                        pass  # Client already declined a late response.
                    destination = feedback_diagnostics if "feedback" in response else diagnostics
                    if destination is not None and not response.get("blocked_context") and ("original" in response or "feedback" in response):
                        # This is an engine decision, not an application acknowledgement.
                        # Publish after replying, keeping disk I/O out of the response budget.
                        snapshot = {**response, "time_ns": time.time_ns(), "source": "feedback" if "feedback" in response else "engine_decision"}
                        temporary = destination.with_suffix(".tmp")
                        try:
                            temporary.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
                            temporary.chmod(0o600)
                            temporary.replace(destination)
                        except OSError:
                            pass  # Diagnostics must not disable typing.
        finally:
            path.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path, help="Ultima analisi locale per la finestra di prova")
    parser.add_argument("--settings", type=Path, help="Margine e frequenza modificabili nella sola sessione di prova")
    parser.add_argument("--context-corpus", type=Path, help="Cartella Leipzig verificata per il ranking contestuale sperimentale")
    parser.add_argument("--feedback-memory", type=Path, help="Memoria persistente dei soli gesti espliciti")
    parser.add_argument("--feedback-diagnostics", type=Path)
    add_engine_arguments(parser)
    args = parser.parse_args(argv)
    try:
        engine = load_engine(args)
        with ExitStack() as stack:
            contextual = None
            learner = None
            if args.context_corpus is not None:
                from .contextual import ContextualCorrector, TrainingNgrams
                model = stack.enter_context(TrainingNgrams.from_leipzig(args.context_corpus))
                contextual = ContextualCorrector(engine, model)
            if args.feedback_memory is not None:
                from .feedback import FeedbackLearner, FeedbackMemory
                memory = stack.enter_context(FeedbackMemory(args.feedback_memory))
                learner = FeedbackLearner(engine, memory)
            serve(engine, args.socket, args.ready, args.diagnostics, args.settings, contextual, learner, args.feedback_diagnostics)
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        parser.exit(2, f"Errore: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
