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
import shutil
import tempfile

from .dictionary import default_dictionary
from .engine import parse_lexicon
from .hunspell import DEFAULT_HUNSPELL_DICTIONARY, HunspellValidator
from .leipzig_corpus import digest_file, build_counts
from .prediction import sentences_from


KIND = "colloquial-llm"
DEFAULT_RAW = Path("benchmark-data/colloquial-it-llm/raw")
DEFAULT_PREPARED = Path("benchmark-data/colloquial-it-llm/prepared")
MAX_RAW_BYTES = 64 * 1024 * 1024
# Chat transcripts may carry the model's headers, fences or list markers.
NOT_A_SENTENCE = re.compile(r"^(batch\b|```|#|[-*•]\s|\d+[.)]\s)", re.IGNORECASE)


def filter_lines(paths, recognized):
    """Yield Leipzig-style "id<TAB>sentence" records; drop any line with an unknown word."""
    stats, unknown = Counter(), Counter()
    records = []
    for path in paths:
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            stats["raw_lines"] += 1
            if not line:
                stats["empty_lines"] += 1
                continue
            if NOT_A_SENTENCE.match(line) or "\t" in line:
                stats["non_sentence_lines"] += 1
                continue
            words = [word for segment in sentences_from(line) for word in segment]
            missing = [word for word in words if not recognized(word)]
            if not words or missing:
                stats["lines_with_unknown_words"] += 1
                unknown.update(missing)
                continue
            stats["accepted_lines"] += 1
            records.append(f"{len(records) + 1}\t{line}")
    return records, stats, unknown


def prepare(raw_dir: Path, destination: Path, lexicon_path: Path, hunspell_path: Path):
    paths = sorted(p for p in raw_dir.glob("*.txt") if p.is_file())
    if not paths:
        raise ValueError(f"Nessun file .txt in {raw_dir}.")
    if sum(p.stat().st_size for p in paths) > MAX_RAW_BYTES:
        raise ValueError("File generati oltre la dimensione massima prevista.")
    lexicon = parse_lexicon(lexicon_path.read_bytes())
    with HunspellValidator(hunspell_path) as validator:
        records, stats, unknown = filter_lines(paths, lambda word: word in lexicon or validator.spell(word))
    if not records:
        raise ValueError("Nessuna frase utilizzabile dopo il filtro ortografico.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".colloquial-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "prepared"
        stage.mkdir()
        result = build_counts(records, stage)
        generation = raw_dir.parent / "GENERATION.txt"
        manifest = {
            "format_version": 1, "kind": KIND,
            "sources": {p.name: {"sha256": digest_file(p), "bytes": p.stat().st_size} for p in paths},
            "generation_notes": generation.read_text(encoding="utf-8")[:4096] if generation.is_file() else None,
            "filter": {"rule": "drop header/list lines and any line with a word unknown to the SymSpell lexicon and Hunspell",
                       "lexicon_sha256": digest_file(lexicon_path), **stats,
                       "unknown_words_top": unknown.most_common(50)},
            "split": {"function": "leipzig_corpus.split_for", "buckets": {"train": "0..79", "development": "80..89", "evaluation": "90..99"}},
            "scope": "Synthetic conversational text written by a language model. Train counts only; never evidence of real typing quality.",
            "source_sha256": {name: digest_file(Path(__file__).with_name(name))
                              for name in ("colloquial_corpus.py", "leipzig_corpus.py", "prediction.py")},
            **result,
            "files_sha256": {name: digest_file(stage / name) for name in (
                "train.txt", "development.txt", "evaluation.txt", "unigrams.txt", "ngrams.sqlite3")},
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Rebuilt whenever the raw files grow: swap the whole folder, never mix versions.
        retired = Path(temporary) / "retired"
        if destination.exists():
            destination.rename(retired)
        stage.rename(destination)
        if retired.exists():
            shutil.rmtree(retired)
    return manifest


def load_prepared(directory: Path):
    from .contextual import TrainingNgrams
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    database = directory / "ngrams.sqlite3"
    expected = manifest["files_sha256"]["ngrams.sqlite3"]
    if manifest.get("kind") != KIND or digest_file(database) != expected:
        raise ValueError("Corpus colloquiale diverso dal manifest verificato.")
    model = TrainingNgrams(database)
    model.metadata = {"database_sha256": expected, "kind": KIND, "scope": manifest["scope"],
                      "accepted_lines": manifest["filter"]["accepted_lines"]}
    return model


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
