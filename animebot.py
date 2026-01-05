import requests
from bs4 import BeautifulSoup
import time
import re
import os
import json
import logging
import pytz
import uuid
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from tenacity import retry, stop_after_attempt, wait_exponential
try:
    from supabase import create_client, Client
except Exception as e:
    logging.warning(f"Supabase import failed: {e}. Falling back to JSON storage.")
    create_client = None
    Client = None
    
from flask import Flask, request
from threading import Thread
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(env_path, override=True)

SESSION_ID = str(uuid.uuid4())[:8]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("anime_news_bot.log"), logging.StreamHandler()],
    force=True
)

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

if not BOT_TOKEN or not CHAT_ID:
    logging.error("BOT_TOKEN or CHAT_ID is missing. Check environment variables.")
    exit(1)

supabase = None
if SUPABASE_URL and SUPABASE_KEY and create_client:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logging.info("Supabase connected")
    except Exception as e:
        logging.error(f"Supabase init failed: {e}")
else:
    logging.warning("Supabase credentials not provided or library missing, using JSON fallback")

utc_tz = pytz.utc
local_tz = pytz.timezone("Asia/Kolkata")
today_local = datetime.now(local_tz).date()

# Fixed-time scheduler constants
SLOT_HOURS = [0, 4, 8, 12, 16, 20]  # IST fixed schedule
SLOTS_PER_DAY = 6

def now_local():
    return datetime.now(local_tz)

def slot_index(dt_local):
    return dt_local.hour // 4  # 0..5

def slot_start_for(dt_local):
    h = (dt_local.hour // 4) * 4
    return dt_local.replace(hour=h, minute=0, second=0, microsecond=0)

def next_slot_start(dt_local):
    cur = slot_start_for(dt_local)
    if dt_local < cur:
        return cur
    nxt_h = ((dt_local.hour // 4) + 1) * 4
    if nxt_h >= 24:
        tomorrow = (dt_local + timedelta(days=1)).date()
        return dt_local.replace(year=tomorrow.year, month=tomorrow.month, day=tomorrow.day,
                                hour=0, minute=0, second=0, microsecond=0)
    return dt_local.replace(hour=nxt_h, minute=0, second=0, microsecond=0)

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
})

last_run_time = None

app = Flask(__name__)

@app.route('/')
def home():
    return f"Bot is alive! Session: {SESSION_ID}", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle incoming webhook updates from Telegram"""
    try:
        update = request.get_json()
        if not update:
            return "OK", 200
        
        message = update.get('message', {})
        if message.get('text') == '/start':
            user_id = message.get('from', {}).get('id')
            chat_id = message.get('chat', {}).get('id')
            
            if str(user_id) == ADMIN_ID or not ADMIN_ID:
                stats = get_bot_stats()
                send_message(chat_id, stats)
        
        return "OK", 200
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return "OK", 200

def keep_alive():
    """Pings the web server storage url to keep it awake on free tiers."""
    if not RENDER_EXTERNAL_URL:
        return
        
    while True:
        try:
            time.sleep(300)
            response = requests.get(RENDER_EXTERNAL_URL, timeout=5)
            logging.info(f"Self-ping status: {response.status_code}")
        except Exception as e:
            logging.error(f"Self-ping failed: {e}")

def escape_html(text):
    """Escapes special characters for Telegram HTML formatting."""
    if not text or not isinstance(text, str):
        return ""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def get_normalized_key(title):
    """Normalizes the title to a key for deduplication across sources."""
    prefixes = ['DC Wiki Update: ', 'TMS News: ', 'Fandom Wiki Update: ', 'ANN DC News: ']
    for prefix in prefixes:
        if title.startswith(prefix):
            return title[len(prefix):].strip()
    return title.strip()

def initialize_bot_stats():
    """Initialize bot statistics in database if not exists."""
    if not supabase:
        return
    
    try:
        response = supabase.table('bot_stats').select('*').limit(1).execute()
        
        if not response.data:
            now = datetime.now(utc_tz)
            supabase.table('bot_stats').insert({
                'bot_started_at': now.isoformat(),
                'total_posts_all_time': 0,
                'last_seen': now.isoformat()
            }).execute()
            logging.info("✅ Initialized bot_stats table")
        
        today = datetime.now(local_tz).date()
        daily_response = supabase.table('daily_stats').select('*').eq('date', str(today)).execute()
        
        if not daily_response.data:
            supabase.table('daily_stats').insert({
                'date': str(today),
                'posts_count': 0,
                'session_start': datetime.now(utc_tz).isoformat()
            }).execute()
            logging.info(f"✅ Initialized daily_stats for {today}")
            
    except Exception as e:
        logging.error(f"Error initializing bot stats: {e}")

def get_bot_stats():
    """Returns simple bot statistics."""
    if not supabase:
        return "<b>⚠️ Database not connected. Stats unavailable.</b>"
    
    try:
        today = datetime.now(local_tz).date()
        
        # Get today's post count
        daily_response = supabase.table('daily_stats').select('*').eq('date', str(today)).execute()
        today_posts = 0
        if daily_response.data:
            today_posts = daily_response.data[0].get('posts_count', 0)
        
        # Get all-time post count
        bot_response = supabase.table('bot_stats').select('*').limit(1).execute()
        total_posts = 0
        if bot_response.data:
            total_posts = bot_response.data[0].get('total_posts_all_time', 0)
        
        # Count active sources (always 4)
        num_sources = 4
        
        stats = (
            f"<b>🤖 Detective Conan News Bot</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 <b>Posts Today:</b> {today_posts}\n"
            f"📊 <b>Total Posts:</b> {total_posts}\n"
            f"📡 <b>Active Sources:</b> {num_sources}\n\n"
            f"<b>Sources:</b>\n"
            f"• Anime News Network\n"
            f"• Detective Conan Wiki\n"
            f"• TMS Entertainment\n"
            f"• Fandom Wiki\n\n"
            f"⏰ <b>Updates every 4 hours</b>\n"
            f"🔔 <b>Status:</b> 🟢 Active"
        )
        return stats
        
    except Exception as e:
        logging.error(f"Error getting bot stats: {e}")
        return f"<b>⚠️ Error loading stats: {str(e)}</b>"

def reset_daily_stats():
    """Resets daily stats at midnight (12 AM IST)."""
    if not supabase:
        return
    
    try:
        today = datetime.now(local_tz).date()
        now = datetime.now(utc_tz)
        
        supabase.table('daily_stats').insert({
            'date': str(today),
            'posts_count': 0,
            'session_start': now.isoformat()
        }).execute()
        
        logging.info(f"✅ Daily stats reset for new day: {today}")
        
    except Exception as e:
        logging.error(f"Error resetting daily stats: {e}")

def ensure_daily_row(date_obj):
    if not supabase:
        return
    try:
        resp = supabase.table('daily_stats').select('*').eq('date', str(date_obj)).execute()
        if not resp.data:
            supabase.table('daily_stats').insert({
                'date': str(date_obj),
                'posts_count': 0,
                'runs_completed': 0,
                'last_slot_done': -1
            }).execute()
    except Exception as e:
        logging.error(f"ensure_daily_row failed: {e}")

def get_last_slot_done(date_obj):
    if not supabase:
        return -1
    try:
        resp = supabase.table('daily_stats').select('last_slot_done').eq('date', str(date_obj)).execute()
        if resp.data:
            return int(resp.data[0].get('last_slot_done', -1))
    except Exception as e:
        logging.error(f"get_last_slot_done failed: {e}")
    return -1

def mark_slot_done(date_obj, slot, run_posts_sent):
    if not supabase:
        return
    try:
        resp = supabase.table('daily_stats').select('*').eq('date', str(date_obj)).execute()
        if not resp.data:
            ensure_daily_row(date_obj)
            resp = supabase.table('daily_stats').select('*').eq('date', str(date_obj)).execute()

        row = resp.data[0]
        runs_completed = int(row.get('runs_completed', 0))
        last_slot = int(row.get('last_slot_done', -1))

        # update only if progressing (prevents double counting if rerun)
        if slot > last_slot:
            supabase.table('daily_stats').update({
                'runs_completed': runs_completed + 1,
                'last_slot_done': slot,
                'updated_at': datetime.now(utc_tz).isoformat()
            }).eq('date', str(date_obj)).execute()
    except Exception as e:
        logging.error(f"mark_slot_done failed: {e}")

def create_run(date_obj, slot, scheduled_at_local):
    if not supabase:
        return None
    try:
        scheduled_at_utc = scheduled_at_local.astimezone(utc_tz).isoformat()
        started_at_utc = datetime.now(utc_tz).isoformat()
        resp = supabase.table('runs').insert({
            'date': str(date_obj),
            'slot': slot,
            'scheduled_at': scheduled_at_utc,
            'started_at': started_at_utc,
            'status': 'started',
            'posts_sent': 0,
            'source_counts': {}
        }).execute()
        return resp.data[0]['id'] if resp.data else None
    except Exception as e:
        logging.error(f"create_run failed: {e}")
        return None

def finish_run(run_id, status, posts_sent, source_counts, error=None):
    if not supabase or not run_id:
        return
    try:
        payload = {
            'status': status,
            'posts_sent': posts_sent,
            'source_counts': source_counts,  # jsonb
            'finished_at': datetime.now(utc_tz).isoformat(),
            'error': error
        }
        supabase.table('runs').update(payload).eq('id', run_id).execute()
    except Exception as e:
        logging.error(f"finish_run failed: {e}")

def load_posted_titles():
    """Loads posted normalized keys from database or file."""
    if supabase:
        try:
            today = datetime.now(local_tz).date()
            response = supabase.table('posted_news').select('normalized_title').eq('posted_date', str(today)).execute()
            return set(item['normalized_title'] for item in response.data)
        except Exception as e:
            logging.error(f"Error loading from Supabase: {e}")
    
    try:
        if os.path.exists(POSTED_TITLES_FILE):
            with open(POSTED_TITLES_FILE, "r", encoding="utf-8") as file:
                return set(json.load(file))
        return set()
    except json.JSONDecodeError:
        logging.error("Error decoding posted_titles.json. Resetting file.")
        return set()

def save_posted_title(title, run_id=None, slot=None):
    """Saves a normalized key to database and updates post counts."""
    key = get_normalized_key(title)
    today = datetime.now(local_tz).date()
    now = datetime.now(utc_tz)
    
    if supabase:
        try:
            # Save the posted news
            insert_data = {
                'normalized_title': key,
                'posted_date': str(today),
                'full_title': title,
                'posted_at': now.isoformat()
            }
            if run_id is not None:
                insert_data['run_id'] = run_id
            if slot is not None:
                insert_data['slot'] = slot
                
            supabase.table('posted_news').insert(insert_data).execute()
            
            # Update today's post count
            daily_response = supabase.table('daily_stats').select('*').eq('date', str(today)).execute()
            if daily_response.data:
                current_count = daily_response.data[0].get('posts_count', 0)
                supabase.table('daily_stats').update({
                    'posts_count': current_count + 1
                }).eq('date', str(today)).execute()
            
            # Update all-time post count
            bot_response = supabase.table('bot_stats').select('*').limit(1).execute()
            if bot_response.data:
                bot_data = bot_response.data[0]
                current_total = bot_data.get('total_posts_all_time', 0)
                supabase.table('bot_stats').update({
                    'total_posts_all_time': current_total + 1,
                    'last_seen': now.isoformat()
                }).eq('id', bot_data['id']).execute()
            
            return
        except Exception as e:
            logging.error(f"Error saving to Supabase: {e}")
    
    try:
        titles = load_posted_titles()
        titles.add(key)
        with open(POSTED_TITLES_FILE, "w", encoding="utf-8") as file:
            json.dump(list(titles), file)
    except Exception as e:
        logging.error(f"Error saving posted title: {e}")

def validate_image_url(image_url):
    """Validates if the image URL is accessible."""
    if not image_url:
        return False
    try:
        headers = {"Range": "bytes=0-511"}
        response = session.get(image_url, headers=headers, timeout=3, stream=True)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            logging.warning(f"URL {image_url} is not an image: {content_type}")
            return False
        return True
    except requests.RequestException as e:
        logging.warning(f"Invalid or inaccessible image URL {image_url}: {e}")
        return False

def extract_video_url(soup, article_url):
    """Extracts video URL from article page - supports YouTube, Twitter, and embedded videos."""
    video_url = None
    
    try:
        youtube_iframe = soup.find('iframe', src=re.compile(r'youtube\.com/embed|youtu\.be'))
        if youtube_iframe:
            src = youtube_iframe.get('src', '')
            video_id_match = re.search(r'embed/([a-zA-Z0-9_-]+)', src)
            if video_id_match:
                video_url = f"https://www.youtube.com/watch?v={video_id_match.group(1)}"
                logging.info(f"Found YouTube video: {video_url}")
                return video_url
        
        twitter_blockquote = soup.find('blockquote', class_='twitter-tweet')
        if twitter_blockquote:
            twitter_link = twitter_blockquote.find('a')
            if twitter_link:
                video_url = twitter_link.get('href')
                logging.info(f"Found Twitter video: {video_url}")
                return video_url
        
        video_tag = soup.find('video')
        if video_tag:
            source_tag = video_tag.find('source')
            if source_tag and source_tag.get('src'):
                video_url = source_tag['src']
                if not video_url.startswith('http'):
                    video_url = f"{BASE_URL}{video_url}"
                logging.info(f"Found direct video: {video_url}")
                return video_url
        
        video_players = soup.find_all('div', class_=re.compile(r'video|player|embed', re.IGNORECASE))
        for player in video_players:
            iframe = player.find('iframe')
            if iframe and iframe.get('src'):
                src = iframe.get('src')
                if 'youtube' in src or 'vimeo' in src or 'dailymotion' in src:
                    video_url = src
                    logging.info(f"Found embedded video: {video_url}")
                    return video_url
                    
    except Exception as e:
        logging.error(f"Error extracting video from {article_url}: {e}")
    
    return video_url

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
def fetch_anime_news():
    """Fetches latest anime news from ANN."""
    try:
        response = session.get(BASE_URL, timeout=8)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        news_list = []
        all_articles = soup.find_all("div", class_="herald box news t-news")
        logging.info(f"Total articles found: {len(all_articles)}")

        for article in all_articles:
            title_tag = article.find("h3")
            date_tag = article.find("time")
            
            if not title_tag or not date_tag:
                continue

            title = title_tag.get_text(" ", strip=True)
            date_str = date_tag["datetime"]  
            try:
                news_date = datetime.fromisoformat(date_str).astimezone(local_tz).date()
            except ValueError as e:
                logging.error(f"Error parsing date {date_str}: {e}")
                continue

            if DEBUG_MODE or news_date == today_local:
                link = title_tag.find("a")
                article_url = f"{BASE_URL}{link['href']}" if link else None
                news_list.append({"title": title, "article_url": article_url, "article": article, "source": "ANN"})
                logging.info(f"✅ Found today's news: {title}")
            else:
                logging.info(f"⏩ Skipping (not today's news): {title} - Date: {news_date}")

        logging.info(f"Filtered today's articles: {len(news_list)}")
        return news_list

    except requests.RequestException as e:
        logging.error(f"Fetch error: {e}")
        return []

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
def fetch_article_details(article_url, article):
    """Fetches article image, video, and summary."""
    image_url = None
    video_url = None
    summary = "No summary available."
    article_date = None

    thumbnail = article.find("div", class_="thumbnail lazyload")
    if thumbnail and thumbnail.get("data-src"):
        img_url = thumbnail["data-src"]
        image_url = f"{BASE_URL}{img_url}" if not img_url.startswith("http") else img_url
        logging.info(f"📸 Extracted Image URL: {image_url}")

    if article_url:
        try:
            article_response = session.get(article_url, timeout=8)
            article_response.raise_for_status()
            article_soup = BeautifulSoup(article_response.text, "html.parser")
            
            video_url = extract_video_url(article_soup, article_url)
            
            time_tag = article_soup.find("time", {"itemprop": "datePublished"})
            if time_tag and time_tag.get("datetime"):
                try:
                    article_date = datetime.fromisoformat(time_tag["datetime"]).astimezone(local_tz).strftime("%b %d, %Y %I:%M %p")
                except:
                    pass
            
            content_div = article_soup.find("div", class_="meat") or article_soup.find("div", class_="content")
            if content_div:
                paragraphs = content_div.find_all("p")
                for p in paragraphs:
                    text = p.get_text(" ", strip=True)
                    if len(text) > 50:
                        summary = text[:350] + "..." if len(text) > 350 else text
                        break
                        
        except requests.RequestException as e:
            logging.error(f"Error fetching article content: {e}")

    return {
        "image": image_url, 
        "video": video_url,
        "summary": summary,
        "date": article_date
    }

def send_message(chat_id, text):
    """Sends a text message to Telegram."""
    try:
        response = session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        response.raise_for_status()
        logging.info(f"Message sent to chat {chat_id}")
    except requests.RequestException as e:
        logging.error(f"Failed to send message to chat {chat_id}: {e}")

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
def fetch_dc_updates():
    """Fetches recent changes from Detective Conan Wiki."""
    try:
        url = f"{BASE_URL_DC}/wiki/Special:RecentChanges"
        response = session.get(url, timeout=8)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        updates_list = []
        changes = soup.find_all("li", class_=re.compile(r"mw-changeslist-line"))

        for change in changes:
            time_tag = change.find("a", class_="mw-changeslist-date")
            if not time_tag:
                continue
            time_str = time_tag.get_text(strip=True)
            
            try:
                if "," in time_str:
                    date_str = time_str + f", {datetime.now().year}"
                else:
                    date_str = time_str
                change_date = datetime.strptime(date_str, "%H:%M, %d %B %Y").replace(tzinfo=pytz.utc).astimezone(local_tz).date()
            except ValueError as e:
                logging.error(f"Error parsing date {time_str}: {e}")
                continue

            if DEBUG_MODE or change_date == today_local:
                title_tag = change.find("a", class_="mw-changeslist-title")
                if not title_tag:
                    continue
                page_title = title_tag.get_text(" ", strip=True)
                user_tag = change.find("a", class_="mw-userlink")
                user = user_tag.get_text(strip=True) if user_tag else "Unknown"
                comment_tag = change.find("span", class_="comment")
                comment = comment_tag.get_text(strip=True) if comment_tag else ""

                title = f"DC Wiki Update: {page_title}"
                summary = f"Edited by {user}. {comment}" if comment else f"Edited by {user}."

                updates_list.append({"title": title, "summary": summary, "image": None, "video": None, "source": "DCW"})
                logging.info(f"✅ Found today's wiki update: {title}")

        logging.info(f"Filtered today's wiki updates: {len(updates_list)}")
        return updates_list

    except requests.RequestException as e:
        logging.error(f"Fetch DC updates error: {e}")
        return []

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
def fetch_tms_news():
    """Fetches latest news from TMS Detective Conan page."""
    try:
        response = session.get(BASE_URL_TMS + "/detective-conan", timeout=8)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        news_list = []
        latest_news_section = soup.find(string="LATEST TMS NEWS")
        if latest_news_section:
            parent = latest_news_section.parent
            news_links = parent.find_next_siblings("a")[:5]
            for link in news_links:
                title = link.get_text(" ", strip=True)
                url = link.get("href")
                if title and url:
                    news_title = f"TMS News: {title}"
                    summary = f"Read more: {BASE_URL_TMS}{url}" if not url.startswith("http") else f"Read more: {url}"
                    news_list.append({"title": news_title, "summary": summary, "image": None, "video": None, "source": "TMS"})
                    logging.info(f"✅ Found TMS news: {title}")

        logging.info(f"Filtered TMS news: {len(news_list)}")
        return news_list

    except requests.RequestException as e:
        logging.error(f"Fetch TMS news error: {e}")
        return []

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
def fetch_fandom_updates():
    """Fetches recent changes from Detective Conan Fandom Wiki."""
    try:
        url = f"{BASE_URL_FANDOM}/wiki/Special:RecentChanges"
        response = session.get(url, timeout=8)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        updates_list = []
        changes = soup.find_all("li", class_=re.compile(r"mw-changeslist-line"))

        for change in changes:
            time_tag = change.find("a", class_="mw-changeslist-date")
            if not time_tag:
                continue
            time_str = time_tag.get_text(strip=True)
            
            try:
                if "," in time_str:
                    date_str = time_str + f", {datetime.now().year}"
                else:
                    date_str = time_str
                change_date = datetime.strptime(date_str, "%H:%M, %d %B %Y").replace(tzinfo=pytz.utc).astimezone(local_tz).date()
            except ValueError as e:
                logging.error(f"Error parsing date {time_str}: {e}")
                continue

            if DEBUG_MODE or change_date == today_local:
                title_tag = change.find("a", class_="mw-changeslist-title")
                if not title_tag:
                    continue
                page_title = title_tag.get_text(" ", strip=True)
                user_tag = change.find("a", class_="mw-userlink")
                user = user_tag.get_text(strip=True) if user_tag else "Unknown"
                comment_tag = change.find("span", class_="comment")
                comment = comment_tag.get_text(strip=True) if comment_tag else ""

                title = f"Fandom Wiki Update: {page_title}"
                summary = f"Edited by {user}. {comment}" if comment else f"Edited by {user}."

                updates_list.append({"title": title, "summary": summary, "image": None, "video": None, "source": "FANDOM"})
                logging.info(f"✅ Found today's Fandom wiki update: {title}")

        logging.info(f"Filtered today's Fandom wiki updates: {len(updates_list)}")
        return updates_list

    except requests.RequestException as e:
        logging.error(f"Fetch Fandom updates error: {e}")
        return []

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
def fetch_ann_dc_news():
    """Fetches latest Detective Conan news from ANN encyclopedia page."""
    try:
        response = session.get(BASE_URL_ANN_DC, timeout=8)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        news_list = []
        all_articles = soup.find_all("div", class_="herald box news t-news")
        logging.info(f"Total DC articles found: {len(all_articles)}")

        for article in all_articles:
            title_tag = article.find("h3")
            date_tag = article.find("time")
            
            if not title_tag or not date_tag:
                continue

            title = title_tag.get_text(" ", strip=True)
            date_str = date_tag["datetime"]  
            try:
                news_date = datetime.fromisoformat(date_str).astimezone(local_tz).date()
            except ValueError as e:
                logging.error(f"Error parsing date {date_str}: {e}")
                continue

            if DEBUG_MODE or news_date == today_local:
                link = title_tag.find("a")
                article_url = f"{BASE_URL}{link['href']}" if link else None
                news_list.append({"title": f"ANN DC News: {title}", "article_url": article_url, "article": article, "source": "ANN_DC"})
                logging.info(f"✅ Found today's DC news: {title}")
            else:
                logging.info(f"⏩ Skipping (not today's DC news): {title} - Date: {news_date}")

        logging.info(f"Filtered today's DC articles: {len(news_list)}")
        return news_list

    except requests.RequestException as e:
        logging.error(f"Fetch ANN DC news error: {e}")
        return []

def fetch_selected_articles(news_list):
    """Fetches article details concurrently."""
    posted_titles = load_posted_titles()
    articles_to_fetch = [news for news in news_list if news["title"] not in posted_titles and "article_url" in news and "article" in news]

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(fetch_article_details, news["article_url"], news["article"]): news for news in articles_to_fetch}
        
        for future in futures:
            try:
                result = future.result(timeout=10)
                news = futures[future]
                news["image"] = result["image"]
                news["video"] = result["video"]
                news["summary"] = result["summary"]
                news["date"] = result.get("date")
            except Exception as e:
                logging.error(f"Error processing article: {e}")
                news = futures[future]
                news["image"] = None
                news["video"] = None
                news["summary"] = "Failed to fetch summary."
                news["date"] = None

def create_beautiful_message(title, summary, source, article_url, date_str, video_url):
    """Creates a compact, elegant, and visually appealing message."""
    clean_title = get_normalized_key(title)
    
    source_emoji = {
        "Anime News Network": "🎬",
        "Detective Conan Wiki": "🔍",
        "TMS Entertainment": "🎥",
        "Fandom Wiki": "📚",
        "ANN DC": "🕵️"
    }.get(source, "📢")
    
    message = f"""┌──────────────────────────╮
  📰 <b>ANIME NEWS UPDATE</b> {source_emoji}
└──────────────────────────╭

<b>▸ {escape_html(clean_title)}</b>

{escape_html(summary) if summary else 'No summary available.'}"""
    
    footer_items = []
    
    if date_str:
        footer_items.append(f"📅 {date_str}")
    
    if video_url:
        footer_items.append(f"<a href='{video_url}'>🎥 Watch Video</a>")
    
    if article_url:
        footer_items.append(f"<a href='{article_url}'>🔗 Read More</a>")
    
    if footer_items:
        message += "\n\n" + " • ".join(footer_items)
    
    message += f"\n\n──────────────────────────\n<i>🏷️ {source}</i>\n\n<b>Channel:</b> @Detective_Conan_News"
    
    return message

def send_to_telegram(title, image_url, summary, source=None, video_url=None, article_url=None, date_str=None, run_id=None, slot=None):
    """Posts news to Telegram with beautiful formatting."""
    # Use provided source or fall back to title-based detection
    if source is None:
        source_map = {
            'DC Wiki Update: ': "Detective Conan Wiki",
            'TMS News: ': "TMS Entertainment",
            'Fandom Wiki Update: ': "Fandom Wiki",
            'ANN DC News: ': "ANN DC"
        }
        
        source = "Anime News Network"
        for prefix, src in source_map.items():
            if title.startswith(prefix):
                source = src
                break
    else:
        # Map source codes to full names
        source_name_map = {
            "ANN": "Anime News Network",
            "DCW": "Detective Conan Wiki", 
            "TMS": "TMS Entertainment",
            "FANDOM": "Fandom Wiki",
            "ANN_DC": "ANN DC"
        }
        source = source_name_map.get(source, source)
    
    message = create_beautiful_message(title, summary, source, article_url, date_str, video_url)
    
    logging.info(f"📤 Sending to Telegram - Title: {title}")
    
    if image_url and validate_image_url(image_url):
        try:
            response = session.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={
                    "chat_id": CHAT_ID,
                    "photo": image_url,
                    "caption": message,
                    "parse_mode": "HTML",
                },
                timeout=10,
            )
            response.raise_for_status()
            logging.info(f"✅ Posted with photo: {title}")
            save_posted_title(title, run_id, slot)
            return
        except requests.RequestException as e:
            logging.error(f"Failed to send photo for {title}: {e}")

    try:
        response = session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": False
            },
            timeout=10,
        )
        response.raise_for_status()
        logging.info(f"✅ Posted as text: {title}")
        save_posted_title(title, run_id, slot)
    except requests.RequestException as e:
        logging.error(f"❌ Failed to send message for {title}: {e}")

def ping_bot():
    """Ping the bot to keep it alive."""
    try:
        response = session.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
        response.raise_for_status()
    except requests.RequestException as e:
        logging.warning(f"Bot ping failed: {e}")

def setup_webhook():
    """Set up webhook for receiving Telegram updates"""
    if not RENDER_EXTERNAL_URL:
        logging.warning("RENDER_EXTERNAL_URL not set, webhook not configured")
        return
    
    webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            json={"url": webhook_url},
            timeout=10
        )
        if response.status_code == 200:
            logging.info(f"✅ Webhook set successfully: {webhook_url}")
        else:
            logging.error(f"Failed to set webhook: {response.text}")
    except Exception as e:
        logging.error(f"Error setting webhook: {e}")

def midnight_check():
    """Checks if it's midnight and resets daily stats."""
    global today_local
    current_date = datetime.now(local_tz).date()
    
    if current_date != today_local:
        logging.info("🆕 New day detected! Resetting daily stats...")
        reset_daily_stats()
        today_local = current_date
        
        if not supabase:
            with open(POSTED_TITLES_FILE, "w", encoding="utf-8") as file:
                json.dump([], file)

def run_once():
    global last_run_time
    
    midnight_check()
    
    logging.info("🔍 Fetching latest anime news...")
    logging.info(f"📅 Today's date (local): {today_local}")
    
    news_list = fetch_anime_news()
    time.sleep(1)
    
    dc_updates = fetch_dc_updates()
    time.sleep(1)
    
    tms_news = fetch_tms_news()
    time.sleep(1)
    
    fandom_updates = fetch_fandom_updates()
    time.sleep(1)
    
    ann_dc_news = fetch_ann_dc_news()
    
    all_updates = news_list + dc_updates + tms_news + fandom_updates + ann_dc_news

    if not all_updates:
        logging.info("❌ No new articles or updates to post.")
        return

    fetch_selected_articles(news_list + ann_dc_news)
    
    posted_count = 0
    for update in all_updates:
        if get_normalized_key(update["title"]) not in load_posted_titles():
            send_to_telegram(
                update["title"], 
                update.get("image"), 
                update.get("summary", "No summary available."),
                update.get("source"),
                update.get("video"),
                update.get("article_url"),
                update.get("date")
            )
            posted_count += 1
            time.sleep(2)
    
    logging.info(f"✅ Posted {posted_count} new updates this cycle")
    last_run_time = datetime.now(utc_tz)
    
    del news_list, dc_updates, tms_news, fandom_updates, ann_dc_news, all_updates

def run_scheduled_slot(date_obj, slot, scheduled_local):
    """Run a scheduled scraping slot with proper tracking."""
    run_id = create_run(date_obj, slot, scheduled_local)
    
    try:
        logging.info(f"🚀 Running slot {slot} for {date_obj} (scheduled for {scheduled_local.strftime('%H:%M')} IST)")
        
        # Track source counts
        source_counts = {"ANN": 0, "DCW": 0, "TMS": 0, "FANDOM": 0, "ANN_DC": 0}
        posted_count = 0
        
        # Fetch all news
        news_list = fetch_anime_news()
        time.sleep(1)
        
        dc_updates = fetch_dc_updates()
        time.sleep(1)
        
        tms_news = fetch_tms_news()
        time.sleep(1)
        
        fandom_updates = fetch_fandom_updates()
        time.sleep(1)
        
        ann_dc_news = fetch_ann_dc_news()
        
        all_updates = news_list + dc_updates + tms_news + fandom_updates + ann_dc_news

        if not all_updates:
            logging.info("❌ No new articles or updates to post.")
            finish_run(run_id, 'success', 0, source_counts)
            mark_slot_done(date_obj, slot, 0)
            return

        fetch_selected_articles(news_list + ann_dc_news)
        
        for update in all_updates:
            if get_normalized_key(update["title"]) not in load_posted_titles():
                send_to_telegram(
                    update["title"], 
                    update.get("image"), 
                    update.get("summary", "No summary available."),
                    update.get("source"),
                    update.get("video"),
                    update.get("article_url"),
                    update.get("date"),
                    run_id,
                    slot
                )
                posted_count += 1
                
                # Count by source
                source = update.get("source", "ANN")
                if source in source_counts:
                    source_counts[source] += 1
                
                time.sleep(2)
        
        logging.info(f"✅ Posted {posted_count} new updates in slot {slot}")
        finish_run(run_id, 'success', posted_count, source_counts)
        mark_slot_done(date_obj, slot, posted_count)
        
        # Clean up
        del news_list, dc_updates, tms_news, fandom_updates, ann_dc_news, all_updates
        
    except Exception as e:
        logging.error(f"❌ Error in slot {slot}: {e}")
        finish_run(run_id, 'failed', 0, {}, str(e))

if __name__ == "__main__":
    logging.info(f"🚀 Starting bot instance [Session ID: {SESSION_ID}]")
    
    initialize_bot_stats()
    
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            logging.info(f"🧹 Clearing webhooks (attempt {attempt + 1}/{max_attempts})...")
            response = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook",
                json={"drop_pending_updates": True},
                timeout=10
            )
            if response.status_code == 200:
                logging.info(f"✅ Webhook cleared (attempt {attempt + 1})")
            time.sleep(2)
        except Exception as e:
            logging.error(f"Failed to clear webhook (attempt {attempt + 1}): {e}")
    
    logging.info("⏳ Waiting 10 seconds for other instances to stop...")
    time.sleep(10)
    
    setup_webhook()
    
    logging.info("✅ This instance is now the primary bot")

    def bot_loop():
        heartbeat_interval = 300
        last_heartbeat = time.time()
        
        if RENDER_EXTERNAL_URL:
            ping_thread = Thread(target=keep_alive, daemon=True, name="Pinger")
            ping_thread.start()
        
        while True:
            current_time = time.time()
            if current_time - last_heartbeat >= heartbeat_interval:
                ping_bot()
                last_heartbeat = current_time
            
            try:
                dt = now_local()
                date_obj = dt.date()

                ensure_daily_row(date_obj)

                current_slot = slot_index(dt)
                last_done = get_last_slot_done(date_obj)

                # catch-up: run missing slots in order up to current slot
                if last_done < current_slot:
                    target_slot = last_done + 1
                    scheduled_local = dt.replace(hour=target_slot * 4, minute=0, second=0, microsecond=0)
                    run_scheduled_slot(date_obj, target_slot, scheduled_local)
                    continue

                # otherwise wait for next exact boundary
                nxt = next_slot_start(dt)
                sleep_s = max(1, int((nxt - dt).total_seconds()))
                logging.info(f"⏳ Next scrape at {nxt.strftime('%Y-%m-%d %H:%M')} IST (sleep {sleep_s}s)")
                time.sleep(sleep_s)
            except Exception as e:
                logging.error(f"Critical error in bot_loop: {e}")
                time.sleep(60)  # Wait 1 minute before retrying

    bot_thread = Thread(target=bot_loop, daemon=True)
    bot_thread.start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)