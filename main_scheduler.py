import requests
import os
import csv
import pytz
import json
import urllib.parse
from datetime import datetime, timezone
from yahooquery import Ticker

# --- 环境变量读取 ---
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
STATE_CACHE_PATH = "data/alert_state.json"
BARK_URL = os.getenv("BARK_URL")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

# --- 逻辑辅助函数 ---
def bark_push(title, body):
    if not BARK_URL: return
    try:
        url = f"{BARK_URL.rstrip('/')}/{urllib.parse.quote(title)}/{urllib.parse.quote(body)}"
        requests.get(url, timeout=10)
    except: pass

def load_state():
    if os.path.exists(STATE_CACHE_PATH):
        try:
            with open(STATE_CACHE_PATH, "r") as f: return json.load(f)
        except: return {}
    return {}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_CACHE_PATH), exist_ok=True)
    with open(STATE_CACHE_PATH, "w") as f: json.dump(state, f)

def fetch_top_news(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}"
        r = requests.get(url, timeout=10)
        news = r.json().get("news", [])
        return " | ".join([n['title'] for n in news[:5]]) if news else "暂无即时新闻"
    except: return "新闻抓取失败"

# --- 核心 AI 引擎 ---
def ai_analyze(symbol, pct, news, mode="MONITOR"):
    if not DASHSCOPE_API_KEY: return "AI Key 缺失"
    
    if mode == "MONITOR":
        trend = "上涨" if pct > 0 else "下跌"
        is_deep = abs(pct) >= 6.0
        prompt = (
            f"股票 {symbol} 实测{trend} {abs(pct):.2f}%。\n新闻：{news}\n"
            f"要求：1.解释{trend}的强相关逻辑；2.若不相关则回答原因不明；"
            f"3. {'深度分析烈度' if is_deep else '简述重点'}；4.中文{'120' if is_deep else '80'}字内。"
        )
        model = "qwen-plus" if is_deep else "qwen-turbo"
    else: # SUMMARY 模式
        prompt = (
            f"处理24h新闻：\n{news}\n任务：1.翻译去重；2.仅保留股价诱因；"
            f"3.按公司分组用[利好/利空]+逻辑输出；4.中文精炼。"
        )
        model = "qwen-plus"

    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        r = requests.post(url, headers=headers, json={"model": model, "input": {"prompt": prompt}}, timeout=30)
        return r.json()['output']['text']
    except: return "AI 分析暂时不可用"

# --- 自动化调度主逻辑 ---
def main():
    now_utc = datetime.now(timezone.utc)
    cn_now = now_utc.astimezone(pytz.timezone("Asia/Shanghai"))
    us_now = now_utc.astimezone(pytz.timezone("US/Eastern"))
    
    action = "IDLE"
    # 判断 A 股 (周一至周五)
    if cn_now.weekday() < 5:
        hm = cn_now.hour * 100 + cn_now.minute
        if 830 <= hm <= 840: action = "SUMMARY"
        elif (925 <= hm <= 1135) or (1255 <= hm <= 1510): action = "MONITOR"
    
    # 判断美股 (周一至周五)
    if us_now.weekday() < 5:
        hm = us_now.hour * 100 + us_now.minute
        if 830 <= hm <= 840: action = "SUMMARY"
        elif 925 <= hm <= 1610: action = "MONITOR"

    if action == "IDLE": return

    # 读取自选股
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        stocks = [r['symbol'].strip() for r in csv.DictReader(f) if r.get('symbol')]

    state = load_state()
    today = datetime.now(timezone.utc).strftime('%Y%m%d')
    if state.get("date") != today: state = {"date": today, "alerts": {}}

    if action == "SUMMARY":
        print("执行盘前汇总...")
        all_news = []
        for s in stocks: all_news.extend(fetch_top_news(s).split(" | "))
        report = ai_analyze("", 0, "\n".join(list(set(all_news))), mode="SUMMARY")
        if report: bark_push("☕ 盘前自选股动态汇总（新版测试）", report)

    elif action == "MONITOR":
        print("扫描股价异动...")
        for s in stocks:
            try:
                t = Ticker(s)
                p = t.price[s]
                price, prev = p.get("regularMarketPrice"), p.get("regularMarketPreviousClose")
                pct = ((price - prev) / prev * 100)
                abs_pct = abs(pct)
                
                level = 2 if abs_pct >= 6.0 else (1 if abs_pct >= 3.0 else 0)
                if level > state["alerts"].get(s, 0):
                    news = fetch_top_news(s)
                    analysis = ai_analyze(s, pct, news, mode="MONITOR")
                    title = f"{'🔥' if level==2 else '🔔'} {s} {'涨' if pct>0 else '跌'}{abs_pct:.2f}%（新版测试）"
                    bark_push(title, f"价格:{price}\n逻辑:\n{analysis}")
                    state["alerts"][s] = level
            except: continue
        save_state(state)

if __name__ == "__main__":
    main()
