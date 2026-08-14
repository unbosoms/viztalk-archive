#!/usr/bin/env bash
# サイト再ビルド: HTMLを生成 → Pagefindインデックスを再構築
set -eu
cd "$(dirname "$0")/.."

echo "==> build_site.py"
python3 build_site.py

echo "==> pagefind (全文検索インデックス)"
./bin/pagefind --site mockup 2>&1 | grep -E "^(Total:|  Indexed|Finished)" || true

echo "==> collect-tweets guide 更新"
python3 bin/build_bookmarklet.py 2>&1 | grep -E "^(\[done\]|\s+対象)" || true

echo "✅ 完了"
