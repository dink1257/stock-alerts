import requests, os, csv, pytz, json
from datetime import datetime
from yahooquery import Ticker

# --- 核心配置 ---
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY") 
WATCHLIST_PATH = "data/watchlist.csv"
STATE_PATH = "data/alert_state.json"

def ai_decision(symbol, name, p_meta, news, m_context, is_forced):
    """
    【总监级决策引擎 V6.6.5】
    集成功能：深度研判 + 股东审计 + 成本实时监控
    """
    prompt = f"""
### 角色定位
你是一位资深买方投资总监。你的研判必须冷静、穿透表象。

### 当前数据
- 市场状态：{m_context}
- 标的：{name} ({symbol}) | 波动：{p_meta['pct']:+.2f}%
- 模式：{'【定时全量审计】' if is_forced else '【实时异动触发】'}

### 核心任务
1. 身份视角：分析对品种影响（方向、幅度、持续性），给出【买入/卖出/持仓】建议。
2. 股东审计：强制扫描前五大股东及高管增减持动向，定性多空意志。
3. 宏观穿透：关联汇率、地缘及流动性因子。

[输出格式]：
【盘面情况】：成交量与前五日对比。
【品种归因分析】：原因、方向、幅度、持续性。
【操作建议】：明确指令及理由。
---
[资讯输入]：{news}
"""
    headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "qwen-max",
        "input": {"messages": [{"role": "user", "content": prompt}]},
        "parameters": {"result_format": "message", "temperature": 0.1}
    }
    
    try:
        res = requests.post("https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation", 
                             headers=headers, json=payload, timeout=120)
        data = res.json()
        content = data['output']['choices'][0]['message']['content']
        
        # --- 成本自动审计逻辑 ---
        usage = data.get('usage', {})
        total_tokens = usage.get('total_tokens', 0)
        # 按照 Qwen-Max 约 0.12元/千Tokens 计算（仅供参考）
        est_cost = (total_tokens / 1000) * 0.12
        
        cost_report = f"\n\n---\n💰 **[成本审计]**\n本次消耗: {total_tokens} Tokens\n预估成本: ¥{est_cost:.4f}\n*注：免费额度(95.6万)消耗中*"
        
        return content + cost_report
    except Exception as e:
        return f"⚠️ 研判异常: {str(e)}"

def main():
    bj_tz = pytz.timezone("Asia/Shanghai")
    now = datetime.now(bj_tz)
    
    # 强制扫描时间窗
    is_morning_forced = (now.hour == 8 and 25 <= now.minute <= 45)
    is_afternoon_forced = (now.hour == 12 and 40 <= now.minute <= 55)
    is_forced = is_morning_forced or is_afternoon_forced
    
    m_context = "2026年2月震荡修复期，聚焦流动性与股权变动。"

    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, 'r', encoding='utf-8') as f: stocks = list(csv.DictReader(f))
    try:
        with open(STATE_PATH, 'r') as f: state = json.load(f)
    except: state = {"last_pct": {}}

    for s in stocks:
        symbol, name, m_type = s['symbol'], s['name'], s.get('type', 'stock')
        try:
            tk = Ticker(symbol)
            p = tk.price[symbol]
            curr, prev = p.get('regularMarketPrice'), p.get('regularMarketPreviousClose')
            pct = (curr - prev) / prev * 100
            
            threshold = 1.0 if m_type == 'forex' else 3.0
            last_p = state["last_pct"].get(symbol, 0)
            
            if is_forced or (abs(pct) >= threshold and abs(pct - last_p) >= 0.5):
                query = f"{name} {symbol} shareholder equity macro policy"
                search_url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&newsCount=8"
                news_text = " | ".join([n.get('title','') for n in requests.get(search_url).json().get('news', [])])
                
                analysis = ai_decision(symbol, name, {"price":curr, "pct":pct}, news_text, m_context, is_forced)
                
                card = {
                    "msg_type": "interactive",
                    "card": {
                        "header": {"title": {"tag": "plain_text", "content": f"【CIO审计】{name} ({pct:+.2f}%)"}, "template": "orange" if is_forced else "blue"},
                        "elements": [{"tag": "markdown", "content": analysis}]
                    }
                }
                requests.post(FEISHU_WEBHOOK, json=card, timeout=15)
                state["last_pct"][symbol] = pct
        except: continue
    
    with open(STATE_PATH, 'w') as f: json.dump(state, f)

if __name__ == "__main__": main()            
