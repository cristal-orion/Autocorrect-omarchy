"""Generated colloquial sentences: spelling filter, deduplicated splits and TRAIN-only counts.

The sentences come from a language model run by the user, not from observed
typing. They supply conversational n-grams missing from the news corpus and
are kept in a separate database, so callers can weight them on their own.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from .dictionary import default_dictionary
from .engine import parse_lexicon
from .hunspell import DEFAULT_HUNSPELL_DICTIONARY, HunspellValidator
from .leipzig_corpus import digest_file
from .prepared_corpus import filter_sentences, load_prepared, write_prepared


KIND = "colloquial-llm"
DEFAULT_RAW = Path("benchmark-data/colloquial-it-llm/raw")
DEFAULT_PREPARED = Path("benchmark-data/colloquial-it-llm/prepared")
MAX_RAW_BYTES = 64 * 1024 * 1024
# Chat transcripts may carry the model's headers, fences or list markers.
NOT_A_SENTENCE = re.compile(r"^(batch\b|```|#|[-*•]\s|\d+[.)]\s)", re.IGNORECASE)

__all__ = ["filter_lines", "load_prepared", "prepare"]


def filter_lines(paths, recognized):
    """Leipzig-style "id<TAB>sentence" records from raw files, one sentence per line."""
    stats = Counter()

    def sentences():
        for path in paths:
            for raw in path.read_text(encoding="utf-8-sig").splitlines():
                line = raw.strip()
                stats["raw_lines"] += 1
                if not line:
                    stats["empty_lines"] += 1
                elif NOT_A_SENTENCE.match(line) or "\t" in line:
                    stats["non_sentence_lines"] += 1
                else:
                    yield line

    return filter_sentences(enumerate(sentences(), 1), recognized, stats)


def prepare(raw_dir: Path, destination: Path, lexicon_path: Path, hunspell_path: Path):
    paths = sorted(p for p in raw_dir.glob("*.txt") if p.is_file())
    if not paths:
        raise ValueError(f"Nessun file .txt in {raw_dir}.")
    if sum(p.stat().st_size for p in paths) > MAX_RAW_BYTES:
        raise ValueError("File generati oltre la dimensione massima prevista.")
    lexicon = parse_lexicon(lexicon_path.read_bytes())
    with HunspellValidator(hunspell_path) as validator:
        records, stats, unknown = filter_lines(paths, lambda word: word in lexicon or validator.spell(word))
    generation = raw_dir.parent / "GENERATION.txt"
    return write_prepared(records, destination, {
        "kind": KIND,
        "sources": {p.name: {"sha256": digest_file(p), "bytes": p.stat().st_size} for p in paths},
        "generation_notes": generation.read_text(encoding="utf-8")[:4096] if generation.is_file() else None,
        "filter": {"rule": "drop header/list lines and any line with a word unknown to the SymSpell lexicon and Hunspell",
                   "lexicon_sha256": digest_file(lexicon_path), **stats, "unknown_words_top": unknown.most_common(50)},
        "scope": "Synthetic conversational text written by a language model. Train counts only; never evidence of real typing quality.",
    }, ("colloquial_corpus.py",))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_PREPARED)
    parser.add_argument("--dictionary", type=Path, default=None)
    parser.add_argument("--hunspell-dictionary", type=Path, default=DEFAULT_HUNSPELL_DICTIONARY)
    args = parser.parse_args(argv)
    try:
        manifest = prepare(args.raw_dir, args.output_dir, args.dictionary or default_dictionary(), args.hunspell_dictionary)
    except (OSError, ValueError) as error:
        parser.exit(2, f"Errore: {error}\n")
    summary = {key: manifest[key] for key in ("statistics", "split_segments", "ngrams")}
    print(json.dumps({"filter": manifest["filter"], **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
