/* Claude in Chrome の javascript_tool で実行する: スペースのページからタイトルと登壇者を読む。
   前提: https://x.com/i/spaces/<ID> を開いた直後 (X は /peek のオーバーレイを #layers に出す)。
   戻り値: {title, status, speakers_csv} — speakers_csv は space_list.csv の「スピーカー」列の書式。
   表示されるのは終了時点の登壇者なので、途中で抜けた人は載らないことがある。 */
await (async () => {
    await new Promise(r => setTimeout(r, 5000));
    const layer = document.querySelector("#layers");
    const lines = (layer ? layer.innerText : "").split("\n").map(s => s.trim()).filter(Boolean);
    const roles = ["ホスト", "共同ホスト", "スピーカー"];
    const groups = [];
    let cur = null;
    for (let i = 0; i < lines.length; i++) {
        const s = lines[i];
        if (roles.includes(s)) { cur = { role: s, people: [] }; groups.push(cur); continue; }
        if (cur && s.startsWith("@") && i > 0 && !roles.includes(lines[i - 1])) {
            const name = lines[i - 1].replace(/\s*\/\s*/g, "/");
            cur.people.push(`${name}(${s})`);
        }
    }
    const title = lines.find(s => /Vizトーク|第\s*\d+\s*回/.test(s)) || "";
    return JSON.stringify({
        title,
        status: lines[0] || "",
        speakers_csv: groups.filter(g => g.people.length).map(g => `${g.role}: ${g.people.join(", ")}`).join("; "),
        raw: lines.slice(0, 30).join(" | "),
    });
})();
