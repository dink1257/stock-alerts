"""
Project: Global Macro & Asset Monitor (CIO Edition)
Version: 5.3.5 (Push Recovery & Microstructure)
"""
import requests, os, csv, pytz, json, time, hashlib
from datetime import datetime, timezone
from yahooquery import Ticker

# --- 系统配置 ---
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
STATE_CACHE_PATH = "data/alert_state.json"
BARK_URL = os.getenv("BARK_URL")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
VOLATILITY_LOCK = 1.0  # 降低锁定阈值，防止遗漏低波动下的主力博弈

def bark_push(title, body):
    """增加更稳健的消息发送机制"""
    if not BARK_URL: return
    try:
        # 确保 URL 格式正确，并增加更长超时
        url = BARK_URL.rstrip('/')
        payload = {
            "title": title, 
            "body": body, 
            "group": "CIO_Intelligence", 
            "sound": "minuet",
            "isArchive": "1"  # 即使手机没联网，上线后也能看到历史
        }
        r = requests.post(url, json=payload, timeout=15)
        print(f"Push Status: {r.status_code}") # 在 GitHub Log 中打印状态以便排查
    except Exception as e:
        print(f"Push Failed: {e}")

def fetch_enhanced_context(symbol, name):
    """增加异常捕获，防止因为某个标的新闻抓不到而卡死全局"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        query = f"{name} {symbol.split('.')[0]} 异动 护盘 盘口"
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&newsCount=5"
        r = requests.get(url, headers=headers, timeout=5) # 缩短单次超时
        news_items = r.json().get("news", [])
        
        raw_text, news_list = "", []
        for n in news_items:
            t = n.get('title', '')
            news_list.append(f"· {t}")
            raw_text += t
        
        content = "\n".join(news_list) if news_list else "盘面存在非自然波动，暂无即时分析。"
        n_hash = hashlib.md5(raw_text.encode()).hexdigest() if raw_text else "no_news"
        return content, n_hash
    except:
        return "资讯抓取受限，仅依据盘面价格及成交量推演。", "err_hash"

def ai_decision_engine(symbol_info, price_meta, news_text, is_summary=False):
    """严格锁定 5 点研判格式"""
    if not is_summary:
        prompt = f"""
你现在是顶级买方投资总监。请针对标的【{symbol_info}】进行穿透。
现价: {price_meta.get('price')} | 涨跌幅: {price_meta.get('pct', 0):.2f}% | 资讯: {news_text}

请严格按此格式输出（150字内）：
1.【逻辑定性】短期异动原因？（分析是否有“国家队”或大资金迹象）
2.【实质影响】分析承接力来源及其背后的筹码交换逻辑。
3.【持仓预警】若触及逻辑证伪点请明确预警。
4.【交易窗口】针对压盘不崩等盘口现象给出操作建议。
5.【深度潜流】推演背后的主力意图与监管意图。
"""
    else:
        prompt = f"请以买方总监视角，对今日自选股全盘博弈情况进行100字内的核心总结：{symbol_info}"

    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "qwen-plus", "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        return r.json()['output']['text']
    except:
        return "CIO逻辑引擎响应缓慢。"

def main():
    now_utc = datetime.now(timezone.utc)
    cn_now = now_utc.astimezone(pytz.timezone("Asia/Shanghai"))
    hm_cn = int(cn_now.strftime('%H%M'))

    # 初始化状态
    if os.path.exists(STATE_CACHE_PATH):
        with open(STATE_CACHE_PATH, "r") as f:
            state = json.load(f)
    else:
        state = {"date": "", "alerts": {}, "last_pct": {}, "last_news_hash": {}, "summary_done": []}

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

    # --- 收盘复盘逻辑 (确保每天必定有一条推送) ---
    is_summary_time = False
    if (1510 <= hm_cn <= 1525 and "CN" not in state["summary_done"]) or \
       (1610 <= hm_cn <= 1625 and "HK" not in state["summary_done"]):
        is_summary_time = True

    if is_summary_time:
        p_list = [f"{it['name']}:{all_data.get(it['symbol'],{}).get('regularMarketChangePercent',0)*100:.1f}%" for it in watchlist]
        analysis = ai_decision_engine(" | ".join(p_list), {}, "", is_summary=True)
        bark_push("📊 CIO 盘后博弈复盘", analysis)
        state["summary_done"].append("CN" if hm_cn < 1600 else "HK")
        with open(STATE_CACHE_PATH, "w") as f: json.dump(state, f)
        return

    # --- 异动实时监控 ---
    pending_alerts = []
    for item in watchlist:
        s, name = item['symbol'], item['name']
        data = all_data.get(s)
        if not isinstance(data, dict): continue
        
        price = data.get("regularMarketPrice", 0)
        pct = (price - data.get("regularMarketPreviousClose", price)) / data.get("regularMarketPreviousClose", 1) * 100
        news_content, current_hash = fetch_enhanced_context(s, name)
        
        # 核心逻辑改进：对 ETF 标的提升灵敏度，捕捉压盘不崩等微观现象
        is_etf = "ETF" in name
        threshold = 0.5 if is_etf else 2.5 
        
        news_updated = (current_hash != state["last_news_hash"].get(s, "")) and (current_hash != "no_news")
        price_moved = abs(pct - state["last_pct"].get(s, 0)) >= threshold

        if news_updated or price_moved:
            p_meta = {'price': price, 'pct': pct}
            analysis = ai_decision_engine(f"{name}({s})", p_meta, news_content)
            pending_alerts.append(f"🛡️ CIO策略 [{name} {pct:.2f}%]\n{analysis}")
            state["last_pct"][s], state["last_news_hash"][s] = pct, current_hash

    if pending_alerts:
        bark_push(f"📊 CIO 深度内参", "\n\n".join(pending_alerts))
    
    with open(STATE_CACHE_PATH, "w") as f:
        json.dump(state, f)

if __name__ == "__main__":
    main()
