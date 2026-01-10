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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from flask import Flask, request
from dotenv import load_dotenv
from collections import defaultdict

try:
    from source_monitor import health_monitor, monitor_source_call
except ImportError:
    # Fallback if monitoring is not available
    health_monitor = None
    def monitor_source_call(source_name):
        def decorator(func):
            return func
        return decorator

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

# Circuit breaker for source failures
class SourceCircuitBreaker:
    def __init__(self, failure_threshold=3, recovery_timeout=300):
        self.failure_counts = defaultdict(int)
        self.last_failure_time = defaultdict(float)
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
    
    def can_call(self, source):
        if self.failure_counts[source] < self.failure_threshold:
            return True
        
        # Check if recovery timeout has passed
        if time.time() - self.last_failure_time[source] > self.recovery_timeout:
            self.failure_counts[source] = 0
            return True
        
        return False
    
    def record_success(self, source):
        self.failure_counts[source] = 0
    
    def record_failure(self, source):
        self.failure_counts[source] += 1
        self.last_failure_time[source] = time.time()
        logging.warning(f"Circuit breaker: {source} failure count: {self.failure_counts[source]}")

circuit_breaker = SourceCircuitBreaker()

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
        logging.info("Supabase connected successfully")
    except Exception as e:
        logging.error(f"Supabase init failed: {e}")

# Session factory for web scraping
def get_scraping_session():
    """Create fresh session for web scraping with proper retry strategy"""
    session = requests.Session()
    
    # Configure retry strategy
    retry_strategy = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504, 104],
        allowed_methods=["GET", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=1, pool_maxsize=1)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "close",  # Prevent connection reuse issues
        "Upgrade-Insecure-Requests": "1",
    })
    
    return session

app = Flask(__name__)

# =========================
# TIME/SLOT HELPERS
# =========================
def now_local():
    return datetime.now(local_tz)

def slot_index(dt_local: datetime) -> int:
    return dt_local.hour // 4

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
# TELEGRAM SESSION HELPER
# =========================
def get_fresh_telegram_session():
    """
    Create a fresh session for Telegram API calls to avoid stale connection issues.
    Each call gets a new session with proper retry strategy.
    """
    tg_session = requests.Session()
    
    # Configure retry strategy for transient errors
    retry_strategy = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=1, pool_maxsize=1)
    tg_session.mount("https://", adapter)
    
    # Force connection closure to prevent stale connections
    tg_session.headers.update({"Connection": "close"})
    
    return tg_session

# =========================
# BASIC WEB + WEBHOOK
# =========================
@app.route("/")
def home():
    return f"Bot is alive! Session: {SESSION_ID}", 200

@app.route("/health")
def health_check():
    """Health check endpoint with source status"""
    try:
        if health_monitor:
            status = {}
            for source in ["ANN", "ANN_DC", "DCW", "TMS", "FANDOM"]:
                health = health_monitor.get_source_health(source)
                if health:
                    status[source] = {
                        "success_rate": health["success_rate"],
                        "consecutive_failures": health["consecutive_failures"],
                        "status": "healthy" if health["consecutive_failures"] < 3 else "unhealthy"
                    }
                else:
                    status[source] = {"status": "no_data"}
            
            return {
                "bot_status": "alive",
                "session_id": SESSION_ID,
                "sources": status,
                "timestamp": datetime.now().isoformat()
            }, 200
        else:
            return {
                "bot_status": "alive",
                "session_id": SESSION_ID,
                "monitoring": "disabled",
                "timestamp": datetime.now().isoformat()
            }, 200
    except Exception as e:
        return {"error": str(e)}, 500

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
    """Extract normalized title for deduplication"""
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
            logging.info("Bot stats initialized")
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

    try:
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
            f"• <b>Active Sources:</b> 5\n"
        )
    except Exception as e:
        logging.error(f"get_simple_stats failed: {e}")
        return "<b>⚠️ Stats temporarily unavailable</b>"

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
        logging.info(f"Slot {slot} already completed successfully")
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
        logging.info(f"Run {run_id} finished with status: {status}")
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
            titles = set(x["normalized_title"] for x in r.data)
            logging.info(f"Loaded {len(titles)} posted titles from database")
            return titles
        except Exception as e:
            logging.error(f"load_posted_titles_for_date failed: {e}")

    try:
        if os.path.exists(POSTED_TITLES_FILE):
            with open(POSTED_TITLES_FILE, "r", encoding="utf-8") as f:
                titles = set(json.load(f))
                logging.info(f"Loaded {len(titles)} posted titles from JSON")
                return titles
    except Exception as e:
        logging.error(f"Failed to load JSON fallback: {e}")
    
    return set()

def save_posted_fallback(normalized_title, date_obj):
    try:
        titles = load_posted_titles_for_date(date_obj)
        titles.add(normalized_title)
        with open(POSTED_TITLES_FILE, "w", encoding="utf-8") as f:
            json.dump(list(titles), f)
    except Exception as e:
        logging.error(f"save_posted_fallback failed: {e}")

def record_post(title, source_code, run_id, slot, posted_titles_set):
    """
    Record post in database BEFORE sending to Telegram.
    This prevents duplicate posts even if Telegram sending fails.
    """
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
        except Exception as e:
            logging.error(f"record_post to Supabase failed: {e}")
            posted_titles_set.add(key)
            return False

    posted_titles_set.add(key)
    save_posted_fallback(key, date_obj)
    return True

# =========================
# SCRAPERS (SOURCE INCLUDED)
# =========================
def validate_image_url(image_url):
    if not image_url:
        return False
    session = get_scraping_session()
    try:
        headers = {"Range": "bytes=0-511"}
        r = session.get(image_url, headers=headers, timeout=10, stream=True)
        r.raise_for_status()
        content_type = r.headers.get("content-type", "")
        return content_type.startswith("image/")
    except Exception as e:
        logging.debug(f"Image validation failed for {image_url}: {e}")
        return False
    finally:
        session.close()

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

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=3, max=10))
@monitor_source_call("ANN")
def fetch_anime_news():
    session = get_scraping_session()
    try:
        r = session.get(BASE_URL, timeout=20)
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
        
        logging.info(f"Fetched {len(out)} ANN articles")
        return out
    except Exception as e:
        logging.error(f"fetch_anime_news failed: {e}")
        return []
    finally:
        session.close()

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=3, max=10))
@monitor_source_call("ANN_DC")
def fetch_ann_dc_news():
    session = get_scraping_session()
    try:
        r = session.get(BASE_URL_ANN_DC, timeout=20)
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
        
        logging.info(f"Fetched {len(out)} ANN DC articles")
        return out
    except Exception as e:
        logging.error(f"fetch_ann_dc_news failed: {e}")
        return []
    finally:
        session.close()

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=3, max=10))
def fetch_article_details(article_url, article):
    session = get_scraping_session()
    image_url = None
    summary = "No summary available."
    video_url = None
    date_str = None

    try:
        thumb = article.find("div", class_="thumbnail lazyload")
        if thumb and thumb.get("data-src"):
            img_url = thumb["data-src"]
            image_url = f"{BASE_URL}{img_url}" if not img_url.startswith("http") else img_url

        if article_url:
            r = session.get(article_url, timeout=20)
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
    except Exception as e:
        logging.warning(f"Failed to fetch article details: {e}")
    finally:
        session.close()

    return {"image": image_url, "summary": summary, "video": video_url, "date": date_str}

def fetch_selected_articles(news_list):
    to_fetch = [x for x in news_list if x.get("article_url") and x.get("article")]
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(fetch_article_details, x["article_url"], x["article"]): x for x in to_fetch}
        for f in futures:
            x = futures[f]
            try:
                res = f.result(timeout=20)
                x["image"] = res["image"]
                x["summary"] = res["summary"]
                x["video"] = res["video"]
                x["date"] = res["date"]
            except Exception as e:
                logging.warning(f"Article fetch timeout: {e}")
                x["image"] = None
                x["summary"] = "Failed to fetch summary."
                x["video"] = None
                x["date"] = None

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=3, max=10))
@monitor_source_call("DCW")
def fetch_dc_updates():
    session = get_scraping_session()
    try:
        url = f"{BASE_URL_DC}/wiki/Special:RecentChanges"
        r = session.get(url, timeout=25)
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
        
        logging.info(f"Fetched {len(out)} DC Wiki updates")
        return out
    except Exception as e:
        logging.error(f"fetch_dc_updates failed: {e}")
        return []
    finally:
        session.close()

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=3, max=10))
@monitor_source_call("TMS")
def fetch_tms_news():
    session = get_scraping_session()
    try:
        r = session.get(BASE_URL_TMS + "/detective-conan", timeout=20)
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
        
        logging.info(f"Fetched {len(out)} TMS news items")
        return out
    except Exception as e:
        logging.error(f"fetch_tms_news failed: {e}")
        return []
    finally:
        session.close()

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=3, max=10))
@monitor_source_call("FANDOM")
def fetch_fandom_updates():
    session = get_scraping_session()
    try:
        url = f"{BASE_URL_FANDOM}/wiki/Special:RecentChanges"
        r = session.get(url, timeout=25)
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
        
        logging.info(f"Fetched {len(out)} Fandom updates")
        return out
    except Exception as e:
        logging.error(f"fetch_fandom_updates failed: {e}")
        return []
    finally:
        session.close()

# =========================
# TELEGRAM SEND (FIXED WITH RETRIES)
# =========================
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=20))
def send_telegram_photo(chat_id, photo_url, caption):
    """Send photo with fresh connection and automatic retries"""
    tg_session = get_fresh_telegram_session()
    try:
        response = tg_session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            data={"chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": "HTML"},
            timeout=30,
        )
        response.raise_for_status()
        return True
    finally:
        tg_session.close()

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=20))
def send_telegram_message(chat_id, text):
    """Send text message with fresh connection and automatic retries"""
    tg_session = get_fresh_telegram_session()
    try:
        response = tg_session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False},
            timeout=30,
        )
        response.raise_for_status()
        return True
    finally:
        tg_session.close()

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=20))
def send_message(chat_id, text):
    """Send message for /start command with retries"""
    tg_session = get_fresh_telegram_session()
    try:
        response = tg_session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=30,
        )
        response.raise_for_status()
        return True
    except Exception as e:
        logging.error(f"send_message to {chat_id} failed: {e}")
        raise
    finally:
        tg_session.close()

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
    lines += ["", "Channel : @Detective_Conan_News"]
    return "\n".join(lines)

def send_to_telegram(item, run_id, slot, posted_titles_set):
    """
    Send news to Telegram with proper deduplication and error handling.
    Records in database BEFORE sending to prevent duplicate spam.
    """
    source_code = item.get("source", "ANN")
    title = item["title"]
    key = get_normalized_key(title)
    
    # Check if already posted
    if key in posted_titles_set:
        logging.info(f"⊘ Duplicate skipped: {key[:60]}")
        return False
    
    # CRITICAL: Record in database BEFORE sending to prevent duplicates
    if not record_post(title, source_code, run_id, slot, posted_titles_set):
        logging.warning(f"⚠ Already in database: {key[:60]}")
        return False
    
    message = build_message(item)
    send_success = False
    
    # Try sending with photo first
    image_url = item.get("image")
    if image_url and validate_image_url(image_url):
        try:
            send_telegram_photo(CHAT_ID, image_url, message)
            logging.info(f"✓ Photo sent: {key[:60]}")
            send_success = True
        except Exception as e:
            logging.warning(f"⚠ Photo failed after retries, trying text-only: {str(e)[:100]}")
    
    # Fallback to text-only message
    if not send_success:
        try:
            send_telegram_message(CHAT_ID, message)
            logging.info(f"✓ Text sent: {key[:60]}")
            send_success = True
        except Exception as e:
            logging.error(f"✗ All send attempts failed: {key[:60]} - {str(e)[:100]}")
            # Note: Still recorded in DB to prevent infinite retry spam
    
    return send_success

# =========================
# SLOT RUNNER
# =========================
def run_slot(date_obj, slot, scheduled_local):
    logging.info(f"═══════════════════════════════════════")
    logging.info(f"RUN slot={slot} date={date_obj} scheduled={scheduled_local.strftime('%H:%M')} IST")
    logging.info(f"═══════════════════════════════════════")
    
    ensure_daily_row(date_obj)

    run_id = create_or_reuse_run(date_obj, slot, scheduled_local)
    if run_id is None:
        logging.info("Slot already completed, skipping")
        return

    posted_titles_set = load_posted_titles_for_date(date_obj)

    posts_sent = 0
    posts_attempted = 0
    source_counts = {"ANN": 0, "ANN_DC": 0, "DCW": 0, "TMS": 0, "FANDOM": 0}

    try:
        # Fetch from all sources with individual error handling
        logging.info("Fetching news from all sources...")
        
        ann = []
        if circuit_breaker.can_call("ANN"):
            try:
                ann = fetch_anime_news()
                circuit_breaker.record_success("ANN")
            except Exception as e:
                circuit_breaker.record_failure("ANN")
                logging.error(f"ANN fetch completely failed: {e}")
        else:
            logging.warning("ANN source circuit breaker open - skipping")
        
        ann_dc = []
        if circuit_breaker.can_call("ANN_DC"):
            try:
                ann_dc = fetch_ann_dc_news()
                circuit_breaker.record_success("ANN_DC")
            except Exception as e:
                circuit_breaker.record_failure("ANN_DC")
                logging.error(f"ANN DC fetch completely failed: {e}")
        else:
            logging.warning("ANN_DC source circuit breaker open - skipping")
        
        # Fetch article details for ANN sources
        try:
            fetch_selected_articles(ann + ann_dc)
        except Exception as e:
            logging.error(f"Article details fetch failed: {e}")
        
        dcw = []
        if circuit_breaker.can_call("DCW"):
            try:
                dcw = fetch_dc_updates()
                circuit_breaker.record_success("DCW")
            except Exception as e:
                circuit_breaker.record_failure("DCW")
                logging.error(f"DC Wiki fetch completely failed: {e}")
        else:
            logging.warning("DCW source circuit breaker open - skipping")
        
        tms = []
        if circuit_breaker.can_call("TMS"):
            try:
                tms = fetch_tms_news()
                circuit_breaker.record_success("TMS")
            except Exception as e:
                circuit_breaker.record_failure("TMS")
                logging.error(f"TMS fetch completely failed: {e}")
        else:
            logging.warning("TMS source circuit breaker open - skipping")
        
        fandom = []
        if circuit_breaker.can_call("FANDOM"):
            try:
                fandom = fetch_fandom_updates()
                circuit_breaker.record_success("FANDOM")
            except Exception as e:
                circuit_breaker.record_failure("FANDOM")
                logging.error(f"Fandom fetch completely failed: {e}")
        else:
            logging.warning("FANDOM source circuit breaker open - skipping")

        items = ann + dcw + tms + fandom + ann_dc
        logging.info(f"Total items fetched: {len(items)}")
        logging.info(f"Source breakdown: ANN={len(ann)}, ANN_DC={len(ann_dc)}, DCW={len(dcw)}, TMS={len(tms)}, FANDOM={len(fandom)}")

        # Send each item
        for item in items:
            posts_attempted += 1
            if send_to_telegram(item, run_id, slot, posted_titles_set):
                posts_sent += 1
                sc = item.get("source", "ANN")
                source_counts[sc] = source_counts.get(sc, 0) + 1
                time.sleep(1.5)  # Rate limiting between posts

        finish_run(run_id, "success", posts_sent, source_counts, None)
        logging.info(f"═══════════════════════════════════════")
        logging.info(f"✓ SLOT {slot} COMPLETED: {posts_sent}/{posts_attempted} posts sent successfully")
        logging.info(f"Source breakdown: {source_counts}")
        logging.info(f"═══════════════════════════════════════")
    except Exception as e:
        error_msg = str(e)[:200]
        finish_run(run_id, "failed", posts_sent, source_counts, error_msg)
        logging.error(f"✗ SLOT {slot} FAILED: {e}")

# =========================
# MAIN LOOP
# =========================
def scheduler_loop():
    logging.info("Scheduler loop started")
    
    while True:
        try:
            dt = now_local()
            date_obj = dt.date()

            current_slot = slot_index(dt)
            completed = completed_slots_today(date_obj)

            # Catch-up: run missing slots <= current slot
            missing = [s for s in range(0, current_slot + 1) if s not in completed]
            if missing:
                s = missing[0]
                scheduled_local = dt.replace(hour=s * 4, minute=0, second=0, microsecond=0)
                logging.info(f"Catching up on missed slot {s}")
                run_slot(date_obj, s, scheduled_local)
                continue

            # Wait for next slot
            nxt = next_slot_start(dt)
            sleep_s = max(1, int((nxt - dt).total_seconds()))
            logging.info(f"Next slot at {nxt.strftime('%H:%M IST')}, sleeping {sleep_s}s")
            time.sleep(min(sleep_s, 300))  # Wake up every 5 min to check
            
        except Exception as e:
            logging.error(f"Scheduler loop error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    logging.info("=" * 60)
    logging.info("Detective Conan News Bot Starting")
    logging.info(f"Session ID: {SESSION_ID}")
    logging.info(f"Timezone: {local_tz}")
    logging.info(f"Supabase: {'Connected' if supabase else 'Disabled'}")
    logging.info("=" * 60)
    
    initialize_bot_stats()

    if RENDER_EXTERNAL_URL:
        Thread(target=keep_alive, daemon=True).start()
        logging.info("Keep-alive thread started")

    Thread(target=scheduler_loop, daemon=True).start()
    logging.info("Scheduler thread started")

    port = int(os.environ.get("PORT", 10000))
    logging.info(f"Starting Flask server on port {port}")
    app.run(host="0.0.0.0", port=port)
