"""
Project: Global Macro & Asset Monitor (CIO Edition)
Version: 5.3.2 (Global Market Sentinel)
"""
import requests, os, csv, pytz, json, time, hashlib
from datetime import datetime, timezone
from yahooquery import Ticker

# --- 配置区 ---
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
STATE_CACHE_PATH = "data/alert_state.json"
BARK_URL = os.getenv("BARK_URL")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
VOLATILITY_LOCK = 2.5 

def bark_push(title, body):
    if not BARK_URL: return
    try:
        url = f"{BARK_URL.rstrip('/')}/"
        payload = {"title": title, "body": body, "group": "CIO_Sentinel", "sound": "anticipate"}
        requests.post(url, json=payload, timeout=10)
    except: pass

def load_state():
    default_state = {"date": "", "alerts": {}, "last_pct": {}, "last_news_hash": {}, "summary_done": []}
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
    """深度扫描引擎：不仅看个股，更看关联的监管与政策变动"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        # 核心搜索策略：标的 + 监管关键词（确保不遗漏保证金、限制等重磅）
        query = f"{name} {symbol.split('.')[0]} 突发 政策 监管 保证金 财报"
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&newsCount=5"
        r = requests.get(url, headers=headers, timeout=8)
        news_items = r.json().get("news", [])
        
        raw_text, news_list = "", []
        for n in news_items:
            t = n.get('title', '')
            news_list.append(f"· {t}")
            raw_text += t
        
        content = "\n".join(news_list) if news_list else "全网暂无公开新增逻辑变量。"
        n_hash = hashlib.md5(raw_text.encode()).hexdigest() if raw_text else "no_news"
        return content, n_hash
    except:
        return "资讯接口响应延迟。", "err_hash"

def ai_decision_engine(symbol_info, price_meta, news_text, is_summary=False, is_opening=False):
    """严格锁定 CIO 五维格式输出"""
    if not is_summary:
        tag = "【开盘前决策前瞻】" if is_opening else "【实时异动深度研判】"
        prompt = f"""
你现在是顶级买方投资总监。请针对{tag}标的【{symbol_info}】进行穿透。
现价: {price_meta.get('price')} | 涨跌幅: {price_meta.get('pct', 0):.2f}% | 资讯: {news_text}

请严格按此格式输出（150字内）：
1.【逻辑定性】短期博弈/长期重构/随机噪音？（若是政策，请指出级别）
2.【实质影响】量化描述对业务、财务的实损或利好。
3.【持仓预警】若触及逻辑证伪点（如监管风向转冷、保证金调整）请明确预警。
4.【交易窗口】结合趋势与政策压力，给出具体的撤退/抄底/对冲建议。
5.【深度潜流】基于第一性原理，推演该信息背后未露出的监管意图或行业拐点。
"""
    else:
        prompt = f"""你现在是买方总监。请对全天自选股表现进行【收盘脱水点评】：
清单: {symbol_info}
要求：1.总结涨跌质量。2.识别异常诱因。3.给出次日核心要点。字数100内。"""

    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "qwen-plus", "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=payload, timeout=25)
        return r.json()['output']['text']
    except: return "CIO逻辑引擎暂时脱机。"

def main():
    now_utc = datetime.now(timezone.utc)
    cn_now = now_utc.astimezone(pytz.timezone("Asia/Shanghai"))
    hm_cn = int(cn_now.strftime('%H%M'))

    state = load_state()
    today_str = cn_now.strftime('%Y%m%d')
    if state.get("date") != today_str:
        state = {"date": today_str, "alerts": {}, "last_pct": {}, "last_news_hash": {}, "summary_done": []}

    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        watchlist = list(csv.DictReader(f))
    
    symbols = [i['symbol'] for i in watchlist]
    try:
        te = Ticker(symbols, asynchronous=True, formatted=False)
        all_data = te.price
    except: return

    # --- A/H/US 汇总逻辑 (收盘时点触发) ---
    is_summary_time, label = False, ""
    if 1510 <= hm_cn <= 1525 and "CN_CLOSE" not in state["summary_done"]:
        is_summary_time, label = True, "CN_CLOSE"
    elif 1610 <= hm_cn <= 1625 and "HK_CLOSE" not in state["summary_done"]:
        is_summary_time, label = True, "HK_CLOSE"

    if is_summary_time:
        p_list = [f"{it['name']}:{all_data.get(it['symbol'],{}).get('regularMarketChangePercent',0)*100:.1f}%" for it in watchlist]
        ans = ai_decision_engine(" | ".join(p_list), {}, "", is_summary=True)
        bark_push(f"📊 CIO 收盘总结 [{label}]", ans)
        state["summary_done"].append(label)
        save_state(state)

    # --- 异动 & 各市场开盘前哨逻辑 ---
    # 定义开盘前扫描窗口 (A/H早盘, A午盘, 美股盘前)
    is_opening_scan = (830 <= hm_cn <= 930) or (1240 <= hm_cn <= 1300) or (2030 <= hm_cn <= 2135)
    
    pending_alerts = []
    for item in watchlist:
        s, name = item['symbol'], item['name']
        data = all_data.get(s)
        if not isinstance(data, dict): continue
        
        price = data.get("regularMarketPrice", 0)
        pct = (price - data.get("regularMarketPreviousClose", price)) / data.get("regularMarketPreviousClose", 1) * 100
        news_content, current_hash = fetch_enhanced_context(s, name)
        
        # 触发逻辑：1.级别提升 2.新闻更新 3.开盘前窗口有新逻辑
        level = 2 if abs(pct) >= 6.0 else (1 if abs(pct) >= 3.0 else 0)
        news_updated = (current_hash != state["last_news_hash"].get(s, "")) and (current_hash != "no_news")
        
        if news_updated or (level > state["alerts"].get(s, 0)) or (abs(pct - state["last_pct"].get(s, 0)) >= VOLATILITY_LOCK):
            # 在开盘前窗口，只要有新资讯，强制推送，无论涨跌
            if news_updated or level > 0:
                p_meta = {'price': price, 'pct': pct, 'high52': data.get("fiftyTwoWeekHigh"), 'low52': data.get("fiftyTwoWeekLow")}
                analysis = ai_decision_engine(f"{name}({s})", p_meta, news_content, is_opening=is_opening_scan)
                pending_alerts.append(f"🛡️ CIO策略 [{name} {pct:.2f}%]\n{analysis}")
                
                state["alerts"][s], state["last_pct"][s], state["last_news_hash"][s] = level, pct, current_hash

    if pending_alerts:
        bark_push(f"📊 CIO 深度内参", "\n\n".join(pending_alerts))
    save_state(state)

if __name__ == "__main__":
    main()
