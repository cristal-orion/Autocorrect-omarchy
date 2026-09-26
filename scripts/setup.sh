#!/usr/bin/env bash
set -euo pipefail
root="$(dirname "$(dirname "$(readlink -f "$0")")")"
python3 -m venv "$root/.venv"
"$root/.venv/bin/python" -m pip --disable-pip-version-check install -e "$root"
"$root/.venv/bin/autocorrect-fetch-dictionary"
printf '%s\n' 'Pronto. Esempio: ./autocorrect quesot --json'
