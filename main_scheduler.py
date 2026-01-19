"""
Project: Global Macro & Asset Monitor (CIO Edition)
Version: 5.2.7 (Final Decision Engine)
Focus: 零冗余推送、全网深度检索、买方决策逻辑、技术交易窗口
"""
import requests, os, csv, pytz, json, time, hashlib
from datetime import datetime, timezone
from yahooquery import Ticker

# --- 系统配置 ---
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
STATE_CACHE_PATH = "data/alert_state.json"
BARK_URL = os.getenv("BARK_URL")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
VOLATILITY_LOCK = 2.5  # 同一阈值区间内，涨跌幅变动超2.5%才允许再次推送

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
    """强化搜索：针对 A/H/US 市场抓取公告、传闻与异动内参"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        # 搜索策略：简称 + 代码 + 核心关键词
        query = f"{name} {symbol.split('.')[0]} 异动 传闻 公告"
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&newsCount=5"
        r = requests.get(url, headers=headers, timeout=5)
        news_items = r.json().get("news", [])
        
        raw_text = ""
        news_list = []
        for n in news_items:
            t = n.get('title', '')
            news_list.append(f"· {t} (来源:{n.get('publisher','')})")
            raw_text += t
        
        content = "\n".join(news_list) if news_list else "全网暂无公开新增资讯流。"
        n_hash = hashlib.md5(raw_text.encode()).hexdigest() if raw_text else "no_news"
        return content, n_hash
    except:
        return "资讯抓取链路异常", "err_hash"

def ai_decision_engine(symbol_info, price_meta, news_text):
    """注入买方 CIO 5大核心指令集"""
    prompt = f"""
你是一位管理百亿头寸的买方投资总监（CIO）。请针对【{symbol_info}】进行深度研判。

【盘面数据】
现价: {price_meta['price']} | 涨跌幅: {price_meta['pct']:.2f}%
52周区间: {price_meta['low52']} - {price_meta['high52']}
日内波动: {price_meta['range']}

【核心资讯流】
{news_text}

【研判任务】请严格执行：
1.【逻辑定性】判定异动时效：是短期博弈、中长期重构、还是随机噪音？
2.【实质影响】量化描述对业务、财务及行业地位的实损或利好。
3.【持仓预警】逻辑是否松动？若触及逻辑证伪点（如中免收购逻辑变质）请明确预警。
4.【交易窗口】比对技术位，分析趋势状态（超买/超卖/破位），给出高抛、低吸或观望建议。
5.【深度潜流】若无公开资讯，必须基于行业第一性原理推演潜在的未公开风险或隐性机会。

要求：冷静、犀利、结构化。拒绝废话。
"""
    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "qwen-plus", "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        return r.json()['output']['text']
    except: return "CIO逻辑引擎暂时脱机，请根据盘面数据自主决策。"

def main():
    now_utc = datetime.now(timezone.utc)
    cn_now = now_utc.astimezone(pytz.timezone("Asia/Shanghai"))
    time_str = cn_now.strftime('%H:%M:%S')
    
    # 盘后静默逻辑（可选启用，当前依靠熵增逻辑更精准）
    # if 1515 <= int(cn_now.strftime('%H%M')) <= 2100: return

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

        # 1. 资讯采集与哈希化
        news_content, current_hash = fetch_enhanced_context(s, name)
        
        # 2. 状态对比 (拦截冗余核心)
        level = 2 if abs(pct) >= 6.0 else (1 if abs(pct) >= 3.0 else 0)
        last_level = state["alerts"].get(s, 0)
        last_pct = state["last_pct"].get(s, 0.0)
        last_hash = state["last_news_hash"].get(s, "")

        # 判定开关
        news_updated = (current_hash != last_hash) and (current_hash != "no_news")
        level_broken = (level > last_level)
        significant_move = abs(pct - last_pct) >= VOLATILITY_LOCK

        should_push = False
        reason = ""
        if news_updated:
            should_push, reason = True, "【新增关联逻辑】"
        elif level_broken:
            should_push, reason = True, "【阶梯阈值突破】"
        elif level > 0 and significant_move:
            should_push, reason = True, "【区间剧烈波动】"

        if should_push:
            print(f"[{time_str}] {name} 触发研判: {reason}")
            analysis = ai_decision_engine(f"{name}({s})", price_meta, news_content)
            pending_alerts.append(f"🛡️ CIO策略 [{name} {pct:.2f}%]\n🕒 报时: {time_str}\n{analysis}")
            
            # 更新持久化状态
            state["alerts"][s] = level
            state["last_pct"][s] = pct
            state["last_news_hash"][s] = current_hash

    if pending_alerts:
        # 每条推送包含更多信息量，减少分条推送频率
        bark_push(f"📊 CIO 深度内参", "\n\n".join(pending_alerts))

    save_state(state)

if __name__ == "__main__":
    main()
