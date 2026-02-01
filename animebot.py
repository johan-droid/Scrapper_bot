import os
import re
import json
import html
import time
import uuid
import pytz
import random
import logging
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
from collections import defaultdict
from typing import Optional, List, Dict, Any
import difflib


class NewsItem:
    """Represents a news item with metadata from various sources."""
    def __init__(
        self,
        title: str,
        source: str,
        article_url: str,
        summary_text: Optional[str] = None,
        image_url: Optional[str] = None,
        publish_date: Optional[datetime] = None,
        tags: Optional[List[str]] = None,
        author: Optional[str] = None,
        category: Optional[str] = None,  # <--- Added parameter
        **kwargs: Any
    ):
        self.title = title
        self.source = source
        self.article_url = article_url
        self.summary_text = summary_text
        self.image_url = image_url
        self.publish_date = publish_date
        self.tags = tags or []
        self.author = author
        self.category = category  # <--- Added initialization
        
        # Store any additional fields that might be passed in
        for key, value in kwargs.items():
            setattr(self, key, value)

# --- 1. SETUP & CONFIGURATION ---
try:
    from source_monitor import health_monitor, monitor_source_call
except ImportError:
    health_monitor = None
    def monitor_source_call(source_name):
        def decorator(func): return func
        return decorator

# Standard Supabase Import (Assumes >= 2.0.0)
try:
    from supabase import create_client, Client
except ImportError:
    logging.warning("Supabase library not found. Running in memory-only mode.")
    create_client = None
    Client = None

# --- ROBUST TEXT CLEANER ---
# --- ROBUST TEXT CLEANER ---
def clean_text_extractor(html_text_or_element, limit=350):
    """
    Robustly cleans HTML content and removes junk data.
    """
    if not html_text_or_element: return "No summary available."

    # Convert BS4 element to string if needed
    if hasattr(html_text_or_element, "get_text"):
        # We need the tag structure to decompose specific tags
        soup = html_text_or_element
    else:
        # Check if it looks like HTML, otherwise just return text
        raw_str = str(html_text_or_element)
        if "<" in raw_str and ">" in raw_str:
             soup = BeautifulSoup(raw_str, "html.parser")
        else:
             return raw_str[:limit]

    # Remove script and style tags entirely
    for script in soup(["script", "style", "header", "footer", "a"]): # Remove links from summary entirely
        script.decompose()
        
    text = soup.get_text(separator=" ")
    
    # Remove URL-like strings and extra whitespace
    text = re.sub(r'http\S+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Fix common encoding artifacts
    text = text.replace('â€™', "'").replace('â€"', "—").replace('&nbsp;', ' ')
    
    if len(text) > limit:
        return text[:limit-3].strip() + "..."
    return text

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
# REDDIT_CHANNEL_ID removed
WORLD_NEWS_CHANNEL_ID = os.getenv("WORLD_NEWS_CHANNEL_ID")
ANIME_NEWS_CHANNEL_ID = os.getenv("ANIME_NEWS_CHANNEL_ID")
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
    "ANI": "Anime News India",
    # Reddit sources removed
    "MAL": "MyAnimeList (Jikan)", "CR": "Crunchyroll News",
    "AC": "Anime Corner", "HONEY": "Honey's Anime",
    "AP": "AP News (Entertainment)",
    "REUTERS": "Reuters (Lifestyle)",
    # Merged World News
    "BBC": "BBC World News", "ALJ": "Al Jazeera", "CNN": "CNN World", "GUARD": "The Guardian",
    "NPR": "NPR International", "DW": "Deutsche Welle", "F24": "France 24", "CBC": "CBC World",
    # Merged General News
    "NL": "NewsLaundry", "WIRE": "The Wire", "CARAVAN": "Caravan Magazine", "SCROLL": "Scroll.in",
    "PRINT": "The Print", "INTER": "The Intercept", "PRO": "ProPublica"
}

# RSS Feeds Dictionary for generic loop
RSS_FEEDS = {
    # Anime
    "ANI": "https://animenewsindia.com/feed/",
    "CR": "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss",
    "AC": "https://animecorner.me/feed/",
    "HONEY": "https://honeysanime.com/feed/",
    # World
    "BBC": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "ALJ": "https://www.aljazeera.com/xml/rss/all.xml",
    "CNN": "http://rss.cnn.com/rss/edition_world.rss",
    "GUARD": "https://www.theguardian.com/world/rss",
    "NPR": "https://feeds.npr.org/1001/rss.xml",
    "DW": "https://www.dw.com/en/rss/rss-en-all",
    "F24": "https://www.france24.com/en/rss",
    "CBC": "https://www.cbc.ca/cmlink/rss-world",
    # General
    "NL": "https://www.newslaundry.com/feed",
    "WIRE": "https://thewire.in/feed",
    "CARAVAN": "https://caravanmagazine.in/feed",
    "SCROLL": "https://scroll.in/feed",
    "PRINT": "https://theprint.in/feed",
    "INTER": "https://theintercept.com/feed/?lang=en",
    "PRO": "https://www.propublica.org/feeds/propublica/main",
}

# Source Categories for Routing (Optional, can be used for channel mapping)
# We can map these to specific channel tags or IDs if needed.

JIKAN_BASE = "https://api.jikan.moe/v4"
BASE_URL_AP_NEWS = "https://apnews.com/hub/entertainment" # Targeting entertainment/pop culture or general top news
# Using Google News RSS bridge for Reuters to avoid paywall/anti-bot issues
RSS_REUTERS = "https://news.google.com/rss/search?q=when:24h+source:Reuters&hl=en-US&gl=US&ceid=US:en"

# Channel routing configuration
# REDDIT_SOURCES set removed
DC_NEWS_SOURCES = {"ANN_DC", "DCW", "TMS", "FANDOM"}
ANIME_NEWS_SOURCES = {"ANN", "ANI", "MAL", "CR", "AC", "HONEY"}
WORLD_NEWS_SOURCES = {"AP", "REUTERS"}
ALL_NEWS_SOURCES = DC_NEWS_SOURCES | ANIME_NEWS_SOURCES | WORLD_NEWS_SOURCES

if not BOT_TOKEN:
    logging.error("CRITICAL: BOT_TOKEN is missing.")
    raise SystemExit(1)

if not CHAT_ID:
    logging.warning("CHAT_ID is missing. Default channel fallbacks must be set.")
    # If using specific channels, this might be intentional.
    if not ANIME_NEWS_CHANNEL_ID:
         logging.warning("WARNING: Neither CHAT_ID nor ANIME_NEWS_CHANNEL_ID is set!")

# REDDIT_CHANNEL_ID check removed
if not ANIME_NEWS_CHANNEL_ID:
    logging.warning("ANIME_NEWS_CHANNEL_ID not set - Anime posts will go to main channel")
if not WORLD_NEWS_CHANNEL_ID:
    logging.warning("WORLD_NEWS_CHANNEL_ID not set - World News posts will go to main channel")

utc_tz = pytz.utc
local_tz = pytz.timezone("Asia/Kolkata")

# --- 2. DATABASE CONNECTION (ROBUST) ---
supabase = None
if SUPABASE_URL and SUPABASE_KEY and create_client:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logging.info("Supabase connected successfully")
    except Exception as e:
        logging.warning(f"Supabase connection failed: {e}")
        logging.warning("WARNING: Running WITHOUT database. Duplicates may occur.")
        supabase = None
elif SUPABASE_URL and not create_client:
    logging.warning("CRITICAL: Supabase URL found but 'supabase' library missing.")
else:
    logging.warning("WARNING: Running WITHOUT database. Duplicates will occur if runs restart.")

# --- 3. SESSION HELPERS ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/121.0"
]

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
    
    # Rotate User-Agent
    ua = random.choice(USER_AGENTS)
    session.headers.update({
        "User-Agent": ua,
        "Connection": "close",
    })
    return session

def decode_google_news_url(source_url):
    """
    Google News RSS encodes the original link. 
    This helper extracts the direct Reuters link or returns the original if extraction fails.
    """
    try:
        if "news.google.com" in source_url:
            # Resolve the redirect to get the actual clean URL
            # We use a session with a proper User-Agent to ensure Google responds correctly
            with requests.Session() as s:
                s.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
                })
                # Check headers only first (Head) or minimal content
                r = s.head(source_url, allow_redirects=True, timeout=5)
                if r.status_code == 200:
                    return r.url
                # If HEAD fails (sometimes disallowed), try GET with stream
                r = s.get(source_url, allow_redirects=True, timeout=5, stream=True)
                if r.status_code == 200:
                    return r.url
    except Exception:
        # If resolution fails (timeout, error), return original. 
        # Telegram client usually handles the redirect fine anyway.
        pass
    return source_url

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
def normalize_title(title):
    """Normalize title for fuzzy matching: lowercase, strip punctuation/emojis/prefixes."""
    # Remove common prefixes
    prefixes = ["BREAKING:", "NEW:", "UPDATE:", "DC Wiki Update: ", "TMS News: ", "Fandom Wiki Update: ", "ANN DC News: "]
    t = title
    for p in prefixes:
        if t.upper().startswith(p.upper()):
            t = t[len(p):].strip()
    
    # Remove non-alphanumeric (keep spaces)
    t = re.sub(r'[^\w\s]', '', t)
    return t.lower().strip()

def is_duplicate(title, url, posted_titles_set):
    """
    Aggressive deduplication:
    1. Exact URL check (if we had a URL store, but here we rely on title mostly).
    2. Normalized Title fuzzy match > 70%.
    """
    # Quick exact check in local set
    norm_title = normalize_title(title)
    if norm_title in posted_titles_set:
        return True
    
    # Fuzzy check against local set (for this batch)
    # We only check if the set is small enough to be performant, otherwise rely on DB
    for existing in posted_titles_set:
        ratio = difflib.SequenceMatcher(None, norm_title, existing).ratio()
        if ratio > 0.7:
            return True
            
    # DB Check (if supabase is available)
    if supabase:
        try:
            # We fetch similar titles from the last 3 days to avoid full table scan if large
            # But 'ilike' is expensive. Optimally we trust the 'posted_titles_set' which we load for the day.
            # However, user requested DB check.
            # Let's trust 'load_posted_titles' which loads TODAY's titles.
            # For "permanent history" check, we might need a specific query.
            # Implementation: we will rely on LOAD_POSTED_TITLES being populated with RECENT history.
            pass 
        except Exception:
            pass
            
    return False

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
    """Calls server-side functions to increment counters safely."""
    if not supabase: return
    try:
        supabase.rpc('increment_daily_stats', {'row_date': str(date_obj)}).execute()
        supabase.rpc('increment_bot_stats').execute()
    except Exception as e:
        logging.error(f"Atomic stats update failed: {e}")

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
        # Load last 3 days to ensure we don't repost recent news even if day changes
        # User wanted "Permanent posted_news table with no TTL" and "Aggressive dedupe".
        # We can't load the WHOLE table into memory.
        # We'll load last 7 days for safety.
        past_date = str(date_obj - timedelta(days=7))
        r = supabase.table("posted_news").select("normalized_title, full_title").gte("posted_date", past_date).execute()
        
        titles = set()
        for x in r.data:
            # Add both the raw normalized key and a freshly normalized version of full_title just in case
            if "normalized_title" in x: titles.add(x["normalized_title"].lower())
            if "full_title" in x: titles.add(normalize_title(x["full_title"]))
            
        return titles
    except Exception as e:
        logging.error(f"Failed to load posted titles: {e}")
        return set()

def record_post(title, source_code, run_id, slot, posted_titles_set, category=None, status='sent'):
    # Normalize with our new robust function
    key = normalize_title(title)
    
    # We might have checked is_duplicate before, but let's double check key logic
    if key in posted_titles_set and status == 'sent': 
        # Only stricter check if we are confirming a send. 
        # If 'attempted', we might be re-recording, so we allow update?
        # Simpler: just insert.
        pass

    date_obj = now_local().date()
    if supabase:
        try:
            payload = {
                "normalized_title": key, "posted_date": str(date_obj), "full_title": title,
                "posted_at": datetime.now(utc_tz).isoformat(), "source": source_code,
                "run_id": run_id if not str(run_id).startswith("local") else None, "slot": slot,
                "category": category,
                "status": status
            }
            supabase.table("posted_news").insert(payload).execute()
            
            if status == 'sent':
                posted_titles_set.add(key)
                increment_post_counters(date_obj)
            return True
        except Exception as e:
            logging.warning(f"DB Record failed: {e}")
            return False
            
def update_post_status(title, status):
    """Updates the status of a post (e.g. attempted -> sent)."""
    if not supabase: return
    try:
         key = normalize_title(title)
         # Update the most recent entry for this title
         # This is a bit loose, ideally we'd use the record ID returned from insert.
         # But for now, updating by normalized_title + date is reasonable.
         date_obj = str(now_local().date())
         supabase.table("posted_news").update({"status": status}).eq("normalized_title", key).eq("posted_date", date_obj).execute()
    except Exception as e:
         logging.warning(f"Failed to update status for {title}: {e}")

    # --- 7. SCRAPERS (CONDENSED) ---
# (Scraper functions remain largely the same, just ensuring they use the session helper)
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=3, max=10))
def fetch_generic(url, source_name, parser_func):
    session = get_scraping_session()
    try:
        # Added explicit stream=False for small RSS/HTML pages to ensure complete loads
        # Timeout tuple: (connect_timeout, read_timeout)
        r = session.get(url, timeout=(5, 20), stream=False) 
        r.raise_for_status()
        return parser_func(r.text)
    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP {e.response.status_code} from {source_name}: {url}")
        return []
    except Exception as e:
        logging.error(f"{source_name} critical failure: {str(e)}")
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
                 item.summary_text = clean_text_extractor(intro) # Apply cleaning here too!

            out.append(item)
    return out

def parse_ann_dc(html):
    # Reuse ANN logic but change source tag
    items = parse_ann(html)
    for i in items: 
        i.source = "ANN_DC"
        i.title = f"ANN DC News: {i.title}"
    return items

def parse_ap_html(html):
    """
    Parses AP News HTML since standard RSS is often deprecated or limited.
    Targets article cards on standard AP Hub pages.
    """
    soup = BeautifulSoup(html, "html.parser")
    items = []
    
    # AP News uses <div class="PageList-items-item"> for article cards
    # or <div class="PagePromo"> depending on the layout.
    # We target common container identifiers.
    
    # Strategy 1: PagePromo (Standard for Hubs)
    cards = soup.find_all("div", class_="PagePromo")
    
    today = now_local().date()
    # If standard cards aren't found, try fallback
    if not cards:
         cards = soup.select("div.PageList-items-item")
         
    for card in cards:
        try:
            content = card.find("div", class_="PagePromo-content")
            if not content: content = card # Fallback
            
            title_tag = content.find("h3", class_="PagePromo-title")
            if not title_tag: continue
            
            link_tag = title_tag.find("a")
            if not link_tag: continue
            
            title = title_tag.get_text(" ", strip=True)
            link = link_tag.get("href")
            if link and not link.startswith("http"):
                link = f"https://apnews.com{link}"
                
            # Date checking is hard on AP hub pages (often hidden or relative)
            # We rely on deduplication database to avoid old news.
            
            # Image Isolation
            img_url = None
            media = card.find("div", class_="PagePromo-media")
            if media:
                img = media.find("img")
                if img:
                    img_url = img.get("src")
            
            # Summary
            summary_tag = content.find("div", class_="PagePromo-description")
            summary = clean_text_extractor(summary_tag) if summary_tag else ""

            item = NewsItem(
                title=title,
                source="AP",
                article_url=link,
                image_url=img_url,
                summary_text=summary
            )
            items.append(item)
            
        except Exception as e:
            continue
            
    return items

# --- ROBUST RSS PARSING ---
def parse_rss_robust(soup, source_code):
    """
    Parses generic RSS/Atom feeds with support for multiple namespaces.
    Replaces specialized parsers for maximum flexibility.
    """
    items = []
    # Support both RSS <item> and Atom <entry>
    entries = soup.find_all(['item', 'entry'])
    
    today = now_local().date()
    yesterday = today - timedelta(days=1)

    for entry in entries:
        try:
             # Date Checking (Generic)
             pub_date = None
             date_tag = entry.find(['pubDate', 'published', 'dc:date', 'updated'])
             if date_tag:
                 try:
                      # Try specific formats common in news feeds
                      # 1. Standard RSS: "Fri, 31 Jan 2025 15:00:00 +0000"
                      dt_text = date_tag.text.strip()
                      try:
                           dt = datetime.strptime(dt_text, "%a, %d %b %Y %H:%M:%S %z")
                           pub_date = dt.astimezone(local_tz).date()
                      except:
                           # 2. ISO/Atom: "2025-01-31T15:00:00Z"
                           pub_date = datetime.fromisoformat(dt_text.replace('Z', '+00:00')).astimezone(local_tz).date()
                      
                      if not DEBUG_MODE and pub_date and pub_date not in [today, yesterday]:
                           continue
                 except: pass
            
             title_tag = entry.find(['title', 'dc:title'])
             link_tag = entry.find(['link', 'guid', 'id']) 
             
             # Atom link handling
             link_str = None
             if link_tag:
                  if link_tag.name == 'link' and link_tag.get('href'):
                       link_str = link_tag.get('href')
                  else:
                       link_str = link_tag.text.strip()
             
             if not title_tag or not link_str: continue

             # Image Handling
             image_url = None
             # 1. Media Content / Enclosure
             media = entry.find(['media:content', 'enclosure'])
             if media and media.get('url'):
                  image_url = media.get('url')
             # 2. Content encoded extract
             if not image_url:
                  content = entry.find(['content:encoded', 'content', 'description'])
                  if content:
                       c_soup = BeautifulSoup(content.text, "html.parser")
                       img = c_soup.find("img")
                       if img: image_url = img.get("src")
             
             # Summary
             description = entry.find(['description', 'content', 'content:encoded', 'summary'])
             summary_text = clean_text_extractor(description) if description else ""

             # Category
             cat_tag = entry.find(['category', 'dc:subject'])
             category = None
             if cat_tag:
                 category = cat_tag.get('term') or cat_tag.text

             item = NewsItem(
                title=title_tag.text.strip(),
                source=source_code,
                article_url=link_str,
                image_url=image_url,
                summary_text=summary_text,
                category=category
             )
             items.append(item)
        except Exception: 
            continue
            
    return items

def fetch_reuters_items():
    """
    Fetches Reuters news using JSON API if possible, falls back to HTML parsing.
    """
    session = get_scraping_session()
    items = []
    
    # URL for World News JSON
    # Verified endpoint or similar: https://www.reuters.com/world/?outputType=json
    # Or the user suggested: https://www.reuters.com/arc/outboundfeeds/newsroom/?outputType=json
    # Let's try the user suggested one + the world one.
    
    urls_to_try = [
        "https://www.reuters.com/world/?outputType=json",
        "https://www.reuters.com/arc/outboundfeeds/newsroom/?outputType=json"
    ]
    
    headers = {
        'User-Agent': random.choice(USER_AGENTS),
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': 'application/json'
    }
    
    for url in urls_to_try:
        try:
            r = session.get(url, headers=headers, timeout=15)
            if r.status_code == 200 and 'application/json' in r.headers.get('content-type', ''):
                data = r.json()
                # Parse JSON structure
                # Structure varies, but usually under 'items', 'headlines', or 'stories'
                raw_items = data.get('items', []) or data.get('stories', []) or data.get('headlines', [])
                
                # If it's the 'newsroom' feed, it might be a list directly or in 'elements'
                
                for entry in raw_items:
                    # Extract fields
                    title = entry.get('title') or entry.get('headline', '')
                    if isinstance(title, dict): title = title.get('text', '') # sometimes headline is an object
                    
                    if not title: continue
                    
                    # Url
                    web_url = entry.get('url') or entry.get('canonical_url') or entry.get('web_url')
                    if web_url and not web_url.startswith('http'):
                        web_url = f"https://www.reuters.com{web_url}"
                        
                    # Summary
                    summary = entry.get('description') or entry.get('sub_as_text') or ""
                    
                    # Image
                    image_url = None
                    try:
                        # Common reuters image paths
                        images = entry.get('image', []) or entry.get('images', [])
                        if isinstance(images, list) and images:
                             image_url = images[0].get('url')
                        elif isinstance(images, dict):
                             image_url = images.get('url')
                    except: pass
                    
                    if not image_url:
                        # Try finding in promo
                        promo = entry.get('promo_image', {})
                        if promo: image_url = promo.get('url')

                    # Date check (if possible to parse 'updated' or 'published_time')
                    # We skip date check here and rely on dedupe for simplicity unless we get a clean timestamp
                    
                    items.append(NewsItem(
                        title=title.strip(),
                        source="REUTERS",
                        article_url=web_url,
                        image_url=image_url,
                        summary_text=clean_text_extractor(summary)
                    ))
                
                if items:
                    logging.info(f"Fetched {len(items)} Reuters items via JSON.")
                    return items
                    
        except Exception as e:
            logging.warning(f"Reuters JSON fetch failed for {url}: {e}")
            continue

    # Fallback to Google RSS if JSON fails
    return fetch_reuters_google_fallback()

def fetch_reuters_google_fallback():
    """Fallback using the Google News RSS bridge."""
    session = get_scraping_session()
    try:
        # Using Google News RSS bridge for Reuters
        rss_url = "https://news.google.com/rss/search?q=when:24h+source:Reuters&hl=en-US&gl=US&ceid=US:en"
        r = session.get(rss_url, timeout=20)
        soup = BeautifulSoup(r.content, "xml")
        return parse_reuters_google_rss(soup)
    except Exception as e:
        logging.error(f"Reuters fallback failed: {e}")
        return []

def parse_reuters_google_rss(soup):
    """
    Targeted parser for Reuters via Google News RSS.
    """
    items = parse_rss_robust(soup, "REUTERS")
    # Post-process to decode URLs or fetch better images
    for item in items:
        # 1. Clean Title (Google News adds "- SourceName" at the end)
        if " - " in item.title:
            item.title = item.title.rsplit(" - ", 1)[0]

        # 2. Decode URL
        # We try to keep it simple. If we can't decode, the user will just follow the google link.
        pass
            
    return items

def fetch_rss(url, source_name, parser_func):
    """
    Generic RSS fetcher. Supports both Atom (Reddit) and RSS 2.0 (WordPress).
    """
    session = get_scraping_session()
    try:
        # Reddit special user-agent check removed
            
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



class JikanRateLimitError(Exception): pass

@retry(
    retry=retry_if_exception_type(JikanRateLimitError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=10)
)
def fetch_jikan_data_robust(url, session):
    """Helper to fetch Jikan data with specific 429 retry logic."""
    r = session.get(url, timeout=15)
    if r.status_code == 429:
        raise JikanRateLimitError(f"Jikan Rate Limit: {url}")
    r.raise_for_status()
    return r.json().get("data", [])

def fetch_jikan_safe():
    """
    Fetches news for Top 5 Airing Anime via Jikan API with robust rate limiting.
    """
    session = get_scraping_session()
    items = []
    try:
        # 1. Get Top Anime
        top_url = f"{JIKAN_BASE}/top/anime?filter=airing&limit=5"
        try:
             data = fetch_jikan_data_robust(top_url, session)
        except Exception as e:
             logging.error(f"Jikan Top Anime fetch failed: {e}")
             return []
        
        for anime in data:
            if not circuit_breaker.can_call("MAL"): break
            
            anime_id = anime.get("mal_id")
            anime_title = anime.get("title")
            if not anime_id: continue
            
            # 2. Get News for this anime
            news_url = f"{JIKAN_BASE}/anime/{anime_id}/news"
            try:
                # Small courtesy sleep between different anime calls even with retries
                time.sleep(1.5) 
                
                news_data = fetch_jikan_data_robust(news_url, session)
                
                for n in news_data:
                    # Filter by date strict check
                    date_str = n.get("date")
                    if date_str:
                        try:
                            # Jikan ISO format: 2024-01-18T14:00:00+00:00
                            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                            n_date = dt.astimezone(local_tz).date()
                            today = now_local().date()
                            yesterday = today - timedelta(days=1)
                            
                            if not DEBUG_MODE and n_date not in [today, yesterday]:
                                continue
                        except Exception:
                            continue

                    title = n.get("title")
                    url = n.get("url")
                    image = n.get("images", {}).get("jpg", {}).get("large_image_url") or n.get("images", {}).get("jpg", {}).get("image_url")
                    excerpt = n.get("excerpt", "News about " + anime_title)
                    
                    item = NewsItem(
                        title=f"{anime_title}: {title}",
                        source="MAL",
                        article_url=url,
                        image_url=image,
                        summary_text=excerpt
                    )
                    items.append(item)
                    
            except Exception as e:
                logging.error(f"Failed to fetch MAL news for {anime_id}: {e}")
                
    except Exception as e:
        logging.error(f"Jikan global failure: {e}")
        circuit_breaker.record_failure("MAL")
    finally:
        session.close()
    
    return items

def fetch_details_concurrently(items):
    def get_details(item: NewsItem):
        if not item.article_url: return item
        
        # Verify URL is scrapable (skip Google News redirect pages to avoid wrong image)
        if "news.google.com" in item.article_url:
             return item

        session = get_scraping_session()
        try:
            r = session.get(item.article_url, timeout=15)
            s = BeautifulSoup(r.text, "html.parser")
            
            # 1. OpenGraph First (Usually best quality)
            og_img = s.find("meta", property="og:image")
            if og_img and og_img.get("content"):
                item.image_url = og_img["content"]

            # 2. Try text content/meat div (Fallback)
            if not item.image_url:
                content_div = s.find("div", class_="meat") or s.find("div", class_="content")
                if content_div:
                    for img in content_div.find_all("img"):
                        src = img.get("src") or img.get("data-src")
                        if src and "spacer" not in src and "pixel" not in src and not src.endswith(".gif"):
                            if "facebook" in src or "twitter" in src: continue
                            full_src = f"{BASE_URL}{src}" if not src.startswith("http") else src
                            item.image_url = full_src
                            break
            
            # 3. Fallback to thumbnail
            if not item.image_url:
                thumb = s.find("div", class_="thumbnail lazyload")
                if thumb and thumb.get("data-src"): 
                    src = thumb['data-src']
                    item.image_url = f"{BASE_URL}{src}" if not src.startswith("http") else src

            # Summary extraction
            div = s.find("div", class_="meat") or s.find("div", class_="content")
            if div:
                # Use centralized utility for consistent cleaning
                txt = clean_text_extractor(div)
                item.summary_text = txt[:350] + "..." if len(txt) > 350 else txt
        except Exception as e:
            logging.error(f"Details fetch failed for {item.article_url}: {e}")
        finally: session.close()
        return item

    with ThreadPoolExecutor(max_workers=5) as ex:
        ex.map(get_details, items)
    # --- 8. TELEGRAM SENDER ---
    return items

def get_smart_tag_key(item: NewsItem):
    """
    Determines the tag KEY based on content.
    """
    text = (item.title + " " + (item.summary_text or "") + " " + (item.category or "")).lower()
    
    if item.category:
        cat = item.category.lower()
        if "review" in cat: return "REVIEW"
        if "editorial" in cat: return "EDITORIAL"
        if "interview" in cat: return "INTERVIEW"
        if "cosplay" in cat: return "COSPLAY"
        if "quiz" in cat: return "QUIZ"
        if "gallery" in cat: return "GALLERY"

    # Keyword Scanning
    if any(x in text for x in ["episode", "preview", "broadcast", "airing"]): return "EPISODE"
    if any(x in text for x in ["chapter", "manga", "volume", "tankobon"]): return "MANGA"
    if any(x in text for x in ["movie", "film", "cinema", "theatrical", "theater"]): return "MOVIE"
    if any(x in text for x in ["figure", "merch", "goods", "nendoroid", "plush"]): return "MERCH"
    if any(x in text for x in ["game", "mobile game", "visual novel", "nintendo", "ps5"]): return "GAME"
    if any(x in text for x in ["music", "opening", "ending", "op/ed", "soundtrack", "ost"]): return "MUSIC"
    if any(x in text for x in ["cast", "staff", "voice actor", "seiyuu"]): return "CAST"
    if "trailer" in text or "pv" in text: return "TRAILER"
        
    return None

def format_message(item: NewsItem):
    # Source Configs
    source_configs = {
        "ANN": { "emoji": "📰", "tag": "ANIME NEWS", "color": "🔴", "source_name": "Anime News Network", "channel_tag": "@Detective_Conan_News" },
        "ANN_DC": { "emoji": "🕵️", "tag": "CONAN NEWS", "color": "🔵", "source_name": "ANN (Detective Conan)", "channel_tag": "@Detective_Conan_News" },
        "DCW": { "emoji": "📚", "tag": "WIKI UPDATE", "color": "🟢", "source_name": "Detective Conan Wiki", "channel_tag": "@Detective_Conan_News" },
        "TMS": { "emoji": "🎬", "tag": "TMS UPDATE", "color": "🟡", "source_name": "TMS Entertainment", "channel_tag": "@Detective_Conan_News" },
        "FANDOM": { "emoji": "🌐", "tag": "FANDOM NEWS", "color": "🟣", "source_name": "Fandom Wiki", "channel_tag": "@Detective_Conan_News" },
        "MAL": { "emoji": "📈", "tag": "MAL TRENDING", "color": "🔵", "source_name": "MyAnimeList", "channel_tag": "@Detective_Conan_News" },
        "CR": { "emoji": "🟠", "tag": "CRUNCHYROLL", "color": "🟠", "source_name": "Crunchyroll News", "channel_tag": "@Detective_Conan_News" },
        "AC": { "emoji": "🏯", "tag": "ANIME CORNER", "color": "🔴", "source_name": "Anime Corner", "channel_tag": "@Detective_Conan_News" },
        "HONEY": { "emoji": "🍯", "tag": "HONEY'S ANIME", "color": "🟡", "source_name": "Honey's Anime", "channel_tag": "@Detective_Conan_News" },
        "ANI": { "emoji": "🇮🇳", "tag": "ANIME INDIA", "color": "🟠", "source_name": "Anime News India", "channel_tag": "@Detective_Conan_News" },
        # Reddit sources removed
        # Added explicit configs for World News to remove channel tag
        "AP": { "emoji": "🌍", "tag": "WORLD NEWS", "color": "🔵", "source_name": "AP News", "channel_tag": None },
        "REUTERS": { "emoji": "🗺️", "tag": "WORLD NEWS", "color": "🟠", "source_name": "Reuters", "channel_tag": None },
    }
    
    # Tag Configs (The "JSON" features requested)
    tag_configs = {
        "REVIEW": { "emoji": "📝", "tag": "REVIEW", "color": "🟡" },
        "EDITORIAL": { "emoji": "🖊️", "tag": "EDITORIAL", "color": "⚪" },
        "INTERVIEW": { "emoji": "🎤", "tag": "INTERVIEW", "color": "🟣" },
        "COSPLAY": { "emoji": "🎭", "tag": "COSPLAY", "color": "🌸" },
        "QUIZ": { "emoji": "❓", "tag": "QUIZ", "color": "🔵" },
        "GALLERY": { "emoji": "🖼️", "tag": "GALLERY", "color": "🟠" },
        "EPISODE": { "emoji": "📺", "tag": "EPISODE UPDATE", "color": "🔴" },
        "MANGA": { "emoji": "📖", "tag": "MANGA UPDATE", "color": "🟢" },
        "MOVIE": { "emoji": "🎬", "tag": "MOVIE NEWS", "color": "🎥" },
        "MERCH": { "emoji": "🎁", "tag": "MERCHANDISE", "color": "🟠" },
        "GAME": { "emoji": "🎮", "tag": "GAMING NEWS", "color": "👾" },
        "MUSIC": { "emoji": "🎵", "tag": "MUSIC NEWS", "color": "🎹" },
        "CAST": { "emoji": "🎙️", "tag": "CAST & STAFF", "color": "🔵" },
        "TRAILER": { "emoji": "🎞️", "tag": "TRAILER / PV", "color": "🎬" }
    }
    
    # Default Config
    config = source_configs.get(item.source, {
        "emoji": "📰", "tag": "NEWS UPDATE", "color": "⚪", "source_name": item.source, "channel_tag": "@Detective_Conan_News"
    })

    # Apply Smart Tagging
    tag_key = get_smart_tag_key(item)
    if tag_key and tag_key in tag_configs:
        tc = tag_configs[tag_key]
        config["emoji"] = tc["emoji"]
        config["tag"] = tc["tag"]
        config["color"] = tc["color"]
    
    # Safe text processing with proper escaping using html library
    # quote=False for content text (allows quotes to be visible)
    title = html.escape(str(item.title or "No Title"), quote=False)
    summary = html.escape(str(item.summary_text or "No summary available"), quote=False)
    link = str(item.article_url or "")
    
    # Build message components safely
    components = [
        f"{config['emoji']} <b>{config['tag']}</b> {config['color']}",
        f"<b>{title}</b>",
        f"<i>{summary}</i>",
        f"📊 <b>Source:</b> {config['source_name']}"
    ]
    
    # Conditionally add channel line
    if config.get('channel_tag'):
        components.append(f"📢 <b>Channel:</b> {config['channel_tag']}")
    
    # Add link only if valid
    if link and link.startswith('http'):
        # quote=True is CRITICAL here for href attributes to escape ' and "
        safe_link = html.escape(link, quote=True)
        components.append(f"🔗 <a href='{safe_link}'>Read Full Article</a>")
    
    # Join with proper spacing and JSON-safe formatting
    msg = "\n\n".join(components)
    
    return msg

def get_target_channel(source):
    """Determine which channel to send the post to based on source"""
    if source in WORLD_NEWS_SOURCES and WORLD_NEWS_CHANNEL_ID:
        return WORLD_NEWS_CHANNEL_ID
    if source in ANIME_NEWS_SOURCES and ANIME_NEWS_CHANNEL_ID:
         return ANIME_NEWS_CHANNEL_ID
    # Fallback to main chat ID for everything else
    return CHAT_ID or ANIME_NEWS_CHANNEL_ID

def send_to_telegram(item: NewsItem, run_id, slot, posted_set):
    # DEDUPLICATION CHECK
    # We normalized earlier, but let's be safe.
    if is_duplicate(item.title, item.article_url, posted_set):
        logging.info(f"Skipping duplicate: {item.title}")
        return False

    # RECORD ATTEMPT FIRST (Prevents loops if we crash)
    # Status = 'attempted'
    if not record_post(item.title, item.source, run_id, slot, posted_set, item.category or None, status='attempted'):
        # If we can't record, we shouldn't send (DB issue?). 
        # But if DB is down, we might want to send anyway?
        # User said "Record before sending".
        logging.warning("Failed to record attempt, skipping send to avoid spam loop.")
        return False
        
    msg = format_message(item)
    target_chat_id = get_target_channel(item.source)
    success = False
    
    # Try sending with photo first
    if item.image_url:
        try:
            sess = get_fresh_telegram_session()
            response = sess.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": target_chat_id, "photo": item.image_url, "caption": msg, "parse_mode": "HTML"},
                timeout=20
            )
            sess.close()
            
            if response.status_code == 200:
                logging.info(f"Message sent (Image): {item.title[:50]}")
                success = True
            elif response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 30))
                logging.warning(f"Rate limited (Image). Sleeping {retry_after}s")
                time.sleep(retry_after)
            else:
                logging.warning(f"Image send failed: {response.text}")
        except Exception as e:
            logging.warning(f"Image send failed for {item.title}: {e}")

    # Fallback to text-only if image failed
    if not success:
        try:
            sess = get_fresh_telegram_session()
            response = sess.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": target_chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=20
            )
            
            if response.status_code == 429:
                 retry_after = int(response.headers.get("Retry-After", 30))
                 time.sleep(retry_after)
                 response = sess.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={"chat_id": target_chat_id, "text": msg, "parse_mode": "HTML"},
                    timeout=20
                )
            sess.close()
            
            if response.status_code == 200:
                 logging.info(f"Message sent (Text): {item.title[:50]}")
                 success = True
            else:
                 logging.error(f"Final send attempt failed: {response.text}")
                 
        except Exception as e:
            logging.error(f"Final send attempt failed: {e}")
            
    if success:
        # UPDATE STATUS TO SENT
        update_post_status(item.title, 'sent')
        
        # Update in-memory set so future checks in this run know it's sent
        key = normalize_title(item.title)
        posted_set.add(key)
        return True
        
    return False

def send_admin_report(run_id, status, posts_sent, source_counts, error=None):
    """
    Sends a comprehensive report to the ADMIN_ID after each cycle.
    Includes: Present stats, Past record, Health warnings, Source breakdown, Channel distribution.
    """
    if not ADMIN_ID: return # Skip if no admin configured

    # 1. Gather Data
    dt = now_local()
    date_str = str(dt.date())
    slot = slot_index(dt)
    
    # Calculate channel distribution
    dc_posts = sum(count for source, count in source_counts.items() if source in DC_NEWS_SOURCES)
    anime_posts = sum(count for source, count in source_counts.items() if source in ANIME_NEWS_SOURCES)
    world_posts = sum(count for source, count in source_counts.items() if source in WORLD_NEWS_SOURCES)
    # Reddit posts removed
    
    # Fetch Daily Total
    daily_total = 0
    if supabase:
        try:
            d = supabase.table("daily_stats").select("posts_count").eq("date", date_str).limit(1).execute()
            if d.data: daily_total = d.data[0].get("posts_count", 0)
        except: pass

    # Fetch All-Time Total
    all_time_total = 0
    if supabase:
        try:
            b = supabase.table("bot_stats").select("total_posts_all_time").limit(1).execute()
            if b.data: all_time_total = b.data[0].get("total_posts_all_time", 0)
        except: pass
        
    # Check Health / Circuit Breaker
    health_warnings = []
    if error:
        health_warnings.append(f"⚠️ <b>Critical Error:</b> {html.escape(str(error)[:100], quote=False)}")
    
    for source, count in circuit_breaker.failure_counts.items():
        if count >= circuit_breaker.failure_threshold:
             health_warnings.append(f"⚠️ <b>Source Skipped:</b> {source} (Failures: {count})")
    
    health_status = "✅ <b>System Healthy</b>" if not health_warnings else "\n".join(health_warnings)

    # Format Source Counts
    source_stats = "\n".join([f"• <b>{k}:</b> {v}" for k, v in source_counts.items()])
    if not source_stats: source_stats = "• No new posts found."

    # 2. Build Message
    report_msg = (
        f"🤖 <b>Scraper Bot Cycle Report</b>\n"
        f"📅 Date: {date_str} | 🕒 Slot: {slot}\n\n"
        
        f"<b>📊 Present Cycle</b>\n"
        f"• Status: {status.upper()}\n"
        f"• Posts Sent: {posts_sent}\n"
        f"• DC News: {dc_posts}\n"
        f"• Anime News: {anime_posts}\n"
        f"• World News: {world_posts}\n"
        f"• Breakdown:\n{source_stats}\n\n"
        
        f"<b>📈 Statistics</b>\n"
        f"• Today's Total: {daily_total}\n"
        f"• All-Time Record: {all_time_total}\n\n"
        
        f"<b>🏥 Health Status</b>\n"
        f"{health_status}"
    )

    # 3. Send
    sess = get_fresh_telegram_session()
    try:
        sess.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", 
                  json={"chat_id": ADMIN_ID, "text": report_msg, "parse_mode": "HTML"}, timeout=20)
    except Exception as e:
        logging.error(f"Failed to send admin report: {e}")
    finally:
        sess.close()

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

    # 1.5 AUTO-RESET REMOVED
    # User requested to keep history forever and not delete old posts daily.
    # The deduplication window is handled by load_posted_titles fetching the last 7 days.


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

    # Anime News India
    if circuit_breaker.can_call("ANI"):
        ani_items = fetch_rss(RSS_ANI, "ANI", lambda s: parse_rss_robust(s, "ANI"))
        all_items.extend(ani_items)

    # Reddit Scrapers (RSS) - Removed due to user request
    # r/anime, r/OTP, r/DC logic deleted

    # Crunchyroll
    if circuit_breaker.can_call("CR"):
        cr_items = fetch_rss(RSS_CRUNCHYROLL, "CR", lambda s: parse_rss_robust(s, "CR"))
        all_items.extend(cr_items)

    # Anime Corner
    if circuit_breaker.can_call("AC"):
        # Use generic loop if possible, provided we mapped it in RSS_FEEDS
        # But we can keep explicit if we want.
        pass

    # GENERIC RSS FETCHING LOOP (Replaces individual calls)
    for code, url in RSS_FEEDS.items():
        if circuit_breaker.can_call(code):
            try:
                # Custom parse function not needed for most, parse_rss_robust handles it.
                items = fetch_rss(url, code, lambda s: parse_rss_robust(s, code))
                all_items.extend(items)
            except Exception:
                continue

    # AP News (HTML)
    if circuit_breaker.can_call("AP"):
        # Keep AP separate as it parses HTML
        ap_items = fetch_generic(BASE_URL_AP_NEWS, "AP", parse_ap_html)
        # Limit AP items to avoid flooding generic news
        all_items.extend(ap_items[:5])

    # Reuters (JSON or Fallback)
    if circuit_breaker.can_call("REUTERS"):
        reuters_items = fetch_reuters_items()
        all_items.extend(reuters_items[:10])


    # MAL (Jikan)
    if circuit_breaker.can_call("MAL"):
        mal_items = fetch_jikan_safe()
        all_items.extend(mal_items)

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
    
    # 6. Report
    send_admin_report(run_id, "success", sent_count, source_counts)

if __name__ == "__main__":
    try:
        # CRON MODE: Run once and exit.
        # The external scheduler (GitHub Actions, Cron, etc.) determines when to run.
        run_once()
    except KeyboardInterrupt:
        logging.info("Bot stopped by user.")
    except Exception as e:
        logging.error(f"FATAL ERROR: {e}")
        # Send crash report
        try:
            send_admin_report("CRASH", "failed", 0, {}, error=str(e))
        except: pass
        exit(1)
