import requests
from bs4 import BeautifulSoup
import time
import re
import os
import json
import logging
import pytz
import uuid
from datetime import datetime
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
load_dotenv(env_path, override=True)  # Force load environment variables

# Generate unique session ID for this instance
SESSION_ID = str(uuid.uuid4())[:8]

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("anime_news_bot.log"), logging.StreamHandler()],
    force=True
)

# Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")  # Fetch from environment variables
CHAT_ID = os.getenv("CHAT_ID")  # Fetch from environment variables
ADMIN_ID = os.getenv("ADMIN_ID")  # Optional: Admin user ID for private commands
SUPABASE_URL = os.getenv("SUPABASE_URL")  # Supabase project URL
SUPABASE_KEY = os.getenv("SUPABASE_KEY")  # Supabase anon key
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL") # Render URL for self-ping
POSTED_TITLES_FILE = "posted_titles.json"
BASE_URL = "https://www.animenewsnetwork.com"
BASE_URL_DC = "https://www.detectiveconanworld.com"
BASE_URL_TMS = "https://tmsanime.com"
BASE_URL_FANDOM = "https://detectiveconan.fandom.com"
BASE_URL_ANN_DC = "https://www.animenewsnetwork.com/encyclopedia/anime.php?id=454&tab=news"
DEBUG_MODE = False  # Set True to test without date filter

if not BOT_TOKEN or not CHAT_ID:
    logging.error("BOT_TOKEN or CHAT_ID is missing. Check environment variables.")
    exit(1)

# Supabase setup
supabase = None
if SUPABASE_URL and SUPABASE_KEY and create_client:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        logging.info("Supabase connected")
    except Exception as e:
        logging.error(f"Supabase init failed: {e}")
else:
    logging.warning("Supabase credentials not provided or library missing, using JSON fallback")

# Time Zone Handling
utc_tz = pytz.utc
local_tz = pytz.timezone("Asia/Kolkata")  # Change if needed
today_local = datetime.now(local_tz).date()

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
})

# Bot Stats
last_run_time = None
posts_today = 0
total_posts = 0
uptime_start = datetime.now(utc_tz)

# Flask Setup
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
            
            # Only respond to admin or if no admin is set
            if str(user_id) == ADMIN_ID or not ADMIN_ID:
                stats = get_bot_stats()
                send_message(chat_id, stats)
        
        return "OK", 200
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return "OK", 200

def keep_alive():
    """Pings the web server storage url to keep it awake on free tiers - every 5 minutes."""
    if not RENDER_EXTERNAL_URL:
        return
        
    while True:
        try:
            time.sleep(300)  # Ping every 5 minutes (300 seconds)
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
    if title.startswith('DC Wiki Update: '):
        return title[len('DC Wiki Update: '):].strip()
    elif title.startswith('TMS News: '):
        return title[len('TMS News: '):].strip()
    elif title.startswith('Fandom Wiki Update: '):
        return title[len('Fandom Wiki Update: '):].strip()
    elif title.startswith('ANN DC News: '):
        return title[len('ANN DC News: '):].strip()
    else:
        return title.strip()  # For general ANN news

def get_bot_stats():
    """Returns bot statistics."""
    uptime = datetime.now(utc_tz) - uptime_start
    stats = (
        f"<b>Bot Statistics</b>\n\n"
        f"Session: {SESSION_ID}\n"
        f"Uptime: {uptime.days}d {uptime.seconds//3600}h {(uptime.seconds//60)%60}m\n"
        f"Last Run: {last_run_time.astimezone(local_tz).strftime('%Y-%m-%d %H:%M') if last_run_time else 'Never'}\n"
        f"Posts Today: {posts_today}\n"
        f"Total Posts: {total_posts}\n"
        f"Sources: ANN, DC Wiki, TMS, Fandom, ANN DC\n"
        f"Next Run: Every 4 hours\n"
        f"Status: Active"
    )
    return stats

def load_posted_titles():
    """Loads posted normalized keys from database or file."""
    if supabase:
        try:
            today = datetime.now(local_tz).date()
            response = supabase.table('posted_news').select('normalized_title').eq('posted_date', str(today)).execute()
            return set(item['normalized_title'] for item in response.data)
        except Exception as e:
            logging.error(f"Error loading from Supabase: {e}")
            # Fallback to JSON
    # Fallback to JSON
    try:
        if os.path.exists(POSTED_TITLES_FILE):
            with open(POSTED_TITLES_FILE, "r", encoding="utf-8") as file:
                return set(json.load(file))
        return set()
    except json.JSONDecodeError:
        logging.error("Error decoding posted_titles.json. Resetting file.")
        return set()

def save_posted_title(title):
    """Saves a normalized key to database or file."""
    key = get_normalized_key(title)
    today = datetime.now(local_tz).date()
    
    if supabase:
        try:
            supabase.table('posted_news').insert({
                'normalized_title': key,
                'posted_date': str(today),
                'full_title': title,
                'posted_at': datetime.now(utc_tz).isoformat()
            }).execute()
            return
        except Exception as e:
            logging.error(f"Error saving to Supabase: {e}")
            # Fallback to JSON
    
    # Fallback to JSON
    try:
        titles = load_posted_titles()
        titles.add(key)
        with open(POSTED_TITLES_FILE, "w", encoding="utf-8") as file:
            json.dump(list(titles), file)
    except Exception as e:
        logging.error(f"Error saving posted title: {e}")

def validate_image_url(image_url):
    """Validates if the image URL is accessible by fetching a small portion of the image."""
    if not image_url:
        return False
    try:
        # Fetch only the first 1KB to verify the image
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
                news_list.append({"title": title, "article_url": article_url, "article": article})
                logging.info(f"Found today's news: {title}")
            else:
                logging.info(f"Skipping (not today's news): {title} - Date: {news_date}")

        logging.info(f"Filtered today's articles: {len(news_list)}")
        return news_list

    except requests.RequestException as e:
        logging.error(f"Fetch error: {e}")
        return []

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=6))
def fetch_article_details(article_url, article):
    """Fetches article image and summary."""
    image_url = None
    summary = "No summary available."

    thumbnail = article.find("div", class_="thumbnail lazyload")
    if thumbnail and thumbnail.get("data-src"):
        img_url = thumbnail["data-src"]
        image_url = f"{BASE_URL}{img_url}" if not img_url.startswith("http") else img_url
        logging.info(f"Extracted Image URL: {image_url}")

    if article_url:
        try:
            article_response = session.get(article_url, timeout=8)
            article_response.raise_for_status()
            article_soup = BeautifulSoup(article_response.text, "html.parser")
            content_div = article_soup.find("div", class_="meat") or article_soup.find("div", class_="content")
            if content_div:
                first_paragraph = content_div.find("p")
                if first_paragraph:
                    summary = first_paragraph.get_text(strip=True)[:300] + "..." if len(first_paragraph.text) > 300 else first_paragraph.text
        except requests.RequestException as e:
            logging.error(f"Error fetching article content: {e}")

    return {"image": image_url, "summary": summary}

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
        # MediaWiki recent changes are in a list
        changes = soup.find_all("li", class_=re.compile(r"mw-changeslist-line"))

        for change in changes:
            time_tag = change.find("a", class_="mw-changeslist-date")
            if not time_tag:
                continue
            time_str = time_tag.get_text(strip=True)
            # Parse time, assuming format like "15:10, 27 September 2025"
            try:
                # Adjust for current year if not present
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

                # Create a unique title
                title = f"DC Wiki Update: {page_title}"
                summary = f"Edited by {user}. {comment}" if comment else f"Edited by {user}."

                updates_list.append({"title": title, "summary": summary, "image": None})
                logging.info(f"Found today's wiki update: {title}")

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
        # Find the LATEST TMS NEWS section
        latest_news_section = soup.find(string="LATEST TMS NEWS")
        if latest_news_section:
            parent = latest_news_section.parent
            # Find the following links
            news_links = parent.find_next_siblings("a")[:5]  # First 5 news items
            for link in news_links:
                title = link.get_text(" ", strip=True)
                url = link.get("href")
                if title and url:
                    # Create a title
                    news_title = f"TMS News: {title}"
                    summary = f"Read more: {BASE_URL_TMS}{url}" if not url.startswith("http") else f"Read more: {url}"
                    news_list.append({"title": news_title, "summary": summary, "image": None})
                    logging.info(f"Found TMS news: {title}")

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
        # Fandom uses similar structure
        changes = soup.find_all("li", class_=re.compile(r"mw-changeslist-line"))

        for change in changes:
            time_tag = change.find("a", class_="mw-changeslist-date")
            if not time_tag:
                continue
            time_str = time_tag.get_text(strip=True)
            # Parse time, assuming format like "15:10, 27 September 2025"
            try:
                # Adjust for current year if not present
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

                # Create a unique title
                title = f"Fandom Wiki Update: {page_title}"
                summary = f"Edited by {user}. {comment}" if comment else f"Edited by {user}."

                updates_list.append({"title": title, "summary": summary, "image": None})
                logging.info(f"Found today's Fandom wiki update: {title}")

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
                news_list.append({"title": f"ANN DC News: {title}", "article_url": article_url, "article": article})
                logging.info(f"Found today's DC news: {title}")
            else:
                logging.info(f"Skipping (not today's DC news): {title} - Date: {news_date}")

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
                news["summary"] = result["summary"]
            except Exception as e:
                logging.error(f"Error processing article: {e}")
                news = futures[future]
                news["image"] = None
                news["summary"] = "Failed to fetch summary."

def send_to_telegram(title, image_url, summary):
    """Posts news to Telegram with JSON-style formatting."""
    global posts_today, total_posts
    
    # Extract source from title prefix
    source = "Unknown"
    if title.startswith('DC Wiki Update: '):
        source = "Detective Conan Wiki"
    elif title.startswith('TMS News: '):
        source = "TMS Entertainment"
    elif title.startswith('Fandom Wiki Update: '):
        source = "Fandom Wiki"
    elif title.startswith('ANN DC News: '):
        source = "Anime-Planet DC"
    else:
        source = "Anime-Planet"
    
    # Clean title
    clean_title = get_normalized_key(title)
    
    # Format as standard news message
    json_message = f"""<b>{escape_html(clean_title)}</b>

{escape_html(summary) if summary else 'No summary available.'}

<i>Source: {source}</i>"""

    logging.info(f"Sending to Telegram - Title: {title}")
    logging.info(f"Image URL: {image_url}")
    logging.info(f"Message: {json_message}")

    # First, try sending with a photo if the image URL is valid
    if image_url and validate_image_url(image_url):
        try:
            response = session.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                data={
                    "chat_id": CHAT_ID,
                    "photo": image_url,
                    "caption": json_message,
                    "parse_mode": "HTML",
                },
                timeout=6,
            )
            response.raise_for_status()
            logging.info(f"Posted with photo: {title}")
            save_posted_title(title)
            posts_today += 1
            total_posts += 1
            return
        except requests.RequestException as e:
            logging.error(f"Failed to send photo for {title}: {e}")
            # Fall through to sendMessage

    # Fallback to sending a text message if photo fails or no valid image
    try:
        response = session.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": json_message,
                "parse_mode": "HTML",
            },
            timeout=10,
        )
        response.raise_for_status()
        logging.info(f"Posted as text: {title}")
        save_posted_title(title)
        posts_today += 1
        total_posts += 1
    except requests.RequestException as e:
        logging.error(f"Failed to send message for {title}: {e}")
        # Do not retry; just log and move on

def ping_bot():
    """Ping the bot to keep it alive (lightweight check)."""
    try:
        # Light ping - just check if we can reach Telegram API
        response = session.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
        response.raise_for_status()
        # Only log occasionally to reduce log spam
        pass  # Silent success
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
            logging.info(f"Webhook set successfully: {webhook_url}")
        else:
            logging.error(f"Failed to set webhook: {response.text}")
    except Exception as e:
        logging.error(f"Error setting webhook: {e}")

def run_once():
    global today_local, last_run_time, posts_today
    current_date = datetime.now(local_tz).date()
    if current_date != today_local:
        # New day, reset daily stats (database handles persistence)
        logging.info("New day detected, resetting daily stats.")
        if not supabase:
            # Only reset JSON if not using Supabase
            with open(POSTED_TITLES_FILE, "w", encoding="utf-8") as file:
                json.dump([], file)
        today_local = current_date
        posts_today = 0
    
    logging.info("Fetching latest anime news...")
    logging.info(f"Today's date (local): {today_local}")
    
    # Scrape sources with minimal delays to reduce total response time
    news_list = fetch_anime_news()
    time.sleep(1)  # Reduced delay between sources
    
    dc_updates = fetch_dc_updates()
    time.sleep(1)
    
    tms_news = fetch_tms_news()
    time.sleep(1)
    
    fandom_updates = fetch_fandom_updates()
    time.sleep(1)
    
    ann_dc_news = fetch_ann_dc_news()
    
    all_updates = news_list + dc_updates + tms_news + fandom_updates + ann_dc_news

    if not all_updates:
        logging.info("No new articles or updates to post.")
        return

    fetch_selected_articles(news_list + ann_dc_news)  # For ANN news that have articles
    
    posted_count = 0
    for update in all_updates:
        if get_normalized_key(update["title"]) not in load_posted_titles():
            send_to_telegram(update["title"], update.get("image"), update["summary"])
            posted_count += 1
            time.sleep(2)  # Reduced delay between posts
    
    logging.info(f"Posted {posted_count} new updates this cycle")
    last_run_time = datetime.now(utc_tz)
    
    # Memory cleanup
    del news_list, dc_updates, tms_news, fandom_updates, ann_dc_news, all_updates

if __name__ == "__main__":
    logging.info(f"Starting bot instance [Session ID: {SESSION_ID}]")
    
    # Force stop all other bot instances by deleting webhook multiple times
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            logging.info(f"Clearing webhooks (attempt {attempt + 1}/{max_attempts})...")
            response = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook",
                json={"drop_pending_updates": True},
                timeout=10
            )
            if response.status_code == 200:
                logging.info(f"Webhook cleared (attempt {attempt + 1})")
            time.sleep(2)  # Wait between attempts
        except Exception as e:
            logging.error(f"Failed to clear webhook (attempt {attempt + 1}): {e}")
    
    # Give time for other instances to stop
    logging.info("Waiting 10 seconds for other instances to stop...")
    time.sleep(10)
    
    # Now set up webhook for this instance
    setup_webhook()
    
    logging.info("This instance is now the primary bot")

    # Start the bot loop in a background thread
    def bot_loop():
        heartbeat_interval = 300  # 5 minutes
        last_heartbeat = time.time()
        
        # Start keep-alive pinger in background (pings every 5 minutes)
        if RENDER_EXTERNAL_URL:
             ping_thread = Thread(target=keep_alive, daemon=True, name="Pinger")
             ping_thread.start()
        
        while True:
            current_time = time.time()
            if current_time - last_heartbeat >= heartbeat_interval:
                ping_bot()
                last_heartbeat = current_time
            
            try:
                run_once()
            except Exception as e:
                logging.error(f"Critical error in run_once: {e}")
                
            logging.info("Sleeping for 4 hours...")
            
            # Sleep in chunks to allow for graceful shutdown
            for _ in range(144):  # 144 * 100 = 14400 seconds = 4 hours
                time.sleep(100)

    # Start bot thread
    bot_thread = Thread(target=bot_loop, daemon=True)
    bot_thread.start()
    
    # Run Flask server (blocks main thread)
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)