import os
import pandas as pd
import requests
import dashscope
from dashscope import Generation

# -----------------------------
# 读取 watchlist
# -----------------------------
WATCHLIST_PATH = "data/watchlist.csv"
df = pd.read_csv(WATCHLIST_PATH)

# -----------------------------
# 配置 DashScope API
# -----------------------------
dashscope.api_key = os.environ.get("DASHSCOPE_API_KEY")

# 对应你提供的 Base URL（无需改）
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

# -----------------------------
# 触发“重大风险”自动切换 Plus 的关键词
# -----------------------------
RISK_KEYWORDS = [
    "暴跌", "闪崩", "监管调查", "财务造假", "停牌", "破产", "诉讼",
    "重磅消息", "黑天鹅", "地缘冲突", "制裁", "限售", "高层变动"
]

def should_use_plus(text):
    """判断是否需要切换到 Qwen-Plus"""
    return any(kw in text for kw in RISK_KEYWORDS)

# -----------------------------
# 获取新闻（使用 Yahoo Finance 免费新闻源）
# -----------------------------
def fetch_news(symbol, market):
    """
    获取最新 5 条新闻
    symbol: 股票代码
    market: US, CN, HK
    """
    # Yahoo Finance 格式映射
    m = {
        "US": "",
        "CN": ".SS",
        "HK": ".HK"
    }
    code = symbol + m.get(market.upper(), "")

    url = f"https://query1.finance.yahoo.com/v1/finance/search?q={code}"

    try:
        r = requests.get(url, timeout=10)
        data = r.json()

        if "news" not in data:
            return []

        # 返回最多 5 条新闻标题 + 链接
        return [
            {"title": n.get("title"), "link": n.get("link")}
            for n in data["news"][:5]
        ]
    except Exception:
        return []

# -----------------------------
# 调用通义千问 AI 分析新闻内容
# -----------------------------
def ai_analyze(news_list, symbol, market):
    """
    对新闻列表做 AI 中文总结
    """

    if not news_list:
        return f"{symbol}（{market}）暂无新闻。"

    titles = "\n".join([f"- {n['title']}" for n in news_list])

    prompt = f"""
你是一名专业金融分析师。请用 **中文** 分析下面这只股票的最新新闻，内容包括：

1. 关键事件总结  
2. 对价格波动可能的影响  
3. 是否存在潜在风险（如监管、财务、行业变化）  
4. 投资者下一步应该重点关注哪些信息  

股票代码：{symbol}（{market}）
相关新闻标题如下：
{titles}

请给出严谨、简短、专业的分析。
"""

    # 判断是否切换 Plus
    model = "qwen-plus" if should_use_plus(titles) else "qwen-flash"

    messages = [{"role": "user", "content": prompt}]

    resp = requests.post(
        BASE_URL,
        json={
            "model": model,
            "messages": messages,
            "temperature": 0.2
        },
        headers={"Authorization": f"Bearer {dashscope.api_key}"}
    )

    try:
        return resp.json()["choices"][0]["message"]["content"]
    except:
        return f"分析失败：{resp.text}"


# -----------------------------
# 主执行流程
# -----------------------------
def run():
    final_output = []

    for _, row in df.iterrows():
        symbol = row["symbol"]
        market = row["market"]

        news_list = fetch_news(symbol, market)
        analysis = ai_analyze(news_list, symbol, market)

        part = f"""
===============================
📌 股票：{symbol}（{market}）
===============================
{analysis}
"""
        final_output.append(part)

    return "\n".join(final_output)


if __name__ == "__main__":
    print(run())
