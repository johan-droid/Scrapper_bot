import requests
from bs4 import BeautifulSoup
import time
import re
import logging
import pytz
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)

# Configuration
BASE_URL = "https://www.animenewsnetwork.com"
BASE_URL_DC = "https://www.detectiveconanworld.com"
BASE_URL_TMS = "https://tmsanime.com"
BASE_URL_FANDOM = "https://detectiveconan.fandom.com"
BASE_URL_ANN_DC = "https://www.animenewsnetwork.com/encyclopedia/anime.php?id=454&tab=news"
DEBUG_MODE = True  # Set True to test without date filter

# Time Zone Handling
utc_tz = pytz.utc
local_tz = pytz.timezone("Asia/Kolkata")
today_local = datetime.now(local_tz).date()

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def fetch_anime_news():
    """Fetches latest anime news from ANN."""
    try:
        response = session.get(BASE_URL, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        news_list = []
        all_articles = soup.find_all("div", class_="herald box news t-news")
        logging.info(f"Total articles found: {len(all_articles)}")

        for article in all_articles:
            title_tag = article.find("h3")
            date_tag = article.find("time")

            if not title_tag or not date_tag:
                continue

            title = title_tag.get_text(strip=True)
            date_str = date_tag["datetime"]
            try:
                news_date = datetime.fromisoformat(date_str).astimezone(local_tz).date()
            except ValueError as e:
                logging.error(f"Error parsing date {date_str}: {e}")
                continue

            if DEBUG_MODE or news_date == today_local:
                link = title_tag.find("a")
                article_url = f"{BASE_URL}{link['href']}" if link else None
                news_list.append({"title": title, "article_url": article_url, "article": article})
                logging.info(f"✅ Found news: {title}")
            else:
                logging.info(f"⏩ Skipping (not today's news): {title} - Date: {news_date}")

        logging.info(f"Filtered articles: {len(news_list)}")
        return news_list

    except requests.RequestException as e:
        logging.error(f"Fetch error: {e}")
        return []

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def fetch_dc_updates():
    """Fetches recent changes from Detective Conan Wiki."""
    try:
        url = f"{BASE_URL_DC}/wiki/Special:RecentChanges"
        response = session.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        updates_list = []
        changes = soup.find_all("li", class_=re.compile(r"mw-changeslist-line"))

        for change in changes:
            time_tag = change.find("a", class_="mw-changeslist-date")
            if not time_tag:
                continue
            time_str = time_tag.get_text(strip=True)
            try:
                if "," in time_str:
                    date_str = time_str + f", {datetime.now().year}"
                else:
                    date_str = time_str
                change_date = datetime.strptime(date_str, "%H:%M, %d %B %Y").replace(tzinfo=pytz.utc).astimezone(local_tz).date()
            except ValueError as e:
                logging.error(f"Error parsing date {time_str}: {e}")
                continue

            if DEBUG_MODE or change_date == today_local:
                title_tag = change.find("a", class_="mw-changeslist-title")
                if not title_tag:
                    continue
                page_title = title_tag.get_text(strip=True)
                user_tag = change.find("a", class_="mw-userlink")
                user = user_tag.get_text(strip=True) if user_tag else "Unknown"
                comment_tag = change.find("span", class_="comment")
                comment = comment_tag.get_text(strip=True) if comment_tag else ""

                title = f"DC Wiki Update: {page_title}"
                summary = f"Edited by {user}. {comment}" if comment else f"Edited by {user}."

                updates_list.append({"title": title, "summary": summary, "image": None})
                logging.info(f"✅ Found wiki update: {title}")

        logging.info(f"Filtered wiki updates: {len(updates_list)}")
        return updates_list

    except requests.RequestException as e:
        logging.error(f"Fetch DC updates error: {e}")
        return []

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def fetch_tms_news():
    """Fetches latest news from TMS Detective Conan page."""
    try:
        response = session.get(BASE_URL_TMS + "/detective-conan", timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        news_list = []
        latest_news_section = soup.find(string="LATEST TMS NEWS")
        if latest_news_section:
            parent = latest_news_section.parent
            news_links = parent.find_next_siblings("a")[:5]
            for link in news_links:
                title = link.get_text(strip=True)
                url = link.get("href")
                if title and url:
                    news_title = f"TMS News: {title}"
                    summary = f"Read more: {BASE_URL_TMS}{url}" if not url.startswith("http") else f"Read more: {url}"
                    news_list.append({"title": news_title, "summary": summary, "image": None})
                    logging.info(f"✅ Found TMS news: {title}")

        logging.info(f"Filtered TMS news: {len(news_list)}")
        return news_list

    except requests.RequestException as e:
        logging.error(f"Fetch TMS news error: {e}")
        return []

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def fetch_fandom_updates():
    """Fetches recent changes from Detective Conan Fandom Wiki."""
    try:
        url = f"{BASE_URL_FANDOM}/wiki/Special:RecentChanges"
        response = session.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        updates_list = []
        changes = soup.find_all("li", class_=re.compile(r"mw-changeslist-line"))

        for change in changes:
            time_tag = change.find("a", class_="mw-changeslist-date")
            if not time_tag:
                continue
            time_str = time_tag.get_text(strip=True)
            try:
                if "," in time_str:
                    date_str = time_str + f", {datetime.now().year}"
                else:
                    date_str = time_str
                change_date = datetime.strptime(date_str, "%H:%M, %d %B %Y").replace(tzinfo=pytz.utc).astimezone(local_tz).date()
            except ValueError as e:
                logging.error(f"Error parsing date {time_str}: {e}")
                continue

            if DEBUG_MODE or change_date == today_local:
                title_tag = change.find("a", class_="mw-changeslist-title")
                if not title_tag:
                    continue
                page_title = title_tag.get_text(strip=True)
                user_tag = change.find("a", class_="mw-userlink")
                user = user_tag.get_text(strip=True) if user_tag else "Unknown"
                comment_tag = change.find("span", class_="comment")
                comment = comment_tag.get_text(strip=True) if comment_tag else ""

                title = f"Fandom Wiki Update: {page_title}"
                summary = f"Edited by {user}. {comment}" if comment else f"Edited by {user}."

                updates_list.append({"title": title, "summary": summary, "image": None})
                logging.info(f"✅ Found Fandom wiki update: {title}")

        logging.info(f"Filtered Fandom wiki updates: {len(updates_list)}")
        return updates_list

    except requests.RequestException as e:
        logging.error(f"Fetch Fandom updates error: {e}")
        return []

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def fetch_ann_dc_news():
    """Fetches latest Detective Conan news from ANN encyclopedia page."""
    try:
        response = session.get(BASE_URL_ANN_DC, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        news_list = []
        all_articles = soup.find_all("div", class_="herald box news t-news")
        logging.info(f"Total DC articles found: {len(all_articles)}")

        for article in all_articles:
            title_tag = article.find("h3")
            date_tag = article.find("time")

            if not title_tag or not date_tag:
                continue

            title = title_tag.get_text(strip=True)
            date_str = date_tag["datetime"]
            try:
                news_date = datetime.fromisoformat(date_str).astimezone(local_tz).date()
            except ValueError as e:
                logging.error(f"Error parsing date {date_str}: {e}")
                continue

            if DEBUG_MODE or news_date == today_local:
                link = title_tag.find("a")
                article_url = f"{BASE_URL}{link['href']}" if link else None
                news_list.append({"title": f"ANN DC News: {title}", "article_url": article_url, "article": article})
                logging.info(f"✅ Found ANN DC news: {title}")

        logging.info(f"Filtered ANN DC news: {len(news_list)}")
        return news_list

    except requests.RequestException as e:
        logging.error(f"Fetch ANN DC news error: {e}")
        return []

if __name__ == "__main__":
    print("Testing Detective Conan news scraping...")

    # Test all sources
    sources = [
        ("ANN General", fetch_anime_news),
        ("DC Wiki", fetch_dc_updates),
        ("TMS", fetch_tms_news),
        ("Fandom Wiki", fetch_fandom_updates),
        ("ANN DC", fetch_ann_dc_news),
    ]

    all_news = []
    for source_name, fetch_func in sources:
        print(f"\n--- Testing {source_name} ---")
        try:
            news = fetch_func()
            print(f"Found {len(news)} items from {source_name}")
            for item in news[:3]:  # Show first 3
                print(f"  - {item['title']}")
            all_news.extend(news)
        except Exception as e:
            print(f"Error with {source_name}: {e}")

    # Filter for DC related
    dc_related = [item for item in all_news if 'conan' in item['title'].lower() or 'detective' in item['title'].lower() or 'dc' in item['title'].lower() or 'shinichi' in item['title'].lower()]

    print(f"\n--- DC Related Results ({len(dc_related)}) ---")
    for item in dc_related[:10]:  # Show first 10
        print(f"  - {item['title']}")

    print(f"\nTotal news scraped: {len(all_news)}")
    print(f"DC related news: {len(dc_related)}")