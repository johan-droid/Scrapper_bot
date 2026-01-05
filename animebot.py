import os
import re
import json
import time
import uuid
import pytz
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from threading import Thread
from concurrent.futures import ThreadPoolExecutor
from tenacity import retry, stop_after_attempt, wait_exponential
from flask import Flask, request
from dotenv import load_dotenv

try:
    from supabase import create_client
except Exception as e:
    logging.warning(f"Supabase import failed: {e}. Falling back to JSON storage.")
    create_client = None

# =========================
# ENV + LOGGING
# =========================
env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path, override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("anime_news_bot.log"), logging.StreamHandler()],
    force=True,
)

SESSION_ID = str(uuid.uuid4())[:8]

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ADMIN_ID = os.getenv("ADMIN_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")

POSTED_TITLES_FILE = "posted_titles.json"

BASE_URL = "https://www.animenewsnetwork.com"
BASE_URL_DC = "https://www.detectiveconanworld.com"
BASE_URL_TMS = "https://tmsanime.com"
BASE_URL_FANDOM = "https://detectiveconan.fandom.com"
BASE_URL_ANN_DC = "https://www.animenewsnetwork.com/encyclopedia/anime.php?id=454&tab=news"

DEBUG_MODE = False

# Fixed schedule (IST): 00:00, 04:00, 08:00, 12:00, 16:00, 20:00
SLOTS_PER_DAY = 6
SLOT_HOURS = [0, 4, 8, 12, 16, 20]

SOURCE_LABEL = {
    "ANN": "Anime News Network",
    "ANN_DC": "ANN (Detective Conan)",
    "DCW": "Detective Conan Wiki",
    "TMS": "TMS Entertainment",
    "FANDOM": "Fandom Wiki",
}

if not BOT_TOKEN or not CHAT_ID:
    logging.error("BOT_TOKEN or CHAT_ID is missing. Check environment variables.")
    raise SystemExit(1)

utc_tz = pytz.utc
local_tz = pytz.timezone("Asia/Kolkata")

supabase = None
if SUPABASE_URL and SUPABASE_KEY and create_client:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logging.info("Supabase connected")
    except Exception as e:
        logging.error(f"Supabase init failed: {e}")

session = requests.Session()
session.headers.update(
    {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }
)

app = Flask(__name__)

# =========================
# TIME/SLOT HELPERS
# =========================
def now_local():
    return datetime.now(local_tz)

def slot_index(dt_local: datetime) -> int:
    return dt_local.hour // 4  # 0..5

def slot_start_for(dt_local: datetime) -> datetime:
    h = (dt_local.hour // 4) * 4
    return dt_local.replace(hour=h, minute=0, second=0, microsecond=0)

def next_slot_start(dt_local: datetime) -> datetime:
    nxt_h = ((dt_local.hour // 4) + 1) * 4
    if nxt_h >= 24:
        tomorrow = (dt_local + timedelta(days=1)).date()
        return dt_local.replace(
            year=tomorrow.year,
            month=tomorrow.month,
            day=tomorrow.day,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    return dt_local.replace(hour=nxt_h, minute=0, second=0, microsecond=0)

# =========================
# BASIC WEB + WEBHOOK
# =========================
@app.route("/")
def home():
    return f"Bot is alive! Session: {SESSION_ID}", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        update = request.get_json()
        if not update:
            return "OK", 200

        msg = update.get("message", {})
        if msg.get("text") == "/start":
            user_id = str(msg.get("from", {}).get("id", ""))
            chat_id = msg.get("chat", {}).get("id")
            if (not ADMIN_ID) or (user_id == str(ADMIN_ID)):
                send_message(chat_id, get_simple_stats())
        return "OK", 200
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return "OK", 200

def keep_alive():
    if not RENDER_EXTERNAL_URL:
        return
    while True:
        try:
            time.sleep(300)
            r = requests.get(RENDER_EXTERNAL_URL, timeout=5)
            logging.info(f"Self-ping status: {r.status_code}")
        except Exception as e:
            logging.error(f"Self-ping failed: {e}")

# =========================
# TEXT HELPERS
# =========================
def escape_html(text):
    if not text or not isinstance(text, str):
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def get_normalized_key(title):
    prefixes = ["DC Wiki Update: ", "TMS News: ", "Fandom Wiki Update: ", "ANN DC News: "]
    for p in prefixes:
        if title.startswith(p):
            return title[len(p):].strip()
    return title.strip()

# =========================
# SUPABASE: STATS
# =========================
def initialize_bot_stats():
    if not supabase:
        return
    try:
        resp = supabase.table("bot_stats").select("*").limit(1).execute()
        if not resp.data:
            now = datetime.now(utc_tz).isoformat()
            supabase.table("bot_stats").insert(
                {"bot_started_at": now, "total_posts_all_time": 0, "last_seen": now}
            ).execute()
    except Exception as e:
        logging.error(f"initialize_bot_stats failed: {e}")

def ensure_daily_row(date_obj):
    if not supabase:
        return
    try:
        r = supabase.table("daily_stats").select("date").eq("date", str(date_obj)).limit(1).execute()
        if not r.data:
            supabase.table("daily_stats").insert(
                {"date": str(date_obj), "posts_count": 0}
            ).execute()
    except Exception as e:
        logging.error(f"ensure_daily_row failed: {e}")

def increment_post_counters(date_obj):
    if not supabase:
        return
    try:
        ensure_daily_row(date_obj)

        d = supabase.table("daily_stats").select("posts_count").eq("date", str(date_obj)).limit(1).execute()
        cur_daily = int(d.data[0].get("posts_count", 0)) if d.data else 0
        supabase.table("daily_stats").update(
            {"posts_count": cur_daily + 1, "updated_at": datetime.now(utc_tz).isoformat()}
        ).eq("date", str(date_obj)).execute()

        b = supabase.table("bot_stats").select("*").limit(1).execute()
        if b.data:
            bot = b.data[0]
            total = int(bot.get("total_posts_all_time", 0))
            supabase.table("bot_stats").update(
                {"total_posts_all_time": total + 1, "last_seen": datetime.now(utc_tz).isoformat()}
            ).eq("id", bot["id"]).execute()
    except Exception as e:
        logging.error(f"increment_post_counters failed: {e}")

def get_simple_stats():
    if not supabase:
        return "<b>⚠️ Database not connected.</b>"

    today = now_local().date()
    ensure_daily_row(today)

    daily = supabase.table("daily_stats").select("posts_count").eq("date", str(today)).limit(1).execute()
    today_posts = int(daily.data[0]["posts_count"]) if daily.data else 0

    bot = supabase.table("bot_stats").select("total_posts_all_time").limit(1).execute()
    total_posts = int(bot.data[0]["total_posts_all_time"]) if bot.data else 0

    return (
        "<b>Detective Conan News Bot</b>\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        f"• <b>Posts Today:</b> {today_posts}\n"
        f"• <b>Total Posts:</b> {total_posts}\n"
        f"• <b>Active Sources:</b> 4\n"
    )

# =========================
# SUPABASE: RUNS (UPSERT SAFE)
# =========================
def get_run(date_obj, slot):
    if not supabase:
        return None
    try:
        r = (
            supabase.table("runs")
            .select("id,status")
            .eq("date", str(date_obj))
            .eq("slot", slot)
            .limit(1)
            .execute()
        )
        if r.data:
            return r.data[0]["id"], r.data[0].get("status")
    except Exception as e:
        logging.error(f"get_run failed: {e}")
    return None

def create_or_reuse_run(date_obj, slot, scheduled_local):
    if not supabase:
        return None

    scheduled_utc = scheduled_local.astimezone(utc_tz).isoformat()
    now_utc = datetime.now(utc_tz).isoformat()

    existing = get_run(date_obj, slot)
    if existing and existing[1] == "success":
        return None

    payload = {
        "date": str(date_obj),
        "slot": slot,
        "scheduled_at": scheduled_utc,
        "started_at": now_utc,
        "status": "started",
        "posts_sent": 0,
        "source_counts": {},
        "error": None,
    }

    try:
        resp = supabase.table("runs").upsert(payload, on_conflict="date,slot").execute()
        if resp.data:
            return resp.data[0]["id"]
    except Exception as e:
        logging.error(f"create_or_reuse_run failed: {e}")

    existing2 = get_run(date_obj, slot)
    return existing2[0] if existing2 else None

def finish_run(run_id, status, posts_sent, source_counts, error=None):
    if not supabase or not run_id:
        return
    try:
        supabase.table("runs").update(
            {
                "status": status,
                "posts_sent": posts_sent,
                "source_counts": source_counts,
                "finished_at": datetime.now(utc_tz).isoformat(),
                "error": error,
            }
        ).eq("id", run_id).execute()
    except Exception as e:
        logging.error(f"finish_run failed: {e}")

def completed_slots_today(date_obj):
    if not supabase:
        return set()
    try:
        r = (
            supabase.table("runs")
            .select("slot")
            .eq("date", str(date_obj))
            .eq("status", "success")
            .execute()
        )
        return set(int(x["slot"]) for x in r.data)
    except Exception as e:
        logging.error(f"completed_slots_today failed: {e}")
        return set()

# =========================
# POSTED NEWS (DEDUPE CACHE)
# =========================
def load_posted_titles_for_date(date_obj):
    if supabase:
        try:
            r = (
                supabase.table("posted_news")
                .select("normalized_title")
                .eq("posted_date", str(date_obj))
                .execute()
            )
            return set(x["normalized_title"] for x in r.data)
        except Exception as e:
            logging.error(f"load_posted_titles_for_date failed: {e}")

    try:
        if os.path.exists(POSTED_TITLES_FILE):
            with open(POSTED_TITLES_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
    except Exception:
        pass
    return set()

def save_posted_fallback(normalized_title):
    titles = load_posted_titles_for_date(now_local().date())
    titles.add(normalized_title)
    with open(POSTED_TITLES_FILE, "w", encoding="utf-8") as f:
        json.dump(list(titles), f)

def record_post(title, source_code, run_id, slot, posted_titles_set):
    key = get_normalized_key(title)
    date_obj = now_local().date()
    now_utc = datetime.now(utc_tz).isoformat()

    if key in posted_titles_set:
        return False

    if supabase:
        try:
            supabase.table("posted_news").insert(
                {
                    "normalized_title": key,
                    "posted_date": str(date_obj),
                    "full_title": title,
                    "posted_at": now_utc,
                    "source": source_code,
                    "run_id": run_id,
                    "slot": slot,
                }
            ).execute()
            posted_titles_set.add(key)
            increment_post_counters(date_obj)
            return True
        except Exception:
            posted_titles_set.add(key)
            return False

    posted_titles_set.add(key)
    save_posted_fallback(key)
    return True

# =========================
# SCRAPERS (SOURCE INCLUDED)
# =========================
def validate_image_url(image_url):
    if not image_url:
        return False
    try:
        headers = {"Range": "bytes=0-511"}
        r = session.get(image_url, headers=headers, timeout=5, stream=True)
        r.raise_for_status()
        return r.headers.get("content-type", "").startswith("image/")
    except Exception:
        return False

def extract_video_url(soup):
    try:
        youtube = soup.find("iframe", src=re.compile(r"youtube\.com/embed|youtu\.be"))
        if youtube:
            src = youtube.get("src", "")
            m = re.search(r"embed/([a-zA-Z0-9_-]+)", src)
            if m:
                return f"https://www.youtube.com/watch?v={m.group(1)}"
    except Exception:
        pass
    return None

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
def fetch_anime_news():
    try:
        r = session.get(BASE_URL, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        today = now_local().date()
        out = []
        for article in soup.find_all("div", class_="herald box news t-news"):
            title_tag = article.find("h3")
            date_tag = article.find("time")
            if not title_tag or not date_tag:
                continue

            title = title_tag.get_text(" ", strip=True)
            date_str = date_tag.get("datetime", "")

            try:
                news_date = datetime.fromisoformat(date_str).astimezone(local_tz).date()
            except Exception:
                continue

            if DEBUG_MODE or news_date == today:
                link = title_tag.find("a")
                article_url = f"{BASE_URL}{link['href']}" if link else None
                out.append({"source": "ANN", "title": title, "article_url": article_url, "article": article})
        return out
    except Exception as e:
        logging.error(f"fetch_anime_news failed: {e}")
        return []

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
def fetch_ann_dc_news():
    try:
        r = session.get(BASE_URL_ANN_DC, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        today = now_local().date()
        out = []
        for article in soup.find_all("div", class_="herald box news t-news"):
            title_tag = article.find("h3")
            date_tag = article.find("time")
            if not title_tag or not date_tag:
                continue

            title = title_tag.get_text(" ", strip=True)
            date_str = date_tag.get("datetime", "")

            try:
                news_date = datetime.fromisoformat(date_str).astimezone(local_tz).date()
            except Exception:
                continue

            if DEBUG_MODE or news_date == today:
                link = title_tag.find("a")
                article_url = f"{BASE_URL}{link['href']}" if link else None
                out.append({"source": "ANN_DC", "title": f"ANN DC News: {title}", "article_url": article_url, "article": article})
        return out
    except Exception as e:
        logging.error(f"fetch_ann_dc_news failed: {e}")
        return []

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
def fetch_article_details(article_url, article):
    image_url = None
    summary = "No summary available."
    video_url = None
    date_str = None

    thumb = article.find("div", class_="thumbnail lazyload")
    if thumb and thumb.get("data-src"):
        img_url = thumb["data-src"]
        image_url = f"{BASE_URL}{img_url}" if not img_url.startswith("http") else img_url

    if article_url:
        try:
            r = session.get(article_url, timeout=12)
            r.raise_for_status()
            s = BeautifulSoup(r.text, "html.parser")

            video_url = extract_video_url(s)

            time_tag = s.find("time", {"itemprop": "datePublished"})
            if time_tag and time_tag.get("datetime"):
                try:
                    date_str = datetime.fromisoformat(time_tag["datetime"]).astimezone(local_tz).strftime("%b %d, %Y %I:%M %p")
                except Exception:
                    pass

            content_div = s.find("div", class_="meat") or s.find("div", class_="content")
            if content_div:
                for p in content_div.find_all("p"):
                    txt = p.get_text(" ", strip=True)
                    if len(txt) > 50:
                        summary = txt[:350] + "..." if len(txt) > 350 else txt
                        break
        except Exception:
            pass

    return {"image": image_url, "summary": summary, "video": video_url, "date": date_str}

def fetch_selected_articles(news_list):
    to_fetch = [x for x in news_list if x.get("article_url") and x.get("article")]
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(fetch_article_details, x["article_url"], x["article"]): x for x in to_fetch}
        for f in futures:
            x = futures[f]
            try:
                res = f.result(timeout=15)
                x["image"] = res["image"]
                x["summary"] = res["summary"]
                x["video"] = res["video"]
                x["date"] = res["date"]
            except Exception:
                x["image"] = None
                x["summary"] = "Failed to fetch summary."
                x["video"] = None
                x["date"] = None

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
def fetch_dc_updates():
    try:
        url = f"{BASE_URL_DC}/wiki/Special:RecentChanges"
        r = session.get(url, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        today = now_local().date()
        out = []
        changes = soup.find_all("li", class_=re.compile(r"mw-changeslist-line"))
        for change in changes:
            time_tag = change.find("a", class_="mw-changeslist-date")
            if not time_tag:
                continue
            time_str = time_tag.get_text(" ", strip=True)

            try:
                if "," in time_str:
                    date_str = time_str + f", {datetime.now().year}"
                else:
                    date_str = time_str
                change_date = (
                    datetime.strptime(date_str, "%H:%M, %d %B %Y")
                    .replace(tzinfo=pytz.utc)
                    .astimezone(local_tz)
                    .date()
                )
            except Exception:
                continue

            if DEBUG_MODE or change_date == today:
                title_tag = change.find("a", class_="mw-changeslist-title")
                if not title_tag:
                    continue
                page_title = title_tag.get_text(" ", strip=True)
                user_tag = change.find("a", class_="mw-userlink")
                user = user_tag.get_text(" ", strip=True) if user_tag else "Unknown"
                comment_tag = change.find("span", class_="comment")
                comment = comment_tag.get_text(" ", strip=True) if comment_tag else ""
                title = f"DC Wiki Update: {page_title}"
                summary = f"Edited by {user}. {comment}".strip()
                out.append({"source": "DCW", "title": title, "summary": summary})
        return out
    except Exception as e:
        logging.error(f"fetch_dc_updates failed: {e}")
        return []

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
def fetch_tms_news():
    try:
        r = session.get(BASE_URL_TMS + "/detective-conan", timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        out = []
        latest = soup.find(string=re.compile(r"LATEST\s+TMS\s+NEWS", re.IGNORECASE))
        if latest:
            parent = latest.parent
            links = parent.find_next_siblings("a")[:5]
            for a in links:
                t = a.get_text(" ", strip=True)
                href = a.get("href")
                if not t or not href:
                    continue
                title = f"TMS News: {t}"
                summary = f"Read more: {href}" if href.startswith("http") else f"Read more: {BASE_URL_TMS}{href}"
                out.append({"source": "TMS", "title": title, "summary": summary})
        return out
    except Exception as e:
        logging.error(f"fetch_tms_news failed: {e}")
        return []

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
def fetch_fandom_updates():
    try:
        url = f"{BASE_URL_FANDOM}/wiki/Special:RecentChanges"
        r = session.get(url, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        today = now_local().date()
        out = []
        changes = soup.find_all("li", class_=re.compile(r"mw-changeslist-line"))
        for change in changes:
            time_tag = change.find("a", class_="mw-changeslist-date")
            if not time_tag:
                continue
            time_str = time_tag.get_text(" ", strip=True)

            try:
                if "," in time_str:
                    date_str = time_str + f", {datetime.now().year}"
                else:
                    date_str = time_str
                change_date = (
                    datetime.strptime(date_str, "%H:%M, %d %B %Y")
                    .replace(tzinfo=pytz.utc)
                    .astimezone(local_tz)
                    .date()
                )
            except Exception:
                continue

            if DEBUG_MODE or change_date == today:
                title_tag = change.find("a", class_="mw-changeslist-title")
                if not title_tag:
                    continue
                page_title = title_tag.get_text(" ", strip=True)
                user_tag = change.find("a", class_="mw-userlink")
                user = user_tag.get_text(" ", strip=True) if user_tag else "Unknown"
                comment_tag = change.find("span", class_="comment")
                comment = comment_tag.get_text(" ", strip=True) if comment_tag else ""
                title = f"Fandom Wiki Update: {page_title}"
                summary = f"Edited by {user}. {comment}".strip()
                out.append({"source": "FANDOM", "title": title, "summary": summary})
        return out
    except Exception as e:
        logging.error(f"fetch_fandom_updates failed: {e}")
        return []

# =========================
# TELEGRAM SEND
# =========================
def send_message(chat_id, text):
    try:
        session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=15,
        ).raise_for_status()
    except Exception as e:
        logging.error(f"send_message failed: {e}")

def build_message(item):
    source_code = item.get("source", "ANN")
    src_label = SOURCE_LABEL.get(source_code, source_code)

    title = escape_html(get_normalized_key(item["title"]))
    summary = escape_html(item.get("summary", "No summary available."))
    date_str = escape_html(item.get("date", "")) if item.get("date") else ""
    article_url = item.get("article_url")
    video_url = item.get("video")

    lines = [
        "┏━━━━━━━━━━━━━━━━━━━┓",
        "<b>ANIME NEWS UPDATE</b>",
        "┗━━━━━━━━━━━━━━━━━━━┛",
        "",
        f"▶️ <b>{title}</b>",
        "",
        summary,
    ]

    meta = []
    if date_str:
        meta.append(f"📅 {date_str}")
    if article_url:
        meta.append(f"🔗 <a href='{article_url}'>Read more</a>")
    if video_url:
        meta.append(f"🎥 <a href='{video_url}'>Watch</a>")
    if meta:
        lines += ["", " • ".join(meta)]

    lines += ["", f"🛰️ <i>Source:</i> <b>{escape_html(src_label)}</b>"]
    return "\n".join(lines)

def send_to_telegram(item, run_id, slot, posted_titles_set):
    source_code = item.get("source", "ANN")
    title = item["title"]
    message = build_message(item)

    image_url = item.get("image")
    if image_url and validate_image_url(image_url):
        try:
            session.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": CHAT_ID, "photo": image_url, "caption": message, "parse_mode": "HTML"},
                timeout=20,
            ).raise_for_status()
            return record_post(title, source_code, run_id, slot, posted_titles_set)
        except Exception as e:
            logging.error(f"sendPhoto failed: {e}")

    try:
        session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML", "disable_web_page_preview": False},
            timeout=20,
        ).raise_for_status()
        return record_post(title, source_code, run_id, slot, posted_titles_set)
    except Exception as e:
        logging.error(f"sendMessage failed: {e}")
        return False

# =========================
# SLOT RUNNER
# =========================
def run_slot(date_obj, slot, scheduled_local):
    logging.info(f"RUN slot={slot} date={date_obj} scheduled={scheduled_local.strftime('%H:%M')} IST")
    ensure_daily_row(date_obj)

    run_id = create_or_reuse_run(date_obj, slot, scheduled_local)
    if run_id is None:
        return

    posted_titles_set = load_posted_titles_for_date(date_obj)

    posts_sent = 0
    source_counts = {"ANN": 0, "ANN_DC": 0, "DCW": 0, "TMS": 0, "FANDOM": 0}

    try:
        ann = fetch_anime_news()
        ann_dc = fetch_ann_dc_news()
        fetch_selected_articles(ann + ann_dc)

        dcw = fetch_dc_updates()
        tms = fetch_tms_news()
        fandom = fetch_fandom_updates()

        items = ann + dcw + tms + fandom + ann_dc

        for item in items:
            if send_to_telegram(item, run_id, slot, posted_titles_set):
                posts_sent += 1
                sc = item.get("source", "ANN")
                source_counts[sc] = source_counts.get(sc, 0) + 1
                time.sleep(1.2)

        finish_run(run_id, "success", posts_sent, source_counts, None)
        logging.info(f"DONE slot={slot} posted={posts_sent}")
    except Exception as e:
        finish_run(run_id, "failed", posts_sent, source_counts, str(e))
        logging.error(f"run_slot failed: {e}")

# =========================
# MAIN LOOP
# =========================
def scheduler_loop():
    while True:
        dt = now_local()
        date_obj = dt.date()

        current_slot = slot_index(dt)
        completed = completed_slots_today(date_obj)

        # catch-up: run missing slots <= current slot
        missing = [s for s in range(0, current_slot + 1) if s not in completed]
        if missing:
            s = missing[0]
            scheduled_local = dt.replace(hour=s * 4, minute=0, second=0, microsecond=0)
            run_slot(date_obj, s, scheduled_local)
            continue

        nxt = next_slot_start(dt)
        sleep_s = max(1, int((nxt - dt).total_seconds()))
        time.sleep(sleep_s)

if __name__ == "__main__":
    initialize_bot_stats()

    if RENDER_EXTERNAL_URL:
        Thread(target=keep_alive, daemon=True).start()

    Thread(target=scheduler_loop, daemon=True).start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
