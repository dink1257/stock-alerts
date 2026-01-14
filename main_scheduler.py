"""
Project: Global Macro & Asset Monitor (CIO Edition)
Version: 5.2.1 (Fixed KeyError & Optimized Async)
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
CHUNK_SIZE = 6           

def bark_push(title, body):
    if not BARK_URL: return
    try:
        url = f"{BARK_URL.rstrip('/')}/"
        payload = {"title": title, "body": body, "group": "InvestmentMonitor"}
        requests.post(url, json=payload, timeout=10)
    except: pass

def load_state():
    default_state = {"date": "", "alerts": {}, "last_push_time": {}}
    if os.path.exists(STATE_CACHE_PATH):
        try:
            with open(STATE_CACHE_PATH, "r") as f:
                data = json.load(f)
                # 确保所有必要的键都存在
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
        return " | ".join([n['title'] for n in news[:3]]) if news else "暂无资讯"
    except: return "资讯抓取略过"

def ai_analyze(symbol_info, pct, news, mode="MONITOR", asset_type="STOCK"):
    if not DASHSCOPE_API_KEY: return "AI Key 缺失"
    model = "qwen-plus" # 默认使用 plus 保证速度
    prompt = f"[{asset_type}] {symbol_info} 变动{pct:.2f}%\n资讯:{news}\n简要研判逻辑与关键位(60字内)" if mode=="MONITOR" else f"研判今日资讯逻辑:{news}"
    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": model, "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        return r.json()['output']['text']
    except: return "AI 响应波动"

def main():
    now_utc = datetime.now(timezone.utc)
    cn_now = now_utc.astimezone(pytz.timezone("Asia/Shanghai"))
    hm_cn = cn_now.hour * 100 + cn_now.minute
    
    # 扩大监控时段兼容性
    action = "MONITOR" # 默认开启，除非代码逻辑判定不需要
    if 825 <= hm_cn <= 905: action = "SUMMARY"
    
    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        watchlist = list(csv.DictReader(f))
    symbols = [i['symbol'] for i in watchlist]

    # --- 异步抓取 ---
    print(f"正在异步请求 {len(symbols)} 个标的...")
    all_prices = {}
    try:
        te = Ticker(symbols, asynchronous=True, formatted=False)
        all_prices = te.price
    except Exception as e:
        print(f"异步失败: {e}，尝试同步抓取...")
        for s in symbols:
            try: all_prices[s] = Ticker(s).price[s]
            except: continue

    state = load_state()
    today_str = now_utc.strftime('%Y%m%d')
    if state.get("date") != today_str:
        state = {"date": today_str, "alerts": {}, "last_push_time": {}}

    if action == "SUMMARY":
        news_list = [f"[{i['name']}]\n{fetch_top_news(i['symbol'])}" for i in watchlist]
        bark_push("🌍 CIO 全球资产内参", ai_analyze("", 0, "\n".join(news_list), mode="SUMMARY"))
    
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
                # 安全读取 state，防止 KeyError
                last_lvl = state.get("alerts", {}).get(s, 0)
                last_ts = state.get("last_push_time", {}).get(s, 0)
                
                if level > last_lvl or (level == last_lvl and (current_ts - last_ts) > COOL_DOWN_SECONDS):
                    print(f"触发异动: {name}")
                    news = fetch_top_news(s)
                    analysis = ai_analyze(f"{name}({s})", pct, news, "MONITOR", asset_type)
                    emoji = "🌐" if asset_type == "MACRO" else ("🌋" if asset_type == "FUTURES" else "🔔")
                    pending_alerts.append(f"{emoji} {name} {pct:.2f}% (现价:{price})\n{analysis}")
                    
                    # 更新状态
                    if "alerts" not in state: state["alerts"] = {}
                    if "last_push_time" not in state: state["last_push_time"] = {}
                    state["alerts"][s] = level
                    state["last_push_time"][s] = current_ts

        if pending_alerts:
            for i in range(0, len(pending_alerts), CHUNK_SIZE):
                bark_push(f"📊 异动内参 ({i//CHUNK_SIZE + 1})", "\n\n".join(pending_alerts[i:i+CHUNK_SIZE]))
        else:
            print("行情平稳。")

    save_state(state)

if __name__ == "__main__":
    main()
