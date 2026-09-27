#!/usr/bin/env python3
"""tweets/{ep}_{date}.json の audio_start_time_jst を X スペースの開始時刻で埋める。

yt-dlp のメタデータ release_timestamp (スペースの実際の開始時刻 = 録音の開始) を使う。
timestamp はスペース作成時刻で、予約・待機があると開始より早いので使わない。

  python3 bin/set_audio_start.py            # 未設定 (null) の回だけ埋める
  python3 bin/set_audio_start.py --ep 147   # 特定回
  python3 bin/set_audio_start.py --force    # 設定済みも取り直す
"""
import argparse
import csv
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "space_list.csv"
TWEETS_DIR = ROOT / "tweets"
JST = timezone(timedelta(hours=9))


def space_start(url):
    r = subprocess.run(["yt-dlp", "-j", "--skip-download", url],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "yt-dlp failed")
    meta = json.loads(r.stdout)
    ts = meta.get("release_timestamp") or meta.get("timestamp")
    if not ts:
        raise RuntimeError("release_timestamp がありません")
    return datetime.fromtimestamp(int(ts), JST)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ep", type=int, action="append", help="対象回 (複数可)")
    ap.add_argument("--force", action="store_true", help="設定済みも上書き")
    args = ap.parse_args()

    done = skipped = failed = 0
    with open(CSV_PATH, newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        if row["録音の有無"] != "あり":
            continue
        m = re.search(r"第(\d+)回", row.get("タイトル", ""))
        if not m:
            continue
        ep = int(m.group(1))
        if args.ep and ep not in args.ep:
            continue
        path = TWEETS_DIR / f"{ep}_{row['Date']}.json"
        if not path.exists():
            print(f"[skip] 第{ep}回 {row['Date']}: {path.name} がまだありません")
            skipped += 1
            continue
        raw = path.read_text()
        data = json.loads(raw)
        if data.get("audio_start_time_jst") and not args.force:
            continue
        sid = row["URL"].rstrip("/").rsplit("/", 1)[-1]
        try:
            start = space_start(row["URL"])
        except Exception as e:
            print(f"[FAIL] 第{ep}回 {row['Date']}: {e}")
            failed += 1
            continue
        if start.date().isoformat() != row["Date"]:
            print(f"[warn] 第{ep}回: 開始時刻 {start:%Y-%m-%d %H:%M} が放送日 {row['Date']} と異なります")
        data["audio_start_time_jst"] = start.isoformat()
        data["audio_start_note"] = (f"X スペース {sid} の開始時刻 (yt-dlp release_timestamp)。"
                                    "null の場合はツイート集中の開始 -10分 で自動推定。")
        indent = 2 if '\n  "' in raw else None
        path.write_text(json.dumps(data, ensure_ascii=False, indent=indent))
        print(f"[set] 第{ep}回 {row['Date']}: {start:%H:%M:%S} JST")
        done += 1
    print(f"=== set {done}, skip {skipped}, fail {failed} ===")


if __name__ == "__main__":
    main()
