#!/usr/bin/env python3
"""Vizトークアーカイブサイトを生成する。CSV + chapters.json から静的HTMLを吐く。"""
import csv
import json
import os
import re
import html
from collections import defaultdict, Counter
from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).parent
CSV_PATH = ROOT / "space_list.csv"
TRANS_DIR = ROOT / "transcripts"
AUDIO_DIR = ROOT / "audio"
TWEETS_DIR = ROOT / "tweets"
SITE_DIR = ROOT / "mockup"
DURATIONS_CACHE_PATH = AUDIO_DIR / "_durations.json"

_durations_cache = None
_durations_dirty = False


def _load_durations_cache():
    global _durations_cache
    if _durations_cache is not None:
        return _durations_cache
    if DURATIONS_CACHE_PATH.exists():
        try:
            _durations_cache = json.loads(DURATIONS_CACHE_PATH.read_text())
        except Exception:
            _durations_cache = {}
    else:
        _durations_cache = {}
    return _durations_cache


def _save_durations_cache():
    global _durations_dirty
    if not _durations_dirty:
        return
    DURATIONS_CACHE_PATH.write_text(json.dumps(_durations_cache, ensure_ascii=False, indent=2))
    _durations_dirty = False


def get_audio_duration_sec(audio_filename):
    """audio/{filename}.m4a の再生時間(秒, int)を返す。ffprobeを1回だけ実行、以降キャッシュ。"""
    global _durations_dirty
    if not audio_filename:
        return None
    cache = _load_durations_cache()
    if audio_filename in cache:
        return cache[audio_filename]
    p = AUDIO_DIR / audio_filename
    if not p.exists():
        cache[audio_filename] = None
        _durations_dirty = True
        return None
    try:
        import subprocess
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(p)],
            capture_output=True, text=True, timeout=10,
        )
        dur = int(float(r.stdout.strip()))
        cache[audio_filename] = dur
        _durations_dirty = True
        return dur
    except Exception:
        cache[audio_filename] = None
        _durations_dirty = True
        return None


def fmt_duration_short(sec):
    """秒 -> '2h04m' or '32m'"""
    if not sec:
        return ""
    h = sec // 3600
    m = (sec % 3600) // 60
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m"


def parse_speakers(raw):
    """CSVのスピーカー列を {role, name, handle}[] にパース。"""
    if not raw:
        return []
    result = []
    # 「ホスト: X(@a); 共同ホスト: Y(@b); スピーカー: Z(@c), W(@d)」
    for group in re.split(r"[;；]\s*", raw):
        m = re.match(r"([^:：]+)[:：]\s*(.+)", group)
        if not m:
            continue
        role = m.group(1).strip()
        rest = m.group(2)
        # カンマ区切りで複数人
        for entry in re.split(r"[,、]", rest):
            entry = entry.strip()
            mm = re.match(r"(.+?)\(@([\w_]+)\)", entry)
            if mm:
                result.append({"role": role, "name": mm.group(1).strip(),
                               "handle": mm.group(2).strip()})
    return result


def load_episodes():
    """CSVを読み込み、chaptersがあればマージ。重複回番号(第76回×2など)は _disambiguate フラグを立てる。"""
    episodes = []
    with open(CSV_PATH, newline='') as f:
        for row in csv.DictReader(f):
            title = row.get("タイトル", "")
            m = re.search(r"第(\d+)回", title)
            ep_num = int(m.group(1)) if m else None
            date = row["Date"]
            date_yyyymmdd = date.replace("-", "")
            recording = row["録音の有無"] == "あり"
            has_rerun = "（再）" in title
            fname_stem = f"{date_yyyymmdd}_第{ep_num}回{'_再' if has_rerun else ''}_Vizトーク" if ep_num else None

            # chapter data
            chapters_path = TRANS_DIR / f"{fname_stem}.clean.chapters.json" if fname_stem else None
            chapters_data = None
            if chapters_path and chapters_path.exists():
                with open(chapters_path) as cf:
                    chapters_data = json.load(cf)

            # 全文文字起こしを Pagefind 用に load (segments listのみ)
            transcript_segments = None
            transcript_path = TRANS_DIR / f"{fname_stem}.clean.json" if fname_stem else None
            if transcript_path and transcript_path.exists():
                try:
                    with open(transcript_path) as tf:
                        td = json.load(tf)
                    transcript_segments = td.get("segments", [])
                except Exception:
                    transcript_segments = None

            audio_path = AUDIO_DIR / f"{fname_stem}.m4a" if fname_stem else None
            # AUDIO_BASE_URL 設定時 (本番) は R2にアップロード済みと信頼し、ローカル存在確認スキップ
            # 未設定時 (ローカル開発) は実ファイルの有無をチェック
            if fname_stem and (AUDIO_BASE_URL or (audio_path and audio_path.exists())):
                audio_filename = f"{fname_stem}.m4a"
            else:
                audio_filename = None

            tweets_data = load_tweets(ep_num, date)

            episodes.append({
                "date": date,
                "date_yyyymmdd": date_yyyymmdd,
                "url": row["URL"],
                "title": title,
                "ep": ep_num,
                "has_rerun": has_rerun,
                "recording": recording,
                "speakers": parse_speakers(row.get("スピーカー", "")),
                "speakers_raw": row.get("スピーカー", ""),
                "fname_stem": fname_stem,
                "audio_filename": audio_filename,
                "chapters_data": chapters_data,
                "tweets_data": tweets_data,
                "transcript_segments": transcript_segments,
            })
    # 重複ep検出
    ep_counts = Counter(e["ep"] for e in episodes if e["ep"])
    for e in episodes:
        e["_disambiguate"] = bool(e["ep"] and ep_counts[e["ep"]] > 1)
    return episodes


def ep_slug(ep):
    """episode dict → 一意なURL slug。重複回は日付付き、通常は回番号のみ。"""
    if not ep.get("ep"):
        return None
    if ep.get("_disambiguate"):
        return f'{ep["ep"]}_{ep["date_yyyymmdd"]}'
    return str(ep["ep"])


AUDIO_BASE_URL = os.environ.get("AUDIO_BASE_URL", "").rstrip("/")
GA_MEASUREMENT_ID = os.environ.get("GA_MEASUREMENT_ID", "").strip()


def audio_url(fname, level):
    """音源URLを解決する。

    - 環境変数 AUDIO_BASE_URL が設定されていればそれを prefix に絶対URL化 (本番/R2用)
      例: AUDIO_BASE_URL=https://audio.vizt.example → https://audio.vizt.example/xxx.m4a
    - 未設定ならローカルの mockup/audio シンボリックリンク経由 (開発用)
      level=0 (mockup直下) → 'audio/xxx.m4a'
      level=1 (episode/等サブフォルダ) → '../audio/xxx.m4a'
    """
    if not fname:
        return ""
    if AUDIO_BASE_URL:
        return f"{AUDIO_BASE_URL}/{quote(fname, safe='')}"
    return ("../" if level == 1 else "") + "audio/" + fname


def parse_dt_to_jst(s):
    """ISO文字列(UTC/JST/ナイーブ) を JST の aware datetime に。"""
    if not s:
        return None
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    return dt.astimezone(JST)


def estimate_audio_start(tweets, broadcast_date, gap_threshold_min=15, offset_min=10):
    """密なtweet集合(gap<=15min)の先頭 - offset_min(10min) を音源開始と推定。

    Vizトーク の実況は開始5〜15分後に始まることが多いため offset=10min を採用。
    密集合が見つからない or 推定結果が異常(21時前 or 24時後)なら broadcast_date 22:30 JST。
    tweets/*.json の `audio_start_time_jst` で手動オーバーライド可。"""
    times = sorted(parse_dt_to_jst(t["posted_at"]) for t in tweets if t.get("posted_at"))
    times = [t for t in times if t is not None]
    d = date.fromisoformat(broadcast_date)
    default_start = datetime(d.year, d.month, d.day, 22, 30, tzinfo=JST)

    cluster_start = None
    for i in range(len(times) - 1):
        gap_min = (times[i + 1] - times[i]).total_seconds() / 60
        if gap_min <= gap_threshold_min:
            cluster_start = times[i]
            break

    if cluster_start is None:
        return default_start

    estimated = cluster_start - timedelta(minutes=offset_min)
    # 推定が妥当な時間帯 (21:00〜24:00 JST) にあるかチェック
    lower = datetime(d.year, d.month, d.day, 21, 0, tzinfo=JST)
    upper = datetime(d.year, d.month, d.day, 23, 59, tzinfo=JST)
    if lower <= estimated <= upper:
        return estimated
    return default_start


def load_tweets(ep_num, date_str):
    """tweets/{ep}_{date}.json をロード。存在しなければ None。各tweetに _audio_offset_sec と _posted_jst を付与する。"""
    if not ep_num:
        return None
    path = TWEETS_DIR / f"{ep_num}_{date_str}.json"
    if not path.exists():
        return None
    with open(path) as f:
        data = json.load(f)
    tweets = data.get("tweets", [])
    if not tweets:
        return data
    # 音源開始時刻を決定
    ast_str = data.get("audio_start_time_jst")
    if ast_str:
        audio_start = parse_dt_to_jst(ast_str)
        data["_audio_start_source"] = "manual (audio_start_time_jst)"
    else:
        audio_start = estimate_audio_start(tweets, date_str)
        data["_audio_start_source"] = "auto (tweet cluster)"
    data["_audio_start_iso"] = audio_start.isoformat()
    data["_audio_start_jst_display"] = audio_start.strftime("%Y-%m-%d %H:%M JST")
    for t in tweets:
        posted = parse_dt_to_jst(t["posted_at"])
        if posted is None:
            t["_audio_offset_sec"] = 0
            t["_posted_jst"] = ""
            continue
        offset = (posted - audio_start).total_seconds()
        t["_audio_offset_sec"] = offset
        t["_posted_jst"] = posted.strftime("%H:%M")
    return data


def linkify_tweet_text(text):
    """tweetテキストのURLをリンク化 + 改行を <br> に。"""
    text = html.escape(text)
    text = re.sub(
        r'(https?://[\w\-./?=%&:#!~+@,;]+)',
        r'<a href="\1" target="_blank" rel="noopener" onclick="event.stopPropagation();">\1</a>',
        text)
    text = text.replace("\n", "<br>")
    return text


def fmt_ts_hms(sec):
    """秒 -> H:MM:SS"""
    sec = int(sec or 0)
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    return f"{h}:{m:02d}:{s:02d}"


def ts_to_sec(ts):
    """'H:MM:SS' or 'MM:SS' or 秒数を秒に変換"""
    if isinstance(ts, (int, float)):
        return int(ts)
    if not ts:
        return 0
    parts = str(ts).split(":")
    try:
        parts = [int(p) for p in parts]
    except ValueError:
        return 0
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0]


def render_tweet_card(t, src, ep):
    """1件のtweetカードHTML（timeline / tweets タブ共通）"""
    offset = t.get("_audio_offset_sec", 0)
    author = html.escape(t.get("author_name", ""))
    handle = html.escape(t.get("author_handle", ""))
    initial = html.escape((t.get("author_name") or " ")[0])
    abs_time = t.get("_posted_jst") or ""
    text_html = linkify_tweet_text(t.get("text", ""))
    url = html.escape(t.get("url", ""), quote=True)
    has_media = t.get("has_media", False)
    metrics = t.get("metrics") or {}
    likes = metrics.get("likes", 0) or 0
    reposts = metrics.get("reposts", 0) or 0
    replies = metrics.get("replies", 0) or 0
    js_title = html.escape(f"第{ep['ep']}回 実況tweet: {author}", quote=True)
    js_sub = html.escape(f"{ep['date']} @ {fmt_offset(offset)}", quote=True)
    metrics_html = ""
    if replies:
        metrics_html += f'<span class="metric">💬 {replies}</span>'
    if reposts:
        metrics_html += f'<span class="metric">🔁 {reposts}</span>'
    if likes:
        metrics_html += f'<span class="metric">♡ {likes}</span>'
    media_badge = ' <span class="tweet-media-badge">📷 メディア</span>' if has_media else ''
    return f'''
    <div class="tweet-item" data-audio-time="{int(offset)}" onclick="playChapter('{src}','{max(0, int(offset))}','{js_title}','{js_sub}')">
      <div class="tweet-header">
        {avatar_img(t.get("author_handle", ""), size=36, css_class="avatar tweet-avatar-img")}
        <div class="tweet-namestack">
          <div class="tweet-name">{author}{media_badge}</div>
          <div class="tweet-metaline">
            <span class="handle">@{handle}</span>
            <span class="dot">·</span>
            <span class="abs-time">{abs_time}</span>
          </div>
        </div>
        <span class="tweet-audio-time">{fmt_offset(offset)}</span>
      </div>
      <div class="tweet-text">{text_html}</div>
      <div class="tweet-footer">
        {metrics_html}
        <a href="{url}" target="_blank" rel="noopener" class="tweet-x-link" onclick="event.stopPropagation();">Xで開く ↗</a>
      </div>
    </div>'''


def fmt_offset(sec):
    """秒 -> '@ 0:12:34' or '@ -0:03:00' (音源開始前)"""
    sign = "-" if sec < 0 else ""
    sec = abs(int(sec))
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h:
        return f"{sign}{h}:{m:02d}:{s:02d}"
    return f"{sign}{m}:{s:02d}"


def x_live_search_url(date_str, hashtag="#Vizトーク"):
    """指定日 00:00 〜 翌日 23:59 の #Vizトーク ツイート検索URL。深夜跨ぎに対応。"""
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        return None
    until_d = d + timedelta(days=2)  # 翌日まで含める（Xのuntilはexclusive相当）
    q = f"{hashtag} since:{d.isoformat()} until:{until_d.isoformat()}"
    return "https://x.com/search?f=live&q=" + quote(q, safe="")


def slug_ep(ep, has_rerun=False):
    return f"{ep}{'_r' if has_rerun else ''}"


def slug_handle(handle):
    return handle.lower().replace("_", "-")


X_ICON_SVG = ('<svg class="x-icon" width="12" height="12" viewBox="0 0 24 24" fill="currentColor" '
              'aria-hidden="true"><path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>')


def avatar_url(handle):
    """X (Twitter) プロフィールアイコンURL。unavatar.io 経由。"""
    if not handle:
        return ""
    return f"https://unavatar.io/x/{quote(handle, safe='')}"


def avatar_img(handle, size=40, css_class="avatar"):
    """<img> タグを返す。読み込み失敗時はイニシャル文字アバターにフォールバック。"""
    if not handle:
        return ""
    initial = html.escape(handle[0].upper())
    return (
        f'<span class="avatar-wrap avatar-{size}">'
        f'<img class="{css_class}" src="{avatar_url(handle)}" alt="@{html.escape(handle)}" '
        f'loading="lazy" '
        f'onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\';">'
        f'<span class="avatar-fallback">{initial}</span>'
        f'</span>'
    )


def x_profile_link(handle, extra_class=""):
    """@handle → Xプロフィールリンク (小さいXアイコン)"""
    if not handle:
        return ""
    return (f'<a href="https://x.com/{html.escape(handle)}" target="_blank" '
            f'rel="noopener" class="x-link {extra_class}" title="Xで @{html.escape(handle)} を開く" '
            f'onclick="event.stopPropagation();">{X_ICON_SVG}</a>')


def slug_tag(tag):
    # ファイル名として使えない文字だけを置換。日本語はそのままファイル名に。
    # ブラウザは href の日本語を自動でURL-encodeし、サーバーはdecodeするので、生の日本語ファイル名で問題なし。
    return re.sub(r'[/\\:*?"<>|]', '_', tag)


def collect_tag_stats(episodes):
    """全chaptersを横断してタグ統計を集計。回の重複(第76回×2など)は別開催として個別カウント。"""
    tag_chapters = defaultdict(list)   # tag → [ (episode, chapter) ]
    tag_episodes = defaultdict(set)    # tag → set of (date, ep) tuples (重複回も別カウント)
    for ep in episodes:
        if not ep["chapters_data"]:
            continue
        for ch in ep["chapters_data"].get("chapters", []):
            for tag in ch.get("tags", []) or []:
                tag_chapters[tag].append((ep, ch))
                tag_episodes[tag].add((ep["date"], ep["ep"]))
    return tag_chapters, tag_episodes


def collect_speaker_stats(episodes):
    """スピーカー横断統計。handle → info + episode list。
    tagsは「そのスピーカーの出演回で当該タグが出現したユニークな回数」でカウント (1話に何chapterあっても+1)。"""
    speakers = defaultdict(lambda: {"name": None, "handle": None, "roles": Counter(),
                                     "episodes": [], "tags": Counter()})
    for ep in episodes:
        # この回の episode_tags (unique) を先に決める
        ep_tags = set()
        if ep["chapters_data"]:
            for ch in ep["chapters_data"].get("chapters", []):
                for tag in ch.get("tags", []) or []:
                    if tag:
                        ep_tags.add(tag)
        for sp in ep["speakers"]:
            key = sp["handle"]
            info = speakers[key]
            info["handle"] = key
            info["name"] = sp["name"]
            info["roles"][sp["role"]] += 1
            info["episodes"].append(ep)
            for tag in ep_tags:
                info["tags"][tag] += 1
    return speakers


# ============ TEMPLATES ============

LAYOUT = """<!doctype html>
<html lang="ja"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#3b8a99">
<title>{title}</title>
<link rel="stylesheet" href="{css}">
{ga_snippet}</head><body>

<header class="header">
  <a href="{home}" class="brand">
    <img src="{logo_url}" alt="Vizトーク">
    <span>Vizトーク Archive</span>
  </a>
  <nav>
    <a href="{episodes_link}"{nav_ep_class}>トーク一覧</a>
    <a href="{tags_link}"{nav_tag_class}>トピック</a>
    <a href="{speakers_link}"{nav_sp_class}>スピーカー</a>
  </nav>
  <form class="search" action="{search_link}" method="get">
    <input type="text" name="q" placeholder="キーワード検索 (Enter で実行)" autocomplete="off">
  </form>
</header>

<div class="container{container_class}">
{body}

<footer class="site-footer">
  <p><strong>Vizトーク アーカイブ</strong> — 非公式ファンサイト</p>
  <p class="foot-note">音源・発言の著作権は各出演者に帰属します。文字起こしは AI (Whisper) 自動処理のため誤りを含みます。</p>
  <p>
    <a href="{privacy_link}">プライバシーポリシー</a>
    ·
    <a href="https://github.com/unbosoms/viztalk-archive/issues" target="_blank" rel="noopener">問題報告・削除依頼</a>
    ·
    <a href="https://github.com/unbosoms/viztalk-archive" target="_blank" rel="noopener">ソースコード</a>
  </p>
</footer>
</div>

<div class="player" id="player-bar">
  <div class="now-playing">
    <div class="title" id="np-title">未再生</div>
    <div class="sub" id="np-sub">回を選んでね</div>
  </div>
  <div class="controls">
    <button onclick="skip(-10)" title="10秒戻る" class="skip">−10秒</button>
    <button class="play" onclick="togglePlay()" id="np-play" title="再生/一時停止">▶</button>
    <button onclick="skip(10)" title="10秒進む" class="skip">+10秒</button>
  </div>
  <div class="seek">
    <span id="np-cur">0:00</span>
    <div class="bar" id="np-bar" onclick="seekBar(event)"><div class="fill" id="np-fill"></div></div>
    <span id="np-dur">0:00</span>
  </div>
  <select class="speed" onchange="setSpeed(this.value)">
    <option value="1.0">1.0x</option>
    <option value="1.25">1.25x</option>
    <option value="1.5">1.5x</option>
    <option value="2.0">2.0x</option>
  </select>
  <audio id="audio-player" preload="none"></audio>
</div>

<script>
const audio = document.getElementById("audio-player");
const npTitle = document.getElementById("np-title");
const npSub = document.getElementById("np-sub");
const npCur = document.getElementById("np-cur");
const npDur = document.getElementById("np-dur");
const npFill = document.getElementById("np-fill");
const npPlay = document.getElementById("np-play");

function fmt(sec) {{
  if (!isFinite(sec)) return "0:00";
  const h = Math.floor(sec/3600);
  const m = Math.floor((sec%3600)/60);
  const s = Math.floor(sec%60);
  if (h) return h+":"+String(m).padStart(2,"0")+":"+String(s).padStart(2,"0");
  return m+":"+String(s).padStart(2,"0");
}}

function parseTs(ts) {{
  const p = ts.split(":").map(Number);
  if (p.length===3) return p[0]*3600+p[1]*60+p[2];
  if (p.length===2) return p[0]*60+p[1];
  return p[0]||0;
}}

let curSrc = null;
function loadAudio(src, title, sub) {{
  if (src !== curSrc) {{
    audio.src = src;
    curSrc = src;
    audio.load();
  }}
  npTitle.textContent = title;
  npSub.textContent = sub;
}}

function playChapter(src, tsStr, title, sub) {{
  loadAudio(src, title, sub);
  const sec = parseTs(tsStr);
  const play = () => {{ audio.currentTime = sec; audio.play(); }};
  if (audio.readyState >= 1) {{ play(); }}
  else {{ audio.addEventListener("loadedmetadata", play, {{once: true}}); }}
  document.querySelectorAll(".chapter").forEach(c => c.classList.remove("active"));
  if (event && event.currentTarget && event.currentTarget.classList) {{
    event.currentTarget.classList.add("active");
  }}
}}

function togglePlay() {{
  if (!audio.src) return;
  if (audio.paused) audio.play(); else audio.pause();
}}
function skip(sec) {{
  if (audio.src) audio.currentTime = Math.max(0, audio.currentTime + sec);
}}
function seekBar(e) {{
  const bar = document.getElementById("np-bar");
  const rect = bar.getBoundingClientRect();
  const p = (e.clientX - rect.left) / rect.width;
  if (audio.duration) audio.currentTime = audio.duration * p;
}}
function setSpeed(v) {{ audio.playbackRate = parseFloat(v); }}

audio.addEventListener("timeupdate", () => {{
  npCur.textContent = fmt(audio.currentTime);
  if (audio.duration) {{
    npFill.style.width = (audio.currentTime/audio.duration*100) + "%";
  }}
  // 時刻同期: tweet と chapter の両方をハイライト
  const t = audio.currentTime;
  document.querySelectorAll(".tweet-item").forEach(el => {{
    const twt = parseFloat(el.dataset.audioTime);
    if (isNaN(twt)) return;
    el.classList.toggle("current", Math.abs(t - twt) < 30);
  }});
  // chapter は「startからendの範囲内」ならcurrent
  const chapters = document.querySelectorAll(".chapter[data-audio-time]");
  const chapterTimes = Array.from(chapters).map(el => ({{el, t: parseFloat(el.dataset.audioTime)}})).filter(x => !isNaN(x.t));
  chapterTimes.sort((a,b) => a.t - b.t);
  let currentIdx = -1;
  for (let i = 0; i < chapterTimes.length; i++) {{
    if (chapterTimes[i].t <= t) currentIdx = i; else break;
  }}
  chapters.forEach(el => el.classList.remove("current"));
  if (currentIdx >= 0) chapterTimes[currentIdx].el.classList.add("current");
}});

// タブ切替
document.addEventListener("click", (e) => {{
  const btn = e.target.closest(".tab-btn");
  if (!btn) return;
  const container = btn.closest(".tab-container");
  if (!container) return;
  container.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  container.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
  btn.classList.add("active");
  const panel = container.querySelector("#" + btn.dataset.target);
  if (panel) panel.classList.add("active");
}});

// data-href 付き要素をクリック可能に (内部の a/button は素通し)
document.addEventListener("click", (e) => {{
  const card = e.target.closest("[data-href]");
  if (!card) return;
  if (e.target.closest("a, button, [onclick]")) return;
  location.href = card.dataset.href;
}});

// 一覧の並び順切替 (data-name / data-count を持つ子要素をソート)
function sortItems(containerId, mode, opts) {{
  const container = document.getElementById(containerId);
  if (!container) return;
  const items = Array.from(container.children).filter(el => el.dataset && (el.dataset.name || el.dataset.count));
  items.sort((a, b) => {{
    if (mode === "count") {{
      const diff = parseInt(b.dataset.count || 0) - parseInt(a.dataset.count || 0);
      if (diff !== 0) return diff;
      return (a.dataset.name || "").localeCompare(b.dataset.name || "", "ja");
    }} else {{
      return (a.dataset.name || "").localeCompare(b.dataset.name || "", "ja");
    }}
  }});
  items.forEach(el => container.appendChild(el));
}}
audio.addEventListener("loadedmetadata", () => {{
  npDur.textContent = fmt(audio.duration);
}});
audio.addEventListener("play", () => {{ npPlay.textContent = "⏸"; }});
audio.addEventListener("pause", () => {{ npPlay.textContent = "▶"; }});

// 検索からの deep-link 対応: ?t=SEC で音源を該当位置から再生 + #tl-tw-XXX #tl-ch-XXX にスクロール
(function() {{
  const params = new URLSearchParams(location.search);
  const t = params.get("t");
  const hash = location.hash;

  // ハッシュがあれば該当要素にスクロール
  if (hash) {{
    setTimeout(() => {{
      const el = document.querySelector(hash);
      if (!el) return;
      // タイムラインタブがアクティブでない場合は切り替え
      const tabContainer = el.closest(".tab-container");
      if (tabContainer) {{
        const targetPanel = el.closest(".tab-panel");
        if (targetPanel) {{
          tabContainer.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
          tabContainer.querySelectorAll(".tab-panel").forEach(p => p.classList.remove("active"));
          targetPanel.classList.add("active");
          const targetBtn = tabContainer.querySelector('[data-target="' + targetPanel.id + '"]');
          if (targetBtn) targetBtn.classList.add("active");
        }}
      }}
      el.scrollIntoView({{behavior: "smooth", block: "center"}});
      el.classList.add("scroll-target-flash");
      setTimeout(() => el.classList.remove("scroll-target-flash"), 3000);
    }}, 100);
  }}

  if (!t) return;
  const startSec = parseInt(t, 10);
  if (isNaN(startSec)) return;
  const someClick = document.querySelector("[onclick*=\\"playChapter(\\"]");
  if (!someClick) return;
  const m = someClick.getAttribute("onclick").match(/playChapter\\('([^']+)'/);
  if (!m) return;
  const src = m[1];
  loadAudio(src, "検索から再生", "@ " + fmt(startSec));
  const doPlay = () => {{ audio.currentTime = startSec; audio.play(); }};
  if (audio.readyState >= 1) doPlay();
  else audio.addEventListener("loadedmetadata", doPlay, {{once: true}});
}})();
</script>

</body></html>"""


GA_SNIPPET_TEMPLATE = """<script async src="https://www.googletagmanager.com/gtag/js?id={mid}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', '{mid}', {{ anonymize_ip: true }});
</script>
"""


def render_layout(*, title, body, level=0, active_nav=""):
    """level: 0=root, 1=under sub-dir like episode/, tag/, speaker/"""
    prefix = "../" if level == 1 else ""
    ga_snippet = GA_SNIPPET_TEMPLATE.format(mid=GA_MEASUREMENT_ID) if GA_MEASUREMENT_ID else ""
    return LAYOUT.format(
        title=html.escape(title),
        css=prefix + "style.css",
        home=prefix + "index.html",
        logo_url=prefix + "assets/logo.png",
        episodes_link=prefix + "episodes.html",
        tags_link=prefix + "tags.html",
        speakers_link=prefix + "speakers.html",
        search_link=prefix + "search.html",
        privacy_link=prefix + "privacy.html",
        nav_ep_class=' class="active"' if active_nav == "episodes" else "",
        nav_tag_class=' class="active"' if active_nav == "tags" else "",
        nav_sp_class=' class="active"' if active_nav == "speakers" else "",
        container_class=" narrow" if level == 1 else "",
        ga_snippet=ga_snippet,
        body=body,
    )


WEEKDAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]


def _fmt_ep_date_block(date_str):
    """'2026-08-06' -> {y, md, wd} 表示用の分割"""
    try:
        d = date.fromisoformat(date_str)
        return {
            "y": str(d.year),
            "md": f"{d.month}/{d.day}",
            "wd": WEEKDAYS_JP[d.weekday()],
        }
    except Exception:
        return {"y": "", "md": date_str, "wd": ""}


def render_ep_card(ep, level=0):
    """回カード（一覧向け）"""
    prefix = "../" if level == 1 else ""
    ep_link = f"{prefix}episode/{ep_slug(ep)}.html" if ep["ep"] else "#"
    ep_num = ep["ep"] or "?"
    # スピーカー chip (アバター + 名前)
    speaker_chips = []
    for sp in ep["speakers"][:4]:
        speaker_chips.append(
            f'<span class="ep-speaker-chip">'
            f'{avatar_img(sp["handle"], size=20, css_class="avatar")}'
            f'<span class="ep-speaker-name">{html.escape(sp["name"])}</span>'
            f'</span>'
        )
    if len(ep["speakers"]) > 4:
        speaker_chips.append(
            f'<span class="ep-speaker-more">ほか{len(ep["speakers"])-4}名</span>'
        )
    speakers_html = "".join(speaker_chips)
    tags_html = ""
    ep_tags = (ep["chapters_data"] or {}).get("episode_tags", []) if ep["chapters_data"] else []
    if ep_tags:
        for t in ep_tags[:5]:
            tags_html += f'<a class="tag" href="{prefix}tag/{slug_tag(t)}.html">{html.escape(t)}</a>'
        if len(ep_tags) > 5:
            tags_html += f'<span class="text-muted" style="font-size:12px;">…+{len(ep_tags)-5}</span>'
    elif ep["recording"]:
        tags_html = '<span class="text-muted" style="font-size:12px;">タグ抽出待ち</span>'

    audio_src = audio_url(ep.get("audio_filename"), level)
    js_title = html.escape(ep["title"] or "", quote=True)
    js_date = html.escape(ep["date"], quote=True)
    duration_sec = get_audio_duration_sec(ep.get("audio_filename"))
    duration_str = fmt_duration_short(duration_sec)
    # meta 上段 = 第XX回・時間長・録音なし表示
    meta_short_parts = [f"第{ep_num}回"]
    if duration_str:
        meta_short_parts.append(duration_str)
    if not ep['recording']:
        meta_short_parts.append("録音なし")
    meta_short = " · ".join(meta_short_parts)
    # この回の要約 (chapters_data から取得、簡易表示では隠す)
    summary = ""
    if ep.get("chapters_data"):
        summary = ep["chapters_data"].get("episode_summary", "").strip()
    summary_html = f'<div class="ep-summary">{html.escape(summary)}</div>' if summary else ''
    dblock = _fmt_ep_date_block(ep["date"])
    # フィルタ/ソート用の data 属性
    speaker_handles = ",".join(sp["handle"] for sp in ep["speakers"])
    ep_tag_list = ep_tags if ep_tags else []
    tag_names_attr = ",".join(ep_tag_list)
    tweet_count = 0
    if ep.get("tweets_data"):
        tweet_count = len(ep["tweets_data"].get("tweets", []))
    chapter_count = 0
    if ep.get("chapters_data"):
        chapter_count = len(ep["chapters_data"].get("chapters", []))
    return f'''
  <div class="ep-card clickable" data-href="{ep_link}"
       data-year="{ep["date"][:4]}"
       data-date="{ep["date"]}"
       data-ep="{ep_num}"
       data-speakers="{html.escape(speaker_handles, quote=True)}"
       data-tags="{html.escape(tag_names_attr, quote=True)}"
       data-duration="{duration_sec or 0}"
       data-tweet-count="{tweet_count}"
       data-chapter-count="{chapter_count}"
       data-recording="{1 if ep['recording'] else 0}">
    <div class="ep-date-block">
      <div class="ep-date-md">{dblock["md"]}</div>
      <div class="ep-date-wd">({dblock["wd"]})</div>
      <div class="ep-date-y">{dblock["y"]}</div>
    </div>
    <div>
      <div class="ep-title"><a href="{ep_link}">{html.escape(ep["title"] or "無題")}</a></div>
      <div class="ep-meta">{meta_short}</div>
      <div class="ep-speakers">{speakers_html}</div>
      {summary_html}
      <div class="ep-tags">{tags_html}</div>
    </div>
    <button class="ep-play-btn" onclick="loadAudio('{audio_src}','{js_title}','{js_date}');togglePlay();">▶</button>
  </div>'''


# ============ PAGE BUILDERS ============

def build_index(episodes, tag_stats, speaker_stats):
    tag_chapters, tag_episodes = tag_stats
    total_h = sum(1.5 for ep in episodes if ep["recording"])  # rough
    recent = [ep for ep in reversed(episodes) if ep["ep"]][:5]
    body = f'''
  <div class="hero hero-branded">
    <div class="hero-content">
      <img src="assets/logo.png" alt="Vizトーク" class="hero-logo">
      <div>
        <h1>Vizトーク アーカイブ</h1>
        <p>X (旧Twitter) のスペースで毎週木曜 22:30 頃から開催されている、
          Tableauやデータ可視化について語り合うトーク番組の非公式アーカイブ。</p>
        <p class="text-muted" style="font-size:13px;">全放送を検索・チャプター単位で再生できます。</p>
      </div>
    </div>
    <div class="stats">
      <div class="stat"><div class="num">{len(episodes)}</div><div class="label">回</div></div>
      <div class="stat"><div class="num">{int(total_h)}h+</div><div class="label">総時間(推定)</div></div>
      <div class="stat"><div class="num">{len(speaker_stats)}</div><div class="label">スピーカー</div></div>
      <div class="stat"><div class="num">{len(tag_episodes)}</div><div class="label">トピック</div></div>
    </div>
  </div>

  <h2 class="section-title">最新の回</h2>
  {"".join(render_ep_card(ep) for ep in recent)}

  <h2 class="section-title">人気のトピック</h2>
  <div class="tag-cloud">
'''
    top_tags = sorted(tag_episodes.items(), key=lambda x: -len(x[1]))[:20]
    for tag, eps in top_tags:
        body += f'<a class="tag big" href="tag/{slug_tag(tag)}.html">{html.escape(tag)} <span class="count">({len(eps)})</span></a>\n'
    body += '</div>'
    return render_layout(title="Vizトーク アーカイブ", body=body, level=0)


def build_episodes_list(episodes):
    # 新しい順に並べて年でグループ化
    valid = [ep for ep in episodes if ep["ep"]]
    valid.sort(key=lambda e: e["date"], reverse=True)

    # フィルタUI用の集計
    speaker_counts = Counter()
    speaker_names = {}
    for ep in valid:
        for sp in ep["speakers"]:
            speaker_counts[sp["handle"]] += 1
            speaker_names[sp["handle"]] = sp["name"]
    tag_counts = Counter()
    for ep in valid:
        ct = ep.get("chapters_data") or {}
        for t in ct.get("episode_tags", []) or []:
            tag_counts[t] += 1

    speaker_json = json.dumps(
        {h: speaker_names[h] for h in speaker_counts.keys()},
        ensure_ascii=False,
    )

    groups = {}
    for ep in valid:
        year = ep["date"][:4]
        groups.setdefault(year, []).append(ep)
    current_year = max(groups.keys()) if groups else None

    sections_html = ""
    for year in sorted(groups.keys(), reverse=True):
        eps_in_year = groups[year]
        cards = "".join(render_ep_card(ep) for ep in eps_in_year)
        is_open = (year == current_year)
        collapsed_class = "" if is_open else " collapsed"
        arrow = "▼" if is_open else "▶"
        sections_html += f'''
  <div class="year-group{collapsed_class}" data-year="{year}" id="year-{year}">
    <h2 class="year-header" onclick="toggleYear(this)">
      <span class="year-toggle">{arrow}</span>
      <span class="year-label">{year}年</span>
      <span class="year-count">({len(eps_in_year)}回)</span>
    </h2>
    <div class="year-body">
      {cards}
    </div>
  </div>'''

    year_nav = " ".join(
        f'<a href="#year-{y}" onclick="expandYear(\'{y}\')">{y}</a>'
        for y in sorted(groups.keys(), reverse=True)
    )

    # スピーカー・タグ フィルタ選択肢UI
    speakers_ui = ""
    for h, cnt in sorted(speaker_counts.items(), key=lambda x: -x[1]):
        speakers_ui += (
            f'<label class="filter-chk">'
            f'<input type="checkbox" data-filter="speaker" value="{html.escape(h, quote=True)}">'
            f'<span>{html.escape(speaker_names[h])} <span class="cnt">({cnt})</span></span>'
            f'</label>'
        )
    tags_ui = ""
    top_50_tags = tag_counts.most_common(50)
    for t, cnt in top_50_tags:
        tags_ui += (
            f'<label class="filter-chk">'
            f'<input type="checkbox" data-filter="tag" value="{html.escape(t, quote=True)}">'
            f'<span>{html.escape(t)} <span class="cnt">({cnt})</span></span>'
            f'</label>'
        )

    body = f'''
  <h1 style="margin-bottom:8px;">トーク一覧 <span class="text-muted" style="font-size:.6em;font-weight:normal;">全{len(valid)}回</span></h1>

  <div class="ep-list-controls">
    <button class="filter-btn" onclick="toggleFilterPanel()">
      🔍 フィルタ <span id="filter-count-badge"></span>
    </button>
    <div class="sort-group">
      <label class="text-muted" style="font-size:12px;">並び順:</label>
      <select id="ep-sort" onchange="onSortChange(this.value)">
        <option value="date-desc">日付 (新→古)</option>
        <option value="date-asc">日付 (古→新)</option>
        <option value="duration-desc">再生時間 (長→短)</option>
        <option value="duration-asc">再生時間 (短→長)</option>
        <option value="tweetCount-desc">実況ツイート数 (多→少)</option>
        <option value="chapterCount-desc">チャプター数 (多→少)</option>
      </select>
    </div>
    <div class="view-toggle" role="group">
      <span class="text-muted" style="font-size:12px;">表示:</span>
      <button data-view="card" class="view-btn active" onclick="setView('card')">⊞ カード</button>
      <button data-view="compact" class="view-btn" onclick="setView('compact')">☰ 簡易</button>
    </div>
  </div>

  <div class="filter-panel" id="filter-panel" style="display:none;">
    <div class="filter-group">
      <h4>スピーカー <span class="text-muted" style="font-size:11px;">(選択でその人が出た回)</span></h4>
      <div class="filter-checkboxes">{speakers_ui}</div>
    </div>
    <div class="filter-group">
      <h4>トピック <span class="text-muted" style="font-size:11px;">(Top 50、選択でそのトピックが含まれる回)</span></h4>
      <div class="filter-checkboxes filter-tag-grid">{tags_ui}</div>
    </div>
    <div class="filter-group filter-radios">
      <h4>録音</h4>
      <label class="filter-radio"><input type="radio" name="rec-filter" value="all" checked> すべて</label>
      <label class="filter-radio"><input type="radio" name="rec-filter" value="1"> 録音あり</label>
      <label class="filter-radio"><input type="radio" name="rec-filter" value="0"> 録音なし</label>
    </div>
    <div class="filter-actions">
      <button onclick="clearAllFilters()" class="mini-btn">すべてクリア</button>
    </div>
  </div>

  <div class="year-nav-row">
    <span class="text-muted" style="font-size:12px;">ジャンプ:</span>
    {year_nav}
    <button onclick="expandAll(true)" class="mini-btn">全て展開</button>
    <button onclick="expandAll(false)" class="mini-btn">全て折りたたむ</button>
    <span class="ep-list-summary" id="ep-list-summary"></span>
  </div>

  <div class="active-filters" id="active-filters" style="display:none;"></div>

  <div class="ep-list" id="ep-list">
    {sections_html}
  </div>

<script>
const SPEAKER_NAMES = {speaker_json};
const state = {{
  speakers: new Set(),
  tags: new Set(),
  recording: "all",
  sort: "date-desc",
}};

function toggleYear(header) {{
  header.closest(".year-group").classList.toggle("collapsed");
  const arrow = header.querySelector(".year-toggle");
  if (arrow) arrow.textContent = header.closest(".year-group").classList.contains("collapsed") ? "▶" : "▼";
}}
function expandYear(year) {{
  const g = document.getElementById("year-" + year);
  if (g) {{
    g.classList.remove("collapsed");
    const arrow = g.querySelector(".year-toggle");
    if (arrow) arrow.textContent = "▼";
  }}
}}
function expandAll(open) {{
  document.querySelectorAll(".year-group").forEach(g => {{
    if (open) g.classList.remove("collapsed"); else g.classList.add("collapsed");
    const arrow = g.querySelector(".year-toggle");
    if (arrow) arrow.textContent = open ? "▼" : "▶";
  }});
}}
function setView(mode) {{
  const list = document.getElementById("ep-list");
  list.classList.toggle("view-compact", mode === "compact");
  list.classList.toggle("view-card", mode === "card");
  document.querySelectorAll(".view-btn").forEach(b => b.classList.toggle("active", b.dataset.view === mode));
  try {{ localStorage.setItem("epListView", mode); }} catch (e) {{}}
}}
function toggleFilterPanel() {{
  const p = document.getElementById("filter-panel");
  p.style.display = p.style.display === "none" ? "" : "none";
}}

function updateFilterBadge() {{
  const n = state.speakers.size + state.tags.size + (state.recording !== "all" ? 1 : 0);
  const b = document.getElementById("filter-count-badge");
  b.textContent = n ? `(${{n}})` : "";
  b.classList.toggle("has-filters", n > 0);
}}

function updateActiveChips() {{
  const chips = document.getElementById("active-filters");
  const parts = [];
  state.speakers.forEach(h => {{
    const name = SPEAKER_NAMES[h] || h;
    parts.push(`<span class="active-chip">${{escapeHtml(name)}} <button data-clear="speaker" data-val="${{escapeHtml(h)}}">×</button></span>`);
  }});
  state.tags.forEach(t => {{
    parts.push(`<span class="active-chip">${{escapeHtml(t)}} <button data-clear="tag" data-val="${{escapeHtml(t)}}">×</button></span>`);
  }});
  if (state.recording === "1") parts.push(`<span class="active-chip">録音あり <button data-clear="rec">×</button></span>`);
  if (state.recording === "0") parts.push(`<span class="active-chip">録音なし <button data-clear="rec">×</button></span>`);
  if (parts.length) {{
    chips.innerHTML = "適用中: " + parts.join(" ") + ' <button class="mini-btn" onclick="clearAllFilters()">クリア</button>';
    chips.style.display = "";
  }} else {{
    chips.innerHTML = "";
    chips.style.display = "none";
  }}
}}

function escapeHtml(s) {{
  return String(s).replace(/[&<>"']/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}}[c]));
}}

function applyFilters() {{
  const cards = document.querySelectorAll(".ep-card[data-year]");
  let shown = 0;
  const yearCounts = {{}};
  cards.forEach(card => {{
    const cardSpeakers = (card.dataset.speakers || "").split(",").filter(Boolean);
    const cardTags = (card.dataset.tags || "").split(",").filter(Boolean);
    const cardRec = card.dataset.recording;
    const cardYear = card.dataset.year;
    let ok = true;
    if (state.speakers.size && !cardSpeakers.some(h => state.speakers.has(h))) ok = false;
    if (state.tags.size && !cardTags.some(t => state.tags.has(t))) ok = false;
    if (state.recording !== "all" && cardRec !== state.recording) ok = false;
    card.style.display = ok ? "" : "none";
    if (ok) {{
      shown++;
      yearCounts[cardYear] = (yearCounts[cardYear] || 0) + 1;
    }}
  }});
  document.querySelectorAll(".year-group").forEach(g => {{
    const y = g.dataset.year;
    const total = g.querySelectorAll(".ep-card").length;
    const shownCount = yearCounts[y] || 0;
    const countEl = g.querySelector(".year-count");
    const anyFilter = state.speakers.size || state.tags.size || state.recording !== "all";
    if (countEl) countEl.textContent = anyFilter ? `(${{shownCount}}/${{total}}回)` : `(${{total}}回)`;
    g.style.display = shownCount ? "" : "none";
  }});
  const total = cards.length;
  const anyFilter = state.speakers.size || state.tags.size || state.recording !== "all";
  document.getElementById("ep-list-summary").textContent = anyFilter ? `表示: ${{shown}} / ${{total}}回` : "";
}}

function applySort() {{
  const [key, dir] = state.sort.split("-");
  document.querySelectorAll(".year-group .year-body").forEach(body => {{
    const cards = Array.from(body.querySelectorAll(".ep-card"));
    cards.sort((a, b) => {{
      let va = 0, vb = 0;
      if (key === "date") {{ va = a.dataset.date; vb = b.dataset.date; }}
      else if (key === "duration") {{ va = parseInt(a.dataset.duration) || 0; vb = parseInt(b.dataset.duration) || 0; }}
      else if (key === "tweetCount") {{ va = parseInt(a.dataset.tweetCount) || 0; vb = parseInt(b.dataset.tweetCount) || 0; }}
      else if (key === "chapterCount") {{ va = parseInt(a.dataset.chapterCount) || 0; vb = parseInt(b.dataset.chapterCount) || 0; }}
      if (va === vb) return 0;
      return dir === "asc" ? (va > vb ? 1 : -1) : (va < vb ? 1 : -1);
    }});
    cards.forEach(c => body.appendChild(c));
  }});
}}

function updateUrl() {{
  const p = new URLSearchParams();
  if (state.speakers.size) p.set("speakers", [...state.speakers].join(","));
  if (state.tags.size) p.set("tags", [...state.tags].join(","));
  if (state.recording !== "all") p.set("rec", state.recording);
  if (state.sort !== "date-desc") p.set("sort", state.sort);
  const q = p.toString();
  history.replaceState(null, "", location.pathname + (q ? "?" + q : ""));
}}

function apply() {{
  updateFilterBadge();
  updateActiveChips();
  applyFilters();
  applySort();
  updateUrl();
}}

function onSortChange(v) {{ state.sort = v; apply(); }}

function clearAllFilters() {{
  state.speakers.clear();
  state.tags.clear();
  state.recording = "all";
  document.querySelectorAll('input[data-filter="speaker"], input[data-filter="tag"]').forEach(el => el.checked = false);
  document.querySelectorAll('input[name="rec-filter"]').forEach(el => el.checked = el.value === "all");
  apply();
}}

// UI 変更ハンドラ
document.addEventListener("change", (e) => {{
  const el = e.target;
  if (el.dataset && el.dataset.filter === "speaker") {{
    if (el.checked) state.speakers.add(el.value); else state.speakers.delete(el.value);
    apply();
  }} else if (el.dataset && el.dataset.filter === "tag") {{
    if (el.checked) state.tags.add(el.value); else state.tags.delete(el.value);
    apply();
  }} else if (el.name === "rec-filter") {{
    state.recording = el.value;
    apply();
  }}
}});

// アクティブchipのXボタン
document.addEventListener("click", (e) => {{
  const btn = e.target.closest("button[data-clear]");
  if (!btn) return;
  const kind = btn.dataset.clear;
  const val = btn.dataset.val;
  if (kind === "speaker") {{
    state.speakers.delete(val);
    const inp = document.querySelector(`input[data-filter="speaker"][value="${{CSS.escape(val)}}"]`);
    if (inp) inp.checked = false;
  }} else if (kind === "tag") {{
    state.tags.delete(val);
    const inp = document.querySelector(`input[data-filter="tag"][value="${{CSS.escape(val)}}"]`);
    if (inp) inp.checked = false;
  }} else if (kind === "rec") {{
    state.recording = "all";
    document.querySelectorAll('input[name="rec-filter"]').forEach(el => el.checked = el.value === "all");
  }}
  apply();
}});

// URLからの初期状態復元
(function() {{
  const p = new URLSearchParams(location.search);
  const sp = p.get("speakers");
  if (sp) sp.split(",").filter(Boolean).forEach(h => state.speakers.add(h));
  const tg = p.get("tags");
  if (tg) tg.split(",").filter(Boolean).forEach(t => state.tags.add(t));
  const rec = p.get("rec");
  if (rec) state.recording = rec;
  const sort = p.get("sort");
  if (sort) state.sort = sort;
  // UI に反映
  document.querySelectorAll('input[data-filter="speaker"]').forEach(el => el.checked = state.speakers.has(el.value));
  document.querySelectorAll('input[data-filter="tag"]').forEach(el => el.checked = state.tags.has(el.value));
  document.querySelectorAll('input[name="rec-filter"]').forEach(el => el.checked = el.value === state.recording);
  document.getElementById("ep-sort").value = state.sort;
  // 表示モード
  let saved = "card";
  try {{ saved = localStorage.getItem("epListView") || "card"; }} catch (e) {{}}
  setView(saved);
  // フィルタがアクティブならパネル開いておく
  if (state.speakers.size || state.tags.size || state.recording !== "all") {{
    document.getElementById("filter-panel").style.display = "";
  }}
  apply();
}})();
</script>
'''
    return render_layout(title="トーク一覧 · Vizトーク Archive", body=body, level=0, active_nav="episodes")


def build_episode_detail(ep):
    """個別回ページ"""
    audio_ready = ep.get("audio_filename") is not None
    src = audio_url(ep.get("audio_filename"), level=1)

    speakers_html_parts = []
    role_groups = defaultdict(list)
    for sp in ep["speakers"]:
        role_groups[sp["role"]].append(sp)
    role_order = ["ホスト", "共同ホスト", "スピーカー"]
    for role in role_order:
        if role in role_groups:
            speakers_html_parts.append(f'<span class="role-label">{html.escape(role)}</span>')
            for sp in role_groups[role]:
                speakers_html_parts.append(
                    f'<a class="speaker-chip" href="../speaker/{slug_handle(sp["handle"])}.html">'
                    f'{html.escape(sp["name"])} (@{html.escape(sp["handle"])})</a>'
                )
            speakers_html_parts.append("<br>")

    ch_data = ep["chapters_data"]
    summary_html = ""
    tags_html = ""
    chapters_body = ""
    chapters_count = 0
    if ch_data:
        summary_html = f'''
    <div class="summary">
      <strong>この回の要約:</strong><br>
      {html.escape(ch_data.get("episode_summary", ""))}
    </div>'''
        ep_tags = ch_data.get("episode_tags", [])
        if ep_tags:
            tags_html = f'<h2 class="section-title">タグ ({len(ep_tags)})</h2><div>'
            for t in ep_tags:
                tags_html += f'<a class="tag" href="../tag/{slug_tag(t)}.html">{html.escape(t)}</a>'
            tags_html += '</div>'
        chapters_list = ch_data.get("chapters", [])
        chapters_count = len(chapters_list)
        chapters_body = '<div class="chapters">'
        for ch in chapters_list:
            title = html.escape(ch.get("title", ""))
            summary = html.escape(ch.get("summary", ""))
            start = ch.get("start", "0:00:00")
            tags_line = "".join(
                f'<a class="tag" href="../tag/{slug_tag(t)}.html" onclick="event.stopPropagation();">{html.escape(t)}</a>'
                for t in ch.get("tags", []) or [])
            js_title = html.escape(f"第{ep['ep']}回: {ch.get('title','')}", quote=True)
            js_sub = html.escape(f"{ep['date']} ({start})", quote=True)
            chapters_body += f'''
    <div class="chapter" data-audio-time="{ts_to_sec(start)}" onclick="playChapter('{src}','{start}','{js_title}','{js_sub}')">
      <button class="play-btn">▶</button>
      <div class="ts">{start}</div>
      <div class="body">
        <h3>{title}</h3>
        <p>{summary}</p>
        <div>{tags_line}</div>
      </div>
    </div>'''
        chapters_body += '</div>'
    else:
        chapters_body = '<p class="text-muted"><em>まだ抽出されていません</em></p>'

    # 実況ツイート
    tw_data = ep.get("tweets_data")
    tweets_body = ""
    tweets_count = 0
    audio_start_display = ""
    audio_start_source = ""
    if tw_data and tw_data.get("tweets"):
        tweets_list = tw_data["tweets"]
        tweets_count = len(tweets_list)
        audio_start_display = tw_data.get("_audio_start_jst_display", "")
        audio_start_source = tw_data.get("_audio_start_source", "")
        tweets_body = '<div class="tweets">'
        for t in tweets_list:
            tweets_body += render_tweet_card(t, src, ep)
        tweets_body += '</div>'
    elif audio_ready:
        tweets_body = f'''<p class="text-muted"><em>まだ収集されていません。
  <a href="{x_live_search_url(ep["date"]) or "#"}" target="_blank" rel="noopener">#Vizトーク の実況ツイートをXで見る ↗</a></em></p>'''

    # 統合タイムライン (chapters + tweets を時系列に混ぜる)
    timeline_body = ""
    timeline_count = chapters_count + tweets_count
    if ch_data or (tw_data and tw_data.get("tweets")):
        events = []
        if ch_data:
            for ch in ch_data.get("chapters", []):
                events.append(("chapter", ts_to_sec(ch.get("start", "0:00:00")), ch))
        if tw_data and tw_data.get("tweets"):
            for t in tw_data["tweets"]:
                events.append(("tweet", int(t.get("_audio_offset_sec", 0)), t))
        events.sort(key=lambda e: e[1])
        timeline_body = '<div class="timeline">'
        for kind, sec, obj in events:
            if kind == "chapter":
                title = html.escape(obj.get("title", ""))
                summary = html.escape(obj.get("summary", ""))
                start = obj.get("start", "0:00:00")
                tags_line = "".join(
                    f'<a class="tag" href="../tag/{slug_tag(t)}.html" onclick="event.stopPropagation();">{html.escape(t)}</a>'
                    for t in obj.get("tags", []) or [])
                js_title = html.escape(f"第{ep['ep']}回: {obj.get('title','')}", quote=True)
                js_sub = html.escape(f"{ep['date']} ({start})", quote=True)
                timeline_body += f'''
    <div class="timeline-chapter chapter" id="tl-ch-{sec}" data-audio-time="{sec}" onclick="playChapter('{src}','{start}','{js_title}','{js_sub}')">
      <div class="timeline-marker">📖</div>
      <div class="chapter-content">
        <div class="chapter-header">
          <button class="play-btn">▶</button>
          <div class="ts">{start}</div>
          <div class="chapter-title-line">CHAPTER · {title}</div>
        </div>
        <p>{summary}</p>
        <div>{tags_line}</div>
      </div>
    </div>'''
            else:
                tid = obj.get("id", "")
                timeline_body += f'<div class="timeline-tweet" id="tl-tw-{tid}">' + render_tweet_card(obj, src, ep) + '</div>'
        timeline_body += '</div>'

    # タブ構造にまとめる
    show_tabs = bool(chapters_body or tweets_body)
    listen_html = ""
    if show_tabs:
        listen_html = f'''
  <div class="tab-container">
    <div class="tabs" role="tablist">
      <button class="tab-btn active" data-target="tab-timeline">🎬 タイムライン ({timeline_count})</button>
      <button class="tab-btn" data-target="tab-chapters">📖 チャプター ({chapters_count})</button>
      <button class="tab-btn" data-target="tab-tweets">🐦 ツイート ({tweets_count})</button>
    </div>
    {("<p class='text-muted' style='font-size:12px;margin:8px 0 0;'>音源開始想定時刻: <code>" + html.escape(audio_start_display) + "</code> <span style='font-size:11px;'>(" + html.escape(audio_start_source) + ")</span></p>") if audio_start_display else ""}
    <div id="tab-timeline" class="tab-panel active">{timeline_body}</div>
    <div id="tab-chapters" class="tab-panel">{chapters_body}</div>
    <div id="tab-tweets" class="tab-panel">{tweets_body}</div>
  </div>'''

    audio_status = ""
    if not audio_ready:
        audio_status = '<div class="summary" style="border-left-color:#e00;background:#fff5f5;">⚠ 音源ファイルが見つかりません</div>'

    # 全文文字起こし (Pagefindで検索対象になる)
    transcript_html = ""
    segs = ep.get("transcript_segments") or []
    if segs:
        # 10セグメントごとに段落化、タイムスタンプクリックで seek
        chunks_html = []
        buf = []
        buf_start = None
        for seg in segs:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            if buf_start is None:
                buf_start = seg["start"]
            buf.append(text)
            if len(buf) >= 10:
                para_start = fmt_ts_hms(buf_start)
                chunks_html.append(
                    f'<p class="tr-para"><span class="tr-ts" '
                    f'onclick="playChapter(\'{src}\',\'{int(buf_start)}\',\'第{ep["ep"]}回 全文\',\'{ep["date"]}\');event.stopPropagation();">'
                    f'{para_start}</span> {html.escape(" ".join(buf))}</p>'
                )
                buf = []
                buf_start = None
        if buf:
            para_start = fmt_ts_hms(buf_start or 0)
            chunks_html.append(
                f'<p class="tr-para"><span class="tr-ts" '
                f'onclick="playChapter(\'{src}\',\'{int(buf_start or 0)}\',\'第{ep["ep"]}回 全文\',\'{ep["date"]}\');event.stopPropagation();">'
                f'{para_start}</span> {html.escape(" ".join(buf))}</p>'
            )
        transcript_html = f'''
  <details class="transcript-full">
    <summary>📝 全文書き起こし ({len(segs)}セグメント · {sum(len((s.get("text") or "").strip()) for s in segs):,}文字) — クリックで展開</summary>
    <div class="transcript-content">
      {"".join(chunks_html)}
    </div>
  </details>'''

    body = f'''
  <p class="text-muted"><a href="../index.html">Home</a> › <a href="../episodes.html">トーク一覧</a> › 第{ep["ep"]}回</p>
  <main data-pagefind-body>
  <div class="ep-header" data-pagefind-meta="title:第{ep['ep']}回 {html.escape(ep['title'])}, date:{ep['date']}, ep:{ep['ep']}">
    <div class="ep-meta-row" data-pagefind-ignore>
      <span>📅 {ep["date"]}</span>
      <span>{'🎧 録音あり' if ep["recording"] else '🚫 録音なし'}</span>
      <span><a href="{html.escape(ep["url"])}" target="_blank" rel="noopener">元スペースをXで開く ↗</a></span>
      <span><a href="{x_live_search_url(ep["date"]) or "#"}" target="_blank" rel="noopener">#Vizトーク の実況ツイートを見る ↗</a></span>
    </div>
    <h1>{html.escape(ep["title"])}</h1>

    <div class="speakers">
      {" ".join(speakers_html_parts)}
    </div>

    {audio_status}
    {summary_html}
  </div>

  <div style="margin:14px 0;" data-pagefind-ignore>
    <button class="ep-play-btn" style="width:auto;padding:8px 20px;font-size:14px;border-radius:6px;"
      onclick="playChapter('{src}','0:00:00','{html.escape('第'+str(ep['ep'])+'回 冒頭から', quote=True)}','{html.escape(ep['date'], quote=True)}')">
      ▶ 最初から再生
    </button>
  </div>

  {tags_html}
  <h2 class="section-title">聴きながら追う (再生位置と連動)</h2>
  {listen_html}

  {transcript_html}
  </main>
'''
    return render_layout(title=f"Vizトーク 第{ep['ep']}回", body=body, level=1)


def build_tags_list(tag_stats):
    tag_chapters, tag_episodes = tag_stats
    body = '<h1 style="margin-bottom:16px;">トピック一覧 <span class="text-muted" style="font-size:.6em;font-weight:normal;">全' + str(len(tag_episodes)) + 'トピック</span></h1>'
    body += '<p class="text-muted mt">タグの右の数字は登場回数（回数）です。クリックで詳細ページ。</p>'
    body += '''<div class="filter-bar"><label>並び順:</label>
      <select id="tag-sort" onchange="sortItems('tag-cloud', this.value, {desc: this.value==='count'})">
        <option value="count">登場回数順</option>
        <option value="name">50音順</option>
      </select></div>'''
    body += '<div class="tag-cloud mt" id="tag-cloud">'
    sorted_tags = sorted(tag_episodes.items(), key=lambda x: (-len(x[1]), x[0]))
    for tag, eps in sorted_tags:
        body += (f'<a class="tag big" href="tag/{slug_tag(tag)}.html" '
                 f'data-name="{html.escape(tag, quote=True)}" data-count="{len(eps)}">'
                 f'{html.escape(tag)} <span class="count">({len(eps)})</span></a>\n')
    body += '</div>'
    return render_layout(title="トピック一覧 · Vizトーク Archive", body=body, level=0, active_nav="tags")


def build_tag_detail(tag, chapters_list, tag_episodes):
    body = f'<p class="text-muted"><a href="../index.html">Home</a> › <a href="../tags.html">トピック</a> › {html.escape(tag)}</p>'
    body += f'''
  <div class="hero" style="padding:24px;">
    <h1># {html.escape(tag)}</h1>
    <div class="mt">
      <span class="text-muted" style="font-size:13px;">登場回数:</span> <strong>{len(tag_episodes)}回</strong>
      &nbsp; <span class="text-muted" style="font-size:13px;">総チャプター数:</span> <strong>{len(chapters_list)}</strong>
    </div>
  </div>

  <h2 class="section-title">このトピックが登場したチャプター ({len(chapters_list)})</h2>
  <p class="text-muted" style="font-size:13px;">クリックでその場所から再生します</p>
  <div class="chapters">
'''
    # 新しい順にソート
    sorted_list = sorted(chapters_list, key=lambda x: x[0]["date"], reverse=True)
    for ep, ch in sorted_list:
        title = html.escape(ch.get("title", ""))
        summary = html.escape(ch.get("summary", ""))
        start = ch.get("start", "0:00:00")
        src = audio_url(ep.get("audio_filename"), level=1)
        js_title = html.escape(f"第{ep['ep']}回: {ch.get('title','')}", quote=True)
        js_sub = html.escape(f"{ep['date']} ({start})", quote=True)
        ep_url = f"../episode/{ep_slug(ep)}.html"
        ep_url_at_chapter = f"{ep_url}#tl-ch-{ts_to_sec(start)}"
        other_tags = "".join(
            f'<a class="tag" href="{slug_tag(t)}.html">{html.escape(t)}</a>'
            for t in ch.get("tags", []) or [] if t != tag
        )
        body += f'''
    <div class="chapter chapter-in-tag" onclick="playChapter('{src}','{start}','{js_title}','{js_sub}')">
      <button class="play-btn">▶</button>
      <div class="body">
        <div class="ep-info-row">
          <span class="ep-badge"><a href="{ep_url}" onclick="event.stopPropagation();">第{ep["ep"]}回</a></span>
          <span class="date-badge">{ep["date"]}</span>
          <span class="ts-badge">@ {start}</span>
          <a href="{ep_url_at_chapter}" class="to-ep-link" onclick="event.stopPropagation();">回詳細 →</a>
        </div>
        <h3>{title}</h3>
        <p>{summary}</p>
        <div>{other_tags}</div>
      </div>
    </div>'''
    body += '</div>'
    return render_layout(title=f"{tag} · トピック · Vizトーク Archive", body=body, level=1)


def build_speakers_list(speakers):
    """スピーカー一覧ページ"""
    sorted_sp = sorted(speakers.values(), key=lambda s: -len(s["episodes"]))
    body = f'<h1 style="margin-bottom:16px;">スピーカー一覧 <span class="text-muted" style="font-size:.6em;font-weight:normal;">全{len(speakers)}名</span></h1>'
    body += '<p class="notice-inline">💡 各カードのタグは、そのスピーカーが<strong>出演した回全体のトピック</strong>で、本人の発言内容とは限りません（現状は発話者ごとの識別をしていません）。</p>'
    body += '''<div class="filter-bar"><label>並び順:</label>
      <select id="speaker-sort" onchange="sortItems('speaker-list', this.value, {desc: this.value==='count'})">
        <option value="count">出演回数順</option>
        <option value="name">50音順</option>
      </select></div>'''
    body += '<div class="mt" id="speaker-list">'
    for sp in sorted_sp:
        top_role = sp["roles"].most_common(1)[0][0] if sp["roles"] else ""
        top_tags = sp["tags"].most_common(8)
        tags_html = ""
        if top_tags:
            tags_html = '<div class="speaker-tags-inline">'
            for tag, cnt in top_tags:
                tags_html += (
                    f'<a class="tag" href="tag/{slug_tag(tag)}.html" '
                    f'onclick="event.stopPropagation();">'
                    f'{html.escape(tag)}<span class="count">·{cnt}</span></a>')
            tags_html += '</div>'
        body += f'''
  <div class="ep-card speaker-card" data-name="{html.escape(sp["name"], quote=True)}" data-count="{len(sp["episodes"])}">
    <a href="speaker/{slug_handle(sp["handle"])}.html" class="avatar-link" title="{html.escape(sp["name"])} の詳細">
      {avatar_img(sp["handle"], size=52, css_class="avatar avatar-lg")}
    </a>
    <div>
      <div class="ep-title"><a href="speaker/{slug_handle(sp["handle"])}.html">{html.escape(sp["name"])}</a> <span class="text-muted" style="font-size:.8em;font-weight:normal;">@{html.escape(sp["handle"])}</span> {x_profile_link(sp["handle"])}</div>
      <div class="ep-meta">{top_role} · 出演 <strong>{len(sp["episodes"])}回</strong></div>
      {tags_html}
    </div>
    <div class="speaker-ep-count"><span class="num">{len(sp["episodes"])}</span><span class="label">回出演</span></div>
  </div>'''
    body += '</div>'
    return render_layout(title="スピーカー一覧 · Vizトーク Archive", body=body, level=0, active_nav="speakers")


def build_speaker_detail(sp):
    body = f'<p class="text-muted"><a href="../index.html">Home</a> › <a href="../speakers.html">スピーカー</a> › {html.escape(sp["name"])}</p>'
    body += f'''
  <div class="hero speaker-hero" style="padding:24px;">
    {avatar_img(sp["handle"], size=96, css_class="avatar avatar-xl")}
    <div class="speaker-hero-info">
      <h1>{html.escape(sp["name"])} {x_profile_link(sp["handle"], "x-link-large")}</h1>
      <p class="text-muted mt">@{html.escape(sp["handle"])} · 出演 <strong>{len(sp["episodes"])}回</strong></p>
    <div class="mt">'''
    for role, cnt in sp["roles"].most_common():
        body += f'<span class="tag">{html.escape(role)} × {cnt}</span> '
    body += '</div></div></div>'

    if sp["tags"]:
        body += '<h2 class="section-title">出演回のトピック (Top 15)</h2>'
        body += '<p class="notice-inline" style="margin-top:-4px;">💡 このスピーカー本人が話したトピックではなく、<strong>出演した回全体のトピック</strong>です（発話者ごとの識別は未実装）。</p>'
        body += '<div class="tag-cloud">'
        for tag, cnt in sp["tags"].most_common(15):
            body += f'<a class="tag big" href="../tag/{slug_tag(tag)}.html">{html.escape(tag)} <span class="count">({cnt})</span></a>\n'
        body += '</div>'

    body += f'<h2 class="section-title">出演した回 ({len(sp["episodes"])})</h2>'
    # 新しい順
    for ep in sorted(sp["episodes"], key=lambda e: e["date"], reverse=True):
        speakers_names = ", ".join(s["name"] for s in ep["speakers"][:4])
        ep_link = f'../episode/{ep_slug(ep)}.html'
        body += f'''
  <div class="ep-card clickable" data-href="{ep_link}">
    <div class="ep-num">{ep["ep"]}<small>回</small></div>
    <div>
      <div class="ep-title"><a href="{ep_link}">{html.escape(ep["title"])}</a></div>
      <div class="ep-meta">{ep["date"]} · {html.escape(speakers_names)}</div>
    </div>
    <button class="ep-play-btn" onclick="loadAudio('{audio_url(ep.get("audio_filename"), level=1)}','{html.escape(ep['title'], quote=True)}','{html.escape(ep['date'], quote=True)}');togglePlay();">▶</button>
  </div>'''
    return render_layout(title=f'{sp["name"]} · スピーカー · Vizトーク Archive', body=body, level=1)


# ============ MAIN ============

def build_privacy_page():
    ga_section = ""
    if GA_MEASUREMENT_ID:
        ga_section = f'''
  <h2>アクセス解析について</h2>
  <p>本サイトでは、より良いコンテンツ提供のためのアクセス解析ツールとして
     <strong>Google Analytics 4</strong> を使用しています。</p>

  <h3>収集される情報</h3>
  <ul>
    <li>Cookie ID (ブラウザ識別子)</li>
    <li>IP アドレス（Google の設定で匿名化済み）</li>
    <li>閲覧したページの URL</li>
    <li>リファラー（前に閲覧していたページ）</li>
    <li>ブラウザ・OS・デバイス種別</li>
    <li>訪問日時、滞在時間</li>
  </ul>

  <h3>送信先</h3>
  <p>Google LLC（米国）</p>

  <h3>利用目的</h3>
  <ul>
    <li>サイトの利用状況の把握</li>
    <li>コンテンツの改善</li>
    <li>人気の回・話題の分析</li>
  </ul>

  <h3>Google Analytics のトラッキング ID</h3>
  <p><code>{html.escape(GA_MEASUREMENT_ID)}</code></p>

  <h3>個人の特定について</h3>
  <p>本サイトでは、収集した情報から特定の個人を識別することはできない設定
     （IP アドレスの匿名化、Google シグナル無効）で運用しています。</p>

  <h3>Google Analytics の無効化</h3>
  <p>次のいずれかの方法で本サイトのアクセス解析を無効化できます:</p>
  <ul>
    <li>ブラウザで Cookie を無効化</li>
    <li>
      <a href="https://tools.google.com/dlpage/gaoptout" target="_blank" rel="noopener">
        Google Analytics オプトアウト アドオン
      </a>
      をブラウザにインストール
    </li>
  </ul>

  <p>Google Analytics のデータ取り扱いポリシーについては、
     <a href="https://policies.google.com/privacy" target="_blank" rel="noopener">
       Google プライバシーポリシー
     </a> をご確認ください。</p>
'''

    body = f'''
  <h1>プライバシーポリシー・外部送信ポリシー</h1>

  <p class="text-muted">最終更新: 2026年8月</p>

  <h2>本サイトについて</h2>
  <p>本サイト「Vizトーク アーカイブ」は、X (旧 Twitter) のスペースで開催されている
     <strong>Vizトーク</strong>（ホスト:
     <a href="https://x.com/YusukeNakanish3" target="_blank" rel="noopener">@YusukeNakanish3</a>）
     の非公式ファンサイトです。個人により非営利で運営されています。</p>

  {ga_section}

  <h2>Cookie の使用</h2>
  <p>本サイトは、上記アクセス解析の目的で Cookie を使用します。
     Cookie の受け入れを拒否する設定にすることも可能ですが、その場合本サイトの一部機能が
     ご利用いただけなくなることがあります（音源再生時の位置記憶など）。</p>

  <h2>著作権・音源について</h2>
  <ul>
    <li>各回の音源、発言内容の著作権は、それぞれの出演者に帰属します。</li>
    <li>本アーカイブは、番組の記録・共有を目的として、出演者陣の理解のもとに運営しています。</li>
    <li>文字起こしは AI (OpenAI Whisper) による自動処理のため、誤認識を含みます。</li>
    <li>チャプター分割・タグ抽出は AI (Ollama Qwen) による自動処理です。</li>
  </ul>

  <h2>削除・訂正のご依頼</h2>
  <p>掲載内容について削除・訂正のご要望がある場合は、以下のいずれかの方法でご連絡ください:</p>
  <ul>
    <li>
      <a href="https://github.com/unbosoms/viztalk-archive/issues" target="_blank" rel="noopener">
        GitHub Issues に投稿
      </a>
    </li>
    <li>
      X ダイレクトメッセージ:
      <a href="https://x.com/unbosoms" target="_blank" rel="noopener">@unbosoms</a>
    </li>
  </ul>
  <p>原則として <strong>48時間以内に対応</strong> します。</p>

  <h2>免責事項</h2>
  <ul>
    <li>掲載情報の正確性は保証されません（AI 自動処理を含むため）。</li>
    <li>本サイトの利用により生じた損害について、運営者は責任を負いません。</li>
    <li>予告なくサービスを停止することがあります。</li>
  </ul>

  <h2>ポリシーの改定</h2>
  <p>本ポリシーは予告なく改定される場合があります。改定後の内容は本ページに掲載されます。</p>

  <hr style="margin:2em 0;">
  <p class="text-muted" style="font-size:12px;">
    このポリシーは日本の改正電気通信事業法（外部送信規律、2023年6月施行）に基づき、
    外部送信情報の内容を公表するものです。
  </p>
'''
    return render_layout(title="プライバシーポリシー · Vizトーク Archive", body=body, level=0)


def build_search_index(episodes):
    """クライアント検索用のインデックスJSON。chapters / tweets / episodesを収録。"""
    chapters = []
    tweets = []
    episodes_meta = []
    for ep in episodes:
        if not ep["ep"]:
            continue
        _slug = ep_slug(ep)
        ep_url = f"episode/{_slug}.html"
        speakers_str = ", ".join(sp["name"] for sp in ep["speakers"])
        episodes_meta.append({
            "ep": ep["ep"], "date": ep["date"], "title": ep["title"],
            "speakers": speakers_str, "url": ep_url,
        })
        if ep["chapters_data"]:
            for ch in ep["chapters_data"].get("chapters", []):
                chapters.append({
                    "ep": ep["ep"], "date": ep["date"],
                    "start": ch.get("start", "0:00:00"),
                    "start_sec": ts_to_sec(ch.get("start", "0:00:00")),
                    "title": ch.get("title", ""),
                    "summary": ch.get("summary", ""),
                    "tags": ch.get("tags", []) or [],
                    "url": ep_url,
                })
        if ep["tweets_data"]:
            for t in ep["tweets_data"].get("tweets", []):
                tweets.append({
                    "ep": ep["ep"], "date": ep["date"],
                    "id": t.get("id", ""),
                    "text": t.get("text", ""),
                    "author": t.get("author_name", ""),
                    "handle": t.get("author_handle", ""),
                    "offset": int(t.get("_audio_offset_sec", 0) or 0),
                    "url": ep_url,
                    "tweet_url": t.get("url", ""),
                })
    return {"chapters": chapters, "tweets": tweets, "episodes": episodes_meta}


def build_search_page():
    body = '''
  <h1>検索</h1>
  <input id="search-input" type="text" placeholder="キーワードを入力 (例: Dynamic Zone Visibility, 英会話, さかぴー)" autofocus autocomplete="off">

  <div class="search-tabs" id="search-tabs">
    <button data-filter="all" class="active">すべて <span class="cnt" id="cnt-all">-</span></button>
    <button data-filter="chapters">📖 チャプター <span class="cnt" id="cnt-chapters">-</span></button>
    <button data-filter="tweets">🐦 ツイート <span class="cnt" id="cnt-tweets">-</span></button>
    <button data-filter="episodes">🎙 エピソード <span class="cnt" id="cnt-episodes">-</span></button>
    <button data-filter="fulltext">📝 全文書き起こし <span class="cnt" id="cnt-fulltext">-</span></button>
  </div>

  <div id="results" class="search-results">
    <p class="text-muted">キーワードを入力すると検索します（インデックス読み込み中…）</p>
  </div>

<script>
let INDEX = null;
let FILTER = "all";

async function loadIndex() {
  const res = await fetch("search-index.json");
  INDEX = await res.json();
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
}

function highlight(text, q) {
  if (!q) return esc(text);
  const escaped = q.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&");
  return esc(text).replace(new RegExp("(" + esc(escaped) + ")", "gi"), "<mark>$1</mark>");
}

function fmtSec(sec) {
  const h = Math.floor(sec/3600);
  const m = Math.floor((sec%3600)/60);
  const s = Math.floor(sec%60);
  if (h) return h + ":" + String(m).padStart(2,"0") + ":" + String(s).padStart(2,"0");
  return m + ":" + String(s).padStart(2,"0");
}

let PAGEFIND = null;
let PAGEFIND_PROMISE = null;
async function loadPagefind() {
  if (PAGEFIND) return PAGEFIND;
  if (PAGEFIND_PROMISE) return await PAGEFIND_PROMISE;
  PAGEFIND_PROMISE = (async () => {
    try {
      const m = await import("./pagefind/pagefind.js");
      await m.options({ excerptLength: 40 });
      PAGEFIND = m;
      return m;
    } catch (e) {
      console.error("pagefind load failed", e);
      return null;
    }
  })();
  return await PAGEFIND_PROMISE;
}

async function runFullTextSearch(query) {
  const pf = await loadPagefind();
  if (!pf) return null;
  return await pf.search(query);
}

function renderMetaResults(chMatches, twMatches, epMatches, q) {
  let html = "";
  const showCh = FILTER === "all" || FILTER === "chapters";
  const showTw = FILTER === "all" || FILTER === "tweets";
  const showEp = FILTER === "all" || FILTER === "episodes";

  if (showCh && chMatches.length) {
    html += '<h2 class="search-section-title">📖 チャプター (' + chMatches.length + ')</h2>';
    chMatches.slice(0, 100).forEach(ch => {
      const tagsHtml = (ch.tags||[]).map(t => '<span class="tag">' + esc(t) + '</span>').join('');
      html += `
        <a class="search-result-item" href="${ch.url}?t=${ch.start_sec}#tl-ch-${ch.start_sec}">
          <div class="sri-badge">📖 第${ch.ep}回 · ${esc(ch.date)} · @${esc(ch.start)}</div>
          <div class="sri-title">${highlight(ch.title, q)}</div>
          <div class="sri-body">${highlight(ch.summary, q)}</div>
          <div>${tagsHtml}</div>
        </a>`;
    });
    if (chMatches.length > 100) html += '<p class="text-muted">…以下' + (chMatches.length-100) + '件省略</p>';
  }
  if (showTw && twMatches.length) {
    html += '<h2 class="search-section-title">🐦 ツイート (' + twMatches.length + ')</h2>';
    twMatches.slice(0, 100).forEach(t => {
      html += `
        <a class="search-result-item" href="${t.url}?t=${t.offset}#tl-tw-${t.id}">
          <div class="sri-badge">🐦 第${t.ep}回 · ${esc(t.date)} · @${fmtSec(t.offset)}</div>
          <div class="sri-title">${esc(t.author)} <span class="text-muted">@${esc(t.handle)}</span></div>
          <div class="sri-body">${highlight(t.text, q)}</div>
        </a>`;
    });
    if (twMatches.length > 100) html += '<p class="text-muted">…以下' + (twMatches.length-100) + '件省略</p>';
  }
  if (showEp && epMatches.length) {
    html += '<h2 class="search-section-title">🎙 エピソード (' + epMatches.length + ')</h2>';
    epMatches.slice(0, 50).forEach(ep => {
      html += `
        <a class="search-result-item" href="${ep.url}">
          <div class="sri-badge">🎙 第${ep.ep}回 · ${esc(ep.date)}</div>
          <div class="sri-title">${highlight(ep.title, q)}</div>
          <div class="sri-body">${highlight(ep.speakers, q)}</div>
        </a>`;
    });
  }
  return html;
}

async function renderFullTextResults(pfResults) {
  if (!pfResults) {
    return '<p class="text-muted">全文検索インデックスが読み込めませんでした（build後に <code>./bin/pagefind --site mockup</code>）</p>';
  }
  const first = await Promise.all(pfResults.results.slice(0, 30).map(r => r.data()));
  let html = '<h2 class="search-section-title">📝 全文検索結果 (' + pfResults.results.length + ')</h2>';
  first.forEach(d => {
    const meta = d.meta || {};
    const title = meta.title || d.url;
    const badge = (meta.ep ? "第" + meta.ep + "回" : "") +
                  (meta.date ? " · " + meta.date : "");
    html += `
      <a class="search-result-item" href="${d.url}">
        <div class="sri-badge">📝 ${esc(badge)}</div>
        <div class="sri-title">${esc(title)}</div>
        <div class="sri-body">${d.excerpt}</div>
      </a>`;
  });
  if (pfResults.results.length > 30) {
    html += '<p class="text-muted">…以下' + (pfResults.results.length - 30) + '件省略</p>';
  }
  if (!pfResults.results.length) html = '<p class="text-muted">全文検索: 該当なし</p>';
  return html;
}

async function search(query) {
  if (!INDEX) return;
  const q = query.trim().toLowerCase();
  if (!q) {
    document.getElementById("results").innerHTML = '<p class="text-muted">キーワードを入力してください</p>';
    ["all","chapters","tweets","episodes","fulltext"].forEach(k => document.getElementById("cnt-"+k).textContent = "-");
    return;
  }
  // メタ検索 (chapters/tweets/episodes)
  const chMatches = INDEX.chapters.filter(ch =>
    ch.title.toLowerCase().includes(q) ||
    ch.summary.toLowerCase().includes(q) ||
    (ch.tags||[]).some(t => t.toLowerCase().includes(q))
  );
  const twMatches = INDEX.tweets.filter(t =>
    t.text.toLowerCase().includes(q) ||
    (t.author||"").toLowerCase().includes(q) ||
    (t.handle||"").toLowerCase().includes(q)
  );
  const epMatches = INDEX.episodes.filter(ep =>
    (ep.title||"").toLowerCase().includes(q) ||
    (ep.speakers||"").toLowerCase().includes(q)
  );
  // 全メタ件数を即時反映
  document.getElementById("cnt-all").textContent = chMatches.length + twMatches.length + epMatches.length;
  document.getElementById("cnt-chapters").textContent = chMatches.length;
  document.getElementById("cnt-tweets").textContent = twMatches.length;
  document.getElementById("cnt-episodes").textContent = epMatches.length;
  document.getElementById("cnt-fulltext").textContent = "…";  // 非同期処理中

  // メタ表示側は同期で先にrender (アクティブタブがメタなら)
  if (FILTER !== "fulltext") {
    let metaHtml = renderMetaResults(chMatches, twMatches, epMatches, q);
    document.getElementById("results").innerHTML = metaHtml || '<p class="text-muted">該当なし</p>';
  }

  // 全文検索は非同期で件数を確定 + アクティブタブが fulltext ならrenderも
  runFullTextSearch(q).then(async (pfResults) => {
    const cnt = pfResults ? pfResults.results.length : 0;
    document.getElementById("cnt-fulltext").textContent = pfResults ? cnt : "?";
    if (FILTER === "fulltext") {
      const html = await renderFullTextResults(pfResults);
      document.getElementById("results").innerHTML = html;
    }
  });
}

let debT;
document.getElementById("search-input").addEventListener("input", (e) => {
  clearTimeout(debT);
  debT = setTimeout(() => {
    const v = e.target.value;
    const u = new URL(location.href);
    if (v) u.searchParams.set("q", v); else u.searchParams.delete("q");
    history.replaceState(null, "", u);
    search(v);
  }, 150);
});

document.querySelectorAll("#search-tabs button").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#search-tabs button").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    FILTER = btn.dataset.filter;
    search(document.getElementById("search-input").value);
  });
});

(async () => {
  await loadIndex();
  const urlQ = new URLSearchParams(location.search).get("q");
  if (urlQ) {
    document.getElementById("search-input").value = urlQ;
    search(urlQ);
  } else {
    document.getElementById("results").innerHTML = '<p class="text-muted">キーワードを入力してください</p>';
  }
})();
</script>
'''
    return render_layout(title="検索 · Vizトーク Archive", body=body, level=0)


def main():
    episodes = load_episodes()
    tag_stats = collect_tag_stats(episodes)
    speaker_stats = collect_speaker_stats(episodes)
    tag_chapters, tag_episodes = tag_stats

    (SITE_DIR / "episode").mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "tag").mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "speaker").mkdir(parents=True, exist_ok=True)

    # 検索インデックス
    idx = build_search_index(episodes)
    (SITE_DIR / "search-index.json").write_text(json.dumps(idx, ensure_ascii=False))
    # 検索ページ
    (SITE_DIR / "search.html").write_text(build_search_page())

    # Home
    (SITE_DIR / "index.html").write_text(build_index(episodes, tag_stats, speaker_stats))

    # Episode list
    (SITE_DIR / "episodes.html").write_text(build_episodes_list(episodes))

    # Privacy page
    (SITE_DIR / "privacy.html").write_text(build_privacy_page())

    # Individual episodes (only those with ep number)
    n_ep = 0
    for ep in episodes:
        if not ep["ep"]:
            continue
        path = SITE_DIR / "episode" / f"{ep_slug(ep)}.html"
        path.write_text(build_episode_detail(ep))
        n_ep += 1

    # Tags list
    (SITE_DIR / "tags.html").write_text(build_tags_list(tag_stats))

    # Individual tags
    n_tag = 0
    for tag, chapters_list in tag_chapters.items():
        path = SITE_DIR / "tag" / f"{slug_tag(tag)}.html"
        path.write_text(build_tag_detail(tag, chapters_list, tag_episodes[tag]))
        n_tag += 1

    # Speakers list
    (SITE_DIR / "speakers.html").write_text(build_speakers_list(speaker_stats))

    # Individual speakers
    n_sp = 0
    for sp in speaker_stats.values():
        path = SITE_DIR / "speaker" / f"{slug_handle(sp['handle'])}.html"
        path.write_text(build_speaker_detail(sp))
        n_sp += 1

    _save_durations_cache()
    print(f"[done] index.html + episodes.html + tags.html + speakers.html")
    print(f"[done] episode pages: {n_ep}")
    print(f"[done] tag pages: {n_tag}")
    print(f"[done] speaker pages: {n_sp}")


if __name__ == "__main__":
    main()
