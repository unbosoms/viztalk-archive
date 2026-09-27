#!/usr/bin/env python3
"""録音ありの各回について、データが揃っているかを一覧する。

  python3 bin/check_status.py          # 欠けがある回だけ表示
  python3 bin/check_status.py --all    # 全回表示
  python3 bin/check_status.py --r2     # R2 上の音源も確認 (rclone で一覧取得)
"""
import argparse
import csv
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--r2", action="store_true")
    args = ap.parse_args()

    r2 = None
    if args.r2:
        out = subprocess.run(["rclone", "lsf", "r2:viztalk-archive-audio", "--files-only"],
                             capture_output=True, text=True)
        r2 = set(out.stdout.split("\n"))
    durations = json.loads((ROOT / "audio/_durations.json").read_text())

    cols = ["audio", "clean", "chapters", "tweets", "start", "duration"] + (["r2"] if args.r2 else [])
    print(f"{'回':>5} {'日付':10} " + " ".join(f"{c:>8}" for c in cols))
    incomplete = 0
    with open(ROOT / "space_list.csv", newline="") as f:
        for row in csv.DictReader(f):
            if row["録音の有無"] != "あり":
                continue
            m = re.search(r"第(\d+)回(（再）)?", row["タイトル"])
            if not m:
                print(f"  ?? {row['Date']}: タイトルに第N回がありません: {row['タイトル']}")
                incomplete += 1
                continue
            ep, date = m.group(1), row["Date"]
            stem = f"{date.replace('-', '')}_第{ep}回{'_再' if m.group(2) else ''}_Vizトーク"
            tw = ROOT / "tweets" / f"{ep}_{date}.json"
            st = {
                "audio": (ROOT / "audio" / f"{stem}.m4a").exists(),
                "clean": (ROOT / "transcripts" / f"{stem}.clean.json").exists(),
                "chapters": (ROOT / "transcripts" / f"{stem}.clean.chapters.json").exists(),
                "tweets": tw.exists(),
                "start": tw.exists() and bool(json.loads(tw.read_text()).get("audio_start_time_jst")),
                "duration": bool(durations.get(f"{stem}.m4a")),
            }
            if r2 is not None:
                st["r2"] = f"{stem}.m4a" in r2
            ok = all(st.values())
            if not ok:
                incomplete += 1
            if args.all or not ok:
                print(f"{ep:>5} {date:10} " + " ".join(f"{'o' if st[c] else '-':>8}" for c in cols))
    print(f"=== 欠けあり {incomplete} 回 ===")


if __name__ == "__main__":
    main()
