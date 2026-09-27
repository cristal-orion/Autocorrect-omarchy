"""Pinned Leipzig news sample; deduplicated splits and exact training n-gram counts."""

import argparse
from collections import Counter
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import urllib.request

from .prediction import END, counts_for, sentences_from


CORPUS = "ita_news_2023_100K"
URL = f"https://downloads.wortschatz-leipzig.de/corpora/{CORPUS}.tar.gz"
SHA256 = "5db4079d208b80a1cab4fed9f2995bbc1433c32edad99d00d5b0e79d006e6869"
MAX_BYTES = 64 * 1024 * 1024
SPLIT_SEED = "autocorrect-leipzig-v1"
LICENSE_STATUS = {
    "status": "unverified_for_this_archive",
    "checked_on": "2026-09-27",
    "usage_url": "https://wortschatz.uni-leipzig.de/en/usage",
    "download_page": "https://wortschatz.uni-leipzig.de/en/download/Italian",
    "finding": "Website serves an Anubis browser challenge; archive metadata contains no license notice. No license inferred from the AOSP wordlist.",
}


def digest_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def fetch_archive(destination: Path):
    if destination.exists():
        if digest_file(destination) != SHA256:
            raise ValueError("Checksum archivio Leipzig esistente non valido.")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as target:
            temporary = Path(target.name)
            digest = hashlib.sha256()
            size = 0
            with urllib.request.urlopen(URL, timeout=60) as response:
                while block := response.read(1024 * 1024):
                    size += len(block)
                    if size > MAX_BYTES:
                        raise ValueError("Archivio oltre la dimensione massima prevista.")
                    target.write(block)
                    digest.update(block)
            target.flush()
            os.fsync(target.fileno())
        if digest.hexdigest() != SHA256:
            raise ValueError("Checksum del download Leipzig non valido.")
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if digest_file(destination) != SHA256:
                raise ValueError("Archivio concorrente con checksum non valido.")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def split_for(normalized_sentence: str) -> str:
    digest = hashlib.sha256((SPLIT_SEED + "\0" + normalized_sentence).encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") % 100
    return "train" if bucket < 80 else ("development" if bucket < 90 else "evaluation")


def build_counts(lines, directory: Path):
    """Split normalized tokenizer segments BEFORE counting; never bridge a boundary."""
    counters = Counter()
    splits = Counter()
    ids, seen = set(), set()
    pending = Counter()
    database = directory / "ngrams.sqlite3"
    with ExitStack() as stack:
        files = {name: stack.enter_context((directory / f"{name}.txt").open("x", encoding="utf-8"))
                 for name in ("train", "development", "evaluation")}
        connection = sqlite3.connect(database)
        stack.callback(connection.close)
        connection.execute("CREATE TABLE ngrams (n INTEGER NOT NULL, c1 TEXT NOT NULL, c2 TEXT NOT NULL, "
                           "word TEXT NOT NULL, count INTEGER NOT NULL CHECK(count > 0), "
                           "PRIMARY KEY(n,c1,c2,word)) WITHOUT ROWID")

        def flush():
            rows = []
            for (context, word), count in pending.items():
                c1, c2 = (("", "") + context)[-2:]
                rows.append((len(context) + 1, c1, c2, word, count))
            with connection:
                connection.executemany("INSERT INTO ngrams VALUES (?,?,?,?,?) "
                                       "ON CONFLICT(n,c1,c2,word) DO UPDATE SET count=count+excluded.count", rows)
            pending.clear()

        for number, line in enumerate(lines, 1):
            parts = line.rstrip("\r\n").split("\t", 1)
            if len(parts) != 2 or not parts[0].isdigit() or int(parts[0]) < 1:
                raise ValueError(f"Leipzig riga {number}: attesi ID positivo e frase separati da tab.")
            if parts[0] in ids:
                raise ValueError(f"Leipzig riga {number}: ID duplicato.")
            ids.add(parts[0])
            counters["source_records"] += 1
            if len(parts[1]) > 16384:
                counters["oversize_records"] += 1
                continue
            segments = sentences_from(parts[1])
            if not segments:
                counters["records_without_usable_words"] += 1
            for words in segments:
                counters["tokenizer_segments"] += 1
                normalized = " ".join(words)
                fingerprint = hashlib.sha256(normalized.encode("utf-8")).digest()
                if fingerprint in seen:
                    counters["duplicate_segments"] += 1
                    continue
                seen.add(fingerprint)
                split = split_for(normalized)
                files[split].write(normalized + "\n")
                splits[split] += 1
                if split == "train":
                    counters["training_word_tokens"] += len(words)
                    pending.update(counts_for([words]))
                    if splits[split] % 1000 == 0:
                        flush()
            if counters["source_records"] % 20000 == 0:
                print(f"Frasi sorgente lette: {counters['source_records']}", flush=True)
        if not counters["source_records"] or not splits["train"]:
            raise ValueError("Corpus senza dati di training utilizzabili.")
        flush()
        ngrams = {str(n): {"types": types, "occurrences": occurrences}
                  for n, types, occurrences in connection.execute("SELECT n,COUNT(*),SUM(count) FROM ngrams GROUP BY n")}
        with (directory / "unigrams.txt").open("x", encoding="utf-8") as output:
            output.write("# Actual occurrence counts in the normalized, deduplicated TRAIN split only.\n")
            for word, count in connection.execute("SELECT word,count FROM ngrams WHERE n=1 AND word<>? ORDER BY word", (END,)):
                output.write(f"{word} {count}\n")
    return {"statistics": dict(counters), "split_segments": dict(splits), "ngrams": ngrams}


def prepare_corpus(archive: Path, destination: Path):
    if destination.exists():
        raise ValueError("La cartella di output esiste già; usare una nuova destinazione.")
    if archive.stat().st_size > MAX_BYTES or digest_file(archive) != SHA256:
        raise ValueError("Checksum o dimensione dell'archivio Leipzig non validi.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".leipzig-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        with tarfile.open(archive, "r:gz") as bundle:
            members = {member.name: member for member in bundle.getmembers()}
            if len(members) != len(bundle.getmembers()):
                raise ValueError("Archivio con nomi di file duplicati.")
            sentence_name = f"{CORPUS}/{CORPUS}-sentences.txt"
            meta_name = f"{CORPUS}/{CORPUS}-meta.txt"
            for name in (sentence_name, meta_name):
                member = members.get(name)
                if member is None or not member.isfile() or not 0 < member.size <= MAX_BYTES:
                    raise ValueError(f"Membro assente o non regolare: {name}")
            # Stream two named regular files, never extract paths or links.
            with bundle.extractfile(members[meta_name]) as source:
                notice = source.read()
            (stage / "source-meta.txt").write_bytes(notice)
            with bundle.extractfile(members[sentence_name]) as source:
                with io.TextIOWrapper(source, encoding="utf-8-sig") as sentences:
                    result = build_counts(sentences, stage)
        manifest = {
            "format_version": 1, "corpus": CORPUS, "url": URL, "archive_sha256": SHA256,
            "source_metadata": notice.decode("utf-8"), "license_verification": LICENSE_STATUS,
            "tokenizer": "prediction.sentences_from: NFC, lowercase, normalized apostrophes; structured tokens interrupt sequences",
            "split": {"unit": "unique normalized tokenizer segment", "seed": SPLIT_SEED,
                      "buckets": {"train": "0..79", "development": "80..89", "evaluation": "90..99"},
                      "method": "SHA-256(seed + NUL + segment), first 8 bytes big endian modulo 100",
                      "caveat": "Not separated by news article, source website, lemma, or semantic near-duplicate. Evaluation is reserved."},
            "counts": "All observed training unigrams, bigrams and trigrams including sentence-boundary markers; no top-k pruning.",
            "scope": "News-domain preparation, not proof of conversational prediction quality. Counts depend on tokenization and deduplication.",
            "source_sha256": {name: digest_file(Path(__file__).with_name(name)) for name in ("leipzig_corpus.py", "prediction.py")},
            **result,
            "files_sha256": {name: digest_file(stage / name) for name in (
                "train.txt", "development.txt", "evaluation.txt", "unigrams.txt", "ngrams.sqlite3", "source-meta.txt")},
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        stage.rename(destination)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--archive", type=Path, help="Archivio locale con lo stesso checksum fissato")
    args = parser.parse_args(argv)
    try:
        if args.output_dir.exists():
            raise ValueError("La cartella di output esiste già; usare una nuova destinazione.")
        archive = args.archive or fetch_archive(args.output_dir.parent / "leipzig-downloads" / f"{CORPUS}.tar.gz")
        manifest = prepare_corpus(archive, args.output_dir)
    except (OSError, ValueError, tarfile.TarError, sqlite3.Error) as error:
        parser.exit(2, f"Errore: {error}\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
