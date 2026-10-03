#!/usr/bin/env bash
# Full pipeline run over the entire XBRL tree. One filing folder per
# company-year becomes one document; OCR is not used (the source is HTML).
set -u
cd "$(dirname "$0")"
python main.py run --input "./XBRL" --workers 4 > logs/full_run.log 2>&1
echo "EXIT_CODE=$?" >> logs/full_run.log
