"""Compare unlabelled personal vocabulary without protecting or learning it.

Hunspell recognition is diagnostic, never a ground-truth label. Only explicit
review labels produce false-positive metrics and a proposed protection list.
"""

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from .dictionary import SHA256, default_dictionary
from .engine import AutocorrectEngine, normalize
from .hunspell import DEFAULT_HUNSPELL_DICTIONARY, HunspellValidator
from .prediction import is_word


LABELS = {"unreviewed", "valid", "typo", "uncertain"}


def vocabulary_entries(text: str) -> list[str]:
    # SwiftKey's header uses '# '; the standalone '#' line is a vocabulary entry.
    return list(dict.fromkeys(line for line in text.lstrip("\ufeff").splitlines()
                              if line and not line.startswith("# ")))


def read_labels(path: Path | None, words: set[str]) -> dict[str, str]:
    if path is None:
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Le etichette devono essere una lista JSON come review.json.")
    labels = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("input"), str):
            raise ValueError("Ogni etichetta richiede input e label.")
        word, label = row["input"], row.get("label")
        if word not in words or word in labels or label not in LABELS:
            raise ValueError("Etichetta non valida, duplicata o riferita a una voce estranea al campione.")
        labels[word] = label
    return labels


def aggregate(rows: list[dict]) -> dict:
    baseline = sum(row["baseline"]["action"] == "correct" for row in rows)
    filtered = sum(row["hunspell"]["action"] == "correct" for row in rows)
    valid = [row for row in rows if row.get("label") == "valid"]
    return {
        "cases": len(rows), "baseline_changes": baseline, "hunspell_changes": filtered,
        "changes_blocked_by_hunspell": sum(row["baseline"]["output"] != row["hunspell"]["output"] for row in rows),
        "hunspell_recognized": sum(row["hunspell_recognized"] for row in rows),
        "labels": dict(Counter(row.get("label", "unreviewed") for row in rows)),
        "reviewed_valid_cases": len(valid),
        "baseline_false_changes_on_reviewed_valid": sum(row["baseline"]["action"] == "correct" for row in valid) if valid else None,
        "hunspell_false_changes_on_reviewed_valid": sum(row["hunspell"]["action"] == "correct" for row in valid) if valid else None,
    }


def compare(entries: list[str], baseline: AutocorrectEngine, filtered: AutocorrectEngine,
            labels: dict[str, str] | None = None) -> tuple[dict, list[dict]]:
    labels = labels or {}
    if baseline.word_validator is not None or filtered.word_validator is None:
        raise ValueError("Confronto atteso: baseline senza validatore e variante con Hunspell.")
    if (baseline.dictionary_sha256 != filtered.dictionary_sha256
            or baseline.protected != filtered.protected or baseline.policy != filtered.policy):
        raise ValueError("Le configurazioni devono differire solo per il validatore.")
    variants = defaultdict(list)
    for entry in entries:
        word = normalize(entry)
        if is_word(word):
            variants[word].append(entry)

    def evaluate(word, label="unreviewed"):
        recognized = bool(is_word(normalize(word)) and len(word) <= baseline.policy.max_token_length
                          and filtered.word_validator.spell(normalize(word)))
        return {"input": word, "label": label, "hunspell_recognized": recognized,
                "baseline": baseline.evaluate(word).to_dict(),
                "hunspell": filtered.evaluate(word).to_dict()}

    raw = [evaluate(entry) for entry in entries]
    lexical = [evaluate(word, labels.get(word, "unreviewed")) for word in sorted(variants)]
    unknown = [dict(row, variants=variants[row["input"]]) for row in lexical
               if row["input"] not in baseline.symspell.words]
    # Put potential harmful changes first, but retain all unknowns for review.
    unknown.sort(key=lambda row: (row["baseline"]["action"] != "correct", row["input"]))
    summary = {
        "scope": "Unlabelled learned vocabulary; change counts are NOT false-positive counts until reviewed.",
        "personal_protection_loaded": False,
        "policy": asdict(baseline.policy), "dictionary_sha256": baseline.dictionary_sha256,
        "word_validator": filtered.word_validator.metadata,
        "builtin_protected_count": len(baseline.protected),
        "builtin_protected_sha256": hashlib.sha256("\n".join(sorted(baseline.protected)).encode()).hexdigest(),
        "unknown_overlap_with_builtin_protection": sum(row["input"] in baseline.protected for row in unknown),
        "raw_entries": aggregate(raw),
        "normalized_lexical_entries": aggregate(lexical),
        "unknown_normalized_lexical_entries": aggregate(unknown),
        "unknown_by_hunspell_recognition": {
            name: aggregate([row for row in unknown if row["hunspell_recognized"] == value])
            for name, value in (("recognized", True), ("unrecognized", False))
        },
    }
    return summary, unknown


def write_json(path, payload):
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    path.chmod(0o600)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vocabulary", type=Path)
    parser.add_argument("--dictionary", type=Path)
    parser.add_argument("--hunspell-dictionary", type=Path, default=DEFAULT_HUNSPELL_DICTIONARY)
    parser.add_argument("--labels", type=Path, help="review.json con label valid/typo/uncertain/unreviewed")
    parser.add_argument("--output-dir", type=Path, required=True, help="Cartella nuova per risultati personali")
    args = parser.parse_args(argv)
    try:
        if args.output_dir.exists() or args.output_dir.is_symlink():
            raise ValueError("La cartella di output esiste già: sceglierne una nuova per conservare le revisioni.")
        raw = args.vocabulary.read_bytes()
        entries = vocabulary_entries(raw.decode("utf-8-sig"))
        if not entries:
            raise ValueError("Vocabolario vuoto.")
        dictionary = args.dictionary or default_dictionary()
        # Deliberately avoid cli.load_engine: it also loads the user's protection file.
        baseline = AutocorrectEngine(dictionary)
        if args.dictionary is None and baseline.dictionary_sha256 != SHA256:
            raise ValueError("Checksum del dizionario predefinito non valido.")
        unknown = {normalize(word) for word in entries if is_word(normalize(word))
                   and normalize(word) not in baseline.symspell.words}
        labels = read_labels(args.labels, unknown)
        with HunspellValidator(args.hunspell_dictionary) as validator:
            filtered = AutocorrectEngine(dictionary, word_validator=validator)
            summary, rows = compare(entries, baseline, filtered, labels)
        summary["vocabulary_sha256"] = hashlib.sha256(raw).hexdigest()
        summary["labels_sha256"] = hashlib.sha256(args.labels.read_bytes()).hexdigest() if args.labels else None
        args.output_dir.mkdir(mode=0o700, parents=True)
        write_json(args.output_dir / "summary.json", summary)
        write_json(args.output_dir / "review.json", rows)
        write_json(args.output_dir / "changes.json", [row for row in rows if row["baseline"]["action"] == "correct"])
        protected = args.output_dir / "approved-protected.txt"
        protected.write_text("# Solo voci etichettate valid nella revisione; non installate automaticamente.\n" +
                             "".join(row["input"] + "\n" for row in rows if row["label"] == "valid"), encoding="utf-8")
        protected.chmod(0o600)
        print(f"Risultati locali: {args.output_dir}")
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    except (OSError, ValueError) as error:
        parser.exit(2, f"Errore: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
