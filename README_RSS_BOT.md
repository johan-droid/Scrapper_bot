# RSS News Bot

A Python bot that aggregates news from multiple RSS sources every 4 hours with proper attribution and disclaimers.

## Features

- **Multiple News Sources**: Aggregates from 7 major news outlets
- **Proper Attribution**: Gives full credit to original sources
- **Legal Disclaimer**: Clear notice about content ownership
- **Automated Scheduling**: Runs every 4 hours automatically
- **Error Handling**: Robust error handling and logging
- **Easy Integration**: Can be integrated with existing bots (Telegram, Discord, etc.)

## Supported News Sources

1. **Al Jazeera** (Qatar) - Non-Western perspective on global conflicts
2. **The Intercept** (USA) - Surveillance, corruption, and war crimes
3. **ProPublica** (USA) - Non-profit investigative journalism
4. **NewsLaundry** (India) - Independent Indian news outlet
5. **The Wire** (India) - Indian nonprofit news and media website
6. **Scroll.in** (India) - Indian independent news publication
7. **The Print** (India) - Indian news and media website

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Set up environment variables (copy `.env.example` to `.env`):
```bash
cp .env.example .env
```

## Usage

### Basic Usage

Run the standalone RSS bot:
```bash
python rss_news_bot.py
```

This will:
- Fetch news immediately on start
- Save news to timestamped files
- Schedule updates every 4 hours
- Log all activities

### Integration with Existing Bots

Use the integration example:
```bash
python integration_example.py
```

Or import the bot class:
```python
from rss_news_bot import RSSNewsBot

bot = RSSNewsBot()
news_content = bot.fetch_all_news()
bot.save_news_to_file(news_content)
```

## Output Format

Each news update includes:

- **Header**: Global news digest with timestamp
- **Disclaimer**: Clear notice about content ownership
- **Articles**: Each with title, description, link, source info
- **Footer**: Repeated disclaimer

Example article format:
```
🔹 **Article Title**

Brief description of the article content...

📖 [Read Full Article](link)

📍 **Source:** News Outlet (Country)
💡 **About:** Source description
🕒 **Published:** Date/Time
```

## Configuration

### Environment Variables

- `BOT_TOKEN`: Telegram bot token (if using Telegram integration)
- `CHAT_ID`: Telegram chat ID (if using Telegram integration)
- `DEBUG_MODE`: Enable debug logging (True/False)

### Customization

You can modify:
- RSS sources in `self.rss_sources` dictionary
- Update frequency (default: 4 hours)
- Number of articles per source (default: 5)
- Output format in `format_article()` method

## Logging

The bot creates:
- Console output with real-time updates
- Log file: `rss_news_bot.log`
- News files: `news_update_YYYYMMDD_HHMMSS.txt`

## Legal Notice

**IMPORTANT**: This bot does not own any news rights. All content belongs to respective sources. The bot:
- Only aggregates headlines and brief descriptions
- Always includes proper attribution and links
- Is for educational/informational purposes only
- Respects robots.txt and rate limits

## Troubleshooting

### Common Issues

1. **RSS Feed Errors**: Some sources may occasionally be unavailable
2. **XML Parsing**: Malformed XML can cause parsing errors
3. **Rate Limiting**: Bot includes delays between requests

### Debug Mode

Enable debug logging:
```python
logging.basicConfig(level=logging.DEBUG)
```

## Integration Examples

### Telegram Integration
```python
def post_to_telegram(content):
    bot_token = os.getenv('BOT_TOKEN')
    chat_id = os.getenv('CHAT_ID')
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {
        'chat_id': chat_id,
        'text': content,
        'parse_mode': 'Markdown'
    }
    response = requests.post(url, json=data)
    return response.status_code == 200
```

### Discord Integration
```python
def post_to_discord(content):
    webhook_url = os.getenv('DISCORD_WEBHOOK_URL')
    data = {'content': content}
    response = requests.post(webhook_url, json=data)
    return response.status_code == 204
```

## Schedule

The bot runs automatically:
- **Initial run**: Immediately on start
- **Subsequent runs**: Every 4 hours
- **Manual trigger**: Call `run_news_update()` method

## Dependencies

- `requests` - HTTP requests
- `beautifulsoup4` - HTML parsing
- `schedule` - Task scheduling
- `python-dotenv` - Environment variables
- `lxml` - XML parsing (fallback)

## License

This project is for educational purposes. Please respect the terms of service of all news sources.
