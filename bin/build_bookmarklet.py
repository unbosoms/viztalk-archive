#!/usr/bin/env python3
"""bin/x-tweet-collector.js をブックマークレット化 + 収集ガイドHTMLを生成する。

出力:
  bin/x-tweet-bookmarklet.txt   ... javascript:... の一行URI (バックアップ用)
  mockup/collect-tweets.html    ... 収集ガイド + ブックマークレット install リンク
"""
import csv
import os
import re
import sys
from datetime import date, timedelta
from urllib.parse import quote
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JS_PATH = ROOT / "bin" / "x-tweet-collector.js"
BM_TXT = ROOT / "bin" / "x-tweet-bookmarklet.txt"
CSV_PATH = ROOT / "space_list.csv"
OUT_HTML = ROOT / "mockup" / "collect-tweets.html"


def minify_js(src):
    """簡易minify: /* */ コメントと余分な空白を削除。
    // 系のコメントを含めないこと（正規表現リテラル内の /\\// を破壊するため）。
    ソースには // コメントを書かず、必要なら /* */ で書く。"""
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.DOTALL)
    src = re.sub(r'\s+', ' ', src).strip()
    return src


def build_bookmarklet(js_src):
    minified = minify_js(js_src)
    return "javascript:" + quote(minified, safe="")


def x_search_url(d):
    until = d + timedelta(days=2)
    q = f"#Vizトーク since:{d.isoformat()} until:{until.isoformat()}"
    return "https://x.com/search?f=live&q=" + quote(q, safe="")


def load_episode_rows():
    rows = []
    with open(CSV_PATH, newline='') as f:
        for row in csv.DictReader(f):
            if row['録音の有無'] != 'あり':
                continue
            m = re.search(r'第(\d+)回', row.get('タイトル', ''))
            if not m: continue
            ep = int(m.group(1))
            try:
                d = date.fromisoformat(row['Date'])
            except ValueError:
                continue
            done = (ROOT / "tweets" / f"{ep}_{d.isoformat()}.json").exists()
            rows.append({"ep": ep, "date": d.isoformat(), "url": x_search_url(d), "done": done})
    rows.sort(key=lambda x: x["date"], reverse=True)  # 新しい順
    return rows


def build_html(bookmarklet, rows):
    items = []
    for r in rows:
        check = "✅" if r["done"] else "◯"
        style = 'style="color:#999;text-decoration:line-through;"' if r["done"] else ""
        items.append(
            f'<li class="ep-item{" done" if r["done"] else ""}">'
            f'<span class="check">{check}</span> '
            f'<span class="date">{r["date"]}</span> '
            f'<span class="epnum">第{r["ep"]}回</span> — '
            f'<a href="{r["url"]}" target="_blank" {style}>X検索を開く ↗</a> '
            f'<code class="hint">{r["ep"]},{r["date"]}</code>'
            f'</li>'
        )
    done_count = sum(1 for r in rows if r["done"])
    total = len(rows)
    items_html = "\n  ".join(items)

    # ブックマークレットは HTML 属性値に入れるため & を &amp; へ (今回は#はquoteされてるので& が主)
    bm_attr = bookmarklet.replace("&", "&amp;").replace('"', "&quot;")

    return f'''<!doctype html>
<html lang="ja"><head>
<meta charset="utf-8">
<title>実況ツイート収集ガイド · Vizトーク</title>
<style>
body {{ font-family: -apple-system, "Hiragino Sans", sans-serif; max-width: 900px; margin: 2em auto; padding: 0 1em; color: #222; line-height: 1.6; }}
h1 {{ border-bottom: 2px solid #333; padding-bottom: .3em; }}
.install-box {{
  background: linear-gradient(135deg, #eef2ff, #ffffff);
  border: 1px solid #c7d7fe;
  border-radius: 12px;
  padding: 24px;
  margin: 20px 0;
}}
.install-box h2 {{ margin-top: 0; }}
.bookmarklet-btn {{
  display: inline-block;
  background: #2563eb;
  color: white !important;
  padding: 12px 24px;
  border-radius: 8px;
  font-weight: 700;
  text-decoration: none;
  margin: 12px 0;
  box-shadow: 0 2px 6px rgba(37,99,235,.3);
}}
.bookmarklet-btn:hover {{ background: #1d4ed8; }}
ol.eps {{ list-style: none; padding-left: 0; }}
.ep-item {{ padding: 6px 8px; border-bottom: 1px solid #eee; display: flex; gap: 10px; align-items: center; }}
.ep-item:hover {{ background: #f5f7fa; }}
.ep-item.done {{ background: #f7fdf7; }}
.check {{ width: 24px; text-align: center; }}
.date {{ font-family: monospace; font-size: 13px; color: #666; }}
.epnum {{ font-weight: 600; }}
code.hint {{
  background: #f5f5f7; padding: 2px 8px; border-radius: 4px;
  font-size: 11px; color: #666; margin-left: auto;
  cursor: pointer;
  user-select: all;
}}
.progress {{
  background: #eef2ff;
  padding: 8px 14px;
  border-radius: 20px;
  display: inline-block;
  font-weight: 600;
  color: #2563eb;
}}
kbd {{
  background: #f0f4f8; border: 1px solid #d0d7de;
  border-radius: 4px; padding: 1px 6px;
  font-family: monospace; font-size: 12px;
}}
</style>
</head><body>

<h1>🎙 Vizトーク 実況ツイート収集ガイド</h1>

<div class="install-box">
  <h2>① ブックマークレットを登録</h2>
  <p>以下のボタンを <strong>ブックマークバーにドラッグ＆ドロップ</strong> してください。</p>
  <a class="bookmarklet-btn" href="{bm_attr}" onclick="alert('このボタンはブックマークバーにドラッグしてください。クリックはしないでください。'); return false;">🐦 Vizトーク実況ツイート抽出</a>
  <p style="font-size:13px;color:#666;">
    ドラッグできない場合: ブックマーク新規作成 → 名前「Vizトーク抽出」→ URL に
    <a href="bin/x-tweet-bookmarklet.txt" download>bin/x-tweet-bookmarklet.txt</a> の内容を貼り付け。
  </p>
</div>

<h2>② 使い方</h2>
<ol>
  <li>下の一覧から未処理の回（◯マーク）の「X検索を開く」をクリック → 新規タブでXが開く</li>
  <li>Xページで <kbd>End</kbd> キーを長押しか、ゆっくり下にスクロール（bookmarklet が自動でも最下部までスクロールします）</li>
  <li>ブックマークバーの <strong>🐦 Vizトーク実況ツイート抽出</strong> をクリック</li>
  <li>プロンプトに <code>ep,date</code>（右の水色コード部分）を貼り付けて OK。URLから日付は自動検出済み、回番号だけ入力でOKな場合も</li>
  <li>自動スクロール + 抽出が走り、完了すると <code>{{ep}}_{{date}}.json</code> が Downloads にダウンロードされます（+ クリップボードにコピー）</li>
  <li>ダウンロードしたJSONを <code>tweets/</code> フォルダに移動</li>
  <li>全部終わったら <code>python3 build_site.py</code> で反映</li>
</ol>

<p style="font-size:13px;background:#fffbea;padding:10px;border-left:3px solid #eab308;border-radius:4px;">
💡 <strong>tips:</strong> Downloads を一気に mv するには <code>mv ~/Downloads/*_*.json tweets/</code>
</p>

<h2>③ 進捗</h2>
<p><span class="progress">{done_count} / {total} 収集済み</span></p>

<h2>④ 回一覧（新しい順）</h2>
<ol class="eps">
  {items_html}
</ol>

<footer style="margin-top:3em;color:#999;font-size:.85em;text-align:center;">
Vizトーク実況ツイート収集ガイド · <a href="index.html">ホームへ</a>
</footer>
</body></html>'''


def main():
    if os.environ.get("PUBLIC_MODE", "").strip() == "1":
        print("[skip] PUBLIC_MODE=1 — collect-tweets guide (maintainer only) は生成しません")
        return
    js_src = JS_PATH.read_text()
    bm = build_bookmarklet(js_src)
    BM_TXT.write_text(bm)
    print(f"[done] bookmarklet ({len(bm)} chars) → {BM_TXT}")

    rows = load_episode_rows()
    html = build_html(bm, rows)
    OUT_HTML.write_text(html)
    done = sum(1 for r in rows if r["done"])
    print(f"[done] guide HTML → {OUT_HTML}")
    print(f"  対象: {len(rows)}, 収集済み: {done}, 残り: {len(rows) - done}")


if __name__ == "__main__":
    main()
