"""
Project: Global Macro & Asset Monitor (CIO Edition)
Version: 5.2.6 (CIO Decision Engine)
Focus: 基本面量化、持仓预警、技术交易窗口、潜流推演
"""
import requests, os, csv, pytz, json, time, hashlib
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
        url = f"{BARK_URL.rstrip('/')}/"
        payload = {"title": title, "body": body, "group": "CIO_Decision", "sound": "minuet"}
        requests.post(url, json=payload, timeout=10)
    except: pass

def load_state():
    default_state = {"date": "", "alerts": {}, "last_pct": {}, "last_news_hash": {}}
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

def fetch_enhanced_context(symbol, name):
    """强化搜索：若无直观新闻，尝试抓取异动传闻和市场评论"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        search_query = f"{name} {symbol.split('.')[0]} 异动 传闻 公告"
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={search_query}&newsCount=5"
        r = requests.get(url, headers=headers, timeout=5)
        news_items = r.json().get("news", [])
        
        raw_text = ""
        for n in news_items:
            raw_text += f"· {n.get('title','')} (来源:{n.get('publisher','')})\n"
        
        news_hash = hashlib.md5(raw_text.encode()).hexdigest() if raw_text else "no_news_hash"
        return raw_text if raw_text else "全网暂无即时公开资讯流。", news_hash
    except:
        return "资讯抓取异常", "err_hash"

def ai_decision_engine(symbol_info, price_data, news_text):
    """
    顶级买方 CIO 指令集注入
    """
    pct = price_data['pct']
    # 提取关键技术位数据
    tech_context = (
        f"现价: {price_data['price']}, 52周最高: {price_data['high52']}, "
        f"52周最低: {price_data['low52']}, 日内区间: {price_data['range']}"
    )

    prompt = f"""
你是一位管理全球头寸的买方投资总监（CIO），兼具第一性原理深度与交易敏感度。
标的: {symbol_info} | 涨跌幅: {pct:.2f}%
技术位参考: {tech_context}
关联资讯: {news_text}

请严格按以下逻辑输出研判（150字内）：
1.【逻辑定性】判定异动时效：短期博弈、中长期重构、或随机波动？
2.【实质影响】量化描述对业务、财务及行业地位的实损或利好。
3.【持仓预警】逻辑是否改变？若触及逻辑证伪点请预警，无则忽略。
4.【交易窗口】比对技术位，分析趋势状态，给出高抛/低吸或观望的交易性机会建议。
5.【深度潜流】(核心)若无资讯，请基于第一性原理推演潜在的未公开风险或隐性机会。

拒绝废话，直指本质。
"""
    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "qwen-plus", "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        return r.json()['output']['text']
    except: return "CIO逻辑引擎暂时脱机。"

def main():
    now_utc = datetime.now(timezone.utc)
    cn_now = now_utc.astimezone(pytz.timezone("Asia/Shanghai"))
    time_str = cn_now.strftime('%H:%M:%S')

    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        watchlist = list(csv.DictReader(f))
    
    symbols = [i['symbol'] for i in watchlist]
    te = Ticker(symbols, asynchronous=True, formatted=False)
    all_data = te.price

    state = load_state()
    today_str = cn_now.strftime('%Y%m%d')
    if state.get("date") != today_str:
        state = {"date": today_str, "alerts": {}, "last_pct": {}, "last_news_hash": {}}

    pending_alerts = []
    for item in watchlist:
        s, name = item['symbol'], item['name']
        data = all_data.get(s)
        if not isinstance(data, dict): continue
        
        # 提取基础与技术位数据
        price = data.get("regularMarketPrice")
        prev = data.get("regularMarketPreviousClose")
        if not price or not prev: continue
        
        pct = ((price - prev) / prev * 100)
        price_meta = {
            'price': price, 'pct': pct,
            'high52': data.get("fiftyTwoWeekHigh"),
            'low52': data.get("fiftyTwoWeekLow"),
            'range': f"{data.get('regularMarketDayLow')} - {data.get('regularMarketDayHigh')}"
        }

        # 1. 资讯搜集与一致性校验
        news_content, current_hash = fetch_enhanced_context(s, name)
        
        # 2. 判定推送阈值
        level = 2 if abs(pct) >= 6.0 else (1 if abs(pct) >= 3.0 else 0)
        last_level = state["alerts"].get(s, 0)
        last_pct = state["last_pct"].get(s, 0.0)
        last_hash = state["last_news_hash"].get(s, "")

        # 推送条件：级别提升 OR 新闻更新 OR (无新闻但价格波动巨大且此前未推)
        should_push = (level > last_level) or (current_hash != last_hash)
        
        if should_push and level > 0:
            print(f"[{time_str}] 触发 CIO 决策流: {name}")
            analysis = ai_decision_engine(f"{name}({s})", price_meta, news_content)
            pending_alerts.append(f"🛡️ CIO 策略 [{name} {pct:.2f}%]\n{analysis}")
            
            # 更新状态
            state["alerts"][s] = level
            state["last_pct"][s] = pct
            state["last_news_hash"][s] = current_hash

    if pending_alerts:
        bark_push(f"📊 CIO 深度内参 [{time_str}]", "\n\n".join(pending_alerts))

    save_state(state)

if __name__ == "__main__":
    main()
