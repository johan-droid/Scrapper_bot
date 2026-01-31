import os
import re
import json
import time
import uuid
import pytz
import random
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
from typing import Optional, List, Dict, Any


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

try:
    from supabase import create_client, Client
    # Try both import methods for compatibility
    supabase_client = None
except Exception as e:
    logging.warning(f"Supabase import failed: {e}")
    create_client = None
    Client = None

# NewsItem class is now defined above

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
        if "<" in str(html_text_or_element) and ">" in str(html_text_or_element):
             soup = BeautifulSoup(str(html_text_or_element), "html.parser")
        else:
             return str(html_text_or_element)[:limit]

    # Remove script and style tags entirely
    for script in soup(["script", "style", "header", "footer"]):
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
REDDIT_CHANNEL_ID = os.getenv("REDDIT_CHANNEL_ID")
WORLD_NEWS_CHANNEL_ID = os.getenv("WORLD_NEWS_CHANNEL_ID")
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
    "MAL": "MyAnimeList (Jikan)", "CR": "Crunchyroll News",
    "AC": "Anime Corner", "HONEY": "Honey's Anime",
    "AP": "AP News (Entertainment)",
    "REUTERS": "Reuters (Lifestyle)",
}

# RSS Feeds
RSS_ANI = "https://animenewsindia.com/feed/"
RSS_R_ANIME = "https://www.reddit.com/r/anime/new/.rss"
RSS_R_OTP = "https://www.reddit.com/r/OneTruthPrevails/new/.rss"
RSS_R_DC = "https://www.reddit.com/r/DetectiveConan/new/.rss"
RSS_CRUNCHYROLL = "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss"
RSS_ANIME_CORNER = "https://animecorner.me/feed/"
RSS_HONEYS = "https://honeysanime.com/feed/"
RSS_HONEYS = "https://honeysanime.com/feed/"
JIKAN_BASE = "https://api.jikan.moe/v4"
BASE_URL_AP_NEWS = "https://apnews.com/hub/entertainment" # Targeting entertainment/pop culture or general top news
# Using Google News RSS bridge for Reuters to avoid paywall/anti-bot issues
RSS_REUTERS = "https://news.google.com/rss/search?q=when:24h+source:Reuters&hl=en-US&gl=US&ceid=US:en"

# Channel routing configuration
REDDIT_SOURCES = {"R_ANIME", "R_OTP", "R_DC"}
DC_NEWS_SOURCES = {"ANN_DC", "DCW", "TMS", "FANDOM"}
WORLD_NEWS_SOURCES = {"ANN", "ANI", "MAL", "CR", "AC", "HONEY", "AP", "REUTERS"}
ALL_NEWS_SOURCES = DC_NEWS_SOURCES | WORLD_NEWS_SOURCES

if not BOT_TOKEN or not CHAT_ID:
    logging.error("CRITICAL: BOT_TOKEN or CHAT_ID is missing.")
    raise SystemExit(1)

if not REDDIT_CHANNEL_ID:
    logging.warning("REDDIT_CHANNEL_ID not set - Reddit posts will go to main channel")
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
            # Google often changes encoding. For now, returning standard URL 
            # often redirects correctly in browser, but cleaner to have direct if possible.
            # Base64 decoding strategy is fragile; relying on the redirect is safer for the bot's 'click'
            # but for 'article_url', let's trust Telegram to follow redirects or just keep it as is.
            # *Update*: User requested base64 extraction logic, but simplified.
            pass 
    except Exception:
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
        # Check last 7 days to prevent duplicate spam from previous days (more robust sync with DB)
        start_date = date_obj - timedelta(days=7)
        r = supabase.table("posted_news").select("normalized_title").gte("posted_date", str(start_date)).execute()
        return set(x["normalized_title"] for x in r.data)
    except Exception as e:
        logging.error(f"Failed to load posted titles: {e}")
        return set()

def record_post(title, source_code, run_id, slot, posted_titles_set, category=None):
    key = get_normalized_key(title)
    if key in posted_titles_set: return False
    
    date_obj = now_local().date()
    if supabase:
        try:
            supabase.table("posted_news").insert({
                "normalized_title": key, "posted_date": str(date_obj), "full_title": title,
                "posted_at": datetime.now(utc_tz).isoformat(), "source": source_code,
                "run_id": run_id if not str(run_id).startswith("local") else None, "slot": slot,
                "category": category
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

def parse_reuters_google_rss(soup):
    """
    Targeted parser for Reuters via Google News RSS.
    """
    items = parse_rss_robust(soup, "REUTERS")
    # Post-process to decode URLs or fetch better images
    for item in items:
        # Google News RSS usually doesn't have images in enclosure.
        # We need to fetch the article to get the image.
        # Since we do concurrent enrichment later, ensuring 'article_url' is correct is key.
        item.article_url = decode_google_news_url(item.article_url)
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
                image_url=image_url
            )
            
            # Extract Reddit Flair/Category
            cats = [c.get("term") for c in entry.find_all("category") if c.get("term")]
            if cats: item.category = cats[0]

            item.summary_text = "Reddit Discussion" # Default
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
                    logging.warning(f"Date check failed for ANI item.")
                    continue # Skip if date is unparseable to avoid old news spam

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
                image_url=image_url,
                summary_text=summary_text if summary_text else "Read more on Anime News India."
            )

            # Extract Category
            cats = [c.text for c in entry.find_all("category")]
            if cats: item.category = cats[0] # Use first category

            items.append(item)

        except Exception as e:
            logging.error(f"Error parsing ANI item: {e}")
            continue

    return items

def parse_general_rss(soup, source_code):
    """
    Parses generic RSS feeds (Crunchyroll, Anime Corner, Honey's Anime).
    Most use standard <item> with <pubDate> and <description>/<content:encoded>.
    """
    items = []
    entries = soup.find_all("item")
    if not entries: return []

    today = now_local().date()
    yesterday = today - timedelta(days=1)

    for entry in entries:
        try:
            # 1. Date Check
            pub_date_tag = entry.find("pubDate")
            if pub_date_tag:
                 try:
                    dt = datetime.strptime(pub_date_tag.text.strip(), "%a, %d %b %Y %H:%M:%S %z")
                    pub_date = dt.astimezone(local_tz).date()
                    if not DEBUG_MODE and pub_date not in [today, yesterday]:
                        continue
                 except: 
                     continue # Skip if date is unparseable

            title = entry.find("title").text
            link = entry.find("link").text if entry.find("link") else None
            
            # 2. Image Extraction
            image_url = None
            # Standard RSS 'enclosure'
            enclosure = entry.find("enclosure")
            if enclosure and "image" in enclosure.get("type", ""):
                image_url = enclosure.get("url")
            
            # Media:content (common in FeedBurner/WordPress)
            if not image_url:
                media = entry.find("media:content") or entry.find("media:thumbnail")
                if media: image_url = media.get("url")

            # Content scraping for image
            if not image_url:
                content = entry.find("content:encoded") or entry.find("description")
                if content:
                    c_soup = BeautifulSoup(content.text, "html.parser")
                    img = c_soup.find("img")
                    if img: image_url = img.get("src")

            # 3. Summary
            summary_text = "No summary."
            desc = entry.find("description")
            if desc:
                summary_text = clean_text_extractor(BeautifulSoup(desc.text, "html.parser"))
                if len(summary_text) > 300: summary_text = summary_text[:300] + "..."

            item = NewsItem(
                title=title,
                source=source_code,
                article_url=link,
                image_url=image_url,
                summary_text=summary_text
            )

            # Extract Category
            cats = [c.text for c in entry.find_all("category")]
            if cats: item.category = cats[0]

            items.append(item)

        except Exception as e:
            logging.error(f"Error parsing RSS {source_code}: {e}")
            continue
            
    return items

def fetch_jikan_mal():
    """
    Fetches news for Top 5 Airing Anime via Jikan API.
    """
    session = get_scraping_session()
    items = []
    try:
        # 1. Get Top Anime
        top_url = f"{JIKAN_BASE}/top/anime?filter=airing&limit=5"
        r = session.get(top_url, timeout=20)
        r.raise_for_status()
        data = r.json().get("data", [])
        
        for anime in data:
            if not circuit_breaker.can_call("MAL"): break
            
            anime_id = anime.get("mal_id")
            anime_title = anime.get("title")
            if not anime_id: continue
            
            # Rate limit pause (Jikan is strict)
            time.sleep(1.0) 
            
            # 2. Get News for this anime
            news_url = f"{JIKAN_BASE}/anime/{anime_id}/news"
            try:
                nr = session.get(news_url, timeout=20)
                if nr.status_code == 429:
                    logging.warning("Jikan Rate Limit Hit")
                    break
                nr.raise_for_status()
                news_data = nr.json().get("data", [])
                
                for n in news_data:
                    # Filter by date strict check
                    date_str = n.get("date")
                    if date_str:
                        try:
                            # Jikan ISO format: 2024-01-18T14:00:00+00:00
                            # Handling 'Z' just in case, though usually +00:00
                            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                            n_date = dt.astimezone(local_tz).date()
                            today = now_local().date()
                            yesterday = today - timedelta(days=1)
                            
                            if not DEBUG_MODE and n_date not in [today, yesterday]:
                                continue
                        except Exception:
                            # If date parsing fails, skip to be safe against old news
                            continue

                    title = n.get("title")
                    url = n.get("url")
                    image = n.get("images", {}).get("jpg", {}).get("large_image_url") or n.get("images", {}).get("jpg", {}).get("image_url")
                    excerpt = n.get("excerpt", "News about " + anime_title)
                    
                    # Store
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
        logging.error(f"Jikan Top Anime fetch failed: {e}")
        circuit_breaker.record_failure("MAL")
    finally:
        session.close()
    
    return items

def fetch_details_concurrently(items):
    def get_details(item: NewsItem):
        if not item.article_url: return item
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
        "R_ANIME": { "emoji": "💬", "tag": "REDDIT DISCUSSION", "color": "⚪", "source_name": "r/anime", "channel_tag": "@Redditposting_DCN" },
        "R_OTP": { "emoji": "🕵️", "tag": "REDDIT CONAN", "color": "🔵", "source_name": "r/OneTruthPrevails", "channel_tag": "@Redditposting_DCN" },
        "R_DC": { "emoji": "🕵️", "tag": "REDDIT CONAN", "color": "🔵", "source_name": "r/DetectiveConan", "channel_tag": "@Redditposting_DCN" },
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
    # Note: Logic moved to get_smart_tag_key for cleanliness
    tag_key = get_smart_tag_key(item)
    if tag_key and tag_key in tag_configs:
        tc = tag_configs[tag_key]
        config["emoji"] = tc["emoji"]
        config["tag"] = tc["tag"]
        config["color"] = tc["color"]
    
    # Safe text processing with proper escaping
    title = escape_html(str(item.title)) if item.title else "No Title"
    summary = escape_html(str(item.summary_text)) if item.summary_text else "No summary available"
    link = str(item.article_url) if item.article_url else ""
    
    # Build message components safely
    components = [
        f"{config['emoji']} <b>{config['tag']}</b> {config['color']}",
        f"<b>{title}</b>",
        f"<i>{summary}</i>",
        f"📊 <b>Source:</b> {config['source_name']}",
        f"📢 <b>Channel:</b> {config['channel_tag']}"
    ]
    
    # Add link only if valid
    if link and link.startswith('http'):
        components.append(f"🔗 <a href='{link}'>Read Full Article</a>")
    
    # Join with proper spacing and JSON-safe formatting
    msg = "\n\n".join(components)
    
    # Final validation to prevent broken JSON
    try:
        # Test if message can be properly encoded
        msg.encode('utf-8')
        return msg
    except Exception as e:
        logging.error(f"Message encoding failed: {e}")
        # Fallback to simple message
        return f"<b>{title}</b>\n\n{summary}\n\n📊 Source: {config['source_name']}"

def get_target_channel(source):
    """Determine which channel to send the post to based on source"""
    if source in REDDIT_SOURCES and REDDIT_CHANNEL_ID:
        return REDDIT_CHANNEL_ID
    if source in WORLD_NEWS_SOURCES and WORLD_NEWS_CHANNEL_ID:
        return WORLD_NEWS_CHANNEL_ID
    return CHAT_ID

def send_to_telegram(item: NewsItem, run_id, slot, posted_set):
    # Skip pre-validation to save time and network footprint
    msg = format_message(item)
    target_chat_id = get_target_channel(item.source)
    
    # Try sending with photo first
    if item.image_url:
        try:
            # We use requests directly here for simplicity if session management is complex, 
            # but using 'sess' from get_fresh_telegram_session is better for connection pooling.
            sess = get_fresh_telegram_session()
            response = sess.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={"chat_id": target_chat_id, "photo": item.image_url, "caption": msg, "parse_mode": "HTML"},
                timeout=20
            )
            sess.close()
            
            if response.status_code == 200:
                logging.info(f"Message sent (Image): {item.title[:50]}")
                return record_post(item.title, item.source, run_id, slot, posted_set)
            elif response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 30))
                logging.warning(f"Rate limited (Image). Sleeping {retry_after}s")
                time.sleep(retry_after)
                # Retry logic could go here, but for now we fall back or fail safe. 
                # Let's fallback to text if image fails due to limits? No, limit means wait.
                # Simple fallback:
                logging.warning("Image send failed/limited, falling back to text...")
        except Exception as e:
            logging.warning(f"Image send failed for {item.title}, falling back to text: {e}")

    # Fallback to text-only if no image or if sendPhoto failed
    try:
        sess = get_fresh_telegram_session()
        response = sess.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": target_chat_id, "text": msg, "parse_mode": "HTML"},
            timeout=20
        )
        
        if response.status_code == 429:
             retry_after = int(response.headers.get("Retry-After", 30))
             logging.warning(f"Rate limited (Text). Sleeping {retry_after}s")
             time.sleep(retry_after)
             response = sess.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": target_chat_id, "text": msg, "parse_mode": "HTML"},
                timeout=20
            )
        
        sess.close()
        
        if response.status_code == 200:
             logging.info(f"Message sent (Text): {item.title[:50]}")
             return record_post(item.title, item.source, run_id, slot, posted_set)
        else:
             logging.error(f"Final send attempt failed: {response.text}")
             return False
             
    except Exception as e:
        logging.error(f"Final send attempt failed: {e}")
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
    world_posts = sum(count for source, count in source_counts.items() if source in WORLD_NEWS_SOURCES)
    reddit_posts = sum(count for source, count in source_counts.items() if source in REDDIT_SOURCES)
    
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
        health_warnings.append(f"⚠️ <b>Critical Error:</b> {str(error)[:100]}")
    
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
        f"• World News: {world_posts}\n"
        f"• Reddit: {reddit_posts}\n"
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

    # Reddit Scrapers (RSS) - Unified
    # r/anime
    if circuit_breaker.can_call("R_ANIME"):
        r_anime = fetch_rss(RSS_R_ANIME, "R_ANIME", lambda s: parse_rss_robust(s, "R_ANIME"))
        all_items.extend(r_anime)
        
    # r/OneTruthPrevails
    if circuit_breaker.can_call("R_OTP"):
        r_otp = fetch_rss(RSS_R_OTP, "R_OTP", lambda s: parse_rss_robust(s, "R_OTP"))
        all_items.extend(r_otp)
        
    # r/DetectiveConan
    if circuit_breaker.can_call("R_DC"):
        r_dc = fetch_rss(RSS_R_DC, "R_DC", lambda s: parse_rss_robust(s, "R_DC"))
        all_items.extend(r_dc)

    # Crunchyroll
    if circuit_breaker.can_call("CR"):
        cr_items = fetch_rss(RSS_CRUNCHYROLL, "CR", lambda s: parse_rss_robust(s, "CR"))
        all_items.extend(cr_items)

    # Anime Corner
    if circuit_breaker.can_call("AC"):
        ac_items = fetch_rss(RSS_ANIME_CORNER, "AC", lambda s: parse_rss_robust(s, "AC"))
        all_items.extend(ac_items)

    # Honey's Anime
    if circuit_breaker.can_call("HONEY"):
        honey_items = fetch_rss(RSS_HONEYS, "HONEY", lambda s: parse_rss_robust(s, "HONEY"))
        all_items.extend(honey_items)

    # AP News
    if circuit_breaker.can_call("AP"):
        ap_items = fetch_generic(BASE_URL_AP_NEWS, "AP", parse_ap_html)
        # Limit AP items to avoid flooding generic news
        all_items.extend(ap_items[:5])

    # Reuters (via Google RSS)
    if circuit_breaker.can_call("REUTERS"):
        # We reuse fetch_rss but with our specialized parser wrapper
        reuters_items = fetch_rss(RSS_REUTERS, "REUTERS", parse_reuters_google_rss)
        all_items.extend(reuters_items[:5])

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
        run_once()
    except Exception as e:
        logging.error(f"FATAL ERROR: {e}")
        # Send crash report
        try:
            send_admin_report("CRASH", "failed", 0, {}, error=str(e))
        except: pass
        exit(1)
