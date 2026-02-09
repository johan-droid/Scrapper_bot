import os
import dotenv
from pathlib import Path

# Load env vars
env_path = Path(__file__).parent.parent / ".env"
dotenv.load_dotenv(env_path, override=True)

# Environment variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
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
    "AC": "Anime Corner", "HONEY": "Honey's Anime", "ANIDB": "AnimeDB",
    "ANIMEUK": "Anime UK News", "MALFEED": "MyAnimeList Feed", "OTAKU": "Otaku USA",
    "ANIPLANET": "Anime Planet", "KOTAKU": "Kotaku Anime", "PCGAMER": "PC Gamer Anime"
}

# RSS Feeds - Anime Only with Multiple Sources
RSS_FEEDS = {
    # Primary Anime News Sources
    "ANN": "https://animenewsnetwork.com/news/rss.xml",
    "ANN_DC": "https://animenewsnetwork.com/news/detective-conan/rss.xml",
    "ANI": "https://animenewsindia.com/feed/",
    "CR": "https://cr-news-api-service.prd.crunchyrollsvc.com/v1/en-US/rss",
    "AC": "https://animecorner.me/feed/",
    "HONEY": "https://honeysanime.com/feed/",
    
    # Additional Anime Sources
    "ANIDB": "https://anidb.net/rss/feed.atom",
    "ANIMEUK": "https://www.animeuknews.net/feed/",
    "MALFEED": "https://myanimelist.net/rss/news.xml",
    "OTAKU": "https://otakuusa.com/feed/",
    "ANIPLANET": "https://www.anime-planet.com/feed",
    
    # Gaming & Tech with Anime Content
    "KOTAKU": "https://kotaku.com/rss",
    "PCGAMER": "https://www.pcgamer.com/rss"
}

# Channel routing - Anime only
ANIME_NEWS_SOURCES = {"ANN", "ANN_DC", "DCW", "TMS", "FANDOM", "ANI", "MAL", "CR", "AC", "HONEY", "ANIDB", "ANIMEUK", "MALFEED", "OTAKU", "ANIPLANET", "KOTAKU", "PCGAMER"}

# Copyright disclaimer for all posts
COPYRIGHT_DISCLAIMER = "\n\n📝 *Disclaimer:* This content is for informational purposes only. All copyrights belong to respective owners."

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]
