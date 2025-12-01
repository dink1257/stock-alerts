#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import time
import os
import pytz
import csv
import io
import urllib.parse
from datetime import datetime, timezone, timedelta

# 正确导入 yahooquery 的 Ticker
try:
    from yahooquery import Ticker
except Exception as e:
    Ticker = None
    print(f"[WARN] 未能导入 yahooquery.Ticker：{e}（请确保 workflow 安装 yahooquery）")

# dashscope（通义）可选，代码中以存在性判断
try:
    import dashscope
except Exception:
    dashscope = None

# exchange_calendars 可选，若不可用将回退到时区判断逻辑
try:
    import exchange_calendars as xcals
except Exception:
    xcals = None

# --- 配置 & 环境变量 ---
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
BARK_URL = os.getenv("BARK_URL")

# 全局交易日历句柄（如果可用）
NY_CAL = None
CN_CAL = None
HK_CAL = None

if xcals:
    try:
        # 名称可能因版本不同略有差别，优先常见代码
        try:
            NY_CAL = xcals.get_calendar("XNYS")
        except Exception:
            # 有些版本用 "XNYS" 或 "NYSE"
            try:
                NY_CAL = xcals.get_calendar("XNYS")
            except Exception:
                NY_CAL = None

        try:
            CN_CAL = xcals.get_calendar("XSES")  # 有些版本可用 XSES
        except Exception:
            # 回退到上交所常见 id
            try:
                CN_CAL = xcals.get_calendar("SSE")
            except Exception:
                CN_CAL = None

        try:
            HK_CAL = xcals.get_calendar("XHKG")
        except Exception:
            try:
                HK_CAL = xcals.get_calendar("HKG")
            except Exception:
                HK_CAL = None
    except Exception as e:
        print(f"[WARN] 初始化 exchange_calendars 失败：{e}")
        NY_CAL = CN_CAL = HK_CAL = None
else:
    print("[INFO] exchange_calendars 未安装，使用时区判断作为后备。")

# ---------- 辅助函数 ----------

def safe_request_get(url, **kwargs):
    """带超时的 requests.get 封装，返回 None 表示失败"""
    try:
        resp = requests.get(url, timeout=10, **kwargs)
        resp.raise_for_status()
        return resp
    except Exception as e:
        print(f"[WARN] 请求失败：{url}  -> {e}")
        return None

def bark_push(title, body):
    """推送到 Bark（从 GitHub Secrets 读取 BARK_URL），失败时只打印警告"""
    if not BARK_URL:
        print("[WARN] BARK_URL 未设置，跳过推送")
        return False

    # URL encode 标题和 body
    safe_title = urllib.parse.quote(title, safe='')
    safe_body = urllib.parse.quote(body, safe='')
    push_url = BARK_URL.rstrip('/') + '/' + safe_title + '/' + safe_body

    try:
        r = requests.get(push_url, timeout=6)
        if r.status_code >= 200 and r.status_code < 300:
            print(f"[INFO] Bark 推送成功: {title}")
            return True
        else:
            print(f"[WARN] Bark 返回 HTTP {r.status_code}")
            return False
    except Exception as e:
        print(f"[WARN] Bark 推送异常: {e}")
        return False

def get_price_from_ticker_obj(ticker_obj, symbol):
    """
    从 yahooquery.Ticker 返回结构中安全取价。
    兼容不同 key 命名（有时带后缀、有时不带）
    返回 (price, prev_close, change_pct) 或 None
    """
    if not ticker_obj:
        return None

    info = getattr(ticker_obj, "price", None)
    if not info:
        return None

    # info 可能是 dict，key 可能为 symbol 或其他
    # 尝试直接取指定 symbol 的数据
    data = None
    if isinstance(info, dict):
        if symbol in info:
            data = info.get(symbol)
        else:
            # 尝试找到最相近的 key，例如去掉后缀或不去后缀
            for k, v in info.items():
                if not isinstance(k, str):
                    continue
                if k.upper() == symbol.upper():
                    data = v
                    break
            if not data:
                # 取第一个非空项作为 fallback
                for v in info.values():
                    if isinstance(v, dict):
                        data = v
                        break
    else:
        # 若不是 dict，直接返回 None
        return None

    if not data or not isinstance(data, dict):
        return None

    # 常见字段
    price = data.get("regularMarketPrice") or data.get("regularMarketLastClose") or data.get("last") or data.get("price")
    prev = data.get("regularMarketPreviousClose") or data.get("chartPreviousClose") or data.get("previousClose")
    change_pct = data.get("regularMarketChangePercent") or data.get("changePercent") or None

    # 有时 change_pct 用小数表示，需要处理（我们只在存在时返回）
    try:
        if change_pct is not None:
            change_pct = float(change_pct)
    except Exception:
        change_pct = None

    if price is None or prev is None:
        return None

    # 计算 pct 如果没有提供
    if change_pct is None:
        try:
            change_pct = (float(price) - float(prev)) / float(prev) * 100
        except Exception:
            change_pct = 0.0

    try:
        return float(price), float(prev), float(change_pct)
    except Exception:
        return None

def tz_now(tz_name):
    """返回指定时区的当前时间（datetime）"""
    try:
        tz = pytz.timezone(tz_name)
        return datetime.now(tz)
    except Exception:
        return datetime.now(timezone.utc)

def is_trading_open_by_calendar(symbol):
    """优先使用 exchange_calendars（若可用）判断当前是否交易时段"""
    now_utc = datetime.now(timezone.utc)
    try:
        if symbol.endswith(".SS") and CN_CAL:
            return CN_CAL.is_open_now(now_utc)
        if symbol.endswith(".HK") and HK_CAL:
            return HK_CAL.is_open_now(now_utc)
        # 默认认为非 A/H 且非 Crypto 的是美股
        if (not symbol.endswith(".SS") and not symbol.endswith(".HK")) and not "-" in symbol:
            if NY_CAL:
                return NY_CAL.is_open_now(now_utc)
    except Exception as e:
        print(f"[WARN] calendar 判断异常：{e}")
    return None  # 表示无法判断

def is_in_trading_hours_by_tz(symbol):
    """基于时区和常见交易时段的后备判断（当 exchange_calendars 不可用时使用）"""
    # Crypto 7x24
    if "-" in symbol:
        return True

    now_utc = datetime.now(pytz.utc)

    # A股（上海/深圳）Asia/Shanghai
    if symbol.endswith(".SS") or symbol.endswith(".SZ"):
        sh_now = now_utc.astimezone(pytz.timezone("Asia/Shanghai"))
        hhmm = sh_now.hour * 100 + sh_now.minute
        # A股常见交易时段 09:30-11:30 / 13:00-15:00
        if (930 <= hhmm <= 1130) or (1300 <= hhmm <= 1500):
            return True
        return False

    # 港股 HKT (Asia/Hong_Kong) 09:30-12:00 / 13:00-16:00
    if symbol.endswith(".HK"):
        hk_now = now_utc.astimezone(pytz.timezone("Asia/Hong_Kong"))
        hhmm = hk_now.hour * 100 + hk_now.minute
        if (930 <= hhmm <= 1200) or (1300 <= hhmm <= 1600):
            return True
        return False

    # 美股（US/Eastern）09:30-16:00（简化）
    # 注意夏令时会由时区自动处理
    if not symbol.endswith((".SS", ".HK")) and not "-" in symbol:
        est_now = now_utc.astimezone(pytz.timezone("US/Eastern"))
        hhmm = est_now.hour * 100 + est_now.minute
        if 930 <= hhmm <= 1600:
            return True
        return False

    return False

def is_open_for_price(symbol):
    """
    综合判断市场是否在交易时段：
    1) 优先使用 exchange_calendars（若可用）
    2) 回退到时区时间段判断
    3) Crypto 始终返回 True（由 cron+workflow 控制频率）
    """
    # Crypto (例如 BTC-USD)
    if "-" in symbol:
        return True

    cal_result = is_trading_open_by_calendar(symbol)
    if cal_result is not None:
        return bool(cal_result)
    # 回退
    return is_in_trading_hours_by_tz(symbol)

def fetch_free_news(symbol):
    """用 Yahoo Finance 的搜索 API 尝试获取最新相关新闻标题（尽量返回字符串或 None）"""
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={urllib.parse.quote(symbol)}"
        r = safe_request_get(url)
        if not r:
            return None
        j = r.json()
        news_items = j.get("news") or j.get("quotes") or []
        if news_items and isinstance(news_items, list):
            # 找到第一个带 title 的
            for it in news_items:
                if isinstance(it, dict) and it.get("title"):
                    return it.get("title")
            # fallback: 返回第一项的简短描述
            first = news_items[0]
            if isinstance(first, dict):
                return first.get("title") or first.get("shortname") or str(first)
        return None
    except Exception as e:
        print(f"[WARN] fetch_free_news 失败：{e}")
        return None

def ai_analyze(news, high_risk, change_pct):
    """调用 dashscope（通义）做简短中文分析；若不可用则返回说明文字"""
    if not DASHSCOPE_API_KEY or not dashscope:
        return "AI分析跳过：API KEY缺失或 dashscope 未安装"
    try:
        # 根据你的 earlier 设定使用可兼容调用，保护调用异常
        model = "qwen-plus" if high_risk else "qwen-turbo"
        if news and change_pct != 0:
            prompt = f"当前涨跌幅 {abs(change_pct):.2f}%。股票相关新闻：{news}。请用中文简短分析其风险和原因，并给出下一步方向。"
        elif news and change_pct == 0:
            prompt = f"休市期间发现新新闻：{news}。请用中文简短分析其对下个交易日的潜在风险和建议。"
        else:
            direction = "上涨" if change_pct > 0 else "下跌"
            prompt = f"股票价格在没有明确新闻的情况下{direction}了 {abs(change_pct):.2f}%。请分析其潜在风险和下一步方向。"

        # 注意：dashscope SDK 的调用接口可能不同，下面是一个常见兼容写法
        try:
            resp = dashscope.Generation.call(model=model, prompt=prompt)
            # resp 结构可能是 dict-like 或对象，尝试多种方式获取文本
            text = None
            if isinstance(resp, dict):
                text = resp.get("output", {}).get("text") or resp.get("text")
            else:
                # object
                text = getattr(resp, "output", None)
                if text:
                    text = text.get("text") if isinstance(text, dict) else None
            if not text:
                # 有些 wrapper 直接返回 string
                text = str(resp)
            return text[:1500]  # 截断避免超长
        except Exception as e:
            # 退到 HTTP API 直接调用（若需要你可替换为实际阿里云 dashscope HTTP 调用）
            print(f"[WARN] dashscope SDK 调用异常：{e}")
            return "AI分析失败：dashscope 调用异常"
    except Exception as e:
        return f"AI分析失败：{e}"

# ---------- 主逻辑 ----------
def check_prices():
    if Ticker is None:
        print("[ERROR] yahooquery.Ticker 未导入，终止运行。请确保在 workflow 的 dependencies 中安装 yahooquery。")
        return

    if not os.path.exists(WATCHLIST_PATH):
        print(f"[ERROR] 未找到 watchlist 文件：{WATCHLIST_PATH}")
        return

    try:
        with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        print(f"[ERROR] 读取 watchlist 失败：{e}")
        return

    print(f"[INFO] 共读取 {len(rows)} 个标的，开始检查...")

    for idx, row in enumerate(rows, 1):
        try:
            symbol_raw = row.get("symbol", "").strip()
            if not symbol_raw:
                continue

            # 标准化 symbol（你 watchlist 中可能已包含后缀 yf_symbol）
            symbol = symbol_raw
            # 如果用户填写 A 股（纯数字如 600519），自动补 .SS / .SZ 规则（优先简单规则）
            if symbol.isdigit():
                if symbol.startswith("6"):
                    symbol = symbol + ".SS"
                else:
                    symbol = symbol + ".SZ"
            # 处理港股常见无前导 0 情况（若已带 .HK 则跳过）
            if len(symbol) <= 4 and symbol.isdigit():
                # 以 4 位为准补 0（0700） -> 0700.HK handled above if needed in watchlist
                pass

            market = row.get("market", "").upper()
            alert_up = float(row.get("alert_up", 0) or 0)
            alert_down = float(row.get("alert_down", 0) or 0)
            high_risk = row.get("high_risk", "").lower() == "true"

            print(f"[{idx}/{len(rows)}] 检查 {symbol} ({market}) ...")

            # 是否在交易时段（Crypto 永远 True）
            open_flag = is_open_for_price(symbol)

            # 第一步：始终尝试抓新闻（即使休市也抓）
            news = fetch_free_news(symbol)

            # 如果是开市时段则做价格监控
            if open_flag:
                # 使用 yahooquery 获取价格（构造 ticker 对象）
                try:
                    t = Ticker(symbol)
                except Exception as e:
                    print(f"[WARN] 创建 Ticker({symbol}) 失败：{e}")
                    time.sleep(0.3)
                    continue

                price_tuple = get_price_from_ticker_obj(t, symbol)
                if not price_tuple:
                    print(f"[WARN] {symbol} 无法解析到价格，跳过")
                    time.sleep(0.3)
                    continue

                price, prev_close, change_pct = price_tuple
                direction = "上涨" if change_pct > 0 else "下跌"

                print(f"    价格: {price} / 昨收: {prev_close} -> {change_pct:.2f}% ({direction})")

                # 触发条件：满足任一阈值
                trigger = False
                if alert_up > 0 and abs(change_pct) >= alert_up:
                    trigger = True
                if alert_down > 0 and abs(change_pct) >= alert_down:
                    trigger = True

                if trigger:
                    title = f"🚨 {symbol} {direction} {abs(change_pct):.2f}%"
                    ai_text = ai_analyze(news=news, high_risk=high_risk, change_pct=change_pct)
                    body = f"方向：{direction} {abs(change_pct):.2f}%\n新闻：{news or '无'}\nAI：{ai_text}"
                    bark_push(title, body)

            # 休市时：若抓到新闻则发新闻预警（AI 基于新闻）
            else:
                if news:
                    print(f"    市场休市，但检测到新闻：{news}")
                    title = f"📰 {symbol} News (Market Closed)"
                    ai_text = ai_analyze(news=news, high_risk=high_risk, change_pct=0)
                    body = f"市场状态：休市\n新闻：{news}\nAI：{ai_text}"
                    bark_push(title, body)
                else:
                    print(f"    休市且无新闻，跳过")

            # 每个标的短暂停顿，避免请求风暴
            time.sleep(0.8)

        except Exception as e:
            print(f"[ERROR] 处理 {row.get('symbol')} 时异常：{e}")
            # 不中断整个循环
            continue

    print("[INFO] 本次检查完成。")


if __name__ == "__main__":
    check_prices()
