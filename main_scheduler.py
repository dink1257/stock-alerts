"""
Project: Global Macro & Asset Monitor (CIO Edition)
Version: 5.2.3 (CIO Logic & Deep Analysis Edition)
Description: 整合买方总监决策逻辑与第一性原理，提供高维度异动研判。
"""
import requests
import os
import csv
import pytz
import json
import time
from datetime import datetime, timezone
from yahooquery import Ticker

# --- 配置区 ---
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
STATE_CACHE_PATH = "data/alert_state.json"
BARK_URL = os.getenv("BARK_URL")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
COOL_DOWN_SECONDS = 3600  
CHUNK_SIZE = 4           # 由于分析深度增加，每条推送包含4个标的，避免排版过挤

def bark_push(title, body):
    if not BARK_URL: return
    try:
        url = f"{BARK_URL.rstrip('/')}/"
        payload = {"title": title, "body": body, "group": "InvestmentMonitor", "sound": "calypso"}
        requests.post(url, json=payload, timeout=10)
    except: pass

def load_state():
    default_state = {"date": "", "alerts": {}, "last_push_time": {}}
    if os.path.exists(STATE_CACHE_PATH):
        try:
            with open(STATE_CACHE_PATH, "r") as f:
                data = json.load(f)
                for key in default_state:
                    if key not in data: data[key] = default_state[key]
                return data
        except: pass
    return default_state

def save_state(state):
    os.makedirs(os.path.dirname(STATE_CACHE_PATH), exist_ok=True)
    with open(STATE_CACHE_PATH, "w") as f: json.dump(state, f)

def fetch_top_news(symbol):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}"
        r = requests.get(url, headers=headers, timeout=5)
        news = r.json().get("news", [])
        return " | ".join([n['title'] for n in news[:3]]) if news else "暂无显著产业新闻"
    except: return "资讯抓取略过"

def ai_analyze(symbol_info, pct, news, mode="MONITOR", asset_type="STOCK"):
    if not DASHSCOPE_API_KEY: return "AI Key 缺失"
    model = "qwen-plus" # 推荐使用 plus，其逻辑严密性更适合 CIO 视角
    
    if mode == "MONITOR":
        # --- 整合：买方投资总监 + 第一性原理 Prompt ---
        prompt = f"""
你现在是一位管理百亿头寸的买方投资总监（CIO）。请对以下异动进行底层逻辑研判。
要求：拒绝任何技术指标、K线描述、短期情绪词汇。穿透波动，直击本质。

【输入信息】
标的：{symbol_info}
当日变动：{pct:.2f}%
最新资讯：{news}

【研判要求】
1. 第一性原理归因：指出变动触动了产业逻辑、竞争壁垒还是长期现金流预期的哪一环。
2. 确定性评估：判断异动是确定性逻辑的强化，还是博弈性噪音。
3. CIO定调：给出“核心仓位不动”、“逻辑边际减损”或“关注定价偏差”的决策建议。

请按此格式输出（100字内）：
【底层逻辑】
【定价评估】
【CIO定调】
"""
    else:
        prompt = f"请以首席投资官视角，对以下全市场资讯进行‘脱水研判’。过滤噪音，只看产业趋势的边际变化及跨资产定价的底层逻辑：{news}"

    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": model, "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        return r.json()['output']['text']
    except: return "AI 逻辑推演波动，请关注原始价格变动。"

def main():
    now_utc = datetime.now(timezone.utc)
    cn_tz = pytz.timezone("Asia/Shanghai")
    cn_now = now_utc.astimezone(cn_tz)
    time_str = cn_now.strftime('%H:%M:%S')
    
    hm_cn = cn_now.hour * 100 + cn_now.minute
    action = "MONITOR" 
    if 825 <= hm_cn <= 905: action = "SUMMARY"
    
    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        watchlist = list(csv.DictReader(f))
    symbols = [i['symbol'] for i in watchlist]

    # --- 批量抓取数据 ---
    all_prices = {}
    try:
        te = Ticker(symbols, asynchronous=True, formatted=False)
        all_prices = te.price
    except:
        for s in symbols:
            try: all_prices[s] = Ticker(s).price[s]
            except: continue

    state = load_state()
    today_str = cn_now.strftime('%Y%m%d')
    if state.get("date") != today_str:
        state = {"date": today_str, "alerts": {}, "last_push_time": {}}

    if action == "SUMMARY":
        news_list = [f"[{i['name']}]\n{fetch_top_news(i['symbol'])}" for i in watchlist]
        bark_push(f"🌍 CIO 内参 [{time_str}]", ai_analyze("", 0, "\n".join(news_list), mode="SUMMARY"))
    
    elif action == "MONITOR":
        pending_alerts = []
        current_ts = time.time()
        
        for item in watchlist:
            s, name = item['symbol'], item['name']
            p_raw = all_prices.get(s)
            if not isinstance(p_raw, dict): continue
            
            price = p_raw.get("regularMarketPrice")
            prev = p_raw.get("regularMarketPreviousClose")
            if price is None or prev is None: continue
            
            pct = ((price - prev) / prev * 100)
            asset_type, l1, l2 = "STOCK", 3.0, 6.0
            if "=F" in s: asset_type, l1, l2 = "FUTURES", 1.5, 3.0
            elif s in ["DX-Y.NYB", "^TNX", "CNY=X"]: asset_type, l1, l2 = "MACRO", 0.5, 1.0

            level = 2 if abs(pct) >= l2 else (1 if abs(pct) >= l1 else 0)
            if level > 0:
                last_lvl = state.get("alerts", {}).get(s, 0)
                last_ts = state.get("last_push_time", {}).get(s, 0)
                
                if level > last_lvl or (level == last_lvl and (current_ts - last_ts) > COOL_DOWN_SECONDS):
                    print(f"[{time_str}] 深度分析: {name}")
                    news = fetch_top_news(s)
                    analysis = ai_analyze(f"{name}({s})", pct, news, "MONITOR", asset_type)
                    emoji = "🌐" if asset_type == "MACRO" else ("🌋" if asset_type == "FUTURES" else "🔔")
                    
                    pending_alerts.append(f"{emoji} {name} {pct:.2f}%\n🕒 报时: {time_str}\n{analysis}")
                    
                    state["alerts"][s] = level
                    state["last_push_time"][s] = current_ts

        if pending_alerts:
            total_batches = (len(pending_alerts) + CHUNK_SIZE - 1) // CHUNK_SIZE
            for i in range(0, len(pending_alerts), CHUNK_SIZE):
                chunk = pending_alerts[i:i + CHUNK_SIZE]
                title = f"📊 CIO 深度研判 [{time_str}] ({i//CHUNK_SIZE + 1}/{total_batches})"
                bark_push(title, "\n\n".join(chunk))

    save_state(state)

if __name__ == "__main__":
    main()
