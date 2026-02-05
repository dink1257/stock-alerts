import requests, os, csv, pytz, json
from datetime import datetime
from yahooquery import Ticker

# --- 环境变量配置 ---
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY") 
WATCHLIST_PATH = "data/watchlist.csv"
STATE_PATH = "data/alert_state.json"

def get_market_context():
    """自动化获取大盘宏观锚点数据，确保盘面研判不偏航"""
    try:
        tickers = Ticker("000001.SS ^HSI")
        sh = tickers.price['000001.SS']
        hs = tickers.price['^HSI']
        sh_pct = sh.get('regularMarketChangePercent', 0) * 100
        hs_pct = hs.get('regularMarketChangePercent', 0) * 100
        
        context = (
            f"上证指数: {sh.get('regularMarketPrice')} ({sh_pct:+.2f}%); "
            f"恒生指数: {hs.get('regularMarketPrice')} ({hs_pct:+.2f}%); "
            "当前处于2026年2月市场环境。"
        )
        return context
    except:
        return "大盘数据获取失败，默认按震荡市对待。"

def ai_decision(symbol, name, p_meta, news, m_context, is_forced):
    """【总监级决策引擎 V6.7.8】精益研判版"""
    prompt = f"""
### 角色定位
你是一位资深买方投资总监。你的审计报告必须结构严谨，严禁偏差，拒绝空话。

### 核心审计数据
- 宏观盘面参考：{m_context}
- 异动目标标的：{name} ({symbol}) | 实时波动：{p_meta['pct']:+.2f}%
- 模式：{'【定时强制扫描】' if is_forced else '【实时异动审计】'}

### 严格审计指令（三段式）

1. **【盘面情况审计】**：
   - 必须点评上证指数/恒生指数走势。
   - 审计成交量（对比前五日均值）判断是放量还是缩量，定性市场情绪。

2. **【品种归因审计】**（核心）：
   - 仅针对标的 {name} ({symbol}) 本次 {p_meta['pct']}% 的波动进行归因。
   - **股权审计**：审计前五大股东、董监高近期是否有增减持、质押、冻结等意志体现。若无明确信息，此项直接略过。
   - **基本面审计**：审计该品种行业政策变动、供求关系、个股经营订单及财报预期。若无明确信息，此项直接略过。
   - **定性分析**：判断本次波动是跟随大盘(Beta)还是独立的个股逻辑(Alpha)。

3. **【操作建议】**：
   - 给出明确的【买入/卖出/持仓】建议。
   - 明确指出波动的方向、幅度预判及持续性。

---
[底层资讯输入]：
{news}
"""
    headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "qwen-max",
        "input": {"messages": [{"role": "user", "content": prompt}]},
        "parameters": {"result_format": "message", "temperature": 0.1}
    }
    
    try:
        res = requests.post("https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation", headers=headers, json=payload, timeout=120)
        data = res.json()
        content = data['output']['choices'][0]['message']['content']
        usage = data.get('usage', {})
        total_tokens = usage.get('total_tokens', 0)
        cost = (total_tokens / 1000) * 0.12
        return content + f"\n\n---\n💰 **[成本审计]**：消耗 {total_tokens} Tokens (约 ¥{cost:.4f})"
    except Exception as e:
        return f"⚠️ 研判异常: {str(e)}"

def main():
    bj_tz = pytz.timezone("Asia/Shanghai")
    now = datetime.now(bj_tz)
    
    # 强制扫描时段
    is_forced = (now.hour == 8 and 25 <= now.minute <= 59) or (now.hour == 9 and 0 <= now.minute <= 15) or \
                (now.hour == 12 and 40 <= now.minute <= 59) or (now.hour == 13 and 0 <= now.minute <= 15)
    
    print(f"⏰ 北京时间: {now.strftime('%H:%M:%S')} | 强制模式: {is_forced}")
    m_context = get_market_context()

    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, 'r', encoding='utf-8') as f:
        stocks = list(csv.DictReader(f))
    try:
        with open(STATE_PATH, 'r') as f: state = json.load(f)
    except: state = {"last_pct": {}}

    for s in stocks:
        symbol, name = s['symbol'], s['name']
        m_type = s.get('type', 'stock')
        try:
            tk = Ticker(symbol)
            p = tk.price[symbol]
            curr, prev = p.get('regularMarketPrice'), p.get('regularMarketPreviousClose')
            if not curr or not prev: continue
            pct = (curr - prev) / prev * 100
            
            threshold = 1.0 if m_type == 'forex' else 3.0
            last_p = state["last_pct"].get(symbol, 0)
            
            if is_forced or (abs(pct) >= threshold and abs(pct - last_p) >= 0.5):
                print(f"🚀 正在研判: {name} ({pct:+.2f}%)")
                query = f"{name} {symbol} 股东增减持 订单 政策 研报"
                search_url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&newsCount=10"
                news_data = requests.get(search_url).json()
                news_text = " | ".join([n.get('title','') for n in news_data.get('news', [])])
                
                analysis = ai_decision(symbol, name, {"price":curr, "pct":pct}, news_text, m_context, is_forced)
                
                card = {
                    "msg_type": "interactive",
                    "card": {
                        "header": {
                            "title": {"tag": "plain_text", "content": f"【CIO审计】{name} ({pct:+.2f}%)"},
                            "template": "orange" if is_forced else "blue"
                        },
                        "elements": [{"tag": "markdown", "content": analysis}]
                    }
                }
                requests.post(FEISHU_WEBHOOK, json=card, timeout=15)
                state["last_pct"][symbol] = pct
        except: continue
    
    with open(STATE_PATH, 'w') as f: json.dump(state, f)

if __name__ == "__main__": main()
