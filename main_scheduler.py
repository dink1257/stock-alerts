import requests, os, csv, pytz, json
from datetime import datetime, timedelta

# --- 配置区 ---
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY") 
WATCHLIST_PATH = "data/watchlist.csv"
STATE_PATH = "data/alert_state.json"

def is_us_dst(now):
    """自动判定美股夏令时 (3月第二个周日至11月第一个周日)"""
    year = now.year
    dst_start = datetime(year, 3, 8, 2, tzinfo=now.tzinfo)
    dst_start += timedelta(days=(6 - dst_start.weekday()) % 7 + 7)
    dst_end = datetime(year, 11, 1, 2, tzinfo=now.tzinfo)
    dst_end += timedelta(days=(6 - dst_end.weekday()) % 7)
    return dst_start <= now < dst_end

def ai_decision(symbol, name, industry, p_meta, news, m_context, is_forced):
    """【锁定：资深买方投资总监三段式提示词 - 严禁精简】"""
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
   - 仅针对标的 {name} ({symbol}) 本次 {p_meta['pct']:+.2f}% 的波动进行归因。
   - **股权审计**：审计前五大股东、董监高近期是否有增减持、质押、冻结等意志体现。若无明确信息，此项直接略过。
   - **基本面审计**：审计该品种行业政策变动（参考标签：{industry}）、供求关系、个股经营订单及财报预期。若无明确信息，此项直接略过。
   - **定性分析**：判断本次波动是跟随大盘(Beta)还是独立的个股逻辑(Alpha)。

3. **【操作建议】**：
   - 给出明确的【买入/卖出/持仓】建议。
   - 明确指出波动的方向、幅度预判及持续性。

---
[实时情报输入]：
{news}
"""
    headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "qwen-max", "input": {"messages": [{"role": "user", "content": prompt}]}, "parameters": {"result_format": "message", "temperature": 0.1}}
    try:
        res = requests.post("https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation", headers=headers, json=payload, timeout=60)
        return res.json()['output']['choices'][0]['message']['content']
    except Exception as e:
        return f"⚠️ AI 审计服务繁忙: {str(e)}"

def get_batch_quotes(symbols):
    """【高效获取方案】利用底层 API 批量抓取行情"""
    if not symbols: return {}
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={','.join(symbols)}"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        data = resp.json()
        result_list = data.get('quoteResponse', {}).get('result', [])
        return {item['symbol']: item for item in result_list}
    except Exception as e:
        print(f"❌ 行情源直连失败: {e}")
        return {}

def main():
    bj_tz = pytz.timezone("Asia/Shanghai")
    now = datetime.now(bj_tz)
    h, m = now.hour, now.minute
    print(f"🚀 财经监控cio版 V8.5.0 | {now.strftime('%H:%M:%S')}")
    
    # 1. 窗口判定逻辑 (资源节省)
    is_dst = is_us_dst(now)
    is_a_pre = (h == 8 and m >= 30) or (h == 9 and m <= 15)
    is_a_hk_trade = (h in [10, 11, 13, 14]) or (h == 9 and m >= 30) or (h == 15 and m <= 10)
    
    # 美股窗口动态适配
    if is_dst: 
        is_us_active = (h == 21 and m >= 30) or h in [22, 23, 0, 1, 2, 3]
        is_us_forced = (h == 21 and m <= 45) or (h == 4 and 0 <= m <= 15)
    else: 
        is_us_active = (h == 22 and m >= 30) or h in [23, 0, 1, 2, 3, 4]
        is_us_forced = (h == 22 and m <= 45) or (h == 5 and 0 <= m <= 15)

    is_forced = is_a_pre or (h == 12 and 45 <= m <= 59) or is_us_forced
    
    if not (is_forced or is_a_hk_trade or is_us_active):
        print(f"💤 非监控时段 ({h:02}:{m:02})，系统进入静默。")
        return

    # 2. 批量行情获取
    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, 'r', encoding='utf-8') as f:
        stocks = list(csv.DictReader(f))
    
    symbols = [s['symbol'] for s in stocks]
    all_quotes = get_batch_quotes(symbols)
    
    # 大盘上下文获取
    m_ctx_data = get_batch_quotes(["000001.SS", "^HSI", "^GSPC"])
    m_ctx = " | ".join([f"{k}: {v.get('regularMarketPrice','N/A')}({v.get('regularMarketChangePercent',0):+.2f}%)" for k, v in m_ctx_data.items()])

    try:
        with open(STATE_PATH, 'r') as f: state = json.load(f)
    except: state = {"last_triggered_pct": {}}

    # 3. 审计循环
    for s in stocks:
        symbol, name, industry = s['symbol'], s['name'], s['industry']
        q = all_quotes.get(symbol)
        if not q: continue
        
        try:
            curr = q.get('regularMarketPrice')
            prev = q.get('regularMarketPreviousClose')
            if curr is None or prev is None: continue
            
            pct = (curr - prev) / prev * 100
            last_p = state["last_triggered_pct"].get(symbol)
            
            # 异动判定逻辑
            should_audit = is_forced or (last_p is None and abs(pct) >= 3.0) or (last_p and abs(pct) >= abs(last_p)*2)
            
            if should_audit:
                print(f"✅ 审计中: {name} ({pct:+.2f}%)")
                # 强化资讯获取关键词
                search_q = f"{name} {symbol} {industry} 股东 政策"
                news_r = requests.get(f"https://query1.finance.yahoo.com/v1/finance/search?q={search_q}&newsCount=6", timeout=10).json()
                news_text = " | ".join([n.get('title','') for n in news_r.get('news', [])])
                
                content = ai_decision(symbol, name, industry, {"pct":pct}, news_text, m_ctx, is_forced)
                
                # 飞书推送
                requests.post(FEISHU_WEBHOOK, json={
                    "msg_type": "interactive",
                    "card": {
                        "header": {"title": {"tag": "plain_text", "content": f"【CIO审计】{name} ({pct:+.2f}%)"}, "template": "orange" if is_forced else "blue"},
                        "elements": [{"tag": "markdown", "content": f"**[触发原因]**: {'⏰ 定时扫描' if is_forced else '🌋 异动触发'}\n**[所属标签]**: {industry}\n---\n{content}"}]
                    }
                }, timeout=10)
                state["last_triggered_pct"][symbol] = pct
        except: continue

    with open(STATE_PATH, 'w') as f: json.dump(state, f)
    print("🏁 任务全部结束")

if __name__ == "__main__": main()
