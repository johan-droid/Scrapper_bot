from apscheduler.schedulers.background import BackgroundScheduler
from .utils import setup_logging, safe_log, now_local, patch_socket_ipv4
from .bot import run_once, send_admin_report
from .keep_alive import keep_alive, app  # Import app for Gunicorn
import time
import signal
import sys

# Scheduler setup
scheduler = BackgroundScheduler()

def scheduled_job():
    """Wrapper for run_once to handle exceptions"""
    try:
        run_once()
    except Exception as e:
        safe_log("error", f"Scheduled job failed: {e}", exc_info=True)

def start_scheduler():
    if not scheduler.running:
        scheduler.add_job(scheduled_job, 'interval', hours=4)
        scheduler.start()
        safe_log("info", "Scheduler started - running every 4 hours")

if __name__ == "__main__":
    patch_socket_ipv4()
    setup_logging()
    
    # Start web server in background thread (immediately for health checks)
    keep_alive() 

    # Start scheduler
    start_scheduler()
    
    # Run once immediately on startup
    try:
        run_once()
    except Exception as e:
        safe_log("error", f"Initial run failed: {e}", exc_info=True) 
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        safe_log("info", "Bot stopped")
