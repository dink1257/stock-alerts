import requests
import os
import csv
import hashlib

WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
BARK_URL = os.getenv("BARK_URL")

def get_all_news():
    symbols = []
    with open(WATCHLIST_PATH, "r") as f:
        symbols = [row['symbol'] for row in csv.DictReader(f)]
    
    combined_news = []
    for s in symbols:
        try:
            r = requests.get(f"https://query1.finance.yahoo.com/v1/finance/search?q={s}", timeout=10)
            news = r.json().get("news", [])
            for n in news:
                combined_news.append(f"[{s}] {n['title']}")
        except: continue
    
    # 基础去重（通过标题哈希）
    unique_news = list(set(combined_news))
    return "\n".join(unique_news)

def ai_summarize_daily(news_content):
    if not DASHSCOPE_API_KEY or not news_content: return None
    prompt = f"以下是盘前搜集的新闻动态：\n{news_content}\n请剔除杂讯，仅保留可能影响股价的重要信息，按公司合并去重，以精炼列表输出。"
    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        data = {"model": "qwen-plus", "input": {"prompt": prompt}} # 盘前用更好的模型
        r = requests.post(url, headers=headers, json=data, timeout=30)
        return r.json()['output']['text']
    except: return None

def main():
    print("开始盘前汇总...")
    all_news = get_all_news()
    summary = ai_summarize_daily(all_news)
    if summary:
        safe_title = urllib.parse.quote("☕ 盘前自选股动态", safe='')
        safe_body = urllib.parse.quote(summary, safe='')
        requests.get(f"{BARK_URL.rstrip('/')}/{safe_title}/{safe_body}")

if __name__ == "__main__":
    main()
