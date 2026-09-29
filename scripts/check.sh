#!/usr/bin/env sh
set -eu
python -m py_compile app/*.py
pytest -q
python - <<'PY'
import json
for f in ['n8n/01-event-router.workflow.json','n8n/02-provider-callbacks.workflow.json']:
    json.load(open(f, encoding='utf-8'))
    print('valid JSON:', f)
PY
