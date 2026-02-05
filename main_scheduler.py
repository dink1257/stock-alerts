import requests, os, csv, pytz, json
from datetime import datetime
from yahooquery import Ticker

# --- 核心环境变量 ---
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY") 
WATCHLIST_PATH = "data/watchlist.csv"
STATE_PATH = "data/alert_state.json"

def get_market_context():
    """【要求响应：大盘锚点强制】自动化获取指数数据，确保分析不偏航"""
    try:
        tickers = Ticker("000001.SS ^HSI")
        sh = tickers.price['000001.SS']
        hs = tickers.price['^HSI']
        sh_pct = sh.get('regularMarketChangePercent', 0) * 100
        hs_pct = hs.get('regularMarketChangePercent', 0) * 100
        return f"上证指数: {sh.get('regularMarketPrice')} ({sh_pct:+.2f}%); 恒生指数: {hs.get('regularMarketPrice')} ({hs_pct:+.2f}%); 市场处于2026年2月交易窗口。"
    except:
        return "大盘数据获取失败，默认维持震荡市研判。"

def ai_decision(symbol, name, p_meta, news, m_context, is_forced):
    """【要求响应：身份隔离+无信息则略】深度研判引擎"""
    prompt = f"""
### 角色定位
你是一位资深买方投资总监。你的研判报告必须结构严谨，严禁偏差，拒绝空话。

### 核心审计数据
- 宏观盘面参考：{m_context}
- 目标标的：{name} ({symbol}) | 实时波动：{p_meta['pct']:+.2f}%
- 运行模式：{'【定时全量扫描】' if is_forced else '【异动触发审计】'}

### 严格审计指令
1. **【盘面情况审计】**：
   - 必须点评上证指数/恒生指数走势。
   - 审计成交量（对比前五日均值）判断是放量还是缩量，以此定性全场情绪。

2. **【品种归因审计】**（核心）：
   - 仅针对标的 {name} ({symbol}) 本次 {p_meta['pct']}% 的波动进行归因。
   - **股权审计**：审计前五大股东、董监高近期是否有增减持、质押、冻结等意志体现。若无实质信息，此项直接略过。
   - **基本面审计**：审计该品种行业政策变动、个股经营订单及财报预期。若无实质信息，此项直接略过。
   - **逻辑隔离**：必须明确判断本次波动是跟随大盘(Beta)还是个股独立逻辑(Alpha)。

3. **【操作建议】**：
   - 给出明确【买入/卖出/持仓】建议。
   - 明确指出波动的方向、幅度预判及持续性（脉冲或趋势）。

---
[资讯输入]：{news}
"""
    headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "qwen-max", "input": {"messages": [{"role": "user", "content": prompt}]}, "parameters": {"result_format": "message", "temperature": 0.1}}
    
    try:
        res = requests.post("https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation", headers=headers, json=payload, timeout=120)
        data = res.json()
        content = data['output']['choices'][0]['message']['content']
        usage = data.get('usage', {})
        total = usage.get('total_tokens', 0)
        cost = (total / 1000) * 0.12
        # 【要求响应：成本审计】
        return content + f"\n\n---\n💰 **[成本审计]**：消耗 {total} Tokens (约 ¥{cost:.4f})"
    except Exception as e:
        return f"⚠️ 研判异常: {str(e)}"

def main():
    bj_tz = pytz.timezone("Asia/Shanghai")
    now = datetime.now(bj_tz)
    
    # 强制扫描时段判定
    is_forced = (now.hour == 8 and 25 <= now.minute <= 59) or (now.hour == 9 and 0 <= now.minute <= 15) or \
                (now.hour == 12 and 40 <= now.minute <= 59) or (now.hour == 13 and 0 <= now.minute <= 15)
    
    m_context = get_market_context()

    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, 'r', encoding='utf-8') as f:
        stocks = list(csv.DictReader(f))
    try:
        with open(STATE_PATH, 'r') as f: state = json.load(f)
    except: state = {"last_triggered_pct": {}}

    for s in stocks:
        symbol, name = s['symbol'], s['name']
        m_type = s.get('type', 'stock')
        try:
            tk = Ticker(symbol)
            p = tk.price[symbol]
            curr, prev = p.get('regularMarketPrice'), p.get('regularMarketPreviousClose')
            if not curr or not prev: continue
            pct = (curr - prev) / prev * 100
            
            # 【要求响应：阶梯预警逻辑】
            base_threshold = 1.0 if m_type == 'forex' else 3.0
            last_triggered = state["last_triggered_pct"].get(symbol, None)
            
            should_audit = False
            trigger_reason = ""

            if is_forced:
                should_audit = True
                trigger_reason = "⏰ 定时强制全量扫描"
            elif last_triggered is None:
                if abs(pct) >= base_threshold:
                    should_audit = True
                    trigger_reason = f"🌋 首次异动达标 ({pct:+.2f}%)"
            else:
                # 只有达到上次触发值的两倍才再次推送
                if abs(pct) >= abs(last_triggered) * 2:
                    should_audit = True
                    trigger_reason = f"🚀 波动翻倍审计 ({last_triggered:+.2f}% -> {pct:+.2f}%)"

            # 【要求响应：无信息则略过】
            if should_audit:
                print(f"✅ 执行审计: {name} | 原因: {trigger_reason}")
                query = f"{name} {symbol} 股东增减持 订单 政策 财报"
                search_url = f"https://query1.finance.yahoo.com/v1/finance/search?q={query}&newsCount=10"
                news_text = " | ".join([n.get('title','') for n in requests.get(search_url).json().get('news', [])])
                
                analysis = ai_decision(symbol, name, {"price":curr, "pct":pct}, news_text, m_context, is_forced)
                
                requests.post(FEISHU_WEBHOOK, json={
                    "msg_type": "interactive",
                    "card": {
                        "header": {"title": {"tag": "plain_text", "content": f"【CIO审计】{name} ({pct:+.2f}%)"}, "template": "orange" if is_forced else "blue"},
                        "elements": [{"tag": "markdown", "content": f"**[触发原因]**: {trigger_reason}\n---\n{analysis}"}]
                    }
                }, timeout=15)
                state["last_triggered_pct"][symbol] = pct
            else:
                # 盘中无异动则保持静默
                print(f"💤 {name} 保持静默 (波动 {pct:+.2f}%)")
        except: continue
    
    with open(STATE_PATH, 'w') as f: json.dump(state, f)

if __name__ == "__main__": main()
