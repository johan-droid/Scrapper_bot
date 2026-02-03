import os
import requests
import sys
from pathlib import Path

# Manually load .env for local testing if dotenv is installed
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(env_path)
    print(f"Loaded .env from {env_path}")
except ImportError:
    print("python-dotenv not installed, using system env vars")

def test_config():
    token = os.getenv("BOT_TOKEN")
    anime_channel = os.getenv("ANIME_NEWS_CHANNEL_ID")
    world_channel = os.getenv("WORLD_NEWS_CHANNEL_ID")

    print(f"\n--- Configuration Check ---")
    if not token:
        print("❌ BOT_TOKEN is missing!")
    else:
        print(f"✅ BOT_TOKEN found. Length: {len(token)}")
        print(f"   First 4 chars: {token[:4]}...")
        if " " in token:
            print("❌ WARNING: BOT_TOKEN contains spaces!")

    if not anime_channel:
        print("❌ ANIME_NEWS_CHANNEL_ID is missing!")
    else:
        print(f"✅ ANIME_NEWS_CHANNEL_ID found: '{anime_channel}'")
        if " " in anime_channel:
            print("❌ WARNING: ANIME_NEWS_CHANNEL_ID contains spaces!")

    if not world_channel:
        print("❌ WORLD_NEWS_CHANNEL_ID is missing!")
    else:
        print(f"✅ WORLD_NEWS_CHANNEL_ID found: '{world_channel}'")

    if not token:
        return

    print(f"\n--- Connectivity Check ---")
    # 1. Test getMe
    try:
        url = f"https://api.telegram.org/bot{token}/getMe"
        print(f"Testing Token: GET {url.replace(token, '********')}...")
        resp = requests.get(url)
        print(f"Response Status: {resp.status_code}")
        print(f"Response Body: {resp.text}")
        
        if resp.status_code == 404:
            print("❌ 404 Error on getMe -> The BOT_TOKEN is likely invalid or has extra characters.")
        elif resp.status_code == 401:
            print("❌ 401 Unauthorized -> The BOT_TOKEN is invalid.")
        elif resp.status_code == 200:
            print("✅ Token is valid. Bot info received.")
            
            # 2. Test getChat
            if anime_channel:
                chat_url = f"https://api.telegram.org/bot{token}/getChat?chat_id={anime_channel}"
                print(f"\nTesting Channel Access: {anime_channel}")
                chat_resp = requests.get(chat_url)
                print(f"Response Status: {chat_resp.status_code}")
                print(f"Response Body: {chat_resp.text}")
                
                if chat_resp.status_code != 200:
                    print("❌ Could not access channel. Check ID and Admin permissions.")
                else:
                    print("✅ Channel access confirmed.")
        else:
            print("❌ Unknown error.")

    except Exception as e:
        print(f"Error during request: {e}")

if __name__ == "__main__":
    test_config()
