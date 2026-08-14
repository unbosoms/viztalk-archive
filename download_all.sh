#!/usr/bin/env bash
set -u
cd "$(dirname "$0")"
mkdir -p audio
LOG=audio/_download.log
: > "$LOG"

python3 <<'PYEOF' > /tmp/vizt_download.list
import csv, re
with open('space_list.csv', newline='') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['録音の有無'] != 'あり':
            continue
        date = row['Date'].replace('-', '')
        url = row['URL']
        title = row['タイトル']
        m = re.search(r'第(\d+)回(（再）)?', title)
        if not m:
            continue
        ep = m.group(1)
        rerun = '_再' if m.group(2) else ''
        fname = f'{date}_第{ep}回{rerun}_Vizトーク'
        print(f'{fname}\t{url}')
PYEOF

TOTAL=$(wc -l < /tmp/vizt_download.list)
echo "Total to download: $TOTAL" | tee -a "$LOG"

i=0
while IFS=$'\t' read -r fname url; do
    i=$((i+1))
    target="audio/${fname}.m4a"
    if [ -f "$target" ]; then
        echo "[$i/$TOTAL] SKIP (exists): $fname" | tee -a "$LOG"
        continue
    fi
    echo "[$i/$TOTAL] DL: $fname <- $url" | tee -a "$LOG"
    yt-dlp -o "audio/${fname}.%(ext)s" "$url" >> "$LOG" 2>&1
    if [ $? -eq 0 ]; then
        echo "[$i/$TOTAL] OK: $fname" | tee -a "$LOG"
    else
        echo "[$i/$TOTAL] FAIL: $fname" | tee -a "$LOG"
    fi
done < /tmp/vizt_download.list

echo "=== ALL DONE ===" | tee -a "$LOG"
