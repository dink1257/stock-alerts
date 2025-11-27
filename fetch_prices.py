import yfinance as yf
import pandas as pd
import os
from openai import OpenAI
from news import fetch_news

# ========== AI 初始化 ==========
client = OpenAI(
    api_key=os.getenv("DASHSCOPE_API_KEY"),
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

FLASH_MODEL = "qwen-turbo"     # 轻量便宜模型
PLUS_MODEL = "qwen-plus"       # 高质量模型

RISK_KEYWORDS = [
    "暴跌", "闪崩", "监管", "财务造假", "裁员", "破产",
    "利润下滑", "业绩预警", "经营风险", "财报", "审查", "制裁"
]

# ========== 核心：智能模型切换 ==========
def choose_model(text):
    if any(k in text for k in RISK_KEYWORDS):
        return PLUS_MODEL
    return FLASH_MODEL


def ai_analyze(news_list, symbol, remark):
    """
    使用 AI 对新闻做中文风险摘要（自动模型切换）
    """
    if not news_list:
        return "未找到相关新闻。"

    news_text = "\n".join([f"- {n['title']}" for n in news_list])

    model = choose_model(news_text)

    prompt = f"""
你是一个专业投资分析助手。现在给你股票的描述与相关新闻标题。
股票：{symbol}
备注：{remark}
新闻：
{news_text}

请用中文总结风险和机遇，只保留最关键3~5点。
"""

    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}]
    )

    return resp.choices[0].message.content


def fetch_price(symbol, market):
    """
    获取股价
    """
    if market == "HK":
        yf_symbol = symbol + ".HK"
    elif market == "CN":
        yf_symbol = symbol + ".SS"
    else:
        yf_symbol = symbol

    data = yf.Ticker(yf_symbol).history(period="1d")

    if data.empty:
        return None

    price = float(data["Close"][-1])
    change = float(data["Close"][-1] - data["Open"][-1])
    pct = (change / data["Open"][-1]) * 100

    return price, pct


# ========== 主程序 ==========
def main():
    df = pd.read_csv("data/watchlist.csv")

    for _, row in df.iterrows():
        symbol = row["symbol"]
        market = row["market"]
        remark = row["remark"]

        price_data = fetch_price(symbol, market)
        if not price_data:
            print(f"{symbol} 数据获取失败")
            continue

        price, pct = price_data

        print("\n=====================================")
        print(f"{symbol} - {remark}")
        print(f"价格：{price:.2f}  涨跌：{pct:.2f}%")

        # 抓新闻
        news_list = fetch_news(remark.split(" - ")[0])

        # AI 分析新闻
        analysis = ai_analyze(news_list, symbol, remark)

        print("【AI 风险摘要】")
        print(analysis)


if __name__ == "__main__":
    main()



 
