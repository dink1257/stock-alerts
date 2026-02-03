import requests, os, csv, pytz, json
from datetime import datetime
from yahooquery import Ticker

# --- 配置 ---
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
STATE_PATH = "data/alert_state.json"

def ai_decision(symbol, name, p_meta, news):
    prompt = f"""
你是买方投研总监。请对【{name} ({symbol})】进行【行业+股权】双穿透研判。
现价: {p_meta['price']} | 涨跌: {p_meta['pct']:+.2f}%

资讯流(含行业动向): {news}

请严格按此结构汇报（有事说事，无事显“无”）：
1.【行业动向审计】: 扫描行业政策/景气度拐点。明确波动是否受行业共性驱动。
2.【股权异动审计】: 核实前五大名股东及高管(董监高)增减持/质押。无则显“无”。
3.【实质影响】: 直接定性：是行业逻辑反转、个股利空、还是正常轮动。
4.【日线交易窗口】: 给出具体指令(动词+点位)。结合行业给出：【顺势持有】/【逆势避险】/【企稳吸纳】。
严禁废话，极简且专业。
"""
    headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "qwen-max", "input": {"messages": [{"role": "user", "content": prompt}]}}
    try:
        res = requests.post("https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation", headers=headers, json=payload, timeout=60)
        return res.json()['output']['choices'][0]['message']['content']
    except: return "AI研判服务超时。"

def main():
    bj_tz = pytz.timezone("Asia/Shanghai")
    now = datetime.now(bj_tz)
    time_str = now.strftime('%H:%M')
    is_morning = (now.hour == 8 and 20 <= now.minute <= 45)
    
    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, 'r') as f: stocks = list(csv.DictReader(f))
    try:
        with open(STATE_PATH, 'r') as f: state = json.load(f)
    except: state = {"last_pct": {}}

    for s in stocks:
        symbol, name = s['symbol'], s['name']
        industry_hint = s.get('industry', '所属行业')
        try:
            tk = Ticker(symbol)
            p = tk.price[symbol]
            curr, prev = p.get('regularMarketPrice'), p.get('regularMarketPreviousClose')
            pct = (curr - prev) / prev * 100
            
            last_p = state["last_pct"].get(symbol, 0)
            if is_morning or (abs(pct) >= 3.0 and abs(pct - last_p) >= 1.0):
                # 穿透搜索：股东+高管+行业
                query = f"{name} {industry_hint} 行业政策 景气度 前五大股东变动 高管增减持"
                news_res = requests.get(f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&newsCount=8", headers={'User-Agent':'Mozilla/5.0'}).json()
                news = " | ".join([n.get('title','') for n in news_res.get('news', [])])
                
                analysis = ai_decision(symbol, name, {"price":curr, "pct":pct}, news)
                sign = "涨" if pct > 0 else "跌"
                # 标题直达本质
                title = f"【{time_str}：盘中{sign}{abs(pct):.2f}%】{name}"
                if is_morning: title = f"【{time_str}：晨间全量审计】{name}"
                
                # 修正颜色逻辑：红涨 (template: red), 绿跌 (template: green)
                card_color = "red" if pct >= 0 else "green"
                
                card = {
                    "msg_type": "interactive",
                    "card": {
                        "header": {"title": {"tag": "plain_text", "content": title}, "template": card_color},
                        "elements": [{"tag": "markdown", "content": analysis}]
                    }
                }
                requests.post(FEISHU_WEBHOOK, json=card, timeout=15)
                state["last_pct"][symbol] = pct
        except: continue
    
    with open(STATE_PATH, 'w') as f: json.dump(state, f)

if __name__ == "__main__": main()
