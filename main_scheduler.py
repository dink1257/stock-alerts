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
        # 编码处理，确保推送内容包含特殊字符时不报错
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
    """增强版抓取：模拟浏览器身份防止被拦截"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}"
        r = requests.get(url, headers=headers, timeout=10)
        news = r.json().get("news", [])
        if not news: return f"{symbol} 暂无即时重要资讯"
        return " | ".join([n['title'] for n in news[:5]])
    except: return f"{symbol} 新闻抓取链路异常"

# --- 核心 AI 分析引擎（买方研究员视角） ---
def ai_analyze(symbol, pct, news, mode="MONITOR"):
    if not DASHSCOPE_API_KEY: return "AI 分析 Key 缺失，请检查环境变量设置。"
    
    if mode == "MONITOR":
        trend = "上涨" if pct > 0 else "下跌"
        # 150字买方研究员风格指令
        prompt = (
            f"【买方研究员深度分析指令】\n"
            f"标的：{symbol} | 当前市场异动：{trend} {abs(pct):.2f}%\n"
            f"参考资讯流：{news}\n\n"
            f"任务要求：\n"
            f"1. 严谨性：以买方分析师视角，客观、准确解释股价{trend}的核心逻辑。严禁给出逻辑相左或无关的推论。\n"
            f"2. 维度覆盖：不得遗漏以下关键点（如有）：重大宏观政策变动、所属行业趋势、公司基本面重大变化或核心公告。\n"
            f"3. 真实性：若提供的新闻中无相关实质性利好/利空，请客观说明‘当前公开资讯未发现直接支撑逻辑’，严禁强行关联新闻。\n"
            f"4. 规范：内容逻辑链条闭环，字数控制在150字左右，禁止空洞套话。"
        )
        model = "qwen-plus"
    else: 
        # SUMMARY 汇总模式（针对所有自选股的 24h 扫描）
        prompt = (
            f"【自选股 24H 深度汇总报告 - 买方视角】\n资讯池：{news}\n\n"
            f"1. 逻辑翻译与去重：将全球资讯翻译为中文，剔除噪音信息。\n"
            f"2. 深度过滤：仅保留对股价有中长期影响的重大宏观、行业、个股资讯。\n"
            f"3. 归因分析：按公司分组，以买方研究视角输出：[关键驱动因素] + [潜在市场影响评估]。\n"
            f"4. 要求：逻辑闭环，准确专业，单条逻辑精炼但信息量完整。"
        )
        model = "qwen-max" 

    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": model, "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=payload, timeout=40)
        return r.json()['output']['text']
    except Exception as e:
        return f"AI 分析暂时不可用，错误信息: {str(e)}"

# --- 自动化调度主逻辑 ---
def main():
    now_utc = datetime.now(timezone.utc)
    cn_now = now_utc.astimezone(pytz.timezone("Asia/Shanghai"))
    us_now = now_utc.astimezone(pytz.timezone("US/Eastern"))
    
    action = "IDLE"

    # A股调度逻辑
    if cn_now.weekday() < 5:
        hm = cn_now.hour * 100 + cn_now.minute
        if 830 <= hm <= 845: action = "SUMMARY"
        elif (925 <= hm <= 1135) or (1255 <= hm <= 1510): action = "MONITOR"
    
    # 美股调度逻辑
    if us_now.weekday() < 5:
        hm = us_now.hour * 100 + us_now.minute
        if 830 <= hm <= 845: action = "SUMMARY"
        elif 925 <= hm <= 1610: action = "MONITOR"

    if action == "IDLE": 
        print(f"当前时间(CN): {cn_now.strftime('%H:%M')}，非核心监控时段，系统静默。")
        return

    # 加载自选股
    if not os.path.exists(WATCHLIST_PATH):
        print("错误：未找到 watchlist.csv 文件。")
        return
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        stocks = [r['symbol'].strip() for r in csv.DictReader(f) if r.get('symbol')]

    state = load_state()
    today = datetime.now(timezone.utc).strftime('%Y%m%d')
    if state.get("date") != today: state = {"date": today, "alerts": {}}

    if action == "SUMMARY":
        print("正在生成买方视角盘前深度汇总...")
        combined_news = []
        for s in stocks: 
            news_text = fetch_top_news(s)
            combined_news.append(f"[{s}]\n{news_text}")
        
        report = ai_analyze("", 0, "\n".join(combined_news), mode="SUMMARY")
        if report: bark_push("☕ 盘前自选股深度动态", report)

    elif action == "MONITOR":
        print("正在进行实时异动监控...")
        for s in stocks:
            try:
                t = Ticker(s)
                p = t.price[s]
                price = p.get("regularMarketPrice")
                prev = p.get("regularMarketPreviousClose")
                if not price or not prev: continue
                
                pct = ((price - prev) / prev * 100)
                abs_pct = abs(pct)
                
                # 触发阈值：3% (Level 1), 6% (Level 2)
                level = 2 if abs_pct >= 6.0 else (1 if abs_pct >= 3.0 else 0)
                
                if level > state["alerts"].get(s, 0):
                    news = fetch_top_news(s)
                    analysis = ai_analyze(s, pct, news, mode="MONITOR")
                    title = f"{'🔥' if level==2 else '🔔'} {s} {trend}{abs_pct:.2f}%"
                    bark_push(title, f"最新价: {price}\n【深度分析】: {analysis}")
                    state["alerts"][s] = level
            except: continue
        save_state(state)

if __name__ == "__main__":
    main()
