#!/usr/bin/env bash
# Run KiClaw tests with the env vars this host needs, and write a log you can open.
set -euo pipefail
cd "$(dirname "$0")/.."

export PYTHONUNBUFFERED=1
export PYDANTIC_DISABLE_PLUGINS=1
# Required on this host: without it, pytest can hang while scanning plugins.
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
# Prefer source tree so new modules are visible without reinstall.
export PYTHONPATH=src

mkdir -p /Users/nirajrajendranaphade/Documents/kiclaw-demo-results
LOG=/Users/nirajrajendranaphade/Documents/kiclaw-demo-results/pytest-deep-analysis.log

{
  echo "=== analysis import smoke ==="
  .venv/bin/python -u -c "from kiclaw.analysis import run_analysis; print('analysis ok')"

  echo "=== full test suite ==="
  .venv/bin/python -u -m pytest tests/test_core.py -q --tb=line -p no:cacheprovider

  echo "=== CLI analyze smoke ==="
  BOARD="/Applications/KiCad/KiCad.app/Contents/SharedSupport/template/Arduino_Uno/Arduino_Uno.kicad_pcb"
  if [[ -f "$BOARD" ]]; then
    .venv/bin/python -u -m kiclaw analyze "$BOARD" --packs power_tree,ground,protection \
      --output /Users/nirajrajendranaphade/Documents/kiclaw-demo-results/arduino-analysis.json \
      > /tmp/kiclaw-analyze-out.json
    .venv/bin/python -u -c "import json;d=json.load(open('/Users/nirajrajendranaphade/Documents/kiclaw-demo-results/arduino-analysis.json')); print('analyze ok=',d['ok'],'warnings=',d['finding_counts'])"
  else
    echo "Arduino template missing; skip CLI smoke"
  fi

  echo "ALL DONE"
} 2>&1 | tee "$LOG"

echo "Log written to: $LOG"
