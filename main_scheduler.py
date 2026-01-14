import requests
import os
import csv
import pytz
import json
import urllib.parse
from datetime import datetime, timezone
from yahooquery import Ticker

# --- 环境配置 ---
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
STATE_CACHE_PATH = "data/alert_state.json"
BARK_URL = os.getenv("BARK_URL")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")

def bark_push(title, body):
    if not BARK_URL: return
    try:
        url = f"{BARK_URL.rstrip('/')}/{urllib.parse.quote(str(title))}/{urllib.parse.quote(str(body))}"
        requests.get(url, timeout=10)
    except Exception as e:
        print(f"推送失败: {e}")

def load_state():
    if os.path.exists(STATE_CACHE_PATH):
        try:
            with open(STATE_CACHE_PATH, "r") as f: return json.load(f)
        except: return {}
    return {}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_CACHE_PATH), exist_ok=True)
    with open(STATE_CACHE_PATH, "w") as f: json.dump(state, f)

def fetch_top_news(symbol):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}"
        r = requests.get(url, headers=headers, timeout=10)
        news = r.json().get("news", [])
        return " | ".join([n['title'] for n in news[:5]]) if news else "暂无直接核心资讯"
    except: return "资讯抓取链路异常"

# --- AI 核心引擎 (顶级 CIO 视角) ---
def ai_analyze(symbol_info, pct, news, mode="MONITOR"):
    if not DASHSCOPE_API_KEY: return "AI Key 缺失"
    
    if mode == "MONITOR":
        trend = "上涨" if pct > 0 else "下跌"
        prompt = (
            f"【投资总监异动研判】\n标的：{symbol_info} | 异动：{trend} {abs(pct):.2f}%\n资讯：{news}\n\n"
            "要求(150字内)：\n1. 归因：界定是宏观β(流动性/政策)还是个股α(财报/基本面)驱动。\n"
            "2. 定价：分析此异动是否代表市场预期差的边际修正，非简单复读新闻。\n"
            "3. 纯度：剔除废话，若资讯弱相关，请直言‘资金博弈，无显著诱因’。"
        )
        model = "qwen-plus"
    else:
        prompt = (
            f"【首席策略师晨会内参】\n资讯池：{news}\n\n"
            "任务：对 24H 资讯执行‘脱水’研判，输出高密度策略简报：\n"
            "1. 核心变量：穿透出对今日开盘有重大定价影响的宏观变量及行业趋势。\n"
            "2. 归母定价：按公司分组，直接给出驱动因素与定价边际变化评估(看多/看空/中性)。\n"
            "3. 警示：标注可能引发预期反转的非对称因子。要求专业、凝炼、无空话。"
        )
        model = "qwen-max"

    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": model, "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        return r.json()['output']['text']
    except Exception as e:
        print(f"AI 调用异常: {e}")
        return f"【系统告警】AI 分析响应超时或波动: {str(e)}"

# --- 调度逻辑 ---
def main():
    now_utc = datetime.now(timezone.utc)
    cn_tz = pytz.timezone("Asia/Shanghai")
    us_tz = pytz.timezone("US/Eastern")
    cn_now = now_utc.astimezone(cn_tz)
    us_now = now_utc.astimezone(us_tz)
    
    print(f"--- 启动任务 [{cn_now.strftime('%Y-%m-%d %H:%M:%S')}] ---")
    
    action = "IDLE"
    hm_cn = cn_now.hour * 100 + cn_now.minute
    hm_us = us_now.hour * 100 + us_now.minute

    # 1. 逻辑判断日志
    if cn_now.weekday() < 5 and 830 <= hm_cn <= 845: action = "SUMMARY"
    elif us_now.weekday() < 5 and 830 <= hm_us <= 845: action = "SUMMARY"
    
    if action == "IDLE":
        if cn_now.weekday() < 5 and ((915 <= hm_cn <= 1140) or (1255 <= hm_cn <= 1510)): action = "MONITOR"
        elif us_now.weekday() < 5 and (925 <= hm_us <= 1610): action = "MONITOR"

    print(f"当前动作决策: {action}")

    if action == "IDLE":
        print("当前不在汇总或交易监控时段，系统静默。")
        return

    # 2. 文件加载检查
    if not os.path.exists(WATCHLIST_PATH):
        print(f"关键错误: 找不到股票名单文件 {WATCHLIST_PATH}")
        return
        
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        watchlist = list(csv.DictReader(f))
        print(f"成功加载自选股数量: {len(watchlist)}")

    state = load_state()
    today = datetime.now(timezone.utc).strftime('%Y%m%d')
    if state.get("date") != today:
        state = {"date": today, "alerts": {}}

    # 3. 执行任务
    if action == "SUMMARY":
        print("开始抓取盘前资讯流并调用 qwen-max 生成报告...")
        news_data = "\n".join([f"[{item['name']}({item['symbol']})]\n{fetch_top_news(item['symbol'])}" for item in watchlist])
        report = ai_analyze("", 0, news_data, mode="SUMMARY")
        bark_push("🌍 CIO 盘前深度内参", report)
        print("盘前内参推送完成。")

    elif action == "MONITOR":
        print(f"正在扫描行情中...")
        for item in watchlist:
            s, name = item['symbol'], item['name']
            try:
                t = Ticker(s)
                p = t.price[s]
                price = p.get("regularMarketPrice")
                prev = p.get("regularMarketPreviousClose")
                if not price or not prev: continue
                
                pct = ((price - prev) / prev * 100)
                level = 2 if abs(pct) >= 6.0 else (1 if abs(pct) >= 3.0 else 0)
                
                if level > state["alerts"].get(s, 0):
                    print(f"检测到异动: {name}({s}) {pct:.2f}%，正在生成买方研判...")
                    analysis = ai_analyze(f"{name}({s})", pct, fetch_top_news(s), mode="MONITOR")
                    bark_push(f"{'🔥' if level==2 else '🔔'} {name} {'涨' if pct>0 else '跌'}{abs(pct):.2f}%", f"现价: {price}\n【研判】: {analysis}")
                    state["alerts"][s] = level
            except Exception as e:
                print(f"扫描 {s} 时发生错误: {e}")
                continue
        save_state(state)
        print("异动扫描循环结束。")

if __name__ == "__main__":
    main()
