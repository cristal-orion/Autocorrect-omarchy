"""Tatoeba Italian sentences: spelling filter, deduplicated splits and TRAIN-only counts.

Short, mostly conversational sentences written by volunteers for language
learners (CC BY 2.0 FR, attribution: Tatoeba, https://tatoeba.org). The
per-language export changes weekly, so the manifest records the checksum and
date of the file actually used instead of pinning one upstream revision.
"""

import argparse
import bz2
from collections import Counter
from functools import lru_cache
import io
import json
import os
from pathlib import Path
import tempfile
import urllib.request

from .dictionary import default_dictionary
from .engine import parse_lexicon
from .hunspell import DEFAULT_HUNSPELL_DICTIONARY, HunspellValidator
from .leipzig_corpus import digest_file
from .prepared_corpus import filter_sentences, write_prepared


KIND = "tatoeba-ita"
URL = "https://downloads.tatoeba.org/exports/per_language/ita/ita_sentences.tsv.bz2"
LICENSE = {"license": "CC BY 2.0 FR", "attribution": "Tatoeba, https://tatoeba.org",
           "terms": "https://tatoeba.org/en/downloads"}
DEFAULT_ARCHIVE = Path("benchmark-data/tatoeba-ita/ita_sentences.tsv.bz2")
DEFAULT_PREPARED = Path("benchmark-data/tatoeba-ita/prepared")
MAX_BYTES = 64 * 1024 * 1024
MAX_SENTENCE = 2048


def fetch(destination: Path):
    """Download once; later runs reuse the local file and its recorded checksum."""
    if destination.exists():
        return destination, None
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as target:
        temporary = Path(target.name)
        try:
            with urllib.request.urlopen(URL, timeout=60) as response:
                modified = response.headers.get("Last-Modified")
                size = 0
                while block := response.read(1024 * 1024):
                    size += len(block)
                    if size > MAX_BYTES:
                        raise ValueError("Archivio Tatoeba oltre la dimensione massima prevista.")
                    target.write(block)
            target.flush()
            os.fsync(target.fileno())
            temporary.rename(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return destination, modified


def sentences(archive: Path, stats):
    with bz2.open(archive, "rb") as source, io.TextIOWrapper(source, encoding="utf-8") as lines:
        for number, line in enumerate(lines, 1):
            parts = line.rstrip("\r\n").split("\t")
            if len(parts) != 3 or not parts[0].isdigit() or int(parts[0]) < 1 or parts[1] != "ita":
                raise ValueError(f"Tatoeba riga {number}: attesi ID, 'ita' e frase separati da tab.")
            stats["raw_lines"] += 1
            if len(parts[2]) > MAX_SENTENCE:
                stats["oversize_lines"] += 1
                continue
            yield int(parts[0]), parts[2]


def prepare(archive: Path, destination: Path, lexicon_path: Path, hunspell_path: Path, modified=None):
    if archive.stat().st_size > MAX_BYTES:
        raise ValueError("Archivio Tatoeba oltre la dimensione massima prevista.")
    lexicon = parse_lexicon(lexicon_path.read_bytes())
    stats = Counter()
    with HunspellValidator(hunspell_path) as validator:
        recognized = lru_cache(maxsize=None)(lambda word: word in lexicon or validator.spell(word))
        records, stats, unknown = filter_sentences(sentences(archive, stats), recognized, stats)
    return write_prepared(records, destination, {
        "kind": KIND, "url": URL, **LICENSE,
        "archive": {"name": archive.name, "sha256": digest_file(archive), "bytes": archive.stat().st_size,
                    "last_modified": modified},
        "filter": {"rule": "drop any sentence with a word unknown to the SymSpell lexicon and Hunspell",
                   "lexicon_sha256": digest_file(lexicon_path), **stats, "unknown_words_top": unknown.most_common(50)},
        "scope": "Volunteer-written learner sentences: conversational but not chat; frequent stock names (Tom, Mary). Train counts only.",
    }, ("tatoeba_corpus.py",))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE, help="Scaricato se assente")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_PREPARED)
    parser.add_argument("--dictionary", type=Path, default=None)
    parser.add_argument("--hunspell-dictionary", type=Path, default=DEFAULT_HUNSPELL_DICTIONARY)
    args = parser.parse_args(argv)
    try:
        archive, modified = fetch(args.archive)
        manifest = prepare(archive, args.output_dir, args.dictionary or default_dictionary(),
                           args.hunspell_dictionary, modified)
    except (OSError, ValueError, EOFError) as error:
        parser.exit(2, f"Errore: {error}\n")
    summary = {key: manifest[key] for key in ("archive", "filter", "statistics", "split_segments", "ngrams")}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
