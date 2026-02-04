import telebot
import os
import threading
import time
from telebot.types import Message
from src.config import BOT_TOKEN, ADMIN_ID
from src.utils import safe_log
from src.database import get_todays_posts_stats

# Initialize the bot
bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

def is_admin(user_id):
    """Check if the user is the admin"""
    if not ADMIN_ID:
        return False
    return str(user_id) == str(ADMIN_ID)

@bot.message_handler(commands=['start'])
def handle_start(message: Message):
    """
    Handle /start command
    Admin: "Scrapper is Awake and active"
    User: "Welcome! I am your Anime & World News Bot."
    """
    user_id = message.from_user.id
    username = message.from_user.username or "User"
    
    if is_admin(user_id):
        text = "🚀 **Scrapper is Awake and active**"
        safe_log("info", f"Admin {username} started the bot interaction.")
    else:
        text = (
            f"👋 Welcome {username}!\n\n"
            "I am the **Anime & World News Bot**.\n"
            "I deliver the latest updates every 2 hours."
        )
        safe_log("info", f"User {username} ({user_id}) started the bot.")
        
    bot.reply_to(message, text, parse_mode="Markdown")

@bot.message_handler(commands=['posts'])
def handle_posts(message: Message):
    """
    Handle /posts command
    Admin: Show detailed stats for today
    User: Ignore
    """
    user_id = message.from_user.id
    
    if not is_admin(user_id):
        # Ignore non-admins
        return

    safe_log("info", f"Admin requested /posts stats.")
    
    stats = get_todays_posts_stats()
    
    if not stats:
        bot.reply_to(message, "⚠️ **Could not fetch statistics from database.**", parse_mode="Markdown")
        return

    total = stats['total']
    sent = stats['sent']
    
    # Build the report
    report = [
        f"📊 **Today's Activity Report**",
        f"━━━━━━━━━━━━━━━━━━",
        f"**Total Posts:** {total}",
        f"**Successfully Sent:** {sent}",
        f"",
        f"**Source Breakdown:**"
    ]
    
    if stats['sources']:
        sorted_sources = sorted(stats['sources'].items(), key=lambda x: x[1], reverse=True)
        for src, count in sorted_sources:
            report.append(f"• `{src}`: {count}")
    else:
        report.append("• No posts recorded yet.")
        
    report.append(f"━━━━━━━━━━━━━━━━━━")
    
    # Send report
    bot.reply_to(message, "\n".join(report), parse_mode="Markdown")

def start_bot_listener():
    """
    Start the bot polling in a separate thread.
    This allows it to run alongside the scheduler.
    """
    def runner():
        safe_log("info", "Starting Telegram command listener...")
        while True:
            try:
                # Remove webhook if it exists (conflicts with polling)
                bot.remove_webhook()
                # Start polling
                bot.infinity_polling(timeout=20, long_polling_timeout=20)
            except Exception as e:
                safe_log("error", f"Telegram polling failed: {e}")
                time.sleep(5) # Wait before retry

    t = threading.Thread(target=runner, daemon=True)
    t.start()
