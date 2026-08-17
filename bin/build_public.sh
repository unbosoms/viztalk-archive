#!/usr/bin/env bash
# 公開版 (PUBLIC_MODE=1) をローカルでビルド。
#   - 音源プレーヤー・再生ボタンなし
#   - 実況ツイート本文なし (件数と Xで見る リンクのみ)
#   - 検索インデックスからツイート除外
# Cloudflare Pages 側では PUBLIC_MODE=1 を env var で設定すれば同じ挙動になる。
set -eu
cd "$(dirname "$0")/.."

export PUBLIC_MODE=1

echo "==> build_site.py (PUBLIC_MODE=1)"
python3 build_site.py

echo "==> pagefind (全文検索インデックス)"
./bin/pagefind --site mockup 2>&1 | grep -E "^(Total:|  Indexed|Finished)" || true

echo "==> collect-tweets guide"
python3 bin/build_bookmarklet.py 2>&1

echo "✅ 公開版ビルド完了 (PUBLIC_MODE=1)"
