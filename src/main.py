import os
import sys
import logging
from .utils import setup_logging, safe_log, patch_socket_ipv4
from .bot import run_once
from .config import ADMIN_ID
from .database import supabase

# Setup
patch_socket_ipv4()
setup_logging()

def main():
    """
    Main entry point for GitHub Actions Cron Job.
    Runs a single scraping cycle and exits.
    """
    safe_log("info", f"\n{'='*70}")
    safe_log("info", "🚀 STARTING GITHUB ACTIONS SCRAPER RUN")
    safe_log("info", f"{'='*70}\n")

    try:
        # Run the scraping cycle once
        run_once()
        
        safe_log("info", f"\n{'='*70}")
        safe_log("info", "✅ CRON JOB COMPLETED SUCCESSFULLY")
        safe_log("info", f"{'='*70}\n")
        sys.exit(0)
        
    except Exception as e:
        safe_log("critical", f"❌ CRITICAL ERROR IN MAIN LOOP: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
