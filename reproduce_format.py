from bs4 import BeautifulSoup
import re

# The exact snippet from the user's report (approximated context)
html_snippet = """
<div class="content">
The staff for the Uta no Prince-sama franchise streamed new teaser videos for the Nintendo Switch versions of the Uta no Prince-sama♪ Dolce Vita game and KLab 's Utano Princesama Shining Live smartphone game on Saturday. Uta no Prince-sama♪ Dolce Vita teaser <span class="fr-mk" style="display: none;">&nbsp;</span> Utano Princesama Shining Live teas..
</div>
"""

def test_cleaning():
    s = BeautifulSoup(html_snippet, "html.parser")
    div = s.find("div", class_="content")
    
    print("--- ORIGINAL GET_TEXT ---")
    print(div.get_text(" ", strip=True)) # Typical behavior: might include hidden text's content like NBSP, but usually strips tags.
    # If the user sees <span...>, maybe it's escaped?
    
    print("\n--- WITH CLEANING LOGIC ---")
    # Current Logic
    for hidden in div.find_all(style=re.compile(r"display:\s*none")): 
        hidden.decompose()
    for bad_class in div.find_all(class_="fr-mk"):
        bad_class.decompose()
        
    print(div.get_text(" ", strip=True))

if __name__ == "__main__":
    test_cleaning()
