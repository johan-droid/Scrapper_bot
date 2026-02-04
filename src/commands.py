import telebot
import os
import threading
import time
from telebot.types import Message
from src.config import BOT_TOKEN, ADMIN_ID
from src.utils import safe_log
from src.database import get_todays_posts_stats

# Initialize the bot
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)

def is_admin(user_id):
    """Check if the user is the admin"""
    if not ADMIN_ID:
        safe_log("warning", "ADMIN_ID not set in environment!")
        return False
    
    is_match = str(user_id) == str(ADMIN_ID)
    if not is_match:
        safe_log("debug", f"Admin check failed: User {user_id} != Admin {ADMIN_ID}")
    return is_match

@bot.message_handler(commands=['start'])
def handle_start(message: Message):
    """
    Handle /start command
    Admin: "Scrapper is Awake and active"
    User: "Welcome! I am your Anime & World News Bot."
    """
    try:
        user_id = message.from_user.id
        username = message.from_user.username or "User"
        safe_log("info", f"Received /start from {username} (ID: {user_id})")
        
        if is_admin(user_id):
            text = "🚀 **Scrapper is Awake and active**\n\nCommand me, Master."
            safe_log("info", f"Recognized Admin {username}. Sending admin greeting.")
        else:
            text = (
                f"👋 Welcome {username}!\n\n"
                "I am the **Anime & World News Bot**.\n"
                "I deliver the latest updates every 2 hours."
            )
            safe_log("info", f"Responded to User {username} (Non-Admin).")
            
        bot.reply_to(message, text, parse_mode="Markdown")
    except Exception as e:
        safe_log("error", f"Error in /start handler: {e}")

@bot.message_handler(commands=['posts'])
def handle_posts(message: Message):
    """
    Handle /posts command
    Admin: Show detailed stats for today
    User: Ignore
    """
    try:
        user_id = message.from_user.id
        safe_log("info", f"Received /posts from ID: {user_id}")
        
        if not is_admin(user_id):
            safe_log("info", f"Ignoring /posts from non-admin {user_id}")
            return

        safe_log("info", f"Admin requested /posts stats. Fetching DB...")
        bot.send_chat_action(message.chat.id, 'typing')
        
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
            report.append("• No posts recorded yet today.")
            
        report.append(f"━━━━━━━━━━━━━━━━━━")
        
        # Send report
        bot.reply_to(message, "\n".join(report), parse_mode="Markdown")
        safe_log("info", "Sent /posts report to admin.")
        
    except Exception as e:
        safe_log("error", f"Error in /posts handler: {e}")
        bot.reply_to(message, f"❌ Check logs: {str(e)[:50]}")

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
