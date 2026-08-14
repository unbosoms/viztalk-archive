#!/usr/bin/env python3
"""Playwright で X 検索ページから Vizトーク実況ツイートを自動収集する。

準備:
  .venv/bin/pip install playwright
  .venv/bin/playwright install chromium

初回ログイン (プロファイル保存):
  .venv/bin/python bin/collect_tweets.py --login
  → ブラウザが開くので X にログイン、Enter で確定

全回収集 (既に json ある回はスキップ):
  .venv/bin/python bin/collect_tweets.py

特定回だけ:
  .venv/bin/python bin/collect_tweets.py --ep 102 --force

数件だけテスト:
  .venv/bin/python bin/collect_tweets.py --limit 3
"""
import argparse
import csv
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    print("playwright が入っていません。以下を実行:", file=sys.stderr)
    print("  .venv/bin/pip install playwright && .venv/bin/playwright install chromium",
          file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "space_list.csv"
TWEETS_DIR = ROOT / "tweets"
PROFILE_DIR = ROOT / ".x_scrape_profile"


# 抽出用JS: window.extractVizTalkTweets を登録する
EXTRACTOR_JS = r"""
window.extractVizTalkTweets = async (episode, dateStr, maxScroll) => {
    maxScroll = maxScroll || 80;
    // 自動スクロール
    let lastH = 0, sameCount = 0;
    for (let i = 0; i < maxScroll; i++) {
        window.scrollTo(0, document.body.scrollHeight);
        await new Promise(r => setTimeout(r, 1500));
        const h = document.body.scrollHeight;
        if (h === lastH) {
            sameCount++;
            if (sameCount >= 3) break;
        } else {
            sameCount = 0;
        }
        lastH = h;
    }
    // 抽出
    const articles = document.querySelectorAll('article[data-testid="tweet"]');
    const seen = new Set();
    const tweets = [];
    for (const art of articles) {
        try {
            const linkEl = art.querySelector('a[href*="/status/"]');
            if (!linkEl) continue;
            const m = linkEl.getAttribute("href").match(/^\/([^/]+)\/status\/(\d+)/);
            if (!m) continue;
            const authorHandle = m[1];
            const id = m[2];
            if (seen.has(id)) continue;
            seen.add(id);
            const timeEl = art.querySelector("time");
            const postedAt = timeEl ? timeEl.getAttribute("datetime") : null;
            const nameEl = art.querySelector('[data-testid="User-Name"] a span');
            const authorName = nameEl ? nameEl.textContent.trim() : authorHandle;
            const textEl = art.querySelector('[data-testid="tweetText"]');
            const text = textEl ? textEl.innerText.trim() : "";
            const hasMedia = !!art.querySelector('[data-testid="tweetPhoto"], [data-testid="videoPlayer"], [aria-label*="Embedded"]');
            const parseNum = s => {
                if (!s) return 0;
                s = s.replace(/,/g, "").trim();
                if (s.endsWith("K")) return Math.round(parseFloat(s) * 1000);
                if (s.endsWith("M")) return Math.round(parseFloat(s) * 1e6);
                return parseInt(s, 10) || 0;
            };
            const reply = art.querySelector('[data-testid="reply"]')?.textContent || "0";
            const repost = art.querySelector('[data-testid="retweet"], [data-testid="unretweet"]')?.textContent || "0";
            const like = art.querySelector('[data-testid="like"], [data-testid="unlike"]')?.textContent || "0";
            const replyingTo = art.querySelector('[data-testid="reply-to-status-name-container"] a')?.getAttribute("href");
            const isReply = !!replyingTo;
            const replyToHandle = replyingTo ? replyingTo.replace(/^\//, "") : null;
            tweets.push({
                id, url: "https://x.com" + linkEl.getAttribute("href"),
                author_name: authorName, author_handle: authorHandle,
                posted_at: postedAt, text,
                is_reply: isReply, reply_to_handle: replyToHandle,
                has_media: hasMedia,
                metrics: {
                    replies: parseNum(reply),
                    reposts: parseNum(repost),
                    likes: parseNum(like)
                }
            });
        } catch (e) {}
    }
    tweets.sort((a, b) => (a.posted_at || "").localeCompare(b.posted_at || ""));
    return {
        episode, date: dateStr,
        collected_at: new Date().toISOString(),
        audio_start_time_jst: null,
        audio_start_note: "null の場合は最初のツイート -5分 を仮の音源開始時刻として扱う。",
        tweet_count: tweets.length,
        tweets
    };
};
"""


def x_search_url(d):
    until = d + timedelta(days=2)
    q = f"#Vizトーク since:{d.isoformat()} until:{until.isoformat()}"
    return "https://x.com/search?f=live&q=" + quote(q, safe="")


def load_episodes(limit=None, ep_filter=None, force=False):
    result = []
    with open(CSV_PATH, newline='') as f:
        for row in csv.DictReader(f):
            if row['録音の有無'] != 'あり':
                continue
            m = re.search(r'第(\d+)回', row.get('タイトル', ''))
            if not m: continue
            ep = int(m.group(1))
            if ep_filter and ep != ep_filter:
                continue
            try:
                d = date.fromisoformat(row['Date'])
            except ValueError:
                continue
            out_path = TWEETS_DIR / f"{ep}_{d.isoformat()}.json"
            if out_path.exists() and not force:
                continue
            result.append({
                "ep": ep, "date": d.isoformat(),
                "url": x_search_url(d), "out": out_path
            })
    # 新しい回から処理（最近の回の方が実況tweetが充実している傾向）
    result.sort(key=lambda x: x["date"], reverse=True)
    if limit:
        result = result[:limit]
    return result


def _open_context(pw, headless=False, use_real_chrome=True, cdp_url=None):
    """Playwright ブラウザコンテキストを開く。
    cdp_url が指定されていれば既存Chromeに接続、そうでなければ persistent context。
    use_real_chrome=True なら chrome バイナリを使う (X の bot 検出回避)。"""
    if cdp_url:
        browser = pw.chromium.connect_over_cdp(cdp_url)
        if browser.contexts:
            return browser, browser.contexts[0], False
        return browser, browser.new_context(), False
    kwargs = dict(
        headless=headless,
        viewport={"width": 1400, "height": 900},
    )
    if use_real_chrome:
        kwargs["channel"] = "chrome"  # 実物Google Chromeを使う
    ctx = pw.chromium.launch_persistent_context(str(PROFILE_DIR), **kwargs)
    return None, ctx, True  # (browser, ctx, is_persistent)


def do_login(use_real_chrome=True, cdp_url=None):
    with sync_playwright() as pw:
        browser, ctx, is_persistent = _open_context(
            pw, headless=False, use_real_chrome=use_real_chrome, cdp_url=cdp_url)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://x.com/login")
        print("→ ブラウザで X にログインしてから Enter を押してください:", end=" ", flush=True)
        input()
        if is_persistent:
            ctx.close()
        elif browser:
            browser.close()
        print(f"✅ ログインセッション保存")


def collect_all(episodes, delay_sec=4, headless=False, use_real_chrome=True, cdp_url=None):
    ok, fail, empty = 0, 0, 0
    with sync_playwright() as pw:
        browser, ctx, is_persistent = _open_context(
            pw, headless=headless, use_real_chrome=use_real_chrome, cdp_url=cdp_url)
        # 各ページで自動的に extractor JS が登録されるようにする
        ctx.add_init_script(EXTRACTOR_JS)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        for i, ep in enumerate(episodes, 1):
            label = f"[{i}/{len(episodes)}] 第{ep['ep']}回 ({ep['date']})"
            print(f"{label} START", flush=True)
            try:
                page.goto(ep["url"], wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)
                data = page.evaluate(
                    "(args) => window.extractVizTalkTweets(args.ep, args.dateStr)",
                    {"ep": ep["ep"], "dateStr": ep["date"]}
                )
                cnt = data.get("tweet_count", 0) if isinstance(data, dict) else 0
                if cnt == 0:
                    print(f"  ⚠ 0件（X制限 or 該当tweetなし）")
                    empty += 1
                else:
                    ep["out"].write_text(json.dumps(data, ensure_ascii=False, indent=2))
                    print(f"  ✅ {cnt}件 → tweets/{ep['out'].name}")
                    ok += 1
            except PWTimeout as e:
                print(f"  ✗ TIMEOUT: {e}")
                fail += 1
            except KeyboardInterrupt:
                print("\n中断されました")
                break
            except Exception as e:
                print(f"  ✗ ERROR: {type(e).__name__}: {e}")
                fail += 1

            if i < len(episodes):
                time.sleep(delay_sec)

        if is_persistent:
            ctx.close()
        elif browser:
            browser.close()
    print(f"\n=== 完了: 成功={ok} / 0件={empty} / 失敗={fail} ===")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--login", action="store_true", help="初回ログイン用")
    ap.add_argument("--limit", type=int, help="処理する最大件数")
    ap.add_argument("--ep", type=int, help="特定の回番号だけ処理")
    ap.add_argument("--force", action="store_true", help="既存jsonを上書き")
    ap.add_argument("--delay", type=int, default=4, help="URL間の待機秒数（rate limit対策）")
    ap.add_argument("--headless", action="store_true", help="ヘッドレス実行（bot検出リスク上昇）")
    ap.add_argument("--playwright-chromium", action="store_true",
                    help="Playwright同梱のChromiumを使う（デフォは実物のGoogle Chrome）")
    ap.add_argument("--cdp", metavar="URL", default=None,
                    help="既に動いているChromeに接続 (例: http://localhost:9222)")
    args = ap.parse_args()

    use_real_chrome = not args.playwright_chromium

    TWEETS_DIR.mkdir(exist_ok=True)
    PROFILE_DIR.mkdir(exist_ok=True)

    if args.login:
        do_login(use_real_chrome=use_real_chrome, cdp_url=args.cdp)
        return

    episodes = load_episodes(limit=args.limit, ep_filter=args.ep, force=args.force)
    print(f"対象: {len(episodes)}件 (delay={args.delay}秒)")
    if not episodes:
        print("処理対象なし（既に全部収集済みか、フィルタに該当なし）")
        return
    collect_all(episodes, delay_sec=args.delay, headless=args.headless,
                use_real_chrome=use_real_chrome, cdp_url=args.cdp)


if __name__ == "__main__":
    main()
