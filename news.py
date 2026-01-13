import requests
import os
import csv
import urllib.parse

# --- 环境配置 ---
WATCHLIST_PATH = os.getenv("WATCHLIST_PATH", "data/watchlist.csv")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
BARK_URL = os.getenv("BARK_URL")

def load_symbols():
    """从 CSV 读取所有自选股代码"""
    symbols = []
    if not os.path.exists(WATCHLIST_PATH): return []
    with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("symbol"): symbols.append(row["symbol"].strip())
    return symbols

def fetch_global_news(symbol):
    """抓取自选股最新动态"""
    try:
        url = f"https://query1.finance.yahoo.com/v1/finance/search?q={symbol}"
        r = requests.get(url, timeout=10)
        news_data = r.json().get("news", [])
        # 提取标题，如果是美股，这里拿到的会是英文标题
        return [f"[{symbol}] {n['title']}" for n in news_data[:5]]
    except:
        return []

def ai_consolidate_report(news_content):
    """调用 AI 进行中文去重汇总"""
    if not DASHSCOPE_API_KEY or not news_content: return None
    
    # 明确要求 AI 将英文内容转化为中文汇总
    prompt = (
        f"以下是自选股的最新动态（包含英文新闻）：\n{news_content}\n"
        "任务：1. 翻译并剔除重复信息；2. 仅保留对股价有潜在重大影响的干货；"
        "3. 按公司分类，用精炼的中文列表输出汇总报告（每条不超过50字）。"
    )
    
    try:
        url = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
        headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
        # 汇总使用更聪明的 qwen-plus 模型
        data = {"model": "qwen-plus", "input": {"prompt": prompt}}
        r = requests.post(url, headers=headers, json=data, timeout=30)
        return r.json()['output']['text']
    except Exception as e:
        print(f"AI 汇总失败: {e}")
        return None

def main():
    print("正在生成盘前深度汇总...")
    symbols = load_symbols()
    if not symbols: return

    all_raw_news = []
    for s in symbols:
        all_raw_news.extend(fetch_global_news(s))
    
    # 基础去重
    unique_raw_news = "\n".join(list(set(all_raw_news)))
    
    # AI 深度总结
    summary = ai_consolidate_report(unique_raw_news)
    
    if summary:
        print("汇总完成，发送推送...")
        safe_title = urllib.parse.quote("☕ 自选股盘前早报", safe='')
        safe_body = urllib.parse.quote(summary, safe='')
        requests.get(f"{BARK_URL.rstrip('/')}/{safe_title}/{safe_body}", timeout=10)
    else:
        print("未发现重要新闻，跳过推送。")

if __name__ == "__main__":
    main()
