"""Joined words and missing apostrophes: perpiacere -> per piacere, lacqua -> l'acqua.

Runs only after the lexical engine (and optional context) abstained. Every
reading, including ordinary one-edit corrections, is scored by how often its
exact surface form occurs in TRAIN counts; a space or an apostrophe is one edit,
like any other. Counts are evidence for ranking, not calibrated confidence.
"""

import argparse
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import time

from .engine import Decision, Policy, latin_word, normalize


VOWELS = "aeiouàèéìòóùh"
# Extra corpora (Tatoeba, generated chat) relative to Leipzig news counts (weight 1).
DEFAULT_EXTRA_WEIGHT = 1.0
ACCENT_SWAP = str.maketrans("èé", "éè")
# One-letter split parts must be real words on their own ("parte a", "i due"),
# never a stray consonant such as "la b" for lab.
ONE_LETTER_WORDS = frozenset("aeèio")
# Base outcomes a new reading may replace. Vetoes (known/valid/protected
# words, case, disabled fields) and existing corrections are never revisited.
RECOVERABLE = ("ambiguous", "short_word", "edit_distance", "low_frequency", "no_candidate", "possible_elision",
               "context_ambiguous", "context_low_evidence", "context_weak_rerank", "context_short_target",
               "context_unsupported_short_edit")


@dataclass(frozen=True)
class SegmentationPolicy:
    # Development choices; see docs/SEGMENTATION.md for the measurements.
    min_evidence: float = 3.0
    min_ratio: float = 5.0
    min_length: int = 2
    max_length: int = 40
    # log10 cost of a letter edit relative to an inserted space/apostrophe:
    # "lho" is far more often a skipped apostrophe than an extra letter in "lo".
    word_edit_penalty: float = 1.0

    @property
    def margin(self):
        return math.log10(self.min_ratio)


@dataclass(frozen=True)
class SegmentCandidate:
    term: str
    distance: int
    frequency: int
    score: float
    kind: str
    evidence: float


def segmented_parts(text):
    """Split a two-part reading; None for anything else."""
    if text.count(" ") + text.count("'") != 1 or text[0] in " '" or text[-1] in " '":
        return None
    parts = text.split(" ") if " " in text else text.split("'")
    return parts if all(latin_word(part) for part in parts) else None


class Segmenter:
    def __init__(self, engine, models, *, policy=None, enabled=True):
        """models: [(TrainingNgrams, weight)], e.g. Leipzig at 1 and generated chat at a chosen weight."""
        if engine.word_validator is None:
            raise ValueError("La separazione delle parole richiede Hunspell per validare gli apostrofi.")
        if not models:
            raise ValueError("Serve almeno un modello di conteggi.")
        self.engine = engine
        self.models = list(models)
        self.policy = policy or SegmentationPolicy()
        self.enabled = enabled

    def surface_count(self, context, word):
        return sum(weight * model.count(context, word) for model, weight in self.models)

    def readings(self, word):
        found = []
        words = self.engine.symspell.words
        minimum = self.engine.policy.min_frequency
        for index in range(1, len(word)):
            left, right = word[:index], word[index:]
            if (left in self.engine.protected or right in self.engine.protected
                    or words.get(left, 0) < minimum or words.get(right, 0) < minimum
                    or any(len(part) == 1 and part not in ONE_LETTER_WORDS for part in (left, right))):
                continue
            evidence = self.surface_count((left,), right)
            found.append(SegmentCandidate(f"{left} {right}", 1, min(words[left], words[right]), 0.0, "split", evidence))
        for index in range(1, len(word)):
            if word[index] not in VOWELS:
                continue
            elided = f"{word[:index]}'{word[index:]}"
            # Hunspell knows which article/preposition elides before which word:
            # it accepts l'acqua and l'ho, and rejects un'altro.
            if elided not in words and not self.engine.word_validator.spell(elided):
                continue
            evidence = self.surface_count((), elided)
            found.append(SegmentCandidate(elided, 1, words.get(elided, 0), 0.0, "elision", evidence))
        return found

    def evaluate(self, token, decision, *, context="text", limit=5):
        started = time.perf_counter()
        word = normalize(token)
        info = {"enabled": self.enabled, "used": False, "baseline_reason": decision.reason,
                "required_margin": self.policy.margin, "min_evidence": self.policy.min_evidence,
                "word_edit_penalty": self.policy.word_edit_penalty}

        def finish(result):
            info["elapsed_ms"] = (time.perf_counter() - started) * 1000
            return result, info

        if (not self.enabled or context != "text" or decision.action != "keep" or decision.reason not in RECOVERABLE
                or token != token.lower() or not self.policy.min_length <= len(word) <= self.policy.max_length
                or not latin_word(word)):
            return finish(decision)
        found = list(self.readings(word))
        if not found:
            return finish(decision)
        # One-edit corrections compete on the same surface-count scale, so a
        # split never steals a typo such as trada -> strada.
        competitors = [SegmentCandidate(item.term, item.distance, item.frequency, 0.0, "word",
                                        self.surface_count((), item.term))
                       for item in decision.candidates
                       if item.distance <= self.engine.policy.max_auto_distance and " " not in item.term]
        penalty = self.policy.word_edit_penalty

        def ranking(items):
            return sorted((SegmentCandidate(c.term, c.distance, c.frequency,
                                            math.log10(c.evidence + .5) - (penalty * c.distance if c.kind == "word" else 0),
                                            c.kind, c.evidence)
                           for c in items), key=lambda c: (-c.score, c.kind != "word", c.term))

        ranked = ranking(found)
        # The engine never applies a letter edit below min_auto_length, so for
        # lho/cè/dovè "lo", "è" and "dove" are not live alternatives to an
        # apostrophe that keeps every typed letter. Splits keep them (sase).
        # A more frequent grave/acute swap stays live: nè is né and sè is sé,
        # not n'è/s'è; dové is rarer than dov'è.
        words = self.engine.symspell.words
        swapped = word.translate(ACCENT_SWAP)
        confusable = swapped != word and words.get(swapped, 0) > words.get(ranked[0].term, 0)
        short = len(word) < self.engine.policy.min_auto_length and not confusable
        if not (short and ranked[0].kind == "elision"):
            ranked = ranking(found + competitors)
        info["word_competitors"] = len(competitors) if len(ranked) > len(found) else 0
        best = ranked[0]
        margin = best.score - ranked[1].score if len(ranked) > 1 else None
        info.update(readings=len(ranked), best_kind=best.kind, evidence=best.evidence)
        if best.kind == "word":
            # The lexical engine already abstained on this word; keep its reason.
            info["outcome"] = "word_preferred"
            return finish(decision)
        info["used"] = True
        reason = "segmentation_split" if best.kind == "split" else "segmentation_elision"
        if best.evidence < self.policy.min_evidence:
            reason = "segmentation_low_evidence"
        elif margin is not None and margin < self.policy.margin:
            reason = "segmentation_ambiguous"
        info["outcome"] = reason
        corrected = not reason.endswith(("low_evidence", "ambiguous"))
        return finish(Decision(token, best.term if corrected else token, "correct" if corrected else "keep",
                               reason, tuple(ranked[:limit]), len(ranked), margin))


def corpus_option(value):
    """argparse type for DIR or DIR=WEIGHT."""
    path, _, weight = value.partition("=")
    try:
        number = float(weight) if weight else DEFAULT_EXTRA_WEIGHT
    except ValueError:
        raise argparse.ArgumentTypeError(f"Peso non valido: {weight}") from None
    if not path or not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Atteso CARTELLA oppure CARTELLA=PESO con peso positivo.")
    return Path(path), number


def load_models(context_corpus, extra=(), stack=None):
    """Leipzig at weight 1, plus prepared corpora as [(directory, weight)]."""
    from .contextual import TrainingNgrams
    from .prepared_corpus import load_prepared
    models = [(TrainingNgrams.from_leipzig(context_corpus), 1.0)]
    for directory, weight in extra:
        models.append((load_prepared(directory), weight))
    if stack is not None:
        for model, _ in models:
            stack.callback(model.close)
    return models


def main(argv=None):
    from contextlib import ExitStack
    from .contextual import DEFAULT_CORPUS
    from .dictionary import default_dictionary
    from .engine import AutocorrectEngine
    from .hunspell import HunspellValidator
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tokens", nargs="+")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--segmentation-corpus", type=corpus_option, action="append", default=[],
                        metavar="CARTELLA[=PESO]", help="Corpus preparato aggiuntivo (Tatoeba, colloquiale)")
    parser.add_argument("--frequency", type=int, default=5000)
    args = parser.parse_args(argv)
    with ExitStack() as stack:
        validator = stack.enter_context(HunspellValidator())
        engine = AutocorrectEngine(default_dictionary(), policy=Policy(min_frequency=args.frequency), word_validator=validator)
        segmenter = Segmenter(engine, load_models(args.corpus, args.segmentation_corpus, stack))
        for token in args.tokens:
            decision, info = segmenter.evaluate(token, engine.evaluate(token))
            print(json.dumps({"decision": decision.to_dict(), "segmentation": info}, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
