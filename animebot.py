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
from concurrent.futures import ThreadPoolExecutor
from tenacity import retry, stop_after_attempt, wait_exponential
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
from collections import defaultdict

# --- 1. SETUP & CONFIGURATION ---
try:
    from source_monitor import health_monitor, monitor_source_call
except ImportError:
    health_monitor = None
    def monitor_source_call(source_name):
        def decorator(func): return func
        return decorator

try:
    from supabase import create_client
except Exception as e:
    logging.warning(f"Supabase import failed: {e}")
    create_client = None

# Load env vars (useful for local testing, ignored in GHA if secrets are mapped)
env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path, override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()], # Only stream to console for GHA logs
    force=True,
)

SESSION_ID = str(uuid.uuid4())[:8]

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ADMIN_ID = os.getenv("ADMIN_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
# Circuit breaker (In-memory for single run duration)
class SourceCircuitBreaker:
    def __init__(self, failure_threshold=3, recovery_timeout=300):
        self.failure_counts = defaultdict(int)
        self.failure_threshold = failure_threshold
    
    def can_call(self, source):
        return self.failure_counts[source] < self.failure_threshold
    
    def record_success(self, source):
        self.failure_counts[source] = 0
    
    def record_failure(self, source):
        self.failure_counts[source] += 1

circuit_breaker = SourceCircuitBreaker()

BASE_URL = "https://www.animenewsnetwork.com"
BASE_URL_DC = "https://www.detectiveconanworld.com"
BASE_URL_TMS = "https://tmsanime.com"
BASE_URL_FANDOM = "https://detectiveconan.fandom.com"
BASE_URL_ANN_DC = "https://www.animenewsnetwork.com/encyclopedia/anime.php?id=454&tab=news"
DEBUG_MODE = False
SOURCE_LABEL = {
    "ANN": "Anime News Network", "ANN_DC": "ANN (Detective Conan)",
    "DCW": "Detective Conan Wiki", "TMS": "TMS Entertainment", "FANDOM": "Fandom Wiki",
}

if not BOT_TOKEN or not CHAT_ID:
    logging.error("CRITICAL: BOT_TOKEN or CHAT_ID is missing.")
    raise SystemExit(1)

utc_tz = pytz.utc
local_tz = pytz.timezone("Asia/Kolkata")

# --- 2. DATABASE CONNECTION (ROBUST) ---
supabase = None
if SUPABASE_URL and SUPABASE_KEY and create_client:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logging.info("Supabase connected successfully")
    except Exception as e:
        logging.error(f"Supabase init failed: {e}")
        # In GHA, if we expect DB but fail, we MUST exit to avoid spamming duplicates
        raise SystemExit("CRITICAL: Supabase configured but connection failed. Aborting to prevent spam.")
elif SUPABASE_URL and not create_client:
    raise SystemExit("CRITICAL: Supabase URL found but 'supabase' library missing.")
else:
    logging.warning("⚠️ Running WITHOUT database. Duplicates will occur if runs restart.")

# --- 3. SESSION HELPERS ---
def get_scraping_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=3, backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504, 104],
        allowed_methods=["GET", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Connection": "close",
    })
    return session

def get_fresh_telegram_session():
    tg_session = requests.Session()
    retry_strategy = Retry(
        total=3, backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    tg_session.mount("https://", adapter)
    tg_session.headers.update({"Connection": "close"})
    return tg_session

# --- 4. TIME HELPERS ---
def now_local(): return datetime.now(local_tz)
def slot_index(dt_local): return dt_local.hour // 4
def slot_start_for(dt_local):
    h = (dt_local.hour // 4) * 4
    return dt_local.replace(hour=h, minute=0, second=0, microsecond=0)

# --- 5. TEXT & VALIDATION HELPERS ---
def escape_html(text):
    if not text or not isinstance(text, str): return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def get_normalized_key(title):
    prefixes = ["DC Wiki Update: ", "TMS News: ", "Fandom Wiki Update: ", "ANN DC News: "]
    for p in prefixes:
        if title.startswith(p): return title[len(p):].strip()
    return title.strip()

def validate_image_url(image_url):
    if not image_url: return False
    session = get_scraping_session()
    try:
        headers = {"Range": "bytes=0-511"}
        r = session.get(image_url, headers=headers, timeout=10, stream=True)
        r.raise_for_status()
        return r.headers.get("content-type", "").startswith("image/")
    except Exception:
        return False
    finally:
        session.close()

# --- 6. DATABASE LOGIC ---
def initialize_bot_stats():
    if not supabase: return
    try:
        resp = supabase.table("bot_stats").select("*").limit(1).execute()
        if not resp.data:
            now = datetime.now(utc_tz).isoformat()
            supabase.table("bot_stats").insert({"bot_started_at": now, "total_posts_all_time": 0}).execute()
    except Exception: pass

def ensure_daily_row(date_obj):
    if not supabase: return
    try:
        r = supabase.table("daily_stats").select("date").eq("date", str(date_obj)).limit(1).execute()
        if not r.data:
            supabase.table("daily_stats").insert({"date": str(date_obj), "posts_count": 0}).execute()
    except Exception: pass

def increment_post_counters(date_obj):
    if not supabase: return
    try:
        ensure_daily_row(date_obj)
        # Optimized: In a real scenario, use an RPC call here to save requests.
        # For now, keeping original logic but wrapped safely.
        d = supabase.table("daily_stats").select("posts_count").eq("date", str(date_obj)).limit(1).execute()
        cur = int(d.data[0].get("posts_count", 0)) if d.data else 0
        supabase.table("daily_stats").update({"posts_count": cur + 1}).eq("date", str(date_obj)).execute()
        
        b = supabase.table("bot_stats").select("*").limit(1).execute()
        if b.data:
            total = int(b.data[0].get("total_posts_all_time", 0))
            supabase.table("bot_stats").update({"total_posts_all_time": total + 1}).eq("id", b.data[0]["id"]).execute()
    except Exception as e:
        logging.error(f"Stats update failed: {e}")

def create_or_reuse_run(date_obj, slot, scheduled_local):
    if not supabase: return f"local-{slot}" # Fallback for local testing only
    
    scheduled_utc = scheduled_local.astimezone(utc_tz).isoformat()
    now_utc = datetime.now(utc_tz).isoformat()

    try:
        r = supabase.table("runs").select("id,status").eq("date", str(date_obj)).eq("slot", slot).limit(1).execute()
        if r.data and r.data[0].get("status") == "success":
            return None # Slot already done

        payload = {"date": str(date_obj), "slot": slot, "scheduled_at": scheduled_utc, "started_at": now_utc, "status": "started"}
        resp = supabase.table("runs").upsert(payload, on_conflict="date,slot").execute()
        return resp.data[0]["id"] if resp.data else None
    except Exception as e:
        logging.error(f"Run tracking failed: {e}")
        return None

def finish_run(run_id, status, posts_sent, source_counts, error=None):
    if not supabase or not run_id or str(run_id).startswith("local"): return
    try:
        supabase.table("runs").update({
            "status": status, "posts_sent": posts_sent, "source_counts": source_counts,
            "finished_at": datetime.now(utc_tz).isoformat(), "error": error
        }).eq("id", run_id).execute()
    except Exception: pass

def load_posted_titles(date_obj):
    if not supabase: return set()
    try:
        r = supabase.table("posted_news").select("normalized_title").eq("posted_date", str(date_obj)).execute()
        return set(x["normalized_title"] for x in r.data)
    except Exception as e:
        logging.error(f"Failed to load posted titles: {e}")
        return set()

def record_post(title, source_code, run_id, slot, posted_titles_set):
    key = get_normalized_key(title)
    if key in posted_titles_set: return False
    
    date_obj = now_local().date()
    if supabase:
        try:
            supabase.table("posted_news").insert({
                "normalized_title": key, "posted_date": str(date_obj), "full_title": title,
                "posted_at": datetime.now(utc_tz).isoformat(), "source": source_code,
                "run_id": run_id if not str(run_id).startswith("local") else None, "slot": slot
            }).execute()
            posted_titles_set.add(key)
            increment_post_counters(date_obj)
            return True
        except Exception:
            return False
    # --- 7. SCRAPERS (CONDENSED) ---
# (Scraper functions remain largely the same, just ensuring they use the session helper)
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=3, max=10))
def fetch_generic(url, source_name, parser_func):
    session = get_scraping_session()
    try:
        r = session.get(url, timeout=20)
        r.raise_for_status()
        return parser_func(r.text)
    except Exception as e:
        logging.error(f"{source_name} fetch failed: {e}")
        return []
    finally:
        session.close()

def parse_ann(html):
    soup = BeautifulSoup(html, "html.parser")
    today = now_local().date()
    out = []
    for article in soup.find_all("div", class_="herald box news t-news"):
        title_tag, date_tag = article.find("h3"), article.find("time")
        if not title_tag or not date_tag: continue
        try:
            news_date = datetime.fromisoformat(date_tag.get("datetime", "")).astimezone(local_tz).date()
        except: continue
        if DEBUG_MODE or news_date == today:
            link = title_tag.find("a")
            out.append({"source": "ANN", "title": title_tag.get_text(" ", strip=True), 
                        "article_url": f"{BASE_URL}{link['href']}" if link else None, "article": article})
    return out

def parse_ann_dc(html):
    # Reuse ANN logic but change source tag
    items = parse_ann(html)
    for i in items: 
        i["source"] = "ANN_DC"
        i["title"] = f"ANN DC News: {i['title']}"
    return items

def fetch_details_concurrently(items):
    def get_details(item):
        if not item.get("article_url"): return item
        session = get_scraping_session()
        try:
            r = session.get(item["article_url"], timeout=15)
            s = BeautifulSoup(r.text, "html.parser")
            
            # 1. Try text content/meat div first (More specific to the article)
            content_img = None
            content_div = s.find("div", class_="meat") or s.find("div", class_="content")
            if content_div:
                for img in content_div.find_all("img"):
                    src = img.get("src") or img.get("data-src")
                    # Filter out spacers, tracking pixels, and tiny icons
                    if src and "spacer" not in src and "pixel" not in src and not src.endswith(".gif"):
                        # Skip known generic/footer images if needed
                        if "facebook" in src or "twitter" in src: continue
                        
                        full_src = f"{BASE_URL}{src}" if not src.startswith("http") else src
                        content_img = full_src
                        item["image"] = content_img
                        break
            
            # 2. If no content image, try OpenGraph (Backup)
            if not item.get("image"):
                og_img = s.find("meta", property="og:image")
                if og_img and og_img.get("content"):
                    item["image"] = og_img["content"]
            
            # 3. Fallback to thumbnail
            if not item.get("image"):
                thumb = s.find("div", class_="thumbnail lazyload")
                if thumb and thumb.get("data-src"): 
                    src = thumb['data-src']
                    item["image"] = f"{BASE_URL}{src}" if not src.startswith("http") else src

            # Summary extraction
            div = s.find("div", class_="meat") or s.find("div", class_="content")
            if div:
                txt = div.get_text(" ", strip=True)
                item["summary"] = txt[:350] + "..." if len(txt) > 350 else txt
        except: pass
        finally: session.close()
        return item

    with ThreadPoolExecutor(max_workers=5) as ex:
        ex.map(get_details, items)
    # --- 8. TELEGRAM SENDER ---
def format_message(item):
    source_map = {
        "ANN": "Anime News Network", "ANN_DC": "ANN (Detective Conan)",
        "DCW": "Detective Conan Wiki", "TMS": "TMS Entertainment", "FANDOM": "Fandom Wiki"
    }
    source_name = source_map.get(item.get("source"), item.get("source", "News"))
    
    title = escape_html(item["title"])
    summary = escape_html(item.get("summary", ""))
    link = item.get("article_url", "")
    
    # Cleaner Template
    msg = (
        f"<b>{title}</b>\n\n"
        f"{summary}\n\n"
        f"<b>Source:</b> {source_name}\n"
        f"🔗 <a href='{link}'>Read Full Article</a>"
    )
    return msg

def send_to_telegram(item, run_id, slot, posted_set):
    title = item["title"]
    if get_normalized_key(title) in posted_set: return False

    if not record_post(title, item.get("source"), run_id, slot, posted_set):
        return False

    msg = format_message(item)
    
    sess = get_fresh_telegram_session()
    sent = False
    try:
        if item.get("image") and validate_image_url(item["image"]):
            sess.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", 
                      data={"chat_id": CHAT_ID, "photo": item["image"], "caption": msg, "parse_mode": "HTML"}, timeout=20)
            sent = True
        else:
            sess.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", 
                      json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=20)
            sent = True
    except Exception as e:
        logging.error(f"Telegram send failed: {e}")
    finally:
        sess.close()
    return sent

# --- 9. MAIN EXECUTION (ACTION MODE) ---
def run_once():
    """Single execution entry point for GitHub Actions"""
    dt = now_local()
    date_obj = dt.date()
    slot = slot_index(dt)
    
    logging.info(f"STARTING RUN: Date={date_obj} Slot={slot} (IST)")
    
    # 1. Initialize
    initialize_bot_stats()
    run_id = create_or_reuse_run(date_obj, slot, slot_start_for(dt))
    
    if run_id is None:
        logging.info("✅ Slot already completed successfully. Exiting.")
        return

    # 2. Fetch Data
    posted_set = load_posted_titles(date_obj)
    all_items = []
    
    # ANN
    if circuit_breaker.can_call("ANN"):
        ann_items = fetch_generic(BASE_URL, "ANN", parse_ann)
        all_items.extend(ann_items)
    
    # ANN DC
    if circuit_breaker.can_call("ANN_DC"):
        ann_dc_items = fetch_generic(BASE_URL_ANN_DC, "ANN_DC", parse_ann_dc)
        all_items.extend(ann_dc_items)

    # (Add other sources DCW, TMS, FANDOM following similar pattern...)

    # 3. Enrich Data
    logging.info(f"Fetching details for {len(all_items)} items...")
    fetch_details_concurrently(all_items)

    # 4. Post
    sent_count = 0
    source_counts = defaultdict(int)
    
    for item in all_items:
        if send_to_telegram(item, run_id, slot, posted_set):
            sent_count += 1
            source_counts[item.get("source")] += 1
            time.sleep(1.0) # Rate limit protection

    # 5. Finish
    finish_run(run_id, "success", sent_count, source_counts)
    logging.info(f"RUN COMPLETE. Sent: {sent_count}")

if __name__ == "__main__":
    try:
        run_once()
    except Exception as e:
        logging.error(f"FATAL ERROR: {e}")
        exit(1)
