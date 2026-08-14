#!/usr/bin/env bash
# 全 .clean.json に対して extract_topics.py を順次実行
set -u
cd "$(dirname "$0")"
LOG=transcripts/_extract.log
: > "$LOG"

files=(transcripts/*.clean.json)
TOTAL=${#files[@]}
i=0

for f in "${files[@]}"; do
    i=$((i+1))
    stem=$(basename "$f" .clean.json)
    out="transcripts/${stem}.clean.chapters.json"

    if [ -f "$out" ]; then
        echo "[$i/$TOTAL] SKIP (exists): $stem" | tee -a "$LOG"
        continue
    fi

    # 回番号を抽出（例: 20250501_第102回_Vizトーク → 102）
    ep=$(echo "$stem" | grep -oE "第[0-9]+回" | grep -oE "[0-9]+" | head -1)
    ep=${ep:-"?"}

    echo "[$(date '+%H:%M:%S')] [$i/$TOTAL] START: $stem (ep=$ep)" | tee -a "$LOG"

    .venv/bin/python extract_topics.py "$f" --model qwen2.5:7b --ep "$ep" \
        >> "$LOG" 2>&1

    if [ -f "$out" ]; then
        echo "[$(date '+%H:%M:%S')] [$i/$TOTAL] DONE: $stem" | tee -a "$LOG"
    else
        echo "[$(date '+%H:%M:%S')] [$i/$TOTAL] FAIL: $stem" | tee -a "$LOG"
    fi
done

echo "[$(date '+%H:%M:%S')] === ALL EXTRACT DONE ===" | tee -a "$LOG"
