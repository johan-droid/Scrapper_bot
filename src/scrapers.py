import logging
import requests
import random
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config import USER_AGENTS, DEBUG_MODE
from src.utils import safe_log, circuit_breaker, clean_text_extractor, now_local, local_tz
from src.models import NewsItem

def get_scraping_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=3, backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    session.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Connection": "close",
        "Accept-Charset": "utf-8",
        "Accept-Encoding": "gzip, deflate"
    })
    return session

def extract_full_article_content(url, source):
    """
    Extract full article content for Telegraph posting
    Returns dict with 'text', 'images', and 'html'
    """
    session = get_scraping_session()
    try:
        response = session.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove unwanted elements
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe', 'ads']):
            tag.decompose()
        
        # Source-specific selectors
        content_selectors = {
            'BBC': ['.article__body-content', '.story-body__inner', 'article'],
            'GUARD': ['.article-body-commercial-selector', '.content__article-body', 'article'],
            'CNN': ['.article__content', '.zn-body__paragraph', 'article'],
            'ALJ': ['.article-p-wrapper', '.wysiwyg', 'article'],
            'NPR': ['#storytext', '.storytext', 'article'],
            'REUTERS': ['.article-body__content__', '.StandardArticleBody_body', 'article'],
            'default': ['article', '.post-content', '.entry-content', '.article-content', '.story-content']
        }
        
        selectors = content_selectors.get(source, content_selectors['default'])
        
        content_div = None
        for selector in selectors:
            content_div = soup.select_one(selector)
            if content_div:
                break
        
        if not content_div:
            content_div = soup.find('body')
        
        if not content_div:
            return None
        
        # Extract images
        images = []
        for img in content_div.find_all('img', limit=5):
            src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
            if src and not any(x in src for x in ['logo', 'icon', 'avatar', 'ads', '1x1']):
                if not src.startswith('http'):
                    from urllib.parse import urljoin
                    src = urljoin(url, src)
                images.append(src)
        
        # Extract paragraphs with proper formatting
        paragraphs = []
        for p in content_div.find_all(['p', 'h2', 'h3', 'blockquote'], recursive=True):
            text = p.get_text(strip=True)
            if len(text) > 20 and not any(x in text.lower() for x in ['cookie', 'subscribe', 'newsletter', 'advertisement']):
                if p.name in ['h2', 'h3']:
                    paragraphs.append(f'<h3>{text}</h3>')
                elif p.name == 'blockquote':
                    paragraphs.append(f'<blockquote>{text}</blockquote>')
                else:
                    paragraphs.append(f'<p>{text}</p>')
        
        # Build HTML content
        html_content = '\n'.join(paragraphs)
        
        return {
            'html': html_content,
            'text': clean_text_extractor(content_div, limit=5000),
            'images': images
        }
        
    except Exception as e:
        logging.debug(f"Content extraction failed for {url}: {e}")
        return None
    finally:
        session.close()

def parse_rss_robust(soup, source_code):
    items = []
    entries = soup.find_all(['item', 'entry'])
    
    today = now_local().date()
    yesterday = today - timedelta(days=1)

    for entry in entries:
        try:
            pub_date = None
            date_tag = entry.find(['pubDate', 'published', 'dc:date', 'updated'])
            if date_tag:
                try:
                    dt_text = date_tag.text.strip()
                    # Use dateutil for robust parsing (handles GMT, ISO, etc.)
                    from dateutil import parser
                    dt = parser.parse(dt_text)
                    
                    # Handle naive datetimes (assume UTC if missing)
                    if dt.tzinfo is None:
                        import pytz
                        dt = dt.replace(tzinfo=pytz.utc)
                        
                    pub_date = dt.astimezone(local_tz).date()
                    
                    if not DEBUG_MODE and pub_date not in [today, yesterday]:
                        continue
                except Exception as e:
                    logging.debug(f"Date parse failed: {e}")
                    continue
            
            title_tag = entry.find(['title', 'dc:title'])
            if not title_tag:
                continue
            
            # Link extraction
            link_str = None
            link_tag = entry.find('link')
            if link_tag:
                if link_tag.get('href'):
                    link_str = link_tag.get('href')
                elif link_tag.text and link_tag.text.strip():
                    link_str = link_tag.text.strip()
            
            if not link_str:
                guid_tag = entry.find('guid')
                if guid_tag:
                    guid_text = guid_tag.text.strip()
                    if guid_text.startswith('http'):
                        link_str = guid_text
            
            if not link_str:
                id_tag = entry.find('id')
                if id_tag:
                    id_text = id_tag.text.strip()
                    if id_text.startswith('http'):
                        link_str = id_text
            
            if not link_str or not link_str.startswith('http'):
                continue

            # Image extraction
            image_url = None
            media = entry.find('media:content')
            if media and media.get('url'):
                image_url = media.get('url')
            
            if not image_url:
                enclosure = entry.find('enclosure')
                if enclosure and enclosure.get('url'):
                    enc_type = enclosure.get('type', '')
                    if 'image' in enc_type or not enc_type:
                        image_url = enclosure.get('url')
            
            if not image_url:
                thumb = entry.find('media:thumbnail')
                if thumb and thumb.get('url'):
                    image_url = thumb.get('url')
            
            # Summary
            summary_text = ""
            description = entry.find(['description', 'summary', 'content', 'content:encoded'])
            if description:
                summary_text = clean_text_extractor(description)
            
            if not summary_text or len(summary_text) < 20:
                summary_text = f"Read more about: {title_tag.text.strip()}"

            # Category
            cat_tag = entry.find(['category', 'dc:subject'])
            category = None
            if cat_tag:
                category = cat_tag.get('term') or cat_tag.text

            item = NewsItem(
                title=title_tag.text.strip(),
                source=source_code,
                article_url=link_str,
                image_url=image_url,
                summary_text=summary_text,
                category=category,
                publish_date=datetime.combine(pub_date, datetime.min.time()).replace(tzinfo=local_tz) if pub_date else None
            )
            items.append(item)
        except Exception as e:
            logging.debug(f"Failed to parse RSS entry: {e}")
            continue
    
    return items

def fetch_rss(url, source_name, parser_func):
    session = get_scraping_session()
    try:
        r = session.get(url, timeout=25)
        r.raise_for_status()
        
        try:
            soup = BeautifulSoup(r.content, "xml")
        except Exception:
            soup = BeautifulSoup(r.content, "html.parser")
            
        items = parser_func(soup)
        circuit_breaker.record_success(source_name)
        return items
    except Exception as e:
        logging.error(f"{source_name} RSS fetch failed: {e}")
        circuit_breaker.record_failure(source_name)
        return []
    finally:
        session.close()
