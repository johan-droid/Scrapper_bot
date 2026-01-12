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

try:
    from models import NewsItem
except ImportError:
    # Fallback for when models.py isn't found (shouldn't happen in correct setup)
    logging.warning("Could not import NewsItem from models") 

try:
    from utils import clean_text_extractor
except ImportError:
    def clean_text_extractor(element): return element.get_text(" ", strip=True) if element else ""

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
    "ANI": "Anime News India", "R_ANIME": "Reddit (r/anime)",
    "R_OTP": "Reddit (r/OneTruthPrevails)", "R_DC": "Reddit (r/DetectiveConan)",
}

# RSS Feeds
RSS_ANI = "https://animenewsindia.com/feed/"
RSS_R_ANIME = "https://www.reddit.com/r/anime/new/.rss"
RSS_R_OTP = "https://www.reddit.com/r/OneTruthPrevails/new/.rss"
RSS_R_DC = "https://www.reddit.com/r/DetectiveConan/new/.rss"

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
            # Create NewsItem immediately - validating data
            item = NewsItem(
                source="ANN",
                title=title_tag.get_text(" ", strip=True),
                article_url=f"{BASE_URL}{link['href']}" if link else None
            )
            # Find initial summary if available (ANN usually has it in 'intro')
            intro = article.find("div", class_="intro") 
            if intro:
                 item.summary = clean_text_extractor(intro) # Apply cleaning here too!

            out.append(item)
    return out

def parse_ann_dc(html):
    # Reuse ANN logic but change source tag
    items = parse_ann(html)
    for i in items: 
        i.source = "ANN_DC"
        i.title = f"ANN DC News: {i.title}"
    return items

def fetch_rss(url, source_name, parser_func):
    """
    Generic RSS fetcher. Supports both Atom (Reddit) and RSS 2.0 (WordPress).
    """
    session = get_scraping_session()
    try:
        # Reddit requires a unique User-Agent to avoid 429s even on RSS
        if "reddit.com" in url:
            session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; ScrapperBot/2.0; +http://github.com/johan-droid)"})
            
        r = session.get(url, timeout=25)
        r.raise_for_status()
        
        # 'xml' parser logic requires lxml or similar, but provides best results for RSS
        # Fallback to html.parser if xml fails or isn't perfect, but RSS is XML.
        try:
            soup = BeautifulSoup(r.content, "xml")
        except Exception:
            soup = BeautifulSoup(r.content, "html.parser") # Fallback
            
        return parser_func(soup)
    except Exception as e:
        logging.error(f"{source_name} RSS fetch failed: {e}")
        return []
    finally:
        session.close()

def parse_reddit_rss(soup):
    """Parses Reddit Atom feeds."""
    items = []
    # Atom uses <entry>
    entries = soup.find_all("entry")
    if not entries: return []

    today = now_local().date()
    yesterday = today - timedelta(days=1)
    
    for entry in entries:
        try:
            # 1. Date Check
            published = entry.find("published") or entry.find("updated")
            if published:
                # Format: 2025-01-12T15:00:00+00:00
                pub_date_str = published.text
                # Handle possible fractional seconds or timezone variations basic check
                pub_date_dt = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                pub_date = pub_date_dt.astimezone(local_tz).date()
                
                # Allow Today OR Yesterday to catch late-night news
                if not DEBUG_MODE and pub_date not in [today, yesterday]:
                    continue
            
            # 2. Extract Basic Info
            title = entry.find("title").text
            link_tag = entry.find("link")
            link = link_tag["href"] if link_tag else None
            
            # 3. Content Analysis (for Image)
            content_html = ""
            content_tag = entry.find("content")
            if content_tag:
                content_html = content_tag.text
            
            # Reddit specific: Parse the content HTML to find the thumbnail preview
            image_url = None
            if content_html:
                c_soup = BeautifulSoup(content_html, "html.parser")
                # Reddit typically puts a preview img in the content or we can use the thumbnail from media:thumbnail if present (Atom might not have media:thumbnail easily exposed without namespace parsing, but content_html usually has it)
                img = c_soup.find("img")
                if img:
                    image_url = img.get("src")
            
            # Determine Source Label based on the feed content or context passed?
            # The parser is generic, but the caller assigns source.
            # We'll return generic objects and let caller/wrapper assign precise source code if needed.
            # actually, passed source in NewsItem is best.
            
            # Wait, this function doesn't know which subreddit it is unless we pass it or infer it.
            # Infer from author or link?
            source_code = "REDDIT" # Placeholder
            if "r/anime" in link: source_code = "R_ANIME"
            elif "r/OneTruthPrevails" in link: source_code = "R_OTP"
            elif "r/DetectiveConan" in link: source_code = "R_DC"

            item = NewsItem(
                title=title,
                source=source_code,
                article_url=link,
                image=image_url
            )
            item.summary = "Reddit Discussion" # Default
            items.append(item)
            
        except Exception as e:
            logging.error(f"Error parsing reddit item: {e}")
            continue
            
    return items

def parse_ani_rss(soup):
    """Parses Anime News India RSS 2.0 feed."""
    items = []
    # RSS 2.0 uses <item>
    entries = soup.find_all("item")
    if not entries: return []

    today = now_local().date()
    yesterday = today - timedelta(days=1)

    for entry in entries:
        try:
            # 1. Date Check
            pub_date_tag = entry.find("pubDate")
            if pub_date_tag:
                # Format: Sun, 12 Jan 2025 10:00:00 +0000
                # Using dateutil or manually parsing would be robust. 
                # Be simplest: try standard format
                try:
                    dt = datetime.strptime(pub_date_tag.text.strip(), "%a, %d %b %Y %H:%M:%S %z")
                    pub_date = dt.astimezone(local_tz).date()
                    if not DEBUG_MODE and pub_date not in [today, yesterday]:
                        continue
                except:
                    pass # If date parsing fails, maybe process it anyway or skip? Safer to skip or log.

            title = entry.find("title").text
            link = entry.find("link").text
            
            # 2. Image Extraction
            image_url = None
            # Check content:encoded first (full content)
            content_encoded = entry.find("content:encoded")
            description = entry.find("description")
            
            html_to_check = ""
            if content_encoded: html_to_check = content_encoded.text
            elif description: html_to_check = description.text
            
            if html_to_check:
                c_soup = BeautifulSoup(html_to_check, "html.parser")
                img = c_soup.find("img")
                if img: image_url = img.get("src")
            
            # 3. Summary
            summary_text = ""
            if description:
                summary_text = clean_text_extractor(BeautifulSoup(description.text, "html.parser"))
                if len(summary_text) > 300: summary_text = summary_text[:300] + "..."
            
            item = NewsItem(
                title=title,
                source="ANI",
                article_url=link,
                image=image_url,
                summary=summary_text if summary_text else "Read more on Anime News India."
            )
            items.append(item)

        except Exception as e:
            logging.error(f"Error parsing ANI item: {e}")
            continue

    return items

def fetch_details_concurrently(items):
    def get_details(item: NewsItem):
        if not item.article_url: return item
        session = get_scraping_session()
        try:
            r = session.get(item.article_url, timeout=15)
            s = BeautifulSoup(r.text, "html.parser")
            
            # 1. Try text content/meat div first
            content_img = None
            content_div = s.find("div", class_="meat") or s.find("div", class_="content")
            if content_div:
                for img in content_div.find_all("img"):
                    src = img.get("src") or img.get("data-src")
                    if src and "spacer" not in src and "pixel" not in src and not src.endswith(".gif"):
                        if "facebook" in src or "twitter" in src: continue
                        full_src = f"{BASE_URL}{src}" if not src.startswith("http") else src
                        item.image = full_src
                        break
            
            # 2. OpenGraph Backup
            if not item.image:
                og_img = s.find("meta", property="og:image")
                if og_img and og_img.get("content"):
                    item.image = og_img["content"]
            
            # 3. Fallback to thumbnail
            if not item.image:
                thumb = s.find("div", class_="thumbnail lazyload")
                if thumb and thumb.get("data-src"): 
                    src = thumb['data-src']
                    item.image = f"{BASE_URL}{src}" if not src.startswith("http") else src

            # Summary extraction
            div = s.find("div", class_="meat") or s.find("div", class_="content")
            if div:
                # Use centralized utility for consistent cleaning
                txt = clean_text_extractor(div)
                item.summary = txt[:350] + "..." if len(txt) > 350 else txt
        except Exception as e:
            logging.error(f"Details fetch failed for {item.article_url}: {e}")
        finally: session.close()
        return item

    with ThreadPoolExecutor(max_workers=5) as ex:
        ex.map(get_details, items)
    # --- 8. TELEGRAM SENDER ---
def format_message(item: NewsItem):
    source_map = {
        "ANN": "Anime News Network", "ANN_DC": "ANN (Detective Conan)",
        "DCW": "Detective Conan Wiki", "TMS": "TMS Entertainment", "FANDOM": "Fandom Wiki"
    }
    source_name = source_map.get(item.source, item.source)
    
    title = escape_html(item.title)
    summary = escape_html(item.summary)
    link = item.article_url or ""
    
    # Cleaner Template
    msg = (
        f"<b>{title}</b>\n\n"
        f"{summary}\n\n"
        f"<b>Source:</b> {source_name}\n"
        f"<b>📢 Channel:</b> @Detective_Conan_News\n"
        f"🔗 <a href='{link}'>Read Full Article</a>"
    )
    return msg

def send_to_telegram(item: NewsItem, run_id, slot, posted_set):
    title = item.title
    if get_normalized_key(title) in posted_set: return False

    if not record_post(title, item.source, run_id, slot, posted_set):
        return False

    msg = format_message(item)
    
    sess = get_fresh_telegram_session()
    sent = False
    try:
        if item.image and validate_image_url(item.image):
            sess.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", 
                      data={"chat_id": CHAT_ID, "photo": item.image, "caption": msg, "parse_mode": "HTML"}, timeout=20)
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
        all_items.extend(ann_dc_items)

    # Anime News India
    if circuit_breaker.can_call("ANI"):
        ani_items = fetch_rss(RSS_ANI, "ANI", parse_ani_rss)
        all_items.extend(ani_items)

    # Reddit Scrapers (RSS)
    # r/anime
    if circuit_breaker.can_call("R_ANIME"):
        r_anime = fetch_rss(RSS_R_ANIME, "R_ANIME", parse_reddit_rss)
        all_items.extend(r_anime)
        
    # r/OneTruthPrevails
    if circuit_breaker.can_call("R_OTP"):
        r_otp = fetch_rss(RSS_R_OTP, "R_OTP", parse_reddit_rss)
        all_items.extend(r_otp)
        
    # r/DetectiveConan
    if circuit_breaker.can_call("R_DC"):
        r_dc = fetch_rss(RSS_R_DC, "R_DC", parse_reddit_rss)
        all_items.extend(r_dc)

    # (Add other sources DCW, TMS, FANDOM following similar pattern...)

    # 3. Enrich Data
    logging.info(f"Fetching details for {len(all_items)} items...")
    fetch_details_concurrently(all_items)

    # 4. Post
    sent_count = 0
    source_counts = defaultdict(int)
    
    for item in all_items:
        # Check if item is valid (Pydantic models are always valid if created, but check empty fields)
        if not item.title: continue
        
        if send_to_telegram(item, run_id, slot, posted_set):
            sent_count += 1
            source_counts[item.source] += 1
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
