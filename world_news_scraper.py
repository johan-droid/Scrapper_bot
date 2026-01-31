#!/usr/bin/env python3
"""
World News Scraper with High-Quality Image Extraction
Scrapes world news from RSS feeds and posts to dedicated Telegram channel.
Disclaimer: We don't own any news rights. All content belongs to respective sources.
"""

import requests
import schedule
import time
import logging
import os
import re
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
import json
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import io
from PIL import Image
import hashlib

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('world_news_scraper.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class WorldNewsScraper:
    def __init__(self):
        # World news RSS sources with high-quality content
        self.world_news_sources = {
            "BBC World": {
                "url": "http://feeds.bbci.co.uk/news/world/rss.xml",
                "description": "BBC World News - Global coverage from the British Broadcasting Corporation",
                "country": "UK",
                "priority": 1
            },
            "Reuters World": {
                "url": "https://www.reuters.com/rssFeed/worldNews",
                "description": "Reuters World News - International news agency coverage",
                "country": "International",
                "priority": 1
            },
            "Al Jazeera": {
                "url": "https://www.aljazeera.com/xml/rss/all.xml",
                "description": "Al Jazeera English - Non-Western perspective on global conflicts",
                "country": "Qatar",
                "priority": 1
            },
            "CNN World": {
                "url": "http://rss.cnn.com/rss/edition_world.rss",
                "description": "CNN World News - American global news coverage",
                "country": "USA",
                "priority": 2
            },
            "The Guardian World": {
                "url": "https://www.theguardian.com/world/rss",
                "description": "The Guardian World News - Progressive international coverage",
                "country": "UK",
                "priority": 2
            },
            "AP World": {
                "url": "https://apnews.com/rss/world-news",
                "description": "Associated Press World News - Factual international reporting",
                "country": "USA",
                "priority": 2
            },
            "NPR International": {
                "url": "https://feeds.npr.org/1001/rss.xml",
                "description": "NPR International - In-depth global news and analysis",
                "country": "USA",
                "priority": 3
            },
            "Deutsche Welle": {
                "url": "https://www.dw.com/en/rss/rss-en-all",
                "description": "Deutsche Welle - German international broadcasting",
                "country": "Germany",
                "priority": 3
            },
            "France 24": {
                "url": "https://www.france24.com/en/rss",
                "description": "France 24 - French international news network",
                "country": "France",
                "priority": 3
            },
            "CBC World": {
                "url": "https://www.cbc.ca/cmlink/rss-world",
                "description": "CBC World News - Canadian international coverage",
                "country": "Canada",
                "priority": 3
            }
        }
        
        self.disclaimer = """
🌍 **WORLD NEWS DISCLAIMER** 🌍
We don't own any news rights. All content belongs to respective sources.
This bot aggregates world news for informational purposes only.
Please visit the original sources for full articles and images.

🤖 **Bot Features:**
• 🌍 World News (10 premium sources) - This channel
• 📰 General News (8 sources) - Main channel
• 🎬 Entertainment (13 sources) - Reddit channel
• 🖼️ High-quality image extraction
• ⚖️ Proper source attribution
        """
        
        # Telegram configuration
        self.bot_token = os.getenv('BOT_TOKEN')
        self.world_news_channel_id = os.getenv('WORLD_NEWS_CHANNEL_ID')
        self.admin_id = os.getenv('ADMIN_ID')
        
        # Session for requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'World-News-Scraper/1.0 (Educational Purpose)'
        })
        
        # Image processing settings
        self.max_image_size = (1200, 800)  # Max dimensions
        self.quality = 85  # JPEG quality
        self.max_file_size = 5 * 1024 * 1024  # 5MB Telegram limit

    def validate_image_url(self, url: str) -> bool:
        """Validate if image URL is accessible and suitable"""
        if not url:
            return False
        
        try:
            # Check file extension
            parsed = urlparse(url)
            if not any(parsed.path.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                return False
            
            # Check if image is accessible
            response = self.session.head(url, timeout=10, allow_redirects=True)
            if response.status_code != 200:
                return False
            
            # Check content type
            content_type = response.headers.get('content-type', '').lower()
            if not content_type.startswith('image/'):
                return False
            
            # Check file size
            content_length = response.headers.get('content-length')
            if content_length and int(content_length) > self.max_file_size:
                return False
            
            return True
            
        except Exception as e:
            logger.warning(f"Image validation failed for {url}: {str(e)}")
            return False

    def download_and_process_image(self, url: str) -> Optional[bytes]:
        """Download and process image for Telegram"""
        if not self.validate_image_url(url):
            return None
        
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            # Process image
            image = Image.open(io.BytesIO(response.content))
            
            # Convert to RGB if necessary
            if image.mode in ('RGBA', 'P'):
                image = image.convert('RGB')
            
            # Resize if too large
            if image.size[0] > self.max_image_size[0] or image.size[1] > self.max_image_size[1]:
                image.thumbnail(self.max_image_size, Image.Resampling.LANCZOS)
            
            # Save to bytes
            img_buffer = io.BytesIO()
            image.save(img_buffer, format='JPEG', quality=self.quality, optimize=True)
            img_data = img_buffer.getvalue()
            
            # Check final size
            if len(img_data) > self.max_file_size:
                logger.warning(f"Image too large after processing: {len(img_data)} bytes")
                return None
            
            return img_data
            
        except Exception as e:
            logger.error(f"Error processing image {url}: {str(e)}")
            return None

    def extract_high_quality_image(self, article_url: str, rss_image_url: str = None) -> Optional[str]:
        """Extract high-quality image from article page"""
        # First try the RSS image
        if rss_image_url and self.validate_image_url(rss_image_url):
            return rss_image_url
        
        try:
            # Fetch article page
            response = self.session.get(article_url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for high-quality images in common locations
            image_selectors = [
                'meta[property="og:image"]',
                'meta[name="twitter:image"]',
                'meta[property="og:image:secure_url"]',
                '.article img[src]',
                '.story-image img[src]',
                '.featured-image img[src]',
                '.main-image img[src]',
                'article img[src]',
                '.content img[src]'
            ]
            
            for selector in image_selectors:
                elements = soup.select(selector)
                for element in elements:
                    if element.name == 'meta':
                        img_url = element.get('content')
                    else:
                        img_url = element.get('src')
                    
                    if img_url:
                        # Convert relative URLs to absolute
                        if img_url.startswith('//'):
                            img_url = 'https:' + img_url
                        elif img_url.startswith('/'):
                            img_url = urljoin(article_url, img_url)
                        
                        # Skip small images and common non-content images
                        if any(skip in img_url.lower() for skip in ['logo', 'icon', 'avatar', 'thumbnail']):
                            continue
                        
                        if self.validate_image_url(img_url):
                            return img_url
            
        except Exception as e:
            logger.warning(f"Error extracting image from {article_url}: {str(e)}")
        
        return None

    def fetch_rss_feed(self, source_name: str, source_info: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch and parse RSS feed from a world news source."""
        try:
            logger.info(f"Fetching world news from {source_name}")
            
            response = self.session.get(source_info["url"], timeout=30)
            response.raise_for_status()
            
            # Parse XML
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
                        link_elem = item.find('.//{http://www.w3.org/2005/Atom}link')
                        if link_elem is not None and link_elem.get('href'):
                            link = link_elem.get('href')
                    
                    # Extract description
                    description = ''
                    desc_elem = item.find('description')
                    if desc_elem is not None and desc_elem.text:
                        desc_text = BeautifulSoup(desc_elem.text, 'html.parser').get_text()
                        description = desc_text[:300] + '...' if len(desc_text) > 300 else desc_text
                    else:
                        desc_elem = item.find('.//{http://www.w3.org/2005/Atom}summary')
                        if desc_elem is not None and desc_elem.text:
                            desc_text = BeautifulSoup(desc_elem.text, 'html.parser').get_text()
                            description = desc_text[:300] + '...' if len(desc_text) > 300 else desc_text
                    
                    # Extract publication date
                    published = ''
                    pub_elem = item.find('pubDate')
                    if pub_elem is not None and pub_elem.text:
                        published = pub_elem.text.strip()
                    else:
                        pub_elem = item.find('.//{http://www.w3.org/2005/Atom}published')
                        if pub_elem is not None and pub_elem.text:
                            published = pub_elem.text.strip()
                    
                    # Extract image from RSS
                    rss_image = None
                    image_elem = item.find('enclosure')
                    if image_elem is not None and image_elem.get('type', '').startswith('image/'):
                        rss_image = image_elem.get('url')
                    else:
                        # Try media:content
                        media_elem = item.find('.//{http://search.yahoo.com/mrss/}content')
                        if media_elem is not None and media_elem.get('medium') == 'image':
                            rss_image = media_elem.get('url')
                    
                    # Extract high-quality image
                    high_quality_image = None
                    if link:
                        high_quality_image = self.extract_high_quality_image(link, rss_image)
                    
                    article = {
                        'title': title,
                        'link': link,
                        'description': description,
                        'published': published,
                        'source': source_name,
                        'source_description': source_info['description'],
                        'country': source_info['country'],
                        'priority': source_info['priority'],
                        'image_url': high_quality_image,
                        'rss_image': rss_image
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

    def send_telegram_message(self, message: str, image_data: bytes = None) -> bool:
        """Send message to Telegram world news channel"""
        if not self.bot_token or not self.world_news_channel_id:
            logger.warning("Telegram configuration missing. Skipping message send.")
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            
            # Split message if too long
            if len(message) > 4096:
                messages = [message[i:i+4096] for i in range(0, len(message), 4096)]
            else:
                messages = [message]
            
            for i, msg in enumerate(messages):
                data = {
                    'chat_id': self.world_news_channel_id,
                    'text': msg,
                    'parse_mode': 'Markdown',
                    'disable_web_page_preview': False if image_data else True
                }
                
                response = requests.post(url, json=data, timeout=30)
                result = response.json()
                
                if not result.get('ok'):
                    logger.error(f"Telegram API error: {result.get('description')}")
                    return False
                
                # If we have an image, send it after the first message
                if image_data and i == 0:
                    self.send_telegram_photo(image_data, message[:1000])
                
                logger.info(f"Message part {i+1}/{len(messages)} sent successfully")
            
            return True
            
        except Exception as e:
            logger.error(f"Error sending Telegram message: {str(e)}")
            return False

    def send_telegram_photo(self, image_data: bytes, caption: str) -> bool:
        """Send photo to Telegram"""
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
            
            files = {
                'photo': ('world_news.jpg', image_data, 'image/jpeg')
            }
            
            data = {
                'chat_id': self.world_news_channel_id,
                'caption': caption[:1024],  # Telegram caption limit
                'parse_mode': 'Markdown'
            }
            
            response = requests.post(url, files=files, data=data, timeout=30)
            result = response.json()
            
            if result.get('ok'):
                logger.info("Photo sent successfully")
                return True
            else:
                logger.error(f"Photo send error: {result.get('description')}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending photo: {str(e)}")
            return False

    def format_world_article(self, article: Dict[str, Any]) -> str:
        """Format world news article with proper attribution"""
        formatted = f"""
🌍 **{article['title']}**

{article['description']}

📖 [Read Full Article]({article['link']})

📍 **Source:** {article['source']} ({article['country']})
💡 **About:** {article['source_description']}
🕒 **Published:** {article['published']}

{self.disclaimer}
        """
        return formatted.strip()

    def fetch_and_post_world_news(self) -> None:
        """Fetch world news and post to Telegram channel"""
        logger.info("Starting world news fetch and post")
        
        try:
            # Fetch news from all sources
            all_articles = []
            
            for source_name, source_info in self.world_news_sources.items():
                articles = self.fetch_rss_feed(source_name, source_info)
                all_articles.extend(articles)
                time.sleep(1)  # Respect rate limits
            
            # Sort by priority and published date
            all_articles.sort(key=lambda x: (x['priority'], x.get('published', '')), reverse=True)
            
            # Get top articles with images
            featured_articles = []
            other_articles = []
            
            for article in all_articles[:20]:  # Limit to top 20
                if article['image_url']:
                    featured_articles.append(article)
                else:
                    other_articles.append(article)
            
            # Post featured articles with images
            for i, article in enumerate(featured_articles[:5]):  # Top 5 with images
                logger.info(f"Processing featured article {i+1}: {article['title'][:50]}...")
                
                # Download and process image
                image_data = self.download_and_process_image(article['image_url'])
                
                # Format message
                message = self.format_world_article(article)
                
                # Send with image if available
                success = self.send_telegram_message(message, image_data)
                
                if success:
                    logger.info(f"Successfully posted featured article from {article['source']}")
                else:
                    logger.error(f"Failed to post featured article from {article['source']}")
                
                # Delay between posts
                time.sleep(2)
            
            # Post other articles without images
            for i, article in enumerate(other_articles[:10]):  # Top 10 without images
                logger.info(f"Processing article {i+1}: {article['title'][:50]}...")
                
                message = self.format_world_article(article)
                success = self.send_telegram_message(message)
                
                if success:
                    logger.info(f"Successfully posted article from {article['source']}")
                else:
                    logger.error(f"Failed to post article from {article['source']}")
                
                time.sleep(1)
            
            logger.info("World news posting completed successfully")
            
        except Exception as e:
            logger.error(f"Error in world news posting: {str(e)}")

    def start_scheduler(self) -> None:
        """Start scheduler for world news updates"""
        logger.info("Starting World News Scraper scheduler")
        
        # Schedule updates every 4 hours
        schedule.every(4).hours.do(self.fetch_and_post_world_news)
        
        # Run once immediately on start
        logger.info("Running initial world news update")
        self.fetch_and_post_world_news()
        
        # Keep the scheduler running
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute

def main():
    """Main function to start the World News Scraper"""
    try:
        scraper = WorldNewsScraper()
        logger.info("World News Scraper started successfully")
        
        # Start scheduler
        scraper.start_scheduler()
            
    except KeyboardInterrupt:
        logger.info("World News Scraper stopped by user")
    except Exception as e:
        logger.error(f"Fatal error in World News Scraper: {str(e)}")

if __name__ == "__main__":
    main()
