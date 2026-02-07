import os
import dotenv
from pathlib import Path

# Load env vars
env_path = Path(__file__).parent.parent / ".env"
dotenv.load_dotenv(env_path, override=True)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
WORLD_NEWS_CHANNEL_ID = os.getenv("WORLD_NEWS_CHANNEL_ID")
ANIME_NEWS_CHANNEL_ID = os.getenv("ANIME_NEWS_CHANNEL_ID")
ADMIN_ID = os.getenv("ADMIN_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
TELEGRAPH_TOKEN = os.getenv("TELEGRAPH_TOKEN")

# Configuration
BASE_URL = "https://www.animenewsnetwork.com"
DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() == "true"
DISABLE_PREVIEW = os.getenv("DISABLE_PREVIEW", "True").lower() == "true"

SOURCE_LABEL = {
    "ANN": "Anime News Network", "ANN_DC": "ANN (Detective Conan)",
    "DCW": "Detective Conan Wiki", "TMS": "TMS Entertainment", "FANDOM": "Fandom Wiki",
    "ANI": "Anime News India", "MAL": "MyAnimeList", "CR": "Crunchyroll News",
    "AC": "Anime Corner", "HONEY": "Honey's Anime",
    "BBC": "BBC World News", "ALJ": "Al Jazeera", "CNN": "CNN World", "GUARD": "The Guardian",
    "NPR": "NPR International", "DW": "Deutsche Welle", "F24": "France 24", "CBC": "CBC World",
    "NL": "NewsLaundry", "WIRE": "The Wire", "SCROLL": "Scroll.in",
    "PRINT": "The Print", "INTER": "The Intercept", "PRO": "ProPublica", "REUTERS": "Reuters",
    "AP": "Associated Press", "WSJ": "Wall Street Journal", "BLOOMBERG": "Bloomberg",
    "FINANCIAL": "Financial Times", "ECONOMIST": "The Economist",
    "NYP": "New York Post", "LATIMES": "Los Angeles Times", "CHICAGO": "Chicago Tribune",
    "MIRROR": "Daily Mirror", "INDEPENDENT": "The Independent"
}

# RSS Feeds - Optimized for long-term reliability
RSS_FEEDS = {
    # Anime News Sources
    "ANI": "https://animenewsindia.com/feed/",
    "CR": "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss",
    "AC": "https://animecorner.me/feed/",
    "HONEY": "https://honeysanime.com/feed/",
    
    # World News Sources - Verified working URLs
    "BBC": "http://feeds.bbci.co.uk/news/world/rss.xml",
    "ALJ": "https://www.aljazeera.com/xml/rss/all.xml",
    "CNN": "http://rss.cnn.com/rss/edition_world.rss",
    "GUARD": "https://www.theguardian.com/world/rss",
    "NPR": "https://feeds.npr.org/1001/rss.xml",
    "DW": "https://rss.dw.com/xml/rss-en-all",
    "F24": "https://www.france24.com/en/rss",
    "CBC": "https://www.cbc.ca/cmlink/rss-world",
    
    # Indian News Sources - Working sources only
    "NL": "https://www.newslaundry.com/feed",
    
    # International Sources - Verified working
    "INTER": "https://theintercept.com/feed/?lang=en",
    "PRO": "https://www.propublica.org/feeds/propublica/main",
    
    # Premium reliable sources
    "BLOOMBERG": "https://feeds.bloomberg.com/markets/news.rss",
    "FINANCIAL": "https://www.ft.com/rss/world",
    # "REUTERS": "https://www.reuters.com/rssFeed/worldNews", # Strictly blocks bots (401)
    
    # Additional reliable sources
    "NYP": "https://nypost.com/feed/",
    "LATIMES": "https://www.latimes.com/world-nation/rss2.0.xml", # Updated URL
    # "CHICAGO": "https://www.chicagotribune.com/news.rss", # 404 / Paywall
    "MIRROR": "https://www.mirror.co.uk/news/world-news/rss.xml",
    "INDEPENDENT": "https://www.independent.co.uk/rss", # Updated URL
}

# Channel routing
ANIME_NEWS_SOURCES = {"ANN", "ANN_DC", "DCW", "TMS", "FANDOM", "ANI", "MAL", "CR", "AC", "HONEY"}
WORLD_NEWS_SOURCES = {
    "BBC", "ALJ", "CNN", "GUARD", "NPR", "DW", "F24", "CBC",
    "NL", "WIRE", "SCROLL", "PRINT", "INTER", "PRO", "REUTERS", "BLOOMBERG", "FINANCIAL",
    "NYP", "LATIMES", "CHICAGO", "MIRROR", "INDEPENDENT"
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]
