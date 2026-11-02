#!/usr/bin/env bash
# Repo gate: run the API test suite. Exits non-zero if any test fails.
# Bootstraps api/venv (gitignored) from api/requirements.txt.
# The real Google Maps test skips unless GOOGLE_MAPS_API_KEY is set.
set -euo pipefail

cd "$(dirname "$0")/../api"

# Reinstall when requirements.txt changes or a previous install did not finish.
want=$(sha256sum requirements.txt | cut -d' ' -f1)
if [ "$(cat venv/.requirements.sha256 2>/dev/null)" != "$want" ]; then
    [ -x venv/bin/python ] || python3 -m venv venv
    venv/bin/pip install -q -r requirements.txt
    echo "$want" > venv/.requirements.sha256
fi

exec venv/bin/python -m pytest "$@"
