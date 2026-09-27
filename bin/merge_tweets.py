#!/usr/bin/env python3
"""収集した実況ツイート JSON を tweets/{ep}_{date}.json にマージする。

X の検索結果は取得のたびに漏れ方が変わるため、既存ファイルと ID で和集合を取る
(同じ ID は新しい方のメトリクスで上書き)。audio_start_time_jst など既存のメタ情報は保持する。

入力形式 (どちらも可、複数ファイル指定可):
  - ブックマークレット形式: {"episode": 145, "date": "2026-09-10", "tweets": [...]}
  - まとめ形式 (bin/x-tweet-collector-claude.js): {"episodes": {"145_2026-09-10": [...], ...}}

  python3 bin/merge_tweets.py ~/Downloads/viztalk_tweets_*.json
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TWEETS_DIR = ROOT / "tweets"
DEFAULT_NOTE = "null の場合はツイート集中の開始 -10分 で自動推定。"


def iter_sets(src):
    if "episodes" in src:
        for key, tweets in src["episodes"].items():
            ep, date = key.split("_", 1)
            yield int(ep), date, tweets
    else:
        yield int(src["episode"]), src["date"], src.get("tweets", [])


def merge(ep, date, tweets, collected_at):
    path = TWEETS_DIR / f"{ep}_{date}.json"
    if path.exists():
        data = json.loads(path.read_text())
    else:
        data = {"episode": ep, "date": date, "collected_at": collected_at,
                "audio_start_time_jst": None, "audio_start_note": DEFAULT_NOTE,
                "tweet_count": 0, "tweets": []}
    old = {t["id"]: t for t in data.get("tweets", [])}
    new = {t["id"]: t for t in tweets if t.get("id")}
    added = [i for i in new if i not in old]
    merged = sorted({**old, **new}.values(), key=lambda t: t.get("posted_at") or "")
    data.update(collected_at=collected_at, tweet_count=len(merged), tweets=merged)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    status = "new" if not old else "update"
    print(f"[{status}] {path.name}: 既存 {len(old)} + 取得 {len(new)} → {len(merged)} 件 (追加 {len(added)})")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    for p in sys.argv[1:]:
        src = json.loads(Path(p).expanduser().read_text())
        collected_at = src.get("collected_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        for ep, date, tweets in iter_sets(src):
            merge(ep, date, tweets, collected_at)


if __name__ == "__main__":
    main()
