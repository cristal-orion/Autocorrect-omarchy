"""Inspect Fluency dynamic.lm structure without exporting personal vocabulary.

Supports the version-7 vocabulary / dmap layout observed in the local SwiftKey
export. This is a structural inspector, not a decoder or a model importer.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import subprocess


MAX_BYTES = 32 * 1024 * 1024
ARCHIVE_ROOT = "com.touchtype.swiftkey/dynamic_model_debug"


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.position = 0

    def take(self, size: int) -> bytes:
        if size < 0 or self.position + size > len(self.data):
            raise ValueError("Modello troncato o dimensioni non valide.")
        result = self.data[self.position:self.position + size]
        self.position += size
        return result

    def u32(self) -> int:
        return struct.unpack("<I", self.take(4))[0]

    def u16(self) -> int:
        return struct.unpack("<H", self.take(2))[0]

    def expect(self, value: bytes):
        if self.take(len(value)) != value:
            raise ValueError(f"Struttura non supportata: atteso marcatore {value!r}.")


def chunk(reader: Reader, tag: bytes) -> tuple[bytes, bytes]:
    reader.expect(tag)
    body = Reader(reader.take(reader.u32()))
    header = body.take(body.u32())
    body.expect(tag)
    if len(body.data) - body.position < 4 or not body.data.endswith(tag):
        raise ValueError("Chiusura del blocco non valida.")
    return header, body.data[body.position:-4]


def inspect_model(data: bytes) -> dict:
    if len(data) > MAX_BYTES:
        raise ValueError("Modello troppo grande per questo ispettore (limite 32 MiB).")
    reader = Reader(data)
    reader.expect(b"flue")
    if reader.u32() != len(data) - 8:
        raise ValueError("Dimensione del modello Fluency non coerente.")
    header = reader.take(reader.u32())
    if b"DynamicNgramTermModel" not in header:
        raise ValueError("Il file non dichiara un DynamicNgramTermModel.")
    reader.expect(b"flue")
    vocab_header, vocab_bytes = chunk(reader, b"voca")
    if vocab_header != b"\x08\x07":
        raise ValueError("Versione del vocabolario non supportata (attesa 7).")
    vocab = Reader(vocab_bytes)
    encoded_size = vocab.u32()
    vocab.take(encoded_size)
    vocabulary_slots = vocab.u32()
    lengths = vocab.take(vocabulary_slots)
    if sum(lengths) != encoded_size:
        raise ValueError("Lunghezze del vocabolario non coerenti.")
    # The remaining vocabulary bytes are not decoded or interpreted as text.
    _, tree_bytes = chunk(reader, b"dmap")
    tree = Reader(tree_bytes)
    declared_nodes = tree.u32()
    nodes = 0
    depth = 1
    depths = Counter()
    root_ids = set()
    max_id = 0
    while depth:
        word_id = tree.u16()
        if word_id == 0:
            depth -= 1
            continue
        if word_id >= vocabulary_slots or depth > 16:
            raise ValueError("ID o profondità del trie non supportati.")
        tree.u32()  # Count-like field; no claim about raw keystroke frequencies.
        if depth == 1:
            if word_id in root_ids:
                raise ValueError("Identificativo duplicato al primo livello.")
            root_ids.add(word_id)
        max_id = max(max_id, word_id)
        depths[depth] += 1
        nodes += 1
        if nodes > declared_nodes:
            raise ValueError("Numero di nodi superiore a quello dichiarato.")
        depth += 1
    if nodes != declared_nodes or tree.take(2) != b"\0\0" or tree.position != len(tree_bytes):
        raise ValueError("Conteggio dei nodi o chiusura del trie non coerenti.")
    reader.expect(b"flue")
    if reader.position != len(data):
        raise ValueError("Dati aggiuntivi non interpretati dopo il modello.")
    return {
        "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "format": "Fluency DynamicNgramTermModel", "vocabulary_version": 7,
        "vocabulary_slots": vocabulary_slots, "encoded_vocabulary_bytes": encoded_size,
        "root_identifiers": len(root_ids), "maximum_identifier": max_id,
        "declared_nodes": declared_nodes, "parsed_nodes": nodes,
        "nodes_by_depth": dict(sorted(depths.items())),
        "vocabulary_decoded": False, "ready_for_context_import": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="File dynamic.lm oppure archivio com.touchtype.swiftkey.7z")
    args = parser.parse_args(argv)
    try:
        reports = {}
        if args.source.suffix.lower() == ".7z":
            for name in ("user", "userbackup", "keyboard_delta"):
                member = f"{ARCHIVE_ROOT}/{name}/dynamic.lm"
                result = subprocess.run(["bsdtar", "-xOf", str(args.source), member],
                                        capture_output=True, timeout=30, check=True)
                reports[name] = inspect_model(result.stdout)
        else:
            with args.source.open("rb") as source:
                reports[args.source.name] = inspect_model(source.read(MAX_BYTES + 1))
        print(json.dumps(reports, indent=2, ensure_ascii=False))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(2, f"Errore: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
