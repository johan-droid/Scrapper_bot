from apscheduler.schedulers.background import BackgroundScheduler
from .utils import setup_logging, safe_log, patch_socket_ipv4
from .bot import run_once
from .keep_alive import keep_alive, app  # Import app for Gunicorn
import time
import requests
import os

# Set Heroku worker mode to prevent web server startup
os.environ['HEROKU_WORKER_MODE'] = 'true'

# 1. Global Setup (Runs on Import)
patch_socket_ipv4()
setup_logging()

# 2. Scheduler Setup
scheduler = BackgroundScheduler()

def scheduled_job():
    """Main 2-hour scraping job with comprehensive logging"""
    try:
        safe_log("info", "🚀 Starting scheduled 2-hour scraping cycle...")
        run_once()
        safe_log("info", "✅ 2-hour scraping cycle completed successfully")
    except Exception as e:
        safe_log("error", f"❌ Scheduled job failed: {e}", exc_info=True)

def self_ping():
    """Ping the service to keep it alive - more frequent for Heroku 1x tier"""
    try:
        url = os.getenv("EXTERNAL_URL") or os.getenv("RENDER_EXTERNAL_URL")
        # Support for Heroku (if HEROKU_APP_NAME is set, construct the URL)
        if not url and os.getenv("HEROKU_APP_NAME"):
            url = f"https://{os.getenv('HEROKU_APP_NAME')}.herokuapp.com"
            
        if not url:
            # Skip self-ping in worker mode
            safe_log("info", "No external URL available, skipping self-ping")
            return
            
        # Ping the keep-alive endpoint
        requests.get(f"{url}/", timeout=10)
        safe_log("info", f"Self-ping successful: {url}")
    except Exception as e:
        safe_log("error", f"Self-ping failed: {e}")

def keep_worker_awake():
    """Lightweight task to keep worker active and prevent sleep"""
    safe_log("info", "💓 Worker heartbeat - keeping process active")
    # Small memory operation to keep the process engaged
    import random
    _ = [random.random() for _ in range(100)]

def log_scheduler_status():
    """Log current scheduler status for monitoring"""
    jobs = scheduler.get_jobs()
    safe_log("info", f"📊 Scheduler Status: {len(jobs)} jobs running")
    for job in jobs:
        next_run = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else 'Not scheduled'
        safe_log("info", f"   📅 {job.id}: Next run at {next_run}")

from datetime import datetime, timedelta

def start_scheduler():
    """Initialize and start the scheduler with 2-hour scraping logic"""
    if not scheduler.running:
        safe_log("info", "🔧 Starting scheduler for Heroku 1x worker...")
        
        # Main job: Every 2 hours (optimized for Heroku 1x tier)
        scheduler.add_job(scheduled_job, 'interval', hours=2, id='scrape_job')
        safe_log("info", "   ✅ Main scraping job: Every 2 hours")
        
        # Keep-alive job: Every 10 minutes (only for non-Heroku environments)
        if not os.getenv("HEROKU_APP_NAME"):
            scheduler.add_job(self_ping, 'interval', minutes=10, id='ping_job')
            safe_log("info", "   ✅ Keep-alive job: Every 10 minutes")
        
        # Worker heartbeat: Every 5 minutes to prevent sleep (Heroku optimization)
        scheduler.add_job(keep_worker_awake, 'interval', minutes=5, id='heartbeat_job')
        safe_log("info", "   ✅ Worker heartbeat: Every 5 minutes")
        
        # Status logging: Every 30 minutes for monitoring
        scheduler.add_job(log_scheduler_status, 'interval', minutes=30, id='status_job')
        safe_log("info", "   ✅ Status logging: Every 30 minutes")
        
        # Initial run: 30 seconds from now (immediate after deployment)
        run_date = datetime.now() + timedelta(seconds=30)
        scheduler.add_job(scheduled_job, 'date', run_date=run_date, id='initial_scrape')
        safe_log("info", f"   ✅ Initial scrape: {run_date.strftime('%Y-%m-%d %H:%M:%S')}")
        
        scheduler.start()
        safe_log("info", "🚀 Scheduler started successfully!")
        safe_log("info", "📋 Schedule Summary:")
        safe_log("info", "   • Main scraping: Every 2 hours")
        safe_log("info", "   • Worker heartbeat: Every 5 minutes")
        safe_log("info", "   • Status logging: Every 30 minutes")
        safe_log("info", "   • Initial run: 30 seconds from now")

# 3. Start Components
# Start the scheduler
start_scheduler()

# 4. Initial Run (Non-blocking)
try:
    safe_log("info", "🎯 Heroku 1x worker startup complete")
    safe_log("info", "📊 Worker configured for continuous operation")
    safe_log("info", "⏰ Ready for 2-hour scraping cycles")
except Exception as e:
    safe_log("error", f"❌ Startup error: {e}")

if __name__ == "__main__":
    # If run directly (not via Heroku worker), keep the main thread alive
    safe_log("info", "🔧 Running in manual mode (not Heroku worker)...")
    
    # Start the web server thread (for health checks locally)
    keep_alive()
    
    # Run once immediately for testing
    safe_log("info", "🧪 Running immediate test scrape...")
    run_once()
    
    # Import command handlers
    from telegram.ext import ApplicationBuilder, CommandHandler
    from src.config import BOT_TOKEN
    from src.commands import start_command, ping_command, status_command, force_run_command
    import asyncio

    if not BOT_TOKEN:
        safe_log("error", "❌ BOT_TOKEN is missing! Cannot start Telegram listener.")
    else:
        try:
            safe_log("info", "🤖 Starting Telegram Command Listener...")
            # Build Application
            application = ApplicationBuilder().token(BOT_TOKEN).build()
            
            # Add Handlers
            application.add_handler(CommandHandler("start", start_command))
            application.add_handler(CommandHandler("ping", ping_command))
            application.add_handler(CommandHandler("status", status_command))
            application.add_handler(CommandHandler("force", force_run_command))
            
            safe_log("info", "✅ Telegram Bot listening for commands (/start, /status, /force)")
            
            # Helper to run the application polling
            # We use run_polling() which blocks, serving as our keep-alive
            application.run_polling()
            
        except Exception as e:
            safe_log("error", f"❌ Failed to start Telegram listener: {e}")
            # Fallback to simple keep-alive if listener fails
            try:
                safe_log("info", "⏳ Keeping process alive (Fallback)... (Press Ctrl+C to stop)")
                while True:
                    time.sleep(1)
            except (KeyboardInterrupt, SystemExit):
                scheduler.shutdown()
                safe_log("info", "✅ Bot stopped")
