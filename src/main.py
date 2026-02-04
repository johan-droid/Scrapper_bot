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
    """Wrapper for run_once to handle exceptions"""
    try:
        run_once()
    except Exception as e:
        safe_log("error", f"Scheduled job failed: {e}", exc_info=True)

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
    safe_log("info", "Worker heartbeat - keeping process active")
    # Small memory operation to keep the process engaged
    import random
    _ = [random.random() for _ in range(100)]

from datetime import datetime, timedelta
from src.commands import start_bot_listener

def start_scheduler():
    if not scheduler.running:
        # Main job: Every 2 hours (reduced from 4 hours)
        scheduler.add_job(scheduled_job, 'interval', hours=2, id='scrape_job')
        
        # Keep-alive job: Every 10 minutes (more frequent for 1x tier)
        # Skip in Heroku worker mode as workers don't need keep-alive
        if not os.getenv("HEROKU_APP_NAME"):
            scheduler.add_job(self_ping, 'interval', minutes=10, id='ping_job')
        
        # Worker heartbeat: Every 5 minutes to prevent sleep
        scheduler.add_job(keep_worker_awake, 'interval', minutes=5, id='heartbeat_job')
        
        # Initial run: 30 seconds from now (to execute immediately after deployment)
        run_date = datetime.now() + timedelta(seconds=30)
        scheduler.add_job(scheduled_job, 'date', run_date=run_date, id='initial_scrape')
        
        scheduler.start()
        safe_log("info", f"Scheduler started - Scraping every 2h, Heartbeat every 5m. Initial scrape scheduled at {run_date}")
        
        # Start the Telegram command listener (Daemon thread)
        start_bot_listener()

# 3. Start Components
# Start the scheduler
start_scheduler()

# 4. Initial Run (Non-blocking)
# We don't want to block the import, so we can schedule the first run 
# to happen shortly after startup if needed, or just rely on the interval.
# For now, let's execute it once safely if not in a worker restart loop
try:
    # Check if we are in the main process
    safe_log("info", "Heroku 1x worker startup complete - Optimized for continuous operation")
except Exception:
    pass

if __name__ == "__main__":
    # If run directly (not via Gunicorn), keep the main thread alive
    safe_log("info", "Running in manual mode...")
    
    # Start the web server thread (for health checks locally)
    keep_alive()
    
    # Run once immediately for testing
    # run_once() # Commented out to avoid double run on simple startup test
    
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        safe_log("info", "Bot stopped")
