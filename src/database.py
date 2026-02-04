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
        logging.info("[OK] Supabase connected successfully (Optimized for 2-hour intervals)")
    except Exception as e:
        logging.warning(f"Supabase connection failed: {e}")
        supabase = None

# Cache for reducing Supabase load
_posted_titles_cache = {}
_cache_timestamp = None
CACHE_DURATION = timedelta(hours=1)  # Cache for 1 hour to reduce DB calls

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
    
    # Reduced Supabase checks for 2-hour intervals - only check recent 3 days instead of 7
    if supabase:
        try:
            past_date = str((now_local().date() - timedelta(days=3)))
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
    # Use cache to reduce Supabase load for 2-hour intervals
    global _posted_titles_cache, _cache_timestamp
    current_time = now_local()
    
    # Check cache first
    if (_cache_timestamp and 
        current_time - _cache_timestamp < CACHE_DURATION and 
        str(date_obj) in _posted_titles_cache):
        safe_log("info", f"Using cached titles for {date_obj} (reduced DB load)")
        return _posted_titles_cache[str(date_obj)]
    
    if not supabase: 
        # Create empty cache entry
        _posted_titles_cache[str(date_obj)] = set()
        return set()
    
    try:
        # Reduced from 7 days to 3 days for 2-hour intervals
        past_date = str(date_obj - timedelta(days=3))
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
        
        # Update cache
        _posted_titles_cache[str(date_obj)] = titles
        _cache_timestamp = current_time
        
        safe_log("info", f"Loaded {len(titles)} titles from last 3 days (optimized for 2h intervals)")
        return titles
    except Exception as e:
        logging.error(f"Failed to load posted titles: {e}")
        # Create empty cache entry on error
        _posted_titles_cache[str(date_obj)] = set()
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

def start_run_lock(date_obj, slot):
    """
    Attempts to start a run lock.
    Returns run_id if successful, None if locked (already running/completed).
    """
    if not supabase: return "memory-lock"
    
    try:
        # Try to insert a new run record
        # This will fail if (date, slot) constraint is violated
        data = {
            "date": str(date_obj),
            "slot": slot,
            "status": "running",
            "started_at": datetime.now(utc_tz).isoformat()
        }
        r = supabase.table("runs").insert(data).execute()
        if r.data:
            return r.data[0]['id']
            
    except Exception as e:
        # If insertion failed, it likely means valid constraint violation (lock exists)
        # Check if the existing run is "stuck" (e.g. older than 2 hours)
        try:
            r = supabase.table("runs")\
                .select("id, status, started_at")\
                .eq("date", str(date_obj))\
                .eq("slot", slot)\
                .limit(1)\
                .execute()
                
            if r.data:
                existing = r.data[0]
                status = existing.get('status')
                started_str = existing.get('started_at')
                
                # If completed, definitely don't run again
                if status == 'completed':
                    safe_log("info", f"[LOCK] Run for {date_obj} slot {slot} already COMPLETED.")
                    return None
                
                # If running, check timeout
                if status == 'running' and started_str:
                    started_at = datetime.fromisoformat(started_str.replace('Z', '+00:00'))
                    if datetime.now(utc_tz) - started_at > timedelta(hours=2):
                        safe_log("warn", f"[LOCK] Found stale run (started {started_str}). Taking over.")
                        # Update to current time and take over
                        # Note: We return existing ID
                        supabase.table("runs").update({
                            "started_at": datetime.now(utc_tz).isoformat(),
                            "status": "running"
                        }).eq("id", existing['id']).execute()
                        return existing['id']
                    else:
                        safe_log("info", f"[LOCK] Run in progress (started {started_str}). Skipping.")
                        return None
        except Exception as ex:
             logging.error(f"Lock check failed: {ex}")
             
    return None

def end_run_lock(run_id, status, posts_sent, source_counts, error=None):
    if not supabase or not run_id or run_id == "memory-lock": return
    
    try:
        data = {
            "status": status,
            "finished_at": datetime.now(utc_tz).isoformat(),
            "posts_sent": posts_sent,
            "source_counts": source_counts,
            "error": str(error) if error else None
        }
        supabase.table("runs").update(data).eq("id", run_id).execute()
    except Exception as e:
        logging.error(f"Failed to release lock: {e}")
def get_todays_posts_stats():
    """
    Fetch all posts for the current day to generate a detailed report.
    Returns a dict with summary stats and list of posts.
    """
    if not supabase: 
        return None
    
    try:
        date_obj = str(now_local().date())
        # Fetch all posts for today
        r = supabase.table("posted_news")\
            .select("source, full_title, status, created_at, channel_type")\
            .eq("posted_date", date_obj)\
            .execute()
        
        data = r.data if r.data else []
        
        stats = {
            "total": len(data),
            "sent": sum(1 for x in data if x.get('status') == 'sent'),
            "sources": defaultdict(int),
            "posts": data
        }
        
        for item in data:
            src = item.get('source', 'Unknown')
            stats["sources"][src] += 1
            
        return stats
    except Exception as e:
        logging.error(f"Failed to fetch today's stats: {e}")
        return None
