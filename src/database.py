import logging
import difflib
import re
from datetime import datetime, timedelta
from src.config import SUPABASE_URL, SUPABASE_KEY, WORLD_NEWS_SOURCES, ANIME_NEWS_SOURCES
from src.utils import safe_log, now_local, utc_tz

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
        dist = difflib.SequenceMatcher(None, norm_title, existing).ratio()
        if dist > 0.85:
            safe_log("info", f"DUPLICATE (Fuzzy {dist:.2%}): {title[:50]}")
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
    
    for p_title in posted_titles_set:
         # Double check in set for fuzzy match again if needed or rely on above
         pass

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

def update_telegraph_url(title, telegraph_url):
    if not supabase: return
    try:
        key = normalize_title(title)
        date_obj = str(now_local().date())
        supabase.table("posted_news")\
            .update({"telegraph_url": telegraph_url})\
            .eq("normalized_title", key)\
            .eq("posted_date", date_obj)\
            .execute()
    except:
        pass
