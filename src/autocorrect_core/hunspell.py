"""Optional, persistent Hunspell C API binding for recognition only.

No suggestions, learning, subprocess per token, or network access. Instances
are single-threaded, like the standalone engine that owns them.
"""

import codecs
import ctypes
from ctypes.util import find_library
import hashlib
import os
from pathlib import Path
import weakref


DEFAULT_HUNSPELL_DICTIONARY = Path("/usr/share/hunspell/it_IT")


def library_name() -> str:
    for name in ("hunspell-1.7", "hunspell-1.6", "hunspell"):
        found = find_library(name)
        if found:
            return found
    raise ValueError("Libreria Hunspell non trovata. Installa hunspell oppure ometti --hunspell.")


class HunspellValidator:
    def __init__(self, dictionary: Path = DEFAULT_HUNSPELL_DICTIONARY):
        # Append rather than replace a suffix: a dictionary prefix may contain dots.
        aff = Path(str(dictionary) + ".aff").resolve()
        dic = Path(str(dictionary) + ".dic").resolve()
        aff_raw, dic_raw = aff.read_bytes(), dic.read_bytes()
        if not any(line.split()[:1] == [b"SET"] and len(line.split()) >= 2
                   for line in aff_raw.splitlines()):
            raise ValueError(f"Hunspell: direttiva SET mancante in {aff}.")
        first_line = dic_raw.splitlines()[0].removeprefix(b"\xef\xbb\xbf") if dic_raw else b""
        if not first_line.isdigit() or int(first_line) < 1:
            raise ValueError(f"Hunspell: intestazione del dizionario non valida in {dic}.")

        name = library_name()
        lib = ctypes.CDLL(name)
        try:
            lib.Hunspell_create.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
            lib.Hunspell_create.restype = ctypes.c_void_p
            lib.Hunspell_destroy.argtypes = [ctypes.c_void_p]
            lib.Hunspell_destroy.restype = None
            lib.Hunspell_get_dic_encoding.argtypes = [ctypes.c_void_p]
            lib.Hunspell_get_dic_encoding.restype = ctypes.c_char_p
            lib.Hunspell_spell.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            lib.Hunspell_spell.restype = ctypes.c_int
        except AttributeError as error:
            raise ValueError(f"API C Hunspell non disponibile in {name}.") from error
        self._lib = lib
        self._handle = lib.Hunspell_create(os.fsencode(aff), os.fsencode(dic))
        if not self._handle:
            raise ValueError(f"Hunspell: impossibile caricare {dictionary}.")
        self._finalizer = weakref.finalize(self, lib.Hunspell_destroy, self._handle)
        try:
            encoding = lib.Hunspell_get_dic_encoding(self._handle)
            if not encoding:
                raise ValueError("Hunspell: encoding del dizionario assente.")
            self.encoding = codecs.lookup(encoding.decode("ascii")).name
        except (LookupError, ValueError) as error:
            self.close()
            raise ValueError("Hunspell: encoding del dizionario non supportato.") from error
        self.metadata = {
            "backend": "hunspell", "library": name, "encoding": self.encoding,
            "aff_path": str(aff), "dic_path": str(dic),
            "aff_sha256": hashlib.sha256(aff_raw).hexdigest(),
            "dic_sha256": hashlib.sha256(dic_raw).hexdigest(),
        }

    def spell(self, word: str) -> bool:
        if not self._finalizer.alive:
            raise ValueError("Il validatore Hunspell è chiuso.")
        if not word or "\0" in word:
            return False
        try:
            encoded = word.encode(self.encoding)
        except UnicodeEncodeError:
            return False
        return bool(self._lib.Hunspell_spell(self._handle, encoded))

    def close(self):
        self._finalizer()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
