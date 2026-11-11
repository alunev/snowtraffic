#!/usr/bin/env bash
# Repo gate: run the API test suite. Exits non-zero if any test fails.
# Bootstraps api/venv (gitignored) from api/requirements.txt.
# The real Google Maps test skips unless GOOGLE_MAPS_API_KEY is set.
set -euo pipefail

cd "$(dirname "$0")/../api"

# Reinstall when requirements.txt changes or a previous install did not finish.
want=$(sha256sum requirements.txt | cut -d' ' -f1)
if [ "$(cat venv/.requirements.sha256 2>/dev/null)" != "$want" ]; then
    # Build the venv with python3.12, what the VPS runs; python3 is the fallback.
    # A venv without pip is a failed earlier build (e.g. python3 3.14 with no
    # ensurepip): remove it and build again.
    if [ ! -x venv/bin/pip ]; then
        py=$(command -v python3.12 || command -v python3) \
            || { echo "check.sh: neither python3.12 nor python3 is on PATH" >&2; exit 1; }
        rm -rf venv
        if ! "$py" -m venv venv >/dev/null 2>&1; then
            rm -rf venv
            echo "check.sh: $py cannot create a venv (no ensurepip?); install python3.12-venv" >&2
            exit 1
        fi
    fi
    venv/bin/pip install -q -r requirements.txt
    echo "$want" > venv/.requirements.sha256
fi

exec venv/bin/python -m pytest "$@"
