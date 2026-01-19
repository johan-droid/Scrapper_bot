def clean_text_extractor(element):
    if not element:
        return ""
    text = element.get_text(" ", strip=True)
    # Remove extra whitespace and clean up
    return " ".join(text.split())