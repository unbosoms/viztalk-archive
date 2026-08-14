#!/usr/bin/env bash
# DL完了済みのm4aを順次文字起こし。DL並行中はループで待機。
set -u
cd "$(dirname "$0")"
mkdir -p transcripts
LOG=transcripts/_transcribe.log
: > "$LOG"

INIT_PROMPT="これはVizトークというXスペースの録音です。TableauやDATA Saber、データ可視化について複数人で日本語で会話します。"
DL_PID=${DL_PID:-59482}  # 音声DLプロセスのPID (デフォルトは既知PID)

transcribe_one() {
    local f="$1"
    local stem
    stem=$(basename "$f" .m4a)
    local out_json="transcripts/${stem}.json"
    local clean_json="transcripts/${stem}.clean.json"

    if [ -f "$clean_json" ]; then
        return 2  # already done
    fi
    echo "[$(date '+%H:%M:%S')] START: $stem" | tee -a "$LOG"

    .venv/bin/mlx_whisper \
        --model mlx-community/whisper-large-v3-turbo \
        --language ja \
        --output-format json --output-dir transcripts \
        --condition-on-previous-text False \
        --no-speech-threshold 0.7 \
        --logprob-threshold -0.5 \
        --initial-prompt "$INIT_PROMPT" \
        "$f" >> "$LOG" 2>&1

    if [ ! -f "$out_json" ]; then
        echo "[$(date '+%H:%M:%S')] FAIL (no json): $stem" | tee -a "$LOG"
        return 1
    fi

    python3 clean_transcript.py "$out_json" --out "$clean_json" >> "$LOG" 2>&1
    if [ -f "$clean_json" ]; then
        echo "[$(date '+%H:%M:%S')] DONE: $stem" | tee -a "$LOG"
    else
        echo "[$(date '+%H:%M:%S')] FAIL (clean): $stem" | tee -a "$LOG"
    fi
    return 0
}

while true; do
    for f in audio/*.m4a; do
        [ -e "$f" ] || continue
        # 部分DL中のファイルは .m4a.part になっているので .m4a だけ拾えばOK
        transcribe_one "$f" || true
    done

    if kill -0 "$DL_PID" 2>/dev/null; then
        echo "[$(date '+%H:%M:%S')] wait 60s (DL still running, PID=$DL_PID)" | tee -a "$LOG"
        sleep 60
    else
        echo "[$(date '+%H:%M:%S')] DL finished, one final pass done. EXIT." | tee -a "$LOG"
        break
    fi
done
echo "[$(date '+%H:%M:%S')] === ALL TRANSCRIPTION DONE ===" | tee -a "$LOG"
