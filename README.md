# Anime & World News Bot 📰

A professional Telegram news bot that delivers **ad-free, full-article content** using Telegraph integration. Features unified formatting, smart content extraction, and comprehensive compliance with all platform policies.

## ✨ Key Features

- **Telegraph Integration**: Full articles, ad-free, instant loading.
- **Unified Professional Format**: Consistent design for all news sources.
- **Smart Content Extraction**: Optimized selectors for BBC, CNN, ANN, etc.
- **Full Compliance**: Respects rate limits, robots.txt, and user agents.
- **Production-Ready**: Circuit breakers, deduplication, and comprehensive logging.

## 🚀 Quick Start

### 1. Clone Repository

```bash
git clone https://github.com/johan-droid/Scrapper_bot.git
cd Scrapper_bot
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

Copy `.env.example` to `.env` and fill in your details:

```bash
cp .env.example .env
```

Required variables:
- `BOT_TOKEN`: Your Telegram Bot Token.
- `ANIME_NEWS_CHANNEL_ID`: Channel ID for Anime news.
- `WORLD_NEWS_CHANNEL_ID`: Channel ID for World news.

Optional but recommended:
- `SUPABASE_URL` & `SUPABASE_KEY`: For database persistence and stats.
- `TELEGRAPH_TOKEN`: For Telegraph account reuse (bot creates one if missing).
- `ADMIN_ID`: For admin reports.

### 4. Run the Bot

```bash
python -m src.main
```

## 📂 Project Structure

```
/
├── docs/                 # Documentation (Guides, Checklists)
├── sql/                  # Database schemas and scripts
├── src/                  # Source code
│   ├── config.py         # Configuration
│   ├── models.py         # Data structures
│   ├── database.py       # Supabase integration
│   ├── utils.py          # Utilities (Logging, Time)
│   ├── telegraph_client.py # Telegraph API
│   ├── scrapers.py       # RSS & Content Extraction
│   ├── bot.py            # Core Bot Logic
│   └── main.py           # Entry Point
├── .gitignore
├── requirements.txt
└── README.md
```

## 📚 Documentation

Detailed guides are available in the `docs/` directory:
- [Telegraph Integration Guide](docs/TELEGRAPH_INTEGRATION_GUIDE.md)
- [Bot Deployment Guide](docs/DEPLOYMENT_GUIDE_TELEGRAPH.md)
- [Database Setup](docs/DATABASE_README.md)

## 📊 How It Works

1.  **Fetch**: Scrapes RSS feeds from configured sources.
2.  **Extract**: Parses full article content using smart selectors.
3.  **Create**: Generates a Telegraph page with the content.
4.  **Post**: Sends a formatted message to the appropriate Telegram channel.
5.  **Log**: Stores metadata in Supabase (if configured) to prevent duplicates.

## 📄 License

MIT License.
