import logging
import html
import time
import requests
from collections import defaultdict
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config import (
    BOT_TOKEN, CHAT_ID, WORLD_NEWS_CHANNEL_ID, ANIME_NEWS_CHANNEL_ID, 
    ADMIN_ID, ANIME_NEWS_SOURCES, WORLD_NEWS_SOURCES, SOURCE_LABEL, 
    RSS_FEEDS, TELEGRAPH_TOKEN, DISABLE_PREVIEW
)
from src.utils import safe_log, now_local, circuit_breaker, is_today_or_yesterday, should_reset_daily_tracking, clean_text_extractor
from src.database import (
    supabase, initialize_bot_stats, ensure_daily_row, load_posted_titles, 
    record_post, update_post_status, increment_post_counters, 
    is_duplicate, normalize_title, update_telegraph_url
)
from src.telegraph_client import TelegraphClient
from src.scrapers import fetch_rss, parse_rss_robust, extract_full_article_content
from src.models import NewsItem

# Initialize Telegraph client
telegraph = TelegraphClient(access_token=TELEGRAPH_TOKEN)

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

def create_telegraph_article(item: NewsItem):
    """
    Create a Telegraph article from NewsItem with enhanced styling
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
        
        # 1. Feature Image (Top, Centered)
        main_image = item.image_url or (full_content['images'][0] if full_content['images'] else None)
        if main_image:
            telegraph_html.append(f'<figure><img src="{main_image}"><figcaption>{item.title}</figcaption></figure>')
        
        # 2. Stylish Summary Block
        if item.summary_text and len(item.summary_text) > 20:
            telegraph_html.append('<blockquote>')
            telegraph_html.append(f'<b>📝 Quick Summary:</b><br>{item.summary_text}')
            telegraph_html.append('</blockquote>')
            telegraph_html.append('<hr>')
        
        # 3. Main Content
        telegraph_html.append(full_content['html'])
        
        # 4. Footer Section
        source_name = SOURCE_LABEL.get(item.source, item.source)
        dt_str = item.publish_date.strftime("%B %d, %Y") if item.publish_date else "Just Now"
        
        telegraph_html.append('<hr>')
        telegraph_html.append('<h4>📌 Source details</h4>')
        
        footer_info = []
        footer_info.append(f'<b>📰 Source:</b> {source_name}')
        if item.category:
            footer_info.append(f'<b>🏷️ Category:</b> {item.category}')
        footer_info.append(f'<b>📅 Published:</b> {dt_str}')
        
        telegraph_html.append(f"<p>{' | '.join(footer_info)}</p>")
        
        # 5. Original Link Button-style
        telegraph_html.append(f'<p><a href="{item.article_url}">🔗 <b>Click here to view original article</b></a></p>')
        
        # Create Telegraph page
        content_html = '\n'.join(telegraph_html)
        
        result = telegraph.create_page(
            title=item.title[:256],
            content=content_html,
            author_name=f"{source_name} (via NewsBot)",
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
    Format news message with distinct styles for Anime and World news
    """
    source_name = SOURCE_LABEL.get(item.source, item.source)
    title = html.escape(str(item.title or "No Title"), quote=False)
    
    # Clean the summary text to remove any HTML tags (imgs, divs, etc)
    raw_summary = str(item.summary_text or "Check out the full story below!")
    clean_summary = clean_text_extractor(raw_summary, limit=350)
    summary = html.escape(clean_summary, quote=False)
    
    # --- ANIME NEWS STYLE ---
    if item.source not in WORLD_NEWS_SOURCES:
        # Header
        header = "🌸 <b>ANIME NEWS FLASH</b> 🌸"
        
        # Body
        msg_parts = [
            header,
            "",
            f"🗞️ <b>{title}</b>",
            "",
            f"✨ <i>{summary}</i>",
            "",
            "🌸━━━━━━━━━━━━━━━━━━━━🌸",
        ]
        
        # Metadata line
        meta_parts = []
        meta_parts.append(f"📡 <b>Source:</b> {source_name}")
        if item.category:
            cat = html.escape(str(item.category), quote=False)
            meta_parts.append(f"🏷️ <b>Category:</b> {cat}")
            
        msg_parts.append(" | ".join(meta_parts))
        
        # Date
        if item.publish_date:
            dt_str = item.publish_date.strftime("%b %d, %I:%M %p")
            msg_parts.append(f"🕒 {dt_str}")
            
        msg_parts.append("")
        
        # Links / CTA
        if item.telegraph_url:
            msg_parts.append(f"👉 <a href='{item.telegraph_url}'><b>READ FULL STORY HERE</b></a> 👈")
            msg_parts.append(f"🔗 <a href='{html.escape(item.article_url, quote=True)}'>Original Source</a>")
        else:
            msg_parts.append(f"👉 <a href='{html.escape(item.article_url, quote=True)}'><b>READ FULL STORY</b></a>")

    # --- WORLD NEWS STYLE ---
    else:
        # Header
        header = "🌍 <b>GLOBAL HEADLINES</b> 🌍"
        
        # Body
        msg_parts = [
            header,
            "",
            f"📰 <b>{title}</b>",
            "",
            f"💬 <i>{summary}</i>",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]
        
        # Metadata
        msg_parts.append(f"🏛️ <b>Source:</b> {source_name}")
        
        if item.publish_date:
            dt_str = item.publish_date.strftime("%B %d, %Y • %I:%M %p")
            msg_parts.append(f"📅 {dt_str}")
            
        msg_parts.append("")
        
        # Links / CTA
        if item.telegraph_url:
            msg_parts.append(f"📖 <a href='{item.telegraph_url}'><b>Read Detailed Coverage</b></a>")
            msg_parts.append(f"🔗 <a href='{html.escape(item.article_url, quote=True)}'>Original Article Link</a>")
        else:
            msg_parts.append(f"🔗 <a href='{html.escape(item.article_url, quote=True)}'><b>Read Full Article</b></a>")
    
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
    sess = get_fresh_telegram_session()
    
    # Try with image first
    if item.image_url:
        try:
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
            response = sess.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": target_chat_id, 
                    "text": msg, 
                    "parse_mode": "HTML",
                    "disable_web_page_preview": DISABLE_PREVIEW
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
                        "disable_web_page_preview": DISABLE_PREVIEW
                    },
                    timeout=20
                )
            
            if response.status_code == 200:
                safe_log("info", f"Sent (Text) to {target_chat_id}: {item.title[:50]}")
                success = True
            else:
                logging.error(f"[ERROR] Send failed: {response.text}")
                
        except Exception as e:
            logging.error(f"[ERROR] Send attempt failed: {e}")
            
    sess.close()

    if success:
        # Update status
        update_post_status(item.title, 'sent')
        
        # Update record with Telegraph URL if created
        if item.telegraph_url:
            update_telegraph_url(item.title, item.telegraph_url)
        
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
