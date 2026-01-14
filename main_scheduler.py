"""
Project: Global Macro & Asset Monitor (CIO Edition)
Version: 5.0.0 (Asynchronous & Fast-Exit Edition)
Description: Optimized for GitHub Actions to stay within 60s execution limit.
"""
import requests
import os
import csv
import pytz
import json
import time
from datetime import datetime, timezone
from yahooquery import Ticker

# --- 环境配置 ---
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
        payload = {"title": title, "body": body, "group": "InvestmentMonitor", "sound": "calypso"}
        requests.post(url, json=payload, timeout=10)
    except Exception as e: print(f"推送失败: {e}")

def load_state():
    if os.path.exists(STATE_CACHE_PATH):
        try:
            with open(STATE_CACHE_PATH, "r") as f: return json.load(f)
        except: pass
    return {"date": "", "alerts": {}, "last_push_time": {}}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_CACHE_PATH), exist_ok=True)
    with open(STATE_CACHE_PATH, "w") as f: json.dump(state, f)

def fetch_top_news(symbol):
    """仅在必要时调用，增加缓存友好头"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}"
        r = requests.get(url, headers=headers, timeout=5)
        news = r.json().get("news", [])
        return " | ".join([n['title'] for n in news[:3]]) if news else "暂无资讯"
    except: return "资讯抓取略过"

def ai_analyze(symbol_info, pct, news, mode="MONITOR", asset_type="STOCK"):
    if not DASHSCOPE_API_KEY: return "AI Key 缺失"
    model = "qwen-max" if mode == "SUMMARY" else "qwen-plus"
    
    if mode == "MONITOR":
        prompts = {
            "FUTURES": f"【期货】{symbol_info}|{pct:.2f}%\n资讯:{news}\n研判:1.归因;2.多空建议;3.关键位。80字内。",
            "MACRO": f"【宏观】{symbol_info}|{pct:.2f}%\n研判该变量对全球资产定价的影响路径。60字内。",
            "STOCK": f"【股票】{symbol_info}|{pct:.2f}%\n资讯:{news}\n研判:1.α/β归因;2.预期差修正。80字内。"
        }
        prompt = prompts.get(asset_type, prompts["STOCK"])
    else:
        prompt = f"【晨会内参】资讯:{news}\n请脱水研判今日核心宏观变量及各品种定价评估。专业凝炼。"

    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": model, "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=payload, timeout=40)
        return r.json()['output']['text']
    except: return "AI 响应超时，请关注价格本身。"

def main():
    now_utc = datetime.now(timezone.utc)
    cn_now = now_utc.astimezone(pytz.timezone("Asia/Shanghai"))
    us_now = now_utc.astimezone(pytz.timezone("US/Eastern"))
    hm_cn, hm_us = cn_now.hour * 100 + cn_now.minute, us_now.hour * 100 + us_now.minute
    
    # 确定任务类型
    action = "IDLE"
    if cn_now.weekday() < 5 and 830 <= hm_cn <= 850: action = "SUMMARY"
    elif us_now.weekday() < 5 and 830 <= hm_us <= 850: action = "SUMMARY"
    if action == "IDLE":
        if cn_now.weekday() < 5 and (915 <= hm_cn <= 1515): action = "MONITOR"
        elif us_now.weekday() < 5 and (925 <= hm_us <= 1615): action = "MONITOR"
    if action == "IDLE": return

    # 读取 Watchlist
    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        watchlist = list(csv.DictReader(f))
    symbols = [item['symbol'] for item in watchlist]

    # --- 批量抓取核心数据 (关键优化) ---
    print(f"[{cn_now.strftime('%H:%M:%S')}] 并发抓取 {len(symbols)} 个标的数据...")
    ticker_engine = Ticker(symbols, asynchronous=True, formatted=False)
    all_data = ticker_engine.price
    
    state = load_state()
    today = now_utc.strftime('%Y%m%d')
    if state.get("date") != today:
        state = {"date": today, "alerts": {}, "last_push_time": {}}

    if action == "SUMMARY":
        # 内参模式：批量获取资讯后提交 AI
        news_list = []
        for i in watchlist:
            news_list.append(f"[{i['name']}]\n{fetch_top_news(i['symbol'])}")
        report = ai_analyze("", 0, "\n".join(news_list), mode="SUMMARY")
        bark_push("🌍 CIO 全球资产内参", report)

    elif action == "MONITOR":
        current_ts = time.time()
        pending_alerts = []

        for item in watchlist:
            s, name = item['symbol'], item['name']
            p_data = all_data.get(s)
            if not isinstance(p_data, dict): continue

            price = p_data.get("regularMarketPrice")
            prev = p_data.get("regularMarketPreviousClose")
            if not price or not prev: continue
            
            pct = ((price - prev) / prev * 100)
            
            # 策略配置
            asset_type, l1, l2 = "STOCK", 3.0, 6.0
            if "=F" in s: asset_type, l1, l2 = "FUTURES", 1.5, 3.0
            elif s in ["DX-Y.NYB", "^TNX", "CNY=X"]: asset_type, l1, l2 = "MACRO", 0.5, 1.0

            level = 2 if abs(pct) >= l2 else (1 if abs(pct) >= l1 else 0)
            
            # 预警触发判定
            last_lvl = state["alerts"].get(s, 0)
            last_ts = state["last_push_time"].get(s, 0)
            
            if level > 0:
                if level > last_lvl or (level == last_lvl and (current_ts - last_ts) > COOL_DOWN_SECONDS):
                    print(f"⚡ 发现异动: {name} {pct:.2f}%")
                    news = fetch_top_news(s)
                    analysis = ai_analyze(f"{name}({s})", pct, news, mode="MONITOR", asset_type=asset_type)
                    emoji = "🌐" if asset_type == "MACRO" else ("🌋" if asset_type == "FUTURES" else "🔔")
                    pending_alerts.append(f"{emoji} {name} {pct:.2f}% (现价:{price})\n{analysis}")
                    
                    state["alerts"][s] = level
                    state["last_push_time"][s] = current_ts

        # --- 推送与状态保存 ---
        if pending_alerts:
            total = len(pending_alerts)
            for i in range(0, total, CHUNK_SIZE):
                chunk = pending_alerts[i:i + CHUNK_SIZE]
                title = f"📊 市场异动内参 ({i//CHUNK_SIZE + 1}/{(total+CHUNK_SIZE-1)//CHUNK_SIZE})"
                bark_push(title, "\n\n".join(chunk))
        else:
            print("行情平稳，无异动触发。")

    save_state(state)

if __name__ == "__main__":
    main()
