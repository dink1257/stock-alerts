import requests, os, csv, pytz, json
from datetime import datetime
from yahooquery import Ticker

# --- 环境配置 ---
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY") 
WATCHLIST_PATH = "data/watchlist.csv"
STATE_PATH = "data/alert_state.json"

def ai_decision(symbol, name, p_meta, news, m_context, is_forced):
    """【总监级核心指令集】"""
    
    # 注入用户的所有具体监控要求
    prompt = f"""
### 角色定位
你是一位【资深买方投资总监】。你的研判直接影响数亿资金的决策，必须冷静、毒辣、穿透表象。

### 当前市场与品种数据
- 市场运行状态：{m_context}
- 监控标约：{name} ({symbol})
- 现价：{p_meta['price']} | 今日波动：{p_meta['pct']:+.2f}%
- 扫描模式：{'【定时强制全量扫描】' if is_forced else '【实时异动触发】'}

### 核心审计任务（必须逐项执行）
1. **身份与视角审计**：结合中英文新闻描述（简洁、完整），点评其对市场或品种的影响。必须从【方向、幅度、持续性（长期还是短期）】三维研判，并给出明确操作建议：【买入、卖出、持仓】。
2. **市场层面审计**：判断品种处于上升、震荡还是下行趋势。识别是板块集体联动(Beta)还是个股特有逻辑(Alpha)。
3. **股东与高管动向审计（硬性要求）**：强制扫描资讯中涉及【前五大股东】及【董监高管】的增减持动向。结合基本面（经营、趋势）判定是“战略性看空”还是“战略性看多”。若无此信息则略过不提。
4. **宏观因子穿透**：审计资讯是否涵盖宏观政策、供求关系、地缘政治、汇率波动(RMB/USD)、流动性等因子。

### 监控分析标准
只有当信息足以引发【品种大幅波动级别】时，才判定为“重要”。

### 飞书推送格式
【盘面情况】：简述指数涨跌，对比前五个交易日成交量有无异常。
【品种归因分析】：异动原因研判（方向、幅度、持续性）。
【操作建议】：结合技术指标与基本面，给出买/卖/持建议及理由。

---
[底层资讯输入]：
{news}
"""
    headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "qwen-max",
        "input": {"messages": [{"role": "user", "content": prompt}]},
        "parameters": {"result_format": "message", "temperature": 0.1, "top_p": 0.5}
    }
    try:
        res = requests.post("https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation", 
                             headers=headers, json=payload, timeout=120)
        return res.json()['output']['choices'][0]['message']['content']
    except: return "⚠️ 研判引擎超时：请检查百炼额度或网络链路。"

def main():
    bj_tz = pytz.timezone("Asia/Shanghai")
    now = datetime.now(bj_tz)
    
    # 强制扫描时间窗判定
    is_morning_forced = (now.hour == 8 and 25 <= now.minute <= 45)
    is_afternoon_forced = (now.hour == 12 and 40 <= now.minute <= 55)
    is_forced = is_morning_forced or is_afternoon_forced
    
    m_context = "当前市场处于2026年2月震荡修复期，需关注美债收益率与汇率波动。"

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
            
            # 品种阈值：外汇1%，其他3%
            threshold = 1.0 if m_type == 'forex' else 3.0
            last_p = state["last_pct"].get(symbol, 0)
            
            # 触发：强制扫描模式 OR 异动达标
            if is_forced or (abs(pct) >= threshold and abs(pct - last_p) >= 0.5):
                query = f"{name} {symbol} shareholder equity policy macro news"
                search_url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&newsCount=10"
                news_res = requests.get(search_url).json()
                news_text = " | ".join([n.get('title','') for n in news_res.get('news', [])])
                
                analysis = ai_decision(symbol, name, {"price":curr, "pct":pct}, news_text, m_context, is_forced)
                
                card = {
                    "msg_type": "interactive",
                    "card": {
                        "header": {"title": {"tag": "plain_text", "content": f"【CIO总监审计】{name} ({pct:+.2f}%)"}, "template": "orange" if is_forced else "blue"},
                        "elements": [{"tag": "markdown", "content": analysis}]
                    }
                }
                requests.post(FEISHU_WEBHOOK, json=card, timeout=15)
                state["last_pct"][symbol] = pct
        except: continue
    
    with open(STATE_PATH, 'w') as f: json.dump(state, f)

if __name__ == "__main__": main()
