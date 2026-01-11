from bs4 import BeautifulSoup
import re

html_content = """
<div class="meat">
    The staff for the Uta no Prince-sama franchise streamed new teaser videos.
    Uta no Prince-sama<span class="fr-mk" style="display: none;">&nbsp;</span> Dolce Vita teaser.
    <span class="fr-mk" style="display:none;">&nbsp;</span> Hidden text.
    <div style="display: none">More hidden</div>
</div>
"""

def clean_and_extract(html):
    s = BeautifulSoup(html, "html.parser")
    div = s.find("div", class_="meat")
    if div:
        # Remove unwanted hidden tags that leak into text
        print("Before cleaning:", div.get_text(" ", strip=True))
        
        for hidden in div.find_all(style=re.compile(r"display:\s*none")): 
            hidden.decompose()
        for bad_class in div.find_all(class_="fr-mk"):
            bad_class.decompose()
            
        txt = div.get_text(" ", strip=True)
        print("After cleaning: ", txt)
        return txt

if __name__ == "__main__":
    clean_and_extract(html_content)
