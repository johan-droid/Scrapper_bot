# Anime News Bot

Fetches anime news from different sources and posts them to your Telegram group with images, titles, and captions.

## Features
- Scrapes news from:
  - Anime-Planet (ANN)
  - Detective Conan Wiki
  - TMS Entertainment
  - Fandom Wiki
  - ANN Detective Conan page
- Posts to Telegram with images, titles, and captions
- Runs continuously every 24 hours with daily resets
- Prevents duplicate posts across sources
- Auto-ping every 5 minutes for monitoring
- Responds to /start command with bot statistics
- Self-healing with retry logic

## Setup
1. Clone the repository
2. Create a virtual environment: `python -m venv .venv`
3. Activate: `.venv\Scripts\activate` (Windows)
4. Install dependencies: `pip install -r requirements.txt`
5. Set environment variables:
   - `BOT_TOKEN`: Your Telegram bot token
   - `CHAT_ID`: Your Telegram chat ID (group or channel)
   - `ADMIN_ID`: (Optional) Your Telegram user ID for /start command access

## Local Testing
Run: `python animebot.py`

## Deployment on Render (Free Tier)

1. **Create a Render Account**: Go to [render.com](https://render.com) and sign up.

2. **Create a New Service**:
   - Click "New" > "Background Worker" (since this runs continuously)
   - Connect your GitHub repository.

3. **Configure the Service**:
   - **Name**: anime-news-bot
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python animebot.py`
   - **Environment Variables**:
     - `BOT_TOKEN`: Your Telegram bot token
     - `CHAT_ID`: Your Telegram chat ID

4. **Deploy**: Click "Create Background Worker". It will build and start automatically.

5. **Monitor**: Check logs in the Render dashboard. The bot will run continuously, fetching news every 24 hours.

**Note**: Render's free tier provides 750 hours/month. The bot uses ~24 hours/month, well within limits.

## Configuration
- Change timezone in `animebot.py` if needed (default: Asia/Kolkata)
- Set `DEBUG_MODE = True` to test without date filtering
