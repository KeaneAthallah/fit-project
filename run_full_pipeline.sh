#!/usr/bin/env bash
# Full pipeline run over the entire LAPORAN KEUANGAN tree.
set -u
cd "$(dirname "$0")"
python main.py run --input "./LAPORAN KEUANGAN" --workers 4 > logs/full_run.log 2>&1
echo "EXIT_CODE=$?" >> logs/full_run.log
