#!/usr/bin/env python3
"""全回分の X検索URLをHTMLで出力（一覧から順番に開いていく用）。"""
import csv
import re
from datetime import date, timedelta
from urllib.parse import quote
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "space_list.csv"
OUT = ROOT / "mockup" / "collect-tweets.html"

def x_search_url(d):
    until = d + timedelta(days=2)
    q = f"#Vizトーク since:{d.isoformat()} until:{until.isoformat()}"
    return "https://x.com/search?f=live&q=" + quote(q, safe="")


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
        # 既にtweets/{ep}_{date}.json がある回はスキップ
        already = (ROOT / "tweets" / f"{ep}_{d.isoformat()}.json").exists()
        rows.append({"ep": ep, "date": d.isoformat(), "url": x_search_url(d), "done": already})

rows.sort(key=lambda x: x["date"], reverse=True)  # 新しい順

items_html = ""
for r in rows:
    check = "✅" if r["done"] else "◯"
    style = 'style="color:#999;text-decoration:line-through;"' if r["done"] else ""
    items_html += f'''
  <li>
    {check} {r["date"]} 第{r["ep"]}回 —
    <a href="{r["url"]}" target="_blank" {style}>X検索を開く ↗</a>
    <code style="font-size:11px;color:#999;">{r["ep"]},{r["date"]}</code>
  </li>'''

html_out = f'''<!doctype html>
<html lang="ja"><head>
<meta charset="utf-8">
<title>Tweet収集ガイド</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 800px; margin: 2em auto; padding: 0 1em; }}
li {{ padding: 6px 0; border-bottom: 1px solid #eee; }}
code {{ background: #f5f5f7; padding: 2px 5px; border-radius: 3px; }}
.done-count {{ background: #d1f0d1; padding: 2px 8px; border-radius: 10px; }}
</style>
</head><body>
<h1>実況tweet収集ガイド</h1>
<p>各回のリンクを開いて、Xで一番下までスクロール → <code>bin/x-tweet-collector.js</code> を DevTools コンソールで実行 → JSONをコピー → <code>tweets/{{ep}}_{{date}}.json</code> として保存。</p>
<p>プロンプトには<code>右側のコピーしやすい形式（例: 102,2025-05-01）</code>を貼り付けてください。</p>
<p>収集済: <span class="done-count">{sum(1 for r in rows if r["done"])}/{len(rows)}</span></p>
<ol>
{items_html}
</ol>
</body></html>'''

OUT.write_text(html_out)
print(f"[done] wrote {OUT}")
print(f"  対象回: {len(rows)}, 収集済み: {sum(1 for r in rows if r['done'])}")
