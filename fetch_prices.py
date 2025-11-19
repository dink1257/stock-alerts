import pandas as pd
import yfinance as yf
from datetime import datetime

# Load watchlist
df = pd.read_csv("watchlist.csv")

# Convert symbol for Yahoo Finance
def convert_symbol(symbol, market):
    if market == "CN":
        return symbol + ".SS"
    elif market == "HK":
        return symbol + ".HK"
    elif market == "US":
        return symbol
    elif market == "CRYPTO":
        return symbol  # Already like BTC-USD
    return symbol

df["yf_symbol"] = df.apply(lambda x: convert_symbol(x["symbol"], x["market"]), axis=1)

# Fetch data
results = []

for _, row in df.iterrows():
    symbol = row["yf_symbol"]
    raw = yf.Ticker(symbol).history(period="1d")

    if raw.empty:
        price = None
        change = None
    else:
        price = round(raw["Close"].iloc[-1], 2)
        prev_close = raw["Open"].iloc[-1]
        change = round((price - prev_close) / prev_close * 100, 2)

    results.append({
        "symbol": row["symbol"],
        "market": row["market"],
        "remark": row["remark"],
        "price": price,
        "change_%": change,
        "alert_up": row["alert_up"],
        "alert_down": row["alert_down"]
    })

out = pd.DataFrame(results)

# Generate markdown report
today = datetime.now().strftime("%Y-%m-%d")
md = f"# Daily Price Report ({today})\n\n"

for _, r in out.iterrows():
    md += f"### {r['symbol']} ({r['market']})\n"
    md += f"- {r['remark']}\n"
    md += f"- Price: {r['price']}\n"
    md += f"- Change: {r['change_%']}%\n"

    if r["change_%"] is not None:
        if r["change_%"] >= r["alert_up"]:
            md += f"  🚀 **上涨预警：涨幅超过 {r['alert_up']}%**\n"
        if r["change_%"] <= -r["alert_down"]:
            md += f"  ⚠️ **下跌预警：跌幅超过 {r['alert_down']}%**\n"

    md += "\n"

with open("daily_report.md", "w", encoding="utf-8") as f:
    f.write(md)

print("Report generated: daily_report.md")
