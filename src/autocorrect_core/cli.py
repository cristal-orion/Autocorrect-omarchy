"""Token-oriented CLI. Application context is explicit, never detected here."""

import argparse
import json
import os
from pathlib import Path
import sys

from .dictionary import SHA256, default_dictionary
from .engine import AutocorrectEngine, CONTEXTS, read_protected


def default_personal_words() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return root / "autocorrect/protected.txt"


def add_engine_arguments(parser):
    parser.add_argument("--dictionary", type=Path, help="File UTF-8 parola/frequenza alternativo")
    parser.add_argument("--protected-words", type=Path, help="Lista personale aggiuntiva, una parola per riga")


def load_personal_words(extra: Path | None = None) -> set[str]:
    protected = set()
    personal = default_personal_words()
    for path in (personal, extra):
        if path is not None and (path.exists() or path.is_symlink() or path == extra):
            protected.update(read_protected(path.read_text(encoding="utf-8")))
    return protected


def load_engine(args) -> AutocorrectEngine:
    default = args.dictionary is None
    dictionary = default_dictionary() if default else args.dictionary
    if not dictionary.is_file():
        raise ValueError(f"Dizionario non trovato: {dictionary}. Esegui autocorrect-fetch-dictionary.")
    engine = AutocorrectEngine(dictionary, protected_words=load_personal_words(args.protected_words))
    if default and engine.dictionary_sha256 != SHA256:
        raise ValueError("Checksum del dizionario predefinito non valido; usare --dictionary per dati propri.")
    return engine


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Autocorrect italiano conservativo: una parola per input.")
    parser.add_argument("words", nargs="*")
    parser.add_argument("--stdin", action="store_true", help="Legge un token per riga e mantiene il motore caricato")
    parser.add_argument("--json", action="store_true", help="Una decisione JSON per riga")
    parser.add_argument("--context", choices=CONTEXTS, default="text")
    parser.add_argument("--limit", type=int, default=5)
    add_engine_arguments(parser)
    args = parser.parse_args(argv)
    if bool(args.words) == args.stdin:
        parser.error("Fornisci parole come argomenti oppure --stdin.")
    if not 1 <= args.limit <= 100:
        parser.error("--limit deve essere tra 1 e 100.")
    try:
        engine = load_engine(args)
        tokens = (line.rstrip("\r\n") for line in sys.stdin) if args.stdin else args.words
        for token in tokens:
            result = engine.evaluate(token, context=args.context, limit=args.limit)
            if args.json:
                print(json.dumps(result.to_dict(), ensure_ascii=False, allow_nan=False))
            else:
                print(f"{result.original} → {result.output}  [{result.action}: {result.reason}]")
                if result.candidates:
                    print("candidato\tdistanza\tfrequenza\tscore (non probabilità)")
                    for candidate in result.candidates:
                        print(f"{candidate.term}\t{candidate.distance}\t{candidate.frequency}\t{candidate.score:.4f}")
            sys.stdout.flush()
    except (OSError, ValueError) as error:
        parser.exit(2, f"Errore: {error}\n")
    return 0
