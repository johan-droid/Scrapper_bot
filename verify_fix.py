import requests
from bs4 import BeautifulSoup
import logging

logging.basicConfig(level=logging.INFO)

BASE_URL = "https://www.animenewsnetwork.com"

# --- Replicating the helper ---
def get_scraping_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    return session

# --- Replicating the NEW logic to verify it works (stand-alone test) ---
def get_details_mock(item):
    if not item.get("article_url"): return item
    session = get_scraping_session()
    try:
        r = session.get(item["article_url"], timeout=15)
        s = BeautifulSoup(r.text, "html.parser")
        
        # 1. Try text content/meat div first (More specific to the article)
        content_img = None
        content_div = s.find("div", class_="meat") or s.find("div", class_="content")
        if content_div:
            for img in content_div.find_all("img"):
                src = img.get("src") or img.get("data-src")
                # Filter out spacers, tracking pixels, and tiny icons
                if src and "spacer" not in src and "pixel" not in src and not src.endswith(".gif"):
                     # Skip known generic/footer images if needed
                    if "facebook" in src or "twitter" in src: continue
                    
                    full_src = f"{BASE_URL}{src}" if not src.startswith("http") else src
                    content_img = full_src
                    item["image"] = content_img
                    print(f"  [+] Found Content Image: {item['image']}")
                    break
        
        # 2. If no content image, try OpenGraph (Backup)
        if not item.get("image"):
            og_img = s.find("meta", property="og:image")
            if og_img and og_img.get("content"):
                item["image"] = og_img["content"]
                print(f"  [+] Found OG Image (Backup): {item['image']}")

        # 3. Fallback to thumbnail (but be careful of generic ones)
        if not item.get("image"):
            thumb = s.find("div", class_="thumbnail lazyload")
            if thumb and thumb.get("data-src"): 
                src = thumb['data-src']
                item["image"] = f"{BASE_URL}{src}" if not src.startswith("http") else src
                print(f"  [+] Fallback to Thumbnail: {item['image']}")
                
    except Exception as e:
        print(f"Error: {e}")
    finally: session.close()
    return item

def run_test():
    session = get_scraping_session()
    print("Fetching homepage...")
    try:
        r = session.get(BASE_URL, timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"Failed to fetch homepage: {e}")
        return

    items = []
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
    
    print(f"Testing {len(items)} articles...")
    for item in items:
        print(f"\nChecking: {item['title']}")
        print(f"URL: {item['article_url']}")
        get_details_mock(item)
        print(f"Final Image: {item.get('image', 'NONE')}")

if __name__ == "__main__":
    run_test()
