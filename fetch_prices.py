import requests
from yahooquery import Ticker
import csv
import os
import time
import dashscope

dashscope.api_key = os.getenv("DASHSCOPE_API_KEY")
BARK_URL = os.getenv("BARK_URL")


# ---------------------------
#  Bark 推送
# ---------------------------
def bark_push(title, body):
    if not BARK_URL:
        print("BARK_URL not set")
        return
    url = f"{BARK_URL}/{title}/{body}"
    try:
        requests.get(url, timeout=5)
    except:
        pass


# ---------------------------
#  免费新闻源（简版）
# ---------------------------
def fetch_free_news(symbol):
    url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}"
    try:
        r = requests.get(url, timeout=5).json()
        if "news" in r:
            items = r["news"]
            if items:
                return items[0].get("title", "（新闻标题获取失败）")
    except:
        return None
    return None


# ---------------------------
#  通义 AI 分析
# ---------------------------
def ai_analyze(text, high_risk=False):
    model = "qwen-plus" if high_risk else "qwen-turbo"

    prompt = f"下面是股票相关新闻或市场情况，请用中文给我简短分析风险和原因：{text}"

    response = dashscope.Generation.call(
        model=model,
        prompt=prompt
    )

    return response["output"]["text"]


# ---------------------------
#  主逻辑：价格检查
# ---------------------------
def check_prices():
    with open("data/watchlist.csv", "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row["symbol"]
            market = row["market"]
            alert_up = float(row["alert_up"])
            alert_down = float(row["alert_down"])

            # yahooquery 代码
            y_symbol = symbol
            if market == "HK":
                y_symbol = symbol + ".HK"
            elif market == "CN":
                y_symbol = symbol + ".SS"

            t = Ticker(y_symbol)
            info = t.price

            if y_symbol not in info:
                print(f"无法获取 {y_symbol} 数据")
                continue

            price = info[y_symbol].get("regularMarketPrice")
            change_pct = info[y_symbol].get("regularMarketChangePercent")

            if change_pct is None:
                continue

            # 触发阈值？
            if abs(change_pct) >= alert_up:
                direction = "上涨" if change_pct > 0 else "下跌"

                # 1）抓新闻
                news = fetch_free_news(symbol)

                # 判断是否高风险
                high_risk = direction == "下跌" and abs(change_pct) >= alert_down

                # 2）AI 分析
                ai_result = ai_analyze(news if news else "没有新闻", high_risk=high_risk)

                # 3）推送
                title = f"{symbol} 异动：{direction} {change_pct:.2f}%"
                body = f"{news or '无相关新闻'} | AI解读：{ai_result}"

                bark_push(title, body)
                print(title)
                print(body)


if __name__ == "__main__":
    check_prices()
