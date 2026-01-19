class NewsItem:
    def __init__(self, title="", source="", article_url=None, image=None, summary="", category=None):
        self.title = title
        self.source = source
        self.article_url = article_url
        self.image = image
        self.summary = summary
        self.category = category