import os
import sys
import uuid
import logging
import pytz
import re
import html
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# UTF-8 handling setup
os.environ['PYTHONIOENCODING'] = 'utf-8'

if sys.platform == "win32":
    import codecs
    try:
        import subprocess
        subprocess.run(['chcp', '65001'], shell=True, capture_output=True)
    except:
        pass
    
    try:
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
    except (AttributeError, OSError):
        pass

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, OSError):
    pass

# Logging
class UTF8StreamHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            if isinstance(msg, str):
                msg = msg.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
            stream = self.stream
            stream.write(msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[UTF8StreamHandler()],
        force=True,
    )

def generate_session_id():
    return str(uuid.uuid4())[:8]

utc_tz = pytz.utc
local_tz = pytz.timezone("Asia/Kolkata")

def now_local(): 
    return datetime.now(local_tz)

def is_today_or_yesterday(dt_to_check):
    """
    Strictly checks if the date is TODAY in the local timezone (IST).
    The user requested "NO old or previous day post".
    Although the function name is 'is_today_or_yesterday' (kept for compatibility),
    it now strictly allows ONLY today.
    """
    if not dt_to_check:
        return False
        
    # User requested "Universal time" sync but context implies "Current Day" logic.
    # We use local_tz (IST) as the primary timeline for "Today".
    today = now_local().date()
    
    check_date = dt_to_check.date() if isinstance(dt_to_check, datetime) else dt_to_check
    
    # STRICT MODE: Only allow today
    return check_date == today

def should_reset_daily_tracking():
    now = now_local()
    if now.hour == 0 and now.minute < 15:
        return True
    return False

def safe_log(level, message, *args, **kwargs):
    try:
        if not isinstance(message, str):
            message = str(message)
        message = message.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
        
        emoji_map = {
            '✅': '[OK]', '❌': '[ERROR]', '⚠️': '[WARN]', '🚫': '[BLOCKED]',
            '📍': '[ROUTE]', '🔄': '[RESET]', '📡': '[FETCH]', '📤': '[SEND]',
            '🔍': '[ENRICH]', '🚀': '[START]', '📅': '[DATE]', '🕒': '[SLOT]',
            '⏰': '[TIME]', '📚': '[LOAD]', '⏭️': '[SKIP]', '⏳': '[WAIT]',
            '🤖': '[BOT]', '📊': '[STATS]', '📈': '[TOTAL]', '🏆': '[ALL]',
            '📰': '[SOURCE]', '🏥': '[HEALTH]', '🌍': '[WORLD]', '🕵️': '[CONAN]'
        }
        
        for emoji, text in emoji_map.items():
            message = message.replace(emoji, text)
        
        getattr(logging, level.lower())(message, *args, **kwargs)
    except Exception:
        try:
            print(f"[{level.upper()}] {message}")
        except:
            print(f"[{level.upper()}] <encoding error>")

def clean_text_extractor(html_text_or_element, limit=350):
    if not html_text_or_element: 
        return "No summary available."

    if hasattr(html_text_or_element, "get_text"):
        soup = html_text_or_element
    else:
        raw_str = str(html_text_or_element)
        # Check if it looks like HTML, otherwise just return it
        if "<" in raw_str and ">" in raw_str:
             soup = BeautifulSoup(raw_str, "html.parser")
        else:
             return raw_str[:limit]

    # Remove all script, style, header, footer, AND standard HTML containers that might clutter text
    for tag in soup(["script", "style", "header", "footer", "nav", "form", "iframe", "img", "figure"]):
        tag.decompose()
        
    text = soup.get_text(separator=" ")
    
    # URL removal
    text = re.sub(r'http\S+', '', text)
    
    # normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # decode entities
    text = html.unescape(text) # Ensure standard library import if needed, or stick to simple replacements
    text = text.replace('â€™', "'").replace('â€"', "—").replace('&nbsp;', ' ')
    
    if len(text) > limit:
        return text[:limit-3].strip() + "..."
    return text

from collections import defaultdict

class SourceCircuitBreaker:
    def __init__(self, failure_threshold=3, recovery_timeout=300):
        self.failure_counts = defaultdict(int)
        self.failure_threshold = failure_threshold
    
    def can_call(self, source):
        return self.failure_counts[source] < self.failure_threshold
    
    def record_success(self, source):
        self.failure_counts[source] = 0
    
    def record_failure(self, source):
        self.failure_counts[source] += 1

circuit_breaker = SourceCircuitBreaker()

def patch_socket_ipv4():
    """
    Monkey-patch socket.getaddrinfo to force IPv4
    Useful for environments where IPv6 is flaky (like some GH Actions runners)
    """
    import socket
    
    real_getaddrinfo = socket.getaddrinfo

    def new_getaddrinfo(*args, **kwargs):
        # Force AF_INET (IPv4)
        if 'family' in kwargs:
            kwargs['family'] = socket.AF_INET
        elif len(args) >= 3:
            # args[0]=host, args[1]=port, args[2]=family
            # We want to force family to AF_INET
            new_args = list(args)
            new_args[2] = socket.AF_INET 
            args = tuple(new_args)
        else:
            # If family wasn't provided in args (len < 3), pass it as kwarg
            kwargs['family'] = socket.AF_INET
            
        return real_getaddrinfo(*args, **kwargs)

    socket.getaddrinfo = new_getaddrinfo
