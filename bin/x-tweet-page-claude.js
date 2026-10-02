/* Claude in Chrome の javascript_tool で実行する: X 検索結果の 1 ページ目だけを読んで sessionStorage に貯める (遡る方式)。
   タブが非表示 (最小化・他アプリの裏・裏タブ) でも動く。X は非表示でも最初の 6〜10 件は読み込むが、
   スクロールでの続きは表示中でないと来ないため、スクロールはせず until_time をずらして開き直す。
   使い方:
     1. 「最新」タブで #Vizトーク since_time:<開始> until_time:<終了> を開く
     2. 先頭に const KEY = "148_2026-10-01"; を付けてこのスクリプトを実行する (回数_開催日)
     3. 戻り値の next_until を次の until_time にして 1 に戻る。done が true になったら終わり
        (stuck が true なら同じ 1 秒に投稿が集中して遡れていない → 止めて報告)
     4. x-tweet-download-claude.js でダウンロード → merge_tweets.py
     5. 取り込みを確認したら sessionStorage.removeItem("__vt_collect") と removeItem("__vt_oldest_" + KEY)
   前回の "__vt_oldest_<KEY>" が残っていると 1 ページ目で done になるので、始める前にも消しておく。
   項目は x-tweet-collector-claude.js と同じ。結果は sessionStorage "__vt_collect" に ID で和集合として貯まる。
   戻り値に URL のクエリ文字列を含めないこと (javascript_tool が BLOCKED にする)。 */
await (async () => {
    await new Promise(r => setTimeout(r, 6000));
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
    const prevOldest = Number(sessionStorage.getItem("__vt_oldest_" + KEY) || Infinity);
    const arts = document.querySelectorAll('article[data-testid="tweet"]');
    let oldest = null, newest = null;
    for (const art of arts) {
        try {
            const linkEl = art.querySelector('a[href*="/status/"]');
            if (!linkEl) continue;
            const m = linkEl.getAttribute("href").match(/^\/([^/]+)\/status\/(\d+)/);
            if (!m) continue;
            const nameEl = art.querySelector('[data-testid="User-Name"] a span');
            const replyingTo = art.querySelector('[data-testid="reply-to-status-name-container"] a')?.getAttribute("href");
            const postedAt = art.querySelector("time")?.getAttribute("datetime") || null;
            if (postedAt && (!oldest || postedAt < oldest)) oldest = postedAt;
            if (postedAt && (!newest || postedAt > newest)) newest = postedAt;
            S[m[2]] = {
                id: m[2],
                url: linkEl.href,
                author_name: nameEl ? nameEl.textContent.trim() : m[1],
                author_handle: m[1],
                posted_at: postedAt,
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
    const oldestUnix = oldest ? Math.floor(Date.parse(oldest) / 1000) : null;
    // 前のページより古い投稿が無ければ開始まで届いた (同じ 1 秒に 1 ページ分を超える投稿があった場合も止まる → stuck)
    const done = oldestUnix === null || oldestUnix >= prevOldest;
    if (!done) sessionStorage.setItem("__vt_oldest_" + KEY, String(oldestUnix));
    const jst = s => s ? new Date(s).toLocaleString("sv", { timeZone: "Asia/Tokyo" }) : null;
    return JSON.stringify({
        key: KEY, on_page: arts.length, added: Object.keys(S).length - before, total: Object.keys(S).length,
        oldest_jst: jst(oldest), newest_jst: jst(newest),
        next_until: done ? null : oldestUnix + 1,
        done, stuck: done && arts.length >= 5,
        visibility: document.visibilityState,
    });
})();
