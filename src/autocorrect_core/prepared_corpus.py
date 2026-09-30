"""Shared preparation for extra sentence corpora: spelling filter, splits, TRAIN-only counts.

Each corpus keeps its own database and manifest, so callers weight it on its
own. Rebuilding replaces the whole folder; versions are never mixed.
"""

from collections import Counter
import json
from pathlib import Path
import shutil
import tempfile

from .leipzig_corpus import build_counts, digest_file
from .engine import normalize
from .prediction import PUNCTUATION, TRUNCATIONS, sentences_from


KINDS = ("colloquial-llm", "tatoeba-ita")
PREPARED_FILES = ("train.txt", "development.txt", "evaluation.txt", "unigrams.txt", "ngrams.sqlite3")


def filter_sentences(pairs, recognized, stats=None):
    """pairs: (positive id, sentence). Drop any sentence with a word unknown to lexicon/Hunspell.

    Unknown words written with a capital letter in the source (Tom, l'Australia)
    are names, not misspellings: they are tolerated and still counted.
    """
    stats = Counter() if stats is None else stats
    unknown = Counter()
    records = []
    for identifier, sentence in pairs:
        words = [word for segment in sentences_from(sentence) for word in segment]
        names = {normalize(token.strip(PUNCTUATION)) for token in sentence.split()
                 if any(character.isupper() for character in token)}
        missing = [word for word in words if not (word in TRUNCATIONS or recognized(word) or word in names)]
        if not words or missing:
            stats["lines_with_unknown_words"] += 1
            unknown.update(missing)
            continue
        stats["accepted_lines"] += 1
        records.append(f"{identifier}\t{sentence}")
    return records, stats, unknown


def write_prepared(records, destination: Path, manifest_fields: dict, sources: tuple[str, ...]):
    if not records:
        raise ValueError("Nessuna frase utilizzabile dopo il filtro ortografico.")
    if manifest_fields.get("kind") not in KINDS:
        raise ValueError("Tipo di corpus non riconosciuto.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".prepared-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "prepared"
        stage.mkdir()
        result = build_counts(records, stage)
        manifest = {
            "format_version": 1, **manifest_fields,
            "split": {"function": "leipzig_corpus.split_for", "buckets": {"train": "0..79", "development": "80..89", "evaluation": "90..99"}},
            "source_sha256": {name: digest_file(Path(__file__).with_name(name))
                              for name in ("prepared_corpus.py", "leipzig_corpus.py", "prediction.py", *sources)},
            **result,
            "files_sha256": {name: digest_file(stage / name) for name in PREPARED_FILES},
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    if manifest.get("kind") not in KINDS or digest_file(database) != expected:
        raise ValueError(f"Corpus in {directory} diverso dal manifest verificato.")
    model = TrainingNgrams(database)
    model.metadata = {"database_sha256": expected, "kind": manifest["kind"], "scope": manifest["scope"],
                      "accepted_lines": manifest["filter"]["accepted_lines"], "directory": str(directory)}
    return model
