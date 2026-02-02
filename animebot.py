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
        full_content: Optional[str] = None,
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
        self.full_content = full_content
        self.telegraph_url = None
        
        for key, value in kwargs.items():
            setattr(self, key, value)


class TelegraphClient:
    """Client for creating Telegraph articles"""
    
    def __init__(self, access_token=None):
        self.base_url = "https://api.telegra.ph"
        self.access_token = access_token
        self.session = requests.Session()
        
        # Create account if no token provided
        if not self.access_token:
            self.create_account()
    
    def create_account(self):
        """Create a Telegraph account"""
        try:
            response = self.session.post(
                f"{self.base_url}/createAccount",
                data={
                    "short_name": "News Bot",
                    "author_name": "Anime & World News Bot",
                    "author_url": "https://t.me/Detective_Conan_News"
                },
                timeout=10
            )
            data = response.json()
            if data.get('ok'):
                self.access_token = data['result']['access_token']
                logging.info("[OK] Telegraph account created")
                return True
            else:
                logging.error(f"[ERROR] Telegraph account creation failed: {data}")
                return False
        except Exception as e:
            logging.error(f"[ERROR] Telegraph account error: {e}")
            return False
    
    def create_page(self, title, content, author_name=None, author_url=None, return_content=False):
        """
        Create a Telegraph page
        
        Args:
            title: Page title
            content: List of Node objects or HTML string
            author_name: Author name
            author_url: Author URL
            return_content: Whether to return content in response
        
        Returns:
            dict with 'ok' status and 'result' containing page data
        """
        if not self.access_token:
            logging.error("[ERROR] No Telegraph access token")
            return None
        
        try:
            # Convert HTML to Telegraph nodes if string provided
            if isinstance(content, str):
                content = self._html_to_nodes(content)
            
            data = {
                "access_token": self.access_token,
                "title": title[:256],  # Telegraph title limit
                "content": json.dumps(content),
                "return_content": return_content
            }
            
            if author_name:
                data["author_name"] = author_name[:128]
            if author_url:
                data["author_url"] = author_url
            
            response = self.session.post(
                f"{self.base_url}/createPage",
                data=data,
                timeout=15
            )
            
            result = response.json()
            if result.get('ok'):
                logging.info(f"[OK] Telegraph page created: {result['result']['url']}")
                return result['result']
            else:
                logging.error(f"[ERROR] Telegraph page creation failed: {result}")
                return None
                
        except Exception as e:
            logging.error(f"[ERROR] Telegraph page creation error: {e}")
            return None
    
    def _html_to_nodes(self, html_content):
        """Convert HTML to Telegraph DOM nodes"""
        soup = BeautifulSoup(html_content, 'html.parser')
        nodes = []
        
        for element in soup.children:
            node = self._element_to_node(element)
            if node:
                nodes.append(node)
        
        return nodes
    
    def _element_to_node(self, element):
        """Convert BeautifulSoup element to Telegraph node"""
        if isinstance(element, str):
            text = element.strip()
            return text if text else None
        
        if element.name is None:
            return None
        
        # Handle different HTML tags
        tag_map = {
            'p': 'p',
            'b': 'strong', 'strong': 'strong',
            'i': 'em', 'em': 'em',
            'a': 'a',
            'h1': 'h3', 'h2': 'h3', 'h3': 'h3', 'h4': 'h4',
            'blockquote': 'blockquote',
            'pre': 'pre',
            'code': 'code',
            'br': 'br',
            'img': 'img'
        }
        
        tag = tag_map.get(element.name)
        if not tag:
            # For unsupported tags, extract text
            return element.get_text(strip=True) or None
        
        # Build node structure
        node = {'tag': tag}
        
        # Handle attributes
        if tag == 'a' and element.get('href'):
            node['attrs'] = {'href': element['href']}
        elif tag == 'img' and element.get('src'):
            node['attrs'] = {'src': element['src']}
        
        # Handle children
        if tag not in ['br', 'img']:
            children = []
            for child in element.children:
                child_node = self._element_to_node(child)
                if child_node:
                    children.append(child_node)
            
            if children:
                node['children'] = children
        
        return node


# Load env vars
env_path = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(env_path, override=True)

# UTF-8 handling
import sys
os.environ['PYTHONIOENCODING'] = 'utf-8'

if sys.platform == "win32":
    import codecs
    try:
        import subprocess
        subprocess.run(['chcp', '65001'], shell=True, capture_output=True)
    except:
        pass
    
    try:
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    except (AttributeError, OSError):
        pass

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, OSError):
    pass

# Logging
class UTF8StreamHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
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

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WORLD_NEWS_CHANNEL_ID = os.getenv("WORLD_NEWS_CHANNEL_ID")
ANIME_NEWS_CHANNEL_ID = os.getenv("ANIME_NEWS_CHANNEL_ID")
ADMIN_ID = os.getenv("ADMIN_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAPH_TOKEN = os.getenv("TELEGRAPH_TOKEN")  # Optional: reuse existing token

# Initialize Telegraph client
telegraph = TelegraphClient(access_token=TELEGRAPH_TOKEN)

# Supabase connection
try:
    from supabase import create_client, Client
except ImportError:
    logging.warning("Supabase library not found. Running in memory-only mode.")
    create_client = None
    Client = None

supabase = None
if SUPABASE_URL and SUPABASE_KEY and create_client:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logging.info("[OK] Supabase connected successfully")
    except Exception as e:
        logging.warning(f"Supabase connection failed: {e}")
        supabase = None

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

# Configuration
BASE_URL = "https://www.animenewsnetwork.com"
DEBUG_MODE = False

SOURCE_LABEL = {
    "ANN": "Anime News Network", "ANN_DC": "ANN (Detective Conan)",
    "DCW": "Detective Conan Wiki", "TMS": "TMS Entertainment", "FANDOM": "Fandom Wiki",
    "ANI": "Anime News India", "MAL": "MyAnimeList", "CR": "Crunchyroll News",
    "AC": "Anime Corner", "HONEY": "Honey's Anime",
    "BBC": "BBC World News", "ALJ": "Al Jazeera", "CNN": "CNN World", "GUARD": "The Guardian",
    "NPR": "NPR International", "DW": "Deutsche Welle", "F24": "France 24", "CBC": "CBC World",
    "NL": "NewsLaundry", "WIRE": "The Wire", "SCROLL": "Scroll.in",
    "PRINT": "The Print", "INTER": "The Intercept", "PRO": "ProPublica", "REUTERS": "Reuters"
}

# RSS Feeds
RSS_FEEDS = {
    "ANI": "https://animenewsindia.com/feed/",
    "CR": "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss",
    "AC": "https://animecorner.me/feed/",
    "HONEY": "https://honeysanime.com/feed/",
    "BBC": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "ALJ": "https://www.aljazeera.com/xml/rss/all.xml",
    "CNN": "http://rss.cnn.com/rss/edition_world.rss",
    "GUARD": "https://www.theguardian.com/world/rss",
    "NPR": "https://feeds.npr.org/1001/rss.xml",
    "DW": "https://rss.dw.com/xml/rss-en-all",
    "F24": "https://www.france24.com/en/rss",
    "CBC": "https://www.cbc.ca/cmlink/rss-world",
    "NL": "https://www.newslaundry.com/feed",
    "WIRE": "https://thewire.in/feed",
    "SCROLL": "https://scroll.in/feed",
    "PRINT": "https://theprint.in/feed",
    "INTER": "https://theintercept.com/feed/?lang=en",
    "PRO": "https://www.propublica.org/feeds/propublica/main",
}

# Channel routing
ANIME_NEWS_SOURCES = {"ANN", "ANN_DC", "DCW", "TMS", "FANDOM", "ANI", "MAL", "CR", "AC", "HONEY"}
WORLD_NEWS_SOURCES = {
    "BBC", "ALJ", "CNN", "GUARD", "NPR", "DW", "F24", "CBC",
    "NL", "WIRE", "SCROLL", "PRINT", "INTER", "PRO", "REUTERS"
}

if not BOT_TOKEN:
    logging.error("CRITICAL: BOT_TOKEN is missing.")
    raise SystemExit(1)

if not ANIME_NEWS_CHANNEL_ID and not CHAT_ID:
    logging.error("CRITICAL: Either ANIME_NEWS_CHANNEL_ID or CHAT_ID must be set.")
    raise SystemExit(1)

utc_tz = pytz.utc
local_tz = pytz.timezone("Asia/Kolkata")

# Session helpers
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

def get_scraping_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=3, backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
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

# Time helpers
def now_local(): 
    return datetime.now(local_tz)

def is_today_or_yesterday(dt_to_check):
    if not dt_to_check:
        return False
    today = now_local().date()
    yesterday = today - timedelta(days=1)
    check_date = dt_to_check.date() if isinstance(dt_to_check, datetime) else dt_to_check
    return check_date in [today, yesterday]

def should_reset_daily_tracking():
    now = now_local()
    if now.hour == 0 and now.minute < 15:
        return True
    return False

# Text helpers
def safe_log(level, message, *args, **kwargs):
    try:
        if not isinstance(message, str):
            message = str(message)
        message = message.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
        
        emoji_map = {
            '✅': '[OK]', '❌': '[ERROR]', '⚠️': '[WARN]', '🚫': '[BLOCKED]',
            '📍': '[ROUTE]', '🔄': '[RESET]', '📡': '[FETCH]', '📤': '[SEND]',
            '🔍': '[ENRICH]', '🚀': '[START]', '📅': '[DATE]', '🕒': '[SLOT]',
            '⏰': '[TIME]', '📚': '[LOAD]', '⏭️': '[SKIP]', '⏳': '[WAIT]',
            '🤖': '[BOT]', '📊': '[STATS]', '📈': '[TOTAL]', '🏆': '[ALL]',
            '📰': '[SOURCE]', '🏥': '[HEALTH]', '🌍': '[WORLD]', '🕵️': '[CONAN]'
        }
        
        for emoji, text in emoji_map.items():
            message = message.replace(emoji, text)
        
        getattr(logging, level.lower())(message, *args, **kwargs)
    except Exception:
        try:
            print(f"[{level.upper()}] {message}")
        except:
            print(f"[{level.upper()}] <encoding error>")

def clean_text_extractor(html_text_or_element, limit=350):
    if not html_text_or_element: 
        return "No summary available."

    if hasattr(html_text_or_element, "get_text"):
        soup = html_text_or_element
    else:
        raw_str = str(html_text_or_element)
        if "<" in raw_str and ">" in raw_str:
             soup = BeautifulSoup(raw_str, "html.parser")
        else:
             return raw_str[:limit]

    for script in soup(["script", "style", "header", "footer"]):
        script.decompose()
        
    text = soup.get_text(separator=" ")
    text = re.sub(r'http\S+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = text.replace('â€™', "'").replace('â€"', "—").replace('&nbsp;', ' ')
    
    if len(text) > limit:
        return text[:limit-3].strip() + "..."
    return text

def extract_full_article_content(url, source):
    """
    Extract full article content for Telegraph posting
    Returns dict with 'text', 'images', and 'html'
    """
    session = get_scraping_session()
    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove unwanted elements
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe', 'ads']):
            tag.decompose()
        
        # Source-specific selectors
        content_selectors = {
            'BBC': ['.article__body-content', '.story-body__inner', 'article'],
            'GUARD': ['.article-body-commercial-selector', '.content__article-body', 'article'],
            'CNN': ['.article__content', '.zn-body__paragraph', 'article'],
            'ALJ': ['.article-p-wrapper', '.wysiwyg', 'article'],
            'NPR': ['#storytext', '.storytext', 'article'],
            'REUTERS': ['.article-body__content__', '.StandardArticleBody_body', 'article'],
            'default': ['article', '.post-content', '.entry-content', '.article-content', '.story-content']
        }
        
        selectors = content_selectors.get(source, content_selectors['default'])
        
        content_div = None
        for selector in selectors:
            content_div = soup.select_one(selector)
            if content_div:
                break
        
        if not content_div:
            content_div = soup.find('body')
        
        if not content_div:
            return None
        
        # Extract images
        images = []
        for img in content_div.find_all('img', limit=5):
            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
            if src and not any(x in src for x in ['logo', 'icon', 'avatar', 'ads', '1x1']):
                if not src.startswith('http'):
                    from urllib.parse import urljoin
                    src = urljoin(url, src)
                images.append(src)
        
        # Extract paragraphs with proper formatting
        paragraphs = []
        for p in content_div.find_all(['p', 'h2', 'h3', 'blockquote'], recursive=True):
            text = p.get_text(strip=True)
            if len(text) > 20 and not any(x in text.lower() for x in ['cookie', 'subscribe', 'newsletter', 'advertisement']):
                if p.name in ['h2', 'h3']:
                    paragraphs.append(f'<h3>{text}</h3>')
                elif p.name == 'blockquote':
                    paragraphs.append(f'<blockquote>{text}</blockquote>')
                else:
                    paragraphs.append(f'<p>{text}</p>')
        
        # Build HTML content
        html_content = '\n'.join(paragraphs)
        
        return {
            'html': html_content,
            'text': clean_text_extractor(content_div, limit=5000),
            'images': images
        }
        
    except Exception as e:
        logging.debug(f"Content extraction failed for {url}: {e}")
        return None
    finally:
        session.close()

# Database helpers
def normalize_title(title):
    prefixes = ["BREAKING:", "NEW:", "UPDATE:", "DC Wiki Update: ", "TMS News: ", 
                "Fandom Wiki Update: ", "ANN DC News: ", "ANN:", "Reuters:", "BBC:"]
    t = title
    for p in prefixes:
        if t.upper().startswith(p.upper()):
            t = t[len(p):].strip()
    
    t = re.sub(r'[^\w\s]', '', t)
    return t.lower().strip()

def is_duplicate(title, url, posted_titles_set, date_check=True):
    norm_title = normalize_title(title)
    
    if norm_title in posted_titles_set:
        safe_log("info", f"DUPLICATE (Exact): {title[:50]}")
        return True
    
    for existing in posted_titles_set:
        ratio = difflib.SequenceMatcher(None, norm_title, existing).ratio()
        if ratio > 0.85:
            safe_log("info", f"DUPLICATE (Fuzzy {ratio:.2%}): {title[:50]}")
            return True
    
    if supabase:
        try:
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
    if not supabase: return
    try:
        supabase.rpc('increment_daily_stats', {'row_date': str(date_obj)}).execute()
        supabase.rpc('increment_bot_stats').execute()
    except Exception as e:
        logging.error(f"Atomic stats update failed: {e}")

def load_posted_titles(date_obj):
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

def record_post(title, source_code, article_url, slot, posted_titles_set, category=None, status='sent', telegraph_url=None):
    key = normalize_title(title)
    date_obj = now_local().date()
    
    if source_code in WORLD_NEWS_SOURCES:
        channel_type = 'world'
    else:
        channel_type = 'anime'
    
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
                "channel_type": channel_type,
                "article_url": article_url,
                "telegraph_url": telegraph_url
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
        if status == 'sent':
            posted_titles_set.add(key)
        return True

def update_post_status(title, status):
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

# RSS parsing
def parse_rss_robust(soup, source_code):
    items = []
    entries = soup.find_all(['item', 'entry'])
    
    today = now_local().date()
    yesterday = today - timedelta(days=1)

    for entry in entries:
        try:
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
                    
                    if not DEBUG_MODE and pub_date not in [today, yesterday]:
                        continue
                except: 
                    continue
            
            title_tag = entry.find(['title', 'dc:title'])
            if not title_tag:
                continue
            
            # Link extraction
            link_str = None
            link_tag = entry.find('link')
            if link_tag:
                if link_tag.get('href'):
                    link_str = link_tag.get('href')
                elif link_tag.text and link_tag.text.strip():
                    link_str = link_tag.text.strip()
            
            if not link_str:
                guid_tag = entry.find('guid')
                if guid_tag:
                    guid_text = guid_tag.text.strip()
                    if guid_text.startswith('http'):
                        link_str = guid_text
            
            if not link_str:
                id_tag = entry.find('id')
                if id_tag:
                    id_text = id_tag.text.strip()
                    if id_text.startswith('http'):
                        link_str = id_text
            
            if not link_str or not link_str.startswith('http'):
                continue

            # Image extraction
            image_url = None
            media = entry.find('media:content')
            if media and media.get('url'):
                image_url = media.get('url')
            
            if not image_url:
                enclosure = entry.find('enclosure')
                if enclosure and enclosure.get('url'):
                    enc_type = enclosure.get('type', '')
                    if 'image' in enc_type or not enc_type:
                        image_url = enclosure.get('url')
            
            if not image_url:
                thumb = entry.find('media:thumbnail')
                if thumb and thumb.get('url'):
                    image_url = thumb.get('url')
            
            # Summary
            summary_text = ""
            description = entry.find(['description', 'summary', 'content', 'content:encoded'])
            if description:
                summary_text = clean_text_extractor(description)
            
            if not summary_text or len(summary_text) < 20:
                summary_text = f"Read more about: {title_tag.text.strip()}"

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
        except Exception as e:
            logging.debug(f"Failed to parse RSS entry: {e}")
            continue
    
    return items

def fetch_rss(url, source_name, parser_func):
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

# Telegraph posting
def create_telegraph_article(item: NewsItem):
    """
    Create a Telegraph article from NewsItem
    Returns Telegraph URL or None
    """
    try:
        # Extract full content
        full_content = extract_full_article_content(item.article_url, item.source)
        
        if not full_content or not full_content['html']:
            logging.debug(f"No content extracted for {item.title}")
            return None
        
        # Build Telegraph content
        telegraph_html = []
        
        # Add featured image if available
        main_image = item.image_url or (full_content['images'][0] if full_content['images'] else None)
        if main_image:
            telegraph_html.append(f'<img src="{main_image}">')
        
        # Add content
        telegraph_html.append(full_content['html'])
        
        # Add source attribution at the end
        source_name = SOURCE_LABEL.get(item.source, item.source)
        telegraph_html.append('<hr>')
        telegraph_html.append(f'<p><strong>📍 Source:</strong> {source_name}</p>')
        
        if item.category:
            telegraph_html.append(f'<p><strong>🏷️ Category:</strong> {item.category}</p>')
        
        if item.publish_date:
            dt_str = item.publish_date.strftime("%B %d, %Y at %I:%M %p IST")
            telegraph_html.append(f'<p><strong>📅 Published:</strong> {dt_str}</p>')
        
        telegraph_html.append(f'<p><a href="{item.article_url}">📍 Read Original Article</a></p>')
        
        # Create Telegraph page
        content_html = '\n'.join(telegraph_html)
        
        result = telegraph.create_page(
            title=item.title[:256],
            content=content_html,
            author_name=source_name,
            author_url=item.article_url
        )
        
        if result and result.get('url'):
            item.telegraph_url = result['url']
            logging.info(f"[OK] Telegraph article created: {result['url']}")
            return result['url']
        else:
            return None
            
    except Exception as e:
        logging.error(f"Telegraph article creation failed: {e}")
        return None

# Telegram posting
def get_target_channel(source):
    if source in WORLD_NEWS_SOURCES:
        if WORLD_NEWS_CHANNEL_ID:
            safe_log("info", f"Routing {source} to WORLD_NEWS_CHANNEL")
            return WORLD_NEWS_CHANNEL_ID
        else:
            logging.warning(f"[WARN] WORLD_NEWS_CHANNEL_ID not set! {source} going to fallback")
            return CHAT_ID or ANIME_NEWS_CHANNEL_ID
    
    if source in ANIME_NEWS_SOURCES:
        if ANIME_NEWS_CHANNEL_ID:
            safe_log("info", f"Routing {source} to ANIME_NEWS_CHANNEL")
            return ANIME_NEWS_CHANNEL_ID
        else:
            return CHAT_ID or ANIME_NEWS_CHANNEL_ID
    
    logging.warning(f"[WARN] Unknown source {source}, using fallback channel")
    return CHAT_ID or ANIME_NEWS_CHANNEL_ID

def format_news_message(item: NewsItem):
    """
    Format news message with Telegraph link (unified format for both anime and world news)
    """
    source_name = SOURCE_LABEL.get(item.source, item.source)
    title = html.escape(str(item.title or "No Title"), quote=False)
    summary = html.escape(str(item.summary_text or "Read the full article on Telegraph for complete details."), quote=False)
    
    # Emoji based on source type
    if item.source in WORLD_NEWS_SOURCES:
        header_emoji = "🌍"
        header_text = "WORLD NEWS"
    else:
        header_emoji = "📰"
        header_text = "ANIME NEWS"
    
    # Build message
    msg_parts = [
        f"{header_emoji} <b>{header_text}</b>",
        "",
        f"<b>{title}</b>",
        "",
        f"<i>{summary}</i>",
        "",
        "━━━━━━━━━━━━━━━━━",
        f"📰 <b>Source:</b> {source_name}",
    ]
    
    if item.category:
        cat = html.escape(str(item.category), quote=False)
        msg_parts.append(f"🏷️ <b>Category:</b> {cat}")
    
    if item.publish_date:
        dt_str = item.publish_date.strftime("%B %d, %Y at %I:%M %p IST")
        msg_parts.append(f"📅 <b>Published:</b> {dt_str}")
    
    msg_parts.append("")
    
    # Add Telegraph link if available (primary CTA)
    if item.telegraph_url:
        msg_parts.append(f"📖 <a href='{item.telegraph_url}'>Read Full Article on Telegraph</a>")
        msg_parts.append(f"📍 <a href='{html.escape(item.article_url, quote=True)}'>Original Source</a>")
    else:
        # Fallback to original link
        msg_parts.append(f"📍 <a href='{html.escape(item.article_url, quote=True)}'>Read Full Article</a>")
    
    return "\n".join(msg_parts)

def send_to_telegram(item: NewsItem, slot, posted_set):
    """
    Send news to Telegram with Telegraph integration
    """
    # Spam detection
    if is_duplicate(item.title, item.article_url, posted_set):
        logging.info(f"[BLOCKED] Skipping duplicate: {item.title[:50]}")
        return False

    # Record attempt
    if not record_post(item.title, item.source, item.article_url, slot, posted_set, item.category, status='attempted'):
        logging.warning("[WARN] Failed to record attempt, skipping to avoid spam")
        return False
    
    # Create Telegraph article (with rate limiting consideration)
    try:
        telegraph_url = create_telegraph_article(item)
        if telegraph_url:
            item.telegraph_url = telegraph_url
            time.sleep(0.5)  # Brief delay after Telegraph creation
    except Exception as e:
        logging.warning(f"Telegraph creation failed, will use original link: {e}")
        item.telegraph_url = None
    
    # Get target channel
    target_chat_id = get_target_channel(item.source)
    
    # Format message
    msg = format_news_message(item)
    
    success = False
    
    # Try with image first
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
                logging.warning(f"[WAIT] Rate limited. Sleeping {retry_after}s")
                time.sleep(retry_after)
            else:
                logging.warning(f"[WARN] Image send failed: {response.text}")
        except Exception as e:
            logging.warning(f"[WARN] Image send failed for {item.title}: {e}")

    # Fallback to text
    if not success:
        try:
            sess = get_fresh_telegram_session()
            response = sess.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": target_chat_id, 
                    "text": msg, 
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False  # Show preview for Telegraph links
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
                        "parse_mode": "HTML",
                        "disable_web_page_preview": False
                    },
                    timeout=20
                )
            sess.close()
            
            if response.status_code == 200:
                safe_log("info", f"Sent (Text) to {target_chat_id}: {item.title[:50]}")
                success = True
            else:
                logging.error(f"[ERROR] Send failed: {response.text}")
                
        except Exception as e:
            logging.error(f"[ERROR] Send attempt failed: {e}")
            
    if success:
        # Update status
        update_post_status(item.title, 'sent')
        
        # Update record with Telegraph URL if created
        if item.telegraph_url and supabase:
            try:
                key = normalize_title(item.title)
                date_obj = str(now_local().date())
                supabase.table("posted_news")\
                    .update({"telegraph_url": item.telegraph_url})\
                    .eq("normalized_title", key)\
                    .eq("posted_date", date_obj)\
                    .execute()
            except:
                pass
        
        key = normalize_title(item.title)
        posted_set.add(key)
        return True
        
    return False

def send_admin_report(status, posts_sent, source_counts, error=None):
    if not ADMIN_ID: 
        return

    dt = now_local()
    date_str = str(dt.date())
    slot = dt.hour // 4
    
    anime_posts = sum(count for source, count in source_counts.items() if source in ANIME_NEWS_SOURCES)
    world_posts = sum(count for source, count in source_counts.items() if source in WORLD_NEWS_SOURCES)
    
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
        
    health_warnings = []
    if error:
        health_warnings.append(f"[WARN] <b>Error:</b> {html.escape(str(error)[:100], quote=False)}")
    
    for source, count in circuit_breaker.failure_counts.items():
        if count >= circuit_breaker.failure_threshold:
            health_warnings.append(f"[WARN] <b>Source Down:</b> {source} ({count} failures)")
    
    health_status = "[OK] <b>All Systems Operational</b>" if not health_warnings else "\n".join(health_warnings)

    source_stats = "\n".join([f"• <b>{k}:</b> {v}" for k, v in source_counts.items()])
    if not source_stats: source_stats = "• No new posts this cycle"

    report_msg = (
        f"[BOT] <b>News Bot Report</b>\n"
        f"[DATE] {date_str} | [SLOT] Slot {slot} | [TIME] {dt.strftime('%I:%M %p IST')}\n\n"
        
        f"<b>[STATS] This Cycle</b>\n"
        f"• Status: {status.upper()}\n"
        f"• Posts Sent: {posts_sent}\n"
        f"• Anime News: {anime_posts}\n"
        f"• World News: {world_posts}\n\n"
        
        f"<b>[TOTAL] Today's Total: {daily_total}</b>\n"
        f"<b>[ALL] All-Time: {all_time_total}</b>\n\n"
        
        f"<b>[SOURCE] Source Breakdown</b>\n{source_stats}\n\n"
        
        f"<b>[HEALTH] System Health</b>\n{health_status}"
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
        logging.error(f"[ERROR] Failed to send admin report: {e}")
    finally:
        sess.close()

# Main execution
def run_once():
    """
    Main execution with Telegraph integration
    """
    dt = now_local()
    date_obj = dt.date()
    slot = dt.hour // 4
    
    safe_log("info", f"\n{'='*60}")
    safe_log("info", f"STARTING NEWS BOT RUN (Telegraph Enabled)")
    safe_log("info", f"Date: {date_obj} | Slot: {slot} | Time: {dt.strftime('%I:%M %p IST')}")
    safe_log("info", f"{'='*60}\n")
    
    if should_reset_daily_tracking():
        safe_log("info", "NEW DAY DETECTED - Resetting daily tracking")
    
    initialize_bot_stats()
    ensure_daily_row(date_obj)
    
    posted_set = load_posted_titles(date_obj)
    all_items = []
    
    safe_log("info", "\nFETCHING NEWS FROM SOURCES...")
    
    # Fetch from RSS feeds
    for code, url in RSS_FEEDS.items():
        if circuit_breaker.can_call(code):
            logging.info(f"  -> Fetching {code}...")
            items = fetch_rss(url, code, lambda s: parse_rss_robust(s, code))
            all_items.extend(items)
            logging.info(f"    [OK] Found {len(items)} items")

    safe_log("info", f"\nPOSTING TO TELEGRAM (with Telegraph)...")
    sent_count = 0
    source_counts = defaultdict(int)
    
    for item in all_items:
        if not item.title: 
            continue
        
        if item.publish_date and not is_today_or_yesterday(item.publish_date):
            logging.debug(f"[SKIP] Skipping old news: {item.title[:50]}")
            continue
        
        if send_to_telegram(item, slot, posted_set):
            sent_count += 1
            source_counts[item.source] += 1
            time.sleep(2.0)  # Increased delay for Telegraph + Telegram posting

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