# Anime News Bot

Robust scraper bot for Telegram that fetches anime news from multiple sources (ANN, Reddit, Anime News India, etc.) and posts them intelligently.

## Features
- **Multi-Source**: Scrapes Anime News Network, Anime News India, and Subreddits (r/anime, r/DetectiveConan, etc.).
- **Smart Scheduling**: Runs every 4 hours via GitHub Actions.
- **Deduplication**: Uses Supabase (PostgreSQL) to prevent duplicate posts.
- **Robustness**: RSS feeds for Reddit/ANI, retry logic, and circuit breakers.
- **Admin Reports**: Sends detailed stats and health reports to the admin after each cycle.

## Setup
1. **Clone & Install**:
   ```bash
   git clone <repo_url>
   pip install -r requirements.txt
   ```
2. **Environment Variables**:
   Create a `.env` file (or set GitHub Secrets):
   - `BOT_TOKEN`: Telegram Bot Token
   - `CHAT_ID`: Channel ID (e.g., -100...)
   - `ADMIN_ID`: Your Personal ID
   - `SUPABASE_URL` & `SUPABASE_KEY`: Database Credentials

3. **Database**:
   Run the SQL provided in the legacy README or checks inside `animebot.py` logic.

## Deployment
- **GitHub Actions**: Automatically runs on schedule (`0 */4 * * *`). Ensure Secrets are set in Repo Settings.
   - Connect your GitHub repository.

3. **Configure the Service**:
   - **Name**: anime-news-bot
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python animebot.py`
   - **Environment Variables**:
     - `BOT_TOKEN`: Your Telegram bot token
     - `CHAT_ID`: Your Telegram chat ID
     - `ADMIN_ID`: (Optional) Your Telegram user ID
     - `SUPABASE_URL`: (Optional) Your Supabase URL
     - `SUPABASE_KEY`: (Optional) Your Supabase key

4. **Deploy**: Click "Create Background Worker". It will build and start automatically.

5. **Monitor**: Check logs in the Render dashboard. The bot will run continuously, fetching news every 4 hours.

**Note**: Render's free tier provides 750 hours/month. The bot uses ~24 hours/month with optimized sleeping and minimal API calls.

## Configuration
- Change timezone in `animebot.py` if needed (default: Asia/Kolkata)
- Set `DEBUG_MODE = True` to test without date filtering
