"""SymSpell candidates plus an explicit abstention policy (not a probability)."""

from dataclasses import asdict, dataclass
import hashlib
from importlib.resources import files
import math
from pathlib import Path
from typing import Protocol
import unicodedata

from symspellpy import SymSpell, Verbosity


CONTEXTS = ("text", "terminal", "password", "url", "email", "code")
APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'"})
ELISION_PREFIXES = ("l", "dell", "all", "dall", "nell", "sull", "coll", "un", "quest", "quell")


def normalize(word: str) -> str:
    return unicodedata.normalize("NFC", word).translate(APOSTROPHES).lower()


def latin_word(word: str) -> bool:
    return bool(word) and all(c.isalpha() and "LATIN" in unicodedata.name(c, "") for c in word)


def read_protected(text: str) -> set[str]:
    return {normalize(line.strip()) for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")}


def parse_lexicon(raw: bytes, max_token_length: int = 64) -> dict[str, int]:
    """Strict dictionary parsing shared with data generation, without indexing."""
    entries = {}
    for number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split()
        if len(parts) != 2:
            raise ValueError(f"Dizionario: riga {number}, attesi parola e frequenza.")
        word, count_text = parts
        try:
            count = int(count_text)
        except ValueError as error:
            raise ValueError(f"Dizionario: frequenza non valida alla riga {number}.") from error
        if not 0 < count <= 2**63 - 1:
            raise ValueError(f"Dizionario: frequenza fuori intervallo alla riga {number}.")
        word = normalize(word)
        if len(word) > max_token_length:
            continue
        entries[word] = min(entries.get(word, 0) + count, 2**63 - 1)
    if not entries:
        raise ValueError("Il dizionario è vuoto.")
    return entries


@dataclass(frozen=True)
class Policy:
    # Fixed initial heuristic, to evaluate rather than fit to the smoke dataset.
    max_edit_distance: int = 2
    max_auto_distance: int = 1
    min_auto_length: int = 5
    max_token_length: int = 64
    min_frequency: int = 100_000
    edit_penalty: float = 2.0
    min_score_margin: float = 1.3

    def __post_init__(self):
        if not 1 <= self.max_edit_distance <= 2:
            raise ValueError("La distanza di ricerca deve essere 1 o 2.")
        if not 1 <= self.max_auto_distance <= self.max_edit_distance:
            raise ValueError("Distanza automatica incompatibile con la ricerca.")
        if not 1 <= self.min_auto_length <= self.max_token_length <= 128:
            raise ValueError("Limiti di lunghezza non validi.")
        if self.min_frequency < 1:
            raise ValueError("La frequenza minima deve essere positiva.")
        if not all(math.isfinite(n) and n > 0 for n in (self.edit_penalty, self.min_score_margin)):
            raise ValueError("Penalità e margine devono essere finiti e positivi.")


@dataclass(frozen=True)
class Candidate:
    term: str
    distance: int
    frequency: int
    score: float


@dataclass(frozen=True)
class Decision:
    original: str
    output: str
    action: str
    reason: str
    candidates: tuple[Candidate, ...] = ()
    candidate_count: int = 0
    score_margin: float | None = None
    # Reserved for a future calibrated model; never invent confidence from score.
    confidence: None = None

    def to_dict(self) -> dict:
        return asdict(self)


class WordValidator(Protocol):
    metadata: dict

    def spell(self, word: str) -> bool: ...


class AutocorrectEngine:
    def __init__(self, dictionary: Path, *, protected_words=(), policy: Policy | None = None,
                 word_validator: WordValidator | None = None):
        self.policy = policy or Policy()
        self.word_validator = word_validator
        self.dictionary_path = Path(dictionary)
        raw = self.dictionary_path.read_bytes()
        self.dictionary_sha256 = hashlib.sha256(raw).hexdigest()
        self.protected = read_protected(files("autocorrect_core").joinpath("protected.txt").read_text(encoding="utf-8"))
        self.protected.update(normalize(w) for w in protected_words)
        self.symspell = SymSpell(max_dictionary_edit_distance=self.policy.max_edit_distance,
                                 prefix_length=7, count_threshold=1)
        entries = parse_lexicon(raw, self.policy.max_token_length)
        for word, count in entries.items():
            self.symspell.create_dictionary_entry(word, count)

    @property
    def word_count(self) -> int:
        return self.symspell.word_count

    def evaluate(self, token: str, *, context: str = "text", limit: int = 5) -> Decision:
        if context not in CONTEXTS:
            raise ValueError(f"Contesto non supportato: {context}")
        if limit < 1:
            raise ValueError("Il limite dei candidati deve essere positivo.")

        def keep(reason):
            return Decision(token, token, "keep", reason)

        if context != "text":
            return keep("disabled_context")
        if len(token) > self.policy.max_token_length:
            return keep("too_long")
        word = normalize(token)
        if not word:
            return keep("empty")
        if word in self.protected:
            return keep("protected_word")
        if word in self.symspell.words:
            return keep("known_word")
        if "'" in word:
            return keep("apostrophe_requires_context")
        if not latin_word(word):
            return keep("non_word")
        if self.word_validator is not None and self.word_validator.spell(word):
            return keep("valid_word")
        # Never turn lacqua into acqua just because elisions are absent upstream.
        for prefix in ELISION_PREFIXES:
            suffix = word[len(prefix):]
            if (word.startswith(prefix) and suffix and suffix[0] in "aeiouàèéìòù"
                    and suffix in self.symspell.words):
                return keep("possible_elision")

        found = self.symspell.lookup(word, Verbosity.ALL, self.policy.max_edit_distance)
        ranked = []
        for item in found:
            # Keep protected dictionary words as competitors, even though they
            # cannot trigger autocorrection; removing them would inflate margins.
            if not latin_word(item.term):
                continue
            score = math.log10(item.count + 1) - self.policy.edit_penalty * item.distance
            ranked.append(Candidate(item.term, item.distance, item.count, score))
        ranked.sort(key=lambda c: (-c.score, c.distance, c.term))
        if not ranked:
            return keep("no_candidate")
        best = ranked[0]
        margin = best.score - ranked[1].score if len(ranked) > 1 else None
        reason = "high_margin"
        if token != token.lower():
            reason = "capitalized_or_mixed_case"
        elif best.term in self.protected:
            reason = "protected_candidate"
        elif len(word) < self.policy.min_auto_length:
            reason = "short_word"
        elif best.distance > self.policy.max_auto_distance:
            reason = "edit_distance"
        elif best.frequency < self.policy.min_frequency:
            reason = "low_frequency"
        elif margin is not None and margin < self.policy.min_score_margin:
            reason = "ambiguous"
        corrected = reason == "high_margin"
        return Decision(token, best.term if corrected else token,
                        "correct" if corrected else "keep", reason,
                        tuple(ranked[:limit]), len(ranked), margin)
