import logging
import difflib
import re
from datetime import datetime, timedelta, time
from src.config import SUPABASE_URL, SUPABASE_KEY, ANIME_NEWS_SOURCES
from src.utils import safe_log, now_local, utc_tz, local_tz

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
        logging.info("[OK] Supabase connected successfully (Anime-Only Optimized)")
    except Exception as e:
        logging.warning(f"Supabase connection failed: {e}")
        supabase = None

# Enhanced caching for anime-only bot
_posted_titles_cache = {}
_cache_timestamp = None
CACHE_DURATION = timedelta(hours=2)  # Cache for 2 hours to match bot schedule
_anime_stats_cache = {}
_stats_cache_timestamp = None

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
    """Optimized duplicate check for anime-only bot"""
    norm_title = normalize_title(title)
    
    # Fast local cache check
    if norm_title in posted_titles_set:
        safe_log("info", f"DUPLICATE (Exact): {title[:50]}")
        return True
    
    # Fuzzy matching with reduced threshold for anime content
    for existing in posted_titles_set:
        dist = difflib.SequenceMatcher(None, norm_title, existing).ratio()
        if dist > 0.85:  # High threshold for anime news
            safe_log("info", f"DUPLICATE (Fuzzy {dist:.2%}): {title[:50]}")
            return True
    
    # Optimized database check - only check recent anime posts
    if supabase:
        try:
            # Use the optimized function if available, fallback to regular query
            try:
                r = supabase.rpc("is_duplicate_anime_post", {
                    "p_normalized_title": norm_title,
                    "p_article_url": url,
                    "p_hours_back": 48  # Check last 48 hours for 2-hour schedule
                }).execute()
                if r.data and r.data[0]:
                    safe_log("info", f"DUPLICATE (Optimized DB): {title[:50]}")
                    posted_titles_set.add(norm_title)
                    return True
            except Exception:
                # Fallback to regular query if RPC function not available
                r = supabase.table("posted_news")\
                    .select("normalized_title")\
                    .eq("normalized_title", norm_title)\
                    .eq("channel_type", "anime")\
                    .gte("posted_date", (datetime.now(utc_tz) - timedelta(hours=48)).isoformat())\
                    .limit(1)\
                    .execute()
                
                if r.data:
                    safe_log("info", f"DUPLICATE (Fallback DB): {title[:50]}")
                    posted_titles_set.add(norm_title)
                    return True
        except Exception as e:
            logging.warning(f"DB duplicate check failed: {e}")
    
    return False

def initialize_bot_stats():
    """Initialize anime-only bot statistics"""
    if not supabase: return
    try:
        resp = supabase.table("bot_stats").select("*").limit(1).execute()
        if not resp.data:
            now = datetime.now(utc_tz).isoformat()
            supabase.table("bot_stats").insert({
                "bot_started_at": now, 
                "total_posts_all_time": 0,
                "total_anime_posts": 0,
                "total_world_posts": 0,
                "config_version": "anime-only-v1.0",
                "notes": "Anime-only bot initialized"
            }).execute()
            safe_log("info", "Anime-only bot stats initialized")
    except Exception as e:
        logging.error(f"Failed to initialize bot stats: {e}")

def ensure_daily_row(date_obj):
    """Ensure daily stats row exists for anime-only bot"""
    if not supabase: return
    try:
        r = supabase.table("daily_stats").select("date").eq("date", str(date_obj)).limit(1).execute()
        if not r.data:
            supabase.table("daily_stats").insert({
                "date": str(date_obj), 
                "posts_count": 0,
                "anime_posts": 0,
                "world_posts": 0
            }).execute()
    except Exception as e:
        logging.error(f"Failed to ensure daily row: {e}")

def get_telegraph_token():
    """Retrieve stored Telegraph token from database"""
    if not supabase: return None
    try:
        r = supabase.table("bot_stats").select("telegraph_token").limit(1).execute()
        if r.data and r.data[0].get('telegraph_token'):
            return r.data[0]['telegraph_token']
        return None
    except Exception as e:
        logging.warning(f"Failed to get telegraph token: {e}")
        return None

def save_telegraph_token(token):
    """Store Telegraph token for future runs"""
    if not supabase or not token: return
    try:
        # We assume row 1 exists (initialized by initialize_bot_stats)
        supabase.table("bot_stats").update({"telegraph_token": token}).eq("id", 1).execute()
        safe_log("info", "✅ Telegraph token saved to database for persistence")
    except Exception as e:
        logging.error(f"Failed to save telegraph token: {e}")

def increment_post_counters(date_obj):
    if not supabase: return
    try:
        supabase.rpc('increment_daily_stats', {'row_date': str(date_obj)}).execute()
        supabase.rpc('increment_bot_stats').execute()
    except Exception as e:
        logging.error(f"Atomic stats update failed: {e}")

def load_posted_titles(date_obj):
    """Load posted titles with anime-only optimization"""
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
        # Optimized: Only load anime posts from last 3 days
        past_date = str(date_obj - timedelta(days=3))
        r = supabase.table("posted_news")\
            .select("normalized_title, full_title")\
            .eq("channel_type", "anime")\
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
        
        safe_log("info", f"Loaded {len(titles)} anime titles from last 3 days (optimized)")
        return titles
    except Exception as e:
        logging.error(f"Failed to load posted titles: {e}")
        # Create empty cache entry on error
        _posted_titles_cache[str(date_obj)] = set()
        return set()

def record_post(title, source_code, article_url, slot, posted_titles_set, category=None, status='sent', telegraph_url=None):
    key = normalize_title(title)
    date_obj = now_local().date()
    
    # All posts are now anime only
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
        try:
            # Calculate scheduled_at (IST -> UTC)
            # Slot 0 = 00:00, Slot 1 = 02:00, etc.
            scheduled_local = local_tz.localize(datetime.combine(date_obj, time(hour=slot*2, minute=0)))
            scheduled_utc = scheduled_local.astimezone(utc_tz)
        except Exception as e:
            logging.warning(f"Failed to calculate scheduled_at: {e}")
            scheduled_utc = datetime.now(utc_tz)

        data = {
            "date": str(date_obj),
            "slot": slot,
            "scheduled_at": scheduled_utc.isoformat(),
            "status": "started",
            "started_at": datetime.now(utc_tz).isoformat()
        }
        r = supabase.table("runs").insert(data).execute()
        if r.data:
            return r.data[0]['id']
            
    except Exception as e:
        # If insertion failed, it likely means valid constraint violation (lock exists)
        # OR it means Schema Validation failed (400 Bad Request)
        # Log detailed info to debug the 400 error
        error_details = str(e)
        if hasattr(e, 'response') and hasattr(e.response, 'text'):
            error_details += f" | Body: {e.response.text}"
        
        # Check for Duplicate Run (Constraint Violation)
        if "23505" in str(e) or "runs_date_slot_key" in str(e):
             safe_log("info", f"[LOCK] Run for {date_obj} slot {slot} already exists. Checking status...")
        else:
            safe_log("error", f"Run lock insert failed: {error_details}")
            safe_log("debug", f"Payload used: {data}")
        
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
                if status in ['success', 'failed', 'skipped', 'completed']:
                    safe_log("info", f"[LOCK] Run for {date_obj} slot {slot} already finished (status: {status}).")
                    return None
                
                # If running, check timeout
                if status == 'started' and started_str:
                    try:
                        # Use a more robust parsing approach for various ISO formats
                        import re
                        from dateutil import parser as date_parser
                        
                        try:
                            # Try dateutil parser first (most robust)
                            started_at = date_parser.parse(started_str)
                        except (ValueError, ImportError):
                            # Fallback to manual parsing with regex
                            # Handle format: 2026-02-09T13:09:28.68841+00:00
                            if re.match(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+[\+\-]\d{2}:\d{2}', started_str):
                                # Extract datetime part and timezone part
                                datetime_part = started_str[:26]  # Up to microseconds
                                timezone_part = started_str[26:]   # Timezone offset
                                started_at = datetime.fromisoformat(datetime_part + timezone_part)
                            elif started_str.endswith('Z'):
                                started_at = datetime.fromisoformat(started_str.replace('Z', '+00:00'))
                            elif '+' in started_str or '-' in started_str:
                                # Already has timezone info
                                started_at = datetime.fromisoformat(started_str)
                            else:
                                # No timezone info, assume UTC
                                started_at = datetime.fromisoformat(started_str + '+00:00')
                        
                        # Ensure timezone awareness for comparison
                        if started_at.tzinfo is None:
                            started_at = utc_tz.localize(started_at)
                        elif started_at.tzinfo != utc_tz:
                            started_at = started_at.astimezone(utc_tz)
                        
                        if datetime.now(utc_tz) - started_at > timedelta(hours=2):
                            safe_log("warn", f"[LOCK] Found stale run (started {started_str}). Taking over.")
                            # Update to current time and take over
                            # Note: We return existing ID
                            supabase.table("runs").update({
                                "started_at": datetime.now(utc_tz).isoformat(),
                                "status": "started"
                            }).eq("id", existing['id']).execute()
                            return existing['id']
                        else:
                            safe_log("info", f"[LOCK] Run in progress (started {started_str}). Skipping.")
                            return None
                    except ValueError as ve:
                        safe_log("error", f"Invalid date format in started_at: {started_str} - {ve}")
                        # If we can't parse the date, assume it's stale and take over
                        safe_log("warn", f"[LOCK] Taking over run due to unparseable date.")
                        supabase.table("runs").update({
                            "started_at": datetime.now(utc_tz).isoformat(),
                            "status": "started"
                        }).eq("id", existing['id']).execute()
                        return existing['id']
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
    Fetch all anime posts for the current day to generate a detailed report.
    Returns a dict with summary stats and list of posts.
    """
    if not supabase: 
        return None
    
    try:
        date_obj = str(now_local().date())
        # Fetch only anime posts for today
        r = supabase.table("posted_news")\
            .select("source, full_title, status, posted_at, channel_type")\
            .eq("posted_date", date_obj)\
            .eq("channel_type", "anime")\
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
        logging.error(f"Failed to fetch today's anime stats: {e}")
        return None

def get_anime_statistics():
    """
    Get optimized anime statistics using cached data and efficient queries
    """
    global _anime_stats_cache, _stats_cache_timestamp
    current_time = now_local()
    
    # Check cache first (5 minute cache for stats)
    if (_stats_cache_timestamp and 
        current_time - _stats_cache_timestamp < timedelta(minutes=5)):
        return _anime_stats_cache
    
    if not supabase:
        return {
            "total_posts": 0,
            "today_posts": 0,
            "week_posts": 0,
            "month_posts": 0,
            "unique_sources": 0,
            "last_updated": None
        }
    
    try:
        # Try to use the optimized function if available
        try:
            r = supabase.rpc("get_anime_statistics").execute()
            if r.data and len(r.data) > 0:
                stats = r.data[0]
                _anime_stats_cache = stats
                _stats_cache_timestamp = current_time
                return stats
        except Exception:
            pass  # Fallback to manual queries
        
        # Fallback manual queries
        today = str(current_time.date())
        week_ago = str((current_time - timedelta(days=7)).date())
        month_ago = str((current_time - timedelta(days=30)).date())
        
        # Get counts efficiently
        total_posts = supabase.table("posted_news").select("id", count="exact")\
            .eq("channel_type", "anime").execute()
        
        today_posts = supabase.table("posted_news").select("id", count="exact")\
            .eq("channel_type", "anime").eq("posted_date", today).execute()
        
        week_posts = supabase.table("posted_news").select("id", count="exact")\
            .eq("channel_type", "anime").gte("posted_date", week_ago).execute()
        
        month_posts = supabase.table("posted_news").select("id", count="exact")\
            .eq("channel_type", "anime").gte("posted_date", month_ago).execute()
        
        sources = supabase.table("posted_news").select("source", count="exact")\
            .eq("channel_type", "anime").execute()
        
        stats = {
            "total_posts": total_posts.count or 0,
            "today_posts": today_posts.count or 0,
            "week_posts": week_posts.count or 0,
            "month_posts": month_posts.count or 0,
            "unique_sources": len(set(s.get('source') for s in sources.data if s.get('source'))),
            "last_updated": current_time.isoformat()
        }
        
        _anime_stats_cache = stats
        _stats_cache_timestamp = current_time
        
        return stats
    except Exception as e:
        logging.error(f"Failed to get anime statistics: {e}")
        return {
            "total_posts": 0,
            "today_posts": 0,
            "week_posts": 0,
            "month_posts": 0,
            "unique_sources": 0,
            "last_updated": None
        }

def run_db_cleanup():
    """
    Calls the database RPC to clean up old anime data (logs, runs, posted items > 30 days).
    This helps keep the database size within Supabase Free Tier limits.
    Anime-only optimization.
    """
    if not supabase: return
    try:
        # Try to use the optimized anime cleanup function
        try:
            result = supabase.rpc("cleanup_old_anime_posts").execute()
            if result.data:
                deleted_count = result.data[0] if isinstance(result.data, list) else result.data
                safe_log("info", f"🧹 Cleaned up {deleted_count} old anime posts")
        except Exception:
            # Fallback to regular cleanup
            supabase.rpc('cleanup_old_data').execute()
            safe_log("info", "🧹 Database cleanup executed successfully")
        
        # Also refresh materialized views if available
        try:
            supabase.rpc("refresh_anime_summary").execute()
            safe_log("info", "📊 Anime summary refreshed")
        except Exception:
            pass  # Materialized view might not exist
            
    except Exception as e:
        # Don't fail the whole bot run for this
        logging.warning(f"Database cleanup failed: {e}")
        logging.warning(f"Database cleanup failed (non-critical): {e}")
