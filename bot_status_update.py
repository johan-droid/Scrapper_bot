#!/usr/bin/env python3
"""
Bot Status Update - Sends comprehensive status message to all channels
"""

import requests
import os
from dotenv import load_dotenv
from datetime import datetime, timezone

load_dotenv()

def send_status_update():
    """Send status update to all configured channels"""
    
    bot_token = os.getenv('BOT_TOKEN')
    main_channel_id = os.getenv('CHAT_ID')
    world_news_channel_id = os.getenv('WORLD_NEWS_CHANNEL_ID')
    reddit_channel_id = os.getenv('REDDIT_CHANNEL_ID')
    
    if not bot_token:
        print("❌ No BOT_TOKEN configured")
        return
    
    # Status message with new features
    status_message = f"""
🤖 **NEWS BOT STATUS UPDATE** 🤖
🕐 Updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

📊 **Bot Capabilities:**
• 📰 **General News**: 8 sources (NewsLaundry, The Wire, Scroll.in, The Print, Al Jazeera, The Intercept, ProPublica, BBC News)
• 🌍 **World News**: 10 premium sources (BBC World, Reuters, Al Jazeera, CNN, Guardian, AP, NPR, DW, France 24, CBC)
• 🎬 **Entertainment**: 13 sources (Anime, Manga, Reddit communities)

🆕 **New Features Added:**
• 🌍 **Dedicated World News Channel** - High-quality international news
• 🖼️ **Advanced Image Extraction** - High-res photos with optimization
• 📱 **Multi-Channel Support** - Separate channels for different content
• ⚖️ **Enhanced Attribution** - Proper source credits and disclaimers
• 🔧 **Smart Scheduling** - 4-hour updates across all channels

📋 **Channel Distribution:**
• 📰 **Main Channel**: General news & updates
• 🌍 **World News Channel**: International news with images
• 🎬 **Reddit Channel**: Entertainment & anime content

🔒 **Security & Compliance:**
• ✅ All credentials secured
• ✅ Proper content attribution
• ✅ Legal disclaimers included
• ✅ Rate limiting implemented
• ✅ Error handling & logging

📈 **Performance:**
• ⚡ Fast RSS parsing
• 🖼️ Image optimization
• 🔄 Automatic retries
• 📊 Comprehensive logging

🎯 **Next Update**: In 4 hours
📞 **Admin**: Contact for issues or feedback

---
📰 **DISCLAIMER**: We don't own any news rights. All content belongs to respective sources.
    """
    
    channels = [
        ("Main Channel", main_channel_id),
        ("World News Channel", world_news_channel_id),
        ("Reddit Channel", reddit_channel_id)
    ]
    
    for channel_name, channel_id in channels:
        if channel_id and channel_id != f"your_{channel_name.lower().replace(' ', '_')}_here":
            try:
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                data = {
                    'chat_id': channel_id,
                    'text': status_message,
                    'parse_mode': 'Markdown',
                    'disable_web_page_preview': True
                }
                
                response = requests.post(url, json=data, timeout=30)
                result = response.json()
                
                if result.get('ok'):
                    print(f"✅ Status update sent to {channel_name}")
                else:
                    print(f"❌ Failed to send to {channel_name}: {result.get('description')}")
                    
            except Exception as e:
                print(f"❌ Error sending to {channel_name}: {str(e)}")
        else:
            print(f"⚠️ {channel_name} not configured")

if __name__ == "__main__":
    send_status_update()
