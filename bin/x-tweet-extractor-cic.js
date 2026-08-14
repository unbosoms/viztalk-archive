// Claude in Chrome から javascript_tool で実行するツイート抽出コード
// window.__vizTalkExtract(102, "2025-05-01") のように呼ぶと JSON文字列を返す
// 前提: 現在開いているタブがX検索ページ
window.__vizTalkExtract = async (episode, dateStr) => {
    // 自動スクロール
    let lastH = 0, sameCount = 0;
    for (let i = 0; i < 80; i++) {
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
                id,
                url: "https://x.com" + linkEl.getAttribute("href"),
                author_name: authorName,
                author_handle: authorHandle,
                posted_at: postedAt,
                text,
                is_reply: isReply,
                reply_to_handle: replyToHandle,
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

    return JSON.stringify({
        episode,
        date: dateStr,
        collected_at: new Date().toISOString(),
        audio_start_time_jst: null,
        audio_start_note: "null の場合は最初のツイート -5分 を仮の音源開始時刻として扱う。",
        tweet_count: tweets.length,
        tweets
    }, null, 2);
};

// 戻り値として関数登録完了を通知
"__vizTalkExtract registered";
