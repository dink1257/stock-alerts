# 🌍 OpenClaw: AI-Driven Multi-Asset CIO Decision Hub
# 🌍 OpenClaw: AI 驱动的全资产买方总监决策中心

**Version:** 6.6.0 (Enterprise-Grade Audit Edition)  
**Core Logic:** Professional Buy-side CIO Perspective  
**Intelligence Base:** Alibaba Qwen-Max (DashScope Native)

---

## 💎 Project Vision / 项目愿景
**OpenClaw** is not a simple price alert tool; it is a **Digital Investment Committee**. It transforms raw market noise into high-fidelity strategic intelligence by combining global real-time data with the reasoning depth of a Chief Investment Officer (CIO).

**OpenClaw** 不仅仅是一个行情预警工具，它是一个**“数字投委会”**。它通过结合全球实时数据与投资总监（CIO）级别的推理深度，将杂乱的市场噪音转化为高保真的战略情报。

---

## 🚀 Key Functional Modules / 核心功能模块

### 1. Dual-Phase Compulsory Global Audit / 双阶段强制全量审计
* **Pre-Market Strategy (08:30 UTC+8):** A full-scale scan of global macro shifts, overnight US market impact, and domestic policy news to define the "Tone of the Day."  
    **盘前策略 (08:30):** 全面扫描全球宏观位移、美股隔夜影响及国内政策要闻，为当日交易“定调”。
* **Mid-Day Pivot Audit (12:45 UTC+8):** A deep dive into mid-day corporate filings, HK market sentiment, and A-share trend persistence before the afternoon session.  
    **午后转折审计 (12:45):** 在下午开盘前，深度穿透午间公司公告、港股情绪及 A 股趋势的延续性。

### 2. Multi-Asset Asymmetric Monitoring / 多资产非对称监控
* **Dynamic Sensitivity:** * **Forex/Macro (±1%):** High-frequency tracking of USD/CNH and DXY to capture liquidity inflection points.  
    * **Equities/Commodities (±3%):** Focused monitoring of A-shares, Global stocks, Gold, and Silver to filter out daily noise.  
* **动态灵敏度:** * **外汇/宏观 (±1%):** 高频追踪人民币汇率与美元指数，捕捉流动性拐点。
    * **权益/大宗 (±3%):** 聚焦 A 股、全球个股及贵金属，过滤日内无效波动。

### 3. "Shareholder Will" Deep Penetration / “股东意志”深度穿透
* **Strategic Audit:** Mandatory scanning for movements of Top 5 shareholders and C-suite executives (Buybacks/Selling).  
    **战略审计:** 强制扫描前五大股东及董监高的增减持动向。
* **Intent Attribution:** Distinguishing between "Strategic Bearishness" (capital exit) and "Strategic Bullishness" (bottom-fishing) based on fundamental valuation.  
    **意图定性:** 结合基本面估值，识别是“产业资本逃离”还是“战略性抄底”。

---

## 🛠️ Technical Framework Details / 技术框架细节

### 🏗️ System Architecture / 架构设计
1.  **Scheduler (GitHub Actions):** Serverless cron-jobs optimized for off-peak execution to ensure 100% reliability in task triggering.  
    **调度层:** 基于 GitHub Actions 的无服务器定时任务，针对高峰期进行了错峰优化，确保任务触发 100% 可靠。
2.  **Data Engine (YahooQuery & Global Search):** Hybrid data retrieval combining structured price feeds with unstructured global financial news (English & Chinese).  
    **数据引擎:** 混合数据获取模式，结合结构化行情流与非结构化全球财经资讯（中英文双语）。
3.  **Reasoning Core (Alibaba Qwen-Max):** A 120-second deep-reasoning window for each asset, utilizing the 2026-optimized prompt engineering for buy-side analysis.  
    **推理核心:** 为每个资产分配 120 秒的深度推理窗口，采用针对 2026 年买方逻辑优化的提示词工程。
4.  **State Management (JSON Persistence):** Persistent state tracking to prevent "notification fatigue" and ensure alerts only fire on meaningful trend changes.  
    **状态管理:** 持久化 JSON 状态追踪，防止“消息轰炸”，确保仅在趋势发生实质改变时推送。

### 🧠 Logic Flow / 逻辑流
`Trigger (Cron/Price) -> Data Aggregation -> Global News Search -> CIO Prompt Inference -> Multi-Dimensional Evaluation -> Feishu Delivery`  
`触发 (定时/股价) -> 数据聚合 -> 全网资讯搜索 -> 总监提示词推理 -> 多维评价 -> 飞书交付`

---

## 📊 Evaluation Standards / 研判输出标准
Every report delivered must meet the **"CIO Triple-Check"**:
每一份交付的报告必须满足**“总监三项审计”**：
1.  **Direction (方向):** Bullish/Bearish/Neutral. (看多/看空/中性)
2.  **Magnitude (幅度):** Expected volatility scale (Pulse/Trend/Reversal). (预计波动级别：脉冲/趋势/反转)
3.  **Persistence (持续性):** Short-term noise vs. Long-term structural change. (短期噪音 vs 长期结构性改变)

---

## 📋 Requirements & Setup / 配置要求
* **Secrets:** `FEISHU_WEBHOOK`, `DASHSCOPE_API_KEY`.
* **Data Source:** `data/watchlist.csv` (Supports `stock`, `forex` types).
* **Runtime:** Python 3.10+ on GitHub Ubuntu Runner.

---

## ⚖️ Disclaimer / 免责声明
This project is an AI-assisted research tool and does not constitute financial advice. The user is solely responsible for investment decisions.  
本项目为 AI 辅助研究工具，不构成投资建议。用户需对投资决策承担全部责任。
