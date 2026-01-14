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
    except: pass

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

# --- AI 核心引擎 (CIO 级别 - 股/期双逻辑) ---
def ai_analyze(symbol_info, pct, news, mode="MONITOR", is_futures=False):
    if not DASHSCOPE_API_KEY: return "AI Key 缺失"
    
    if mode == "MONITOR":
        if is_futures:
            # 【期货 CIO 逻辑】关注：供需边际、宏观定价、多空建议
            prompt = (
                f"【买方 CIO 期货深度研判】\n标的：{symbol_info} | 波动：{pct:.2f}%\n核心资讯：{news}\n\n"
                "作为顶级对冲基金 CIO，请针对该期货合约给出专业研判（150字内）：\n"
                "1. 归因：识别是地缘政治、宏观政策、库存数据还是期限结构（Back/Contango）驱动。\n"
                "2. 判别：明确当前属于‘单边趋势’还是‘宽幅震荡’，给出[多/空/观望]方向建议。\n"
                "3. 开仓指引：评估当前波动是否具备‘大级别周期’开仓价值，指出关键支撑/阻力逻辑。\n"
                "4. 风险：提示当前最易导致止损的尾部风险变量。"
            )
        else:
            # 【股票 CIO 逻辑】关注：α/β 归因、预期差
            prompt = (
                f"【买方 CIO 股票异动研判】\n标的：{symbol_info} | 波动：{pct:.2f}%\n资讯：{news}\n\n"
                "要求(150字内)：\n1. 归因：界定是宏观β驱动还是个股α驱动。\n"
                "2. 定价：分析此异动是否代表市场预期差的边际修正。\n"
                "3. 纯度：剔除废话，若资讯弱相关，请直言‘资金博弈，无显著诱因’。"
            )
        model = "qwen-plus"
    else:
        # 【全品种盘前汇总】
        prompt = (
            f"【全球首席策略师 - 晨会内参】\n资讯池：{news}\n\n"
            "任务：对 24H 资讯执行‘脱水’研判，输出高密度策略简报：\n"
            "1. 全球驱动：识别影响今日股/期市场的宏观定价变量。\n"
            "2. 归母定价：按品种分组，给出驱动因素与定价边际变化评估(看多/看空/中性)。\n"
            "3. 机会预警：标注具备大级别趋势启动潜力的品种及理由。要求专业凝炼。"
        )
        model = "qwen-max"

    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": model, "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=payload, timeout=60)
        return r.json()['output']['text']
    except Exception as e:
        return f"【系统告警】AI 响应超时，请参考实时资讯: {str(e)}"

# --- 调度逻辑 ---
def main():
    now_utc = datetime.now(timezone.utc)
    cn_tz, us_tz = pytz.timezone("Asia/Shanghai"), pytz.timezone("US/Eastern")
    cn_now, us_now = now_utc.astimezone(cn_tz), now_utc.astimezone(us_tz)
    
    print(f"--- 启动任务 [{cn_now.strftime('%Y-%m-%d %H:%M:%S')}] ---")
    
    action = "IDLE"
    hm_cn, hm_us = cn_now.hour * 100 + cn_now.minute, us_now.hour * 100 + us_now.minute

    # 1. 自动适配期货交易（期货通常全天扫描，股票按开盘时间）
    # 如果有期货需求，建议将 GitHub Actions 改为全天候执行
    if cn_now.weekday() < 5 and 830 <= hm_cn <= 845: action = "SUMMARY"
    elif us_now.weekday() < 5 and 830 <= hm_us <= 845: action = "SUMMARY"
    
    if action == "IDLE":
        # 扩展：如果当前处于 A 股或美股交易时段，进入监控
        if cn_now.weekday() < 5 and ((915 <= hm_cn <= 1510)): action = "MONITOR"
        elif us_now.weekday() < 5 and (925 <= hm_us <= 1610): action = "MONITOR"
        # 备注：如需 24 小时监控期货，可在 .yml 中将频率设为全天执行，此处 action 强制设为 MONITOR

    print(f"当前动作决策: {action}")

    if not os.path.exists(WATCHLIST_PATH): return
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        watchlist = list(csv.DictReader(f))

    state = load_state()
    today = datetime.now(timezone.utc).strftime('%Y%m%d')
    if state.get("date") != today: state = {"date": today, "alerts": {}}

    if action == "SUMMARY":
        news_data = "\n".join([f"[{i['name']}({i['symbol']})]\n{fetch_top_news(i['symbol'])}" for i in watchlist])
        report = ai_analyze("", 0, news_data, mode="SUMMARY")
        bark_push("🌍 CIO 全球市场深度内参", report)

    elif action == "MONITOR":
        for item in watchlist:
            s, name = item['symbol'], item['name']
            is_futures = ("=F" in s or "FTX" in s) # 期货识别逻辑
            try:
                t = Ticker(s)
                p = t.price[s]
                price, prev = p.get("regularMarketPrice"), p.get("regularMarketPreviousClose")
                if not price or not prev: continue
                
                pct = ((price - prev) / prev * 100)
                # 期货阈值通常设得比股票敏感（例如 1.5% 就算显著波动）
                threshold_l1 = 1.5 if is_futures else 3.0
                threshold_l2 = 3.0 if is_futures else 6.0
                
                level = 2 if abs(pct) >= threshold_l2 else (1 if abs(pct) >= threshold_l1 else 0)
                
                if level > state["alerts"].get(s, 0):
                    print(f"检测到异动: {name} {pct:.2f}%")
                    analysis = ai_analyze(f"{name}({s})", pct, fetch_top_news(s), mode="MONITOR", is_futures=is_futures)
                    title = f"{'🌋' if is_futures else ('🔥' if level==2 else '🔔')} {name} {pct:.2f}%"
                    bark_push(title, f"现价: {price}\n【CIO 研判】: {analysis}")
                    state["alerts"][s] = level
            except: continue
        save_state(state)

if __name__ == "__main__":
    main()
