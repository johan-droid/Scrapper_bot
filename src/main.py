import os
import time
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import telebot
from telebot import types

from .utils import setup_logging, safe_log, patch_socket_ipv4
from .bot import run_once
from .config import BOT_TOKEN, ADMIN_ID
from .database import supabase

# Set Heroku worker mode
os.environ['HEROKU_WORKER_MODE'] = 'true'

# Setup
patch_socket_ipv4()
setup_logging()

# Initialize bot for commands
bot = None
if BOT_TOKEN:
    try:
        bot = telebot.TeleBot(BOT_TOKEN)
        safe_log("info", "✅ Telegram bot initialized for commands")
    except Exception as e:
        safe_log("error", f"❌ Failed to initialize Telegram bot: {e}")

# Scheduler
scheduler = BackgroundScheduler()
last_run_time = None
run_count = 0
error_count = 0

def scheduled_job():
    """Main 2-hour scraping job with error tracking"""
    global last_run_time, run_count, error_count
    
    try:
        safe_log("info", f"\n{'='*70}")
        safe_log("info", "🚀 STARTING SCHEDULED 2-HOUR SCRAPING CYCLE")
        safe_log("info", f"   Run Count: {run_count + 1}")
        safe_log("info", f"   Last Run: {last_run_time.strftime('%Y-%m-%d %H:%M:%S') if last_run_time else 'Never'}")
        safe_log("info", f"{'='*70}\n")
        
        start_time = time.time()
        run_once()
        duration = time.time() - start_time
        
        last_run_time = datetime.now()
        run_count += 1
        
        safe_log("info", f"\n{'='*70}")
        safe_log("info", f"✅ SCRAPING CYCLE COMPLETED")
        safe_log("info", f"   Duration: {duration:.1f}s")
        safe_log("info", f"   Total Runs: {run_count}")
        safe_log("info", f"   Errors: {error_count}")
        safe_log("info", f"{'='*70}\n")
        
    except Exception as e:
        error_count += 1
        safe_log("error", f"❌ Scheduled job failed: {e}", exc_info=True)
        
        # Notify admin about failure
        if bot and ADMIN_ID:
            try:
                error_msg = (
                    f"🚨 <b>Scraping Cycle Failed</b>\n\n"
                    f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"❌ Error: {str(e)[:200]}\n"
                    f"📊 Total Errors: {error_count}\n\n"
                    f"💡 The scheduler will retry in 2 hours."
                )
                bot.send_message(ADMIN_ID, error_msg, parse_mode='HTML')
            except:
                pass

def keep_worker_awake():
    """Lightweight heartbeat for Heroku 1x dyno"""
    safe_log("debug", "💓 Worker heartbeat")

# ============================================
# ADMIN COMMANDS
# ============================================

if bot and ADMIN_ID:
    
    @bot.message_handler(commands=['start'])
    def start_command(message):
        """Admin start command - bot information"""
        if str(message.from_user.id) != str(ADMIN_ID):
            bot.reply_to(message, "⛔ Unauthorized access.")
            return
        
        uptime = datetime.now() - (last_run_time or datetime.now())
        
        info_msg = (
            f"🤖 <b>Scrapper Bot - Admin Panel</b>\n"
            f"{'='*30}\n\n"
            
            f"📊 <b>Bot Status</b>\n"
            f"• Status: {'🟢 Running' if scheduler.running else '🔴 Stopped'}\n"
            f"• Mode: Heroku 1x Dyno\n"
            f"• Schedule: Every 2 hours\n"
            f"• Total Runs: {run_count}\n"
            f"• Total Errors: {error_count}\n"
            f"• Last Run: {last_run_time.strftime('%Y-%m-%d %H:%M:%S') if last_run_time else 'Never'}\n\n"
            
            f"🎯 <b>Next Scheduled Run</b>\n"
        )
        
        # Get next run time
        jobs = scheduler.get_jobs()
        for job in jobs:
            if job.id == 'scrape_job' and job.next_run_time:
                next_run = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S')
                info_msg += f"• {next_run}\n"
                break
        
        info_msg += (
            f"\n📋 <b>Available Commands</b>\n"
            f"/start - Show this info\n"
            f"/status - Detailed statistics\n"
            f"/run - Force scrape now\n"
            f"/health - System health check\n\n"
            
            f"🔧 <b>Configuration</b>\n"
            f"• Channels: {'✅' if os.getenv('ANIME_NEWS_CHANNEL_ID') and os.getenv('WORLD_NEWS_CHANNEL_ID') else '⚠️'}\n"
            f"• Database: {'✅' if supabase else '⚠️'}\n"
            f"• Admin ID: {ADMIN_ID}\n"
        )
        
        bot.reply_to(message, info_msg, parse_mode='HTML')
    
    @bot.message_handler(commands=['status'])
    def status_command(message):
        """Admin status command - detailed statistics"""
        if str(message.from_user.id) != str(ADMIN_ID):
            bot.reply_to(message, "⛔ Unauthorized access.")
            return
        
        try:
            # Get database stats
            today_posts = 0
            total_posts = 0
            anime_posts = 0
            world_posts = 0
            
            if supabase:
                try:
                    # Today's stats
                    today = datetime.now().date()
                    daily = supabase.table("daily_stats").select("posts_count, anime_posts, world_posts").eq("date", str(today)).limit(1).execute()
                    if daily.data:
                        today_posts = daily.data[0].get("posts_count", 0)
                        anime_posts = daily.data[0].get("anime_posts", 0)
                        world_posts = daily.data[0].get("world_posts", 0)
                    
                    # All-time stats
                    total = supabase.table("bot_stats").select("total_posts_all_time").limit(1).execute()
                    if total.data:
                        total_posts = total.data[0].get("total_posts_all_time", 0)
                except Exception as e:
                    safe_log("error", f"Failed to fetch stats: {e}")
            
            status_msg = (
                f"📊 <b>Bot Statistics</b>\n"
                f"{'='*30}\n\n"
                
                f"📅 <b>Today's Performance</b>\n"
                f"• Total Posts: {today_posts}\n"
                f"• Anime News: {anime_posts}\n"
                f"• World News: {world_posts}\n\n"
                
                f"🏆 <b>All-Time Stats</b>\n"
                f"• Total Posts: {total_posts:,}\n"
                f"• Bot Runs: {run_count}\n"
                f"• Error Count: {error_count}\n"
                f"• Success Rate: {((run_count - error_count) / max(run_count, 1) * 100):.1f}%\n\n"
                
                f"⏰ <b>Runtime Info</b>\n"
                f"• Last Run: {last_run_time.strftime('%Y-%m-%d %H:%M:%S') if last_run_time else 'Never'}\n"
                f"• Scheduler: {'🟢 Active' if scheduler.running else '🔴 Inactive'}\n"
            )
            
            # Get next run time
            jobs = scheduler.get_jobs()
            for job in jobs:
                if job.id == 'scrape_job' and job.next_run_time:
                    next_run = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S')
                    status_msg += f"• Next Run: {next_run}\n"
                    break
            
            bot.reply_to(message, status_msg, parse_mode='HTML')
            
        except Exception as e:
            bot.reply_to(message, f"❌ Error fetching status: {str(e)}")
    
    @bot.message_handler(commands=['run'])
    def run_command(message):
        """Admin run command - force scrape immediately"""
        if str(message.from_user.id) != str(ADMIN_ID):
            bot.reply_to(message, "⛔ Unauthorized access.")
            return
        
        try:
            bot.reply_to(message, "🚀 <b>Force scrape initiated!</b>\n\nPlease wait...", parse_mode='HTML')
            
            start_time = time.time()
            run_once()
            duration = time.time() - start_time
            
            success_msg = (
                f"✅ <b>Force scrape completed!</b>\n\n"
                f"⏱️ Duration: {duration:.1f}s\n"
                f"📊 Check your channels for new posts\n"
                f"💡 Next scheduled run in ~2 hours"
            )
            
            bot.send_message(ADMIN_ID, success_msg, parse_mode='HTML')
            
        except Exception as e:
            error_msg = (
                f"❌ <b>Force scrape failed!</b>\n\n"
                f"Error: {str(e)[:200]}\n\n"
                f"💡 Check logs for details"
            )
            bot.send_message(ADMIN_ID, error_msg, parse_mode='HTML')
    
    @bot.message_handler(commands=['health'])
    def health_command(message):
        """Admin health command - system health check"""
        if str(message.from_user.id) != str(ADMIN_ID):
            bot.reply_to(message, "⛔ Unauthorized access.")
            return
        
        health_status = []
        
        # Check scheduler
        if scheduler.running:
            health_status.append("✅ Scheduler: Running")
        else:
            health_status.append("❌ Scheduler: Stopped")
        
        # Check database
        if supabase:
            try:
                supabase.table("bot_stats").select("id").limit(1).execute()
                health_status.append("✅ Database: Connected")
            except Exception as e:
                health_status.append(f"❌ Database: Error - {str(e)[:50]}")
        else:
            health_status.append("⚠️ Database: Not configured")
        
        # Check channels
        anime_channel = os.getenv('ANIME_NEWS_CHANNEL_ID')
        world_channel = os.getenv('WORLD_NEWS_CHANNEL_ID')
        
        if anime_channel:
            health_status.append("✅ Anime Channel: Configured")
        else:
            health_status.append("⚠️ Anime Channel: Not configured")
        
        if world_channel:
            health_status.append("✅ World Channel: Configured")
        else:
            health_status.append("⚠️ World Channel: Not configured")
        
        # Check bot token
        health_status.append("✅ Bot Token: Valid")
        
        # Memory/performance
        import psutil
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        cpu_percent = process.cpu_percent(interval=1)
        
        health_msg = (
            f"🏥 <b>System Health Check</b>\n"
            f"{'='*30}\n\n"
            f"{chr(10).join(health_status)}\n\n"
            f"💻 <b>System Resources</b>\n"
            f"• Memory: {memory_mb:.1f} MB\n"
            f"• CPU: {cpu_percent:.1f}%\n"
            f"• Uptime: {run_count} runs\n"
            f"• Error Rate: {(error_count / max(run_count, 1) * 100):.1f}%\n"
        )
        
        bot.reply_to(message, health_msg, parse_mode='HTML')

def start_scheduler():
    """Initialize and start the scheduler with 2-hour intervals"""
    if not scheduler.running:
        safe_log("info", "🔧 Starting scheduler for Heroku 1x dyno...")
        
        # Main job: Every 2 hours at :00 minutes (0:00, 2:00, 4:00, etc.)
        # This ensures consistent timing
        scheduler.add_job(
            scheduled_job,
            CronTrigger(hour='*/2', minute='0'),
            id='scrape_job',
            max_instances=1,
            coalesce=True
        )
        safe_log("info", "   ✅ Main scraping job: Every 2 hours (on the hour)")
        
        # Worker heartbeat: Every 5 minutes (keep dyno awake)
        scheduler.add_job(
            keep_worker_awake,
            'interval',
            minutes=5,
            id='heartbeat_job'
        )
        safe_log("info", "   ✅ Worker heartbeat: Every 5 minutes")
        
        # Initial run: 30 seconds from now
        run_date = datetime.now() + timedelta(seconds=30)
        scheduler.add_job(
            scheduled_job,
            'date',
            run_date=run_date,
            id='initial_scrape'
        )
        safe_log("info", f"   ✅ Initial scrape: {run_date.strftime('%Y-%m-%d %H:%M:%S')}")
        
        scheduler.start()
        safe_log("info", "🚀 Scheduler started successfully!")
        safe_log("info", "📋 Schedule Summary:")
        safe_log("info", "   • Main scraping: Every 2 hours (0:00, 2:00, 4:00...)")
        safe_log("info", "   • Worker heartbeat: Every 5 minutes")
        safe_log("info", "   • Initial run: 30 seconds from now")

def start_command_listener():
    """Start Telegram command listener in background"""
    if not bot or not ADMIN_ID:
        safe_log("warn", "⚠️ Bot or Admin ID not configured - commands disabled")
        return
    
    def polling_loop():
        safe_log("info", "🤖 Starting Telegram command listener...")
        while True:
            try:
                bot.infinity_polling(timeout=60, long_polling_timeout=60)
            except Exception as e:
                safe_log("error", f"❌ Polling error: {e}")
                time.sleep(5)
    
    from threading import Thread
    listener_thread = Thread(target=polling_loop, daemon=True)
    listener_thread.start()
    safe_log("info", "✅ Command listener started in background")

# ============================================
# STARTUP
# ============================================

# Start scheduler
start_scheduler()

# Start command listener
start_command_listener()

# Keep main thread alive for Heroku
if __name__ == "__main__":
    safe_log("info", "🎯 Heroku 1x worker startup complete")
    safe_log("info", "📊 Worker configured for continuous operation")
    safe_log("info", "⏰ Ready for 2-hour scraping cycles")
    safe_log("info", "🤖 Admin commands active: /start, /status, /run, /health")
    
    try:
        # Keep main thread alive
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        safe_log("info", "🛑 Shutting down...")
        scheduler.shutdown()
        safe_log("info", "✅ Bot stopped")
