import requests
import time

NEWS_API = "https://newsapi.org/v2/everything"
NEWS_API_KEY = "demo"  # 如果需要，我可换成其他免费源

def fetch_news(keyword: str, limit=5):
    """
    获取与股票相关的新闻标题（仅用于演示，可换更强新闻源）
    """
    params = {
        "q": keyword,
        "pageSize": limit,
        "sortBy": "publishedAt",
        "language": "zh",
        "apiKey": NEWS_API_KEY
    }

    try:
        r = requests.get(NEWS_API, params=params, timeout=10)
        data = r.json()
        if "articles" not in data:
            return []

        return [
            {
                "title": x.get("title", ""),
                "url": x.get("url", ""),
                "time": x.get("publishedAt", "")
            }
            for x in data["articles"]
        ]

    except Exception:
        return []
