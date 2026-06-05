#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

LOCK_DIR="${TMPDIR:-/tmp}/e_ppr_send_latest.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
	echo "$(date '+%Y-%m-%d %H:%M:%S') send_latest already running; exiting"
	exit 0
fi
trap 'rmdir "$LOCK_DIR"' EXIT

if [[ -x ".venv/bin/python" ]]; then
	PYTHON=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
	PYTHON="$(command -v python3)"
else
	PYTHON="$(command -v python)"
fi

echo "$(date '+%Y-%m-%d %H:%M:%S') checking today's image availability"
"$PYTHON" check_published_dates.py "$@"

echo "$(date '+%Y-%m-%d %H:%M:%S') sending today's papers"
"$PYTHON" main.py send-latest "$@"

echo "$(date '+%Y-%m-%d %H:%M:%S') done"
