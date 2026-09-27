"""Persistent local engine for the isolated Fcitx probe, one token per packet."""

import argparse
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import re
import signal
import socket
import time

from .cli import add_engine_arguments, load_engine


PACKET_LIMIT = 4096
TRAILING_PUNCTUATION = re.compile(r"([^\W\d_]+)([,.!?;:]+)", re.UNICODE)


def decide(engine, request: bytes) -> dict:
    payload = json.loads(request)
    if not isinstance(payload, dict) or not isinstance(payload.get("token"), str):
        raise ValueError("Atteso un token testuale.")
    token = payload["token"]
    if len(token) > 128 or "\0" in token:
        raise ValueError("Token non valido o troppo lungo.")
    # Strip only trailing punctuation from an otherwise plain alphabetic token.
    # URLs, paths, numbers, apostrophes and mixed punctuation remain whole.
    match = TRAILING_PUNCTUATION.fullmatch(token)
    word, suffix = (match[1], match[2]) if match else (token, "")
    decision = engine.evaluate(word)
    return {"original": token, "output": decision.output + suffix,
            "action": decision.action, "reason": decision.reason,
            "candidates": [asdict(candidate) for candidate in decision.candidates[:3]],
            "score_margin": decision.score_margin,
            "required_margin": engine.policy.min_score_margin}


def refresh_policy(engine, settings: Path | None) -> bool:
    """Apply a session-local override; malformed writes retain the last policy."""
    if settings is None:
        return False
    try:
        with settings.open("rb") as source:
            raw = source.read(1025)
        if len(raw) > 1024:
            return False
        payload = json.loads(raw)
        value = payload.get("min_score_margin") if isinstance(payload, dict) else None
        if type(value) not in (int, float) or not 0.01 <= value <= 5.0:
            return False
        engine.policy = replace(engine.policy, min_score_margin=float(value))
        return True
    except (OSError, ValueError):
        return False


def serve(engine, path: Path, ready: Path, diagnostics: Path | None = None,
          settings: Path | None = None):
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
            ready.write_text(json.dumps({"dictionary_sha256": engine.dictionary_sha256,
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
                        refresh_policy(engine, settings)
                        response = decide(engine, packet)
                    except (ValueError, OSError):
                        response = {"action": "keep", "reason": "invalid_request"}
                    try:
                        client.send(json.dumps(response, ensure_ascii=False).encode("utf-8"))
                    except OSError:
                        pass  # Client already declined a late response.
                    if diagnostics is not None:
                        # This is an engine decision, not an application acknowledgement.
                        # Publish after replying, keeping disk I/O out of the response budget.
                        snapshot = {**response, "time_ns": time.time_ns(), "source": "engine_decision"}
                        temporary = diagnostics.with_suffix(".tmp")
                        try:
                            temporary.write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
                            temporary.chmod(0o600)
                            temporary.replace(diagnostics)
                        except OSError:
                            pass  # Diagnostics must not disable typing.
        finally:
            path.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path, help="Ultima analisi locale per la finestra di prova")
    parser.add_argument("--settings", type=Path, help="Margine modificabile, solo per questa sessione di prova")
    add_engine_arguments(parser)
    args = parser.parse_args(argv)
    try:
        engine = load_engine(args)
        serve(engine, args.socket, args.ready, args.diagnostics, args.settings)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Errore: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
