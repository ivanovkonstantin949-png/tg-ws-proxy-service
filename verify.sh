#!/bin/sh
# Run with a Python environment containing the runtime + test requirements.
set -eu
cd "$(dirname "$0")"
PYTHON=${PYTHON:-python3}
mkdir -p .scratch/tmp
export TMPDIR="$PWD/.scratch/tmp"
"$PYTHON" -m compileall -q proxy windows_service.py tests
"$PYTHON" -m py_compile packaging/service.spec packaging/service_version.txt
"$PYTHON" -m pytest tests -q
case "$(uname -s)" in
  Darwin|Linux) "$PYTHON" tests/smoke_cli.py ;;
  *) echo 'CLI SIGINT smoke needs macOS/Linux; Windows MSI acceptance: tests/windows-msi-smoke.ps1' ;;
esac
git diff --check
