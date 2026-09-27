"""Small interpolated n-gram model for explicit, contextual suggestions.

Scores rank suggestions; they are not calibrated correction confidence.
"""

from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
import heapq
import math
import re
import unicodedata

from .engine import AutocorrectEngine, latin_word, normalize


START = "<s>"
END = "</s>"
PUNCTUATION = ',.:;!?()[]{}"«»“”'
WORD = re.compile(r"[^\W\d_]+(?:'[^\W\d_]+)*", re.UNICODE)


def is_word(token: str) -> bool:
    return bool(WORD.fullmatch(token)) and latin_word(token.replace("'", ""))


def scan_text(text: str) -> tuple[list[list[str]], list[str]]:
    """Return completed sequences and an unfinished one, without bridging URLs/code.

    This intentionally small tokenizer handles whitespace-delimited prose and
    apostrophes. Numbers and structured tokens interrupt the context.
    """
    sentences, current = [], []
    for match in re.finditer(r"\n|[^\s]+", unicodedata.normalize("NFC", text)):
        chunk = match.group()
        word = normalize(chunk.strip(PUNCTUATION))
        if is_word(word) and len(word) <= 64:
            current.append(word)
        elif current:
            sentences.append(current)
            current = []
        if chunk == "\n" or chunk.endswith((".", "!", "?", ";")):
            if current:
                sentences.append(current)
                current = []
    return sentences, current


def sentences_from(text: str) -> list[list[str]]:
    completed, current = scan_text(text)
    return completed + ([current] if current else [])


def history_for(words) -> tuple[str, str]:
    return tuple(([START, START] + list(words))[-2:])


def counts_for(sentences) -> Counter:
    counts = Counter()
    for words in sentences:
        history = (START, START)
        for word in [*words, END]:
            for context in ((), history[-1:], history):
                counts[context, word] += 1
            history = (history[-1], word)
    return counts


class NgramModel:
    def __init__(self):
        self.rows = defaultdict(Counter)
        self.totals = Counter()
        self.revision = 0

    def add_counts(self, counts):
        for (context, word), count in counts.items():
            self.rows[context][word] += count
            self.totals[context] += count
        self.revision += 1

    def learn(self, text: str) -> int:
        sentences = sentences_from(text)
        self.add_counts(counts_for(sentences))
        return len(sentences)

    def probability(self, word: str, history: tuple[str, str]) -> float:
        probability = self.rows.get((), {}).get(word, 0) / max(1, self.totals[()])
        for context, weight in ((history[-1:], 0.85), (history, 0.9)):
            if self.totals[context]:
                local = self.rows[context].get(word, 0) / self.totals[context]
                probability = weight * local + (1 - weight) * probability
        return probability

    def evidence(self, word: str, history: tuple[str, str]) -> int:
        for context in (history, history[-1:], ()):
            if self.rows.get(context, {}).get(word, 0):
                return len(context) + 1
        return 0

    def has_context(self, history: tuple[str, str]) -> bool:
        return bool(self.totals[history] or self.totals[history[-1:]])

    def candidates(self, history: tuple[str, str], prefix: str) -> set[str]:
        result = set()
        for context in (history, history[-1:], ()):
            row = self.rows.get(context, {})
            matching = ((word, count) for word, count in row.items()
                        if (word.startswith(prefix) if prefix else True))
            result.update(word for word, _ in heapq.nlargest(32, matching, key=lambda item: (item[1], item[0])))
        return result


@dataclass(frozen=True)
class Suggestion:
    word: str
    kind: str
    source: str
    order: int
    score: float


@dataclass(frozen=True)
class Suggestions:
    start: int
    cursor: int
    items: tuple[Suggestion, ...]


class ContextPredictor:
    def __init__(self, engine: AutocorrectEngine, base: NgramModel,
                 personal: NgramModel | None = None, *, base_label="demo"):
        self.engine = engine
        self.base = base
        self.personal = personal if personal is not None else NgramModel()
        self.base_label = base_label
        self.vocabulary = sorted(w for w in engine.symspell.words if is_word(w))
        self.frequency_total = sum(engine.symspell.words[w] for w in self.vocabulary)

    @lru_cache(maxsize=256)
    def completions(self, prefix: str) -> tuple[str, ...]:
        start = bisect_left(self.vocabulary, prefix)
        stop = bisect_left(self.vocabulary, prefix + chr(0x10ffff))
        return tuple(heapq.nlargest(32, self.vocabulary[start:stop],
                                   key=lambda word: (self.engine.symspell.words[word], word)))

    def suggest(self, text: str, cursor: int | None = None) -> Suggestions:
        cursor = len(text) if cursor is None else cursor
        if not 0 <= cursor <= len(text):
            raise ValueError("Posizione del cursore non valida.")
        return self._suggest(text, cursor, self.base.revision, self.personal.revision)

    @lru_cache(maxsize=128)
    def _suggest(self, text: str, cursor: int, base_revision: int, personal_revision: int) -> Suggestions:
        empty = Suggestions(cursor, cursor, ())
        if len(text) > 16_384:
            return empty
        # Do not replace the left half of a word, a selection, or a structured token.
        if cursor < len(text) and (text[cursor].isalnum() or text[cursor] in "_'’"):
            return empty
        left = text[:cursor]
        tail = re.search(r"\S+$", left)
        raw_prefix = tail.group() if tail else ""
        prefix = normalize(raw_prefix)
        start = tail.start() if tail else cursor
        if prefix and not is_word(prefix):
            if raw_prefix.endswith(tuple(PUNCTUATION)):
                prefix, raw_prefix, start = "", "", cursor
            else:
                return empty
        if len(prefix) > self.engine.policy.max_token_length:
            return empty
        _, previous = scan_text(left[:start])
        history = history_for(previous)
        terms = self.base.candidates(history, prefix) | self.personal.candidates(history, prefix)
        distances = {}
        if prefix:
            terms.update(self.completions(prefix))
            decision = self.engine.evaluate(raw_prefix, limit=32)
            for candidate in decision.candidates:
                # Suggestions may require two edits; choosing them is explicit.
                if candidate.term not in self.engine.protected:
                    terms.add(candidate.term)
                    distances[candidate.term] = candidate.distance
        terms.discard(START)
        if prefix:
            terms.discard(END)
        if not previous:
            terms.discard(END)
        weight = 0.7 if self.personal.has_context(history) else (0.15 if self.personal.totals[()] else 0)
        ranked = []
        for word in sorted(terms):
            frequency = self.engine.symspell.words.get(word, 0) / max(1, self.frequency_total)
            general = (1 - weight) * (0.98 * self.base.probability(word, history) + 0.02 * frequency)
            personal = weight * self.personal.probability(word, history)
            correction = bool(prefix and not word.startswith(prefix))
            distance = distances.get(word, 0) if correction else 0
            score = math.log(max(general + personal, 1e-12)) - 1.8 * distance
            if personal > general:
                source, order = "personale", self.personal.evidence(word, history)
            else:
                order = self.base.evidence(word, history)
                source = self.base_label if order else "frequenza"
            displayed = "." if word == END else word
            if raw_prefix.isupper() and len(raw_prefix) > 1:
                displayed = displayed.upper()
            elif raw_prefix[:1].isupper():
                displayed = displayed[:1].upper() + displayed[1:]
            kind = "fine frase" if word == END else ("correzione" if correction else ("completamento" if prefix else "successiva"))
            ranked.append(Suggestion(displayed, kind, source, order, score))
        ranked.sort(key=lambda item: (-item.score, item.word))
        return Suggestions(start, cursor, tuple(ranked[:3]))


def apply_suggestion(text: str, suggestions: Suggestions, index: int) -> tuple[str, int]:
    if not 0 <= index < len(suggestions.items):
        return text, suggestions.cursor
    item = suggestions.items[index]
    before, after = text[:suggestions.start], text[suggestions.cursor:]
    if item.kind == "fine frase":
        before = before.rstrip()
    elif before and not before[-1].isspace():
        before += " "
    # Reuse existing separators when editing earlier in the line.
    separator = "" if after[:1].isspace() or (after and after[0] in ",.!?;:") else " "
    inserted = before + item.word + separator
    return inserted + after, len(inserted) + (1 if after[:1].isspace() else 0)
