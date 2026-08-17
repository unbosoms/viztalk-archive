#!/usr/bin/env python3
"""Vizトーク アーカイブから BI ツール (Tableau等) 用の分析用CSVを生成する。

出力ディレクトリ: analytics/
生成ファイル:
  episodes.csv         ... 1行=1回。日付、時間、各種カウント
  episode_speakers.csv ... 1行=1回×1スピーカー (long format)
  episode_topics.csv   ... 1行=1回×1トピック (long format)
  chapters.csv         ... 1行=1チャプター
  chapter_topics.csv   ... 1行=1チャプター×1トピック

全ファイルは `ep` (+ `date`) を join key として使えます。
"""
import csv
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "space_list.csv"
TRANS_DIR = ROOT / "transcripts"
TWEETS_DIR = ROOT / "tweets"
DURATIONS_PATH = ROOT / "audio" / "_durations.json"
OUT_DIR = ROOT / "analytics"

WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]


def parse_speakers(raw):
    """CSVのスピーカー列を [{role, name, handle}, ...] にパース。"""
    if not raw:
        return []
    result = []
    for group in re.split(r"[;；]\s*", raw):
        m = re.match(r"([^:：]+)[:：]\s*(.+)", group)
        if not m:
            continue
        role = m.group(1).strip()
        rest = m.group(2)
        for entry in re.split(r"[,、]", rest):
            entry = entry.strip()
            mm = re.match(r"(.+?)\(@([\w_]+)\)", entry)
            if mm:
                result.append({
                    "role": role,
                    "name": mm.group(1).strip(),
                    "handle": mm.group(2).strip(),
                })
    return result


def ts_to_sec(ts):
    """'0:01:23' or '1:23' -> 秒 (int)"""
    if not ts:
        return 0
    parts = ts.split(":")
    try:
        parts = [int(x) for x in parts]
    except ValueError:
        return 0
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0]


def load_durations():
    if DURATIONS_PATH.exists():
        return json.loads(DURATIONS_PATH.read_text())
    return {}


def load_episodes():
    """CSVを読んで各回のメタ + chapters + tweets を紐付けた dict のリストを返す。"""
    durations = load_durations()
    episodes = []
    with open(CSV_PATH, newline="") as f:
        for row in csv.DictReader(f):
            title = row.get("タイトル", "")
            m = re.search(r"第(\d+)回", title)
            ep_num = int(m.group(1)) if m else None
            date_str = row["Date"]
            date_yyyymmdd = date_str.replace("-", "")
            recording = row["録音の有無"] == "あり"
            has_rerun = "（再）" in title
            fname_stem = (
                f"{date_yyyymmdd}_第{ep_num}回{'_再' if has_rerun else ''}_Vizトーク"
                if ep_num else None
            )

            chapters_data = None
            if fname_stem:
                ch_path = TRANS_DIR / f"{fname_stem}.clean.chapters.json"
                if ch_path.exists():
                    chapters_data = json.loads(ch_path.read_text())

            tweets_data = None
            if fname_stem:
                tw_path = TWEETS_DIR / f"{date_yyyymmdd}_第{ep_num}回.json"
                if tw_path.exists():
                    tweets_data = json.loads(tw_path.read_text())

            audio_filename = f"{fname_stem}.m4a" if fname_stem else None
            duration_sec = durations.get(audio_filename) if audio_filename else None

            try:
                d = date.fromisoformat(date_str)
                weekday = WEEKDAYS_JP[d.weekday()]
                year = d.year
                month = d.month
            except Exception:
                weekday = ""
                year = None
                month = None

            episodes.append({
                "ep": ep_num,
                "date": date_str,
                "title": title,
                "weekday": weekday,
                "year": year,
                "month": month,
                "recording": recording,
                "url": row.get("URL", ""),
                "speakers": parse_speakers(row.get("スピーカー", "")),
                "duration_sec": duration_sec,
                "chapters_data": chapters_data,
                "tweets_data": tweets_data,
            })
    return episodes


def write_csv(path, headers, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"[done] {path.name}: {len(rows)} 行")


def main():
    OUT_DIR.mkdir(exist_ok=True)
    episodes = load_episodes()

    # --- episodes.csv (fact table) ---
    ep_rows = []
    for ep in episodes:
        if not ep["ep"]:
            continue  # 回番号なしはスキップ
        ch = ep["chapters_data"] or {}
        tw = ep["tweets_data"] or {}
        chapters = ch.get("chapters", []) or []
        topics = ch.get("episode_tags", []) or []
        speakers = ep["speakers"]
        tweets = tw.get("tweets", []) or []
        dur_sec = ep["duration_sec"]
        ep_rows.append({
            "ep": ep["ep"],
            "date": ep["date"],
            "year": ep["year"],
            "month": ep["month"],
            "weekday": ep["weekday"],
            "title": ep["title"],
            "recording": int(ep["recording"]),
            "duration_sec": dur_sec if dur_sec else "",
            "duration_min": round(dur_sec / 60, 1) if dur_sec else "",
            "duration_hour": round(dur_sec / 3600, 2) if dur_sec else "",
            "speaker_count": len(speakers),
            "topic_count": len(topics),
            "chapter_count": len(chapters),
            "tweet_count": len(tweets),
        })
    write_csv(
        OUT_DIR / "episodes.csv",
        headers=[
            "ep", "date", "year", "month", "weekday", "title", "recording",
            "duration_sec", "duration_min", "duration_hour",
            "speaker_count", "topic_count", "chapter_count", "tweet_count",
        ],
        rows=ep_rows,
    )

    # --- episode_speakers.csv (long) ---
    sp_rows = []
    for ep in episodes:
        if not ep["ep"]:
            continue
        for sp in ep["speakers"]:
            sp_rows.append({
                "ep": ep["ep"],
                "date": ep["date"],
                "speaker_name": sp["name"],
                "speaker_handle": sp["handle"],
                "role": sp["role"],
            })
    write_csv(
        OUT_DIR / "episode_speakers.csv",
        headers=["ep", "date", "speaker_name", "speaker_handle", "role"],
        rows=sp_rows,
    )

    # --- episode_topics.csv (long) ---
    tp_rows = []
    for ep in episodes:
        if not ep["ep"]:
            continue
        ch = ep["chapters_data"] or {}
        for topic in ch.get("episode_tags", []) or []:
            tp_rows.append({
                "ep": ep["ep"],
                "date": ep["date"],
                "topic": topic,
            })
    write_csv(
        OUT_DIR / "episode_topics.csv",
        headers=["ep", "date", "topic"],
        rows=tp_rows,
    )

    # --- chapters.csv (1行 = 1 chapter) ---
    ch_rows = []
    for ep in episodes:
        if not ep["ep"]:
            continue
        ch_data = ep["chapters_data"] or {}
        for i, ch in enumerate(ch_data.get("chapters", []) or [], start=1):
            start = ch.get("start", "")
            end = ch.get("end", "")
            start_sec = ts_to_sec(start)
            end_sec = ts_to_sec(end)
            ch_rows.append({
                "ep": ep["ep"],
                "date": ep["date"],
                "chapter_num": i,
                "start_time": start,
                "start_sec": start_sec,
                "end_time": end,
                "end_sec": end_sec,
                "duration_sec": max(0, end_sec - start_sec) if end_sec else "",
                "title": ch.get("title", ""),
                "summary": ch.get("summary", ""),
                "tag_count": len(ch.get("tags", []) or []),
            })
    write_csv(
        OUT_DIR / "chapters.csv",
        headers=[
            "ep", "date", "chapter_num",
            "start_time", "start_sec", "end_time", "end_sec", "duration_sec",
            "title", "summary", "tag_count",
        ],
        rows=ch_rows,
    )

    # --- chapter_topics.csv (long) ---
    ctp_rows = []
    for ep in episodes:
        if not ep["ep"]:
            continue
        ch_data = ep["chapters_data"] or {}
        for i, ch in enumerate(ch_data.get("chapters", []) or [], start=1):
            for topic in ch.get("tags", []) or []:
                ctp_rows.append({
                    "ep": ep["ep"],
                    "date": ep["date"],
                    "chapter_num": i,
                    "start_sec": ts_to_sec(ch.get("start", "")),
                    "topic": topic,
                })
    write_csv(
        OUT_DIR / "chapter_topics.csv",
        headers=["ep", "date", "chapter_num", "start_sec", "topic"],
        rows=ctp_rows,
    )

    print()
    print(f"✅ 全ファイル → {OUT_DIR}/")
    print("Tableau ではまず episodes.csv を主テーブルとして読み込み、")
    print("他ファイルを `ep + date` でリレーションしてください。")


if __name__ == "__main__":
    main()
