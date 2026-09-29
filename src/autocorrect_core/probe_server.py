"""Persistent local engine for the isolated Fcitx probe, one token per packet."""

import argparse
from contextlib import ExitStack
from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
import re
import signal
import socket
import sqlite3
import time

from .cli import add_engine_arguments, load_engine
from .engine import CONTEXTS, Decision
from .settings import read_patch, validate_patch, write_settings


PACKET_LIMIT = 4096
TRAILING_PUNCTUATION = re.compile(r"([^\W\d_]+)([,.!?;:]+)", re.UNICODE)


@dataclass
class RuntimeControls:
    correction_enabled: bool = True


def settings_snapshot(engine, contextual=None, learner=None, runtime=None):
    return {"correction_enabled": runtime.correction_enabled if runtime else True,
            "min_score_margin": engine.policy.min_score_margin, "min_frequency": engine.policy.min_frequency,
            "use_context": bool(contextual and contextual.enabled), "learn_enabled": bool(learner and learner.enabled),
            "suggestions_enabled": bool(learner and learner.suggestions_enabled)}


def control_snapshot(engine, contextual=None, learner=None, runtime=None):
    return {"protocol_version": 1, "pid": os.getpid(),
            "settings": settings_snapshot(engine, contextual, learner, runtime),
            "capabilities": {"context": contextual is not None, "learning": learner is not None}}


def validate_available(payload, contextual=None, learner=None, runtime=None):
    payload = validate_patch(payload)
    if payload.get("use_context") and contextual is None:
        raise ValueError("Questa istanza non ha un modello contestuale.")
    if (payload.get("learn_enabled") or payload.get("suggestions_enabled")) and learner is None:
        raise ValueError("Questa istanza non ha la memoria personale.")
    if "correction_enabled" in payload and runtime is None:
        raise ValueError("Questa istanza non supporta la pausa globale.")
    return payload


def apply_settings(engine, payload, contextual=None, learner=None, runtime=None):
    overrides = {key: payload[key] for key in ("min_score_margin", "min_frequency") if key in payload}
    engine.policy = replace(engine.policy, **overrides)
    if contextual is not None and "use_context" in payload:
        contextual.enabled = payload["use_context"]
    if learner is not None:
        if "learn_enabled" in payload:
            learner.enabled = payload["learn_enabled"]
        if "suggestions_enabled" in payload:
            learner.suggestions_enabled = payload["suggestions_enabled"]
    if runtime is not None and "correction_enabled" in payload:
        runtime.correction_enabled = payload["correction_enabled"]


def decide(engine, request: bytes, contextual=None, learner=None, runtime=None, segmenter=None) -> dict:
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
    paused = runtime is not None and not runtime.correction_enabled
    if paused:
        decision = Decision(word, word, "keep", "paused")
    elif contextual is None:
        decision = engine.evaluate(word, context=field_context)
    else:
        decision, context_info = contextual.evaluate(word, previous, context=field_context)
    segmentation_info = {"enabled": False, "used": False}
    if segmenter is not None and not paused:
        decision, segmentation_info = segmenter.evaluate(word, decision, context=field_context)
    personal_info = {"enabled": False, "used": False}
    if learner is not None and not paused:
        decision, personal_info = learner.apply(word, previous, decision, context=field_context)
    required_margin = context_info["required_margin"] if context_info["used"] else engine.policy.min_score_margin
    if segmentation_info["used"]:
        required_margin = segmentation_info["required_margin"]
    if personal_info["used"]:
        required_margin = None  # Explicit feedback is not a calibrated language-model margin.
    return {"original": token, "output": decision.output + suffix,
            "action": decision.action, "reason": decision.reason,
            "candidates": [asdict(candidate) for candidate in decision.candidates[:3]],
            "score_margin": decision.score_margin,
            "required_margin": required_margin,
            "baseline_required_margin": engine.policy.min_score_margin,
            "required_frequency": engine.policy.min_frequency, "context": context_info,
            "segmentation": segmentation_info, "personal": personal_info,
            "blocked_context": field_context != "text",
            "suggestions_enabled": bool(not paused and learner and learner.suggestions_enabled and field_context == "text"),
            "candidate_outputs": [c.term + suffix for c in decision.candidates[:3]] if decision.action == "keep" else []}


def handle_request(engine, request, contextual=None, learner=None, runtime=None, settings=None, segmenter=None):
    payload = json.loads(request)
    if not isinstance(payload, dict):
        raise ValueError("Richiesta non valida.")
    operation = payload.get("op", "decide")
    if operation == "decide":
        return decide(engine, request, contextual, learner, runtime, segmenter)
    if payload.get("context", "text") != "text":
        return {"feedback": {"status": "ignored_context"}}
    if operation == "status":
        token = payload.get("token")
        if token is not None and (not isinstance(token, str) or len(token) > 128):
            raise ValueError("Input di stato non valido.")
        return {"memory": learner.memory.status(token) if learner else None,
                "state": control_snapshot(engine, contextual, learner, runtime)}
    if operation == "configure":
        if settings is None:
            raise ValueError("Impostazioni non modificabili in questa istanza.")
        patch = validate_available(payload.get("changes"), contextual, learner, runtime)
        if settings.exists():
            read_patch(settings)  # Do not overwrite an unfamiliar/malformed file.
        updated = {**settings_snapshot(engine, contextual, learner, runtime), **patch}
        write_settings(settings, updated)
        apply_settings(engine, updated, contextual, learner, runtime)
        return {"configured": True, "state": control_snapshot(engine, contextual, learner, runtime)}
    if learner is None:
        return {"feedback": {"status": "learning_unavailable"}}
    if operation == "feedback":
        if runtime is not None and not runtime.correction_enabled:
            return {"feedback": {"status": "ignored_paused"}}
        return {"feedback": learner.feedback(payload)}
    if operation == "forget":
        from .feedback import feedback_word
        original = feedback_word(payload.get("token"))
        if not original:
            raise ValueError("Indicare il typo da dimenticare.")
        count = learner.memory.forget(original)
        return {"feedback": {"status": "forgotten", "original": original,
                             "forgotten_events": count, **learner.memory.status()}}
    raise ValueError("Operazione non riconosciuta.")


def refresh_policy(engine, settings: Path | None, contextual=None, learner=None, runtime=None) -> bool:
    """Apply a session-local override; malformed writes retain the last policy."""
    if settings is None:
        return False
    try:
        payload = validate_available(read_patch(settings), contextual, learner, runtime)
        apply_settings(engine, payload, contextual, learner, runtime)
        return True
    except (OSError, ValueError):
        return False


def serve(engine, path: Path, ready: Path, diagnostics: Path | None = None,
          settings: Path | None = None, contextual=None, learner=None, feedback_diagnostics: Path | None = None,
          segmenter=None):
    if len(os.fsencode(path)) >= 108:
        raise ValueError("Percorso del socket troppo lungo.")
    # Refuse to overwrite a socket from another running session.
    if path.exists() or path.is_symlink():
        raise ValueError("Il socket esiste già.")
    running = True
    runtime = RuntimeControls()

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
            refresh_policy(engine, settings, contextual, learner, runtime)
            ready.write_text(json.dumps({"dictionary_sha256": engine.dictionary_sha256,
                                        "policy": asdict(engine.policy),
                                        "context_model": contextual.model.metadata if contextual else None,
                                        "segmentation_models": [model.metadata for model, _ in segmenter.models] if segmenter else None,
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
                        refresh_policy(engine, settings, contextual, learner, runtime)
                        response = handle_request(engine, packet, contextual, learner, runtime, settings, segmenter)
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
    parser.add_argument("--segmentation", action="store_true",
                        help="Stacca parole attaccate e rimette l'apostrofo (richiede --context-corpus e Hunspell)")
    parser.add_argument("--colloquial-corpus", type=Path, help="Corpus colloquiale preparato, usato dalla separazione")
    parser.add_argument("--colloquial-weight", type=float)
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
            segmenter = None
            if args.segmentation:
                if args.context_corpus is None:
                    raise ValueError("--segmentation richiede --context-corpus.")
                from .segmentation import Segmenter, load_models
                segmenter = Segmenter(engine, load_models(args.context_corpus, args.colloquial_corpus,
                                                          args.colloquial_weight, stack))
            elif args.colloquial_corpus is not None:
                raise ValueError("--colloquial-corpus richiede --segmentation.")
            if args.feedback_memory is not None:
                from .feedback import FeedbackLearner, FeedbackMemory
                memory = stack.enter_context(FeedbackMemory(args.feedback_memory))
                learner = FeedbackLearner(engine, memory)
            serve(engine, args.socket, args.ready, args.diagnostics, args.settings, contextual, learner,
                  args.feedback_diagnostics, segmenter)
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        parser.exit(2, f"Errore: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
