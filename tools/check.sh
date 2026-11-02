#!/usr/bin/env bash
# Repo gate: run the API test suite. Exits non-zero if any test fails.
# Bootstraps api/venv (gitignored) from api/requirements.txt on first run.
# The real Google Maps test skips unless GOOGLE_MAPS_API_KEY is set.
set -euo pipefail

cd "$(dirname "$0")/../api"

if [ ! -x venv/bin/python ]; then
    python3 -m venv venv
    venv/bin/pip install -q -r requirements.txt
fi

exec venv/bin/python -m pytest "$@"
