"""Deterministic synthetic typo suites; never uses the engine's predictions."""

import argparse
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import tempfile

from .benchmark import load_cases
from .cli import add_engine_arguments, load_personal_words
from .dictionary import default_dictionary, validate_download
from .engine import latin_word, normalize, parse_lexicon, read_protected


GENERATOR_VERSION = 1
LAYOUT = "qwerty-us-letters-v1"
SCOPE = ("Synthetic single-edit typos from dictionary words; word-disjoint development/evaluation "
         "splits. Not real typing, not lemma-disjoint, not a test of unknown valid words.")


def qwerty_neighbors() -> dict[str, tuple[str, ...]]:
    # Letter centers, key-width units; physical approximation, not an error model.
    rows = (("qwertyuiop", 0.0), ("asdfghjkl", 0.25), ("zxcvbnm", 0.75))
    positions = {letter: (column + offset, row)
                 for row, (letters, offset) in enumerate(rows)
                 for column, letter in enumerate(letters)}
    return {letter: tuple(sorted(other for other, (ox, oy) in positions.items()
                                 if other != letter and (x - ox)**2 + (y - oy)**2 <= 1.3**2))
            for letter, (x, y) in positions.items()}


NEIGHBORS = qwerty_neighbors()


@dataclass(frozen=True)
class GenerationConfig:
    seed: int = 42
    words: int = 2000
    typos_per_word: int = 4
    extra_clean_words: int = 4000
    evaluation_percent: int = 20
    min_length: int = 4
    max_length: int = 20

    def __post_init__(self):
        if self.words < 1 or self.extra_clean_words < 0:
            raise ValueError("Servono almeno una parola sorgente e un numero non negativo di parole pulite.")
        if not 1 <= self.typos_per_word <= 20:
            raise ValueError("I typo per parola devono essere tra 1 e 20.")
        if not 1 <= self.evaluation_percent <= 99:
            raise ValueError("La percentuale di valutazione deve essere tra 1 e 99.")
        if not 2 <= self.min_length <= self.max_length <= 32:
            raise ValueError("Lunghezze consentite: da 2 a 32, minimo non superiore al massimo.")


def stable_key(seed: int, purpose: str, value: str) -> bytes:
    return hashlib.sha256(f"{seed}\0{purpose}\0{value}".encode("utf-8")).digest()


def split_for(word: str, config: GenerationConfig) -> str:
    bucket = int.from_bytes(stable_key(config.seed, "split", word)[:8], "big") % 100
    return "evaluation" if bucket < config.evaluation_percent else "development"


def frequency_band(count: int) -> str:
    if count >= 1_000_000:
        return "common"
    if count >= 100_000:
        return "medium"
    return "rare"


def length_band(word: str) -> str:
    return "short" if len(word) <= 6 else "medium" if len(word) <= 10 else "long"


def stratified_sample(words: dict[str, int], count: int, seed: int, purpose: str) -> list[str]:
    if count > len(words):
        raise ValueError(f"Richieste {count} parole, ma ne sono disponibili solo {len(words)}.")
    buckets = defaultdict(list)
    for word, frequency in words.items():
        buckets[(frequency_band(frequency), length_band(word))].append(word)
    queues = [deque(sorted(bucket, key=lambda w: (stable_key(seed, purpose, w), w)))
              for _, bucket in sorted(buckets.items())]
    selected = []
    while len(selected) < count:
        for queue in queues:
            if queue and len(selected) < count:
                selected.append(queue.popleft())
    return selected


def mutations(word: str) -> dict[str, set[str]]:
    """Each output differs by one insertion, deletion, substitution or transpose."""
    variants = {name: set() for name in (
        "transposition", "missing_letter", "extra_letter", "double_letter_missing", "nearby_key")}
    for index, letter in enumerate(word):
        before, after = word[:index], word[index + 1:]
        variants["extra_letter"].add(before + letter + letter + after)
        is_double = (index > 0 and word[index - 1] == letter) or after.startswith(letter)
        variants["double_letter_missing" if is_double else "missing_letter"].add(before + after)
        for neighbor in NEIGHBORS.get(letter, ()):
            variants["nearby_key"].add(before + neighbor + after)
        if after and letter != after[0]:
            variants["transposition"].add(before + after[0] + letter + after[1:])
    for candidates in variants.values():
        candidates.discard(word)
        candidates.discard("")
    return variants


def generate_suite(lexicon: dict[str, int], config: GenerationConfig, *,
                   protected=(), excluded=()) -> tuple[dict[str, list[dict]], dict]:
    # Include all normalized dictionary terms in the collision filter, not just
    # sampled or eligible terms. Preserve accents: cara/carta and e/è matter.
    protected = {normalize(word) for word in protected}
    excluded = {normalize(word) for word in excluded}
    blocked = protected | excluded
    eligible = {word: count for word, count in lexicon.items()
                if config.min_length <= len(word) <= config.max_length
                and latin_word(word) and word == normalize(word) and word not in blocked}
    if config.words + config.extra_clean_words > len(eligible):
        raise ValueError(f"Campione troppo grande: {len(eligible)} parole eleggibili.")
    sources = stratified_sample(eligible, config.words, config.seed, "typo-sources")
    source_set = set(sources)
    extras = stratified_sample({w: c for w, c in eligible.items() if w not in source_set},
                               config.extra_clean_words, config.seed, "extra-clean")
    variants = {}
    owners = {}
    rejected = Counter()
    examples = defaultdict(list)

    def reject(reason, source, typo):
        rejected[reason] += 1
        if len(examples[reason]) < 10:
            examples[reason].append({"source": source, "variant": typo})

    for source in sources:
        variants[source] = {}
        for operation, candidates in mutations(source).items():
            accepted = []
            for typo in sorted(candidates):
                if typo in lexicon:
                    reject("known_dictionary_word", source, typo)
                elif typo in blocked:
                    reject("protected_or_excluded", source, typo)
                else:
                    accepted.append(typo)
                    if typo not in owners:
                        owners[typo] = source
                    elif owners[typo] != source:
                        owners[typo] = None
            variants[source][operation] = accepted

    suites = {"development": [], "evaluation": []}
    no_typos = []
    for source in sources + extras:
        target = suites[split_for(source, config)]
        common = {"source_word": source, "source_frequency": lexicon[source],
                  "frequency_band": frequency_band(lexicon[source]), "length_band": length_band(source)}
        target.append({"input": source, "expected": source, "category": "known_word", **common})
        if source not in source_set:
            continue
        queues = []
        for operation in sorted(variants[source], key=lambda op: stable_key(config.seed, "operation", source + op)):
            candidates = []
            for typo in variants[source][operation]:
                if owners[typo] != source:
                    reject("multiple_sampled_sources", source, typo)
                else:
                    candidates.append(typo)
            queues.append((operation, deque(sorted(candidates, key=lambda typo: stable_key(
                config.seed, "variant", source + "\0" + operation + "\0" + typo)))))
        selected = set()
        while len(selected) < config.typos_per_word and any(queue for _, queue in queues):
            for operation, queue in queues:
                if not queue or len(selected) >= config.typos_per_word:
                    continue
                typo = queue.popleft()
                if typo in selected:
                    continue
                selected.add(typo)
                target.append({"input": typo, "expected": source, "category": operation, **common})
        if not selected:
            no_typos.append(source)

    for name, cases in suites.items():
        cases.sort(key=lambda case: stable_key(config.seed, "case-order", name + "\0" + case["input"]))
    stats = {
        "eligible_words": len(eligible), "typo_source_words": len(sources),
        "extra_clean_words": len(extras), "sources_without_typos": no_typos,
        "rejected_proposals": dict(sorted(rejected.items())),
        "rejected_examples": dict(sorted(examples.items())),
        "splits": {name: {
            "cases": len(cases), "typos": sum(c["input"] != c["expected"] for c in cases),
            "clean_cases": sum(c["input"] == c["expected"] for c in cases),
            "source_words": len({c["source_word"] for c in cases}),
            "categories": dict(sorted(Counter(c["category"] for c in cases).items())),
            "frequency_bands": dict(sorted(Counter(c["frequency_band"] for c in cases).items())),
        } for name, cases in suites.items()},
    }
    return suites, stats


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def write_suite(output: Path, suites: dict, metadata: dict, stats: dict) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError(f"La cartella esiste già, nessun file sovrascritto: {output}")
    if not all(suites.values()):
        raise ValueError("Uno split è vuoto: aumentare il campione prima di esportare.")
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"metadata": metadata, "statistics": stats, "datasets": {}}
    with tempfile.TemporaryDirectory(prefix=".typos-", dir=output.parent) as temporary:
        staged = Path(temporary) / "suite"
        staged.mkdir()
        for name, cases in suites.items():
            payload = encoded({"metadata": {**metadata, "split": name}, "cases": cases})
            (staged / f"{name}.json").write_bytes(payload)
            manifest["datasets"][name] = {"file": f"{name}.json", "sha256": hashlib.sha256(payload).hexdigest()}
        (staged / "manifest.json").write_bytes(encoded(manifest))
        staged.rename(output)
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--words", type=int, default=2000, help="Parole sorgenti dei typo")
    parser.add_argument("--typos-per-word", type=int, default=4)
    parser.add_argument("--extra-clean-words", type=int, default=4000)
    parser.add_argument("--evaluation-percent", type=int, default=20)
    parser.add_argument("--min-length", type=int, default=4)
    parser.add_argument("--max-length", type=int, default=20)
    parser.add_argument("--exclude-cases", type=Path, action="append", default=[], help="Esclude input e target di dataset già usati")
    parser.add_argument("--output-dir", type=Path, default=Path("benchmark-data/it-seed42"))
    add_engine_arguments(parser)
    args = parser.parse_args(argv)
    try:
        config = GenerationConfig(**{key: getattr(args, key) for key in GenerationConfig.__dataclass_fields__})
        if args.output_dir.exists() or args.output_dir.is_symlink():
            raise ValueError(f"Cartella già esistente: {args.output_dir}. Scegliere un nuovo percorso.")
        raw = (args.dictionary or default_dictionary()).read_bytes()
        if args.dictionary is None:
            validate_download(raw)
        lexicon = parse_lexicon(raw)
        protected = read_protected(files("autocorrect_core").joinpath("protected.txt").read_text(encoding="utf-8"))
        protected.update(load_personal_words(args.protected_words))
        excluded = set()
        exclusion_hashes = []
        for path in args.exclude_cases:
            for case in load_cases(path):
                excluded.update((normalize(case["input"]), normalize(case["expected"])))
            exclusion_hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
        suites, stats = generate_suite(lexicon, config, protected=protected, excluded=excluded)
        metadata = {
            "format_version": 1, "kind": "synthetic_typos", "generator_version": GENERATOR_VERSION,
            "scope": SCOPE, "config": asdict(config), "keyboard_layout": LAYOUT,
            "dictionary_sha256": hashlib.sha256(raw).hexdigest(),
            "protected_words_sha256": hashlib.sha256("\n".join(sorted(protected)).encode()).hexdigest(),
            "excluded_dataset_sha256": sorted(exclusion_hashes),
            "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
        write_suite(args.output_dir, suites, metadata, stats)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Errore: {error}\n")
    print(f"Dataset creati in: {args.output_dir}")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
