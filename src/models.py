from datetime import datetime
from typing import Optional, List, Any

class NewsItem:
    """Represents a news item with metadata from various sources."""
    def __init__(
        self,
        title: str,
        source: str,
        article_url: str,
        summary_text: Optional[str] = None,
        image_url: Optional[str] = None,
        publish_date: Optional[datetime] = None,
        tags: Optional[List[str]] = None,
        author: Optional[str] = None,
        category: Optional[str] = None,
        full_content: Optional[str] = None,
        **kwargs: Any
    ):
        self.title = title
        self.source = source
        self.article_url = article_url
        self.summary_text = summary_text
        self.image_url = image_url
        self.publish_date = publish_date
        self.tags = tags or []
        self.author = author
        self.category = category
        self.full_content = full_content
        self.telegraph_url = None
        
        for key, value in kwargs.items():
            setattr(self, key, value)
