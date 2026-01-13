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
        safe_title = urllib.parse.quote(title, safe='')
        safe_body = urllib.parse.quote(body, safe='')
        requests.get(f"{BARK_URL.rstrip('/')}/{safe_title}/{safe_body}", timeout=10)
    except Exception as e:
        print(f"推送失败: {e}")

def load_state():
    if os.path.exists(STATE_CACHE_PATH):
        try:
            with open(STATE_CACHE_PATH, "r") as f:
                return json.load(f)
        except: return {}
    return {}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_CACHE_PATH), exist_ok=True)
    with open(STATE_CACHE_PATH, "w") as f:
        json.dump(state, f)

def ai_analyze_logic(symbol, pct, news, is_deep=False):
    """
    强化 Prompt：确保分析与涨跌方向强相关
    """
    if not DASHSCOPE_API_KEY: return "AI Key 缺失"
    trend = "上涨" if pct > 0 else "下跌"
    abs_pct = abs(pct)
    
    # 针对不同等级的强约束指令
    if not is_deep:
        # 3% 基础分析：侧重于逻辑确认
        prompt = (
            f"【逻辑分析指令】\n股票：{symbol} 当前实测：{trend} {abs_pct:.2f}%\n"
            f"参考新闻：{news}\n"
            f"要求：1. 必须解释导致{trend}的直接逻辑，严禁给出与{trend}相反的分析。\n"
            f"2. 若新闻不相关，请直接回答'监控到异动但当前新闻无直接诱因'。\n"
            f"3. 中文输出，120字以内，禁止套话。"
        )
        model = "qwen-turbo"
    else:
        # 6% 深度分析：侧重于烈度分析
        prompt = (
            f"【烈度评估指令】\n股票：{symbol} 实测{trend}已达：{abs_pct:.2f}% (显著波动)\n"
            f"参考新闻：{news}\n"
            f"要求：1. 深度挖掘导致此次剧烈{trend}的催化剂，评估其影响烈度与持续性。\n"
            f"2. 逻辑必须强相关。3. 中文输出，150字左右，分条列出干货。"
        )
        model = "qwen-plus" # 深度分析建议用逻辑更强的 plus 模型

    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        data = {"model": model, "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=data, timeout=20)
        return r.json()['output']['text']
    except Exception as e:
        return f"逻辑解析中断: {e}"

def fetch_top_news(symbol):
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}"
        r = requests.get(url, timeout=10)
        news = r.json().get("news", [])
        return " | ".join([n['title'] for n in news[:5]]) if news else "暂无即时新闻"
    except: return "新闻抓取失败"

def is_market_open(symbol):
    now_utc = datetime.now(timezone.utc)
    if "-" in symbol: return True
    sh_now = now_utc.astimezone(pytz.timezone("Asia/Shanghai"))
    hhmm = sh_now.hour * 100 + sh_now.minute
    if symbol.endswith((".SS", ".SZ", ".HK")):
        return (925 <= hhmm <= 1135) or (1255 <= hhmm <= 1510)
    est_now = now_utc.astimezone(pytz.timezone("US/Eastern"))
    hhmm_est = est_now.hour * 100 + est_now.minute
    return 925 <= hhmm_est <= 1610

def check_prices():
    state = load_state()
    today_str = datetime.now(timezone.utc).strftime('%Y%m%d')
    if state.get("date") != today_str:
        state = {"date": today_str, "alerts": {}}

    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for row in rows:
        symbol = row.get("symbol", "").strip()
        if not symbol or not is_market_open(symbol): continue

        try:
            t = Ticker(symbol)
            p_data = t.price.get(symbol, {})
            price = p_data.get("regularMarketPrice")
            prev = p_data.get("regularMarketPreviousClose")
            if price is None or prev is None: continue
            
            pct = ((price - prev) / prev * 100)
            abs_pct = abs(pct)

            # 阶梯判定
            current_level = 0
            if abs_pct >= 6.0: current_level = 2
            elif abs_pct >= 3.0: current_level = 1

            # 只有当 Level 提升时才触发
            last_level = state["alerts"].get(symbol, 0)
            if current_level > last_level:
                is_deep = (current_level == 2)
                news = fetch_top_news(symbol)
                analysis = ai_analyze_logic(symbol, pct, news, is_deep=is_deep)
                
                direction_icon = "🚀上涨" if pct > 0 else "📉下跌"
                level_icon = "🔥深度" if is_deep else "🔔触发"
                
                title = f"{level_icon}: {symbol} {direction_icon} {abs_pct:.2f}%"
                content = f"现价: {price}\n【{'催化烈度分析' if is_deep else '强相关逻辑'}】:\n{analysis}"
                
                bark_push(title, content)
                state["alerts"][symbol] = current_level
                print(f"[OK] 已推送 {symbol} Level {current_level}")
        except Exception as e:
            print(f"[ERR] {symbol}: {e}")

    save_state(state)

if __name__ == "__main__":
    check_prices()
