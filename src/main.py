from apscheduler.schedulers.background import BackgroundScheduler
from .utils import setup_logging, safe_log, patch_socket_ipv4
from .bot import run_once
from .keep_alive import keep_alive, app  # Import app for Gunicorn
import time
import requests
import os

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
    """Ping the service to keep it alive"""
    try:
        url = os.getenv("EXTERNAL_URL") or os.getenv("RENDER_EXTERNAL_URL")
        # Support for Heroku (if HEROKU_APP_NAME is set, construct the URL)
        if not url and os.getenv("HEROKU_APP_NAME"):
            url = f"https://{os.getenv('HEROKU_APP_NAME')}.herokuapp.com"
            
        if not url:
            url = "http://127.0.0.1:10000"
            
        # Ping the keep-alive endpoint
        requests.get(f"{url}/", timeout=10)
        safe_log("info", f"Self-ping successful: {url}")
    except Exception as e:
        safe_log("error", f"Self-ping failed: {e}")

from datetime import datetime, timedelta

def start_scheduler():
    if not scheduler.running:
        # Main job: Every 4 hours
        scheduler.add_job(scheduled_job, 'interval', hours=4, id='scrape_job')
        
        # Keep-alive job: Every 14 minutes (Render sleeps after 15 mins of inactivity)
        scheduler.add_job(self_ping, 'interval', minutes=14, id='ping_job')
        
        # Initial run: 20 seconds from now (to execute immediately after deployment)
        run_date = datetime.now() + timedelta(seconds=20)
        scheduler.add_job(scheduled_job, 'date', run_date=run_date, id='initial_scrape')
        
        scheduler.start()
        safe_log("info", f"Scheduler started - Scraping every 4h, Pinging every 14m. Initial scrape scheduled at {run_date}")

# 3. Start Components
# Start the scheduler
start_scheduler()

# 4. Initial Run (Non-blocking)
# We don't want to block the import, so we can schedule the first run 
# to happen shortly after startup if needed, or just rely on the interval.
# For now, let's execute it once safely if not in a worker restart loop
try:
    # Check if we are in the main process
    safe_log("info", "Application startup complete")
except Exception:
    pass

if __name__ == "__main__":
    # If run directly (not via Gunicorn), keep the main thread alive
    safe_log("info", "Running in manual mode...")
    
    # Start the web server thread (for health checks locally)
    keep_alive()
    
    # Run once immediately for testing
    run_once()
    
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        safe_log("info", "Bot stopped")
