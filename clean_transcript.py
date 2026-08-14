#!/usr/bin/env python3
"""Whisperのハルシネーション（連続同一セグメント）と空セグメントを除去する。"""
import json
import sys
import argparse


def clean_segments(segments, min_run=3):
    """連続同一テキストがmin_run回以上のブロックを1個に圧縮、空文字は削除。"""
    # 1. 空文字（whitespaceのみ）セグメント除去
    filtered = [s for s in segments if s['text'].strip()]

    # 2. 連続同一テキストを検出して圧縮
    result = []
    i = 0
    stats = {'empty_dropped': len(segments) - len(filtered),
             'halluc_runs': 0, 'halluc_segments_dropped': 0}
    while i < len(filtered):
        j = i + 1
        while j < len(filtered) and filtered[j]['text'].strip() == filtered[i]['text'].strip():
            j += 1
        run_len = j - i
        if run_len >= min_run:
            # ハルシネーション: 最初の1個だけ残す（時刻はrun全体を包括）
            merged = dict(filtered[i])
            merged['end'] = filtered[j - 1]['end']
            merged['_hallucination_run'] = run_len
            result.append(merged)
            stats['halluc_runs'] += 1
            stats['halluc_segments_dropped'] += run_len - 1
        else:
            result.extend(filtered[i:j])
        i = j
    return result, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_in")
    ap.add_argument("--out", help="出力先（デフォルト: <入力>.clean.json）")
    ap.add_argument("--min-run", type=int, default=3, help="ハルシネーション判定する連続回数")
    args = ap.parse_args()

    with open(args.json_in) as f:
        data = json.load(f)

    orig_segs = data['segments']
    cleaned, stats = clean_segments(orig_segs, min_run=args.min_run)

    orig_chars = sum(len(s['text']) for s in orig_segs)
    new_chars = sum(len(s['text']) for s in cleaned)

    out_path = args.out or args.json_in.replace('.json', '.clean.json')
    data['segments'] = cleaned
    data['_clean_stats'] = stats
    with open(out_path, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"[in] segments={len(orig_segs)} chars={orig_chars}")
    print(f"[out] segments={len(cleaned)} chars={new_chars}  -> {out_path}")
    print(f"[stats] 空セグメント削除: {stats['empty_dropped']}")
    print(f"        ハルシネーションクラスタ: {stats['halluc_runs']}件")
    print(f"        除去したハルシネーションセグメント: {stats['halluc_segments_dropped']}")


if __name__ == "__main__":
    main()
