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
        encoded_title = urllib.parse.quote(str(title))
        encoded_body = urllib.parse.quote(str(body))
        url = f"{BARK_URL.rstrip('/')}/{encoded_title}/{encoded_body}"
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
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}"
        r = requests.get(url, headers=headers, timeout=10)
        news = r.json().get("news", [])
        if not news: return f"暂无关于 {symbol} 的即时重要资讯"
        return " | ".join([n['title'] for n in news[:5]])
    except: return "资讯链路异常"

# --- 核心 AI 分析引擎 ---
def ai_analyze(symbol_info, pct, news, mode="MONITOR"):
    if not DASHSCOPE_API_KEY: return "AI Key 缺失"
    
    if mode == "MONITOR":
        trend = "上涨" if pct > 0 else "下跌"
        prompt = (
            f"【买方研究员深度分析指令】\n标的：{symbol_info} | 异动：{trend} {abs(pct):.2f}%\n"
            f"参考资讯：{news}\n\n要求：1.客观解释{trend}核心逻辑。2.覆盖政策、行业及基本面。3.无相关资讯请说明‘无直接诱因’。4.约150字，逻辑闭环。"
        )
        model = "qwen-plus"
    else: 
        prompt = (
            f"【自选股(A/港/美) 24H 深度汇总 - 买方视角】\n资讯：{news}\n\n要求：翻译去重，仅保留中长期影响的重大因素。按公司分组输出：[驱动因素] + [影响评估]。"
        )
        model = "qwen-max" 

    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": model, "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=payload, timeout=40)
        return r.json()['output']['text']
    except Exception as e:
        return f"AI 分析暂时不可用: {str(e)}"

# --- 调度主逻辑 ---
def main():
    now_utc = datetime.now(timezone.utc)
    cn_tz, us_tz = pytz.timezone("Asia/Shanghai"), pytz.timezone("US/Eastern")
    cn_now, us_now = now_utc.astimezone(cn_tz), now_utc.astimezone(us_tz)
    
    action = "IDLE"
    hm_cn, hm_us = cn_now.hour * 100 + cn_now.minute, us_now.hour * 100 + us_now.minute

    if cn_now.weekday() < 5 and 830 <= hm_cn <= 845: action = "SUMMARY"
    elif us_now.weekday() < 5 and 830 <= hm_us <= 845: action = "SUMMARY"
    
    if action == "IDLE":
        if cn_now.weekday() < 5 and ((915 <= hm_cn <= 1210) or (1255 <= hm_cn <= 1610)): action = "MONITOR"
        elif us_now.weekday() < 5 and (925 <= hm_us <= 1610): action = "MONITOR"

    if action == "IDLE": return

    # 加载自选股（读取 symbol 和 name）
    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        # 使用 DictReader 读取 CSV
        watchlist = list(csv.DictReader(f))

    state = load_state()
    today = datetime.now(timezone.utc).strftime('%Y%m%d')
    if state.get("date") != today: state = {"date": today, "alerts": {}}

    if action == "SUMMARY":
        news_list = []
        for item in watchlist:
            s, name = item['symbol'], item['name']
            news_list.append(f"[{name}({s})]\n{fetch_top_news(s)}")
        report = ai_analyze("", 0, "\n".join(news_list), mode="SUMMARY")
        if report: bark_push("🌍 全球自选股深度汇总", report)

    elif action == "MONITOR":
        for item in watchlist:
            s, name = item['symbol'], item['name']
            try:
                t = Ticker(s)
                p = t.price[s]
                price, prev = p.get("regularMarketPrice"), p.get("regularMarketPreviousClose")
                if not price or not prev: continue
                
                pct = ((price - prev) / prev * 100)
                abs_pct = abs(pct)
                level = 2 if abs_pct >= 6.0 else (1 if abs_pct >= 3.0 else 0)
                
                if level > state["alerts"].get(s, 0):
                    news = fetch_top_news(s)
                    analysis = ai_analyze(f"{name}({s})", pct, news, mode="MONITOR")
                    title = f"{'🔥' if level==2 else '🔔'} {name} {'涨' if pct>0 else '跌'}{abs_pct:.2f}%"
                    bark_push(title, f"现价: {price}\n【深度分析】: {analysis}")
                    state["alerts"][s] = level
            except: continue
        save_state(state)

if __name__ == "__main__":
    main()
