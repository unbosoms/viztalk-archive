/* Claude in Chrome の javascript_tool で実行する: X 検索結果からスペースのカードを拾う。
   前提: 開いているタブが次のような X 検索ページで、タブが表示状態 (visible) であること。
     https://x.com/search?f=live&q=url:spaces since:2026-09-01 (#Vizトーク OR from:YusukeNakanish3)
   スペースの ID はカードの DOM に無いため React fiber の props から "spaces/<ID>" を探す。
   戻り値: [{posted_jst, space_id, card, text}] の JSON 文字列 (URL クエリを含めないこと)。 */
await (async () => {
    const findSpaces = el => {
        const k = Object.keys(el).find(k => k.startsWith("__reactFiber"));
        let f = el[k], d = 0;
        const seen = new Set(), res = new Set();
        while (f && d < 60) {
            try {
                const s = JSON.stringify(f.memoizedProps, (key, v) => {
                    if (typeof v === "object" && v) { if (seen.has(v)) return; seen.add(v); }
                    if (key.startsWith("_")) return;
                    return v;
                });
                (s || "").replace(/spaces\/(1[A-Za-z0-9]{12})/g, (m, g) => res.add(g));
            } catch (e) {}
            f = f.return; d++;
        }
        return [...res];
    };
    await new Promise(r => setTimeout(r, 4000));
    const out = new Map();
    let last = 0, same = 0;
    for (let i = 0; i < 60; i++) {
        for (const a of document.querySelectorAll('article[data-testid="tweet"]')) {
            const w = a.querySelector('[data-testid="wrapperView"]');
            if (!w) continue;
            const ids = findSpaces(w);
            if (!ids.length) continue;
            const t = a.querySelector("time")?.getAttribute("datetime");
            const key = ids[0] + t;
            if (out.has(key)) continue;
            out.set(key, {
                posted_jst: t ? new Date(t).toLocaleString("sv", { timeZone: "Asia/Tokyo" }) : null,
                space_id: ids[0],
                card: w.innerText.replace(/\n/g, " | "),
                text: (a.querySelector('[data-testid="tweetText"]')?.innerText || "").replace(/\n/g, " ").split("http")[0].slice(0, 80),
            });
        }
        window.scrollBy(0, window.innerHeight * 0.9);
        await new Promise(r => setTimeout(r, 2500));
        if (out.size === last) { if (++same >= 5) break; } else same = 0;
        last = out.size;
    }
    const rows = [...out.values()].sort((a, b) => (a.posted_jst || "").localeCompare(b.posted_jst || ""));
    return JSON.stringify({ visibility: document.visibilityState, count: rows.length, rows });
})();
