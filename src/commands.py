import logging
import datetime
from src.bot import run_once
from src.config import ADMIN_ID

# Setup logging
logger = logging.getLogger(__name__)

def register_handlers(bot):
    """
    Register command handlers for the TeleBot instance
    """
    
    @bot.message_handler(commands=['start'])
    def start_command(message):
        user = message.from_user
        logger.info(f"Command /start triggered by {user.first_name} ({user.id})")
        
        welcome_msg = (
            f"👋 Hello {user.first_name}!\n\n"
            f"I am the Scrapper Bot. I run automatically every few hours.\n\n"
            f"<b>Available Commands:</b>\n"
            f"/status - Check bot health\n"
            f"/force - Force a scraper run (Admin only)\n"
            f"/ping - Simple connectivity check"
        )
        
        bot.reply_to(message, welcome_msg, parse_mode='HTML')

    @bot.message_handler(commands=['ping'])
    def ping_command(message):
        bot.reply_to(message, "🏓 Pong! I'm awake and listening.")

    @bot.message_handler(commands=['status'])
    def status_command(message):
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        bot.reply_to(message, 
            f"🤖 <b>System Status</b>\n"
            f"🕒 Time: {now}\n"
            f"✅ Bot is running\n"
            f"✅ Scheduler is active (background)",
            parse_mode='HTML'
        )

    @bot.message_handler(commands=['force'])
    def force_run_command(message):
        user_id = message.from_user.id
        
        if str(user_id) != str(ADMIN_ID):
            bot.reply_to(message, "⛔ You are not authorized to use this command.")
            return

        bot.reply_to(message, "🚀 Force run initiated! Check logs/channel for updates.")
        
        # Run the scraper code (synchronously)
        try:
            run_once()
            bot.reply_to(message, "✅ Force run completed.")
        except Exception as e:
            bot.reply_to(message, f"❌ Force run failed: {e}")
