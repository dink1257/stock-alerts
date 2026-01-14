import requests
import os
import csv
import pytz
import json
import urllib.parse
from datetime import datetime, timezone
from yahooquery import Ticker

# --- 环境变量配置 ---
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
STATE_CACHE_PATH = "data/alert_state.json"
BARK_URL = os.getenv("BARK_URL")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

# --- 基础辅助函数 ---
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
        headers = {'User-Agent': 'Mozilla/5.0'}
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}"
        r = requests.get(url, headers=headers, timeout=10)
        news = r.json().get("news", [])
        if not news: return f"{symbol} 暂无即时新闻"
        return " | ".join([n['title'] for n in news[:5]])
    except: return "新闻抓取异常"

# --- 核心 AI 分析引擎 ---
def ai_analyze(symbol, pct, news, mode="MONITOR"):
    if not DASHSCOPE_API_KEY: return "AI Key 缺失"
    
    if mode == "MONITOR":
        trend = "上涨" if pct > 0 else "下跌"
        is_deep = abs(pct) >= 6.0
        prompt = (
            f"股票 {symbol} 实测{trend} {abs(pct):.2f}%。\n相关新闻：{news}\n"
            f"任务：1.分析{trend}的核心逻辑；2.若无直接关联则提示原因不明；"
            f"3. {'深度分析' if is_deep else '简明扼要'}；4.中文{'120' if is_deep else '80'}字内。"
        )
        model = "qwen-plus" if is_deep else "qwen-turbo"
    else: # SUMMARY 汇总模式
        prompt = (
            f"处理以下24h自选股动态：\n{news}\n"
            f"任务：1.翻译并去重；2.仅保留对股价有影响的诱因；"
            f"3.按公司分组用[利好/利空]输出逻辑；4.中文精炼。"
        )
        model = "qwen-plus"

    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": model, "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        return r.json()['output']['text']
    except: return "AI 分析暂时不可用"

# --- 自动化调度逻辑 ---
def main():
    now_utc = datetime.now(timezone.utc)
    cn_now = now_utc.astimezone(pytz.timezone("Asia/Shanghai"))
    us_now = now_utc.astimezone(pytz.timezone("US/Eastern"))
    
    action = "IDLE"

    # A股调度 (周一至周五)
    if cn_now.weekday() < 5:
        hm = cn_now.hour * 100 + cn_now.minute
        if 830 <= hm <= 845: action = "SUMMARY"
        elif (925 <= hm <= 1135) or (1255 <= hm <= 1510): action = "MONITOR"
    
    # 美股调度 (周一至周五)
    if us_now.weekday() < 5:
        hm = us_now.hour * 100 + us_now.minute
        if 830 <= hm <= 845: action = "SUMMARY"
        elif 925 <= hm <= 1610: action = "MONITOR"

    # 如果不在活跃时段，直接退出
    if action == "IDLE": 
        print(f"当前时间 {cn_now.strftime('%H:%M')}，处于非监控时段，系统静默。")
        return

    # 加载自选股清单
    if not os.path.exists(WATCHLIST_PATH):
        print("未找到 watchlist.csv")
        return
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        stocks = [r['symbol'].strip() for r in csv.DictReader(f) if r.get('symbol')]

    state = load_state()
    today = datetime.now(timezone.utc).strftime('%Y%m%d')
    if state.get("date") != today: state = {"date": today, "alerts": {}}

    if action == "SUMMARY":
        print("执行盘前新闻汇总...")
        combined_news = []
        for s in stocks: combined_news.append(fetch_top_news(s))
        report = ai_analyze("", 0, "\n".join(combined_news), mode="SUMMARY")
        if report: bark_push("☕ 盘前自选股动态汇总", report)

    elif action == "MONITOR":
        print("执行股价异动扫描...")
        for s in stocks:
            try:
                t = Ticker(s)
                p = t.price[s]
                price = p.get("regularMarketPrice")
                prev = p.get("regularMarketPreviousClose")
                if not price or not prev: continue
                
                pct = ((price - prev) / prev * 100)
                abs_pct = abs(pct)
                
                # 定义 3% 和 6% 两个告警阈值
                level = 2 if abs_pct >= 6.0 else (1 if abs_pct >= 3.0 else 0)
                
                # 只有当当前波动等级高于今日已推送等级时才报警
                if level > state["alerts"].get(s, 0):
                    news = fetch_top_news(s)
                    analysis = ai_analyze(s, pct, news, mode="MONITOR")
                    title = f"{'🔥' if level==2 else '🔔'} {s} {'涨' if pct>0 else '跌'}{abs_pct:.2f}%"
                    bark_push(title, f"现价: {price}\nAI 分析: {analysis}")
                    state["alerts"][s] = level
            except: continue
        save_state(state)

if __name__ == "__main__":
    main()
