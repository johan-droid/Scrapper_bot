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
        category: Optional[str] = None,
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
        self.category = category
        
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


def clean_text_extractor(html_text_or_element, limit=350):
    """
    Robustly cleans HTML content and removes junk data.
    """
    if not html_text_or_element: return "No summary available."

    # Convert BS4 element to string if needed
    if hasattr(html_text_or_element, "get_text"):
        soup = html_text_or_element
    else:
        raw_str = str(html_text_or_element)
        if "<" in raw_str and ">" in raw_str:
             soup = BeautifulSoup(raw_str, "html.parser")
        else:
             return raw_str[:limit]

    # Remove script and style tags entirely
    for script in soup(["script", "style", "header", "footer", "a"]):
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

# Load env vars
env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path, override=True)

# Windows terminal compatibility - FIXED
import sys
import os

# Set environment variables for UTF-8 support
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Windows-specific encoding fixes
if sys.platform == "win32":
    import codecs
    import locale
    
    # Set console code page to UTF-8
    try:
        import subprocess
        subprocess.run(['chcp', '65001'], shell=True, capture_output=True)
    except:
        pass
    
    # Configure stdout/stderr for UTF-8
    try:
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    except (AttributeError, OSError):
        # Fallback for older Python versions or different terminal types
        pass

# Ensure UTF-8 encoding for all string operations
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, OSError):
    pass

# Configure logging with UTF-8 support
class UTF8StreamHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            # Ensure message is properly encoded
            if isinstance(msg, str):
                msg = msg.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
            stream = self.stream
            stream.write(msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[UTF8StreamHandler()],
    force=True,
)

SESSION_ID = str(uuid.uuid4())[:8]

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WORLD_NEWS_CHANNEL_ID = os.getenv("WORLD_NEWS_CHANNEL_ID")
ANIME_NEWS_CHANNEL_ID = os.getenv("ANIME_NEWS_CHANNEL_ID")
ADMIN_ID = os.getenv("ADMIN_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Circuit breaker
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
    "MAL": "MyAnimeList (Jikan)", "CR": "Crunchyroll News",
    "AC": "Anime Corner", "HONEY": "Honey's Anime",
    "AP": "AP News (Entertainment)",
    "REUTERS": "Reuters (Lifestyle)",
    # World News Sources
    "BBC": "BBC World News", "ALJ": "Al Jazeera", "CNN": "CNN World", "GUARD": "The Guardian",
    "NPR": "NPR International", "DW": "Deutsche Welle", "F24": "France 24", "CBC": "CBC World",
    # General News Sources
    "NL": "NewsLaundry", "WIRE": "The Wire", "CARAVAN": "Caravan Magazine", "SCROLL": "Scroll.in",
    "PRINT": "The Print", "INTER": "The Intercept", "PRO": "ProPublica"
}

# RSS Feeds Dictionary
RSS_FEEDS = {
    # Anime
    "ANI": "https://animenewsindia.com/feed/",
    "CR": "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss",
    "AC": "https://animecorner.me/feed/",
    "HONEY": "https://honeysanime.com/feed/",
    # World News - THESE MUST GO TO WORLD_NEWS_CHANNEL_ID
    "BBC": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "ALJ": "https://www.aljazeera.com/xml/rss/all.xml",
    "CNN": "http://rss.cnn.com/rss/edition_world.rss",
    "GUARD": "https://www.theguardian.com/world/rss",
    "NPR": "https://feeds.npr.org/1001/rss.xml",
    "DW": "https://www.dw.com/en/rss/rss-en-all",
    "F24": "https://www.france24.com/en/rss",
    "CBC": "https://www.cbc.ca/cmlink/rss-world",
    # General News - THESE GO TO WORLD_NEWS_CHANNEL_ID
    "NL": "https://www.newslaundry.com/feed",
    "WIRE": "https://thewire.in/feed",
    "CARAVAN": "https://caravanmagazine.in/feed",
    "SCROLL": "https://scroll.in/feed",
    "PRINT": "https://theprint.in/feed",
    "INTER": "https://theintercept.com/feed/?lang=en",
    "PRO": "https://www.propublica.org/feeds/propublica/main",
}

JIKAN_BASE = "https://api.jikan.moe/v4"
BASE_URL_AP_NEWS = "https://apnews.com/hub/entertainment"

# ===== CRITICAL: CHANNEL ROUTING CONFIGURATION =====
# Define which sources go to which channel
ANIME_NEWS_SOURCES = {"ANN", "ANN_DC", "DCW", "TMS", "FANDOM", "ANI", "MAL", "CR", "AC", "HONEY"}

# WORLD NEWS SOURCES - MUST POST TO WORLD_NEWS_CHANNEL_ID
WORLD_NEWS_SOURCES = {
    "AP", "REUTERS",
    "BBC", "ALJ", "CNN", "GUARD", "NPR", "DW", "F24", "CBC",  # World News
    "NL", "WIRE", "CARAVAN", "SCROLL", "PRINT", "INTER", "PRO"  # General News
}

ALL_NEWS_SOURCES = ANIME_NEWS_SOURCES | WORLD_NEWS_SOURCES

if not BOT_TOKEN:
    logging.error("CRITICAL: BOT_TOKEN is missing.")
    raise SystemExit(1)

if not ANIME_NEWS_CHANNEL_ID and not CHAT_ID:
    logging.error("CRITICAL: Either ANIME_NEWS_CHANNEL_ID or CHAT_ID must be set.")
    raise SystemExit(1)

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
        safe_log("info", f"Supabase connected successfully")
    except Exception as e:
        safe_log("warning", f"Supabase connection failed: {e}")
        safe_log("warning", "WARNING: Running WITHOUT database. Duplicates may occur.")
        supabase = None
else:
    logging.warning("WARNING: Running WITHOUT database. Duplicates will occur if runs restart.")

# --- 3. SESSION HELPERS ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
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
    
    ua = random.choice(USER_AGENTS)
    session.headers.update({
        "User-Agent": ua,
        "Connection": "close",
        "Accept-Charset": "utf-8",
        "Accept-Encoding": "gzip, deflate"
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
def now_local(): 
    return datetime.now(local_tz)

def is_today_or_yesterday(dt_to_check):
    """Check if a date is today or yesterday in IST"""
    if not dt_to_check:
        return False
    today = now_local().date()
    yesterday = today - timedelta(days=1)
    check_date = dt_to_check.date() if isinstance(dt_to_check, datetime) else dt_to_check
    return check_date in [today, yesterday]

def should_reset_daily_tracking():
    """Check if we should reset daily tracking (new day started)"""
    now = now_local()
    # Reset happens at midnight IST
    if now.hour == 0 and now.minute < 15:  # Within first 15 minutes of new day
        return True
    return False

# --- 5. TEXT & VALIDATION HELPERS ---
def safe_log(level, message, *args, **kwargs):
    """Safe logging function that handles encoding issues"""
    try:
        # Ensure message is string and properly encoded
        if not isinstance(message, str):
            message = str(message)
        message = message.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
        
        # Remove problematic Unicode characters that cause terminal issues
        message = message.replace('✅', '[OK]').replace('❌', '[ERROR]').replace('⚠️', '[WARN]')
        message = message.replace('🚫', '[BLOCKED]').replace('📍', '[ROUTE]').replace('🔄', '[RESET]')
        message = message.replace('📡', '[FETCH]').replace('📤', '[SEND]').replace('🔍', '[ENRICH]')
        message = message.replace('🚀', '[START]').replace('📅', '[DATE]').replace('🕒', '[SLOT]')
        message = message.replace('⏰', '[TIME]').replace('📚', '[LOAD]').replace('⏭️', '[SKIP]')
        message = message.replace('⏳', '[WAIT]').replace('🤖', '[BOT]').replace('📊', '[STATS]')
        message = message.replace('📈', '[TOTAL]').replace('🏆', '[ALL]').replace('📰', '[SOURCE]')
        message = message.replace('🏥', '[HEALTH]').replace('🌍', '[WORLD]').replace('🕵️', '[CONAN]')
        
        getattr(logging, level.lower())(message, *args, **kwargs)
    except Exception:
        # Fallback to basic print if logging fails
        try:
            print(f"[{level.upper()}] {message}")
        except:
            print(f"[{level.upper()}] <encoding error>")

def escape_html(text):
    if not text or not isinstance(text, str): return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def normalize_title(title):
    """Normalize title for fuzzy matching"""
    prefixes = ["BREAKING:", "NEW:", "UPDATE:", "DC Wiki Update: ", "TMS News: ", 
                "Fandom Wiki Update: ", "ANN DC News: ", "ANN:", "Reuters:", "BBC:"]
    t = title
    for p in prefixes:
        if t.upper().startswith(p.upper()):
            t = t[len(p):].strip()
    
    t = re.sub(r'[^\w\s]', '', t)
    return t.lower().strip()

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

# --- 6. ENHANCED DATABASE LOGIC WITH STRONG SPAM DETECTION ---
def is_duplicate(title, url, posted_titles_set, date_check=True):
    """
    STRONG SPAM DETECTION:
    1. Check normalized title in memory set
    2. Fuzzy match against recent titles (>85% similarity)
    3. Check database for permanent history
    4. Verify date is today or yesterday (unless DEBUG_MODE)
    """
    norm_title = normalize_title(title)
    
    # Quick exact check in local set
    if norm_title in posted_titles_set:
        safe_log("info", f"DUPLICATE (Exact): {title[:50]}")
        return True
    
    # Fuzzy check against local set with HIGHER threshold (85%)
    for existing in posted_titles_set:
        ratio = difflib.SequenceMatcher(None, norm_title, existing).ratio()
        if ratio > 0.85:  # Increased from 0.7 to 0.85 for stronger detection
            safe_log("info", f"DUPLICATE (Fuzzy {ratio:.2%}): {title[:50]}")
            return True
    
    # Database check for permanent history
    if supabase:
        try:
            # Check last 7 days for this normalized title
            past_date = str((now_local().date() - timedelta(days=7)))
            r = supabase.table("posted_news")\
                .select("normalized_title, posted_date")\
                .eq("normalized_title", norm_title)\
                .gte("posted_date", past_date)\
                .limit(1)\
                .execute()
            
            if r.data:
                safe_log("info", f"DUPLICATE (Database): {title[:50]}")
                return True
        except Exception as e:
            logging.warning(f"DB duplicate check failed: {e}")
    
    return False

def initialize_bot_stats():
    if not supabase: return
    try:
        resp = supabase.table("bot_stats").select("*").limit(1).execute()
        if not resp.data:
            now = datetime.now(utc_tz).isoformat()
            supabase.table("bot_stats").insert({
                "bot_started_at": now, 
                "total_posts_all_time": 0
            }).execute()
            safe_log("info", "Bot stats initialized")
    except Exception as e:
        logging.error(f"Failed to initialize bot stats: {e}")

def ensure_daily_row(date_obj):
    if not supabase: return
    try:
        r = supabase.table("daily_stats").select("date").eq("date", str(date_obj)).limit(1).execute()
        if not r.data:
            supabase.table("daily_stats").insert({
                "date": str(date_obj), 
                "posts_count": 0
            }).execute()
    except Exception as e:
        logging.error(f"Failed to ensure daily row: {e}")

def increment_post_counters(date_obj):
    """Calls server-side functions to increment counters safely."""
    if not supabase: return
    try:
        supabase.rpc('increment_daily_stats', {'row_date': str(date_obj)}).execute()
        supabase.rpc('increment_bot_stats').execute()
    except Exception as e:
        logging.error(f"Atomic stats update failed: {e}")

def load_posted_titles(date_obj):
    """Load posted titles from last 7 days for strong deduplication"""
    if not supabase: return set()
    try:
        past_date = str(date_obj - timedelta(days=7))
        r = supabase.table("posted_news")\
            .select("normalized_title, full_title")\
            .gte("posted_date", past_date)\
            .execute()
        
        titles = set()
        for x in r.data:
            if "normalized_title" in x: 
                titles.add(x["normalized_title"].lower())
            if "full_title" in x: 
                titles.add(normalize_title(x["full_title"]))
        
        safe_log("info", f"Loaded {len(titles)} titles from last 7 days")
        return titles
    except Exception as e:
        logging.error(f"Failed to load posted titles: {e}")
        return set()

def record_post(title, source_code, slot, posted_titles_set, category=None, status='sent'):
    """Record a post to database with strong tracking"""
    key = normalize_title(title)
    date_obj = now_local().date()
    
    # Determine channel type based on source
    if source_code in WORLD_NEWS_SOURCES:
        channel_type = 'world'
    else:
        channel_type = 'anime'  # Includes both anime and DC news
    
    if supabase:
        try:
            payload = {
                "normalized_title": key, 
                "posted_date": str(date_obj), 
                "full_title": title,
                "posted_at": datetime.now(utc_tz).isoformat(), 
                "source": source_code,
                "slot": slot,
                "category": category,
                "status": status,
                "channel_type": channel_type
            }
            supabase.table("posted_news").insert(payload).execute()
            
            if status == 'sent':
                posted_titles_set.add(key)
                increment_post_counters(date_obj)
                safe_log("info", f"Recorded: {title[:50]}")
            return True
        except Exception as e:
            logging.warning(f"DB Record failed: {e}")
            return False
    else:
        # If no DB, just track in memory for this session
        if status == 'sent':
            posted_titles_set.add(key)
        return True

def update_post_status(title, status):
    """Updates the status of a post"""
    if not supabase: return
    try:
        key = normalize_title(title)
        date_obj = str(now_local().date())
        supabase.table("posted_news")\
            .update({"status": status})\
            .eq("normalized_title", key)\
            .eq("posted_date", date_obj)\
            .execute()
    except Exception as e:
        logging.warning(f"Failed to update status for {title}: {e}")

# --- 7. SCRAPERS (CONDENSED) ---
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=3, max=10))
def fetch_generic(url, source_name, parser_func):
    session = get_scraping_session()
    try:
        r = session.get(url, timeout=(5, 20), stream=False) 
        r.raise_for_status()
        return parser_func(r.text)
    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP {e.response.status_code} from {source_name}: {url}")
        circuit_breaker.record_failure(source_name)
        return []
    except Exception as e:
        logging.error(f"{source_name} critical failure: {str(e)}")
        circuit_breaker.record_failure(source_name)
        return []
    finally:
        session.close()

def parse_ann(html):
    soup = BeautifulSoup(html, "html.parser")
    today = now_local().date()
    yesterday = today - timedelta(days=1)
    out = []
    
    for article in soup.find_all("div", class_="herald box news t-news"):
        title_tag, date_tag = article.find("h3"), article.find("time")
        if not title_tag or not date_tag: continue
        
        try:
            news_date = datetime.fromisoformat(date_tag.get("datetime", "")).astimezone(local_tz).date()
        except: 
            continue
        
        # STRICT DATE FILTERING: Only today or yesterday
        if not DEBUG_MODE and news_date not in [today, yesterday]:
            continue
            
        link = title_tag.find("a")
        item = NewsItem(
            source="ANN",
            title=title_tag.get_text(" ", strip=True),
            article_url=f"{BASE_URL}{link['href']}" if link else None,
            publish_date=datetime.combine(news_date, datetime.min.time()).replace(tzinfo=local_tz)
        )
        
        intro = article.find("div", class_="intro") 
        if intro:
            item.summary_text = clean_text_extractor(intro)

        out.append(item)
    return out

def parse_ann_dc(html):
    items = parse_ann(html)
    for i in items: 
        i.source = "ANN_DC"
        i.title = f"ANN DC News: {i.title}"
    return items

def parse_rss_robust(soup, source_code):
    """
    Parses generic RSS/Atom feeds with STRICT date filtering
    """
    items = []
    entries = soup.find_all(['item', 'entry'])
    
    today = now_local().date()
    yesterday = today - timedelta(days=1)

    for entry in entries:
        try:
            # Date Checking (STRICT)
            pub_date = None
            date_tag = entry.find(['pubDate', 'published', 'dc:date', 'updated'])
            if date_tag:
                try:
                    dt_text = date_tag.text.strip()
                    try:
                        dt = datetime.strptime(dt_text, "%a, %d %b %Y %H:%M:%S %z")
                        pub_date = dt.astimezone(local_tz).date()
                    except:
                        pub_date = datetime.fromisoformat(dt_text.replace('Z', '+00:00')).astimezone(local_tz).date()
                    
                    # STRICT: Only today or yesterday
                    if not DEBUG_MODE and pub_date not in [today, yesterday]:
                        continue
                except: 
                    continue
            
            title_tag = entry.find(['title', 'dc:title'])
            link_tag = entry.find(['link', 'guid', 'id']) 
            
            link_str = None
            if link_tag:
                if link_tag.name == 'link' and link_tag.get('href'):
                    link_str = link_tag.get('href')
                else:
                    link_str = link_tag.text.strip()
            
            if not title_tag or not link_str: continue

            # Image Handling
            image_url = None
            media = entry.find(['media:content', 'enclosure'])
            if media and media.get('url'):
                image_url = media.get('url')
            
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
                category=category,
                publish_date=datetime.combine(pub_date, datetime.min.time()).replace(tzinfo=local_tz) if pub_date else None
            )
            items.append(item)
        except Exception: 
            continue
    
    return items

def fetch_rss(url, source_name, parser_func):
    """Generic RSS fetcher"""
    session = get_scraping_session()
    try:
        r = session.get(url, timeout=25)
        r.raise_for_status()
        
        try:
            soup = BeautifulSoup(r.content, "xml")
        except Exception:
            soup = BeautifulSoup(r.content, "html.parser")
            
        items = parser_func(soup)
        circuit_breaker.record_success(source_name)
        return items
    except Exception as e:
        logging.error(f"{source_name} RSS fetch failed: {e}")
        circuit_breaker.record_failure(source_name)
        return []
    finally:
        session.close()

def fetch_jikan_safe():
    """Fetches news for Top 5 Airing Anime via Jikan API"""
    session = get_scraping_session()
    items = []
    try:
        top_url = f"{JIKAN_BASE}/top/anime?filter=airing&limit=5"
        r = session.get(top_url, timeout=15)
        r.raise_for_status()
        data = r.json().get("data", [])
        
        today = now_local().date()
        yesterday = today - timedelta(days=1)
        
        for anime in data:
            if not circuit_breaker.can_call("MAL"): break
            
            anime_id = anime.get("mal_id")
            anime_title = anime.get("title")
            if not anime_id: continue
            
            time.sleep(1.5)
            news_url = f"{JIKAN_BASE}/anime/{anime_id}/news"
            try:
                nr = session.get(news_url, timeout=15)
                nr.raise_for_status()
                news_data = nr.json().get("data", [])
                
                for n in news_data:
                    date_str = n.get("date")
                    if date_str:
                        try:
                            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                            n_date = dt.astimezone(local_tz).date()
                            
                            # STRICT: Only today or yesterday
                            if not DEBUG_MODE and n_date not in [today, yesterday]:
                                continue
                        except Exception:
                            continue

                    title = n.get("title")
                    url = n.get("url")
                    image = n.get("images", {}).get("jpg", {}).get("large_image_url")
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
                
        circuit_breaker.record_success("MAL")
    except Exception as e:
        logging.error(f"Jikan global failure: {e}")
        circuit_breaker.record_failure("MAL")
    finally:
        session.close()
    
    return items

def fetch_details_concurrently(items):
    """Fetch detailed content for items"""
    def get_details(item: NewsItem):
        if not item.article_url or not item.article_url.startswith("http"):
            return item
        
        if "news.google.com" in item.article_url:
            return item

        session = get_scraping_session()
        try:
            r = session.get(item.article_url, timeout=15)
            s = BeautifulSoup(r.text, "html.parser")
            
            # OpenGraph image
            og_img = s.find("meta", property="og:image")
            if og_img and og_img.get("content"):
                item.image_url = og_img["content"]

            # Summary extraction
            div = s.find("div", class_="meat") or s.find("div", class_="content")
            if div and not item.summary_text:
                txt = clean_text_extractor(div)
                item.summary_text = txt[:350] + "..." if len(txt) > 350 else txt
        except Exception as e:
            logging.debug(f"Details fetch failed for {item.article_url}: {e}")
        finally: 
            session.close()
        return item

    with ThreadPoolExecutor(max_workers=5) as ex:
        ex.map(get_details, items)
    
    return items

# --- 8. TELEGRAM SENDER WITH PROPER CHANNEL ROUTING ---
def get_target_channel(source):
    """
    CRITICAL: Determine which channel to send the post to based on source
    This fixes the issue where world news was posting to anime channel
    """
    # WORLD NEWS SOURCES -> WORLD_NEWS_CHANNEL_ID (STRICT)
    if source in WORLD_NEWS_SOURCES:
        if WORLD_NEWS_CHANNEL_ID:
            safe_log("info", f"Routing {source} to WORLD_NEWS_CHANNEL")
            return WORLD_NEWS_CHANNEL_ID
        else:
            logging.warning(f"⚠️ WORLD_NEWS_CHANNEL_ID not set! {source} going to fallback")
            return CHAT_ID or ANIME_NEWS_CHANNEL_ID
    
    # ANIME NEWS SOURCES (includes DC news) -> ANIME_NEWS_CHANNEL_ID
    if source in ANIME_NEWS_SOURCES:
        if ANIME_NEWS_CHANNEL_ID:
            safe_log("info", f"Routing {source} to ANIME_NEWS_CHANNEL")
            return ANIME_NEWS_CHANNEL_ID
        else:
            return CHAT_ID or ANIME_NEWS_CHANNEL_ID
    
    # Default fallback
    logging.warning(f"⚠️ Unknown source {source}, using fallback channel")
    return CHAT_ID or ANIME_NEWS_CHANNEL_ID

def format_world_news_html(item: NewsItem):
    """
    SPECIAL HTML/JSON FORMAT FOR WORLD NEWS
    Enhanced formatting with more structure
    """
    title = html.escape(str(item.title or "No Title"), quote=False)
    summary = html.escape(str(item.summary_text or "No summary available"), quote=False)
    link = str(item.article_url or "")
    source_name = SOURCE_LABEL.get(item.source, item.source)
    
    # Build structured HTML message
    msg_parts = [
        f"🌍 <b>WORLD NEWS</b>",
        f"",  # Empty line
        f"<b>{title}</b>",
        f"",
        f"{summary}",
        f"",
        f"━━━━━━━━━━━━━━━━━",
        f"📰 <b>Source:</b> {source_name}",
    ]
    
    # Add category if available
    if item.category:
        cat = html.escape(str(item.category), quote=False)
        msg_parts.append(f"🏷️ <b>Category:</b> {cat}")
    
    # Add publish date if available
    if item.publish_date:
        dt_str = item.publish_date.strftime("%B %d, %Y at %I:%M %p IST")
        msg_parts.append(f"📅 <b>Published:</b> {dt_str}")
    
    # Add link
    if link and link.startswith('http'):
        safe_link = html.escape(link, quote=True)
        msg_parts.append(f"")
        msg_parts.append(f"🔗 <a href='{safe_link}'>Read Full Article</a>")
    
    return "\n".join(msg_parts)

def format_anime_news(item: NewsItem):
    """Standard format for anime news"""
    source_configs = {
        "ANN": { "emoji": "📰", "tag": "ANIME NEWS", "color": "🔴" },
        "ANN_DC": { "emoji": "🕵️", "tag": "CONAN NEWS", "color": "🔵" },
        "DCW": { "emoji": "📚", "tag": "WIKI UPDATE", "color": "🟢" },
        "TMS": { "emoji": "🎬", "tag": "TMS UPDATE", "color": "🟡" },
        "FANDOM": { "emoji": "🌐", "tag": "FANDOM NEWS", "color": "🟣" },
        "MAL": { "emoji": "📈", "tag": "MAL TRENDING", "color": "🔵" },
        "CR": { "emoji": "🟠", "tag": "CRUNCHYROLL", "color": "🟠" },
        "AC": { "emoji": "🏯", "tag": "ANIME CORNER", "color": "🔴" },
        "HONEY": { "emoji": "🍯", "tag": "HONEY'S ANIME", "color": "🟡" },
        "ANI": { "emoji": "🇮🇳", "tag": "ANIME INDIA", "color": "🟠" },
    }
    
    config = source_configs.get(item.source, {
        "emoji": "📰", "tag": "NEWS UPDATE", "color": "⚪"
    })
    
    title = html.escape(str(item.title or "No Title"), quote=False)
    summary = html.escape(str(item.summary_text or "No summary available"), quote=False)
    link = str(item.article_url or "")
    source_name = SOURCE_LABEL.get(item.source, item.source)
    
    components = [
        f"{config['emoji']} <b>{config['tag']}</b> {config['color']}",
        f"<b>{title}</b>",
        f"<i>{summary}</i>",
        f"📊 <b>Source:</b> {source_name}",
        f"📢 <b>Channel:</b> @Detective_Conan_News"
    ]
    
    if link and link.startswith('http'):
        safe_link = html.escape(link, quote=True)
        components.append(f"🔗 <a href='{safe_link}'>Read Full Article</a>")
    
    return "\n\n".join(components)

def send_to_telegram(item: NewsItem, slot, posted_set):
    """
    Send news to Telegram with proper channel routing and spam detection
    """
    # STRONG SPAM DETECTION
    if is_duplicate(item.title, item.article_url, posted_set):
        logging.info(f"🚫 Skipping duplicate: {item.title[:50]}")
        return False

    # RECORD ATTEMPT FIRST
    if not record_post(item.title, item.source, slot, posted_set, item.category, status='attempted'):
        logging.warning("⚠️ Failed to record attempt, skipping to avoid spam")
        return False
    
    # Get correct channel based on source
    target_chat_id = get_target_channel(item.source)
    
    # Format message based on channel type
    if item.source in WORLD_NEWS_SOURCES:
        msg = format_world_news_html(item)
    else:
        msg = format_anime_news(item)
    
    success = False
    
    # Try sending with photo first
    if item.image_url:
        try:
            sess = get_fresh_telegram_session()
            response = sess.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={
                    "chat_id": target_chat_id, 
                    "photo": item.image_url, 
                    "caption": msg, 
                    "parse_mode": "HTML"
                },
                timeout=20
            )
            sess.close()
            
            if response.status_code == 200:
                safe_log("info", f"Sent (Image) to {target_chat_id}: {item.title[:50]}")
                success = True
            elif response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 30))
                logging.warning(f"⏳ Rate limited. Sleeping {retry_after}s")
                time.sleep(retry_after)
            else:
                logging.warning(f"⚠️ Image send failed: {response.text}")
        except Exception as e:
            logging.warning(f"⚠️ Image send failed for {item.title}: {e}")

    # Fallback to text-only
    if not success:
        try:
            sess = get_fresh_telegram_session()
            response = sess.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": target_chat_id, 
                    "text": msg, 
                    "parse_mode": "HTML"
                },
                timeout=20
            )
            
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 30))
                time.sleep(retry_after)
                response = sess.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": target_chat_id, 
                        "text": msg, 
                        "parse_mode": "HTML"
                    },
                    timeout=20
                )
            sess.close()
            
            if response.status_code == 200:
                safe_log("info", f"Sent (Text) to {target_chat_id}: {item.title[:50]}")
                success = True
            else:
                logging.error(f"❌ Send failed: {response.text}")
                
        except Exception as e:
            logging.error(f"❌ Send attempt failed: {e}")
            
    if success:
        # UPDATE STATUS TO SENT
        update_post_status(item.title, 'sent')
        
        # Update in-memory set
        key = normalize_title(item.title)
        posted_set.add(key)
        return True
        
    return False

def send_admin_report(status, posts_sent, source_counts, error=None):
    """Send comprehensive report to admin"""
    if not ADMIN_ID: 
        return

    dt = now_local()
    date_str = str(dt.date())
    slot = dt.hour // 4
    
    # Calculate channel distribution
    anime_posts = sum(count for source, count in source_counts.items() if source in ANIME_NEWS_SOURCES)
    world_posts = sum(count for source, count in source_counts.items() if source in WORLD_NEWS_SOURCES)
    
    # Fetch stats
    daily_total = 0
    all_time_total = 0
    if supabase:
        try:
            d = supabase.table("daily_stats").select("posts_count").eq("date", date_str).limit(1).execute()
            if d.data: daily_total = d.data[0].get("posts_count", 0)
            
            b = supabase.table("bot_stats").select("total_posts_all_time").limit(1).execute()
            if b.data: all_time_total = b.data[0].get("total_posts_all_time", 0)
        except: 
            pass
        
    # Health warnings
    health_warnings = []
    if error:
        health_warnings.append(f"⚠️ <b>Error:</b> {html.escape(str(error)[:100], quote=False)}")
    
    for source, count in circuit_breaker.failure_counts.items():
        if count >= circuit_breaker.failure_threshold:
            health_warnings.append(f"⚠️ <b>Source Down:</b> {source} ({count} failures)")
    
    health_status = "✅ <b>All Systems Operational</b>" if not health_warnings else "\n".join(health_warnings)

    # Format source stats
    source_stats = "\n".join([f"• <b>{k}:</b> {v}" for k, v in source_counts.items()])
    if not source_stats: source_stats = "• No new posts this cycle"

    report_msg = (
        f"🤖 <b>News Bot Report</b>\n"
        f"📅 {date_str} | 🕒 Slot {slot} | ⏰ {dt.strftime('%I:%M %p IST')}\n\n"
        
        f"<b>📊 This Cycle</b>\n"
        f"• Status: {status.upper()}\n"
        f"• Posts Sent: {posts_sent}\n"
        f"• Anime News: {anime_posts}\n"
        f"• World News: {world_posts}\n\n"
        
        f"<b>📈 Today's Total: {daily_total}</b>\n"
        f"<b>🏆 All-Time: {all_time_total}</b>\n\n"
        
        f"<b>📰 Source Breakdown</b>\n{source_stats}\n\n"
        
        f"<b>🏥 System Health</b>\n{health_status}"
    )

    sess = get_fresh_telegram_session()
    try:
        sess.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", 
            json={
                "chat_id": ADMIN_ID, 
                "text": report_msg, 
                "parse_mode": "HTML"
            }, 
            timeout=20
        )
        safe_log("info", "Admin report sent")
    except Exception as e:
        logging.error(f"❌ Failed to send admin report: {e}")
    finally:
        sess.close()

# --- 9. MAIN EXECUTION ---
def run_once():
    """
    Single execution entry point for 4-hour schedule
    Implements: 
    - Strict date filtering (only today/yesterday)
    - Strong spam detection
    - Proper channel routing
    - Midnight reset handling
    """
    dt = now_local()
    date_obj = dt.date()
    slot = dt.hour // 4
    
    safe_log("info", f"\n{'='*60}")
    safe_log("info", f"STARTING NEWS BOT RUN")
    safe_log("info", f"Date: {date_obj} | Slot: {slot} | Time: {dt.strftime('%I:%M %p IST')}")
    safe_log("info", f"{'='*60}\n")
    
    # Check if we should reset (new day)
    if should_reset_daily_tracking():
        safe_log("info", "NEW DAY DETECTED - Resetting daily tracking")
    
    # Initialize
    initialize_bot_stats()
    ensure_daily_row(date_obj)
    
    # Load posted titles (last 7 days for strong deduplication)
    posted_set = load_posted_titles(date_obj)
    all_items = []
    
    # Fetch from all sources
    safe_log("info", "\nFETCHING NEWS FROM SOURCES...")
    
    # ANN
    if circuit_breaker.can_call("ANN"):
        logging.info("  → Fetching ANN...")
        ann_items = fetch_generic(BASE_URL, "ANN", parse_ann)
        all_items.extend(ann_items)
        logging.info(f"    ✓ Found {len(ann_items)} items")
    
    # ANN DC
    if circuit_breaker.can_call("ANN_DC"):
        logging.info("  → Fetching ANN DC...")
        ann_dc_items = fetch_generic(BASE_URL_ANN_DC, "ANN_DC", parse_ann_dc)
        all_items.extend(ann_dc_items)
        logging.info(f"    ✓ Found {len(ann_dc_items)} items")

    # RSS FEEDS (Anime + World News)
    for code, url in RSS_FEEDS.items():
        if circuit_breaker.can_call(code):
            logging.info(f"  → Fetching {code}...")
            items = fetch_rss(url, code, lambda s: parse_rss_robust(s, code))
            all_items.extend(items)
            logging.info(f"    ✓ Found {len(items)} items")

    # MAL (Jikan)
    if circuit_breaker.can_call("MAL"):
        logging.info("  → Fetching MAL...")
        mal_items = fetch_jikan_safe()
        all_items.extend(mal_items)
        logging.info(f"    ✓ Found {len(mal_items)} items")

    # Enrich data
    safe_log("info", f"\nEnriching {len(all_items)} items with details...")
    fetch_details_concurrently(all_items)

    # Post to Telegram
    safe_log("info", "\nPOSTING TO TELEGRAM...")
    sent_count = 0
    source_counts = defaultdict(int)
    
    for item in all_items:
        if not item.title: 
            continue
        
        # Verify item is from today or yesterday
        if item.publish_date and not is_today_or_yesterday(item.publish_date):
            logging.debug(f"⏭️ Skipping old news: {item.title[:50]}")
            continue
        
        if send_to_telegram(item, slot, posted_set):
            sent_count += 1
            source_counts[item.source] += 1
            time.sleep(1.0)  # Rate limit protection

    # Report
    safe_log("info", f"\n{'='*60}")
    safe_log("info", f"RUN COMPLETE - Sent: {sent_count} posts")
    safe_log("info", f"{'='*60}\n")
    
    send_admin_report("success", sent_count, source_counts)

if __name__ == "__main__":
    try:
        run_once()
    except KeyboardInterrupt:
        safe_log("info", "Bot stopped by user")
    except Exception as e:
        safe_log("error", f"FATAL ERROR: {e}", exc_info=True)
        try:
            send_admin_report("failed", 0, {}, error=str(e))
        except: 
            pass
        exit(1)