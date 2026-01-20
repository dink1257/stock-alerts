"""
Project: Global Macro & Asset Monitor (CIO Edition)
Version: 5.3.3 (Index Anchor & Market Context)
Focus: 指数/个股双重研判、全时段开盘前哨、格式绝对锁定
"""
import requests, os, csv, pytz, json, time, hashlib
from datetime import datetime, timezone
from yahooquery import Ticker

# --- 系统配置 ---
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
STATE_CACHE_PATH = "data/alert_state.json"
BARK_URL = os.getenv("BARK_URL")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
VOLATILITY_LOCK = 1.5  # 指数波动通常较小，将锁设为1.5%以提高指数敏感度

def bark_push(title, body):
    if not BARK_URL: return
    try:
        url = f"{BARK_URL.rstrip('/')}/"
        payload = {"title": title, "body": body, "group": "CIO_Intelligence", "sound": "anticipate"}
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
    """深度扫描：指数关注宏观/政策，个股关注业务/监管"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        is_index = symbol.startswith('^') or symbol.endswith('.SS') or symbol.endswith('.SZ')
        if is_index:
            query = f"{name} 宏观政策 货币环境 市场走势 传闻"
        else:
            query = f"{name} {symbol.split('.')[0]} 监管 保证金 政策 异动"
            
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&newsCount=5"
        r = requests.get(url, headers=headers, timeout=8)
        news_items = r.json().get("news", [])
        
        raw_text, news_list = "", []
        for n in news_items:
            t = n.get('title', '')
            news_list.append(f"· {t}")
            raw_text += t
        
        content = "\n".join(news_list) if news_list else "暂无新增逻辑变量。"
        n_hash = hashlib.md5(raw_text.encode()).hexdigest() if raw_text else "no_news"
        return content, n_hash
    except:
        return "资讯流抓取延迟。", "err_hash"

def ai_decision_engine(symbol_info, price_meta, news_text, is_summary=False, is_opening=False):
    """严格锁定 CIO 五维格式输出，动态适配指数与个股逻辑"""
    is_index = any(x in symbol_info for x in ['指数', '成指', '^', 'Index'])
    
    if not is_summary:
        tag = "【开盘哨兵】" if is_opening else "【深度研判】"
        target_type = "指数（大盘环境）" if is_index else "个股（标的基本面）"
        
        prompt = f"""
你现在是顶级买方投资总监。请针对{tag} {target_type}【{symbol_info}】进行穿透研判。
现价: {price_meta.get('price')} | 涨跌幅: {price_meta.get('pct', 0):.2f}% | 资讯: {news_text}

请严格按此格式输出（150字内）：
1.【逻辑定性】短期博弈/长期重构/随机噪音？(指数请分析宏观情绪)
2.【实质影响】{"对个股业务与财务的实损" if not is_index else "对全天市场赚钱效应与板块流动性的影响"}。
3.【持仓预警】若触及逻辑证伪点（如系统性风险、政策限制）请明确预警。
4.【交易窗口】给出具体的交易建议（如：个股对冲/指数看涨期权布局/减仓观望）。
5.【深度潜流】基于第一性原理，推演信息背后未露出的监管意图或宏观转向。
"""
    else:
        prompt = f"""你现在是买方总监。请对全天表现进行【收盘脱水点评】：
清单: {symbol_info}
要求：1.总结主线涨跌质量。2.识别最异常标的及其底层诱因。3.给出次日策略建议。字数100字内。"""

    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "qwen-plus", "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=payload, timeout=25)
        return r.json()['output']['text']
    except: return "CIO决策流超时，请根据盘面自主判断。"

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

    # --- 收盘总结逻辑 ---
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

    # --- 异动 & 开盘前哨 (核心增强) ---
    is_opening_scan = (830 <= hm_cn <= 930) or (1240 <= hm_cn <= 1300) or (2030 <= hm_cn <= 2135)
    
    pending_alerts = []
    for item in watchlist:
        s, name = item['symbol'], item['name']
        data = all_data.get(s)
        if not isinstance(data, dict): continue
        
        price = data.get("regularMarketPrice", 0)
        pct = (price - data.get("regularMarketPreviousClose", price)) / data.get("regularMarketPreviousClose", 1) * 100
        news_content, current_hash = fetch_enhanced_context(s, name)
        
        # 判定触发：新闻哈希变化为最高优先级
        news_updated = (current_hash != state["last_news_hash"].get(s, "")) and (current_hash != "no_news")
        
        # 指数波动锁更小，个股保持原有锁
        is_idx = any(x in name for x in ['指数', '成指', '^'])
        dynamic_lock = 1.0 if is_idx else VOLATILITY_LOCK
        
        level = 2 if abs(pct) >= 6.0 else (1 if abs(pct) >= 3.0 else 0)
        
        triggered = news_updated or (level > state["alerts"].get(s, 0)) or (abs(pct - state["last_pct"].get(s, 0)) >= dynamic_lock)

        if triggered:
            # 在开盘前窗口或有实质新闻时，即便波动不大也推送
            if news_updated or level > 0 or is_opening_scan:
                p_meta = {'price': price, 'pct': pct, 'high52': data.get("fiftyTwoWeekHigh"), 'low52': data.get("fiftyTwoWeekLow")}
                analysis = ai_decision_engine(f"{name}({s})", p_meta, news_content, is_opening=is_opening_scan)
                pending_alerts.append(f"🛡️ CIO策略 [{name} {pct:.2f}%]\n{analysis}")
                
                state["alerts"][s], state["last_pct"][s], state["last_news_hash"][s] = level, pct, current_hash

    if pending_alerts:
        bark_push(f"📊 CIO 深度内参", "\n\n".join(pending_alerts))
    save_state(state)

if __name__ == "__main__":
    main()
