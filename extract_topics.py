#!/usr/bin/env python3
"""Whisper JSON transcript から chapter + tags を抽出する（Ollama使用）。

出力構造:
{
  "episode_summary": "番組全体の2-3文要約",
  "chapters": [
    {"start": "HH:MM:SS", "end": "HH:MM:SS",
     "title": "章タイトル", "summary": "1-2文の要約",
     "tags": ["タグ1", "タグ2", ...]}
  ],
  "episode_tags": [chapter.tagsのユニオン],
  ...
}
"""
import json
import sys
import re
import argparse
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/generate"


def chunks_by_time(segments, window_sec=900):
    """Whisperセグメントを ~window_sec (デフォルト15分) 単位でグループ化。"""
    buckets = []
    cur = []
    cur_start = None
    for seg in segments:
        if cur_start is None:
            cur_start = seg["start"]
        cur.append(seg)
        if seg["end"] - cur_start >= window_sec:
            buckets.append(cur)
            cur = []
            cur_start = None
    if cur:
        buckets.append(cur)
    return buckets


def fmt_ts(sec):
    """秒 -> 常に 'H:MM:SS'（1桁時+2桁分+2桁秒）"""
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    return f"{h:d}:{m:02d}:{s:02d}"


def parse_ts(s, chunk_start_sec=None, chunk_end_sec=None):
    """タイムスタンプ文字列を秒に。失敗時はNone。
    LLMが chunk 内 MM:SS を "MM:SS:00" と誤出力するケースにも対処。"""
    if not s:
        return None
    s = str(s).strip()
    parts = s.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    candidates = []
    if len(nums) == 3:
        candidates.append(nums[0] * 3600 + nums[1] * 60 + nums[2])   # H:MM:SS
        candidates.append(nums[0] * 60 + nums[1])                    # MM:SS:00 誤出力 → MM:SSと解釈
    elif len(nums) == 2:
        candidates.append(nums[0] * 60 + nums[1])                    # MM:SS
        candidates.append(nums[0] * 3600 + nums[1] * 60)             # H:MM(:00)
    elif len(nums) == 1:
        candidates.append(nums[0])
    if chunk_start_sec is not None and chunk_end_sec is not None:
        in_range = [c for c in candidates
                    if chunk_start_sec - 5 <= c <= chunk_end_sec + 5]
        if in_range:
            return in_range[0]
    return candidates[0]


def validate_and_normalize_chapter(chapter, chunk_start_sec, chunk_end_sec):
    """chapter の start/end を chunk 範囲に合わせて検証・補正、常に H:MM:SS で書き戻す。"""
    st = parse_ts(chapter.get("start"), chunk_start_sec, chunk_end_sec)
    en = parse_ts(chapter.get("end"), chunk_start_sec, chunk_end_sec)
    if st is None or st < chunk_start_sec - 5 or st > chunk_end_sec + 5:
        st = chunk_start_sec
    if en is None or en < st or en > chunk_end_sec + 5:
        en = chunk_end_sec
    chapter["start"] = fmt_ts(max(0, st))
    chapter["end"] = fmt_ts(max(st, en))
    chapter["_start_sec"] = st
    chapter["_end_sec"] = en
    return chapter


def title_bigrams(s):
    s = re.sub(r"\s+", "", s or "")
    if len(s) < 2:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def title_similarity(a, b):
    ba, bb = title_bigrams(a), title_bigrams(b)
    if not ba or not bb:
        return 0.0
    return len(ba & bb) / len(ba | bb)


def tag_overlap(a_tags, b_tags):
    sa, sb = set(a_tags or []), set(b_tags or [])
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def should_merge(a, b, title_th=0.5, tag_th=0.4):
    ts = title_similarity(a.get("title", ""), b.get("title", ""))
    to = tag_overlap(a.get("tags", []), b.get("tags", []))
    return ts >= title_th or to >= tag_th


def merge_chapters_py(chapters):
    """隣接chapterでタイトル類似 or タグ重複が閾値以上ならマージ。"""
    if not chapters:
        return []
    # 時刻順に並べる（念のため）
    chapters = sorted(chapters, key=lambda c: c.get("_start_sec", 0))
    result = [dict(chapters[0])]
    for ch in chapters[1:]:
        prev = result[-1]
        if should_merge(prev, ch):
            # マージ
            prev["end"] = ch["end"]
            prev["_end_sec"] = ch.get("_end_sec", prev.get("_end_sec"))
            # タイトルは類似度で判断
            if title_similarity(prev.get("title", ""), ch.get("title", "")) < 0.7:
                prev["title"] = f"{prev.get('title', '')} / {ch.get('title', '')}"
            # サマリは連結（重複は簡易除去）
            a_sum = (prev.get("summary") or "").strip()
            b_sum = (ch.get("summary") or "").strip()
            if b_sum and b_sum not in a_sum:
                prev["summary"] = (a_sum + " " + b_sum).strip()
            # タグはユニオン（denylist/aliasは事前正規化済みなので単純結合）
            seen = set()
            merged_tags = []
            for t in (prev.get("tags") or []) + (ch.get("tags") or []):
                if t and t not in seen:
                    seen.add(t)
                    merged_tags.append(t)
            # マージ後は上限を少し緩める(5個)
            prev["tags"] = merged_tags[:5]
        else:
            result.append(dict(ch))
    # デバッグフィールド除去
    for ch in result:
        ch.pop("_start_sec", None)
        ch.pop("_end_sec", None)
    return result


def call_ollama(model, prompt, json_mode=True, num_ctx=8192):
    body_dict = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": num_ctx},
    }
    if json_mode:
        body_dict["format"] = "json"
    body = json.dumps(body_dict).encode()
    req = urllib.request.Request(
        OLLAMA_URL, data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=900) as resp:
        data = json.loads(resp.read())
    return data["response"]


def try_parse_json(text):
    """LLM出力からJSONを抽出。format:jsonでも稀に前後にゴミが付くので保険。"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # コードフェンス除去
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 最初の { から最後の } まで
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


CHUNK_PROMPT = """以下は「Vizトーク」（Tableau・データ可視化・DATA Saberなどをテーマに日本語で複数人が雑談する番組）の書き起こしの一部です。
時間帯: {start} 〜 {end}

この区間の内容を、話題ごとに **1〜4個のchapter** に分割してください。話題が1つなら1chapterでOK。

## 各chapter
- start / end: 書き起こし中の [HH:MM:SS] タイムスタンプから拾う
- title: 10〜20文字の日本語タイトル
- summary: 1〜2文の日本語要約
- tags: **2〜4個** のタグ配列（少なめ推奨）

## タグの付け方（重要）

以下の【推奨タグ集】から選ぶことを最優先。無い話題ならそれに準じた具体タグを付ける。

### Tableau機能
Dynamic Zone Visibility, Tableau Pulse, Viz Extension, Tableau Next, Tableau Prep, Tableau Public, Tableau Cloud, Tableau Server, パラメータアクション, セットアクション, LOD計算, 表計算, ダッシュボードアクション, Ask Data, Explain Data, コンテナ, Tableau新機能, リリースノート

### 生成AI・新技術
生成AI, LLM, Claude, ChatGPT, Copilot, AI画像生成, プロンプトエンジニアリング

### コミュニティ・イベント
Tableau Conference, TC, Iron Viz, Makeover Monday, Workout Wednesday, Viz for Social Good, DATA Saber, Tableau Public Ambassador, ユーザー会, Speed Tableau

### 推し系
推しオーサートーク, 推しViz, 推しダッシュボード

### デザイン論
デザイン論, 配色, カラーパレット, レイアウト, タイポグラフィ, UI/UX, チャートタイプ選択, ミニマルデザイン, ホワイトスペース

### データエンジニアリング
データエンジニアリング, dbt, Snowflake, BigQuery, Databricks, ETL, ELT, データモデリング, データウェアハウス, データレイク

### 語学
英語学習, 英会話, 多言語対応

### ガジェット・趣味
ガジェット, 自作キーボード, 周辺機器, モニター

### チャートタイプ
パンチカードチャート, ペタルチャート, サンキー図, 散布図, サンバースト, ヒートマップ, ゲージチャート

### 番組メタ（他に該当なしなら使う）
雑談, イベント告知, 技術Tips, Viz紹介, ダッシュボード設計

## 絶対に使ってはいけないタグ
- 動作動詞: 「購入」「配布」「着用」「感想」「反省」「呼びかけ」「挑戦」「議論」
- 一過性メタ: 「CM」「挨拶」「締め切り」「計画」「話題」「経過」「説明」「紹介」
- 曖昧すぎ: 「話」「データ」「情報」「その他」「文章読解」
- 番組の終端行為: 「終了」「開始」「締めくくり」
- 長いフリーテキスト風（8文字超えのタグは推奨タグ集にあるものだけOK）

## 書き起こし
{text}

## 出力（JSONのみ、余計な文字を出さない）
{{
  "chapters": [
    {{"start": "HH:MM:SS", "end": "HH:MM:SS", "title": "...", "summary": "...", "tags": ["...", "..."]}}
  ]
}}
"""


# タグ後処理用の denylist と正規化辞書
BAD_TAGS = {
    # 動作動詞
    "購入", "配布", "着用", "挑戦", "感想", "反省", "呼びかけ", "議論",
    # 一過性メタ
    "CM", "挨拶", "締め切り", "計画", "話題", "経過", "説明", "紹介",
    # 曖昧・汎用一般語
    "話", "データ", "情報", "その他", "文章読解", "検討", "仕事", "音楽ボタン",
    # 番組の一部
    "終了", "開始", "締めくくり", "終了挨拶",
    # 誤字・一回限り推定
    "ワークフォロー", "レビューコミュニティ", "飲酒控え", "武老心",
    # 一過性の細かい話題
    "Tシャツ", "グッズ", "フィリピン", "ケーブルオーガナイザー", "インフルエンサー賞",
    # カテゴリ名そのもの（具体タグに絞る）
    "推し系", "推し",
    # 表記ゆれ・不要
    "Viz", "VizTalk", "Vizトーク",
}

TAG_ALIASES = {
    # Tableau製品・機能
    "タブロー": "Tableau",
    "Tableau (タブロー)": "Tableau",
    "データセーバー": "DATA Saber",
    "データセイバー": "DATA Saber",
    "データセーバーマスター": "DATA Saber",
    "ワークアウトウェンズデー": "Workout Wednesday",
    "ワークアウトウェイズ": "Workout Wednesday",
    "ワークアウトウエンズデー": "Workout Wednesday",
    "ワークアウトマンデー": "Workout Wednesday",
    "アイアンビズ": "Iron Viz",
    "メイクオーバーマンデー": "Makeover Monday",
    "メイカオーバーマンデー": "Makeover Monday",
    # Tableau新機能・用語
    "パンケーキチャート": "パンチカードチャート",
    "パンチカード": "パンチカードチャート",
    "ダイナミックゾンビジビリティ": "Dynamic Zone Visibility",
    "ダイナミックゾンビジュプリティ": "Dynamic Zone Visibility",
    "ダイナミックゾンビジュビリティ": "Dynamic Zone Visibility",
    "ダイナミックゾンビジビリティー": "Dynamic Zone Visibility",
    "ダイナミックゾーンビジビリティ": "Dynamic Zone Visibility",
    "ダイナミックゾーンビジュアリティ": "Dynamic Zone Visibility",
    "DZV": "Dynamic Zone Visibility",
    "TC": "Tableau Conference",
    "花びらチャート": "ペタルチャート",
    "円グラフ": "パイチャート",
    "円チャート": "パイチャート",
    # 表記統合（ダッシュボード関連）
    "ダッシュボード": "ダッシュボード設計",
    "ダッシュボード制作": "ダッシュボード設計",
    "ダッシュボードデザイン": "ダッシュボード設計",
    "ダッシュボードレイアウト": "レイアウト",
    # 英会話関連は「英語学習」に統合（英会話は残す）
    "オンライン英会話": "英会話",
    "英会話サービス": "英会話",
    "英会話の反省": "英会話",
    "多言語": "多言語対応",
    "言語学習": "英語学習",
    # 固有名詞誤字
    "ワンシート卿研究会": "ワンシート研究会",
    "データプラスムービー": "Data + Movies",
    "データプラスムービーズ": "Data + Movies",
    "スピーク": "AI英会話スピーク",
    "AIA英会話": "AI英会話スピーク",
    "AIAスピーク": "AI英会話スピーク",
    "ネイティブキャンプ": "英会話",  # サービス名から一般タグに
    "EZトーク": "英会話",
    # 一般カテゴリ統合
    "データ可視化": "Viz紹介",
    "チャートタイプ": "チャートタイプ選択",
}


def title_to_fallback_tag(title):
    """chapter titleから機械的にフォールバックタグを推測。denyされて空になった時用。"""
    t = (title or "").lower()
    keyword_map = [
        ("dashboard|ダッシュボード", "ダッシュボード設計"),
        ("英会話|英語|オンライン英会話", "英語学習"),
        ("パラメータ|parameter", "パラメータアクション"),
        ("dynamic zone|ダイナミックゾ", "Dynamic Zone Visibility"),
        ("workout wednesday|ワークアウトウ", "Workout Wednesday"),
        ("makeover monday|メイクオーバー", "Makeover Monday"),
        ("iron viz|アイアンビズ", "Iron Viz"),
        ("data saber|データセーバー", "DATA Saber"),
        ("tc|tableau conference", "Tableau Conference"),
        ("推し", "推しオーサートーク"),
        ("チャート|chart|グラフ", "チャートタイプ選択"),
        ("キーボード|ガジェット|周辺機器|モニター", "ガジェット"),
        ("ai|生成ai|llm|claude|chatgpt|copilot", "生成AI"),
        ("dbt|snowflake|bigquery|databricks|etl|elt", "データエンジニアリング"),
        ("配色|カラー|color", "配色"),
        ("イベント|conference|セミナー|勉強会", "イベント告知"),
        ("slack", "Slack"),
    ]
    for pat, tag in keyword_map:
        if re.search(pat, t):
            return tag
    return "雑談"


def normalize_tags(tags, max_tags=4):
    """タグをdenylistで除外 + aliasで正規化 + 上限で切る。順序保持。"""
    result = []
    seen = set()
    for t in tags or []:
        if not t:
            continue
        t = t.strip()
        # alias 正規化
        t = TAG_ALIASES.get(t, t)
        # denylist
        if t in BAD_TAGS:
            continue
        # 曖昧語句（末尾一致で除去。例: "英会話の感想" → 感想でマッチ）
        skip = False
        for bad in BAD_TAGS:
            if len(bad) >= 2 and t != bad and (t.endswith(bad) and len(t) <= len(bad) + 4):
                skip = True
                break
        if skip:
            continue
        # 重複除去
        if t in seen:
            continue
        seen.add(t)
        result.append(t)
        if len(result) >= max_tags:
            break
    return result


SUMMARY_PROMPT = """以下は「Vizトーク 第{ep}回」の統合済みchapter一覧です。
これを踏まえて、番組全体の概要を **2〜3文の日本語** で作成してください。タイムスタンプや技術用語はいじらないでください。

## Chapter一覧
{chapters_text}

## 出力（JSONのみ）
{{"episode_summary": "..."}}
"""


def extract_chunk_chapters(chunk, model):
    chunk_start_sec = chunk[0]["start"]
    chunk_end_sec = chunk[-1]["end"]
    start = fmt_ts(chunk_start_sec)
    end = fmt_ts(chunk_end_sec)
    lines = []
    for seg in chunk:
        ts = fmt_ts(seg["start"])
        t = seg["text"].strip()
        if t:
            lines.append(f"[{ts}] {t}")
    text = "\n".join(lines)
    prompt = CHUNK_PROMPT.format(start=start, end=end, text=text)
    resp = call_ollama(model, prompt, json_mode=True)
    parsed = try_parse_json(resp)
    if not parsed:
        print(f"[warn] chunk {start}-{end}: JSON parse failed, raw: {resp[:200]}",
              file=sys.stderr)
        return []
    raw = parsed.get("chapters", []) or []
    # 各chapterのタイムスタンプを検証・正規化（chunk範囲に基づく）
    normalized = []
    for c in raw:
        c = dict(c)
        c = validate_and_normalize_chapter(c, chunk_start_sec, chunk_end_sec)
        tags = normalize_tags(c.get("tags", []))
        # 空タグ対策: title から推測
        if not tags:
            tags = [title_to_fallback_tag(c.get("title", ""))]
        c["tags"] = tags
        normalized.append(c)
    return normalized


def summarize_episode(chapters, ep, model):
    """chapter一覧から番組全体の要約だけをLLMで生成する（タイムスタンプ生成には使わない）。"""
    lines = [f"- [{c['start']}-{c['end']}] {c.get('title', '')}: {c.get('summary', '')}"
             for c in chapters]
    prompt = SUMMARY_PROMPT.format(ep=ep or "?", chapters_text="\n".join(lines))
    resp = call_ollama(model, prompt, json_mode=True)
    parsed = try_parse_json(resp)
    if not parsed:
        return ""
    return parsed.get("episode_summary", "")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("transcript_json", help="Whisper出力の(できれば.clean.)json")
    ap.add_argument("--model", default="qwen2.5:7b", help="Ollamaモデル名")
    ap.add_argument("--ep", default="", help="回番号（プロンプト用）")
    ap.add_argument("--out", default=None, help="出力先。省略時は入力名を .chapters.json に")
    ap.add_argument("--window", type=int, default=900, help="Chunk幅（秒）。デフォ900=15分")
    ap.add_argument("--skip-consolidation", action="store_true",
                    help="最終統合をスキップ（デバッグ用）")
    args = ap.parse_args()

    with open(args.transcript_json) as f:
        data = json.load(f)
    segments = data["segments"]
    chunks = chunks_by_time(segments, args.window)
    print(f"[info] segments={len(segments)} chunks={len(chunks)} model={args.model}",
          file=sys.stderr)

    all_chapters = []
    for i, chunk in enumerate(chunks, 1):
        c_start = fmt_ts(chunk[0]["start"])
        c_end = fmt_ts(chunk[-1]["end"])
        print(f"[info] chunk {i}/{len(chunks)}  {c_start}-{c_end}  segs={len(chunk)}",
              file=sys.stderr)
        try:
            chs = extract_chunk_chapters(chunk, args.model)
            all_chapters.extend(chs)
            titles = ", ".join(c.get("title", "?") for c in chs)
            print(f"[info]   -> {len(chs)} chapters: {titles}", file=sys.stderr)
        except Exception as e:
            print(f"[warn] chunk {i} failed: {e}", file=sys.stderr)

    print(f"[info] total chapters before merge: {len(all_chapters)}",
          file=sys.stderr)

    # Python側で機械的にマージ（LLM任せにしない、タイムスタンプ安全）
    merged = merge_chapters_py(all_chapters)
    print(f"[info] chapters after merge: {len(merged)}", file=sys.stderr)

    # 番組全体の要約だけLLMで生成（タイムスタンプは触らせない）
    if args.skip_consolidation:
        episode_summary = ""
    else:
        try:
            episode_summary = summarize_episode(merged, args.ep, args.model)
        except Exception as e:
            print(f"[warn] summary failed: {e}", file=sys.stderr)
            episode_summary = ""

    final = {"episode_summary": episode_summary, "chapters": merged}

    # 回タグ = 全chapter tagsのユニオン（順序保持）
    seen = set()
    episode_tags = []
    for ch in final.get("chapters", []):
        for t in ch.get("tags", []) or []:
            if t not in seen:
                seen.add(t)
                episode_tags.append(t)

    result = {
        "source": args.transcript_json,
        "model": args.model,
        "episode": args.ep,
        "chunks_processed": len(chunks),
        "raw_chunk_chapters": all_chapters,  # デバッグ用に元も残す
        "episode_summary": final.get("episode_summary", ""),
        "chapters": final.get("chapters", []),
        "episode_tags": episode_tags,
    }

    out = args.out or args.transcript_json.replace(".json", ".chapters.json")
    with open(out, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"[done] wrote {out}", file=sys.stderr)

    # プレビュー
    print(f"\n=== Episode Summary ===")
    print(result["episode_summary"])
    print(f"\n=== Chapters ({len(result['chapters'])}) ===")
    for ch in result["chapters"]:
        tags = ", ".join(ch.get("tags", []) or [])
        print(f"  [{ch.get('start')}-{ch.get('end')}] {ch.get('title')}")
        print(f"    tags: {tags}")
    print(f"\n=== Episode Tags ({len(episode_tags)}) ===")
    print("  " + ", ".join(episode_tags))


if __name__ == "__main__":
    main()
