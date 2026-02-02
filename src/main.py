from .utils import setup_logging, safe_log, now_local, patch_socket_ipv4
from .bot import run_once, send_admin_report
import time

if __name__ == "__main__":
    patch_socket_ipv4() # Force IPv4 for stability
    setup_logging()
    try:
        run_once()
    except KeyboardInterrupt:
        safe_log("info", "Bot stopped by user")
    except Exception as e:
        safe_log("error", f"FATAL ERROR: {e}", exc_info=True)
        try:
            send_admin_report("failed", 0, {}, error=str(e))
        except: 
            pass
        exit(1)
