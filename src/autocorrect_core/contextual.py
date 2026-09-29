"""Experimental context-assisted abstention recovery using TRAIN-only counts."""

import argparse
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
import json
import math
from pathlib import Path
import sqlite3
import time

from .dictionary import default_dictionary
from .engine import AutocorrectEngine, Decision, Policy, normalize
from .hunspell import HunspellValidator
from .leipzig_corpus import SHA256 as CORPUS_SHA256, digest_file
from .prediction import scan_text


DEFAULT_CORPUS = Path("benchmark-data/leipzig-ita-news-2023-100k")
ARTICLE_FAMILIES = (
    ("il", "del", "al", "dal", "nel", "sul", "col"),
    ("lo", "dello", "allo", "dallo", "nello", "sullo"),
    ("la", "della", "alla", "dalla", "nella", "sulla", "colla"),
    ("i", "dei", "ai", "dai", "nei", "sui", "coi"),
    ("gli", "degli", "agli", "dagli", "negli", "sugli"),
    ("le", "delle", "alle", "dalle", "nelle", "sulle", "colle"),
)
ARTICLE_FAMILY = {article: family for family in ARTICLE_FAMILIES for article in family}


def missing_internal_vowel(typed, candidate):
    return len(candidate) == len(typed) + 1 and any(
        letter in "aeiouàèéìòóù" and candidate[:index] + candidate[index + 1:] == typed
        for index, letter in enumerate(candidate) if 0 < index < len(candidate) - 1)


@dataclass(frozen=True)
class ContextPolicy:
    # Development choices, not calibrated probabilities/confidence. Compared
    # against controls before enabling the optional Fcitx laboratory mode.
    smoothing: float = 20.0
    unigram_pseudocount: float = 0.5
    min_ratio: float = 5.0
    min_evidence: int = 3
    short_min_evidence: int = 5
    min_length: int = 3
    three_letter_margin: float = 1.3
    three_letter_edit_penalty: float = 3.0
    three_letter_min_trigram: int = 3
    article_min_evidence: int = 10

    @property
    def margin(self):
        return math.log10(self.min_ratio)


class TrainingNgrams:
    """Indexed read-only SQLite rows with a bounded per-instance row cache."""

    def __init__(self, database: Path):
        self.connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=.01)
        self.connection.execute("PRAGMA query_only=ON")
        self.connection.execute("PRAGMA cache_size=-4096")
        self.row = lru_cache(maxsize=64)(self._row)
        self.article_row = lru_cache(maxsize=len(ARTICLE_FAMILIES))(self._article_row)
        try:
            self.unigrams, self.total = self._row(())
            if not self.unigrams or self.total <= 0:
                raise ValueError("Conteggi unigramma assenti.")
        except BaseException:
            self.close()
            raise
        self.metadata = {"database": str(database), "scope": "custom counts; caller supplies provenance"}

    @classmethod
    def from_leipzig(cls, directory: Path):
        manifest = json.loads((directory / "manifest.json").read_text())
        database = directory / "ngrams.sqlite3"
        expected = manifest["files_sha256"]["ngrams.sqlite3"]
        if manifest["archive_sha256"] != CORPUS_SHA256 or digest_file(database) != expected:
            raise ValueError("Corpus Leipzig diverso dall'archivio/manifest verificato.")
        result = cls(database)
        result.metadata = {"database_sha256": expected, "archive_sha256": CORPUS_SHA256,
                           "scope": "Leipzig normalized/deduplicated TRAIN split only", "split": manifest["split"]}
        return result

    def _row(self, context):
        c1, c2 = (("", "") + context)[-2:]
        values = dict(self.connection.execute(
            "SELECT word,count FROM ngrams WHERE n=? AND c1=? AND c2=?", (len(context) + 1, c1, c2)))
        if any(type(count) is not int or count <= 0 for count in values.values()):
            raise ValueError("Conteggi del corpus non validi.")
        return values, sum(values.values())

    def count(self, context, word):
        """One primary-key lookup, for callers that need a single surface form."""
        c1, c2 = (("", "") + tuple(context))[-2:]
        found = self.connection.execute("SELECT count FROM ngrams WHERE n=? AND c1=? AND c2=? AND word=?",
                                        (len(context) + 1, c1, c2, word)).fetchone()
        if found is not None and (type(found[0]) is not int or found[0] <= 0):
            raise ValueError("Conteggi del corpus non validi.")
        return found[0] if found else 0

    def close(self):
        self.row.cache_clear()
        self.article_row.cache_clear()
        self.connection.close()

    def _article_row(self, family):
        if family not in ARTICLE_FAMILIES:
            raise ValueError("Famiglia di articoli non riconosciuta.")
        placeholders = ",".join("?" for _ in family)
        values = dict(self.connection.execute(
            f"SELECT word,SUM(count) FROM ngrams WHERE n=2 AND c1='' AND c2 IN ({placeholders}) GROUP BY word",
            family))
        if any(type(count) is not int or count <= 0 for count in values.values()):
            raise ValueError("Conteggi aggregati non validi.")
        return values, sum(values.values())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@dataclass(frozen=True)
class ContextCandidate:
    term: str
    distance: int
    frequency: int
    score: float
    bigram_count: int
    trigram_count: int
    article_count: int = 0


class ContextualCorrector:
    def __init__(self, engine, model, *, enabled=True):
        self.engine = engine
        self.model = model
        self.enabled = enabled
        self.policy = ContextPolicy()
        # Load these six aggregates before accepting keystrokes. Broad indexed
        # GROUP BY queries must not consume the bridge's 50 ms request budget.
        for family in ARTICLE_FAMILIES:
            self.model.article_row(family)

    def evaluate(self, token, previous="", *, context="text", limit=5):
        started = time.perf_counter()
        # Request the entire candidate set, not the diagnostic top 3/CLI top 5.
        base = self.engine.evaluate(token, context=context, limit=max(1, self.engine.word_count))
        word = normalize(token)
        length = len(word)
        info = {"enabled": self.enabled, "used": False, "baseline_reason": base.reason,
                "baseline_output": base.output, "previous_words": [],
                "required_margin": self.policy.margin, "min_evidence": self.policy.min_evidence,
                "short_min_evidence": self.policy.short_min_evidence,
                "minimum_context_length": self.policy.min_length, "evidence_source": "exact_context"}

        def finish(decision):
            info["elapsed_ms"] = (time.perf_counter() - started) * 1000
            return replace(decision, candidates=decision.candidates[:limit]), info

        # This first experiment only recovers abstentions; it never replaces
        # an existing automatic decision or any lexical/validator/form veto.
        if (not self.enabled or base.reason not in ("ambiguous", "short_word")
                or length < self.policy.min_length
                or token != token.lower() or not base.candidates):
            return finish(base)
        if not isinstance(previous, str) or len(previous) > 1024 or "\0" in previous:
            raise ValueError("Contesto non valido o troppo lungo.")
        # A partial previous word is not usable evidence.
        if not previous or not previous[-1].isspace():
            return finish(base)
        _, words = scan_text(previous)
        history = tuple(words[-2:])
        info["previous_words"] = list(history)
        if not history:
            return finish(base)
        try:
            bigrams, bigram_total = self.model.row(history[-1:])
            trigrams, trigram_total = self.model.row(history) if len(history) == 2 else ({}, 0)
            article_counts, article_total = {}, 0
            family = ARTICLE_FAMILY.get(history[-1])
            if (length == 3 and family
                    and any(missing_internal_vowel(word, candidate.term) for candidate in base.candidates)
                    and not any(candidate.distance <= self.engine.policy.max_auto_distance
                                and (bigrams.get(candidate.term, 0) or trigrams.get(candidate.term, 0))
                                for candidate in base.candidates)):
                article_counts, article_total = self.model.article_row(family)
        except (sqlite3.Error, ValueError):
            info["model_error"] = True
            return finish(base)
        if not bigram_total and not trigram_total and not article_total:
            return finish(base)
        info.update(used=True, bigram_total=bigram_total, trigram_total=trigram_total)
        if article_total:
            info.update(evidence_source="article_family", article_family=list(family), article_total=article_total)
        alpha, pseudocount = self.policy.smoothing, self.policy.unigram_pseudocount
        penalty = self.policy.three_letter_edit_penalty if length == 3 else self.engine.policy.edit_penalty
        info["edit_penalty"] = penalty
        ranked = []
        for item in base.candidates:
            probability = (self.model.unigrams.get(item.term, 0) + pseudocount) / (
                self.model.total + pseudocount * len(self.model.unigrams))
            levels = ((article_counts, article_total),) if article_total else ((bigrams, bigram_total), (trigrams, trigram_total))
            for row, total in levels:
                if total:
                    probability = (row.get(item.term, 0) + alpha * probability) / (total + alpha)
            score = math.log10(probability) - penalty * item.distance
            ranked.append(ContextCandidate(item.term, item.distance, item.frequency, score,
                                            bigrams.get(item.term, 0), trigrams.get(item.term, 0),
                                            article_counts.get(item.term, 0)))
        ranked.sort(key=lambda item: (-item.score, item.distance, item.term))
        best = ranked[0]
        margin = best.score - ranked[1].score if len(ranked) > 1 else None
        evidence = best.article_count if article_total else max(best.bigram_count, best.trigram_count)
        short = length <= 4
        needed = self.policy.short_min_evidence if short else self.policy.min_evidence
        required_margin = self.policy.margin if short else self.engine.policy.min_score_margin
        if length == 3:
            required_margin = max(self.policy.three_letter_margin, self.engine.policy.min_score_margin)
            if article_total:
                needed = self.policy.article_min_evidence
            else:
                # Three-character substitutions are easily confused with tool
                # names and pronouns. A frequent one-word context isn't enough.
                evidence = best.trigram_count
                needed = self.policy.three_letter_min_trigram
                info["evidence_source"] = "exact_trigram"
        info.update(evidence=evidence, required_evidence=needed, required_margin=required_margin,
                    baseline_candidate=base.candidates[0].term,
                    baseline_rank=next(i + 1 for i, item in enumerate(base.candidates) if item.term == best.term))
        reason = "context_high_margin"
        if best.term in self.engine.protected:
            reason = "protected_candidate"
        elif best.distance > self.engine.policy.max_auto_distance:
            reason = "edit_distance"
        elif best.frequency < self.engine.policy.min_frequency:
            reason = "low_frequency"
        elif length == 3 and len(best.term) < 3:
            reason = "context_short_target"
        elif article_total and not missing_internal_vowel(word, best.term):
            reason = "context_unsupported_short_edit"
        elif evidence < needed:
            reason = "context_low_evidence"
        elif (not short and best.term != base.candidates[0].term
              and best.trigram_count < self.policy.min_evidence):
            reason = "context_weak_rerank"
        elif margin is not None and margin < required_margin:
            reason = "context_ambiguous"
        corrected = reason == "context_high_margin"
        return finish(Decision(token, best.term if corrected else token,
                               "correct" if corrected else "keep", reason,
                               tuple(ranked), len(ranked), margin))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("token")
    parser.add_argument("--previous", default="")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--frequency", type=int, default=5000)
    args = parser.parse_args(argv)
    with HunspellValidator() as validator, TrainingNgrams.from_leipzig(args.corpus) as model:
        engine = AutocorrectEngine(default_dictionary(), policy=Policy(min_frequency=args.frequency), word_validator=validator)
        corrector = ContextualCorrector(engine, model)
        decision, info = corrector.evaluate(args.token, args.previous)
        print(json.dumps({"decision": decision.to_dict(), "context": info, "policy": asdict(corrector.policy)},
                         ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
