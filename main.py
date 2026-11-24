"""
The Health Coach - Daily Instagram + Facebook Auto Poster
=========================================================
  python main.py generate   -> aaj ka post banata hai, Google Sheet mein bhejta hai
  python main.py publish    -> Sheet mein jo APPROVE hue hain, unhe IG + FB + YouTube pe post karta hai
  python main.py test       -> sab setting check karta hai
  python main.py youtube_login -> ek baar YouTube account se login
"""
import configparser
import datetime as dt
import json
import os
import random
import re
import sys
import time
import traceback

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "posts")
HISTORY = os.path.join(BASE, "history.json")
LOG = os.path.join(BASE, "log.txt")
os.makedirs(OUT, exist_ok=True)

cfg = configparser.ConfigParser(interpolation=None)
cfg.read(os.path.join(BASE, "config.ini"), encoding="utf-8")


def C(key, default=""):
    return cfg.get("settings", key, fallback=default).strip()


def log(msg):
    line = f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


GRAPH = f"https://graph.facebook.com/{C('GRAPH_VERSION', 'v25.0')}"

# ------------------------------------------------------------------ history
def load_history():
    try:
        with open(HISTORY, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"topics": [], "photos": []}


def save_history(h):
    h["topics"] = h["topics"][-90:]
    h["photos"] = h["photos"][-200:]
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(h, f, ensure_ascii=False, indent=1)


# ------------------------------------------------------------------ REAL RESEARCH (free: Google Trends + Google News)
HEALTH_WORDS = [
    "health", "disease", "dengue", "malaria", "chikungunya", "flu", "fever", "virus", "covid", "infection",
    "diabetes", "sugar", "bp", "blood pressure", "heart", "cancer", "obesity", "weight", "diet", "nutrition",
    "vitamin", "yoga", "fitness", "exercise", "sleep", "stress", "mental", "anxiety", "pollution", "aqi",
    "smog", "air quality", "heatwave", "cold wave", "winter", "monsoon", "water", "hygiene", "vaccine",
    "doctor", "hospital", "aiims", "medicine", "kidney", "liver", "lung", "asthma", "allergy", "skin",
    "eye", "thyroid", "pcos", "pregnancy", "child", "elderly", "food", "adulteration", "milk", "outbreak",
    "\u0938\u094d\u0935\u093e\u0938\u094d\u0925\u094d\u092f", "\u092c\u0940\u092e\u093e\u0930\u0940",
    "\u0921\u0947\u0902\u0917\u0942", "\u092c\u0941\u0916\u093e\u0930", "\u0921\u093e\u092f\u092c\u093f\u091f\u0940\u091c",
    "\u092a\u094d\u0930\u0926\u0942\u0937\u0923", "\u0920\u0902\u0921", "\u092f\u094b\u0917",
    "\u0921\u0949\u0915\u094d\u091f\u0930", "\u0905\u0938\u094d\u092a\u0924\u093e\u0932",
]
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 Safari/537.36"}
NEWS_FEEDS = [
    ("India health news", "https://news.google.com/rss/search?q=health+India+when:2d&hl=en-IN&gl=IN&ceid=IN:en"),
    ("MP / Indore", "https://news.google.com/rss/search?q=(health+OR+dengue+OR+fever+OR+AQI+OR+hospital)+(Indore+OR+%22Madhya+Pradesh%22)+when:7d&hl=en-IN&gl=IN&ceid=IN:en"),
    ("Hindi health", "https://news.google.com/rss/search?q=%E0%A4%B8%E0%A5%8D%E0%A4%B5%E0%A4%BE%E0%A4%B8%E0%A5%8D%E0%A4%A5%E0%A5%8D%E0%A4%AF+when:2d&hl=hi&gl=IN&ceid=IN:hi"),
    ("Health section", "https://news.google.com/rss/headlines/section/topic/HEALTH?hl=en-IN&gl=IN&ceid=IN:en"),
]


def _rss(url):
    import xml.etree.ElementTree as ET
    r = requests.get(url, headers=UA, timeout=25)
    r.raise_for_status()
    return ET.fromstring(r.content)


def is_health(text):
    t = text.lower()
    return any(w in t for w in HEALTH_WORDS)


def do_research():
    """Aaj ke trending searches + health khabrein laata hai. Kuch fail ho to bhi chalta rehta hai."""
    out = {"trends": [], "health_trends": [], "news": [], "errors": [], "youtube": None, "instagram": None}
    HT = "{https://trends.google.com/trending/rss}"
    try:
        root = _rss("https://trends.google.com/trending/rss?geo=IN")
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            traffic = (it.findtext(HT + "approx_traffic") or "").strip()
            heads = [(n.findtext(HT + "news_item_title") or "").strip() for n in it.findall(HT + "news_item")]
            entry = {"q": title, "traffic": traffic, "news": [h for h in heads if h][:2]}
            out["trends"].append(entry)
            if is_health(title + " " + " ".join(heads)):
                out["health_trends"].append(entry)
    except Exception as e:
        out["errors"].append(f"Trends: {e}")
    seen = set()
    for label, url in NEWS_FEEDS:
        try:
            root = _rss(url)
            for it in list(root.iter("item"))[:15]:
                title = re.sub(r"\s+-\s+[^-]+$", "", (it.findtext("title") or "").strip())
                src = (it.findtext("source") or "").strip()
                key = title.lower()[:60]
                if title and key not in seen:
                    seen.add(key)
                    out["news"].append({"title": title, "source": src, "feed": label})
        except Exception as e:
            out["errors"].append(f"{label}: {e}")
    out["news"] = out["news"][:35]
    out["youtube"], out["instagram"] = None, None
    try:
        out["youtube"] = youtube_trending_health()
    except Exception as e:
        out["errors"].append(f"YouTube trends: {str(e)[:100]}")
    try:
        out["instagram"] = instagram_hashtag_research()
    except Exception as e:
        out["errors"].append(f"Instagram: {str(e)[:100]}")
    return out




# ------------------------------------------------------------------ SOCIAL MEDIA RESEARCH
YT_QUERIES = ["health tips", "\u0938\u0947\u0939\u0924 \u091f\u093f\u092a\u094d\u0938",
              "weight loss tips hindi", "home remedies hindi"]
IG_HASHTAGS = ["healthtips", "healthtipsinhindi", "weightloss", "ayurveda", "healthylifestyle",
               "fitnesstips", "homeremedies", "diettips", "yoga"]


def youtube_trending_health():
    """Pichhle 7 din ke sabse zyada dekhe gaye health Shorts (India) + unke hashtags."""
    yt = youtube_client()
    if not yt.hc_creds.has_scopes([YT_READ]):
        raise RuntimeError("YouTube research ke liye youtube_login.bat ek baar dobara chalayein")
    since = (dt.datetime.utcnow() - dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids = []
    for q in YT_QUERIES:
        r = yt.search().list(part="id", q=q, type="video", regionCode="IN", relevanceLanguage="hi",
                             order="viewCount", publishedAfter=since, videoDuration="short",
                             maxResults=10).execute()
        ids += [i["id"]["videoId"] for i in r.get("items", []) if i["id"].get("videoId")]
    ids = list(dict.fromkeys(ids))[:50]
    if not ids:
        return {"videos": [], "hashtags": []}
    v = yt.videos().list(part="snippet,statistics", id=",".join(ids)).execute()
    vids, tags = [], {}
    for it in v.get("items", []):
        sn, st = it["snippet"], it.get("statistics", {})
        views = int(st.get("viewCount", 0))
        vids.append({"title": sn["title"], "views": views, "likes": int(st.get("likeCount", 0)),
                     "channel": sn.get("channelTitle", "")})
        for t in re.findall(r"#(\w+)", sn["title"] + " " + sn.get("description", "")):
            k = t.lower()
            if k not in ("shorts", "short", "viral", "trending", "youtubeshorts", "ytshorts", "reels"):
                tags[k] = tags.get(k, 0) + views
    vids.sort(key=lambda x: -x["views"])
    top_tags = [t for t, _ in sorted(tags.items(), key=lambda x: -x[1])[:15]]
    return {"videos": vids[:15], "hashtags": top_tags}


def instagram_hashtag_research():
    """Instagram par health hashtags ki top posts (Meta connect hone ke baad chalega).
    Instagram limit: 7 din mein 30 alag hashtags - isliye roz sirf 3 (ghoom-ghoom ke)."""
    if not meta_ready():
        return None
    ig = C("IG_USER_ID")
    day = dt.date.today().toordinal()
    todays = [IG_HASHTAGS[(day * 3 + i) % len(IG_HASHTAGS)] for i in range(3)]
    posts = []
    for tag in todays:
        try:
            hid = graph("GET", "ig_hashtag_search", params={"user_id": ig, "q": tag})["data"][0]["id"]
            top = graph("GET", f"{hid}/top_media", params={
                "user_id": ig, "fields": "caption,like_count,comments_count,media_type", "limit": 25})
            for m in top.get("data", []):
                cap = (m.get("caption") or "").strip().split("\n")[0][:140]
                if cap:
                    posts.append({"tag": tag, "caption": cap, "likes": m.get("like_count", 0),
                                  "comments": m.get("comments_count", 0), "type": m.get("media_type", "")})
        except Exception as e:
            log(f"Instagram #{tag} research nahi hua: {str(e)[:80]}")
    posts.sort(key=lambda x: -(x["likes"] + 3 * x["comments"]))
    return {"hashtags": todays, "posts": posts[:15]}


def research_text(res):
    lines = []
    if res["health_trends"]:
        lines.append("HEALTH-RELATED GOOGLE SEARCH TRENDS IN INDIA TODAY:")
        for t in res["health_trends"][:8]:
            lines.append(f"- {t['q']} ({t['traffic']} searches) | news: {' / '.join(t['news'])}")
    if res["trends"]:
        lines.append("ALL TOP GOOGLE TRENDS IN INDIA TODAY (use only if there is a sensible health angle):")
        lines.append(", ".join(t["q"] for t in res["trends"][:20]))
    if res["news"]:
        lines.append("TODAY'S HEALTH NEWS HEADLINES (India, MP/Indore, Hindi):")
        for n in res["news"]:
            lines.append(f"- [{n['feed']}] {n['title']}" + (f" ({n['source']})" if n["source"] else ""))
    yt = res.get("youtube") or {}
    if yt.get("videos"):
        lines.append("MOST-VIEWED HEALTH SHORTS ON YOUTUBE INDIA, LAST 7 DAYS (what short-video audiences watch now):")
        for v in yt["videos"]:
            lines.append(f"- {v['title']} ({v['views']:,} views)")
    if yt.get("hashtags"):
        lines.append("HASHTAGS USED BY THOSE TOP VIDEOS: " + " ".join("#" + t for t in yt["hashtags"]))
    ig = res.get("instagram") or {}
    if ig.get("posts"):
        lines.append("TOP INSTAGRAM POSTS TODAY FOR " + ", ".join("#" + t for t in ig["hashtags"]) + ":")
        for p in ig["posts"]:
            lines.append(f"- {p['caption']} ({p['likes']} likes, {p['comments']} comments, {p['type']})")
    pc = performance_context()
    if pc:
        lines.append(pc)
    return "\n".join(lines) if lines else "No live research data available today."


# ------------------------------------------------------------------ Gemini (free)
PROMPT = """You are the social-media content planner for "The Health Coach" (thehealthcoach.in),
a personal health coaching service in Indore, India, run by a qualified doctor. The goal: help
ordinary Indian families stay healthy through simple daily habits. Audience: Hindi-speaking
adults in Madhya Pradesh, 25-60 years old.

Today is {today}. Below is LIVE RESEARCH collected this morning from Google Trends and Google News:

=== LIVE RESEARCH ===
{research}
=== END ===

STEP 1 - study the research. The YouTube Shorts and Instagram sections show which health subjects
people are actually watching and engaging with on social media right now - use them to judge what
will get views, likes and shares. Prefer a topic that is BOTH engaging on social media AND useful/
relevant (in the news, searched, or seasonal) for families in Indore/MP (outbreaks, AQI/pollution, weather, festivals, a health news story).
If nothing in the research is useful or safe for a general health tip, use the season and upcoming
festivals instead. Never spread panic or unverified claims; turn news into calm, practical prevention tips.
STEP 2 - pick ONE topic for today's Instagram post.
Do NOT repeat any of these recent topics: {recent}

Rules:
- Practical, safe, evidence-based lifestyle tips only. No medicine names, no doses,
  no "cure" claims, no fear-mongering.
- Poster text must be in simple Hinglish written in ROMAN (English) letters, not Devanagari.
- Caption in friendly Hinglish (Roman script), 90-160 words, energetic and warm, with
  3-4 short tips using emojis, ending with:
  "Free health guidance ke liye Call/WhatsApp karein: {phone}"
  and one line: "Ye general jaankari hai, kisi bhi samasya mein doctor se salah zaroor lein."
- 12-15 hashtags: include the most relevant trending hashtags from the research (only if they fit
  the topic), plus #Indore #TheHealthCoach. No misleading or unrelated trending tags.

Reply with ONLY this JSON, nothing else:
{{"topic": "short topic name in English",
  "why_today": "one short line in Hinglish: why this topic today, naming the trend or news it came from",
  "source": "the exact research headline or trend you used, or 'season' if none",
  "poster_title": "catchy title, max 7 words",
  "points": ["tip 1, max 8 words", "tip 2, max 8 words", "tip 3, max 8 words"],
  "caption": "full caption text without hashtags",
  "hashtags": "#tag1 #tag2 ...",
  "photo_query": "2-4 English words to search a bright, positive stock photo (no doctors, no medicines, no sick people)",
  "scenes": {{"hook": "on-screen HOOK question in Hinglish Roman, max 10 words, e.g. Kya aapka bhi subah pet saaf nahi hota?", "problem": "on-screen PROBLEM line that names the viewer's pain, max 10 words, e.g. Constipation ki wajah se aap pareshan hain?", "solution": "on-screen SOLUTION line with the key tips, max 14 words, e.g. Fiber, adequate water aur physical activity par dhyan dein.", "cta": "Aise hi health tips ke liye The Health Coach ko subscribe karein."}},
  "video_script": "a 25-35 second SPOKEN script (60-85 words) in natural Hinglish written in Roman letters, in EXACTLY this order: 1) HOOK - the hook question, 2) PROBLEM - relate to the viewer's pain, 3) SOLUTION - the 3 tips in simple words, 4) CTA - Aise hi health tips ke liye The Health Coach ko subscribe karein. No emojis, no hashtags, no headings.",
  "voice_parts": ["spoken HOOK part", "spoken PROBLEM part", "spoken SOLUTION part", "spoken CTA part"],
  "voice_script_hi": "the SAME spoken script (same 4 parts, same order) written in Devanagari Hindi script for a Hindi text-to-speech voice (write common English words like protein, vitamin, subscribe in Devanagari too). No emojis."}}"""


def gemini(prompt, use_search=True, model=None):
    key = C("GEMINI_API_KEY")
    model = model or C("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.9}}
    if use_search:
        body["tools"] = [{"google_search": {}}]
    r = requests.post(url, json=body, headers={"x-goog-api-key": key}, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"Gemini error {r.status_code}: {r.text[:300]}")
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


def gemini_models():
    out = []
    for m in (C("GEMINI_MODEL", "gemini-flash-latest"), "gemini-flash-latest", "gemini-3.8-flash",
              "gemini-3.5-flash", "gemini-flash-lite-latest", "gemma-3-27b-it", "gemma-3-12b-it"):
        if m and m not in out:
            out.append(m)
    return out


DEAD_MODELS = set()


def gemini_any(prompt, use_search=False, rounds=3):
    """Jo model chal jaye usse jawab lo. Band model skip, Google busy ho to ruk ke dobara."""
    err = None
    for rnd in range(rounds):
        for m in gemini_models():
            if m in DEAD_MODELS:
                continue
            try:
                return gemini(prompt, use_search, m)
            except Exception as e:
                err = e
                msg = str(e)
                if "404" in msg or "400" in msg:
                    DEAD_MODELS.add(m)
                if use_search and "429" in msg:
                    raise  # free plan mein search nahi - bina search ke chalayenge
                code = re.search(r"error (\d{3})", msg)
                log(f"AI model {m}: abhi nahi chala ({code.group(1) if code else msg[:40]})")
        if rnd < rounds - 1:
            wait = 30 * (rnd + 1)
            log(f"Google busy hai, {wait} second baad dobara try...")
            time.sleep(wait)
    raise err


def parse_content(text):
    m = re.search(r"\{.*\}", text, re.S)
    data = json.loads(m.group(0))
    assert data["poster_title"] and len(data["points"]) >= 3 and data["caption"]
    return data


RESEARCH_SUMMARY = {}


def make_content():
    h = load_history()
    res = do_research()
    RESEARCH_SUMMARY.update(trends=len(res["trends"]), health_trends=len(res["health_trends"]),
                            news=len(res["news"]), errors=res["errors"],
                            yt=len((res.get("youtube") or {}).get("videos", [])),
                            ig=len((res.get("instagram") or {}).get("posts", [])))
    try:
        with open(os.path.join(OUT, f"{dt.date.today().isoformat()}_research.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    except Exception:
        pass
    log(f"Research: {len(res['news'])} health khabrein, {len(res['health_trends'])} health trends "
        f"(kul {len(res['trends'])} trends), {RESEARCH_SUMMARY['yt']} YouTube Shorts, {RESEARCH_SUMMARY['ig']} Instagram posts" + (f" | dikkat: {'; '.join(res['errors'])[:120]}" if res["errors"] else ""))
    prompt = PROMPT.replace("{research}", research_text(res).replace("{", "(").replace("}", ")")).format(
        today=dt.date.today().strftime("%d %B %Y, %A"),
        recent=", ".join(h["topics"][-30:]) or "none",
        phone=C("PHONE", "8982264044"))
    if C("USE_GOOGLE_SEARCH", "no").lower() == "yes":
        try:
            return parse_content(gemini_any(prompt, use_search=True, rounds=1))
        except Exception as e:
            log(f"Search ke saath nahi hua, bina search ke bana rahe hain ({str(e)[:60]})")
    try:
        return parse_content(gemini_any(prompt))
    except Exception as e:
        log(f"AI abhi available nahi, backup tip bank se post bana rahe hain ({str(e)[:60]})")
    return backup_content(h)


def backup_content(h):
    from tip_bank import pick
    topic, title, points, intro, query = pick(h["topics"][-30:])
    phone = C("PHONE", "8982264044")
    emo = ["\u2705", "\U0001F4AA", "\U0001F33F"]
    caption = (f"{title} \U0001F31F\n\n{intro}\n\n"
               + "\n".join(f"{emo[i % 3]} {p}" for i, p in enumerate(points))
               + f"\n\nChhoti aadatein, badi sehat. Aaj se shuru karein!\n\n"
               f"Free health guidance ke liye Call/WhatsApp karein: {phone}\n"
               "Ye general jaankari hai, kisi bhi samasya mein doctor se salah zaroor lein.")
    tag = "#" + re.sub(r"[^A-Za-z]", "", topic.title())
    hashtags = (f"{tag} #HealthTips #SwasthJeevan #HealthyLifestyle #Fitness #Wellness "
                "#HealthyHabits #SehatKiBaat #Indore #IndoreHealth #MPHealth #TheHealthCoach")
    vscript = (f"{title}? {intro} Pehla, {points[0]}. Doosra, {points[1]}. Teesra, {points[2]}. "
               "Chhoti aadatein, badi sehat. Aisi aur tips ke liye follow karein, aur free guidance ke liye WhatsApp karein.")
    return {"video_script": vscript, "topic": topic, "why_today": "backup tip (AI busy tha)", "poster_title": title,
            "points": points, "caption": caption, "hashtags": hashtags, "photo_query": query}


# ----------------------------------------------------------------- photo (Pixabay / Pexels, free)
def _save_photo(url, pid):
    r = requests.get(url, timeout=120, headers=UA)
    path = os.path.join(OUT, "_photo.jpg")
    with open(path, "wb") as f:
        f.write(r.content)
    try:  # check ki asli photo hai, error page nahi
        with Image.open(path) as im:
            im.verify()
    except Exception:
        raise RuntimeError(f"photo file kharab aayi (HTTP {r.status_code}, {len(r.content)} bytes)")
    h = load_history()
    h["photos"].append(pid)
    save_history(h)
    return path


def get_photo(query):
    used = set(load_history()["photos"])
    queries = (query, "healthy lifestyle", "healthy food fresh")
    pix = C("PIXABAY_API_KEY")
    if pix:
        for q in queries:
            try:
                r = requests.get("https://pixabay.com/api/", params={
                    "key": pix, "q": q, "image_type": "photo", "orientation": "horizontal",
                    "safesearch": "true", "per_page": 30, "min_width": 1200}, timeout=60)
                hits = [x for x in r.json().get("hits", []) if f"pb{x['id']}" not in used]
                random.shuffle(hits)
                for x in hits[:4]:
                    for key in ("largeImageURL", "webformatURL"):
                        try:
                            return _save_photo(x[key], f"pb{x['id']}")
                        except Exception as e:
                            log(f"Pixabay photo skip: {str(e)[:80]}")
            except Exception as e:
                log(f"Pixabay issue: {e}")
    pex = C("PEXELS_API_KEY")
    if pex:
        for q in queries:
            try:
                r = requests.get("https://api.pexels.com/v1/search",
                                 params={"query": q, "per_page": 20, "orientation": "landscape"},
                                 headers={"Authorization": pex}, timeout=60)
                photos = [p for p in r.json().get("photos", []) if p["id"] not in used]
                random.shuffle(photos)
                for p in photos[:3]:
                    try:
                        return _save_photo(p["src"]["large2x"], p["id"])
                    except Exception as e:
                        log(f"Pexels photo skip: {str(e)[:80]}")
            except Exception as e:
                log(f"Pexels issue: {e}")
    return None


# ------------------------------------------------------------------ poster design
W, H = 1080, 1350
GREEN = (22, 163, 74)
ORANGE = (249, 115, 22)
DARK = (15, 23, 42)
CREAM = (255, 251, 245)


def font(bold=True, size=40):
    names = (["seguibl.ttf", "segoeuib.ttf", "Roboto-Black.ttf", "Roboto-Bold.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"] if bold
             else ["segoeuisb.ttf", "segoeui.ttf", "Roboto-Medium.ttf", "Roboto-Regular.ttf", "arial.ttf", "DejaVuSans.ttf"])
    dirs = [r"C:\Windows\Fonts", os.path.join(BASE, "fonts"), "/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF",
            "/usr/share/fonts/truetype/roboto/hinted", "/usr/share/fonts/truetype/dejavu", ""]
    for n in names:
        for d in dirs:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def wrap(draw, text, f, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=f) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def find_logo():
    """Folder mein logo.png / logo.jpg / logo_*.jpg dhoondh ke, safed kinare kaat ke deta hai."""
    import glob
    names = [C("LOGO_PATH", "logo.png")] + sorted(glob.glob(os.path.join(BASE, "logo*.*")))
    for n in names:
        path = n if os.path.isabs(n) else os.path.join(BASE, n)
        if os.path.isfile(path) and path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            try:
                lg = Image.open(path).convert("RGBA")
                gray = lg.convert("L").point(lambda v: 255 if v < 235 else 0)
                alpha = lg.getchannel("A").point(lambda v: 255 if v > 20 else 0)
                from PIL import ImageChops
                box = ImageChops.multiply(gray, alpha).getbbox()
                return lg.crop(box) if box else lg
            except Exception as e:
                log(f"Logo nahi khula ({path}): {e}")
    return None


def make_poster(data, photo_path, out_path):
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)
    PH = 600
    ph = None
    if photo_path:
        try:
            ph = ImageOps.fit(Image.open(photo_path).convert("RGB"), (W, PH), Image.LANCZOS)
        except Exception as e:
            log(f"Photo nahi khuli, rangeen background lagega: {e}")
    if ph is not None:
        img.paste(ph, (0, 0))
    else:  # fallback: energetic gradient
        for y in range(PH):
            t = y / PH
            d.line([(0, y), (W, y)], fill=tuple(int(GREEN[i] * (1 - t) + ORANGE[i] * t) for i in range(3)))
    logo = find_logo()
    # brand chip top-left (sirf tab jab logo na ho)
    fb = font(True, 30)
    if not logo:
        chip = "THE HEALTH COACH"
        cw = d.textlength(chip, font=fb)
        d.rounded_rectangle([40, 36, 40 + cw + 44, 92], 28, fill=DARK)
        d.text((62, 44), chip, font=fb, fill="white")
    # "today's tip" badge
    fbad = font(True, 32)
    badge = "AAJ KA HEALTH TIP"
    bw = d.textlength(badge, font=fbad)
    d.rounded_rectangle([60, PH - 34, 60 + bw + 56, PH + 34], 34, fill=ORANGE)
    d.text((88, PH - 24), badge, font=fbad, fill="white")
    # title (auto-size)
    y = PH + 70
    for size in (82, 74, 66, 58, 52):
        ft = font(True, size)
        lines = wrap(d, data["poster_title"], ft, W - 130)
        if len(lines) <= 2:
            break
    for ln in lines[:3]:
        d.text((64, y), ln, font=ft, fill=DARK)
        y += int(size * 1.15)
    d.rectangle([64, y + 14, 200, y + 22], fill=GREEN)
    y += 56
    # points
    fp = font(False, 40)
    for pt in data["points"][:3]:
        d.ellipse([64, y + 4, 112, y + 52], fill=GREEN)
        d.line([(76, y + 29), (86, y + 40), (101, y + 17)], fill="white", width=6)
        pl = wrap(d, pt, fp, W - 210)
        for i, ln in enumerate(pl[:2]):
            d.text((136, y + i * 50), ln, font=fp, fill=(31, 41, 55))
        y += 50 * min(len(pl), 2) + 30
    # footer
    FH = 165
    d.rectangle([0, H - FH, W, H], fill=DARK)
    d.rectangle([0, H - FH, W, H - FH + 8], fill=ORANGE)
    f1, f2 = font(True, 40), font(False, 30)
    site = C("WEBSITE", "thehealthcoach.in")
    if logo:  # logo safed card pe, footer ke left mein
        lg = logo.copy()
        lg.thumbnail((380, 122), Image.LANCZOS)
        cx, cy = 40, H - FH + 20
        d.rounded_rectangle([cx, cy, cx + lg.width + 28, cy + lg.height + 16], 16, fill="white")
        img.paste(lg, (cx + 14, cy + 8), lg)
        d.text((cx + lg.width + 52, H - FH + 72), site, font=f2, fill=(203, 213, 225))
    else:
        d.text((64, H - FH + 34), "The Health Coach", font=f1, fill="white")
        d.text((64, H - FH + 84), site, font=f2, fill=(203, 213, 225))
    call = "Call / WhatsApp"
    num = C("PHONE", "8982264044")
    d.text((W - 56 - d.textlength(call, font=f2), H - FH + 34), call, font=f2, fill=(203, 213, 225))
    d.text((W - 56 - d.textlength(num, font=f1), H - FH + 72), num, font=f1, fill=ORANGE)
    img.save(out_path, "JPEG", quality=93)
    return out_path


# ------------------------------------------------------------------ YouTube Short video (from poster)
def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def audio_seconds(path):
    import subprocess
    r = subprocess.run([ffmpeg_exe(), "-i", path], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0


def make_voice(data, out_mp3):
    """Free Microsoft neural awaaz (edge-tts) se script bulwata hai."""
    import asyncio
    import edge_tts
    hi = (data.get("voice_script_hi") or "").strip()
    if hi:
        text, voice = hi, C("TTS_VOICE_HI", "hi-IN-MadhurNeural")
    else:
        text = (data.get("video_script") or "").strip()
        voice = C("TTS_VOICE_EN", "en-IN-PrabhatNeural")
    if not text:
        raise RuntimeError("video script khali hai")
    rate = C("TTS_RATE", "+5%").replace("%%", "%")
    tries = [(text, voice, rate), (text, voice, "+0%")]
    roman = (data.get("video_script") or "").strip()
    if roman:
        tries += [(roman, C("TTS_VOICE_HI", "hi-IN-MadhurNeural"), "+0%"), (roman, "en-IN-PrabhatNeural", "+0%")]
    last = None
    for t_, v_, r_ in tries:
        try:
            asyncio.run(edge_tts.Communicate(t_, v_, rate=r_).save(out_mp3))
            if audio_seconds(out_mp3) >= 3:
                return out_mp3
        except Exception as e:
            last = e
            log(f"Awaaz try fail ({v_}, {r_}): {str(e)[:60]}")
    raise RuntimeError(f"awaaz nahi bani: {last}")
    if audio_seconds(out_mp3) < 3:
        raise RuntimeError("awaaz file sahi nahi bani")
    return out_mp3


def story_scenes(data):
    """Hook / Problem / Solution / CTA - AI se, warna poster ke content se."""
    sc = data.get("scenes") or {}
    pts = data.get("points") or []
    return [
        ("SAWAL", sc.get("hook") or (data.get("poster_title", "").rstrip("?") + "?")),
        ("PROBLEM", sc.get("problem") or data.get("why_today") or data.get("topic", "")),
        ("SOLUTION", sc.get("solution") or " | ".join(pts[:3])),
        ("SUBSCRIBE", sc.get("cta") or "Aise hi health tips ke liye The Health Coach ko subscribe karein."),
    ]


def story_frame(label, text, bg, idx, out_path):
    """Ek scene ka 1080x1920 card: photo background + bada text + logo footer."""
    SW, SH = 1080, 1920
    if bg is not None:
        img = ImageOps.fit(bg, (SW, SH), Image.LANCZOS).filter(ImageFilter.GaussianBlur(6))
        img = Image.blend(img, Image.new("RGB", (SW, SH), DARK), 0.62)
    else:
        img = Image.new("RGB", (SW, SH), DARK)
        g = ImageDraw.Draw(img)
        for y in range(SH):
            t = y / SH
            g.line([(0, y), (SW, y)], fill=tuple(int(DARK[i] * (1 - t) + GREEN[i] * t * 0.6) for i in range(3)))
    d = ImageDraw.Draw(img)
    colors = [ORANGE, (220, 38, 38), GREEN, ORANGE]
    fl = font(True, 46)
    lw = d.textlength(label, font=fl)
    d.rounded_rectangle([(SW - lw) / 2 - 40, 430, (SW + lw) / 2 + 40, 520], 45, fill=colors[idx % 4])
    d.text(((SW - lw) / 2, 448), label, font=fl, fill="white")
    for size in (92, 84, 76, 68, 60, 54):
        ft = font(True, size)
        lines = wrap(d, text, ft, SW - 140)
        if len(lines) * size * 1.2 <= 760:
            break
    y = 600 + (760 - len(lines) * int(size * 1.2)) // 2
    for ln in lines:
        d.text(((SW - d.textlength(ln, font=ft)) / 2, y), ln, font=ft, fill="white")
        y += int(size * 1.2)
    for i in range(4):  # progress dots
        x = SW / 2 - 66 + i * 44
        d.ellipse([x, 1460, x + 20, 1480], fill=(255, 255, 255) if i == idx else (100, 116, 139))
    logo = find_logo()
    if logo:
        lg = logo.copy()
        lg.thumbnail((420, 140), Image.LANCZOS)
        x = (SW - lg.width - 32) // 2
        d.rounded_rectangle([x, 1600, x + lg.width + 32, 1600 + lg.height + 20], 18, fill="white")
        img.paste(lg, (x + 16, 1610), lg)
    else:
        f1 = font(True, 48)
        d.text(((SW - d.textlength("The Health Coach", font=f1)) / 2, 1620), "The Health Coach", font=f1, fill="white")
    f2 = font(False, 34)
    num = "Call / WhatsApp " + C("PHONE", "8982264044")
    d.text(((SW - d.textlength(num, font=f2)) / 2, 1790), num, font=f2, fill=(203, 213, 225))
    img.save(out_path, quality=93)
    return out_path


def make_story_short(data, photo_path, out_path, voice=None):
    """Hook -> Problem -> Solution -> CTA: 4 scene wala vertical Short (+ awaaz)."""
    import subprocess
    scenes = story_scenes(data)
    bg = None
    if photo_path:
        try:
            bg = Image.open(photo_path).convert("RGB")
        except Exception:
            bg = None
    total = min(58.0, audio_seconds(voice) + 0.8) if voice else 14.0
    words = [max(len(t.split()), 3) for _, t in scenes]
    if voice and data.get("voice_parts"):
        words = [max(len(str(p).split()), 3) for p in data["voice_parts"]][:4] or words
    durs = [max(2.2, total * w / sum(words)) for w in words]
    durs = [d * total / sum(durs) for d in durs]
    fps = 30
    cmd = [ffmpeg_exe(), "-y"]
    for i, (label, text) in enumerate(scenes):
        f = story_frame(label, text, bg, i, os.path.join(OUT, f"_scene{i}.jpg"))
        cmd += ["-loop", "1", "-t", f"{durs[i]:.2f}", "-i", f]
    parts = []
    for i, dd in enumerate(durs):
        n = int(dd * fps) + 1
        parts.append(f"[{i}:v]scale=2160:3840,zoompan=z='min(1+0.0006*on,1.06)':x='iw/2-(iw/zoom/2)':"
                     f"y='ih/2-(ih/zoom/2)':d={n}:s=1080x1920:fps={fps},trim=duration={dd:.2f},setpts=PTS-STARTPTS[v{i}]")
    flt = ";".join(parts) + ";" + "".join(f"[v{i}]" for i in range(4)) + "concat=n=4:v=1:a=0,format=yuv420p[v]"
    music = os.path.join(BASE, "music.mp3")
    has_music = os.path.exists(music)
    fade = f"afade=t=out:st={max(total - 1.5, 0):.2f}:d=1.5"
    if voice and has_music:
        cmd += ["-i", voice, "-stream_loop", "-1", "-i", music]
        flt += f";[5:a]volume=0.12[m];[4:a][m]amix=inputs=2:duration=first:dropout_transition=0,{fade}[a]"
        maps = ["-map", "[v]", "-map", "[a]"]
    elif voice:
        cmd += ["-i", voice]
        maps = ["-map", "[v]", "-map", "4:a", "-af", fade]
    elif has_music:
        cmd += ["-stream_loop", "-1", "-i", music]
        maps = ["-map", "[v]", "-map", "4:a", "-af", fade]
    else:
        maps = ["-map", "[v]"]
    cmd += ["-filter_complex", flt] + maps
    if voice or has_music:
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    cmd += ["-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-movflags", "+faststart", out_path]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


PART_LABELS = {"hook": 0, "sawal": 0, "problem": 1, "solution": 2, "hal": 2, "upay": 2,
               "cta": 3, "subscribe": 3}
DEFAULT_CTA = "Aise hi health tips ke liye The Health Coach ko subscribe karein."


def parse_script(text):
    """'Hook: ... / Problem: ... / Solution: ... / CTA: ...' wali script ko 4 hisson mein todta hai."""
    parts = ["", "", "", ""]
    loose = []
    for raw in str(text).splitlines():
        ln = raw.strip().lstrip("*-•0123456789.) ").strip()
        if not ln:
            continue
        m = re.match(r"^([A-Za-z]+)\s*[:\-]\s*(.+)$", ln)
        key = m.group(1).lower() if m else ""
        if m and key in PART_LABELS:
            parts[PART_LABELS[key]] = m.group(2).strip().strip('"“”\' ')
        else:
            loose.append(ln.strip('"“”\' '))
    if not any(parts) and loose:
        sents = re.split(r"(?<=[?.!।])\s+", " ".join(loose))
        sents = [s for s in sents if s.strip()]
        n = max(1, len(sents))
        cuts = [0, max(1, n // 4), max(2, n // 2), max(3, n - 1)]
        for i in range(4):
            a = cuts[i]
            b = cuts[i + 1] if i < 3 else n
            parts[i] = " ".join(sents[a:b]).strip()
    if not parts[3]:
        parts[3] = DEFAULT_CTA
    return [p for p in parts if p]


def script_parts_from_data(data):
    vp = [str(p).strip() for p in (data.get("voice_parts") or []) if str(p).strip()]
    if len(vp) >= 3 and not any(p.lower().startswith("spoken ") for p in vp):
        return vp[:4]
    sc = data.get("scenes") or {}
    parts = [sc.get("hook"), sc.get("problem"), sc.get("solution"), sc.get("cta") or DEFAULT_CTA]
    if all(parts):
        return parts
    return parse_script(data.get("video_script") or data.get("poster_title", ""))


def hindi_and_queries(parts, topic=""):
    """Gemini se: har hisse ka Devanagari (awaaz ke liye) + stock video search words."""
    ask = ("For each numbered Hinglish line below give (a) the same line in natural Devanagari Hindi for a "
           "Hindi text-to-speech voice (write English words like fiber, water, subscribe, The Health Coach in "
           "Devanagari too) and (b) 2-3 simple English words to search a matching stock VIDEO clip "
           "(bright, positive, no doctors, no medicines, no sick or sad people, no text). Topic: " + str(topic) +
           "\n" + "\n".join(f"{i + 1}. {p}" for i, p in enumerate(parts)) +
           '\nReply with ONLY JSON: {"hi": ["..."], "q": ["..."]} with exactly ' + str(len(parts)) + " items each.")
    try:
        txt = gemini_any(ask, rounds=2)
        j = json.loads(re.search(r"\{.*\}", txt, re.S).group(0))
        hi, q = list(j.get("hi") or []), list(j.get("q") or [])
        if len(hi) == len(parts) and len(q) == len(parts):
            return hi, q
    except Exception as e:
        log(f"Hindi/keywords AI se nahi mile ({str(e)[:60]}), seedha script use hogi")
    kw = [("pet ", "fiber rich food"), ("constipation", "fiber rich food"), ("kabz", "fiber rich food"),
          ("fiber", "fiber rich food"), ("paani", "drinking water"), ("water", "drinking water"),
          ("walk", "people walking park"), ("activity", "people walking park"), ("exercise", "exercise workout"),
          ("yoga", "yoga"), ("neend", "sleeping"), ("sleep", "sleeping"), ("fruit", "fresh fruits"),
          ("fal ", "fresh fruits"), ("sabzi", "vegetables"), ("sugar", "healthy breakfast"),
          ("diabetes", "healthy breakfast"), ("dil ", "jogging"), ("heart", "jogging"), ("stress", "meditation"),
          ("tension", "meditation"), ("subscribe", "happy family"), ("health", "healthy lifestyle")]
    qs = [next((q for k, q in kw if k in " " + p.lower() + " "), "healthy lifestyle") for p in parts]
    return list(parts), qs


def free_tts(text_hi, text_roman, out_mp3):
    """Free Hindi awaaz: Google (gTTS), warna Microsoft (edge-tts)."""
    errs = []
    try:
        from gtts import gTTS
        gTTS(text_hi, lang="hi").save(out_mp3)
        if audio_seconds(out_mp3) > 0.5:
            return out_mp3
    except Exception as e:
        errs.append(f"gTTS: {str(e)[:60]}")
    try:
        import asyncio
        import edge_tts
        asyncio.run(edge_tts.Communicate(text_hi, C("TTS_VOICE_HI", "hi-IN-MadhurNeural"), rate="+0%").save(out_mp3))
        if audio_seconds(out_mp3) > 0.5:
            return out_mp3
    except Exception as e:
        errs.append(f"edge: {str(e)[:60]}")
    try:
        from gtts import gTTS
        gTTS(text_roman, lang="hi").save(out_mp3)
        if audio_seconds(out_mp3) > 0.5:
            return out_mp3
    except Exception as e:
        errs.append(f"gTTS roman: {str(e)[:60]}")
    raise RuntimeError("awaaz nahi bani: " + " | ".join(errs))


def pixabay_clip(query, out_path, used):
    """Pixabay se free stock video clip (pehle portrait, phir koi bhi)."""
    key = C("PIXABAY_API_KEY")
    if not key:
        return None
    for q in (query, "healthy lifestyle", "fresh fruits vegetables", "nature morning"):
        try:
            r = requests.get("https://pixabay.com/api/videos/", params={
                "key": key, "q": q, "safesearch": "true", "per_page": 30, "video_type": "film"}, timeout=60)
            hits = [h for h in r.json().get("hits", []) if h["id"] not in used and 4 <= h.get("duration", 0) <= 60]
            hits.sort(key=lambda h: (h["videos"]["medium"].get("height", 0) <= h["videos"]["medium"].get("width", 1),
                                     -h.get("likes", 0)))
            for h in hits[:5]:
                v = h["videos"].get("medium") or h["videos"].get("small")
                if not v or not v.get("url"):
                    continue
                data = requests.get(v["url"], timeout=120, headers=UA).content
                if len(data) < 50_000:
                    continue
                with open(out_path, "wb") as f:
                    f.write(data)
                used.add(h["id"])
                return out_path
        except Exception as e:
            log(f"Pixabay video '{q}' nahi mila: {str(e)[:60]}")
    return None


def caption_png(text, idx, out_path):
    """Neeche subtitle + upar chhota logo, transparent PNG."""
    SW, SH = 1080, 1920
    img = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for size in (64, 58, 52, 46):
        ft = font(True, size)
        lines = wrap(d, text, ft, SW - 180)
        if len(lines) <= 4:
            break
    lh = int(size * 1.25)
    boxh = len(lines) * lh + 60
    y0 = 1380 - boxh // 2
    d.rounded_rectangle([60, y0, SW - 60, y0 + boxh], 34, fill=(15, 23, 42, 190))
    accent = [ORANGE, (220, 38, 38), GREEN, ORANGE][idx % 4]
    d.rounded_rectangle([60, y0, 76, y0 + boxh], 8, fill=accent + (255,))
    y = y0 + 30
    for ln in lines:
        d.text(((SW - d.textlength(ln, font=ft)) / 2, y), ln, font=ft, fill="white")
        y += lh
    logo = find_logo()
    if logo:
        lg = logo.copy()
        lg.thumbnail((260, 90), Image.LANCZOS)
        d.rounded_rectangle([40, 60, 40 + lg.width + 24, 60 + lg.height + 16], 14, fill=(255, 255, 255, 235))
        img.paste(lg, (52, 68), lg)
    img.save(out_path)
    return out_path


def end_card(out_path):
    SW, SH = 1080, 1920
    img = Image.new("RGB", (SW, SH), DARK)
    d = ImageDraw.Draw(img)
    for y in range(SH):
        t = y / SH
        d.line([(0, y), (SW, y)], fill=tuple(int(DARK[i] * (1 - t) + GREEN[i] * t * 0.6) for i in range(3)))
    logo = find_logo()
    y = 560
    if logo:
        lg = logo.copy()
        lg.thumbnail((640, 260), Image.LANCZOS)
        x = (SW - lg.width - 48) // 2
        d.rounded_rectangle([x, y, x + lg.width + 48, y + lg.height + 36], 28, fill="white")
        img.paste(lg, (x + 24, y + 18), lg)
        y += lg.height + 110
    f1, f2 = font(True, 64), font(False, 42)
    for t, f, c in (("SUBSCRIBE karein", f1, ORANGE), ("Free guidance: Call / WhatsApp", f2, (203, 213, 225)),
                    (C("PHONE", "8982264044"), f1, (255, 255, 255))):
        d.text(((SW - d.textlength(t, font=f)) / 2, y), t, font=f, fill=c)
        y += 100
    img.save(out_path, quality=93)
    return out_path


def make_free_video(parts, out_path, topic="", photo_path=None):
    """Free video: har hisse ke liye stock clip + Hindi awaaz + subtitle, aakhir mein logo/subscribe card."""
    import subprocess
    ff = ffmpeg_exe()
    hi, qs = hindi_and_queries(parts, topic)
    used, segs, auds = set(), [], []
    for i, part in enumerate(parts):
        mp3 = os.path.join(OUT, f"_fv_a{i}.mp3")
        free_tts(hi[i], part, mp3)
        dur = audio_seconds(mp3) + 0.15
        auds.append(mp3)
        clip = pixabay_clip(qs[i], os.path.join(OUT, f"_fv_c{i}.mp4"), used)
        cap = caption_png(part, i, os.path.join(OUT, f"_fv_t{i}.png"))
        seg = os.path.join(OUT, f"_fv_s{i}.mp4")
        if clip:
            src = ["-stream_loop", "-1", "-i", clip]
            base = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30"
        else:
            bgimg = photo_path if photo_path and os.path.exists(photo_path) else end_card(os.path.join(OUT, "_fv_bg.jpg"))
            src = ["-loop", "1", "-i", bgimg]
            base = ("[0:v]scale=2160:3840:force_original_aspect_ratio=increase,crop=2160:3840,"
                    "zoompan=z='min(1+0.0008*on,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30")
        flt = f"{base},eq=brightness=-0.07[b];[b][1:v]overlay=0:0,format=yuv420p[v]"
        subprocess.run([ff, "-y"] + src + ["-loop", "1", "-i", cap, "-filter_complex", flt, "-map", "[v]",
                        "-t", f"{dur:.2f}", "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                        "-an", seg], check=True, capture_output=True)
        segs.append(seg)
    endimg = end_card(os.path.join(OUT, "_fv_end.jpg"))
    endseg = os.path.join(OUT, "_fv_end.mp4")
    subprocess.run([ff, "-y", "-loop", "1", "-i", endimg, "-t", "2.5", "-r", "30", "-vf", "format=yuv420p",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", endseg], check=True, capture_output=True)
    segs.append(endseg)
    vlist = os.path.join(OUT, "_fv_v.txt")
    alist = os.path.join(OUT, "_fv_a.txt")
    with open(vlist, "w") as f:
        f.write("".join(f"file '{os.path.abspath(s)}'\n" for s in segs))
    with open(alist, "w") as f:
        f.write("".join(f"file '{os.path.abspath(a)}'\n" for a in auds))
    total = sum(audio_seconds(a) + 0.15 for a in auds) + 2.5
    music = os.path.join(BASE, "music.mp3")
    cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", vlist, "-f", "concat", "-safe", "0", "-i", alist]
    if os.path.exists(music):
        cmd += ["-stream_loop", "-1", "-i", music, "-filter_complex",
                "[1:a]apad[va];[2:a]volume=0.10[m];[va][m]amix=inputs=2:duration=first:dropout_transition=0[a]",
                "-map", "0:v", "-map", "[a]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a", "-af", "apad"]
    cmd += ["-t", f"{total:.2f}", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out_path]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


def make_short(poster_path, out_path, seconds=12, voice=None):
    """Poster -> 1080x1920 vertical video with slow zoom (+ Hindi awaaz + music.mp3 if present)."""
    import math
    import subprocess
    if voice:
        seconds = min(58, math.ceil(audio_seconds(voice)) + 1)
    bg = Image.open(poster_path).convert("RGB")
    canvas = ImageOps.fit(bg, (1080, 1920)).filter(ImageFilter.GaussianBlur(40))
    canvas = Image.blend(canvas, Image.new("RGB", canvas.size, DARK), 0.35)
    pw = 960
    small = bg.resize((pw, int(1350 * pw / 1080)), Image.LANCZOS)
    canvas.paste(small, ((1080 - pw) // 2, (1920 - small.height) // 2))
    frame = os.path.join(OUT, "_frame.jpg")
    canvas.save(frame, quality=95)
    fps = 30
    n = seconds * fps
    zr = 0.05 / n
    vf = (f"scale=2160:3840,zoompan=z='min(1+{zr:.6f}*on,1.05)':x='iw/2-(iw/zoom/2)':"
          f"y='ih/2-(ih/zoom/2)':d={n}:s=1080x1920:fps={fps},format=yuv420p")
    cmd = [ffmpeg_exe(), "-y", "-loop", "1", "-i", frame]
    music = os.path.join(BASE, "music.mp3")
    has_music = os.path.exists(music)
    fade = f"afade=t=out:st={max(seconds - 2, 0)}:d=2"
    if voice and has_music:
        cmd += ["-i", voice, "-stream_loop", "-1", "-i", music, "-filter_complex",
                f"[2:a]volume=0.12[m];[1:a][m]amix=inputs=2:duration=first:dropout_transition=0,{fade}[a]",
                "-map", "0:v", "-map", "[a]"]
    elif voice:
        cmd += ["-i", voice, "-map", "0:v", "-map", "1:a", "-af", fade]
    elif has_music:
        cmd += ["-i", music, "-map", "0:v", "-map", "1:a", "-af", fade]
    if voice or has_music:
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    cmd += ["-vf", vf, "-t", str(seconds), "-c:v", "libx264", "-preset", "veryfast",
            "-crf", "22", "-movflags", "+faststart", out_path]
    subprocess.run(cmd, check=True, capture_output=True)
    return out_path


YT_SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
             "https://www.googleapis.com/auth/youtube.readonly"]
YT_READ = "https://www.googleapis.com/auth/youtube.readonly"


def find_client_secret():
    """client_secret file ko is folder ya Downloads mein dhoondhta hai (naam kuch bhi ho)."""
    import glob
    import shutil
    target = os.path.join(BASE, "client_secret.json")
    if os.path.exists(target):
        return target
    found = []
    for folder in (BASE, os.path.join(os.path.expanduser("~"), "Downloads")):
        found += [f for f in glob.glob(os.path.join(folder, "client_secret*")) if os.path.isfile(f)]
    if not found:
        raise RuntimeError("client_secret file na is folder mein mili na Downloads mein. "
                           "Google Cloud se 'Download JSON' dobara karein.")
    newest = max(found, key=os.path.getmtime)
    shutil.copy(newest, target)
    print(f"Login file mil gayi: {os.path.basename(newest)}")
    return target


def youtube_client(interactive=False):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    tok = os.path.join(BASE, "youtube_token.json")
    creds = Credentials.from_authorized_user_file(tok) if os.path.exists(tok) else None
    if interactive:
        creds = None  # hamesha naya login, taaki saari permissions mil jayein
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not interactive:
            raise RuntimeError("YouTube login nahi hua. 'youtube_login.bat' chalayein.")
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(find_client_secret(), YT_SCOPES)
        creds = flow.run_local_server(port=0)
    with open(tok, "w") as f:
        f.write(creds.to_json())
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    yt.hc_creds = creds
    return yt


def publish_youtube(video_path, title, caption):
    from googleapiclient.http import MediaFileUpload
    yt = youtube_client()
    tags = re.findall(r"#(\w+)", caption)[:15]
    body = {"snippet": {"title": (title + " #shorts")[:100], "description": caption[:4900],
                        "tags": tags, "categoryId": "26", "defaultLanguage": "hi"},
            "status": {"privacyStatus": C("YOUTUBE_PRIVACY", "public"),
                       "selfDeclaredMadeForKids": False}}
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(video_path, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return resp["id"]


# ------------------------------------------------------------------ Meta (Facebook / Instagram)
def token():
    return C("PAGE_ACCESS_TOKEN")


def graph(method, path, **kw):
    kw.setdefault("timeout", 120)
    params = kw.pop("params", {})
    params["access_token"] = token()
    r = requests.request(method, f"{GRAPH}/{path}", params=params, **kw)
    j = r.json()
    if "error" in j:
        raise RuntimeError(f"Meta: {j['error'].get('message')}")
    return j


def meta_ready():
    return bool(C("PAGE_ACCESS_TOKEN") and C("FB_PAGE_ID"))


def upload_unpublished_photo(path):
    with open(path, "rb") as f:
        j = graph("POST", f"{C('FB_PAGE_ID')}/photos",
                  data={"published": "false", "temporary": "true"}, files={"source": f})
    return j["id"]


def photo_url(photo_id):
    j = graph("GET", photo_id, params={"fields": "images"})
    return max(j["images"], key=lambda i: i["width"])["source"]


def publish_facebook(photo_id, caption):
    j = graph("POST", f"{C('FB_PAGE_ID')}/feed",
              data={"message": caption, "attached_media": json.dumps([{"media_fbid": photo_id}])})
    return j["id"]


def publish_facebook_video(path, caption):
    with open(path, "rb") as f:
        j = graph("POST", f"{C('FB_PAGE_ID')}/videos", data={"description": caption}, files={"source": f}, timeout=600)
    return j["id"]


def publish_instagram_reel(video_url, caption):
    ig = C("IG_USER_ID")
    cid = graph("POST", f"{ig}/media", data={"media_type": "REELS", "video_url": video_url,
                                            "caption": caption, "share_to_feed": "true"})["id"]
    for _ in range(60):
        s_ = graph("GET", cid, params={"fields": "status_code"}).get("status_code")
        if s_ == "FINISHED":
            break
        if s_ == "ERROR":
            raise RuntimeError("Instagram ne Reel process nahi ki")
        time.sleep(10)
    return graph("POST", f"{ig}/media_publish", data={"creation_id": cid})["id"]


def publish_instagram(image_url, caption):
    ig = C("IG_USER_ID")
    c = graph("POST", f"{ig}/media", data={"image_url": image_url, "caption": caption})
    cid = c["id"]
    for _ in range(30):
        s = graph("GET", cid, params={"fields": "status_code"})
        if s.get("status_code") == "FINISHED":
            break
        if s.get("status_code") == "ERROR":
            raise RuntimeError("Instagram ne image process nahi ki")
        time.sleep(5)
    return graph("POST", f"{ig}/media_publish", data={"creation_id": cid})["id"]


# ------------------------------------------------------------------ Google Sheet (Apps Script web app)
def sheet(action, **payload):
    payload.update(action=action, secret=C("SHEET_SECRET"))
    r = requests.post(C("SHEET_WEBAPP_URL"), data=json.dumps(payload),
                      headers={"Content-Type": "text/plain"}, timeout=400)
    try:
        j = r.json()
    except Exception:
        raise RuntimeError(f"Sheet ka jawab samajh nahi aaya: {r.text[:200]}")
    if not j.get("ok"):
        raise RuntimeError(f"Sheet error: {j.get('error')}")
    return j


def heartbeat(kind, ok, msg=""):
    """Dashboard ko batata hai ki PC agent ne kya kiya."""
    try:
        sheet("heartbeat", kind=kind, ok=bool(ok), msg=str(msg)[:300], meta=meta_ready(),
              when=dt.datetime.now().strftime("%d-%m %H:%M"))
    except Exception:
        pass



# ----------------------------------------------------------------- HEYGEN CLONE VIDEO (haftey mein 3)
HG = "https://api.heygen.com"
HG_LOG = os.path.join(BASE, "heygen_log.json")
DAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def hg(method, path, **kw):
    r = requests.request(method, HG + path, headers={"x-api-key": C("HEYGEN_API_KEY"),
                                                    "Content-Type": "application/json"}, timeout=120, **kw)
    try:
        j = r.json()
    except Exception:
        raise RuntimeError(f"HeyGen {r.status_code}: {r.text[:200]}")
    if r.status_code >= 400 or j.get("error"):
        raise RuntimeError(f"HeyGen {r.status_code}: {str(j.get('error') or j)[:250]}")
    return j.get("data", j)


def heygen_ready():
    return bool(C("HEYGEN_API_KEY") and C("HEYGEN_AVATAR_ID") and C("HEYGEN_VOICE_ID"))


def clone_day_today():
    days = [DAYS[d.strip().lower()[:3]] for d in C("CLONE_DAYS", "mon,wed,fri").split(",") if d.strip()]
    return dt.date.today().weekday() in days


def clone_count_this_week():
    try:
        log_ = json.load(open(HG_LOG, encoding="utf-8"))
    except Exception:
        log_ = []
    monday = dt.date.today() - dt.timedelta(days=dt.date.today().weekday())
    return sum(1 for x in log_ if x.get("date", "") >= monday.isoformat()), log_


def make_clone_video(script, title, out_path):
    """HeyGen pe aapka clone script bolta hai -> 9:16 video download."""
    n, log_ = clone_count_this_week()
    limit = int(C("CLONE_PER_WEEK", "3") or 3)
    if n >= limit:
        raise RuntimeError(f"Is haftey ke {limit} clone video ban chuke (kharcha control)")
    engine = C("HEYGEN_ENGINE", "avatar_iii")
    body = {"type": "avatar", "avatar_id": C("HEYGEN_AVATAR_ID"), "voice_id": C("HEYGEN_VOICE_ID"),
            "script": script, "title": f"Health Coach - {title}"[:90], "resolution": "1080p",
            "aspect_ratio": "9:16", "engine": {"type": engine}}
    if C("HEYGEN_CAPTIONS", "yes").lower() == "yes":
        body["caption"] = {"file_format": "srt", "style": "default"}
    try:
        res = hg("POST", "/v3/videos", json=body)
    except Exception as e:
        if "caption" in body:  # captions na chalein to bina captions ke
            log(f"Captions ke saath nahi bana ({str(e)[:80]}), bina captions try...")
            body.pop("caption")
            res = hg("POST", "/v3/videos", json=body)
        else:
            raise
    vid = res.get("video_id") or res.get("id")
    log(f"HeyGen pe clone video ban raha hai (id {vid})... 2-10 minute")
    log_.append({"date": dt.date.today().isoformat(), "video_id": vid, "title": title})
    json.dump(log_[-60:], open(HG_LOG, "w", encoding="utf-8"), indent=1)
    for _ in range(90):  # ~30 minute tak
        time.sleep(20)
        st = hg("GET", f"/v3/videos/{vid}")
        status = st.get("status")
        if status == "completed":
            url = st.get("captioned_video_url") or st.get("video_url")
            with open(out_path, "wb") as f:
                f.write(requests.get(url, timeout=300).content)
            with open(out_path + ".heygen", "w") as f:
                f.write(vid)
            log(f"Clone video download ho gaya ({st.get('duration', '?')} sec).")
            return out_path
        if status == "failed":
            raise RuntimeError(f"HeyGen fail: {st.get('failure_code')} {st.get('failure_message')}")
    raise RuntimeError("HeyGen video 30 minute mein nahi bana")


def cmd_heygen_setup():
    """Aapke HeyGen clone (look) aur awaaz ki ID dhoondh ke config.ini mein bharta hai."""
    if not C("HEYGEN_API_KEY"):
        print("Pehle config.ini mein HEYGEN_API_KEY daalein."); return
    looks = hg("GET", "/v3/avatars/looks", params={"avatar_type": "digital_twin", "ownership": "private", "limit": 50})
    looks = looks.get("looks") or looks.get("items") or (looks if isinstance(looks, list) else [])
    if not looks:
        print("Aapka koi Digital Twin (clone) nahi mila. HeyGen website pe pehle clone banayein."); return
    print("\nAapke clone looks:")
    for i, l in enumerate(looks, 1):
        print(f"  {i}. {l.get('name') or l.get('look_name') or l.get('id')}   engines: {l.get('supported_api_engines', '?')}")
    n = input("Kaunsa look? number [1]: ").strip() or "1"
    look = looks[int(n) - 1]
    voices = hg("GET", "/v3/models/audio/voices", params={"limit": 100})
    voices = voices.get("voices") or voices.get("items") or (voices if isinstance(voices, list) else [])
    mine = [v for v in voices if str(v.get("ownership", v.get("type", ""))).lower() in ("private", "clone", "custom")] or voices
    print("\nAwaaz (aapki clone awaaz upar honi chahiye):")
    for i, v in enumerate(mine[:40], 1):
        print(f"  {i}. {v.get('name') or v.get('voice_name')}  ({v.get('language', '')} {v.get('gender', '')})")
    n = input("Kaunsi awaaz? number [1]: ").strip() or "1"
    voice = mine[int(n) - 1]
    text = open(os.path.join(BASE, "config.ini"), encoding="utf-8").read()
    for k, v in (("HEYGEN_AVATAR_ID", look.get("id") or look.get("look_id")),
                 ("HEYGEN_VOICE_ID", voice.get("voice_id") or voice.get("id"))):
        if re.search(rf"(?m)^{k}\s*=", text):
            text = re.sub(rf"(?m)^{k}\s*=.*$", lambda m: f"{k} = {v}", text)
        else:
            text += f"\n{k} = {v}"
    open(os.path.join(BASE, "config.ini"), "w", encoding="utf-8").write(text)
    eng = look.get("supported_api_engines")
    if eng and "avatar_iii" not in str(eng):
        print(f"\nDHYAN: is look pe sasta Avatar III engine nahi chalta ({eng}). Kharcha zyada hoga.")
    print("\nHo gaya! Clone aur awaaz config.ini mein save.")



# ------------------------------------------------------------------ PERFORMANCE + NEXT WEEK STRATEGY
POSTED = os.path.join(BASE, "posted.json")
PERF = os.path.join(BASE, "performance.json")


def _load(path, default):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def record_posted(row, yt_id):
    p = _load(POSTED, [])
    p.append({"date": row.get("date", ""), "yt": yt_id, "topic": row.get("topic", ""),
              "title": row.get("title", "")})
    json.dump(p[-500:], open(POSTED, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def performance_context():
    """Roz ke topic prompt mein jaata hai: hamare channel pe kya chala."""
    perf = _load(PERF, {})
    if not perf.get("videos"):
        return ""
    top = sorted(perf["videos"], key=lambda v: -v["views"])[:5]
    low = sorted(perf["videos"], key=lambda v: v["views"])[:3]
    lines = ["OUR OWN CHANNEL PERFORMANCE (learn from it):",
             "Best: " + "; ".join(f"{v['topic']} ({v['views']} views)" for v in top),
             "Weakest: " + "; ".join(f"{v['topic']} ({v['views']} views)" for v in low)]
    if perf.get("strategy"):
        lines.append("THIS WEEK'S STRATEGY: " + perf["strategy"])
    return "\n".join(lines)


def cmd_performance(force_strategy=False):
    posted = _load(POSTED, [])
    yt = youtube_client()
    # channel ki saari uploads (pehle wale videos bhi) + hamara record (topic naam ke liye)
    try:
        ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
        up = ch["contentDetails"]["relatedPlaylists"]["uploads"]
        items = yt.playlistItems().list(part="snippet", playlistId=up, maxResults=50).execute().get("items", [])
        known = {p.get("yt") for p in posted}
        for it in reversed(items):
            sn = it["snippet"]
            vid = sn.get("resourceId", {}).get("videoId")
            if vid and vid not in known:
                posted.append({"date": sn.get("publishedAt", "")[:10], "yt": vid,
                               "topic": sn.get("title", "").replace("#shorts", "").strip(), "title": sn.get("title", "")})
    except Exception as e:
        log(f"Channel uploads nahi padhe: {str(e)[:80]}")
    if not posted:
        heartbeat("performance", True, "Abhi koi YouTube video nahi mila")
        return
    ids = [p["yt"] for p in posted if p.get("yt")][-200:]
    stats = {}
    for i in range(0, len(ids), 50):
        r = yt.videos().list(part="statistics", id=",".join(ids[i:i + 50])).execute()
        for it in r.get("items", []):
            st = it.get("statistics", {})
            stats[it["id"]] = (int(st.get("viewCount", 0)), int(st.get("likeCount", 0)), int(st.get("commentCount", 0)))
    vids = []
    for p in posted:
        v, l, c = stats.get(p.get("yt"), (0, 0, 0))
        vids.append({"date": p["date"], "topic": p["topic"], "title": p["title"], "views": v, "likes": l, "comments": c})
    perf = _load(PERF, {})
    perf["videos"], perf["updated"] = vids, dt.datetime.now().strftime("%d-%m %H:%M")
    total = sum(v["views"] for v in vids)
    best = max(vids, key=lambda v: v["views"])
    week_old = perf.get("strategy_date", "") < (dt.date.today() - dt.timedelta(days=7)).isoformat()
    if force_strategy or dt.date.today().weekday() == 6 or week_old or not perf.get("strategy"):
        table = "\n".join(f"- {v['date']} | {v['topic']} | {v['title']} | {v['views']} views, {v['likes']} likes, {v['comments']} comments"
                          for v in vids[-40:])
        ask = ("You are the growth strategist for 'The Health Coach' YouTube Shorts channel (Hindi/Hinglish health tips, "
               "Indore). Here is the performance of our videos:\n" + table +
               "\n\nWrite next week's content strategy in simple Hinglish (Roman script), max 60 words, as 3 short "
               "points: which topic types to do more of, which to avoid, and one hook/title style tip. "
               "Note: if most views are 0 the videos may still be private - then say to make them public first. Plain text only.")
        try:
            perf["strategy"] = gemini_any(ask).strip()[:500]
        except Exception as e:
            perf["strategy"] = (f"Sabse zyada chala: {best['topic']} ({best['views']} views). Isi tarah ke topic zyada banayein."
                                if total else "Abhi views 0 hain - YouTube Studio mein videos Public karein, tabhi asli data aayega.")
            log(f"Strategy AI se nahi bani: {str(e)[:80]}")
        perf["strategy_date"] = dt.date.today().isoformat()
    json.dump(perf, open(PERF, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    msg = (f"{len(vids)} videos, kul {total} views. Top: {best['title'] or best['topic']} ({best['views']}). "
           f"Strategy: {perf.get('strategy', '')}")
    log("Performance: " + msg[:200])
    heartbeat("performance", True, msg)


# ------------------------------------------------------------------ commands
def cmd_generate(force=False):
    os.makedirs(OUT, exist_ok=True)
    today = dt.date.today().isoformat()
    done = os.path.join(OUT, f"{today}.done")
    if os.path.exists(done) and not force:
        log("Aaj ka post pehle hi ban chuka hai.")
        return
    log("Aaj ka content ban raha hai...")
    data = make_content()
    log(f"Topic: {data['topic']}  |  {data.get('why_today', '')}")
    photo = get_photo(data.get("photo_query", "healthy lifestyle"))
    poster = make_poster(data, photo, os.path.join(OUT, f"{today}.jpg"))
    caption = data["caption"].strip() + "\n\n" + data.get("hashtags", "").strip()
    with open(os.path.join(OUT, f"{today}.txt"), "w", encoding="utf-8") as f:
        f.write(caption)
    video_kind, vb64 = "poster", ""
    vpath = os.path.join(OUT, f"{today}.mp4")
    if heygen_ready() and clone_day_today():
        try:
            make_clone_video(data.get("video_script") or data["caption"][:500], data["poster_title"], vpath)
            video_kind = "clone"
            with open(os.path.join(OUT, f"{today}_script.txt"), "w", encoding="utf-8") as f:
                f.write(data.get("video_script", ""))
            if os.path.getsize(vpath) < 30 * 1024 * 1024:
                import base64
                vb64 = base64.b64encode(open(vpath, "rb").read()).decode()
        except Exception as e:
            log(f"Clone video nahi bana, poster wala video banega: {e}")
    if video_kind == "poster" and C("FREE_VIDEO", "no").lower() == "yes":
        try:
            make_free_video(script_parts_from_data(data), vpath, data.get("topic", ""), photo)
            video_kind = "free"
            log("Free video ban gaya (stock clips + Hindi awaaz).")
            if os.path.getsize(vpath) < 30 * 1024 * 1024:
                import base64
                vb64 = base64.b64encode(open(vpath, "rb").read()).decode()
        except Exception as e:
            log(f"Free video nahi bana: {str(e)[:150]}")
    if video_kind == "poster" and C("VIDEO_ON_OTHER_DAYS", "no").lower() == "yes":
        voice = None
        if C("VOICEOVER", "yes").lower() == "yes":
            try:
                voice = make_voice(data, os.path.join(OUT, f"{today}_voice.mp3"))
                log("Hindi awaaz ban gayi.")
            except Exception as e:
                log(f"Awaaz nahi bani, bina awaaz ka video banega: {str(e)[:100]}")
        try:
            try:
                make_story_short(data, photo, vpath, voice=voice)
            except Exception as e:
                log(f"4-scene video nahi bana ({str(e)[:80]}), poster video bana rahe hain")
                make_short(poster, vpath, voice=voice)
            log("YouTube Short video ban gaya" + (" (Hindi awaaz ke saath)." if voice else "."))
        except Exception as e:
            log(f"Video nahi bana: {e}")
    pid, url, b64 = "", "", ""
    if meta_ready():
        try:
            pid = upload_unpublished_photo(poster)  # private upload; nothing is public yet
            url = photo_url(pid)
        except Exception as e:
            log(f"Facebook upload abhi nahi hua ({e}); preview Drive se banega.")
    if not url:
        import base64
        with open(poster, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
    why = data.get("why_today", "")
    if data.get("source") and data["source"] not in ("season", why):
        why += f"  [Source: {data['source']}]"
    sheet("add", date=today, topic=data["topic"], title=data["poster_title"],
          why=why, caption=caption, image_url=url, photo_id=pid, img_b64=b64,
          video_kind=video_kind, video_b64=vb64)
    h = load_history()
    h["topics"].append(data["topic"])
    save_history(h)
    open(done, "w").close()
    log("Post Sheet mein bhej diya. Approve ka intezaar hai.")
    rs = RESEARCH_SUMMARY
    src = data.get("source", "")
    rmsg = (f"{rs.get('news', 0)} khabrein, {rs.get('health_trends', 0)} Google trends, {rs.get('yt', 0)} YouTube Shorts"
            + (f", {rs.get('ig', 0)} Instagram posts" if rs.get('ig') else "") + " padhe") if rs else "research nahi hua"
    heartbeat("generate", True, f"{rmsg} -> Topic: {data['topic']}" + (f" (source: {src})" if src and src != "season" else "")
              + (" | Aaj CLONE video bana" if video_kind == "clone" else ""))


def cmd_publish():
    res = sheet("pending")
    if res.get("gen_request"):
        log("Dashboard se naye post ki request aayi.")
        sheet("clear_request")
        try:
            cmd_generate(force=True)
        except Exception as e:
            log(f"Request wala post nahi bana: {e}")
            heartbeat("generate", False, e)
        res = sheet("pending")
    after = C("PUBLISH_AFTER", "09:00")
    if dt.datetime.now().strftime("%H:%M") < after:
        log(f"{after} se pehle post nahi karte. Baad mein check hoga.")
        heartbeat("publish", True, f"{after} ke baad post karega")
        return
    rows = res.get("rows", [])
    if not rows:
        log("Koi naya approved post nahi.")
        heartbeat("publish", True, "Koi naya approved post nahi")
        return
    results = []
    for row in rows:
        r, cap, pid = row["row"], row["caption"], (row.get("photo_id") or "").strip("'")
        fb_id = row.get("fb_id") or ""
        ig_id = str(row.get("ig_id") or "").strip("'")
        errors, skipped = [], []
        poster = os.path.join(OUT, f"{row.get('date', '')}.jpg")
        want_fb = C("POST_TO_FACEBOOK", "yes").lower() == "yes" and not fb_id
        want_ig = C("POST_TO_INSTAGRAM", "yes").lower() == "yes" and not ig_id
        if (want_fb or want_ig) and not meta_ready():
            skipped.append("FB/IG (Meta connect baaki)")
            want_fb = want_ig = False
        vfile = os.path.join(OUT, f"{row.get('date', '')}.mp4")
        clone_id = ""
        if os.path.exists(vfile + ".heygen"):
            clone_id = open(vfile + ".heygen").read().strip()
        if clone_id and (want_fb or want_ig):  # clone wala din: photo nahi, Reel/video
            if want_fb:
                try:
                    fb_id = publish_facebook_video(vfile, cap)
                    log(f"Facebook pe clone video post: {fb_id}")
                except Exception as e:
                    errors.append(f"FB video: {e}")
            if want_ig:
                try:
                    st = hg("GET", f"/v3/videos/{clone_id}")
                    ig_id = publish_instagram_reel(st.get("captioned_video_url") or st["video_url"], cap)
                    log(f"Instagram Reel post: {ig_id}")
                except Exception as e:
                    errors.append(f"IG reel: {e}")
            want_fb = want_ig = False
        if (want_fb or want_ig) and not pid:
            try:
                pid = upload_unpublished_photo(poster)
            except Exception as e:
                errors.append(f"Photo upload: {e}")
                want_fb = want_ig = False
        if want_fb:
            try:
                fb_id = publish_facebook(pid, cap)
                log(f"Facebook pe post ho gaya: {fb_id}")
            except Exception as e:
                errors.append(f"FB: {e}")
        if want_ig:
            try:
                ig_id = publish_instagram(photo_url(pid), cap)
                log(f"Instagram pe post ho gaya: {ig_id}")
            except Exception as e:
                errors.append(f"IG: {e}")
        yt_id = row.get("yt_id") or ""
        video = os.path.join(OUT, f"{row.get('date', '')}.mp4")
        if C("POST_TO_YOUTUBE", "yes").lower() == "yes" and not yt_id and os.path.exists(video):
            try:
                if not os.path.exists(video):
                    raise RuntimeError("video file nahi mili")
                yt_id = publish_youtube(video, row.get("title") or row.get("topic", ""), cap)
                log(f"YouTube pe upload ho gaya: {yt_id}")
                try:
                    record_posted(row, yt_id)
                except Exception:
                    pass
            except Exception as e:
                errors.append(f"YT: {e}")
        status = ("POSTED " + dt.datetime.now().strftime("%d-%m %H:%M")) if not errors else ("ERROR - " + " | ".join(errors))
        if skipped and not errors:
            status += "  (skip: " + ", ".join(skipped) + ")"
        sheet("update", row=r, status=status, fb_id=fb_id, ig_id=ig_id, yt_id=yt_id)
        log(f"Row {r}: {status}")
        results.append((not errors, status))
    bad = [st for ok, st in results if not ok]
    heartbeat("publish", not bad, bad[0] if bad else f"{len(results)} post publish kiye")


def cmd_test():
    ok = True

    def chk(name, fn):
        nonlocal ok
        try:
            res = fn()
            print(f"  [OK]   {name} {res or ''}")
        except Exception as e:
            ok = False
            print(f"  [FAIL] {name} -> {e}")

    print("\nThe Health Coach - setup check\n")
    chk("Gemini AI", lambda: "-> " + gemini_any("Reply with just the word READY").strip()[:20])
    chk("Photos", lambda: "(key nahi hai, rangeen background use hoga)" if not (C("PIXABAY_API_KEY") or C("PEXELS_API_KEY")) else
        "-> " + ("photo mil gayi" if get_photo("yoga") else "photo nahi mili, key check karein"))
    chk("Facebook Page", lambda: "(abhi connect nahi, baad mein)" if not meta_ready() else "-> " + graph("GET", C("FB_PAGE_ID"), params={"fields": "name"})["name"])
    chk("Instagram", lambda: "(abhi connect nahi, baad mein)" if not meta_ready() else "-> @" + graph("GET", C("IG_USER_ID"), params={"fields": "username"})["username"])
    chk("YouTube", lambda: "-> login OK" if youtube_client() else "")
    chk("HeyGen clone", lambda: "(abhi set nahi, poster video banenge)" if not heygen_ready() else
        "-> OK, clone days: " + C("CLONE_DAYS", "mon,wed,fri") + f", is haftey bane: {clone_count_this_week()[0]}")
    chk("Video maker", lambda: "-> " + os.path.basename(ffmpeg_exe()))
    chk("Google Sheet", lambda: "-> " + str(len(sheet("pending").get("rows", []))) + " approved pending")
    print("\nSab theek hai!" if ok else "\nJo FAIL hai, uski setting config.ini mein check karein.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    try:
        {"generate": cmd_generate, "generate_now": lambda: cmd_generate(force=True), "publish": cmd_publish, "test": cmd_test,
         "heygen_setup": cmd_heygen_setup,
         "performance": lambda: cmd_performance(force_strategy=True),
         "youtube_login": lambda: (youtube_client(interactive=True), print("YouTube login ho gaya!"))}[cmd]()
    except Exception as e:
        log(f"ERROR ({cmd}): {e}\n{traceback.format_exc()}")
        if cmd in ("generate", "generate_now", "publish", "performance"):
            heartbeat("generate" if cmd.startswith("generate") else cmd, False, f"{type(e).__name__}: {e}")
        sys.exit(1)
