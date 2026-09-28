"""Validated persistent preferences shared by the shell and the engine."""

import json
import os
from pathlib import Path
import tempfile


DEFAULT_SETTINGS = {
    "correction_enabled": True,
    "min_score_margin": 1.3,
    "min_frequency": 5000,
    "use_context": True,
    "learn_enabled": True,
    "suggestions_enabled": False,
}
BOOLEAN_SETTINGS = {"correction_enabled", "use_context", "learn_enabled", "suggestions_enabled"}


def validate_patch(payload):
    if not isinstance(payload, dict) or not payload or not set(payload) <= DEFAULT_SETTINGS.keys():
        raise ValueError("Impostazioni mancanti o non riconosciute.")
    for key, value in payload.items():
        if key in BOOLEAN_SETTINGS:
            if type(value) is not bool:
                raise ValueError(f"{key}: atteso true o false.")
        elif key == "min_frequency":
            if type(value) is not int or not 1000 <= value <= 100000:
                raise ValueError("Frequenza ammessa: un intero da 1000 a 100000.")
        elif type(value) not in (int, float) or not .01 <= value <= 5:
            raise ValueError("Margine ammesso: da 0,01 a 5,00.")
    return dict(payload)


def read_patch(path: Path):
    with path.open("rb") as source:
        raw = source.read(1025)
    if len(raw) > 1024:
        raise ValueError("File impostazioni troppo grande.")
    return validate_patch(json.loads(raw))


def load_settings(path: Path):
    return {**DEFAULT_SETTINGS, **(read_patch(path) if path.exists() else {})}


def write_settings(path: Path, values):
    values = validate_patch(values)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as target:
            temporary = Path(target.name)
            target.write(json.dumps(values, indent=2, allow_nan=False) + "\n")
            target.flush()
            os.fsync(target.fileno())
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
