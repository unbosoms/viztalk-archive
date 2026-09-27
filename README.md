# Vizトーク Archive

X (旧Twitter) の Spaces で開催されている **Vizトーク**（データ可視化・Tableau・DATA Saber などをテーマにした週次番組）のアーカイブサイト。

## サイト構成

- **回一覧・詳細** — 全放送の年別グループ + 簡易/カード表示切替
- **チャプター** — Whisper で文字起こし → ローカルLLM (Qwen 2.5) で章立て + タグ抽出
- **実況ツイート同期** — 放送中の #Vizトーク ツイートを音源再生位置と同期表示
- **全文検索** — Pagefind による書き起こし全文検索
- **タグ / スピーカー** ページ、横断ナビゲーション

## リポジトリ構成

```
├── space_list.csv         # マスターデータ (Date, URL, 回数, タイトル, スピーカー)
├── build_site.py          # 静的サイト生成 (メイン)
├── extract_topics.py      # Whisper JSON → chapter/tag 抽出 (via Ollama)
├── clean_transcript.py    # Whisper のハルシネーション除去
├── serve.py               # 開発用HTTPサーバー (Range対応)
├── mockup/                # 生成された静的サイト (CI では ci build → deploy)
├── audio/                 # 音源 (R2にアップロード、Git 非同期)
├── transcripts/           # 文字起こし + chapter JSON
├── tweets/                # 実況tweet JSON
├── bin/                   # ヘルパースクリプト
│   ├── rebuild.sh         # ローカル用サイト再ビルド
│   ├── build_prod.sh      # 本番用ビルド (R2 URL埋込)
│   ├── x-tweet-collector.js  # tweet 収集ブックマークレット
│   └── collect_tweets.py  # Playwright 自動収集 (代替)
└── .github/workflows/     # CI/CD
```

## ローカル開発

```bash
# 初回セットアップ
python3 -m venv .venv
.venv/bin/pip install mlx-whisper playwright  # 文字起こし/tweet収集で使う

# サイト再ビルド
./bin/rebuild.sh

# 開発サーバー起動 (HTTP Range 対応)
python3 serve.py
# → http://localhost:8000
```

## デプロイ

- **音源**: Cloudflare R2 (公開バケット `viztalk-archive-audio`)
- **静的サイト**: Cloudflare Pages
- **CI**: GitHub Actions で `main` push で自動デプロイ

環境変数:
- `AUDIO_BASE_URL` — R2の公開URL (例: `https://pub-xxx.r2.dev`)

## データ生成パイプライン

```
音源 (m4a)
  ↓ mlx-whisper (large-v3-turbo, JST + tuned)
transcripts/xxx.json (raw)
  ↓ clean_transcript.py (ハルシネーション除去)
transcripts/xxx.clean.json
  ↓ extract_topics.py (Ollama + qwen2.5:7b、chapter/tag抽出)
transcripts/xxx.clean.chapters.json
  ↓ build_site.py + Pagefind
mockup/ (デプロイ物)
```

## 新しい回の追加 (週次)

1. `space_list.csv` に行を追加 (Date, スペースURL, 回数, `#Vizトーク 第N回`, `あり`, スピーカー)
2. `./bin/weekly_pipeline.sh audio` — 音源DL → faststart → 文字起こし → チャプター抽出
3. 実況ツイートを収集し `python3 bin/merge_tweets.py <収集したJSON>` で `tweets/` に取り込む
   (ブックマークレット `bin/x-tweet-collector.js` か、Claude in Chrome 用の `bin/x-tweet-collector-claude.js`)
   - X はタブが表示されていないと検索結果の続きを読み込まないので、表示中のタブで実行する
4. `./bin/weekly_pipeline.sh finish` — 音源開始時刻の設定 (`bin/set_audio_start.py`) → R2 アップロード → 再ビルド → `bin/check_status.py`
5. commit / push

実況ツイートと音源の同期には `tweets/*.json` の `audio_start_time_jst` を使う。
`bin/set_audio_start.py` が yt-dlp のメタデータ `release_timestamp` (スペースの実際の開始時刻) を入れる。
未設定の回はツイートの集中開始 -10分 で推定する。

## ライセンス

音源著作権は各出演者に帰属。本アーカイブは主催者陣の許諾を得て運営しています。

削除リクエストは Issue またはメンテナへ。
