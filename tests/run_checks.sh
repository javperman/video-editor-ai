#!/usr/bin/env bash
# Comprobaciones locales mínimas del repositorio.
set -euo pipefail
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$BASE"

PY="${PYTHON:-python3}"
if [[ -x .venv/bin/python ]]; then PY=.venv/bin/python; fi

echo "[1/6] esquema JSON"
"$PY" -m json.tool schemas/edit-plan.schema.json >/dev/null

echo "[2/6] compilación Python"
find src scripts -name '*.py' -print0 | xargs -0 "$PY" -m py_compile

echo "[3/5] inspección de fixtures"
if compgen -G "tests/fixtures/spike/*.mp4" >/dev/null; then
  PYTHONPATH=src "$PY" -m video_ai.cli ingest tests/fixtures/spike/screen.mp4 >/dev/null
else
  echo "  (sin fixtures, se omite)"
fi

echo "[4/6] validación del plan de ejemplo"
if [[ -f tests/fixtures/plan.example.json ]]; then
  PYTHONPATH=src "$PY" -m video_ai.plan tests/fixtures/plan.example.json --root .
else
  echo "  (sin plan de ejemplo, se omite)"
fi

echo "[5/6] tests unitarios"
if "$PY" -c "import jsonpatch" 2>/dev/null; then
  PYTHONPATH=src "$PY" -m unittest discover -s tests -p 'test_*.py' >/dev/null
  echo "  OK"
else
  echo "  (faltan dependencias, se omiten)"
fi

echo "[6/6] git status"
git status --short --branch

echo "OK"
