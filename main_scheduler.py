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
    """支持全球市场的新闻抓取，模拟浏览器防止拦截"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}"
        r = requests.get(url, headers=headers, timeout=10)
        news = r.json().get("news", [])
        if not news: return f"{symbol} 暂无即时重要资讯"
        return " | ".join([n['title'] for n in news[:5]])
    except: return f"{symbol} 资讯链路异常"

# --- 核心 AI 分析引擎 (买方研究员视角) ---
def ai_analyze(symbol, pct, news, mode="MONITOR"):
    if not DASHSCOPE_API_KEY: return "AI 分析 Key 缺失。"
    
    if mode == "MONITOR":
        trend = "上涨" if pct > 0 else "下跌"
        prompt = (
            f"【买方研究员深度分析指令】\n"
            f"标的：{symbol} | 当前市场异动：{trend} {abs(pct):.2f}%\n"
            f"参考资讯流：{news}\n\n"
            f"任务要求：\n"
            f"1. 严谨性：以买方分析师视角，客观解释股价{trend}的核心逻辑，严禁给出逻辑相左的推论。\n"
            f"2. 维度覆盖：不得遗漏重大宏观政策变动、所属行业趋势、公司基本面重大变化或核心公告。\n"
            f"3. 真实性：若资讯中无实质性内容，请说明‘当前公开资讯未发现直接支撑逻辑’，严禁强行关联。\n"
            f"4. 规范：字数在150字左右，逻辑链条闭环，禁止空洞套话。"
        )
        model = "qwen-plus"
    else: 
        prompt = (
            f"【自选股(A/港/美) 24H 深度汇总报告】\n资讯池：{news}\n\n"
            f"1. 翻译与去重：全球资讯翻译为中文，剔除噪音。\n"
            f"2. 深度过滤：仅保留对股价有中长期影响的重大宏观、行业、个股资讯。\n"
            f"3. 归因分析：按公司分组，以买方视角输出：[驱动因素] + [潜在市场影响评估]。\n"
            f"4. 要求：逻辑准确专业，单条逻辑完整，总字数控制在有效范围内。"
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

# --- 自动化调度主逻辑 (覆盖 A/港/美 市场) ---
def main():
    now_utc = datetime.now(timezone.utc)
    cn_tz = pytz.timezone("Asia/Shanghai")
    us_tz = pytz.timezone("US/Eastern")
    
    cn_now = now_utc.astimezone(cn_tz)
    us_now = now_utc.astimezone(us_tz)
    
    action = "IDLE"
    hm_cn = cn_now.hour * 100 + cn_now.minute
    hm_us = us_now.hour * 100 + us_now.minute

    # --- 1. 盘前汇总触发 (A股与港股 08:30 | 美股盘前 21:30) ---
    if cn_now.weekday() < 5 and 830 <= hm_cn <= 845:
        action = "SUMMARY"
    elif us_now.weekday() < 5 and 830 <= hm_us <= 845:
        action = "SUMMARY"

    # --- 2. 实时异动监控触发 (排除盘前汇总时间) ---
    if action == "IDLE":
        # A股交易时段
        if cn_now.weekday() < 5 and ((925 <= hm_cn <= 1135) or (1255 <= hm_cn <= 1510)):
            action = "MONITOR"
        # 港股交易时段 (包含收盘竞价)
        elif cn_now.weekday() < 5 and ((915 <= hm_cn <= 1210) or (1255 <= hm_cn <= 1610)):
            action = "MONITOR"
        # 美股正式交易时段
        elif us_now.weekday() < 5 and (925 <= hm_us <= 1610):
            action = "MONITOR"

    if action == "IDLE": 
        print(f"当前时间(CN): {cn_now.strftime('%H:%M')}，非监控时段。")
        return

    # 加载自选股
    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        stocks = [r['symbol'].strip() for r in csv.DictReader(f) if r.get('symbol')]

    state = load_state()
    today = datetime.now(timezone.utc).strftime('%Y%m%d')
    if state.get("date") != today: state = {"date": today, "alerts": {}}

    if action == "SUMMARY":
        print("执行盘前深度汇总...")
        news_list = []
        for s in stocks: news_list.append(f"[{s}]\n{fetch_top_news(s)}")
        report = ai_analyze("", 0, "\n".join(news_list), mode="SUMMARY")
        if report: bark_push("🌍 全球自选股深度动态汇总", report)

    elif action == "MONITOR":
        print("执行异动扫描...")
        for s in stocks:
            try:
                t = Ticker(s)
                p = t.price[s]
                price = p.get("regularMarketPrice")
                prev = p.get("regularMarketPreviousClose")
                if not price or not prev: continue
                
                pct = ((price - prev) / prev * 100)
                abs_pct = abs(pct)
                level = 2 if abs_pct >= 6.0 else (1 if abs_pct >= 3.0 else 0)
                
                if level > state["alerts"].get(s, 0):
                    news = fetch_top_news(s)
                    analysis = ai_analyze(s, pct, news, mode="MONITOR")
                    title = f"{'🔥' if level==2 else '🔔'} {s} {'涨' if pct>0 else '跌'}{abs_pct:.2f}%"
                    bark_push(title, f"现价: {price}\n【买方分析】: {analysis}")
                    state["alerts"][s] = level
            except: continue
        save_state(state)

if __name__ == "__main__":
    main()
