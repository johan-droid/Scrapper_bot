import requests
import json
import logging
from bs4 import BeautifulSoup

class TelegraphClient:
    """Client for creating Telegraph articles"""
    
    def __init__(self, access_token=None):
        self.base_url = "https://api.telegra.ph"
        self.access_token = access_token
        self.session = requests.Session()
        
        # Create account if no token provided
        if not self.access_token:
            self.create_account()
    
    def create_account(self):
        """Create a Telegraph account"""
        try:
            response = self.session.post(
                f"{self.base_url}/createAccount",
                data={
                    "short_name": "News Bot",
                    "author_name": "Anime News Bot",
                    "author_url": "https://t.me/Detective_Conan_News"
                },
                timeout=10
            )
            data = response.json()
            if data.get('ok'):
                self.access_token = data['result']['access_token']
                logging.info("[OK] Telegraph account created")
                return True
            else:
                logging.error(f"[ERROR] Telegraph account creation failed: {data}")
                return False
        except Exception as e:
            logging.error(f"[ERROR] Telegraph account error: {e}")
            return False
    
    def create_page(self, title, content, author_name=None, author_url=None, return_content=False):
        """
        Create a Telegraph page
        
        Args:
            title: Page title
            content: List of Node objects or HTML string
            author_name: Author name
            author_url: Author URL
            return_content: Whether to return content in response
        
        Returns:
            dict with 'ok' status and 'result' containing page data
        """
        if not self.access_token:
            logging.error("[ERROR] No Telegraph access token")
            return None
        
        try:
            # Convert HTML to Telegraph nodes if string provided
            if isinstance(content, str):
                content = self._html_to_nodes(content)
            
            data = {
                "access_token": self.access_token,
                "title": title[:256],  # Telegraph title limit
                "content": json.dumps(content),
                "return_content": return_content
            }
            
            if author_name:
                data["author_name"] = author_name[:128]
            if author_url:
                data["author_url"] = author_url
            
            response = self.session.post(
                f"{self.base_url}/createPage",
                data=data,
                timeout=15
            )
            
            result = response.json()
            if result.get('ok'):
                logging.info(f"[OK] Telegraph page created: {result['result']['url']}")
                return result['result']
            else:
                logging.error(f"[ERROR] Telegraph page creation failed: {result}")
                return None
                
        except Exception as e:
            logging.error(f"[ERROR] Telegraph page creation error: {e}")
            return None
    
    def _html_to_nodes(self, html_content):
        """Convert HTML to Telegraph DOM nodes"""
        soup = BeautifulSoup(html_content, 'html.parser')
        nodes = []
        
        for element in soup.children:
            node = self._element_to_node(element)
            if node:
                nodes.append(node)
        
        return nodes
    
    def _element_to_node(self, element):
        """Convert BeautifulSoup element to Telegraph node"""
        if isinstance(element, str):
            text = element.strip()
            return text if text else None
        
        if element.name is None:
            return None
        
        # Handle different HTML tags
        tag_map = {
            'p': 'p',
            'b': 'strong', 'strong': 'strong',
            'i': 'em', 'em': 'em',
            'a': 'a',
            'h1': 'h3', 'h2': 'h3', 'h3': 'h3', 'h4': 'h4',
            'blockquote': 'blockquote',
            'pre': 'pre',
            'code': 'code',
            'br': 'br',
            'img': 'img'
        }
        
        tag = tag_map.get(element.name)
        if not tag:
            # For unsupported tags, extract text
            return element.get_text(strip=True) or None
        
        # Build node structure
        node = {'tag': tag}
        
        # Handle attributes
        if tag == 'a' and element.get('href'):
            node['attrs'] = {'href': element['href']}
        elif tag == 'img' and element.get('src'):
            node['attrs'] = {'src': element['src']}
        
        # Handle children
        if tag not in ['br', 'img']:
            children = []
            for child in element.children:
                child_node = self._element_to_node(child)
                if child_node:
                    children.append(child_node)
            
            if children:
                node['children'] = children
        
        return node
