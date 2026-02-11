# 🌸 FINAL ANIME-ONLY SCRAPER
# This is the ONLY scraper file needed for the anime news bot
# All world news references have been removed and optimized for anime content

import logging
import requests
import random
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dateutil import parser as date_parser
import pytz

from src.config import USER_AGENTS, DEBUG_MODE
from src.utils import safe_log, circuit_breaker, clean_text_extractor, now_local, local_tz
from src.models import NewsItem

def get_scraping_session():
    """Create a robust HTTP session with retries and proper headers"""
    session = requests.Session()
    retry_strategy = Retry(
        total=3, 
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Connection": "close",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Charset": "utf-8",
        "Accept-Encoding": "gzip, deflate"
    })
    return session

def parse_date_flexible(date_string):
    """
    Flexible date parser that handles multiple formats and timezones
    Returns timezone-aware datetime in local timezone
    """
    if not date_string:
        return None
    
    try:
        # Use dateutil parser for maximum flexibility
        dt = date_parser.parse(date_string)
        
        # Handle naive datetimes (assume UTC if missing timezone)
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        
        # Convert to local timezone
        return dt.astimezone(local_tz)
        
    except Exception as e:
        logging.debug(f"Date parsing failed for '{date_string}': {e}")
        
        # Fallback: Try common formats manually
        formats = [
            "%a, %d %b %Y %H:%M:%S %z",      # RFC 822
            "%a, %d %b %Y %H:%M:%S GMT",     # RSS standard
            "%Y-%m-%dT%H:%M:%S%z",           # ISO 8601 with timezone
            "%Y-%m-%dT%H:%M:%SZ",            # ISO 8601 UTC
            "%Y-%m-%d %H:%M:%S",             # Simple format
            "%Y-%m-%d",                      # Date only
        ]
        
        for fmt in formats:
            try:
                if "GMT" in date_string:
                    date_string = date_string.replace("GMT", "+0000")
                
                dt = datetime.strptime(date_string, fmt)
                
                # If no timezone, assume UTC
                if dt.tzinfo is None:
                    dt = pytz.utc.localize(dt)
                
                return dt.astimezone(local_tz)
            except:
                continue
        
        logging.warning(f"Could not parse date: {date_string}")
        return None

def extract_full_article_content(url, source):
    """
    Extract full article content for Telegraph posting with anime-optimized selectors
    Returns dict with 'text', 'images', and 'html'
    """
    session = get_scraping_session()
    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
        
        # Handle different encodings
        response.encoding = response.apparent_encoding or 'utf-8'
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove unwanted elements
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 
                        'iframe', 'ads', 'advertisement', 'social-share', 'related-articles']):
            tag.decompose()
        
        # Anime-only content selectors (optimized for anime sites)
        content_selectors = {
            'ANN': [
                '.article__body-content', 
                '.story-body__inner', 
                '[data-component="text-block"]',
                'article'
            ],
            'CR': [
                '.article-content',
                '.news-detail-body',
                'article'
            ],
            'AC': [
                '.entry-content',
                '.post-content',
                'article'
            ],
            'HONEY': [
                '.entry-content',
                '.article-body',
                'article'
            ],
            'ANI': [
                '.entry-content',
                '.post-content',
                'article'
            ],
            'ANIMEUK': [
                '.entry-content',
                '.post-content',
                'article'
            ],
            'MALFEED': [
                '.entry-content',
                '.post-content',
                'article'
            ],
            'OTAKU': [
                '.entry-content',
                '.post-content',
                'article'
            ],
            'ANIPLANET': [
                '.entry-content',
                '.post-content',
                'article'
            ],
            'KOTAKU': [
                '.entry-content',
                '.post-content',
                'article'
            ],
            'PCGAMER': [
                '.entry-content',
                '.post-content',
                'article'
            ],
            'default': [
                'article', 
                '.post-content', 
                '.entry-content', 
                '.article-content', 
                '.story-content',
                '.main-content'
            ]
        }
        
        selectors = content_selectors.get(source, content_selectors['default'])
        
        content_div = None
        for selector in selectors:
            content_div = soup.select_one(selector)
            if content_div:
                logging.debug(f"Content found with selector: {selector}")
                break
        
        if not content_div:
            content_div = soup.find('body')
            logging.debug("Falling back to body tag")
        
        if not content_div:
            logging.warning(f"No content found for {url}")
            return None
        
        # Extract images with better filtering
        images = []
        for img in content_div.find_all('img', limit=5):
            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src') or img.get('data-original')
            
            # Skip unwanted images
            if not src:
                continue
            
            # Filter out tracking pixels, icons, logos, ads
            skip_patterns = ['logo', 'icon', 'avatar', 'ads', '1x1', 'pixel', 'tracking', 
                           'spinner', 'loading', 'placeholder', 'transparent']
            if any(pattern in src.lower() for pattern in skip_patterns):
                continue
            
            # Convert relative URLs to absolute
            if not src.startswith('http'):
                from urllib.parse import urljoin
                src = urljoin(url, src)
            
            # Basic size check (avoid tiny images)
            width = img.get('width') or '0'
            height = img.get('height') or '0'
            try:
                if width.isdigit() and height.isdigit():
                    if int(width) < 100 or int(height) < 100:
                        continue
            except:
                pass
            
            images.append(src)
        
        # Extract paragraphs with proper formatting and cleanup
        paragraphs = []
        for element in content_div.find_all(['p', 'h2', 'h3', 'h4', 'blockquote', 'ul', 'ol'], recursive=True):
            text = element.get_text(strip=True)
            
            # Skip short paragraphs and unwanted content
            if len(text) < 20:
                continue
            
            unwanted_phrases = [
                'cookie', 'subscribe', 'newsletter', 'advertisement', 
                'related articles', 'read more', 'share this',
                'follow us', 'sign up', 'copyright'
            ]
            if any(phrase in text.lower() for phrase in unwanted_phrases):
                continue
            
            # Format based on element type
            if element.name in ['h2', 'h3', 'h4']:
                paragraphs.append(f'<h3>{text}</h3>')
            elif element.name == 'blockquote':
                paragraphs.append(f'<blockquote>{text}</blockquote>')
            elif element.name in ['ul', 'ol']:
                # Convert lists to paragraphs with bullets
                list_items = element.find_all('li')
                for li in list_items:
                    li_text = li.get_text(strip=True)
                    if len(li_text) > 10:
                        paragraphs.append(f'<p>• {li_text}</p>')
            else:
                paragraphs.append(f'<p>{text}</p>')
        
        # Build HTML content
        html_content = '\n'.join(paragraphs)
        
        # Extract plain text for summary
        plain_text = clean_text_extractor(content_div, limit=5000)
        
        return {
            'html': html_content,
            'text': plain_text,
            'images': images
        }
        
    except requests.exceptions.Timeout:
        logging.warning(f"Timeout extracting content from {url}")
        return None
    except requests.exceptions.RequestException as e:
        logging.warning(f"Request failed for {url}: {e}")
        return None
    except Exception as e:
        logging.error(f"Content extraction failed for {url}: {e}")
        return None
    finally:
        session.close()

def parse_rss_robust(soup, source_code):
    """
    Enhanced RSS/Atom parser optimized for anime feeds
    """
    items = []
    
    # Find all entries (works for both RSS and Atom)
    entries = soup.find_all(['item', 'entry'])
    
    if not entries:
        logging.warning(f"No entries found in feed for {source_code}")
        return items
    
    today = now_local().date()
    yesterday = today - timedelta(days=1)
    
    logging.debug(f"Processing {len(entries)} entries for {source_code}")

    for entry in entries:
        try:
            # ============ DATE EXTRACTION ============
            pub_date = None
            pub_datetime = None
            
            # Try multiple date fields with enhanced handling
            date_tag = (
                entry.find('pubDate') or 
                entry.find('published') or 
                entry.find('dc:date') or 
                entry.find('updated') or
                entry.find('lastBuildDate') or
                entry.find('date') or
                entry.find('created') or
                entry.find('issued')
            )
            
            if date_tag:
                date_string = date_tag.text.strip()
                pub_datetime = parse_date_flexible(date_string)
                
                if pub_datetime:
                    pub_date = pub_datetime.date()
                    
                    # Relaxed date filtering for problematic anime sources
                    if not DEBUG_MODE:
                        if source_code in ['ANI', 'HONEY', 'ANIMEUK', 'OTAKU']:
                            # For problematic anime sources, accept last 3 days
                            three_days_ago = today - timedelta(days=3)
                            if pub_date < three_days_ago:
                                logging.debug(f"Skipping old article from {pub_date}: {entry.find('title').text[:50] if entry.find('title') else 'No title'}")
                                continue
                        else:
                            # For good anime sources, stick to today/yesterday
                            if pub_date not in [today, yesterday]:
                                logging.debug(f"Skipping old article from {pub_date}: {entry.find('title').text[:50] if entry.find('title') else 'No title'}")
                                continue
            else:
                logging.debug(f"No date found for entry in {source_code}")
                # For problematic anime sources, be more lenient
                if source_code in ['ANI', 'HONEY', 'ANIMEUK', 'OTAKU']:
                    if not DEBUG_MODE:
                        # Skip only if in debug mode, otherwise proceed
                        pass
                    else:
                        continue
                else:
                    # In production, skip entries without dates for good sources
                    if not DEBUG_MODE:
                        continue
            
            # ============ TITLE EXTRACTION ============
            title_tag = entry.find('title') or entry.find('dc:title')
            if not title_tag or not title_tag.text.strip():
                logging.debug("Skipping entry without title")
                continue
            
            title = title_tag.text.strip()
            
            # Skip very short titles (likely garbage)
            if len(title) < 10:
                logging.debug(f"Skipping short title: {title}")
                continue
            
            # ============ LINK EXTRACTION ============
            link_str = None
            
            # Method 1: <link> tag
            link_tag = entry.find('link')
            if link_tag:
                # Atom feeds use href attribute
                if link_tag.get('href'):
                    link_str = link_tag.get('href')
                # RSS feeds use text content
                elif link_tag.text and link_tag.text.strip():
                    link_str = link_tag.text.strip()
            
            # Method 2: <guid> tag (if it's a URL)
            if not link_str:
                guid_tag = entry.find('guid')
                if guid_tag:
                    guid_text = guid_tag.text.strip()
                    if guid_text.startswith('http'):
                        link_str = guid_text
            
            # Method 3: <id> tag (Atom feeds)
            if not link_str:
                id_tag = entry.find('id')
                if id_tag:
                    id_text = id_tag.text.strip()
                    if id_text.startswith('http'):
                        link_str = id_text
            
            # Method 4: Extract from description/content
            if not link_str:
                desc_tag = entry.find('description') or entry.find('summary') or entry.find('content')
                if desc_tag:
                    import re
                    urls = re.findall(r'href=["\']([^"\']+)["\']', str(desc_tag))
                    if urls:
                        link_str = urls[0]
            
            # Method 5: Look for any URL in the entire entry
            if not link_str:
                import re
                entry_text = str(entry)
                urls = re.findall(r'https?://[^\s<>"\']+', entry_text)
                if urls:
                    # Prefer URLs that look like article links
                    for url in urls:
                        if any(keyword in url.lower() for keyword in ['article', 'story', 'news', 'post', 'anime', 'manga']):
                            link_str = url
                            break
                    if not link_str:
                        link_str = urls[0]  # Fallback to first URL
            
            # Validate link
            if not link_str or not link_str.startswith('http'):
                logging.debug(f"Skipping entry without valid link: {title[:50]}")
                continue
            
            # ============ IMAGE EXTRACTION ============
            image_url = None
            
            # Method 1: media:content
            media = entry.find('media:content')
            if media and media.get('url'):
                media_type = media.get('type', '')
                if 'image' in media_type or not media_type:
                    image_url = media.get('url')
            
            # Method 2: enclosure
            if not image_url:
                enclosure = entry.find('enclosure')
                if enclosure and enclosure.get('url'):
                    enc_type = enclosure.get('type', '')
                    if 'image' in enc_type or not enc_type:
                        image_url = enclosure.get('url')
            
            # Method 3: media:thumbnail
            if not image_url:
                thumb = entry.find('media:thumbnail')
                if thumb and thumb.get('url'):
                    image_url = thumb.get('url')
            
            # Method 4: Extract from description/content
            if not image_url:
                content_tag = (
                    entry.find('content:encoded') or 
                    entry.find('description') or 
                    entry.find('summary')
                )
                if content_tag:
                    content_soup = BeautifulSoup(str(content_tag), 'html.parser')
                    img_tag = content_soup.find('img')
                    if img_tag:
                        image_url = img_tag.get('src') or img_tag.get('data-src')
            
            # ============ SUMMARY EXTRACTION ============
            summary_text = ""
            
            # Try multiple content fields
            description = (
                entry.find('content:encoded') or
                entry.find('description') or 
                entry.find('summary') or 
                entry.find('content')
            )
            
            if description:
                summary_text = clean_text_extractor(description, limit=400)
            
            # Fallback summary
            if not summary_text or len(summary_text) < 20:
                summary_text = f"Read the full anime story about: {title}"
            
            # ============ CATEGORY EXTRACTION ============
            category = None
            cat_tag = entry.find('category') or entry.find('dc:subject')
            if cat_tag:
                category = cat_tag.get('term') or cat_tag.text.strip()
            
            # ============ AUTHOR EXTRACTION ============
            author = None
            author_tag = (
                entry.find('author') or 
                entry.find('dc:creator') or 
                entry.find('creator')
            )
            if author_tag:
                # Handle <author><name>Text</name></author> structure
                name_tag = author_tag.find('name')
                if name_tag:
                    author = name_tag.text.strip()
                else:
                    author = author_tag.text.strip()
            
            # ============ CREATE NEWS ITEM ============
            item = NewsItem(
                title=title,
                source=source_code,
                article_url=link_str,
                image_url=image_url,
                summary_text=summary_text,
                category=category,
                author=author,
                publish_date=pub_datetime
            )
            
            items.append(item)
            
        except Exception as e:
            logging.warning(f"Failed to parse RSS entry: {e}")
            continue
    
    logging.info(f"Successfully parsed {len(items)} anime items from {source_code}")
    return items

def fetch_rss(url, source_name, parser_func):
    """
    Enhanced RSS feed fetcher with better error handling and fallbacks
    Optimized for anime news sources
    """
    session = get_scraping_session()
    try:
        logging.debug(f"Fetching {source_name} from {url}")
        
        # Try with different approaches for problematic feeds
        response = None
        content = None
        
        # First attempt: Standard request
        try:
            # Increased timeout for reliability
            response = session.get(url, timeout=30)
            response.raise_for_status()
            content = response.content
        except Exception as e:
            logging.warning(f"Standard request failed for {source_name}: {e}")
            
            # Second attempt: With different headers for problematic anime sites
            if source_name in ['ANI', 'HONEY', 'ANIMEUK', 'OTAKU']:
                try:
                    # Use a real browser User-Agent to avoid blocking
                    session.headers.update({
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
                        'Cache-Control': 'no-cache',
                        'Upgrade-Insecure-Requests': '1'
                    })
                    # Drastically increased timeout for slow anime servers
                    response = session.get(url, timeout=60)
                    response.raise_for_status()
                    content = response.content
                    logging.info(f"Fallback request succeeded for {source_name}")
                except Exception as e2:
                    logging.error(f"Fallback request also failed for {source_name}: {e2}")
                    
                    # Third attempt: Try alternative URLs for problematic anime sources
                    alternative_urls = {
                        'ANI': [
                            'https://animenewsindia.com/feed/atom/',
                            'https://animenewsindia.com/category/news/feed/'
                        ],
                        'HONEY': [
                            'https://honeysanime.com/feed/',
                            'https://honeysanime.com/feed/rss/'
                        ],
                        'ANIMEUK': [
                            'https://www.animeuknews.net/feed/',
                            'https://animeuknews.net/feed/rss/'
                        ],
                        'OTAKU': [
                            'https://otakuusa.com/feed/',
                            'https://otakuusa.com/feed/rss/'
                        ]
                    }
                    
                    if source_name in alternative_urls:
                        for alt_url in alternative_urls[source_name]:
                            try:
                                logging.info(f"Trying alternative URL for {source_name}: {alt_url}")
                                response = session.get(alt_url, timeout=30)
                                response.raise_for_status()
                                content = response.content
                                logging.info(f"Alternative URL worked for {source_name}: {alt_url}")
                                break
                            except Exception as e3:
                                logging.debug(f"Alternative URL failed: {alt_url} - {e3}")
                                continue
                    
                    if not content:
                        raise e2
            else:
                raise e
        
        if not content:
            raise Exception("No content received")
        
        # Enhanced XML parsing with multiple fallbacks
        soup = None
        parsing_attempts = [
            ("xml", "xml"),
            ("lxml", "lxml"),
            ("html.parser", "html"),
            ("html5lib", "html5")
        ]
        
        for parser_name, parser_type in parsing_attempts:
            try:
                if parser_type == "xml":
                    soup = BeautifulSoup(content, "xml")
                    # Verify it's actually XML by looking for RSS/Atom elements
                    if not soup.find(['rss', 'feed', 'item', 'entry']):
                        raise Exception("Not valid RSS/Atom XML")
                else:
                    soup = BeautifulSoup(content, parser_name)
                    # Check if we found any meaningful content
                    if not soup.find(['item', 'entry', 'title', 'link']):
                        raise Exception(f"No RSS elements found with {parser_name}")
                
                logging.debug(f"Successfully parsed {source_name} with {parser_name}")
                break
                
            except Exception as parse_error:
                logging.debug(f"Parser {parser_name} failed for {source_name}: {parse_error}")
                soup = None
                continue
        
        if not soup:
            raise Exception("All parsing attempts failed")
        
        # Try calling with source_name first (for robust parser), fall back if it fails
        try:
            items = parser_func(soup, source_name)
        except TypeError:
            items = parser_func(soup)
        
        # Record success with circuit breaker
        circuit_breaker.record_success(source_name)
        
        logging.info(f"[OK] {source_name}: Fetched {len(items)} anime items")
        return items
        
    except requests.exceptions.Timeout:
        logging.error(f"[TIMEOUT] {source_name}: Request timed out")
        circuit_breaker.record_failure(source_name)
        return []
    except requests.exceptions.RequestException as e:
        logging.error(f"[ERROR] {source_name}: Request failed - {e}")
        circuit_breaker.record_failure(source_name)
        return []
    except Exception as e:
        logging.error(f"[ERROR] {source_name}: Parsing failed - {e}")
        circuit_breaker.record_failure(source_name)
        return []
    finally:
        session.close()

# ================================================================
# 🌸 ANIME-ONLY SCRAPER - FINAL VERSION
# ================================================================
# This is the complete, optimized scraper for anime news only
# All world news references have been removed
# Optimized for anime sites and content
# Ready for production use
# ================================================================
