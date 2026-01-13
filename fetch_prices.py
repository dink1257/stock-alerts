#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import time
import os
import pytz
import csv
import urllib.parse
from datetime import datetime, timezone

# --- 核心依赖导入 ---
try:
    from yahooquery import Ticker
except Exception as e:
    Ticker = None
    print(f"[WARN] 未能导入 yahooquery.Ticker：{e}")

try:
    import exchange_calendars as xcals
except Exception:
    xcals = None

# --- 配置 & 环境变量 ---
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
BARK_URL = os.getenv("BARK_URL")

# 全局日历初始化 (保持你原有逻辑)
NY_CAL = CN_CAL = HK_CAL = None
if xcals:
    try:
        for cid in ["XNYS", "NYSE"]:
            try: NY_CAL = xcals.get_calendar(cid); break
            except: pass
        for cid in ["XSES", "SSE"]:
            try: CN_CAL = xcals.get_calendar(cid); break
            except: pass
        for cid in ["XHKG", "HKG"]:
            try: HK_CAL = xcals.get_calendar(cid); break
            except: pass
    except Exception as e:
        print(f"[WARN] 初始化日历失败：{e}")

# ---------- 辅助函数 ----------

def set_github_output(name, value):
    """向 GitHub Actions 发送信号的核心函数"""
    if 'GITHUB_OUTPUT' in os.environ:
        with open(os.environ['GITHUB_OUTPUT'], 'a') as fh:
            print(f"{name}={value}", file=fh)
            print(f"[SENTINEL] 已向 GitHub 发送信号: {name}={value}")

def bark_push(title, body):
    """预警即时推送"""
    if not BARK_URL:
        return False
    safe_title = urllib.parse.quote(title, safe='')
    safe_body = urllib.parse.quote(body, safe='')
    push_url = BARK_URL.rstrip('/') + '/' + safe_title + '/' + safe_body
    try:
        r = requests.get(push_url, timeout=6)
        return r.status_code < 300
    except:
        return False

def get_price_info(symbol):
    """封装价格获取，提高鲁棒性"""
    try:
        t = Ticker(symbol)
        p = t.price[symbol]
        price = p.get("regularMarketPrice") or p.get("regularMarketLastClose")
        prev = p.get("regularMarketPreviousClose")
        change_pct = p.get("regularMarketChangePercent") or ((price-prev)/prev*100 if prev else 0)
        return float(price), float(prev), float(change_pct)
    except:
        return None

def is_open(symbol):
    """综合判断交易时段"""
    if "-" in symbol: return True # Crypto
    now_utc = datetime.now(timezone.utc)
    # 优先日历判断
    try:
        if symbol.endswith(".SS") and CN_CAL: return CN_CAL.is_open_now(now_utc)
        if symbol.endswith(".HK") and HK_CAL: return HK_CAL.is_open_now(now_utc)
        if not symbol.endswith((".SS", ".HK")):
            if NY_CAL: return NY_CAL.is_open_now(now_utc)
    except: pass
    # 后备：时区硬编码判断 (保持你原有逻辑)
    sh_now = now_utc.astimezone(pytz.timezone("Asia/Shanghai"))
    hhmm = sh_now.hour * 100 + sh_now.minute
    if symbol.endswith(".SS") or symbol.endswith(".SZ"):
        return (930 <= hhmm <= 1130) or (1300 <= hhmm <= 1500)
    return True # 默认放行或按需添加美股硬编码

# ---------- 主逻辑 ----------

def check_prices():
    if not os.path.exists(WATCHLIST_PATH):
        print(f"[ERROR] 找不到文件: {WATCHLIST_PATH}")
        return

    try:
        with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except Exception as e:
        print(f"[ERROR] 读取失败: {e}")
        return

    any_alert_triggered = False  # 🚩 哨兵开关
    summary_list = []

    for row in rows:
        symbol = row.get("symbol", "").strip()
        if not symbol: continue
        
        # 自动补全后缀逻辑
        if symbol.isdigit():
            symbol += ".SS" if symbol.startswith("6") else ".SZ"

        alert_up = float(row.get("alert_up", 0) or 0)
        alert_down = float(row.get("alert_down", 0) or 0)
        
        # 1. 判断是否需要监控价格
        if not is_open(symbol):
            print(f"[{symbol}] 休市中，跳过实时监控")
            continue

        # 2. 获取价格
        price_data = get_price_info(symbol)
        if not price_data: continue
        price, prev, pct = price_data
        
        # 3. 阈值检查
        triggered = False
        if alert_up > 0 and pct >= alert_up: triggered = True
        if alert_down < 0 and pct <= alert_down: triggered = True 

        if triggered:
            any_alert_triggered = True
            direction = "🚀涨" if pct > 0 else "📉跌"
            title = f"警报: {symbol} {direction} {pct:.2f}%"
            body = f"当前价: {price} | 昨收: {prev}\n系统已唤醒 AI 进行深度新闻分析..."
            bark_push(title, body)
            summary_list.append(f"{symbol}({pct:.2f}%)")
            print(f"[ALERT] {title}")
        else:
            print(f"[SCAN] {symbol} 当前波动 {pct:.2f}%，未达阈值")

    # --- 核心联动：如果触发了警报，通知 GitHub Actions 开启 AI 深度模式 ---
    if any_alert_triggered:
        set_github_output("alert_triggered", "true")
        print(f"信号已发出：检测到 {', '.join(summary_list)} 异常波动。")
    else:
        set_github_output("alert_triggered", "false")
        print("市场平稳，未触发 AI 分析链路。")

if __name__ == "__main__":
    check_prices()
