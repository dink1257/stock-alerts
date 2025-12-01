import requests
import time
import os
import pytz 
from datetime import datetime
import Ticker # 假设这是 yahooquery.Ticker 的别名
import csv
import io
import dashscope
# 引入 exchange_calendars 库，用于精确判断全球市场交易时间
import exchange_calendars as xcals

# --- 环境变量/密钥 ---
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY") 
BARK_URL = os.getenv("BARK_URL")

# --- 初始化全球交易所日历 (只执行一次) ---
try:
    # 纽约证券交易所 (美股，自动处理夏令时/冬令时/节假日)
    NYSE = xcals.get_calendar("XNYS")
    # 上海证券交易所 (A股，自动处理周末/节假日/午休)
    SSE = xcals.get_calendar("XSES")
    # 香港证券交易所 (港股，自动处理周末/节假日/午休)
    HKG = xcals.get_calendar("XHKG")
except Exception as e:
    print(f"初始化交易日历失败：{e}")
    # 允许程序继续运行，但交易时间判断可能不准确
    pass


# --- Bark 推送函数 ---
def bark_push(title, body):
    # ... (推送函数与原版相同) ...
    if not BARK_URL:
        print(f"Skipping push: {title} / {body}")
        return
    
    # 简化URL编码处理 (实际使用时应更严谨地编码 body)
    url = f"{BARK_URL}/{title}/{body}" 
    try:
        requests.get(url, timeout=5)
    except Exception as e:
        print(f"Bark push error: {e}")
        pass

# --- 核心辅助函数：精确判断价格是否开市 ---
def is_open_for_price(symbol):
    """
    精确判断给定资产是否处于主要交易时段，自动兼容中港美节假日。
    """
    now_utc = datetime.now(pytz.utc)

    # 1. A股 (使用 SSE 日历)
    if symbol.endswith(".SS"):
        return SSE.is_open_now(now_utc) 

    # 2. 港股 (使用 HKG 日历)
    elif symbol.endswith(".HK"):
        return HKG.is_open_now(now_utc)

    # 3. 美股 (使用 NYSE 日历)
    elif not symbol.endswith((".SS", ".HK")) and not symbol.endswith("-USD"): 
        # 默认认为非 A/H 且非 Crypto 的是美股
        return NYSE.is_open_now(now_utc)

    # 4. 加密货币 (7x24 资产，始终允许运行，依赖 cron 限制周一到周五)
    elif symbol.upper() in ["BTC-USD", "ETH-USD"] or "-" in symbol:
        return True 
        
    return False # 未识别资产，视为关闭


# --- 新闻抓取和 AI 分析函数 ---
def fetch_free_news(symbol):
    # ... (新闻抓取函数与原版相同) ...
    url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}"
    try:
        r = requests.get(url, timeout=5).json()
        if "news" in r:
            items = r["news"]
            if items:
                return items[0].get("title", f"{symbol}新闻标题获取失败")
    except Exception:
        return None
    return None

def ai_analyze(news, high_risk, change_pct):
    # ... (AI 分析函数与原版相同) ...
    if not DASHSCOPE_API_KEY:
        return "AI分析跳过：API KEY缺失"
        
    model = "qwen-plus" if high_risk else "qwen-turbo"
    
    if news and change_pct != 0:
        prompt = f"当前涨跌幅 {abs(change_pct)}%。股票相关新闻：{news}。请用中文简短分析其风险和原因，并给出下一步方向（text）"
    elif news and change_pct == 0:
        prompt = f"休市期间发现新新闻：{news}。请用中文简短分析其对下个交易日的潜在风险和原因，并给出下一步方向（text）"
    else:
        direction = "上涨" if change_pct > 0 else "下跌"
        prompt = f"股票价格在没有明确新闻的情况下{direction}了 {abs(change_pct)}%。请分析其潜在风险和下一步方向，text："

    try:
        response = dashscope.Generation.call(
            model=model,
            prompt=prompt
        )
        return response.output['text']
    except Exception as e:
        return f"AI分析失败：{e}"


# --- 主逻辑函数 ---
def check_prices():
    try:
        with open("watchlist.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            
            for row in reader:
                symbol = row.get("symbol", "").upper()
                alert_up = float(row.get("alert_up", 0))
                alert_down = float(row.get("alert_down", 0))
                high_risk = row.get("high_risk", "false").lower() == "true"
                
                # ⭐️ 核心标志：判断当前是否是价格监控时段
                is_open = is_open_for_price(symbol)
                
                # --- 步骤 1: 始终尝试获取新闻（即使休市）---
                news = fetch_free_news(symbol)

                # --- 步骤 2: 价格监控和价格警报 (仅在开市时执行) ---
                if is_open:
                    
                    # --- 获取价格数据 ---
                    t = Ticker(symbol)
                    info = t.price
                    
                    if symbol not in info or "regularMarketPrice" not in info[symbol]:
                        print(f"[{symbol}] 无法获取价格数据，跳过。")
                        time.sleep(0.5)
                        continue
                        
                    price_info = info[symbol]
                    change_pct = price_info.get("regularMarketChangePercent", 0) 
                    direction = "上涨" if change_pct > 0 else "下跌"
                    
                    # 警报触发判断 (价格警报)
                    if abs(change_pct) >= alert_up or abs(change_pct) >= alert_down:
                        
                        title = f"🚨 {symbol} {direction} {abs(change_pct):.2f}% Alert"
                        
                        # AI 分析 (包含新闻或价格变动)
                        AI_result = ai_analyze(news=news, high_risk=high_risk, change_pct=change_pct)
                        
                        body = f"方向：{direction} {abs(change_pct):.2f}%\n新闻：{news if news else '无相关新闻'}\nAI 解读：{AI_result}"
                        bark_push(title, body)

                # --- 步骤 3: 休市时的新闻警报和 AI 分析（针对增量新闻）---
                elif news:
                    # 价格 API 已跳过 (is_open=False)，但抓到了新闻
                    
                    title = f"📰 {symbol} News Alert (Market Closed)" 
                    
                    # 仅基于新闻进行 AI 分析，设置 change_pct=0 仅激活新闻分析逻辑
                    AI_result = ai_analyze(news=news, high_risk=high_risk, change_pct=0) 
                    
                    body = f"市场状态：休市\n新闻：{news}\nAI 解读：{AI_result}"
                    bark_push(title, body)
                    
                # 否则（休市且无新闻）：跳过价格 API 和 AI 分析
                else:
                    print(f"[{symbol}] 休市且无增量新闻，跳过 API/AI 监控。")
                    
                time.sleep(1) # 增加延迟
                
    except FileNotFoundError:
        print("错误：未找到 watchlist.csv 文件。")
    except Exception as e:
        print(f"运行过程中发生错误: {e}")

if __name__ == '__main__':
    check_prices()
