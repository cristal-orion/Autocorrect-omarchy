"""Transactional local n-gram counts, updated only for confirmed sentences."""

import json
import os
from pathlib import Path
import sqlite3

from .prediction import NgramModel, counts_for, sentences_from


def default_memory() -> Path:
    root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    return root / "autocorrect/personal-ngrams.sqlite3"


class PersonalMemory:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        self.connection = sqlite3.connect(self.path)
        try:
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                if self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise ValueError("Il file SQLite esistente non è una memoria autocorrect.")
                with self.connection:
                    self.connection.execute("CREATE TABLE ngrams (context TEXT, word TEXT, count INTEGER NOT NULL CHECK(count > 0), PRIMARY KEY(context, word))")
                    self.connection.execute("CREATE TABLE metadata (name TEXT PRIMARY KEY, value INTEGER NOT NULL)")
                    self.connection.execute("INSERT INTO metadata VALUES ('sentences', 0)")
                    self.connection.execute("PRAGMA user_version = 1")
            elif version != 1:
                raise ValueError(f"Versione della memoria personale non supportata: {version}.")
            self.model = NgramModel()
            counts = {}
            for context, word, count in self.connection.execute("SELECT context, word, count FROM ngrams"):
                context = json.loads(context)
                if (not isinstance(context, list) or len(context) > 2
                        or not all(isinstance(w, str) for w in context)
                        or not isinstance(word, str) or not isinstance(count, int) or count <= 0):
                    raise ValueError("Conteggi della memoria personale non validi.")
                counts[tuple(context), word] = count
            self.model.add_counts(counts)
            row = self.connection.execute("SELECT value FROM metadata WHERE name='sentences'").fetchone()
            if row is None or not isinstance(row[0], int) or row[0] < 0:
                raise ValueError("Contatore della memoria personale non valido.")
            self.sentence_count = row[0]
        except Exception:
            self.connection.close()
            raise

    def learn(self, text: str) -> int:
        if len(text) > 16_384:
            raise ValueError("La frase supera il limite di 16.384 caratteri.")
        sentences = sentences_from(text)
        if not sentences:
            return 0
        counts = counts_for(sentences)
        with self.connection:
            self.connection.executemany(
                "INSERT INTO ngrams VALUES (?, ?, ?) ON CONFLICT(context, word) DO UPDATE SET count=count+excluded.count",
                [(json.dumps(context, ensure_ascii=False), word, count)
                 for (context, word), count in counts.items()])
            self.connection.execute("UPDATE metadata SET value=value+? WHERE name='sentences'", (len(sentences),))
        self.model.add_counts(counts)
        self.sentence_count += len(sentences)
        return len(sentences)

    def close(self):
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
