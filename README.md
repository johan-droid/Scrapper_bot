# Anime News Bot

Fetches anime news from different sources and posts them to your Telegram group with images, titles, and captions.

## Features
- Scrapes news from:
  - Anime-Planet (ANN)
  - Detective Conan Wiki
  - TMS Entertainment
  - Fandom Wiki
  - ANN Detective Conan page
- Posts to Telegram with JSON-formatted messages
- Runs continuously every 4 hours with optimized resource usage
- Prevents duplicate posts across sources with database persistence
- Auto-ping every 10 minutes for connection stability
- Responds to /start command with bot statistics
- Memory-efficient with cleanup and chunked sleeping
- Rate-limited API calls to respect free tier limits

## Setup
1. Clone the repository
2. Create a virtual environment: `python -m venv .venv`
3. Activate: `.venv\Scripts\activate` (Windows)
4. Install dependencies: `pip install -r requirements.txt`
5. Copy `.env.example` to `.env` and fill in your values:
   ```bash
   cp .env.example .env
   ```
6. Edit `.env` with your actual credentials

## Supabase Database Setup (Optional)
If you want persistent storage to prevent reposts across deployments:

1. Create a [Supabase](https://supabase.com) account
2. Create a new project
3. Go to SQL Editor and run:
```sql
-- 1. Main News Storage
CREATE TABLE IF NOT EXISTS posted_news (
    id SERIAL PRIMARY KEY,
    normalized_title TEXT NOT NULL,
    full_title TEXT,
    source TEXT,
    posted_date DATE NOT NULL,
    posted_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    run_id TEXT,
    slot INTEGER,
    UNIQUE(normalized_title, posted_date)
);

-- 2. Run Tracking (for GitHub Actions slot logic)
CREATE TABLE IF NOT EXISTS runs (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    date TEXT NOT NULL,
    slot INTEGER NOT NULL,
    scheduled_at TIMESTAMP WITH TIME ZONE,
    started_at TIMESTAMP WITH TIME ZONE,
    finished_at TIMESTAMP WITH TIME ZONE,
    status TEXT,
    posts_sent INTEGER DEFAULT 0,
    source_counts JSONB,
    error TEXT,
    UNIQUE(date, slot) -- Critical for preventing duplicate runs
);

-- 3. Analytics
CREATE TABLE IF NOT EXISTS bot_stats (
    id SERIAL PRIMARY KEY,
    bot_started_at TIMESTAMP WITH TIME ZONE,
    total_posts_all_time INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS daily_stats (
    date DATE PRIMARY KEY,
    posts_count INTEGER DEFAULT 0
);
```
4. Get your project URL and anon key from Settings > API
5. Set `SUPABASE_URL` and `SUPABASE_KEY` environment variables

If Supabase is not configured, the bot falls back to local JSON storage.

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
     - `ADMIN_ID`: (Optional) Your Telegram user ID
     - `SUPABASE_URL`: (Optional) Your Supabase URL
     - `SUPABASE_KEY`: (Optional) Your Supabase key

4. **Deploy**: Click "Create Background Worker". It will build and start automatically.

5. **Monitor**: Check logs in the Render dashboard. The bot will run continuously, fetching news every 4 hours.

**Note**: Render's free tier provides 750 hours/month. The bot uses ~24 hours/month with optimized sleeping and minimal API calls.

## Configuration
- Change timezone in `animebot.py` if needed (default: Asia/Kolkata)
- Set `DEBUG_MODE = True` to test without date filtering
