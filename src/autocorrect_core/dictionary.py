"""Explicit, checksum-pinned acquisition of the upstream Italian dictionary."""

import argparse
import hashlib
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.request


REVISION = "b8b2905bdea6835b04e9a026a1b83e3210665237"
URL = (f"https://raw.githubusercontent.com/wolfgarbe/SymSpell/{REVISION}/"
       "SymSpell.FrequencyDictionary/it-100k.txt")
SHA256 = "5f746afb7e6ae802872061ef025ce883cfa2a8779780968fa285dfd0907e9cfc"
MAX_BYTES = 4 * 1024 * 1024


def default_dictionary() -> Path:
    root = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    return root / "autocorrect/dictionaries/it-100k.txt"


def validate_download(data: bytes) -> None:
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError("Checksum del dizionario diverso da quello atteso.")


def fetch_dictionary(destination: Path) -> Path:
    if destination.exists():
        validate_download(destination.read_bytes())
        return destination
    with urllib.request.urlopen(URL, timeout=30) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Dizionario oltre la dimensione massima prevista.")
    validate_download(data)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Download is complete and verified before the final path becomes visible.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        # Refuse to overwrite a file created by another process meanwhile.
        try:
            os.link(temporary, destination)
        except FileExistsError:
            validate_download(destination.read_bytes())
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return destination


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Scarica e verifica il dizionario italiano SymSpell.")
    parser.add_argument("--output", type=Path, default=default_dictionary())
    args = parser.parse_args(argv)
    try:
        path = fetch_dictionary(args.output)
    except (OSError, ValueError, urllib.error.URLError) as error:
        parser.exit(2, f"Errore: {error}\n")
    print(f"Dizionario verificato: {path}\nSHA-256: {SHA256}")
    print("Provenienza e condizioni dei dati: docs/DICTIONARIES.md")
    return 0
