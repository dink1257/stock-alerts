import requests, os, csv, pytz, json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote as url_quote

# --- 配置区 ---
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY")
WATCHLIST_PATH = "data/watchlist.csv"
STATE_PATH = "data/alert_state.json"

UA_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.4472.124 Safari/537.36'}
# Yahoo 备用 host，query1 被限流时自动切换
YAHOO_HOSTS = ["https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"]


def is_us_dst(now):
    """自动判定美股夏令时 (3月第二个周日 02:00 至 11月第一个周日 02:00)"""
    year = now.year
    # 3月8日~14日之间必有第二个周日
    mar8 = datetime(year, 3, 8, 2, tzinfo=now.tzinfo)
    dst_start = mar8 + timedelta(days=(6 - mar8.weekday()) % 7)
    # 11月1日~7日之间必有第一个周日
    nov1 = datetime(year, 11, 1, 2, tzinfo=now.tzinfo)
    dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7)
    return dst_start <= now < dst_end


def ai_decision(symbol, name, industry, p_meta, news, m_context, is_forced):
    mode_tag = "定时强制扫描" if is_forced else "实时异动审计"
    prompt = (
        "### 角色定位\n"
        "你是一位资深买方投资总监。你的审计报告必须结构严谨，严禁偏差，拒绝空话。\n"
        "\n"
        "### 核心审计数据\n"
        f"- 宏观盘面参考：{m_context}\n"
        f"- 异动目标标的：{name} ({symbol}) | 实时波动：{p_meta['pct']:+.2f}%\n"
        f"- 模式：【{mode_tag}】\n"
        "\n"
        "### 严格审计指令（三段式）\n"
        "\n"
        "1. 【盘面情况审计】：\n"
        "   - 必须点评上证指数/恒生指数走势。\n"
        "   - 审计成交量（对比前五日均值）判断是放量还是缩量，定性市场情绪。\n"
        "\n"
        "2. 【品种归因审计】（核心）：\n"
        f"   - 仅针对标的 {name} ({symbol}) 本次 {p_meta['pct']:+.2f}% 的波动进行归因。\n"
        "   - 股权审计：审计前五大股东、董监高近期是否有增减持、质押、冻结等意志体现。若无明确信息，此项直接略过。\n"
        f"   - 基本面审计：审计该品种行业政策变动（参考标签：{industry}）、供求关系、个股经营订单及财报预期。若无明确信息，此项直接略过。\n"
        "   - 定性分析：判断本次波动是跟随大盘(Beta)还是独立的个股逻辑(Alpha)。\n"
        "\n"
        "3. 【操作建议】：\n"
        "   - 给出明确的【买入/卖出/持仓】建议。\n"
        "   - 明确指出波动的方向、幅度预判及持续性。\n"
        "\n"
        "---\n"
        "[实时情报输入]：\n"
        f"{news}\n"
    )
    if not DASHSCOPE_API_KEY:
        return "未配置 DASHSCOPE_API_KEY，跳过 AI 审计"
    headers = {"Authorization": f"Bearer {DASHSCOPE_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": "qwen-max", "input": {"messages": [{"role": "user", "content": prompt}]},
               "parameters": {"result_format": "message", "temperature": 0.1}}
    try:
        res = requests.post("https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",
                            headers=headers, json=payload, timeout=60)
        res.raise_for_status()
        return res.json()['output']['choices'][0]['message']['content']
    except Exception as e:
        print(f"AI 审计调用失败 ({symbol}): {e}")
        return f"AI 审计服务繁忙: {str(e)}"


def get_quote(symbol):
    """单个 symbol 行情抓取。

    2026-10 修复：Yahoo v7 quote 批量接口已下线（返回 401 Unauthorized），
    改用 v8 chart 单 symbol 接口，仍可用且无需登录。
    """
    path_symbol = url_quote(symbol, safe='')
    for host in YAHOO_HOSTS:
        url = f"{host}/v8/finance/chart/{path_symbol}?interval=1d&range=5d"
        try:
            resp = requests.get(url, headers=UA_HEADERS, timeout=15)
            if resp.status_code == 429:
                print(f"{symbol} 触发限流，换 host 重试")
                continue
            resp.raise_for_status()
            result = resp.json().get('chart', {}).get('result')
            if not result:
                continue
            meta = result[0].get('meta', {})
            curr = meta.get('regularMarketPrice')
            prev = meta.get('chartPreviousClose')
            if curr is None or prev is None or prev == 0:
                continue
            return {
                'symbol': symbol,
                'regularMarketPrice': curr,
                'regularMarketPreviousClose': prev,
                'regularMarketChangePercent': meta.get('regularMarketChangePercent', 0),
            }
        except Exception as e:
            print(f"{symbol} 行情获取失败 ({host}): {e}")
            continue
    return None


def get_batch_quotes(symbols):
    """并发批量抓取：v8 不支持多 symbol，改用线程池并发，70+ 标的约 10 秒完成"""
    if not symbols:
        return {}
    result = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        for symbol, q in zip(symbols, ex.map(get_quote, symbols)):
            if q:
                result[symbol] = q
            else:
                print(f"{symbol} 行情缺失，本轮跳过")
    print(f"行情抓取完成: {len(result)}/{len(symbols)}")
    return result


def load_state():
    """兼容旧版 state 文件结构 (last_pct -> last_triggered_pct)，避免 KeyError 导致整轮静默跳过"""
    try:
        with open(STATE_PATH, 'r', encoding='utf-8') as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"state 文件不存在或损坏，将重建: {e}")
        raw = {}
    last_triggered = raw.get("last_triggered_pct") or raw.get("last_pct") or {}
    return {"last_triggered_pct": last_triggered}


def push_feishu(title, industry, content, is_forced):
    if not FEISHU_WEBHOOK:
        print(f"未配置 FEISHU_WEBHOOK，跳过推送: {title}")
        return
    try:
        reason = "定时扫描" if is_forced else "异动触发"
        r = requests.post(FEISHU_WEBHOOK, json={
            "msg_type": "interactive",
            "card": {
                "header": {"title": {"tag": "plain_text", "content": title},
                           "template": "orange" if is_forced else "blue"},
                "elements": [{"tag": "markdown",
                              "content": f"**[触发原因]**: {reason}\n**[所属标签]**: {industry}\n---\n{content}"}]
            }
        }, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"飞书推送失败: {e}")


def main():
    bj_tz = pytz.timezone("Asia/Shanghai")
    now = datetime.now(bj_tz)
    h, m = now.hour, now.minute
    print(f"财经监控cio版 V8.6.0 | {now.strftime('%Y-%m-%d %H:%M:%S')}")

    # 1. 窗口判定逻辑 (资源节省)
    is_dst = is_us_dst(now)
    is_a_pre = (h == 8 and m >= 30) or (h == 9 and m <= 15)
    is_a_hk_trade = (h in [10, 11, 13, 14]) or (h == 9 and m >= 30) or (h == 15 and m <= 10)

    # 美股窗口动态适配
    if is_dst:
        is_us_active = (h == 21 and m >= 30) or h in [22, 23, 0, 1, 2, 3]
        is_us_forced = (h == 21 and m <= 45) or (h == 4 and 0 <= m <= 15)
    else:
        is_us_active = (h == 22 and m >= 30) or h in [23, 0, 1, 2, 3, 4]
        is_us_forced = (h == 22 and m <= 45) or (h == 5 and 0 <= m <= 15)

    is_forced = is_a_pre or (h == 12 and 45 <= m <= 59) or is_us_forced

    if not (is_forced or is_a_hk_trade or is_us_active):
        print(f"非监控时段 ({h:02}:{m:02})，系统进入静默。")
        return

    # 2. 批量行情获取
    if not os.path.exists(WATCHLIST_PATH):
        print(f"找不到 {WATCHLIST_PATH}")
        return
    with open(WATCHLIST_PATH, 'r', encoding='utf-8') as f:
        stocks = list(csv.DictReader(f))

    symbols = [s['symbol'] for s in stocks]
    all_quotes = get_batch_quotes(symbols)
    if not all_quotes:
        print("未获取到任何行情数据，本轮终止（请检查网络/Yahoo 接口状态）")
        return

    # 大盘上下文获取
    m_ctx_data = get_batch_quotes(["000001.SS", "^HSI", "^GSPC"])
    m_ctx = " | ".join([f"{k}: {v.get('regularMarketPrice', 'N/A')}"
                        f"({v.get('regularMarketChangePercent', 0):+.2f}%)"
                        for k, v in m_ctx_data.items()])
    print(f"大盘上下文: {m_ctx or '获取失败'}")

    state = load_state()
    last_triggered = state["last_triggered_pct"]

    # 3. 审计循环
    audited = 0
    for s in stocks:
        symbol, name, industry = s['symbol'], s['name'], s['industry']
        q = all_quotes.get(symbol)
        if not q:
            continue

        try:
            curr = q.get('regularMarketPrice')
            prev = q.get('regularMarketPreviousClose')
            if curr is None or prev is None or prev == 0:
                continue

            pct = (curr - prev) / prev * 100
            last_p = last_triggered.get(symbol)

            # 异动判定逻辑
            should_audit = (is_forced
                            or (last_p is None and abs(pct) >= 3.0)
                            or (last_p is not None and abs(pct) >= abs(last_p) * 2))

            if should_audit:
                print(f"审计中: {name} ({pct:+.2f}%)")
                # 资讯获取（params 自动处理中文编码）
                search_q = f"{name} {symbol} {industry} 股东 政策"
                try:
                    news_r = requests.get(
                        "https://query1.finance.yahoo.com/v1/finance/search",
                        params={"q": search_q, "newsCount": 6},
                        headers=UA_HEADERS, timeout=10).json()
                    news_list = [n.get('title', '') for n in news_r.get('news', [])]
                    news_text = " | ".join(news_list) or "暂无相关资讯"
                except Exception as e:
                    print(f"{symbol} 资讯获取失败: {e}")
                    news_text = "资讯获取失败"

                content = ai_decision(symbol, name, industry, {"pct": pct}, news_text, m_ctx, is_forced)
                push_feishu(f"【CIO审计】{name} ({pct:+.2f}%)", industry, content, is_forced)
                last_triggered[symbol] = pct
                audited += 1
        except Exception as e:
            # 不再静默吞异常，打出日志方便排查
            print(f"{symbol} 处理异常: {e}")
            continue

    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False)
    print(f"任务全部结束，本轮审计 {audited} 个标的")


if __name__ == "__main__":
    main()
