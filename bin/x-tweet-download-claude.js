/* Claude in Chrome の javascript_tool で実行する: x-tweet-collector-claude.js で貯めた結果を
   1 ファイル (viztalk_tweets_<回>.json) としてダウンロードする。bin/merge_tweets.py で取り込める形式。
   x.com からの 2 件目以降のダウンロードは Chrome が止めることがあるので、
   初回はサイト設定で「自動ダウンロード」を許可してもらう。
   取り込みを確認したら sessionStorage.removeItem("__vt_collect") で消す。 */
(() => {
    const store = JSON.parse(sessionStorage.getItem("__vt_collect") || "{}");
    const episodes = Object.fromEntries(Object.entries(store).map(([k, v]) =>
        [k, Object.values(v).sort((a, b) => (a.posted_at || "").localeCompare(b.posted_at || ""))]));
    const keys = Object.keys(episodes);
    if (!keys.length) return JSON.stringify({ error: "収集結果がありません" });
    const out = { collected_at: new Date().toISOString(), episodes };
    const filename = "viztalk_tweets_" + keys.map(k => k.split("_")[0]).join("-") + ".json";
    const blob = new Blob([JSON.stringify(out, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    return JSON.stringify({ filename, counts: Object.fromEntries(keys.map(k => [k, episodes[k].length])) });
})();
