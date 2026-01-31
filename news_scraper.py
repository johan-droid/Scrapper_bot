#!/usr/bin/env python3
"""
RSS News Scraper
Scrapes news from various RSS feeds every 4 hours with proper attribution.
Disclaimer: We don't own any news rights. All content belongs to respective sources.
"""

import requests
import schedule
import time
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
import os
from dotenv import load_dotenv
import json
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('news_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class NewsScraper:
    def __init__(self):
        # Original news sources with RSS feeds
        self.rss_sources = {
            "NewsLaundry": {
                "url": "https://www.newslaundry.com/feed",
                "description": "Independent Indian news outlet",
                "country": "India"
            },
            "The Wire": {
                "url": "https://thewire.in/feed",
                "description": "Indian nonprofit news and media website", 
                "country": "India"
            },
            "Caravan Magazine": {
                "url": "https://caravanmagazine.in/feed",
                "description": "Indian literary and politics magazine",
                "country": "India"
            },
            "Scroll.in": {
                "url": "https://scroll.in/feed",
                "description": "Indian independent news publication",
                "country": "India"
            },
            "The Print": {
                "url": "https://theprint.in/feed",
                "description": "Indian news and media website",
                "country": "India"
            },
            "Al Jazeera": {
                "url": "https://www.aljazeera.com/xml/rss/all.xml",
                "description": "Non-Western perspective on global conflicts; ruthless coverage of the Middle East and Global South",
                "country": "Qatar"
            },
            "The Intercept": {
                "url": "https://theintercept.com/feed/?lang=en",
                "description": "Founded to publish the Snowden leaks. Focuses on surveillance, corruption, and war crimes",
                "country": "USA"
            },
            "ProPublica": {
                "url": "https://www.propublica.org/feeds/propublica/main",
                "description": "Non-profit investigative journalism. They expose abuses of power",
                "country": "USA"
            }
        }
        
        self.disclaimer = """
📰 **NEWS DISCLAIMER** 📰
We don't own any news rights. All content belongs to respective sources.
This bot aggregates news for informational purposes only.
Please visit the original sources for full articles.

🤖 **Bot Features:**
• 📰 General News (8 sources) - This channel
• 🌍 World News (10 sources) - Separate channel
• 🎬 Entertainment (13 sources) - Reddit channel
• 🖼️ High-quality image extraction
• ⚖️ Proper source attribution
        """
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'RSS-News-Scraper/1.0 (Educational Purpose)'
        })

    def fetch_rss_feed(self, source_name: str, source_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch and parse RSS feed from a source."""
        try:
            logger.info(f"Fetching RSS feed from {source_name}")
            
            response = self.session.get(source_info["url"], timeout=30)
            response.raise_for_status()
            
            # Parse XML using ElementTree
            root = ET.fromstring(response.content)
            
            articles = []
            
            # Handle different RSS formats
            if root.tag == 'rss' or root.tag == 'rdf:RDF':
                items = root.findall('.//item')
                if not items:
                    items = root.findall('.//{http://purl.org/rss/1.0/}item')
            elif root.tag == 'feed':
                items = root.findall('.//{http://www.w3.org/2005/Atom}entry')
            else:
                items = root.findall('.//item') or root.findall('.//entry')
            
            for item in items[:5]:  # Get latest 5 articles per source
                try:
                    # Extract title
                    title = 'No Title'
                    title_elem = item.find('title')
                    if title_elem is not None and title_elem.text:
                        title = title_elem.text.strip()
                    else:
                        # Try Atom namespace
                        title_elem = item.find('.//{http://www.w3.org/2005/Atom}title')
                        if title_elem is not None and title_elem.text:
                            title = title_elem.text.strip()
                    
                    # Extract link
                    link = ''
                    link_elem = item.find('link')
                    if link_elem is not None:
                        if link_elem.text:
                            link = link_elem.text.strip()
                        elif link_elem.get('href'):
                            link = link_elem.get('href')
                    else:
                        # Try Atom namespace
                        link_elem = item.find('.//{http://www.w3.org/2005/Atom}link')
                        if link_elem is not None and link_elem.get('href'):
                            link = link_elem.get('href')
                    
                    # Extract description
                    description = ''
                    desc_elem = item.find('description')
                    if desc_elem is not None and desc_elem.text:
                        desc_text = BeautifulSoup(desc_elem.text, 'html.parser').get_text()
                        description = desc_text[:200] + '...' if len(desc_text) > 200 else desc_text
                    else:
                        # Try summary (Atom)
                        desc_elem = item.find('.//{http://www.w3.org/2005/Atom}summary')
                        if desc_elem is not None and desc_elem.text:
                            desc_text = BeautifulSoup(desc_elem.text, 'html.parser').get_text()
                            description = desc_text[:200] + '...' if len(desc_text) > 200 else desc_text
                        else:
                            # Try content (Atom)
                            desc_elem = item.find('.//{http://www.w3.org/2005/Atom}content')
                            if desc_elem is not None and desc_elem.text:
                                desc_text = BeautifulSoup(desc_elem.text, 'html.parser').get_text()
                                description = desc_text[:200] + '...' if len(desc_text) > 200 else desc_text
                    
                    # Extract publication date
                    published = ''
                    pub_elem = item.find('pubDate')
                    if pub_elem is not None and pub_elem.text:
                        published = pub_elem.text.strip()
                    else:
                        # Try Atom published
                        pub_elem = item.find('.//{http://www.w3.org/2005/Atom}published')
                        if pub_elem is not None and pub_elem.text:
                            published = pub_elem.text.strip()
                        else:
                            # Try date
                            pub_elem = item.find('date')
                            if pub_elem is not None and pub_elem.text:
                                published = pub_elem.text.strip()
                    
                    article = {
                        'title': title,
                        'link': link,
                        'description': description,
                        'published': published,
                        'source': source_name,
                        'source_description': source_info['description'],
                        'country': source_info['country']
                    }
                    articles.append(article)
                    
                except Exception as e:
                    logger.warning(f"Error parsing article from {source_name}: {str(e)}")
                    continue
            
            logger.info(f"Successfully fetched {len(articles)} articles from {source_name}")
            return articles
            
        except Exception as e:
            logger.error(f"Error fetching RSS feed from {source_name}: {str(e)}")
            return []

    def format_article(self, article: Dict[str, Any]) -> str:
        """Format an article with proper attribution."""
        formatted = f"""
🔹 **{article['title']}**

{article['description']}

📖 [Read Full Article]({article['link']})

📍 **Source:** {article['source']} ({article['country']})
💡 **About:** {article['source_description']}
🕒 **Published:** {article['published']}

---
        """
        return formatted.strip()

    def save_news_to_file(self, news_content: str) -> None:
        """Save news content to a file."""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"news_update_{timestamp}.txt"
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(news_content)
            
            logger.info(f"News update saved to {filename}")
            
        except Exception as e:
            logger.error(f"Error saving news to file: {str(e)}")

    def fetch_all_news(self) -> str:
        """Fetch news from all sources and format with disclaimer."""
        logger.info("Starting news fetch from all sources")
        
        all_articles = []
        
        for source_name, source_info in self.rss_sources.items():
            articles = self.fetch_rss_feed(source_name, source_info)
            all_articles.extend(articles)
            
            # Add small delay between requests to be respectful
            time.sleep(1)
        
        # Sort by published date if available
        all_articles.sort(key=lambda x: x.get('published', ''), reverse=True)
        
        # Format the complete news update
        news_update = f"""
🌍 **GLOBAL NEWS DIGEST** 🌍
🕐 Updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
📊 Sources: {len(self.rss_sources)} news outlets • 4-hour updates

{self.disclaimer}

---
"""
        
        # Add articles (limit to prevent too long messages)
        for i, article in enumerate(all_articles[:15]):  # Limit to 15 articles total
            news_update += f"\n{self.format_article(article)}\n"
            
            if i < len(all_articles[:15]) - 1:
                news_update += "---\n"
        
        news_update += f"\n{self.disclaimer}"
        
        logger.info(f"Formatted news update with {len(all_articles[:15])} articles")
        return news_update

    def run_news_update(self) -> None:
        """Main function to run the news update."""
        try:
            logger.info("Starting scheduled news update")
            
            news_content = self.fetch_all_news()
            
            # Save to file
            self.save_news_to_file(news_content)
            
            # Send status update to show bot features
            self.send_status_summary()
            
            logger.info("News update completed successfully")
            
        except Exception as e:
            logger.error(f"Error in news update: {str(e)}")

    def send_status_summary(self) -> None:
        """Send brief status summary about bot capabilities"""
        try:
            status_msg = f"""
📰 **News Update Complete** ✅
🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
📊 Sources: {len(self.rss_sources)} news outlets

🤖 **Bot Features:**
• 📰 General News (8 sources) - This channel
• 🌍 World News (10 sources) - Separate channel
• 🎬 Entertainment (13 sources) - Reddit channel
• 🖼️ High-quality image extraction
• ⚖️ Proper source attribution

Next update in 4 hours ⏰
            """
            
            # This would integrate with your existing Telegram posting
            # For now, just log it
            logger.info("Status summary ready for posting")
            
        except Exception as e:
            logger.error(f"Error sending status summary: {str(e)}")

    def start_scheduler(self) -> None:
        """Start the scheduler to run news updates every 4 hours."""
        logger.info("Starting RSS News Scraper scheduler")
        
        # Schedule news update every 4 hours
        schedule.every(4).hours.do(self.run_news_update)
        
        # Run once immediately on start
        logger.info("Running initial news update")
        self.run_news_update()
        
        # Keep the scheduler running
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute

def main():
    """Main function to start the RSS News Scraper."""
    try:
        scraper = NewsScraper()
        logger.info("RSS News Scraper started successfully")
        
        # Start scheduler
        scraper.start_scheduler()
            
    except KeyboardInterrupt:
        logger.info("RSS News Scraper stopped by user")
    except Exception as e:
        logger.error(f"Fatal error in RSS News Scraper: {str(e)}")

if __name__ == "__main__":
    main()
