import requests, os, csv, pytz, json
from datetime import datetime
from yahooquery import Ticker

# --- 系统配置 ---
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
STATE_PATH = "data/alert_state.json"

def ai_decision(symbol, name, p_meta, news):
    """行业+股权双穿透研判逻辑"""
    prompt = f"""
你是买方投研总监。请对【{name} ({symbol})】进行【行业+股权】双穿透研判。
现价: {p_meta['price']} | 涨跌: {p_meta['pct']:+.2f}%

资讯流(含行业动向、前五大股东、高管信息): {news}

请严格按此结构汇报（有事说事，无事显“无”）：
1.【行业动向审计】: 扫描所属行业政策/景气度。明确波动是否受行业共性驱动。
2.【股权异动审计】: 核实前五大名股东及高管(董监高)增减持。
3.【实质影响】: 定性：是行业逻辑反转、个股利空、还是正常轮动。
4.【日线交易窗口】: 给出指令(动词+点位)。
极简专业，严禁废话。
"""
    headers = {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}", 
        "Content-Type": "application/json",
        "X-DashScope-Client": "python-requests"
    }
    
    payload = {
        "model": "qwen-max", 
        "input": {"messages": [{"role": "user", "content": prompt}]},
        "parameters": {"result_format": "message"}
    }
    
    try:
        # 核心修复：提升超时时间至 120s，应对深度审计时的生成耗时
        res = requests.post(
            "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation", 
            headers=headers, 
            json=payload, 
            timeout=120 
        )
        
        if res.status_code != 200:
            return f"API 状态异常: {res.status_code} - {res.text[:100]}"
            
        return res.json()['output']['choices'][0]['message']['content']
    except requests.exceptions.Timeout:
        return "AI研判超时：生成耗时过长，请检查网络或精简关键词。"
    except Exception as e:
        return f"系统连接异常: {str(e)}"

def main():
    bj_tz = pytz.timezone("Asia/Shanghai")
    now = datetime.now(bj_tz)
    time_str = now.strftime('%H:%M')
    is_morning = (now.hour == 8 and 20 <= now.minute <= 45)
    
    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, 'r', encoding='utf-8') as f: 
        stocks = list(csv.DictReader(f))
    try:
        with open(STATE_PATH, 'r') as f: state = json.load(f)
    except: state = {"last_pct": {}}

    for s in stocks:
        symbol, name = s['symbol'], s['name']
        industry = s.get('industry', '行业')
        try:
            tk = Ticker(symbol)
            p = tk.price[symbol]
            curr, prev = p.get('regularMarketPrice'), p.get('regularMarketPreviousClose')
            pct = (curr - prev) / prev * 100
            
            last_p = state["last_pct"].get(symbol, 0)
            if is_morning or (abs(pct) >= 3.0 and abs(pct - last_p) >= 1.0):
                query = f"{name} {industry} 行业政策 前五大股东变动 高管增减持"
                news_res = requests.get(f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&newsCount=8").json()
                news = " | ".join([n.get('title','') for n in news_res.get('news', [])])
                
                analysis = ai_decision(symbol, name, {"price":curr, "pct":pct}, news)
                
                # 标题直读
                sign = "涨" if pct >= 0 else "跌"
                title = f"【{time_str}：盘中{sign}{abs(pct):.2f}%】{name}"
                if is_morning: title = f"【{time_str}：晨间全量审计】{name}"
                
                # 涨红跌绿
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
