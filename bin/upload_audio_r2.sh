#!/usr/bin/env bash
# audio/*.m4a のうち R2 にまだ無いものをアップロードし、公開URLで取得できるか確認する。
# 事前に remux_faststart.sh を済ませておくこと (moov 先頭でないとブラウザでシークできない)。
# R2 トークンはバケット作成権限が無いので --s3-no-check-bucket が必須。
set -eu
cd "$(dirname "$0")/.."

REMOTE="r2:viztalk-archive-audio"
PUBLIC_BASE="https://pub-b4ff3b045a444a86b84b02b4a0817e9a.r2.dev"

rclone copy audio/ "$REMOTE" \
    --filter "- *.faststart.m4a" --filter "+ /*_Vizトーク.m4a" --filter "- *" \
    --ignore-existing --s3-no-check-bucket -v 2>&1 | grep -E "Copied|ERROR|Transferred:" || true

echo "==> 公開URLの確認 (ローカルにあってR2の一覧と照合)"
remote_list=$(rclone lsf "$REMOTE" --files-only)
missing=0
for f in audio/*_Vizトーク.m4a; do
    name=$(basename "$f")
    if ! grep -qxF "$name" <<< "$remote_list"; then
        echo "MISSING on R2: $name"
        missing=$((missing+1))
    fi
done
echo "R2: $(wc -l <<< "$remote_list" | tr -d ' ') files, missing $missing"

# 直近3本は公開URLで HEAD 確認
for f in $(ls audio/*_Vizトーク.m4a | sort | tail -3); do
    name=$(basename "$f")
    enc=$(python3 -c "import sys;from urllib.parse import quote;print(quote(sys.argv[1]))" "$name")
    code=$(curl -s -o /dev/null -w "%{http_code}" -I "$PUBLIC_BASE/$enc")
    echo "HTTP $code  $name"
done
[ "$missing" -eq 0 ]
