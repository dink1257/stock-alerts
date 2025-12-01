import json
import os
import requests
import sys
from datetime import datetime

DATA_PATH = "tickers.json"


def load_tickers():
    """从 tickers.json 读取标的信息，并进行基础校验。"""
    if not os.path.exists(DATA_PATH):
        print(f"[ERROR] 找不到 {DATA_PATH}")
        sys.exit(1)

    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[ERROR] tickers.json 读取失败: {e}")
        sys.exit(1)

    if "tickers" not in data or not isinstance(data["tickers"], list):
        print("[ERROR] tickers.json 格式错误：缺少 tickers 列表")
        sys.exit(1)

    return data["tickers"]


def fetch_price_yf(symbol):
    """调用 Yahoo Finance API 读取股价."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        j = resp.json()

        result = j.get("chart", {}).get("result")
        if not result:
            return None

        meta = result[0]["meta"]
        price = meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose")

        if price is None or prev is None:
            return None

        return price, prev
    except Exception:
        return None


def push_bark(msg):
    """推送到 Bark。BARK_URL 存在 GitHub Secrets."""
    bark_url = os.getenv("BARK_URL")
    if not bark_url:
        print("[WARN] 未设置 BARK_URL，跳过推送")
        return

    try:
        url = f"{bark_url}/{msg}"
        requests.get(url)
    except Exception as e:
        print(f"[WARN] Bark 推送失败：{e}")


def process_one(ticker):
    """单个标的的处理逻辑：请求、比较、生成输出。"""

    symbol = ticker["symbol"]
    name = ticker.get("name", symbol)

    result = fetch_price_yf(symbol)
    if result is None:
        print(f"[FAILED] {symbol} 读取失败")
        return None

    price, prev = result
    change = price - prev
    pct = (change / prev) * 100 if prev != 0 else 0

    return {
        "symbol": symbol,
        "name": name,
        "price": round(price, 2),
        "prev_close": round(prev, 2),
        "change": round(change, 2),
        "pct": round(pct, 2),
    }


def main():
    tickers = load_tickers()
    print(f"[INFO] 本次共需要更新 {len(tickers)} 个标的…")

    reports = []
    for t in tickers:
        r = process_one(t)
        if r:
            reports.append(r)

    if not reports:
        print("[ERROR] 没有任何成功的数据，终止。")
        return

    # 输出表格到 console（GitHub Actions 日志）
    print("\n=== Price Report ===")
    for r in reports:
        print(
            f"{r['name']} ({r['symbol']}): {r['price']} | "
            f"Prev {r['prev_close']} | {r['change']} ({r['pct']}%)"
        )

    # 推送 Bark 汇总
    ts = datetime.now().strftime("%H:%M")
    summary = f"更新 {len(reports)} 个标的成功 ({ts})"
    push_bark(summary)


if __name__ == "__main__":
    main()
