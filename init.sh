#!/usr/bin/env bash
# init.sh - Harness session startup script
cd "$(dirname "$0")"

ERRORS=0

echo "=== 1. Environment ==="
if [ ! -d ".venv" ]; then
  echo "[warn] .venv is missing"
  ERRORS=$((ERRORS + 1))
else
  echo "[ok] Found .venv"
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "[warn] .venv/bin/python is missing"
  ERRORS=$((ERRORS + 1))
else
  .venv/bin/python -V || ERRORS=$((ERRORS + 1))
fi

echo "=== 2. Tests ==="
if [ -x ".venv/bin/pytest" ]; then
  .venv/bin/pytest --maxfail=1 >/tmp/nanobot-harness-pytest.log 2>&1
  STATUS=$?
  if [ $STATUS -ne 0 ]; then
    echo "[warn] pytest reported failures; see /tmp/nanobot-harness-pytest.log"
    ERRORS=$((ERRORS + 1))
  else
    echo "[ok] pytest passed"
  fi
else
  echo "[warn] .venv/bin/pytest is missing"
  ERRORS=$((ERRORS + 1))
fi

echo "=== 3. CLI Health ==="
if [ -x ".venv/bin/python" ]; then
  .venv/bin/python -m nanobot.cli.commands --help >/tmp/nanobot-harness-cli.log 2>&1
  STATUS=$?
  if [ $STATUS -ne 0 ]; then
    echo "[warn] CLI health check failed; see /tmp/nanobot-harness-cli.log"
    ERRORS=$((ERRORS + 1))
  else
    echo "[ok] CLI help rendered"
  fi
fi

echo "=== Init complete (errors: $ERRORS) ==="
exit 0
