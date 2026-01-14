import requests
import os
import csv
import pytz
import json
import urllib.parse
import time
from datetime import datetime, timezone
from yahooquery import Ticker

# --- 环境配置 ---
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
STATE_CACHE_PATH = "data/alert_state.json"
BARK_URL = os.getenv("BARK_URL")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
COOL_DOWN_SECONDS = 3600  # 冷却时间：1小时
CHUNK_SIZE = 6           # 每批次推送的最大标的数量

def bark_push(title, body):
    if not BARK_URL: return
    try:
        url = f"{BARK_URL.rstrip('/')}/"
        payload = {
            "title": title,
            "body": body,
            "group": "InvestmentMonitor",
            "sound": "calypso"
        }
        requests.post(url, json=payload, timeout=15)
    except Exception as e: print(f"推送失败: {e}")

def load_state():
    if os.path.exists(STATE_CACHE_PATH):
        try:
            with open(STATE_CACHE_PATH, "r") as f: return json.load(f)
        except: return {}
    return {"date": "", "alerts": {}, "last_push_time": {}}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_CACHE_PATH), exist_ok=True)
    with open(STATE_CACHE_PATH, "w") as f: json.dump(state, f)

def fetch_top_news(symbol):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}"
        r = requests.get(url, headers=headers, timeout=10)
        news = r.json().get("news", [])
        return " | ".join([n['title'] for n in news[:5]]) if news else "暂无资讯"
    except: return "资讯抓取异常"

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
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        return r.json()['output']['text']
    except: return "AI 响应波动"

def main():
    now_utc = datetime.now(timezone.utc)
    cn_now = now_utc.astimezone(pytz.timezone("Asia/Shanghai"))
    us_now = now_utc.astimezone(pytz.timezone("US/Eastern"))
    print(f"--- 启动 [{cn_now.strftime('%H:%M:%S')}] ---")
    
    action = "IDLE"
    hm_cn, hm_us = cn_now.hour * 100 + cn_now.minute, us_now.hour * 100 + us_now.minute

    if cn_now.weekday() < 5 and 830 <= hm_cn <= 845: action = "SUMMARY"
    elif us_now.weekday() < 5 and 830 <= hm_us <= 845: action = "SUMMARY"
    
    if action == "IDLE":
        if cn_now.weekday() < 5 and (915 <= hm_cn <= 1510): action = "MONITOR"
        elif us_now.weekday() < 5 and (925 <= hm_us <= 1610): action = "MONITOR"

    if action == "IDLE": return

    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        watchlist = list(csv.DictReader(f))

    state = load_state()
    today = datetime.now(timezone.utc).strftime('%Y%m%d')
    if state.get("date") != today:
        state = {"date": today, "alerts": {}, "last_push_time": {}}

    if action == "SUMMARY":
        news_data = "\n".join([f"[{i['name']}({i['symbol']})]\n{fetch_top_news(i['symbol'])}" for i in watchlist])
        report = ai_analyze("", 0, news_data, mode="SUMMARY")
        bark_push("🌍 CIO 全球资产内参", report)

    elif action == "MONITOR":
        current_ts = time.time()
        pending_alerts = []

        for item in watchlist:
            s, name = item['symbol'], item['name']
            asset_type, l1, l2 = "STOCK", 3.0, 6.0
            if "=F" in s or "FTX" in s: asset_type, l1, l2 = "FUTURES", 1.5, 3.0
            elif s in ["DX-Y.NYB", "^TNX", "CNY=X"]: asset_type, l1, l2 = "MACRO", 0.5, 1.0
            elif "USD" in s: asset_type, l1, l2 = "FUTURES", 2.0, 5.0

            try:
                t = Ticker(s)
                p = t.price[s]
                price, prev = p.get("regularMarketPrice"), p.get("regularMarketPreviousClose")
                if not price or not prev: continue
                pct = ((price - prev) / prev * 100)
                level = 2 if abs(pct) >= l2 else (1 if abs(pct) >= l1 else 0)
                
                last_time = state["last_push_time"].get(s, 0)
                is_cooled = (current_ts - last_time) > COOL_DOWN_SECONDS
                is_level_up = level > state["alerts"].get(s, 0)

                if level > 0 and (is_level_up or (level == state["alerts"].get(s, 0) and is_cooled)):
                    print(f"分析异动: {name}")
                    analysis = ai_analyze(f"{name}({s})", pct, fetch_top_news(s), mode="MONITOR", asset_type=asset_type)
                    emoji = "🌐" if asset_type == "MACRO" else ("🌋" if asset_type == "FUTURES" else "🔔")
                    pending_alerts.append(f"{emoji} {name} {pct:.2f}% (现价:{price})\n{analysis}")
                    
                    state["alerts"][s] = level
                    state["last_push_time"][s] = current_ts
            except: continue
        
        # --- 分批推送逻辑 (每 6 条一组) ---
        if pending_alerts:
            total = len(pending_alerts)
            for i in range(0, total, CHUNK_SIZE):
                chunk = pending_alerts[i:i + CHUNK_SIZE]
                batch_no = (i // CHUNK_SIZE) + 1
                total_batches = (total + CHUNK_SIZE - 1) // CHUNK_SIZE
                
                title = f"📊 市场异动内参 ({batch_no}/{total_batches})"
                body = "\n\n".join(chunk)
                bark_push(title, body)
                if total_batches > 1: time.sleep(1) # 多批次发送时稍作停顿，防止乱序
            
            print(f"共推送 {total} 条异动研判，分为 {total_batches} 批次。")

    save_state(state)

if __name__ == "__main__":
    main()
