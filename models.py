from pydantic import BaseModel, HttpUrl, field_validator
from typing import Optional

class NewsItem(BaseModel):
    title: str
    source: str
    article_url: Optional[str] = None 
    image: Optional[str] = None
    summary: str = "No summary available."
    
    @field_validator('title')
    @classmethod
    def clean_title(cls, v):
        prefixes = ["DC Wiki Update:", "TMS News:", "Fandom Wiki Update:", "ANN DC News:"]
        for p in prefixes:
            if v.startswith(p):
                return v.replace(p, "").strip()
        return v.strip()
