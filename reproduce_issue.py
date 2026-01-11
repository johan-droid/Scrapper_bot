import requests
from bs4 import BeautifulSoup
import logging

logging.basicConfig(level=logging.INFO)

BASE_URL = "https://www.animenewsnetwork.com"

def get_scraping_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    return session

def run_test():
    session = get_scraping_session()
    
    # 1. Fetch Homepage to get links
    print(f"Fetching {BASE_URL}...")
    try:
        r = session.get(BASE_URL, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"Failed to fetch homepage: {e}")
        return

    items = []
    # Simplified parse_ann logic
    for article in soup.find_all("div", class_="herald box news t-news"):
        title_tag = article.find("h3")
        if not title_tag: continue
        link = title_tag.find("a")
        if link:
            items.append({
                "title": title_tag.get_text(" ", strip=True),
                "article_url": f"{BASE_URL}{link['href']}"
            })
        if len(items) >= 3: break
    
    print(f"Found {len(items)} articles. Checking details...")

    # 2. Check details for each
    for item in items:
        url = item["article_url"]
        print(f"\nChecking: {item['title']}")
        print(f"URL: {url}")
        
        try:
            r = session.get(url, timeout=10)
            s = BeautifulSoup(r.text, "html.parser")
            
            # The logic from animebot.py
            thumb = s.find("div", class_="thumbnail lazyload")
            image_url = None
            if thumb and thumb.get("data-src"): 
                image_url = thumb['data-src']
                if not image_url.startswith("http"):
                    image_url = f"{BASE_URL}{image_url}"
            
            print(f"Extracted Image: {image_url}")
            
            # Debug: Print all matching thumbnails to see if there are multiple
            all_thumbs = s.find_all("div", class_="thumbnail lazyload")
            print(f"DEBUG: Found {len(all_thumbs)} 'thumbnail lazyload' divs.")
            for i, t in enumerate(all_thumbs):
                src = t.get("data-src")
                print(f"  [{i}] data-src: {src}")

        except Exception as e:
            print(f"Error fetching details: {e}")

if __name__ == "__main__":
    run_test()
