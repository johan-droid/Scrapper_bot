import requests
from bs4 import BeautifulSoup

def inspect_page():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    
    # 1. Get a random news link
    try:
        r = session.get("https://www.animenewsnetwork.com", timeout=10)
        soup = BeautifulSoup(r.text, "html.parser")
        article_link = None
        for a in soup.find_all("div", class_="herald box news t-news"):
             t = a.find("h3")
             if t and t.find("a"):
                 article_link = "https://www.animenewsnetwork.com" + t.find("a")['href']
                 break
        
        if not article_link:
            # Fallback to a known URL if parsing fails (might be outdated but worth a shot)
            article_link = "https://www.animenewsnetwork.com/news/2024-01-01/example"
            print("Could not find dynamic link, using fallback (which likely fails).")

        print(f"Inspecting: {article_link}")
        
        # 2. Inspect the structure
        r = session.get(article_link, timeout=10)
        s = BeautifulSoup(r.text, "html.parser")
        
        # Find the first 'thumbnail lazyload'
        first_thumb = s.find("div", class_="thumbnail lazyload")
        if first_thumb:
            print("First 'thumbnail lazyload' found:")
            print(f"  Parent classes: {first_thumb.parent.get('class')}")
            print(f"  Parent tag: {first_thumb.parent.name}")
            print(f"  Grandparent tag: {first_thumb.parent.parent.name}")
            print(f"  Inside #content-zone? {bool(first_thumb.find_parent(id='content-zone'))}")
            print(f"  Inside .meat? {bool(first_thumb.find_parent(class_='meat'))}")
            print(f"  Data-src: {first_thumb.get('data-src')}")
        else:
            print("No 'thumbnail lazyload' found.")

        # Check for better candidates
        print("\nChecking for images inside .meat or .content:")
        content_div = s.find("div", class_="meat") or s.find("div", class_="content")
        if content_div:
            imgs = content_div.find_all("img")
            print(f"Found {len(imgs)} images inside content div.")
            for i, img in enumerate(imgs[:3]):
                print(f"  [{i}] src: {img.get('src') or img.get('data-src')}")
        else:
            print("No content div found.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_page()
