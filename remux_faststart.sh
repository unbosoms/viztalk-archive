#!/usr/bin/env bash
# 全 .m4a に対して moov atom を先頭移動（-movflags +faststart）
# ブラウザでの seek を可能にする
set -u
cd "$(dirname "$0")"
count=0
skipped=0
for f in audio/*.m4a; do
    [ -e "$f" ] || continue
    # 既に処理済みか判定: moov atom が mdat より前にあれば OK
    if python3 -c "
import struct, sys
with open('$f','rb') as fp:
    data = fp.read(1024*1024)
i = 0
found_moov_first = False
while i < len(data) - 8:
    size = struct.unpack('>I', data[i:i+4])[0]
    atom = data[i+4:i+8].decode('ascii', errors='replace')
    if atom == 'moov':
        found_moov_first = True; break
    if atom == 'mdat': break
    if size < 8 or size > len(data)-i: break
    i += size
sys.exit(0 if found_moov_first else 1)
" ; then
        skipped=$((skipped+1))
        continue
    fi
    tmp="${f%.m4a}.faststart.m4a"
    if ffmpeg -y -v error -i "$f" -c copy -movflags +faststart "$tmp" && [ -f "$tmp" ]; then
        \mv -f "$tmp" "$f"
        count=$((count+1))
        echo "[$count] $f"
    else
        echo "FAIL: $f"
        \rm -f "$tmp"
    fi
done
echo "=== faststart done: $count processed, $skipped skipped (already ok) ==="
