import requests, os, csv, pytz, json, time, hashlib
from datetime import datetime
from yahooquery import Ticker

# --- 1. 配置与环境变量 ---
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
STATE_CACHE_PATH = "data/alert_state.json"

def feishu_push(title, content):
    if not FEISHU_WEBHOOK: return
    now_dt = datetime.now(pytz.timezone("Asia/Shanghai"))
    color = "orange" if "异动" in title else "blue"
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"[{now_dt.strftime('%H:%M')}] {title}"},
                "template": color
            },
            "elements": [{"tag": "markdown", "content": content}]
        }
    }
    try:
        requests.post(FEISHU_WEBHOOK, json=payload, timeout=20)
    except: pass

def fetch_enhanced_context(symbol, name):
    """针对减持、外资流向的深度搜索引擎"""
    try:
        # 针对三花智控股价教训，强化减持与北向资金搜索
        search_query = f"{name} {symbol.split('.')[0]} 减持 股份变动 北向资金 持仓 CCASS 研报"
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={search_query}&newsCount=8"
        headers = {'User-Agent': 'Mozilla/5.0'}
        r = requests.get(url, headers=headers, timeout=15)
        news_items = r.json().get("news", [])
        
        raw_text, news_list = "", []
        for n in news_items:
            title = n.get('title', '')
            # 关键词高亮
            if any(k in title for k in ["减持", "卖出", "流出", "股份变动", "警告"]):
                news_list.append(f"🔴 **[重大关联] {title}**")
            else:
                news_list.append(f"• {title}")
            raw_text += title
        
        return "\n".join(news_list) if news_list else "暂无关联基本面资讯。", hashlib.md5(raw_text.encode()).hexdigest()
    except:
        return "资讯抓取超时。", "err"

def ai_decision_engine(symbol, name, price_info, news_text):
    """CIO 五维深度研判指令"""
    if not DASHSCOPE_API_KEY: return "AI Key 未配置。"
    
    prompt = f"""
你现在是顶级买方 CIO。请对【{name} ({symbol})】进行定性分析。
实时价格: {price_info.get('price')} (涨跌幅: {price_info.get('pct'):.2f}%)
搜集资讯: {news_text}

请按格式回复：
1.【逻辑定性】重点穿透是否有大股东减持、外资撤离或基本面恶化。
2.【实质影响】分析该动向对股价中长期韧性的破坏力。
3.【持仓预警】指出关键心理位或技术性溃败点。
4.【交易窗口】给出具体的避险、对冲或减速退出建议。
5.【深度潜流】推演该个股异动是否预示行业拐点。
"""
    headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
    data = {
        "model": "qwen-max",
        "input": {"messages": [{"role": "user", "content": prompt}]},
        "parameters": {"result_format": "message"}
    }
    try:
        r = requests.post("https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation", 
                         headers=headers, json=data, timeout=60)
        return r.json()['output']['choices'][0]['message']['content']
    except:
        return "AI 分析引擎暂时离线。"

def main():
    bj_tz = pytz.timezone("Asia/Shanghai")
    now_bj = datetime.now(bj_tz)
    
    # 策略判定：08:26 - 08:45 为早晨强制全量扫描时间
    is_morning_scan = (now_bj.hour == 8 and 20 <= now_bj.minute <= 45)
    intra_day_threshold = 3.0 # 盘中阈值设为 3%
    
    print(f"[{now_bj}] 模式: {'早晨全量扫描' if is_morning_scan else '盘中 3% 监控'}")

    # 读取 Watchlist
    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, 'r') as f:
        reader = csv.DictReader(f)
        stocks = list(reader)

    # 加载状态
    try:
        with open(STATE_CACHE_PATH, 'r') as f: state = json.load(f)
    except: state = {"last_pct": {}}

    for item in stocks:
        symbol, name = item['symbol'], item['name']
        try:
            tk = Ticker(symbol)
            price_data = tk.price[symbol]
            curr_price = price_data.get('regularMarketPrice')
            prev_close = price_data.get('regularMarketPreviousClose')
            change_pct = (curr_price - prev_close) / prev_close * 100
            
            # 触发条件：1. 早晨强制扫描 2. 盘中波动 > 3%
            should_trigger = is_morning_scan or abs(change_pct) >= intra_day_threshold
            
            # 针对重复推送的过滤（仅在非早间模式生效）
            last_p = state["last_pct"].get(symbol, 0)
            if not is_morning_scan and abs(change_pct - last_p) < 1.0: should_trigger = False

            if should_trigger:
                print(f">> 触发研判: {name} ({change_pct:.2f}%)")
                news, n_hash = fetch_enhanced_context(symbol, name)
                analysis = ai_decision_engine(symbol, name, {"price": curr_price, "pct": change_pct}, news)
                
                title = f"【早间 CIO 晨会内参】{name}" if is_morning_scan else f"【盘中异动爆发】{name}"
                feishu_push(title, analysis)
                state["last_pct"][symbol] = change_pct
        except Exception as e:
            print(f"处理 {name} 失败: {e}")

    # 保存状态
    with open(STATE_CACHE_PATH, 'w') as f: json.dump(state, f)

if __name__ == "__main__":
    main()
