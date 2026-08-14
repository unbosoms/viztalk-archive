(async () => {
    const SCROLL_INTERVAL_MS = 2500;
    const SCROLL_MAX_TRIES = 200;
    const NO_GROWTH_STOP = 6;

    let hint = "";
    try {
        const u = new URL(window.location.href);
        const q = u.searchParams.get("q") || "";
        const sinceMatch = q.match(/since:(\d{4}-\d{2}-\d{2})/);
        if (sinceMatch) hint = "," + sinceMatch[1];
    } catch (e) {}

    const EPISODE_HINT = prompt("回数,開催日を入力 (例: 102,2025-05-01)", hint);
    if (!EPISODE_HINT) return;
    const [epStr, dateStr] = EPISODE_HINT.split(",").map(s => s.trim());
    const episode = parseInt(epStr, 10);
    if (!episode || !dateStr) { alert("入力が不正です"); return; }

    const seen = new Set();
    const tweets = [];

    function extractVisible() {
        const articles = document.querySelectorAll('article[data-testid="tweet"]');
        for (const art of articles) {
            try {
                const linkEl = art.querySelector('a[href*="/status/"]');
                if (!linkEl) continue;
                const href = linkEl.getAttribute("href");
                const m = href.match(/^\/([^/]+)\/status\/(\d+)/);
                if (!m) continue;
                const authorHandle = m[1];
                const id = m[2];
                if (seen.has(id)) continue;
                seen.add(id);
                const url = linkEl.href;

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
                const replyToHandle = replyingTo ? replyingTo.replace(/^[/]/, "") : null;

                tweets.push({
                    id, url, author_name: authorName, author_handle: authorHandle,
                    posted_at: postedAt, text,
                    is_reply: isReply, reply_to_handle: replyToHandle,
                    has_media: hasMedia,
                    metrics: { replies: parseNum(reply), reposts: parseNum(repost), likes: parseNum(like) }
                });
            } catch (e) {}
        }
    }

    let lastCount = 0;
    let noGrowthCount = 0;
    for (let i = 0; i < SCROLL_MAX_TRIES; i++) {
        extractVisible();
        window.scrollBy(0, window.innerHeight * 0.9);
        await new Promise(r => setTimeout(r, SCROLL_INTERVAL_MS));
        if (tweets.length === lastCount) {
            noGrowthCount++;
            if (noGrowthCount >= NO_GROWTH_STOP) break;
        } else {
            noGrowthCount = 0;
        }
        lastCount = tweets.length;
    }
    extractVisible();

    tweets.sort((a, b) => (a.posted_at || "").localeCompare(b.posted_at || ""));

    const out = {
        episode, date: dateStr,
        collected_at: new Date().toISOString(),
        audio_start_time_jst: null,
        audio_start_note: "null の場合は最初のツイート -5分 を仮の音源開始時刻として扱う。",
        tweet_count: tweets.length,
        tweets,
    };

    const json = JSON.stringify(out, null, 2);
    const filename = episode + "_" + dateStr + ".json";

    const blob = new Blob([json], { type: "application/json" });
    const bloburl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = bloburl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(bloburl), 1000);

    try {
        await navigator.clipboard.writeText(json);
        alert("✅ " + tweets.length + "件のtweetを抽出。\n" + filename + " をダウンロード＋クリップボードにコピーしました。\n~/Downloads から tweets/ にmvしてください。");
    } catch (e) {
        alert("✅ " + tweets.length + "件のtweetを抽出。\n" + filename + " をダウンロードしました。");
    }
    console.log(out);
})();
