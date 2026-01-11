from bs4 import BeautifulSoup
import re

def clean_text_extractor(element):
    """
    Cleans an HTML element by removing hidden elements and specific trash classes,
    then returns the stripped text.
    """
    if not element: return ""
    
    # 1. Remove display:none style elements
    for hidden in element.find_all(style=re.compile(r"display:\s*none", re.IGNORECASE)): 
        hidden.decompose()
        
    # 2. Remove specific bad classes (fr-mk is a known tracking/hidden spam span)
    for bad_class in element.find_all(class_="fr-mk"):
        bad_class.decompose()
        
    # 3. Remove script and style tags just in case
    for script in element(["script", "style"]):
        script.decompose()
        
    return element.get_text(" ", strip=True)
