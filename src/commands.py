import logging
import datetime
from telegram import Update
from telegram.ext import ContextTypes
from src.bot import run_once
from src.config import ADMIN_ID, CHAT_ID

# Setup logging
logger = logging.getLogger(__name__)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle /start command
    """
    user = update.effective_user
    logger.info(f"Command /start triggered by {user.first_name} ({user.id})")
    
    welcome_msg = (
        f"👋 Hello {user.first_name}!\n\n"
        f"I am the Scrapper Bot. I run automatically every few hours.\n\n"
        f"<b>Available Commands:</b>\n"
        f"/status - Check bot health\n"
        f"/force - Force a scraper run (Admin only)\n"
        f"/ping - Simple connectivity check"
    )
    
    await update.message.reply_html(welcome_msg)

async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle /ping command - Simple check
    """
    await update.message.reply_text("🏓 Pong! I'm awake and listening.")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle /status command
    """
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    await update.message.reply_html(
        f"🤖 <b>System Status</b>\n"
        f"🕒 Time: {now}\n"
        f"✅ Bot is running\n"
        f"✅ Scheduler is active (background)"
    )

async def force_run_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle /force command - Manually trigger scraping
    Only for Admin
    """
    user_id = update.effective_user.id
    
    if str(user_id) != str(ADMIN_ID):
        await update.message.reply_text("⛔ You are not authorized to use this command.")
        return

    await update.message.reply_text("🚀 Force run initiated! Check logs/channel for updates.")
    
    # Run the scraper code (synchronously)
    # Note: run_once is a sync function, so we run it directly or in executor if needed.
    # For now, running directly is fine for simple usage, though it might block the bot for a bit.
    try:
        run_once()
        await update.message.reply_text("✅ Force run completed.")
    except Exception as e:
        await update.message.reply_text(f"❌ Force run failed: {e}")
