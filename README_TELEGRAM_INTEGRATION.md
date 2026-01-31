# Telegram RSS News Bot Integration

A complete testing environment for the RSS News Bot with Telegram integration.

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment
Copy `.env.example` to `.env` and configure:
```bash
cp .env.example .env
```

Edit `.env`:
```env
BOT_TOKEN=your_telegram_bot_token_here
CHAT_ID=your_telegram_chat_id_here
TEST_MODE=True
ADMIN_ID=your_telegram_user_id_here
```

### 3. Run Setup & Test
```bash
# Interactive setup guide
python setup_telegram_bot.py

# Quick test
python test_telegram_bot.py

# Full test with news
RUN_ONCE=True python telegram_rss_bot.py
```

## 📋 Files Overview

### Core Files
- **`telegram_rss_bot.py`** - Main bot with Telegram integration
- **`setup_telegram_bot.py`** - Interactive setup and configuration checker
- **`test_telegram_bot.py`** - Quick test script

### Configuration
- **`.env.example`** - Environment variables template
- **`requirements.txt`** - Python dependencies

## 🛠️ Setup Process

### Step 1: Create Telegram Bot
1. Message @BotFather on Telegram
2. Send `/newbot`
3. Choose bot name and username
4. Copy the bot token

### Step 2: Get Chat ID
**For Personal Chat:**
1. Start a chat with your bot
2. Send any message
3. Visit: `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. Find your chat ID in the response

**For Channel/Group:**
1. Add bot as administrator
2. Send a message to the channel
3. Use the same getUpdates method
4. Channel IDs usually start with `-100`

### Step 3: Configure .env
```env
BOT_TOKEN=1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
CHAT_ID=-1001234567890
TEST_MODE=True
ADMIN_ID=123456789
```

## 🧪 Testing Modes

### Test Mode (`TEST_MODE=True`)
- Messages are printed to console instead of sent
- Perfect for development and debugging
- No actual Telegram API calls

### Live Mode (`TEST_MODE=False`)
- Real messages sent to Telegram
- Full API integration
- Rate limiting and error handling

## 🎯 Usage Examples

### Interactive Setup
```bash
python setup_telegram_bot.py
```
Options:
1. Show setup guide
2. Check configuration
3. Test bot connection
4. Test chat connection
5. Send test message
6. Run all tests

### Quick Test
```bash
python test_telegram_bot.py
```
- Checks configuration
- Runs test environment
- Sends sample news

### Single Run Test
```bash
RUN_ONCE=True python telegram_rss_bot.py
```
- Runs once and exits
- Perfect for testing

### Production Mode
```bash
python telegram_rss_bot.py
```
- Runs continuously
- Updates every 4 hours
- Full scheduling

## 📊 Message Format

The bot sends well-formatted messages with:

```
🌍 **GLOBAL NEWS DIGEST** 🌍
🕐 Updated: 2026-02-01 12:00 UTC
🤖 Mode: TEST MODE

📰 **NEWS DISCLAIMER** 📰
We don't own any news rights...

---

🔹 **Article Title**
Brief description...

📖 [Read Full Article](link)
📍 **Source:** News Outlet (Country)
💡 **About:** Source description
🕒 **Published:** Date/Time

---
```

## 🔧 Configuration Options

### Environment Variables
- `BOT_TOKEN` - Telegram bot token (required)
- `CHAT_ID` - Target chat ID (required)
- `TEST_MODE` - Enable test mode (default: True)
- `ADMIN_ID` - Admin user ID (optional)
- `DEBUG_MODE` - Enable debug logging (default: False)

### Runtime Options
- `RUN_ONCE=True` - Run once and exit
- `TEST_MODE=True` - Console output only

## 🚨 Troubleshooting

### Common Issues

**"Bot token not found"**
- Check your .env file
- Ensure BOT_TOKEN is set correctly

**"Chat ID not accessible"**
- Verify chat ID format
- Ensure bot is admin in channels/groups
- Check privacy settings for personal chats

**"Message too long"**
- Bot automatically splits long messages
- Each part is sent separately

**"Rate limiting"**
- Bot includes delays between messages
- Respects Telegram API limits

### Debug Mode
Enable detailed logging:
```env
DEBUG_MODE=True
```

### Test Commands
```bash
# Check configuration
python -c "from dotenv import load_dotenv; load_dotenv(); print('BOT_TOKEN:', '✅' if os.getenv('BOT_TOKEN') else '❌')"

# Test API connection
curl "https://api.telegram.org/bot<TOKEN>/getMe"

# Test message
curl -X POST "https://api.telegram.org/bot<TOKEN>/sendMessage" -d "chat_id=<CHAT_ID>&text=Test"
```

## 📈 Features

### ✅ Implemented
- [x] Telegram bot integration
- [x] Test mode with console output
- [x] Message splitting for long content
- [x] Error handling and retries
- [x] Configuration validation
- [x] Interactive setup tool
- [x] Proper attribution and disclaimers
- [x] Rate limiting
- [x] Logging and debugging

### 🔄 Scheduled Features
- Automatic news updates every 4 hours
- Persistent scheduling
- Error recovery

### 🛡️ Safety Features
- Test mode to prevent accidental posts
- Configuration validation
- Rate limiting
- Error handling
- Logging

## 📝 Development Notes

### Adding New Sources
Edit `telegram_rss_bot.py`:
```python
self.rss_sources["New Source"] = {
    "url": "https://example.com/feed.xml",
    "description": "Source description",
    "country": "Country"
}
```

### Customizing Message Format
Edit the `format_article()` method in `telegram_rss_bot.py`.

### Adding New Platforms
Use the `send_telegram_message()` method as a template for other platforms.

## 📞 Support

If you encounter issues:
1. Run `python setup_telegram_bot.py` for diagnostics
2. Check the log files: `telegram_rss_bot.log`
3. Verify your .env configuration
4. Test with `TEST_MODE=True` first

## 🔐 Security

- Keep your bot token secret
- Use environment variables, not hard-coded tokens
- Enable test mode during development
- Monitor your bot's activity
- Respect Telegram's Terms of Service
