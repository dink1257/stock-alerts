import requests, os, csv, pytz, json
from datetime import datetime
from yahooquery import Ticker

# --- 配置区 ---
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY") 
WATCHLIST_PATH = "data/watchlist.csv"
STATE_PATH = "data/alert_state.json"

def get_market_context():
    """获取大盘数据，作为全局审计锚点"""
    print("🌐 正在抓取指数行情 (SH000001 / ^HSI)...")
    try:
        tickers = Ticker("000001.SS ^HSI")
        data = tickers.price
        sh = data.get('000001.SS', {})
        hs = data.get('^HSI', {})
        
        sh_p = sh.get('regularMarketPrice', "N/A")
        sh_pct = sh.get('regularMarketChangePercent', 0) * 100
        hs_p = hs.get('regularMarketPrice', "N/A")
        hs_pct = hs.get('regularMarketChangePercent', 0) * 100
        
        ctx = f"上证: {sh_p} ({sh_pct:+.2f}%); 恒生: {hs_p} ({hs_pct:+.2f}%)"
        print(f"✅ 大盘快照: {ctx}")
        return ctx
    except Exception as e:
        print(f"⚠️ 大盘抓取提示: {e}")
        return "指数行情暂时离线，根据个股独立逻辑研判。"

def ai_decision(symbol, name, p_meta, news, m_context, is_forced):
    """总监级 AI 决策引擎"""
    print(f"🧠 正在调用 Qwen-Max 对 {name} 进行深度审计...")
    prompt = f"""
### 角色定位
你是一位资深买方投资总监。你的审计报告必须结构严谨，严禁偏差。

### 核心审计数据
- 宏观盘面：{m_context}
- 目标标的：{name} ({symbol}) | 实时波动：{p_meta['pct']:+.2f}%
- 模式：{'【定时全量审计】' if is_forced else '【异动触发】'}

### 严格审计指令
1. **【盘面情况审计】**：点评上证/恒指走势及成交量，定性市场情绪。
2. **【品种归因审计】**：
   - 股权审计：前五大股东、董监高增减持/质押等。无信息则略过。
   - 基本面审计：个股经营订单、基本面及财报预期。无信息则略过。
   - 逻辑隔离：判断是跟随大盘(Beta)还是个股独立逻辑(Alpha)。
3. **【操作建议】**：买入/卖出/持仓。明确方向、幅度及持续性。

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
        res = requests.post("https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation", headers=headers, json=payload, timeout=120)
        res_data = res.json()
        content = res_data['output']['choices'][0]['message']['content']
        tokens = res_data.get('usage', {}).get('total_tokens', 0)
        return content + f"\n\n---\n💰 **[成本审计]**：消耗 {tokens} Tokens (约 ¥{(tokens/1000)*0.12:.4f})"
    except Exception as e:
        print(f"❌ AI 接口异常: {e}")
        return f"⚠️ 研判异常: {str(e)}"

def main():
    bj_tz = pytz.timezone("Asia/Shanghai")
    now = datetime.now(bj_tz)
    print(f"🚀 系统启动 | 北京时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 强制扫描模式判定 (08:30 & 12:45)
    is_forced = (now.hour == 8 and 25 <= now.minute <= 59) or (now.hour == 9 and 0 <= now.minute <= 15) or \
                (now.hour == 12 and 40 <= now.minute <= 59) or (now.hour == 13 and 0 <= now.minute <= 15)
    print(f"📢 当前运行模式: {'强制全量推送' if is_forced else '异动阶梯监控'}")

    m_context = get_market_context()

    if not os.path.exists(WATCHLIST_PATH):
        print(f"❌ 错误: 找不到文件 {WATCHLIST_PATH}")
        return
        
    with open(WATCHLIST_PATH, 'r', encoding='utf-8') as f:
        stocks = list(csv.DictReader(f))
    
    try:
        with open(STATE_PATH, 'r') as f: state = json.load(f)
    except: 
        print("💡 初始运行，创建状态追踪文件")
        state = {"last_triggered_pct": {}}

    for s in stocks:
        symbol, name = s['symbol'], s['name']
        m_type = s.get('type', 'stock')
        print(f"🔎 扫描标的: {name} ({symbol})")
        
        try:
            tk = Ticker(symbol)
            p_info = tk.price.get(symbol, {})
            curr = p_info.get('regularMarketPrice')
            prev = p_info.get('regularMarketPreviousClose')
            
            if curr is None or prev is None:
                print(f"   ⚠️ 价格抓取失败，跳过")
                continue
                
            pct = (curr - prev) / prev * 100
            base_threshold = 1.0 if m_type == 'forex' else 3.0
            last_p = state["last_triggered_pct"].get(symbol)
            
            should_audit = False
            reason = ""

            if is_forced:
                should_audit = True
                reason = "⏰ 定时强制全量审计"
            elif last_p is None:
                if abs(pct) >= base_threshold:
                    should_audit = True
                    reason = f"🌋 首次异动达标 ({pct:+.2f}%)"
            else:
                # 阶梯翻倍逻辑：只有当前波动达到上次触发值的两倍才推送
                if abs(pct) >= abs(last_p) * 2:
                    should_audit = True
                    reason = f"🚀 波动翻倍审计 ({last_p:+.2f}% -> {pct:+.2f}%)"

            if should_audit:
                print(f"   ✅ 触发审计! 原因: {reason}")
                # 全网搜寻
                search_url = f"https://query1.finance.yahoo.com/v1/finance/search?q={name} {symbol} 股东 订单 研报&newsCount=8"
                news_r = requests.get(search_url).json()
                news_text = " | ".join([n.get('title','') for n in news_r.get('news', [])])
                
                analysis = ai_decision(symbol, name, {"pct":pct}, news_text, m_context, is_forced)
                
                # 发送飞书
                card = {
                    "msg_type": "interactive",
                    "card": {
                        "header": {"title": {"tag": "plain_text", "content": f"【CIO审计】{name} ({pct:+.2f}%)"}, "template": "orange" if is_forced else "blue"},
                        "elements": [{"tag": "markdown", "content": f"**[触发原因]**: {reason}\n---\n{analysis}"}]
                    }
                }
                requests.post(FEISHU_WEBHOOK, json=card, timeout=15)
                state["last_triggered_pct"][symbol] = pct
            else:
                print(f"   💤 保持静默 (当前 {pct:+.2f}%, 上次触发 {last_p if last_p else 0:+.2f}%)")
                
        except Exception as e:
            print(f"   ❌ 处理异常: {e}")
            continue

    with open(STATE_PATH, 'w') as f:
        json.dump(state, f)
    print(f"🏁 审计任务全部完成 | {datetime.now(bj_tz).strftime('%H:%M:%S')}")

if __name__ == "__main__":
    main()
