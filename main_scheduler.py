"""
Project: Global Macro & Asset Monitor (CIO Edition)
Version: 5.3.8 (Final Framework & Format Recovery)
Focus: 严格五维格式回归、飞书话题置顶、大资金博弈穿透
"""
import requests, os, csv, pytz, json, time, hashlib
from datetime import datetime, timezone
from yahooquery import Ticker

# --- 系统配置 ---
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
STATE_CACHE_PATH = "data/alert_state.json"
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
VOLATILITY_LOCK = 1.0 

def feishu_push(title, content):
    """适配话题模式：确保新研判话题在飞书群最顶端显示"""
    if not FEISHU_WEBHOOK: return
    now_dt = datetime.now(pytz.timezone("Asia/Shanghai"))
    time_tag = now_dt.strftime('%H:%M:%S')
    
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"[{time_tag}] {title}"},
                "template": "blue" if "异动" in title else "orange"
            },
            "elements": [
                {"tag": "markdown", "content": content},
                {"tag": "hr"},
                {
                    "tag": "note",
                    "elements": [{"tag": "plain_text", "content": f"📅 {now_dt.strftime('%Y-%m-%d %H:%M:%S')} | 投资总监内参"}]
                }
            ]
        }
    }
    try:
        requests.post(FEISHU_WEBHOOK, json=payload, timeout=15)
    except: pass

def ai_decision_engine(symbol_info, price_meta, news_text, is_summary=False):
    """【硬核回归】严格锁定 CIO 五维研判格式"""
    if not is_summary:
        # 这里是您最核心的定型要求，已全部找回并加固
        prompt = f"""
你现在是顶级买方投资总监。请针对标的【{symbol_info}】进行穿透。
现价: {price_meta.get('price')} | 涨跌幅: {price_meta.get('pct', 0):.2f}% | 资讯: {news_text}

请严格按此格式输出，确保150字内，每点之间换行：
1.【逻辑定性】短期博弈/长期重构/随机噪音？（必须分析是否有国家队/大资金迹象）
2.【实质影响】量化描述对业务或市场韧性（承接力）的实损或利好。
3.【持仓预警】明确指出逻辑证伪点（如监管转向、压盘力度异常）。
4.【交易窗口】针对当前盘口现象，给出具体的撤退/抄底/对冲建议。
5.【深度潜流】基于第一性原理，推演主力意图与未露出的监管底牌。
"""
    else:
        prompt = f"以投资总监视角，对今日自选股全盘博弈进行100字内复盘：{symbol_info}"

    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "qwen-plus", "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        return r.json()['output']['text']
    except: return "CIO逻辑引擎暂时掉线，请关注盘面承接力。"

def fetch_enhanced_context(symbol, name):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        query = f"{name} {symbol.split('.')[0]} 异动 护盘 盘口 政策"
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&newsCount=5"
        r = requests.get(url, headers=headers, timeout=5)
        news_items = r.json().get("news", [])
        raw_text, news_list = "", []
        for n in news_items:
            t = n.get('title', '')
            news_list.append(f"• {t}")
            raw_text += t
        content = "\n".join(news_list) if news_list else "盘面出现异常大资金博弈，暂无即时公开资讯。"
        n_hash = hashlib.md5(raw_text.encode()).hexdigest() if raw_text else "no_news"
        return content, n_hash
    except: return "资讯流抓取超时。", "err_hash"

def main():
    now_utc = datetime.now(timezone.utc)
    cn_now = now_utc.astimezone(pytz.timezone("Asia/Shanghai"))
    hm_cn = int(cn_now.strftime('%H%M'))

    if os.path.exists(STATE_CACHE_PATH):
        with open(STATE_CACHE_PATH, "r") as f: state = json.load(f)
    else: state = {"date": "", "alerts": {}, "last_pct": {}, "last_news_hash": {}, "summary_done": []}

    today_str = cn_now.strftime('%Y%m%d')
    if state.get("date") != today_str:
        state = {"date": today_str, "alerts": {}, "last_pct": {}, "last_news_hash": {}, "summary_done": []}

    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f: watchlist = list(csv.DictReader(f))
    
    symbols = [i['symbol'] for i in watchlist]
    try:
        te = Ticker(symbols, asynchronous=True, formatted=False)
        all_data = te.price
    except: return

    # --- 收盘复盘 ---
    if (1510 <= hm_cn <= 1525 and "CN" not in state["summary_done"]) or \
       (1610 <= hm_cn <= 1625 and "HK" not in state["summary_done"]):
        p_list = [f"{it['name']}:{all_data.get(it['symbol'],{}).get('regularMarketChangePercent',0)*100:.1f}%" for it in watchlist]
        analysis = ai_decision_engine(" | ".join(p_list), {}, "", is_summary=True)
        feishu_push("全天博弈总结复盘", analysis)
        state["summary_done"].append("CN" if hm_cn < 1600 else "HK")
        with open(STATE_CACHE_PATH, "w") as f: json.dump(state, f)
        return

    # --- 异动监控 ---
    for item in watchlist:
        s, name = item['symbol'], item['name']
        data = all_data.get(s)
        if not isinstance(data, dict): continue
        
        price = data.get("regularMarketPrice", 0)
        pct = (price - data.get("regularMarketPreviousClose", price)) / data.get("regularMarketPreviousClose", 1) * 100
        news_content, current_hash = fetch_enhanced_context(s, name)
        
        # 捕捉国家队压盘（ETF 0.5% 灵敏度，普通标的 1.0%）
        threshold = 0.5 if "ETF" in name else 1.0 
        news_updated = (current_hash != state["last_news_hash"].get(s, "")) and (current_hash != "no_news")
        price_moved = abs(pct - state["last_pct"].get(s, 0)) >= threshold

        if news_updated or price_moved:
            analysis = ai_decision_engine(f"{name}({s})", {'price': price, 'pct': pct}, news_content)
            feishu_push(f"异动研判: {name} ({pct:.2f}%)", analysis) # 独立话题发送，确保置顶
            state["last_pct"][s], state["last_news_hash"][s] = pct, current_hash

    with open(STATE_CACHE_PATH, "w") as f: json.dump(state, f)

if __name__ == "__main__":
    main()
