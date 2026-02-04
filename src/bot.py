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
    is_duplicate, normalize_title, update_telegraph_url,
    start_run_lock, end_run_lock
)
from src.telegraph_client import TelegraphClient
from src.scrapers import fetch_rss, parse_rss_robust, extract_full_article_content
from src.models import NewsItem

# Initialize Telegraph client
telegraph = TelegraphClient(access_token=TELEGRAPH_TOKEN)

def get_fresh_telegram_session():
    """Create a fresh Telegram session with retries and proper configuration"""
    tg_session = requests.Session()
    retry_strategy = Retry(
        total=3, 
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST", "GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    tg_session.mount("https://", adapter)
    tg_session.headers.update({"Connection": "close"})
    return tg_session

def create_telegraph_article(item: NewsItem):
    """
    Create a Telegraph article from NewsItem with enhanced styling and metadata
    Returns Telegraph URL or None
    """
    try:
        # Extract full content
        full_content = extract_full_article_content(item.article_url, item.source)
        
        if not full_content or not full_content['html']:
            logging.debug(f"No content extracted for {item.title}")
            return None
        
        # Build Telegraph content with professional structure
        telegraph_html = []
        
        # 1. Hero Image Section (if available)
        main_image = item.image_url or (full_content['images'][0] if full_content['images'] else None)
        if main_image:
            telegraph_html.append(f'<figure>')
            telegraph_html.append(f'<img src="{main_image}">')
            telegraph_html.append(f'<figcaption>{html.escape(item.title)}</figcaption>')
            telegraph_html.append(f'</figure>')
        
        # 2. Article Metadata (Byline)
        source_name = SOURCE_LABEL.get(item.source, item.source)
        
        metadata_parts = []
        if item.author:
            metadata_parts.append(f'<strong>By {html.escape(item.author)}</strong>')
        metadata_parts.append(f'<strong>{source_name}</strong>')
        
        if item.publish_date:
            date_str = item.publish_date.strftime("%B %d, %Y at %I:%M %p %Z")
            metadata_parts.append(f'<em>{date_str}</em>')
        
        if metadata_parts:
            telegraph_html.append(f'<p><em>{" • ".join(metadata_parts)}</em></p>')
            telegraph_html.append('<hr>')
        
        # 3. Summary/Lede (if available and substantial)
        if item.summary_text and len(item.summary_text) > 50:
            telegraph_html.append('<blockquote>')
            telegraph_html.append(f'<strong>📝 At a Glance:</strong><br>{html.escape(item.summary_text)}')
            telegraph_html.append('</blockquote>')
            telegraph_html.append('<hr>')
        
        # 4. Main Article Content
        telegraph_html.append(full_content['html'])
        
        # 5. Additional Images Gallery (if multiple images)
        if len(full_content['images']) > 1:
            telegraph_html.append('<hr>')
            telegraph_html.append('<h4>📸 Image Gallery</h4>')
            for img_url in full_content['images'][1:4]:  # Max 3 additional images
                telegraph_html.append(f'<figure><img src="{img_url}"></figure>')
        
        # 6. Footer Section with Attribution
        telegraph_html.append('<hr>')
        telegraph_html.append('<h4>📌 Article Information</h4>')
        
        footer_info = []
        footer_info.append(f'<p><strong>📰 Source:</strong> {source_name}</p>')
        
        if item.category:
            footer_info.append(f'<p><strong>🏷️ Category:</strong> {html.escape(item.category)}</p>')
        
        if item.publish_date:
            pub_date_full = item.publish_date.strftime("%A, %B %d, %Y at %I:%M %p %Z")
            footer_info.append(f'<p><strong>📅 Published:</strong> {pub_date_full}</p>')
        
        telegraph_html.extend(footer_info)
        
        # 7. Original Source Link (Call-to-Action)
        telegraph_html.append('<br>')
        telegraph_html.append(f'<p><a href="{item.article_url}">🔗 <strong>View Original Article</strong></a></p>')
        
        # Create Telegraph page
        content_html = '\n'.join(telegraph_html)
        
        # Clean title for Telegraph (remove special characters that might cause issues)
        clean_title = item.title.replace('\n', ' ').replace('\r', '').strip()[:256]
        
        result = telegraph.create_page(
            title=clean_title,
            content=content_html,
            author_name=f"{source_name} (via News Bot)",
            author_url=item.article_url
        )
        
        if result and result.get('url'):
            item.telegraph_url = result['url']
            logging.info(f"[OK] Telegraph created: {result['url']}")
            return result['url']
        else:
            logging.warning(f"Telegraph creation returned no URL for: {item.title[:50]}")
            return None
            
    except Exception as e:
        logging.error(f"Telegraph creation failed for '{item.title[:50]}': {e}")
        return None

def get_target_channel(source):
    """Determine target Telegram channel based on source"""
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
    Format news message with professional, distinct styles for Anime and World news
    Both styles are now consistent with Telegraph integration
    """
    source_name = SOURCE_LABEL.get(item.source, item.source)
    
    # Escape HTML special characters
    title = html.escape(str(item.title or "No Title"), quote=False)
    
    # Clean and truncate summary
    raw_summary = str(item.summary_text or "Read the full story below!")
    clean_summary = clean_text_extractor(raw_summary, limit=400)
    summary = html.escape(clean_summary, quote=False)
    
    # Format publish date
    if item.publish_date:
        date_str = item.publish_date.strftime("%B %d, %Y")
        time_str = item.publish_date.strftime("%I:%M %p %Z")
    else:
        date_str = "Recently"
        time_str = ""
    
    # Category formatting
    category_str = ""
    if item.category:
        cat = html.escape(str(item.category), quote=False)
        category_str = f"🏷️ <b>Category:</b> {cat}"
    
    # --- ANIME NEWS STYLE ---
    if item.source in ANIME_NEWS_SOURCES:
        header = "✨ <b>ANIME NEWS UPDATE</b> ✨"
        
        msg_parts = [
            header,
            "",
            f"📰 <b>{title}</b>",
            "",
            f"<i>{summary}</i>",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━",
        ]
        
        # Metadata section
        metadata = [f"📡 <b>Source:</b> {source_name}"]
        if category_str:
            metadata.append(category_str)
        if item.author:
            author = html.escape(str(item.author), quote=False)
            metadata.append(f"✍️ <b>By:</b> {author}")
        
        msg_parts.append(" | ".join(metadata))
        
        # Date/Time
        if time_str:
            msg_parts.append(f"📅 {date_str} • 🕐 {time_str}")
        else:
            msg_parts.append(f"📅 {date_str}")
        
        msg_parts.append("")
        
        # Call-to-Action with Telegraph priority
        if item.telegraph_url:
            msg_parts.append("━━━━━━━━━━━━━━━━━━━━━━━")
            msg_parts.append(f"📖 <a href='{item.telegraph_url}'><b>READ FULL ARTICLE</b></a> (Ad-Free)")
            msg_parts.append(f"🔗 <a href='{html.escape(item.article_url, quote=True)}'>Original Source</a>")
        else:
            msg_parts.append("━━━━━━━━━━━━━━━━━━━━━━━")
            msg_parts.append(f"📖 <a href='{html.escape(item.article_url, quote=True)}'><b>READ FULL ARTICLE</b></a>")
    
    # --- WORLD NEWS STYLE ---
    else:
        header = "🌍 <b>WORLD NEWS BRIEFING</b> 🌍"
        
        msg_parts = [
            header,
            "",
            f"<b>{title}</b>",
            "",
            f"<i>{summary}</i>",
            "",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ]
        
        # Metadata
        msg_parts.append(f"🏛️ <b>Source:</b> {source_name}")
        
        if category_str:
            msg_parts.append(category_str)
        
        if item.author:
            author = html.escape(str(item.author), quote=False)
            msg_parts.append(f"✍️ <b>Reported By:</b> {author}")
        
        # Date/Time
        if time_str:
            msg_parts.append(f"📅 {date_str} at {time_str}")
        else:
            msg_parts.append(f"📅 {date_str}")
        
        msg_parts.append("")
        
        # Call-to-Action
        if item.telegraph_url:
            msg_parts.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            msg_parts.append(f"📰 <a href='{item.telegraph_url}'><b>Read Full Coverage</b></a> (Clean Format)")
            msg_parts.append(f"🔗 <a href='{html.escape(item.article_url, quote=True)}'>Original Article</a>")
        else:
            msg_parts.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            msg_parts.append(f"📰 <a href='{html.escape(item.article_url, quote=True)}'><b>Read Full Coverage</b></a>")
    
    return "\n".join(msg_parts)

def send_to_telegram(item: NewsItem, slot, posted_set):
    """
    Send news to Telegram with Telegraph integration and robust error handling
    """
    # Spam detection (triple-layer check)
    if is_duplicate(item.title, item.article_url, posted_set):
        logging.info(f"[BLOCKED] Skipping duplicate: {item.title[:50]}")
        return False

    # Record attempt in database first
    if not record_post(item.title, item.source, item.article_url, slot, posted_set, 
                      item.category, status='attempted'):
        logging.warning("[WARN] Failed to record attempt, skipping to avoid spam")
        return False
    
    # Create Telegraph article (with rate limiting)
    try:
        telegraph_url = create_telegraph_article(item)
        if telegraph_url:
            item.telegraph_url = telegraph_url
            time.sleep(0.5)  # Brief delay after Telegraph creation
    except Exception as e:
        logging.warning(f"Telegraph creation error, using original link: {e}")
        item.telegraph_url = None
    
    # Get target channel
    target_chat_id = get_target_channel(item.source)
    
    # Format message
    msg = format_news_message(item)
    
    success = False
    sess = get_fresh_telegram_session()
    
    # Try sending with image first
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
                # Don't retry here, will fall through to text
            else:
                logging.warning(f"[WARN] Image send failed ({response.status_code}): {response.text[:200]}")
                
        except Exception as e:
            logging.warning(f"[WARN] Image send exception: {e}")

    # Fallback to text message
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
            
            # Handle rate limiting
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 30))
                logging.warning(f"[WAIT] Rate limited on text send. Sleeping {retry_after}s")
                time.sleep(retry_after)
                
                # Retry once
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
                logging.error(f"[ERROR] Send failed ({response.status_code}): {response.text[:200]}")
                
        except Exception as e:
            logging.error(f"[ERROR] Send exception: {e}")
            
    sess.close()

    # Update status in database
    if success:
        update_post_status(item.title, 'sent')
        
        # Update Telegraph URL if created
        if item.telegraph_url:
            update_telegraph_url(item.title, item.telegraph_url)
        
        # Add to in-memory set
        key = normalize_title(item.title)
        posted_set.add(key)
        
        # Increment counters
        increment_post_counters(now_local().date())
        
        return True
    else:
        update_post_status(item.title, 'failed')
        return False

def send_admin_report(status, posts_sent, source_counts, error=None):
    """Send comprehensive admin report with Telegraph statistics"""
    if not ADMIN_ID: 
        return

    dt = now_local()
    date_str = str(dt.date())
    slot = dt.hour // 4
    
    # Calculate category breakdowns
    anime_posts = sum(count for source, count in source_counts.items() if source in ANIME_NEWS_SOURCES)
    world_posts = sum(count for source, count in source_counts.items() if source in WORLD_NEWS_SOURCES)
    
    # Get daily and all-time totals from database
    daily_total = 0
    all_time_total = 0
    if supabase:
        try:
            d = supabase.table("daily_stats").select("posts_count").eq("date", date_str).limit(1).execute()
            if d.data: 
                daily_total = d.data[0].get("posts_count", 0)
            
            b = supabase.table("bot_stats").select("total_posts_all_time").limit(1).execute()
            if b.data: 
                all_time_total = b.data[0].get("total_posts_all_time", 0)
        except Exception as e:
            logging.warning(f"Failed to fetch stats for admin report: {e}")
    
    # System health warnings
    health_warnings = []
    if error:
        health_warnings.append(f"⚠️ <b>Error:</b> {html.escape(str(error)[:150], quote=False)}")
    
    for source, count in circuit_breaker.failure_counts.items():
        if count >= circuit_breaker.failure_threshold:
            health_warnings.append(f"🔴 <b>Source Down:</b> {source} ({count} consecutive failures)")
    
    health_status = "✅ <b>All Systems Operational</b>" if not health_warnings else "\n".join(health_warnings)

    # Source breakdown
    source_stats = "\n".join([f"• <b>{SOURCE_LABEL.get(k, k)}:</b> {v}" for k, v in sorted(source_counts.items(), key=lambda x: x[1], reverse=True)])
    if not source_stats: 
        source_stats = "• No new posts this cycle"

    # Build report
    report_msg = (
        f"🤖 <b>News Bot Status Report</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        f"📅 <b>Run Details</b>\n"
        f"• Date: {date_str}\n"
        f"• Time Slot: {slot} ({dt.strftime('%I:%M %p %Z')})\n"
        f"• Status: <b>{status.upper()}</b>\n\n"
        
        f"📊 <b>This Cycle</b>\n"
        f"• Posts Sent: <b>{posts_sent}</b>\n"
        f"• Anime News: {anime_posts}\n"
        f"• World News: {world_posts}\n\n"
        
        f"📈 <b>Cumulative Stats</b>\n"
        f"• Today's Total: <b>{daily_total}</b>\n"
        f"• All-Time Total: <b>{all_time_total:,}</b>\n\n"
        
        f"📰 <b>Source Breakdown</b>\n{source_stats}\n\n"
        
        f"🏥 <b>System Health</b>\n{health_status}"
    )

    sess = get_fresh_telegram_session()
    try:
        response = sess.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", 
            json={
                "chat_id": ADMIN_ID, 
                "text": report_msg, 
                "parse_mode": "HTML"
            }, 
            timeout=20
        )
        
        if response.status_code == 200:
            safe_log("info", "Admin report sent successfully")
        else:
            logging.warning(f"Admin report send failed: {response.status_code}")
            
    except Exception as e:
        logging.error(f"[ERROR] Failed to send admin report: {e}")
    finally:
        sess.close()

def run_once():
    """
    Main execution with Telegraph integration and comprehensive error handling
    """
    dt = now_local()
    date_obj = dt.date()
    slot = dt.hour // 4
    
    # Attempt to acquire run lock
    run_id = start_run_lock(date_obj, slot)
    if not run_id:
        safe_log("info", f"[LOCK] Run for {date_obj} slot {slot} already completed or in progress")
        return

    run_status = "success"
    run_error = None
    sent_count = 0
    source_counts = defaultdict(int)

    try:
        safe_log("info", f"\n{'='*70}")
        safe_log("info", f"🚀 STARTING NEWS BOT RUN (Telegraph Edition)")
        safe_log("info", f"{'='*70}")
        safe_log("info", f"📅 Date: {date_obj}")
        safe_log("info", f"🕐 Slot: {slot} ({dt.strftime('%I:%M %p %Z')})")
        safe_log("info", f"🆔 Run ID: {run_id}")
        safe_log("info", f"{'='*70}\n")
        
        # Check for new day reset
        if should_reset_daily_tracking():
            safe_log("info", "🔄 NEW DAY DETECTED - Resetting daily tracking")
        
        # Initialize database
        initialize_bot_stats()
        ensure_daily_row(date_obj)
        
        # Load posted titles for deduplication
        posted_set = load_posted_titles(date_obj)
        all_items = []
        
        safe_log("info", "📡 FETCHING NEWS FROM SOURCES...\n")
        
        # Fetch from all RSS feeds
        for code, url in RSS_FEEDS.items():
            if circuit_breaker.can_call(code):
                source_label = SOURCE_LABEL.get(code, code)
                logging.info(f"  🔍 Fetching {source_label} ({code})...")
                
                items = fetch_rss(url, code, lambda s: parse_rss_robust(s, code))
                
                if items:
                    all_items.extend(items)
                    logging.info(f"    ✅ Found {len(items)} items")
                else:
                    logging.info(f"    ⚠️ No items found")
            else:
                logging.warning(f"  ⏭️ Skipping {code} (circuit breaker open)")

        safe_log("info", f"\n📤 POSTING TO TELEGRAM (with Telegraph)...\n")
        
        # Process and post items
        for item in all_items:
            if not item.title: 
                continue
            
            # Date filtering (strict: only today/yesterday)
            if item.publish_date and not is_today_or_yesterday(item.publish_date):
                logging.debug(f"[SKIP] Old news ({item.publish_date.date()}): {item.title[:50]}")
                continue
            
            # Attempt to send
            if send_to_telegram(item, slot, posted_set):
                sent_count += 1
                source_counts[item.source] += 1
                time.sleep(2.0)  # Rate limiting (Telegram + Telegraph)
            else:
                logging.warning(f"[FAIL] Could not send: {item.title[:50]}")

        safe_log("info", f"\n{'='*70}")
        safe_log("info", f"✅ RUN COMPLETE")
        safe_log("info", f"{'='*70}")
        safe_log("info", f"📊 Posts Sent: {sent_count}")
        safe_log("info", f"📰 Sources: {len(source_counts)}")
        safe_log("info", f"{'='*70}\n")
        
        # Send admin report
        send_admin_report("success", sent_count, source_counts)

    except Exception as e:
        logging.error(f"❌ Run failed with error: {e}", exc_info=True)
        run_status = "failed"
        run_error = str(e)
        send_admin_report("failure", sent_count, source_counts, error=e)
        
    finally:
        # Release lock and update run status
        end_run_lock(run_id, run_status, sent_count, source_counts, run_error)
