/* Claude in Chrome の javascript_tool で実行する: 実況ツイートを収集して sessionStorage に貯める。
   bin/x-tweet-collector.js (ブックマークレット) と同じ項目を取るが、以下が違う:
     - 先頭に const KEY = "145_2026-09-10"; を付けて実行する (回数_開催日)
     - 結果はダウンロードせず sessionStorage "__vt_collect" に ID で和集合として貯める
       (同じタブなら画面遷移しても残るので、複数の検索ページの結果を重ねられる)
     - 最後に x-tweet-download-claude.js でまとめて 1 ファイルとしてダウンロードする
   前提: タブが表示状態 (document.visibilityState === "visible") であること。
     非表示タブだと X が続きを読み込まず、最初の 10 件前後で止まる。
     Claude in Chrome では computer の screenshot を撮るとタブが前面に出る。 */
await (async () => {
    await new Promise(r => setTimeout(r, 5000));
    const parseNum = s => {
        if (!s) return 0;
        s = s.replace(/,/g, "").trim();
        if (s.endsWith("K")) return Math.round(parseFloat(s) * 1000);
        if (s.endsWith("M")) return Math.round(parseFloat(s) * 1e6);
        return parseInt(s, 10) || 0;
    };
    const store = JSON.parse(sessionStorage.getItem("__vt_collect") || "{}");
    store[KEY] = store[KEY] || {};
    const S = store[KEY];
    const before = Object.keys(S).length;
    const extract = () => {
        for (const art of document.querySelectorAll('article[data-testid="tweet"]')) {
            try {
                const linkEl = art.querySelector('a[href*="/status/"]');
                if (!linkEl) continue;
                const m = linkEl.getAttribute("href").match(/^\/([^/]+)\/status\/(\d+)/);
                if (!m) continue;
                const nameEl = art.querySelector('[data-testid="User-Name"] a span');
                const replyingTo = art.querySelector('[data-testid="reply-to-status-name-container"] a')?.getAttribute("href");
                S[m[2]] = {
                    id: m[2],
                    url: linkEl.href,
                    author_name: nameEl ? nameEl.textContent.trim() : m[1],
                    author_handle: m[1],
                    posted_at: art.querySelector("time")?.getAttribute("datetime") || null,
                    text: (art.querySelector('[data-testid="tweetText"]')?.innerText || "").trim(),
                    is_reply: !!replyingTo,
                    reply_to_handle: replyingTo ? replyingTo.replace(/^[/]/, "") : null,
                    has_media: !!art.querySelector('[data-testid="tweetPhoto"], [data-testid="videoPlayer"], [aria-label*="Embedded"]'),
                    metrics: {
                        replies: parseNum(art.querySelector('[data-testid="reply"]')?.textContent || "0"),
                        reposts: parseNum(art.querySelector('[data-testid="retweet"], [data-testid="unretweet"]')?.textContent || "0"),
                        likes: parseNum(art.querySelector('[data-testid="like"], [data-testid="unlike"]')?.textContent || "0"),
                    },
                };
            } catch (e) {}
        }
        sessionStorage.setItem("__vt_collect", JSON.stringify(store));
    };
    let lastCount = 0, noGrowth = 0;
    const log = [];
    for (let i = 0; i < 200; i++) {
        extract();
        window.scrollBy(0, window.innerHeight * 0.9);
        await new Promise(r => setTimeout(r, 2500));
        const c = Object.keys(S).length;
        if (c === lastCount) { if (++noGrowth >= 6) break; } else noGrowth = 0;
        lastCount = c;
        log.push(c);
    }
    extract();
    return JSON.stringify({
        key: KEY, before, after: Object.keys(S).length,
        on_page: document.querySelectorAll('article[data-testid="tweet"]').length,
        visibility: document.visibilityState, log: log.join(","),
    });
})();
