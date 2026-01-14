import requests
import os
import csv
import pytz
import json
import urllib.parse
from datetime import datetime, timezone
from yahooquery import Ticker

# --- 环境配置 ---
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
STATE_CACHE_PATH = "data/alert_state.json"
BARK_URL = os.getenv("BARK_URL")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

def bark_push(title, body):
    if not BARK_URL: return
    try:
        url = f"{BARK_URL.rstrip('/')}/{urllib.parse.quote(str(title))}/{urllib.parse.quote(str(body))}"
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
        return " | ".join([n['title'] for n in news[:5]]) if news else "暂无直接核心资讯"
    except: return "资讯抓取链路异常"

# --- AI 核心引擎 (顶级 CIO 视角) ---
def ai_analyze(symbol_info, pct, news, mode="MONITOR"):
    if not DASHSCOPE_API_KEY: return "AI Key 缺失"
    
    if mode == "MONITOR":
        trend = "上涨" if pct > 0 else "下跌"
        prompt = (
            f"【投资总监异动研判】\n标的：{symbol_info} | 异动：{trend} {abs(pct):.2f}%\n资讯：{news}\n\n"
            "要求(150字内)：\n1. 归因：界定是宏观β(流动性/政策)还是个股α(财报/基本面)驱动。\n"
            "2. 定价：分析此异动是否代表市场预期差的边际修正，非简单复读新闻。\n"
            "3. 纯度：剔除废话，若资讯弱相关，请直言‘资金博弈，无显著诱因’。"
        )
        model = "qwen-plus"
    else:
        prompt = (
            f"【首席策略师晨会内参】\n资讯池：{news}\n\n"
            "任务：对 24H 资讯执行‘脱水’研判，输出高密度策略简报：\n"
            "1. 核心变量：穿透出对今日开盘有重大定价影响的宏观变量及行业趋势。\n"
            "2. 归母定价：按公司分组，直接给出驱动因素与定价边际变化评估(看多/看空/中性)。\n"
            "3. 警示：标注可能引发预期反转的非对称因子。要求专业、凝炼、无空话。"
        )
        model = "qwen-max"

    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": model, "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=payload, timeout=60) # 延长至 60s
        return r.json()['output']['text']
    except Exception as e:
        return f"【系统告警】AI 分析响应超时或波动，请结合资讯自行研判：{str(e)}"

# --- 调度逻辑 ---
def main():
    now_utc = datetime.now(timezone.utc)
    cn_now, us_now = now_utc.astimezone(pytz.timezone("Asia/Shanghai")), now_utc.astimezone(pytz.timezone("US/Eastern"))
    action = "IDLE"
    hm_cn, hm_us = cn_now.hour * 100 + cn_now.minute, us_now.hour * 100 + us_now.minute

    # 盘前汇总判断
    if cn_now.weekday() < 5 and 830 <= hm_cn <= 845: action = "SUMMARY"
    elif us_now.weekday() < 5 and 830 <= hm_us <= 845: action = "SUMMARY"
    
    # 监控判断
    if action == "IDLE":
        if cn_now.weekday() < 5 and ((915 <= hm_cn <= 1140) or (1255 <= hm_cn <= 1510)): action = "MONITOR"
        elif us_now.weekday() < 5 and (925 <= hm_us <= 1610): action = "MONITOR"

    if action == "IDLE": return

    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        watchlist = list(csv.DictReader(f))

    state = load_state()
    today = datetime.now(timezone.utc).strftime('%Y%m%d')
    if state.get("date") != today: state = {"date": today, "alerts": {}}

    if action == "SUMMARY":
        news_data = "\n".join([f"[{item['name']}({item['symbol']})]\n{fetch_top_news(item['symbol'])}" for item in watchlist])
        report = ai_analyze("", 0, news_data, mode="SUMMARY")
        bark_push("🌍 CIO 盘前深度内参", report)

    elif action == "MONITOR":
        for item in watchlist:
            s, name = item['symbol'], item['name']
            try:
                t = Ticker(s)
                p = t.price[s]
                price, prev = p.get("regularMarketPrice"), p.get("regularMarketPreviousClose")
                if not price or not prev: continue
                pct = ((price - prev) / prev * 100)
                level = 2 if abs(pct) >= 6.0 else (1 if abs(pct) >= 3.0 else 0)
                
                if level > state["alerts"].get(s, 0):
                    analysis = ai_analyze(f"{name}({s})", pct, fetch_top_news(s), mode="MONITOR")
                    bark_push(f"{'🔥' if level==2 else '🔔'} {name} {'涨' if pct>0 else '跌'}{abs(pct):.2f}%", f"现价: {price}\n【研判】: {analysis}")
                    state["alerts"][s] = level
            except: continue
        save_state(state)

if __name__ == "__main__":
    main()
