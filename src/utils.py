import os
import sys
import uuid
import logging
import pytz
import re
import html
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

# UTF-8 handling setup for cross-platform compatibility
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

# Logging setup
class UTF8StreamHandler(logging.StreamHandler):
    """Custom handler that ensures UTF-8 encoding for all log messages"""
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
    """Configure logging with UTF-8 support and proper formatting"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[UTF8StreamHandler()],
        force=True,
    )

def generate_session_id():
    """Generate a unique session ID for tracking"""
    return str(uuid.uuid4())[:8]

# Timezone configuration
utc_tz = pytz.utc
local_tz = pytz.timezone("Asia/Kolkata")  # IST

def now_local(): 
    """Get current time in local timezone (IST)"""
    return datetime.now(local_tz)

def is_today_or_yesterday(dt_to_check):
    """
    Check if a datetime is today or yesterday in local timezone
    This allows recent news from both days to be posted
    
    Args:
        dt_to_check: datetime object or date object to check
    
    Returns:
        bool: True if date is today or yesterday, False otherwise
    """
    if not dt_to_check:
        return False
    
    # Get current local time
    now = now_local()
    today = now.date()
    yesterday = today - timedelta(days=1)
    
    # Convert to date if datetime
    if isinstance(dt_to_check, datetime):
        # Ensure timezone awareness
        if dt_to_check.tzinfo is None:
            dt_to_check = local_tz.localize(dt_to_check)
        
        # Convert to local timezone
        check_date = dt_to_check.astimezone(local_tz).date()
    else:
        check_date = dt_to_check
    
    # Allow today or yesterday
    return check_date in [today, yesterday]

def should_reset_daily_tracking():
    """
    Check if we should reset daily tracking (new day started)
    Returns True if current time is within the first 15 minutes of midnight
    """
    now = now_local()
    if now.hour == 0 and now.minute < 15:
        return True
    return False

def safe_log(level, message, *args, **kwargs):
    """
    Safely log messages with UTF-8 encoding and emoji conversion
    
    Args:
        level: Log level (info, warning, error, debug)
        message: Message to log
    """
    try:
        if not isinstance(message, str):
            message = str(message)
        
        # Ensure UTF-8 encoding
        message = message.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
        
        # Emoji to text mapping for compatibility
        emoji_map = {
            '✅': '[OK]', '❌': '[ERROR]', '⚠️': '[WARN]', '🚫': '[BLOCKED]',
            '📍': '[ROUTE]', '🔄': '[RESET]', '📡': '[FETCH]', '📤': '[SEND]',
            '🔍': '[ENRICH]', '🚀': '[START]', '📅': '[DATE]', '🕒': '[SLOT]',
            '⏰': '[TIME]', '📚': '[LOAD]', '⏭️': '[SKIP]', '⏳': '[WAIT]',
            '🤖': '[BOT]', '📊': '[STATS]', '📈': '[TOTAL]', '🏆': '[ALL]',
            '📰': '[SOURCE]', '🏥': '[HEALTH]', '🌍': '[WORLD]', '🕵️': '[CONAN]',
            '🆔': '[ID]', '🕐': '[CLOCK]', '✨': '[STAR]', '🔗': '[LINK]',
            '📖': '[BOOK]', '💬': '[CHAT]', '🏛️': '[BUILDING]', '📸': '[CAMERA]',
            '🎯': '[TARGET]', '💡': '[IDEA]', '🔴': '[RED]', '🟢': '[GREEN]'
        }
        
        for emoji, text in emoji_map.items():
            message = message.replace(emoji, text)
        
        # Log with appropriate level
        getattr(logging, level.lower())(message, *args, **kwargs)
        
    except Exception:
        try:
            print(f"[{level.upper()}] {message}")
        except:
            print(f"[{level.upper()}] <encoding error>")

def clean_text_extractor(html_text_or_element, limit=400):
    """
    Extract clean text from HTML content with improved filtering
    
    Args:
        html_text_or_element: HTML string or BeautifulSoup element
        limit: Maximum character length
    
    Returns:
        str: Clean text extracted from HTML
    """
    if not html_text_or_element: 
        return "No summary available."

    # Convert to BeautifulSoup if needed
    if hasattr(html_text_or_element, "get_text"):
        soup = html_text_or_element
    else:
        raw_str = str(html_text_or_element)
        # Check if it looks like HTML
        if "<" in raw_str and ">" in raw_str:
            soup = BeautifulSoup(raw_str, "html.parser")
        else:
            # Not HTML, just clean and return
            text = raw_str.strip()
            text = re.sub(r'\s+', ' ', text)
            if len(text) > limit:
                return text[:limit-3].strip() + "..."
            return text

    # Remove unwanted tags and their content
    for tag in soup(["script", "style", "header", "footer", "nav", "form", 
                     "iframe", "img", "figure", "video", "audio", "noscript"]):
        tag.decompose()
    
    # Extract text with space separator
    text = soup.get_text(separator=" ")
    
    # Remove URLs
    text = re.sub(r'http\S+', '', text)
    text = re.sub(r'www\.\S+', '', text)
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    # Decode HTML entities
    text = html.unescape(text)
    
    # Fix common encoding issues
    text = text.replace('â€™', "'")
    text = text.replace('â€"', "—")
    text = text.replace('â€"', "–")
    text = text.replace('&nbsp;', ' ')
    text = text.replace('\xa0', ' ')
    
    # Remove multiple consecutive spaces
    text = re.sub(r' {2,}', ' ', text)
    
    # Truncate if needed
    if len(text) > limit:
        # Try to break at a sentence
        truncated = text[:limit]
        last_period = truncated.rfind('.')
        last_question = truncated.rfind('?')
        last_exclamation = truncated.rfind('!')
        
        break_point = max(last_period, last_question, last_exclamation)
        
        if break_point > limit * 0.7:  # Only break if we're not losing too much
            text = text[:break_point + 1]
        else:
            text = truncated.rsplit(' ', 1)[0] + "..."
    
    return text.strip()

from collections import defaultdict

class SourceCircuitBreaker:
    """
    Circuit breaker pattern for handling failing sources
    Prevents repeated attempts to fetch from consistently failing sources
    """
    def __init__(self, failure_threshold=3, recovery_timeout=300):
        """
        Initialize circuit breaker
        
        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds before attempting recovery (not currently used)
        """
        self.failure_counts = defaultdict(int)
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time = defaultdict(float)
    
    def can_call(self, source):
        """Check if source can be called (circuit not open)"""
        return self.failure_counts[source] < self.failure_threshold
    
    def record_success(self, source):
        """Record successful call, reset failure count"""
        self.failure_counts[source] = 0
    
    def record_failure(self, source):
        """Record failed call, increment failure count"""
        self.failure_counts[source] += 1
        self.last_failure_time[source] = datetime.now().timestamp()
        
        if self.failure_counts[source] >= self.failure_threshold:
            logging.warning(f"[CIRCUIT] Circuit breaker opened for {source} after {self.failure_counts[source]} failures")

# Global circuit breaker instance
circuit_breaker = SourceCircuitBreaker()

def patch_socket_ipv4():
    """
    Monkey-patch socket.getaddrinfo to force IPv4
    Useful for environments where IPv6 is flaky (like some GH Actions runners)
    """
    import socket
    
    real_getaddrinfo = socket.getaddrinfo

    def new_getaddrinfo(*args, **kwargs):
        """Wrapper that forces IPv4 family"""
        # Force AF_INET (IPv4)
        if 'family' in kwargs:
            kwargs['family'] = socket.AF_INET
        elif len(args) >= 3:
            # args[0]=host, args[1]=port, args[2]=family
            new_args = list(args)
            new_args[2] = socket.AF_INET 
            args = tuple(new_args)
        else:
            # If family wasn't provided, pass it as kwarg
            kwargs['family'] = socket.AF_INET
            
        return real_getaddrinfo(*args, **kwargs)

    socket.getaddrinfo = new_getaddrinfo
    logging.debug("[NETWORK] Socket patched to force IPv4")

def format_duration(seconds):
    """Format duration in seconds to human-readable format"""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"

def validate_url(url):
    """
    Validate if a string is a proper URL
    
    Args:
        url: String to validate
    
    Returns:
        bool: True if valid URL, False otherwise
    """
    if not url:
        return False
    
    url = str(url).strip()
    
    # Must start with http/https
    if not url.startswith(('http://', 'https://')):
        return False
    
    # Basic URL pattern
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain...
        r'localhost|'  # localhost...
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # ...or ip
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    
    return bool(url_pattern.match(url))
