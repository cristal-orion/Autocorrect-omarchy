"""Persistent explicit feedback: typo pairs, contextual uses and rejection signals."""

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time

from symspellpy.editdistance import DistanceAlgorithm, EditDistance

from .engine import CONTEXTS, Decision, latin_word, normalize
from .prediction import scan_text
from .segmentation import segmented_parts


POSITIVE_KINDS = ("manual", "selection")
# A rejection is an undo the user then kept with Space; it weighs as much as a
# confirmation. Backspace is common while writing, so one undo must not
# outweigh earlier explicit corrections.
REJECTION_WEIGHT = 1
DISTANCE = EditDistance(DistanceAlgorithm.DAMERAU_OSA)
# Also "per piacere," and "l'acqua.": two-part readings keep their punctuation.
TRAILING = re.compile(r"([^\W\d_]+(?:[ '][^\W\d_]+)?)([,.!?;:]+)", re.UNICODE)


def default_feedback_memory():
    root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    return root / "autocorrect/feedback.sqlite3"


def history(previous):
    if not isinstance(previous, str) or len(previous) > 1024 or "\0" in previous:
        raise ValueError("Contesto del feedback non valido.")
    _, words = scan_text(previous)
    return (("", "") + tuple(words))[-2:]


def feedback_word(value):
    if not isinstance(value, str) or len(value) > 128 or "\0" in value:
        raise ValueError("Parola del feedback non valida.")
    match = TRAILING.fullmatch(value)
    return normalize(match[1] if match else value)


class FeedbackMemory:
    """No learned counts are cached: another session/forget is visible immediately."""

    def __init__(self, path, *, read_only=False):
        self.path = Path(path)
        if read_only:
            self.db = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.02)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(fd)
            self.db = sqlite3.connect(self.path, timeout=.02)
        try:
            tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if not tables and version == 0 and not read_only:
                with self.db:
                    self.db.execute("CREATE TABLE feedback_events (id TEXT PRIMARY KEY, kind TEXT NOT NULL, "
                                    "original TEXT NOT NULL, target TEXT NOT NULL, c1 TEXT NOT NULL, c2 TEXT NOT NULL, "
                                    "pair_eligible INTEGER NOT NULL, active INTEGER NOT NULL, created_ns INTEGER NOT NULL)")
                    # Forget removes text/events, but receipts prevent retransmission
                    # of an already handled event from resurrecting the learned pair.
                    self.db.execute("CREATE TABLE feedback_receipts (id TEXT PRIMARY KEY, digest TEXT NOT NULL)")
                    self.db.execute("CREATE INDEX feedback_original ON feedback_events(original)")
                    self.db.execute("CREATE INDEX feedback_context ON feedback_events(c1,c2)")
                    self.db.execute("PRAGMA user_version=1")
            elif tables != {"feedback_events", "feedback_receipts"} or version != 1:
                raise ValueError("Il file esistente non è una memoria feedback supportata.")
            if not read_only:
                self.db.execute("PRAGMA journal_mode=WAL")
        except BaseException:
            self.db.close()
            raise

    def record(self, event_id, kind, original, target, ctx, pair_eligible, undo_of=""):
        payload = (kind, original, target, ctx, bool(pair_eligible), undo_of)
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            receipt = self.db.execute("SELECT digest FROM feedback_receipts WHERE id=?", (event_id,)).fetchone()
            if receipt:
                if receipt[0] != digest:
                    raise ValueError("Identificativo feedback riutilizzato con contenuto diverso.")
                return "duplicate"
            self.db.execute("INSERT INTO feedback_receipts VALUES (?,?)", (event_id, digest))
            if undo_of:
                previous = self.db.execute("SELECT kind,original,target,active FROM feedback_events WHERE id=?", (undo_of,)).fetchone()
                if previous is None:
                    return "ignored_missing_event"
                if kind != "reject" or previous[0] not in POSITIVE_KINDS or previous[1:3] != (original, target):
                    raise ValueError("Annullamento non coerente con la conferma.")
                if not previous[3]:
                    return "ignored_already_undone"
                self.db.execute("UPDATE feedback_events SET active=0 WHERE id=?", (undo_of,))
            self.db.execute("INSERT INTO feedback_events VALUES (?,?,?,?,?,?,?,?,?)",
                            (event_id, kind, original, target, *ctx, int(pair_eligible), 1, time.time_ns()))
        return "learned_pair" if pair_eligible and kind in POSITIVE_KINDS else ("learned_use" if kind in POSITIVE_KINDS else "rejected")

    def pairs(self, original):
        rows = self.db.execute(
            "SELECT target,SUM(kind IN ('manual','selection')),SUM(kind='reject') FROM feedback_events "
            "WHERE original=? AND pair_eligible=1 AND active=1 GROUP BY target", (original,))
        return {target: {"confirmations": positive, "rejections": negative, "net": positive - REJECTION_WEIGHT * negative}
                for target, positive, negative in rows}

    def uses(self, ctx):
        return dict(self.db.execute(
            "SELECT target,COUNT(*) FROM feedback_events WHERE c1=? AND c2=? "
            "AND active=1 AND kind IN ('manual','selection') GROUP BY target ORDER BY COUNT(*) DESC,target LIMIT 64", ctx))

    def forget(self, original):
        with self.db:
            count = self.db.execute("DELETE FROM feedback_events WHERE original=?", (original,)).rowcount
        return count

    def status(self, original=None):
        positive, negative = self.db.execute(
            "SELECT COALESCE(SUM(kind IN ('manual','selection')),0),COALESCE(SUM(kind='reject'),0) "
            "FROM feedback_events WHERE active=1").fetchone()
        pairs = self.db.execute("SELECT COUNT(*) FROM (SELECT original,target FROM feedback_events "
                                "WHERE active=1 AND pair_eligible=1 GROUP BY original,target)").fetchone()[0]
        result = {"confirmations": positive, "rejections": negative, "pair_count": pairs}
        if original is not None:
            result["pairs"] = self.pairs(normalize(original))
        return result

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@dataclass(frozen=True)
class PersonalCandidate:
    term: str
    distance: int
    frequency: int
    score: float | None
    confirmations: int = 0
    rejections: int = 0
    context_uses: int = 0


class FeedbackLearner:
    def __init__(self, engine, memory):
        if engine.word_validator is None:
            raise ValueError("L'apprendimento delle coppie richiede Hunspell.")
        self.engine = engine
        self.memory = memory
        self.enabled = True
        self.suggestions_enabled = False

    def recognized(self, word):
        return (word in self.engine.symspell.words or word in self.engine.protected
                or self.engine.word_validator.spell(word))

    def recognized_target(self, target):
        """A destination may be a split (per piacere) or an elided form (l'acqua)."""
        if " " in target:
            parts = segmented_parts(target)
            return parts is not None and all(self.recognized(part) for part in parts)
        return self.recognized(target)

    def feedback(self, payload):
        context = payload.get("context", "text")
        if context not in CONTEXTS:
            raise ValueError("Contesto del campo non riconosciuto.")
        if context != "text":
            return {"status": "ignored_context"}
        if not self.enabled:
            return {"status": "ignored_disabled"}
        kind = payload.get("kind")
        if kind == "automatic":
            return {"status": "ignored_automatic"}
        if kind not in (*POSITIVE_KINDS, "reject"):
            raise ValueError("Tipo di feedback non riconosciuto.")
        event_id, undo_of = payload.get("id"), payload.get("undo_of", "")
        if (not isinstance(event_id, str) or not 1 <= len(event_id) <= 128 or "\0" in event_id
                or not isinstance(undo_of, str) or len(undo_of) > 128 or "\0" in undo_of
                or (undo_of and kind != "reject")):
            raise ValueError("Identificativo del feedback non valido.")
        original = feedback_word(payload.get("original"))
        target = feedback_word(payload.get("target"))
        ctx = history(payload.get("previous", ""))
        if (not latin_word(original) or not (latin_word(target) or segmented_parts(target))
                or max(len(original), len(target)) > 64 or original == target):
            return {"status": "ignored_edit"}
        if not self.recognized_target(target):
            return {"status": "ignored_unknown_target"}
        distance = DISTANCE.compare(original, target, 2)
        pair = (len(original) >= 3 and payload["original"] == payload["original"].lower()
                and payload["target"] == payload["target"].lower()
                and 1 <= distance <= 2 and not self.recognized(original))
        result = self.memory.record(event_id, kind, original, target, ctx, pair, undo_of)
        return {"status": result, "original": original, "target": target, "id": event_id,
                "pair_eligible": pair, **self.memory.status(original)}

    def apply(self, token, previous, decision, *, context="text", limit=5):
        info = {"enabled": self.enabled, "used": False}
        word = normalize(token)
        if (not self.enabled or context != "text" or len(word) < 3 or len(word) > 64 or not latin_word(word)
                or token != token.lower() or self.recognized(word)
                or decision.reason in ("possible_elision", "protected_word", "disabled_context")):
            return decision, info
        pairs = self.memory.pairs(word)
        uses = self.memory.uses(history(previous))
        if not pairs and not uses:
            return decision, info
        candidates = {item.term: item for item in decision.candidates}
        # Human-confirmed destinations can be absent from the truncated base
        # ranking, or recognized only through Hunspell.
        for target in sorted(pairs.keys() | uses.keys()):
            distance = DISTANCE.compare(word, target, 2)
            if target not in candidates and 1 <= distance <= 2 and self.recognized_target(target):
                candidates[target] = PersonalCandidate(target, distance, self.engine.symspell.words.get(target, 0), None)
        order = {term: index for index, term in enumerate(candidates)}
        ranked = [PersonalCandidate(item.term, item.distance, item.frequency, item.score,
                    pairs.get(item.term, {}).get("confirmations", 0), pairs.get(item.term, {}).get("rejections", 0),
                    uses.get(item.term, 0)) for item in candidates.values()]
        ranked.sort(key=lambda item: (-(item.confirmations - REJECTION_WEIGHT * item.rejections), -item.context_uses, order[item.term]))
        available = [(value["net"], target) for target, value in pairs.items() if target in candidates and value["net"] > 0]
        available.sort(reverse=True)
        reason, output = decision.reason, decision.output
        if available and (len(available) == 1 or available[0][0] > available[1][0]):
            output, reason = available[0][1], "personal_correction"
        elif available:
            output, reason = token, "personal_ambiguous"
        elif decision.action == "correct" and pairs.get(normalize(decision.output), {}).get("net", 0) < 0:
            # Only a net majority of rejections vetoes the general engine.
            output, reason = token, "personal_rejected"
        elif decision.action == "correct":
            return decision, info
        elif any(value["net"] < 0 for value in pairs.values()):
            output, reason = token, "personal_rejected"
        elif any(item.context_uses or item.confirmations or item.rejections for item in ranked):
            reason = "personal_suggestion"
        else:
            return decision, info
        evidence_target = normalize(output)
        if evidence_target not in pairs and pairs:
            evidence_target = max(pairs, key=lambda target: (pairs[target]["confirmations"] + pairs[target]["rejections"], target))
        elif not pairs and ranked:
            evidence_target = ranked[0].term
        info.update(used=True, source="explicit_feedback", baseline_reason=decision.reason, target=evidence_target,
                    confirmations=pairs.get(evidence_target, {}).get("confirmations", 0),
                    rejections=pairs.get(evidence_target, {}).get("rejections", 0),
                    context_uses=uses.get(evidence_target, 0))
        return Decision(token, output, "correct" if output != token else "keep", reason,
                        tuple(ranked[:limit]), len(ranked)), info


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--memory", type=Path, default=default_feedback_memory())
    sub = parser.add_subparsers(dest="operation", required=True)
    status = sub.add_parser("status")
    status.add_argument("original", nargs="?")
    forget = sub.add_parser("forget")
    forget.add_argument("original", help="Dimentica coppie, usi e rifiuti originati da questo input")
    args = parser.parse_args(argv)
    with FeedbackMemory(args.memory) as memory:
        if args.operation == "forget":
            result = {"forgotten_events": memory.forget(feedback_word(args.original)), **memory.status()}
        else:
            result = memory.status(args.original)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
