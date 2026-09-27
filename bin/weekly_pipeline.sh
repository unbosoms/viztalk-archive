#!/usr/bin/env bash
# 週次追加のローカル処理。space_list.csv に新しい回の行を足してから実行する。
#
#   ./bin/weekly_pipeline.sh audio    音源DL → faststart → 文字起こし → チャプター抽出 (1回あたり15〜20分)
#   (ここで実況ツイートを収集し bin/merge_tweets.py で tweets/ に取り込む)
#   ./bin/weekly_pipeline.sh finish   音源開始時刻の設定 → R2 アップロード → サイト再ビルド → 状態確認
#
# どの工程も「作成済みはスキップ」なので、途中で止まっても再実行すればよい。
set -eu
cd "$(dirname "$0")/.."

step() { echo; echo "===== $* ====="; }

case "${1:-}" in
audio)
    step "音源ダウンロード"
    ./download_all.sh | grep -v "SKIP" || true
    if ls audio/*.part >/dev/null 2>&1; then
        echo "未完了のダウンロード (.part) があります。再実行してください。"; exit 1
    fi
    step "faststart 化"
    ./remux_faststart.sh
    step "文字起こし (mlx-whisper)"
    ./transcribe_all.sh | grep -E "START|DONE|FAIL" || true
    step "チャプター抽出 (Ollama qwen2.5:7b)"
    if ! curl -s -o /dev/null http://localhost:11434/api/tags; then
        echo "Ollama が起動していません (ollama serve / アプリを起動してください)"; exit 1
    fi
    ./extract_all.sh | grep -vE "SKIP" || true
    ;;
finish)
    step "音源開始時刻 (yt-dlp release_timestamp)"
    python3 bin/set_audio_start.py
    step "R2 アップロード"
    ./bin/upload_audio_r2.sh
    step "サイト再ビルド (ローカル確認用)"
    ./bin/rebuild.sh
    step "状態確認"
    python3 bin/check_status.py --r2
    ;;
*)
    sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
