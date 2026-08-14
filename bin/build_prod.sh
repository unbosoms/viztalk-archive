#!/usr/bin/env bash
# 本番URL (R2) を指す形でサイトをビルドする。
# ローカル開発は ./bin/rebuild.sh (AUDIO_BASE_URL 未設定 → mockup/audio シンボリック参照)
# 本番デプロイ用は ./bin/build_prod.sh (このスクリプト、R2 URL を埋め込む)
set -eu
cd "$(dirname "$0")/.."

export AUDIO_BASE_URL="https://pub-b4ff3b045a444a86b84b02b4a0817e9a.r2.dev"

echo "==> build_site.py (AUDIO_BASE_URL=$AUDIO_BASE_URL)"
python3 build_site.py

echo "==> pagefind"
./bin/pagefind --site mockup 2>&1 | grep -E "^(Total:|  Indexed|Finished)" || true

echo "==> collect-tweets guide"
python3 bin/build_bookmarklet.py 2>&1 | grep -E "^(\[done\]|\s+対象)" || true

echo "✅ 本番用ビルド完了 (R2 URL埋め込み)"
