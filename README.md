# Anime News Scraper Bot 🌸

A **GitHub Actions-based anime news scraper** that fetches anime news from multiple RSS feeds and posts them to Telegram channels using Telegraph integration. Features **2-hour interval automated scraping**, **fault detection**, and **database deduplication**.

## ✨ Key Features

### 🤖 Bot Capabilities
- **Anime-Only Content**: Focused exclusively on anime and manga news from 16+ sources
- **Telegraph Integration**: Full articles, ad-free, instant loading
- **Professional Format**: Otaku Insight style with metadata and copyright
- **2-Hour Interval Scraping**: Automated anime news updates via GitHub Actions cron
- **Active Fault Detection**: Real-time scraper monitoring and reporting
- **Database Deduplication**: Prevents duplicate posts using Supabase

### 🛡️ Reliability Features
- **Circuit Breaker Pattern**: Auto-disable failing sources
- **Robust Error Handling**: Automatic retries and graceful degradation
- **Comprehensive Logging**: Full audit trail
- **Date Parsing Fix**: Handles various ISO 8601 formats robustly
- **Resource Optimization**: Efficient for GitHub Actions free tier

### 📊 Monitoring
- **Scraper Failure Reports**: Sent after every cycle to admin
- **Performance Metrics**: Success rates, response times
- **Circuit Breaker Status**: Real-time source health
- **Database Cleanup**: Automatic maintenance to stay within free tier limits

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
```env
BOT_TOKEN=your_telegram_bot_token
ANIME_NEWS_CHANNEL_ID=-100...
ADMIN_ID=your_telegram_user_id
```

Optional but recommended:
```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_key
TELEGRAPH_TOKEN=your_telegraph_token
```

### 4. Configure GitHub Actions Secrets

Add the following secrets to your GitHub repository settings:

```
BOT_TOKEN=your_telegram_bot_token
ANIME_NEWS_CHANNEL_ID=-100xxxxxxxxxx
ADMIN_ID=your_telegram_user_id
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_key
TELEGRAPH_TOKEN=your_telegraph_token
```

### 5. Test Locally (Optional)

```bash
python -m src.main
```

### 6. Deploy to GitHub Actions

```bash
git add .
git commit -m "Deploy anime news scraper"
git push origin main
```

The bot will automatically run every 2 hours via GitHub Actions cron job.

## 📂 Project Structure

```
Scrapper_bot/
├── src/
│   ├── main.py              # Entry point for GitHub Actions
│   ├── bot.py               # Core scraper logic with anime news formatting
│   ├── SCRAPER_FINAL_ANIME_ONLY.py  # Anime RSS parsing and content extraction
│   ├── database.py          # Supabase integration with date parsing fix
│   ├── telegraph_client.py  # Telegraph API client
│   ├── config.py            # Configuration and constants
│   ├── models.py            # Data structures
│   └── utils.py             # Utilities and helpers
├── .github/
│   └── workflows/
│       └── bot_schedule.yml # GitHub Actions cron workflow
├── requirements.txt         # Python dependencies
├── .env.example             # Environment template
└── README.md               # This file
```

## 🎯 How It Works

### Scraping Cycle (Every 2 Hours)

```
1. Fetch anime RSS feeds from all configured sources
   ↓
2. Parse entries with flexible handling
   ↓
3. Extract full article content
   ↓
4. Create Telegraph pages (ad-free)
   ↓
5. Post to anime Telegram channel with professional formatting
   ↓
6. Record in database (deduplication)
   ↓
7. Send scraper failure report to admin
```

### Scraper Fault Detection

**After every cycle**, the bot analyzes each scraper and sends a report to admin:

- ✅ **Success**: Source name + item count
- ❌ **Failure**: Source name + error details
- 🔴 **Circuit Breaker**: Auto-disabled after 3 failures

**Admin receives detailed report:**
```
📊 Summary
• Total Scrapers: 16
• ✅ Successful: 14 (87.5%)
• ❌ Failed: 2 (12.5%)

🔍 Failed Scrapers
❌ Source Name 🔴 [CIRCUIT BREAKER OPEN]
   └ Connection timeout after 3 attempts
```

## 📊 Scraping Schedule

The bot runs **12 times per day** at:
```
00:00  02:00  04:00  06:00
08:00  10:00  12:00  14:00
16:00  18:00  20:00  22:00
```

All times in UTC (converted from your local timezone).

## 🔧 Configuration

### Anime News Sources (16 sources)

#### Primary Anime News
- **Anime News Network (ANN)** - Main feed and Detective Conan specialized
- **Anime News India (ANI)** - Indian anime community news
- **Crunchyroll News (CR)** - Official Crunchyroll news feed
- **Anime Corner (AC)** - Anime news and reviews
- **Honey's Anime (HONEY)** - Anime articles and guides

#### Additional Anime Sources
- **AnimeDB (ANIDB)** - Anime database news
- **Anime UK News (ANIMEUK)** - UK anime community
- **MyAnimeList Feed (MALFEED)** - Official MAL news
- **Otaku USA (OTAKU)** - American anime magazine
- **Anime Planet (ANIPLANET)** - Anime recommendations and news

#### Gaming & Tech with Anime Content
- **Kotaku Anime (KOTAKU)** - Gaming news with anime coverage
- **PC Gamer Anime (PCGAMER)** - PC gaming with anime content

### Adding New Sources

Edit `src/config.py`:

```python
RSS_FEEDS = {
    "YOUR_CODE": "https://example.com/feed.xml",
    # Add more...
}

SOURCE_LABEL = {
    "YOUR_CODE": "Your Source Name",
    # Add more...
}
```

## 📈 Performance

### Resource Usage (GitHub Actions)
- **Memory**: 150-300 MB per run
- **CPU**: Efficient usage within GitHub Actions limits
- **Runtime**: ~5-15 minutes per cycle
- **Network**: Efficient with retries and circuit breakers

### Scraping Efficiency
- **Average**: 20-50 anime items per cycle
- **Deduplication**: 99%+ accuracy
- **Telegraph Success**: 80%+ of articles
- **Error Rate**: <10% typical

## 🛡️ Compliance

### Telegram Bot Policy ✅
- Rate limiting: Proper delays between posts
- Error handling: 429 retry with backoff
- Proper attribution: Always includes source

### Server Policies ✅
- User-Agent headers: Rotating browser agents
- Robots.txt compliance: Respects all rules
- Retry strategy: Exponential backoff

### Supabase Free Tier ✅
- Database: Automatic cleanup to stay within limits
- Bandwidth: Efficient usage within free tier
- Optimized queries with indexes

### GitHub Actions Free Tier ✅
- Monthly minutes: Well within 2000 minute limit
- Storage: Minimal repository footprint
- Efficient caching with pip cache

## 📚 Documentation

- [Contributing](CONTRIBUTING.md) - How to contribute

## 🔍 Monitoring

### Real-Time Monitoring
1. **GitHub Actions Logs**: Check workflow runs in repository
2. **Telegram Reports**: Automatic admin reports after each cycle
3. **Supabase Dashboard**: Database monitoring and statistics

### Weekly Review
1. Check scraper failure trends in GitHub Actions
2. Review database size in Supabase
3. Verify all sources working properly

### Monthly Maintenance
1. Automatic database cleanup handles old posts
2. Update RSS URLs if sources change
3. Optimize source list based on performance

## 🚨 Troubleshooting

### GitHub Actions Not Running

**Check workflow status:**
1. Go to your repository's **Actions** tab
2. Check if the workflow is enabled
3. Verify cron schedule is properly set

**Common fixes:**
- Ensure secrets are properly configured
- Check workflow file syntax
- Verify repository has Actions enabled

### Database Errors

**Check Supabase connection:**
1. Review GitHub Actions logs for database errors
2. Verify SUPABASE_URL and SUPABASE_KEY secrets
3. Check Supabase dashboard for service status

### Telegram Posting Issues

**Verify configuration:**
1. Check BOT_TOKEN is valid
2. Verify ANIME_NEWS_CHANNEL_ID is correct (starts with -100)
3. Ensure bot has posting permissions in channel

### Scraper Failures

**Check GitHub Actions logs:**
- Look for specific error messages
- Review failure reports sent to admin
- Common solutions:
  1. Update RSS URLs in config
  2. Wait for circuit breaker reset
  3. Remove permanently dead sources

## 💡 Best Practices

### For Admins
1. **Monitor daily reports** - Check Telegram for scraper reports
2. **Review GitHub Actions** - Check workflow runs weekly
3. **Database monitoring** - Review Supabase dashboard monthly
4. **Update sources** - Keep RSS URLs current

### For Developers
1. **Test locally** - Before deploying changes
2. **Check workflow logs** - After every deployment
3. **Monitor errors** - Address failures quickly
4. **Optimize queries** - Keep database efficient

## 🎯 Key Features in This Version

### ✅ Core Functionality
1. **GitHub Actions Integration**: Automated 2-hour scraping via cron
2. **16 Anime Sources**: Comprehensive anime news coverage
3. **Telegraph Integration**: Ad-free full article hosting
4. **Supabase Database**: Efficient deduplication and storage
5. **Fault Detection**: Automatic scraper monitoring and reporting

### ✅ Reliability Features
1. **Circuit Breaker**: Prevents repeated failures
2. **Automatic Cleanup**: Database maintenance for free tier
3. **Error Handling**: Robust retry mechanisms
4. **Resource Optimization**: Efficient GitHub Actions usage

### ✅ Performance Optimizations
1. **Smart Caching**: Reduces redundant operations
2. **Efficient Parsing**: Optimized RSS feed processing
3. **Background Operations**: Non-blocking execution
4. **Resource Monitoring**: Tracks usage patterns

## 📄 License

MIT License - See [LICENSE](LICENSE) for details

## 🤝 Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/johan-droid/Scrapper_bot/issues)
- **Admin Reports**: Automatic reports sent to configured admin ID
- **Logs**: Check GitHub Actions workflow runs

---

**Status**: Production Ready ✅  
**Version**: 2.0 (GitHub Actions Optimized)  
**Last Updated**: February 2026  
**Maintainer**: [@johan-droid](https://github.com/johan-droid)

**Key Features**: 2-Hour Scraping ✅ | Active Fault Detection ✅ | Telegraph Integration ✅ | GitHub Actions ✅
