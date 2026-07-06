#!/usr/bin/env bash
# Extract all currently missing P3DH reference dates, then run one failed-only cleanup pass per date.
set -euo pipefail

run_date() {
  local date="$1"
  local folder="$2"
  local log="data/p3dh_timeseries_${folder}.log"

  mkdir -p data
  echo "===== START ${date} (${folder}) $(date -Is) =====" | tee -a "$log"
  PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/download_p3dh_robust.py \
    --date "$date" \
    --workers 8 \
    --refresh-minutes 8 \
    --request-delay-ms 100 \
    --max-requests-per-minute 0 \
    --partition-chunk-size 50 \
    --partition-timeout 30 \
    --partition-retries 1 \
    --refresh-discovery \
    --clean \
    >> "$log" 2>&1
  echo "===== PRIMARY END ${date} (${folder}) $(date -Is) =====" | tee -a "$log"

  echo "===== CLEANUP START ${date} (${folder}) $(date -Is) =====" | tee -a "$log"
  PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/download_p3dh_robust.py \
    --date "$date" \
    --workers 8 \
    --refresh-minutes 8 \
    --request-delay-ms 100 \
    --max-requests-per-minute 0 \
    --partition-chunk-size 50 \
    --partition-timeout 30 \
    --partition-retries 1 \
    --resume \
    --failed-only \
    >> "$log" 2>&1
  echo "===== CLEANUP END ${date} (${folder}) $(date -Is) =====" | tee -a "$log"
  echo "===== END ${date} (${folder}) $(date -Is) =====" | tee -a "$log"
}

run_date "30/06/2025" "20250630"
run_date "30/09/2025" "20250930"
run_date "31/10/2025" "20251031"
run_date "31/03/2026" "20260331"
