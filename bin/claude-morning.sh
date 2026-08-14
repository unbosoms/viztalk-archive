#!/usr/bin/env bash
# Claude Code に短いプロンプトを投げて 5時間セッションウィンドウを開始する。
# cron から呼ぶことを想定。

set -u

# PATH に homebrew / claude を確実に含める（cron環境は最小構成のため）
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.claude/local:$PATH"

LOG_DIR="$HOME/.claude/wake-log"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/wake-$(date +%Y%m%d).log"

# claude コマンドの場所を確認
CLAUDE_BIN="$(command -v claude || true)"
if [ -z "$CLAUDE_BIN" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: claude command not found in PATH" >> "$LOG_FILE"
    exit 1
fi

MSG="${1:-おはよう}"

echo "----- $(date '+%Y-%m-%d %H:%M:%S') START (msg='$MSG') -----" >> "$LOG_FILE"

# -p (print mode) で 1回だけ実行して終了。トークン消費は最小限。
# 応答は捨てる（サイズ制限のためログはメタのみ残す）
timeout 60 "$CLAUDE_BIN" -p "$MSG" > /dev/null 2>>"$LOG_FILE"
EXIT_CODE=$?

echo "[$(date '+%Y-%m-%d %H:%M:%S')] exit_code=$EXIT_CODE" >> "$LOG_FILE"
exit $EXIT_CODE
