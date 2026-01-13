import requests
import os
import csv
import pytz
import urllib.parse
from datetime import datetime, timezone
from yahooquery import Ticker

# --- 环境配置 ---
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
BARK_URL = os.getenv("BARK_URL")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

def bark_push(title, body):
    if not BARK_URL: return
    try:
        safe_title = urllib.parse.quote(title, safe='')
        safe_body = urllib.parse.quote(body, safe='')
        requests.get(f"{BARK_URL.rstrip('/')}/{safe_title}/{safe_body}", timeout=10)
    except Exception as e:
        print(f"推送失败: {e}")

def ai_quick_analyze(symbol, pct, news):
    """发现异动后立即调用 AI 进行分析"""
    if not DASHSCOPE_API_KEY: return "AI Key 缺失"
    prompt = f"股票 {symbol} 波动 {pct:.2f}%。相关新闻: {news}。请用 60 字内中文分析核心原因。"
    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        data = {"model": "qwen-turbo", "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=data, timeout=15)
        return r.json()['output']['text']
    except Exception as e:
        return f"AI 暂时不可用: {e}"

def fetch_top_news(symbol):
    """获取即时新闻"""
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}"
        r = requests.get(url, timeout=10)
        news = r.json().get("news", [])
        return " | ".join([n['title'] for n in news[:3]]) if news else "暂无即时新闻"
    except:
        return "新闻检索失败"

def is_market_open(symbol):
    """判断是否为交易时间"""
    now_utc = datetime.now(timezone.utc)
    if "-" in symbol: return True  # 加密货币全天候
    
    # A股/港股判断
    sh_now = now_utc.astimezone(pytz.timezone("Asia/Shanghai"))
    hhmm = sh_now.hour * 100 + sh_now.minute
    if symbol.endswith((".SS", ".SZ", ".HK")):
        return (930 <= hhmm <= 1135) or (1300 <= hhmm <= 1605)
        
    # 美股判断 (简单处理美东时间)
    est_now = now_utc.astimezone(pytz.timezone("US/Eastern"))
    hhmm_est = est_now.hour * 100 + est_now.minute
    return 930 <= hhmm_est <= 1605

def check_prices():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始股价巡检...")
    if not os.path.exists(WATCHLIST_PATH):
        print(f"错误: 找不到文件 {WATCHLIST_PATH}")
        return

    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for row in rows:
        symbol = row.get("symbol", "").strip()
        if not symbol or not is_market_open(symbol):
            continue

        try:
            t = Ticker(symbol)
            # 安全取价
            p_data = t.price.get(symbol, {})
            price = p_data.get("regularMarketPrice")
            prev = p_data.get("regularMarketPreviousClose")
            
            if price is None or prev is None:
                print(f"[跳过] {symbol}: 无法获取实时价格数据")
                continue
                
            pct = ((price - prev) / prev * 100)
            
            # --- 修正点：根据你的标准设为 3.0 ---
            # 逻辑：优先读取 CSV 里的设定值，如果没有填，则默认按 3.0% 触发
            threshold = float(row.get("alert_up") or 3.0) 

            if abs(pct) >= threshold:
                print(f"[触发] {symbol} 波动 {pct:.2f}% (阈值 {threshold}%)，开始 AI 诊断...")
                news = fetch_top_news(symbol)
                analysis = ai_quick_analyze(symbol, pct, news)
                
                direction = "🚀大涨" if pct > 0 else "📉大跌"
                title = f"{direction}: {symbol} {pct:.2f}%"
                content = f"当前价: {price}\n分析: {analysis}"
                bark_push(title, content)
            else:
                print(f"[正常] {symbol} 波动 {pct:.2f}%，未达 {threshold}% 阈值")
        except Exception as e:
            print(f"[报错] 处理 {symbol} 时出错: {e}")

if __name__ == "__main__":
    check_prices()
