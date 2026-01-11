import sys
import os

# Ensure we can import from the script verify_fix.py directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Mock Env Vars to pass animebot startup checks
os.environ["BOT_TOKEN"] = "FALSE_TOKEN"
os.environ["CHAT_ID"] = "12345"

from models import NewsItem
from animebot import parse_ann

mock_html = """
<div class="herald box news t-news">
    <h3><a href="/news/2024-01-01/example">Example News Title</a></h3>
    <time datetime="2026-01-11T12:00:00+05:30">Jan 11, 2026</time>
    <div class="intro">This is a summary.</div>
</div>
"""

def test_pydantic_parsing():
    print("Testing Pydantic parsing...")
    items = parse_ann(mock_html)
    
    if not items:
        print("[-] No items parsed (might be date filtering).")
        # Creating a manual item to test validation
        try:
            item = NewsItem(title=" Test Title ", source="ANN", article_url="http://example.com")
            print(f"[+] Created NewsItem: {item}")
            print(f"    Title Cleaned: '{item.title}'") # Should be 'Test Title'
            return
        except Exception as e:
            print(f"[-] Failed to create NewsItem: {e}")
            return

    for item in items:
        print(f"[+] Parsed Item Type: {type(item)}")
        if isinstance(item, NewsItem):
            print(f"    - Title: {item.title}")
            print(f"    - URL: {item.article_url}")
            print(f"    - Summary: {item.summary}")
            print("    [OK] Checked as Pydantic Model")
        else:
            print("    [FAIL] Not a Pydantic Model")

if __name__ == "__main__":
    test_pydantic_parsing()
