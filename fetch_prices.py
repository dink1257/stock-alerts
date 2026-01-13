import requests
import os
import csv
import pytz
import urllib.parse
from datetime import datetime, timezone
from yahooquery import Ticker

# --- 配置 ---
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
BARK_URL = os.getenv("BARK_URL")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

def bark_push(title, body):
    if not BARK_URL: return
    safe_title = urllib.parse.quote(title, safe='')
    safe_body = urllib.parse.quote(body, safe='')
    requests.get(f"{BARK_URL.rstrip('/')}/{safe_title}/{safe_body}", timeout=10)

def ai_quick_analyze(symbol, pct, news):
    """交易时段的瞬时 AI 分析"""
    if not DASHSCOPE_API_KEY: return "AI Key 缺失"
    prompt = f"股票 {symbol} 异动 {pct:.2f}%。相关新闻: {news}。请用 60 字内中文分析原因。"
    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        data = {"model": "qwen-turbo", "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=data, timeout=15)
        return r.json()['output']['text']
    except: return "AI 分析暂时不可用"

def fetch_top_news(symbol):
    """获取该股票即时新闻标题"""
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}"
        r = requests.get(url, timeout=10)
        news = r.json().get("news", [])
        return " | ".join([n['title'] for n in news[:3]]) if news else "暂无即时新闻"
    except: return "新闻抓取失败"

def is_market_open(symbol):
    """简化的交易时段判断"""
    now_utc = datetime.now(timezone.utc)
    if "-" in symbol: return True  # Crypto
    sh_now = now_utc.astimezone(pytz.timezone("Asia/Shanghai"))
    if symbol.endswith((".SS", ".SZ")):
        hhmm = sh_now.hour * 100 + sh_now.minute
        return (930 <= hhmm <= 1130) or (1300 <= hhmm <= 1500)
    # 美股简易判断 (21:30 - 04:00)
    est_now = now_utc.astimezone(pytz.timezone("US/Eastern"))
    hhmm = est_now.hour * 100 + est_now.minute
    return 930 <= hhmm <= 1600

def check_prices():
    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for row in rows:
        symbol = row.get("symbol")
        if not is_market_open(symbol): continue

        try:
            t = Ticker(symbol)
            p = t.price[symbol]
            price = p.get("regularMarketPrice")
            prev = p.get("regularMarketPreviousClose")
            pct = ((price - prev) / prev * 100) if prev else 0
            
            # 触发条件：涨跌幅超过阈值
            if abs(pct) >= float(row.get("alert_up", 2.0)):
                news = fetch_top_news(symbol)
                analysis = ai_quick_analyze(symbol, pct, news)
                bark_push(f"🚨 {symbol} 异动 {pct:.2f}%", f"价格: {price}\n分析: {analysis}")
        except: continue

if __name__ == "__main__":
    check_prices()
