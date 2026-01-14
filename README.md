# stock-alerts
中文财经预警 Early Warning for Chinese Financial Information
# 📈 AI-stock-monitor: Global Intelligence System
### (A-Shares / HK / US Stocks)

[English](#english) | [中文说明](#chinese)

---

<a name="english"></a>
## 🚀 Project Overview (English)
**AI Stock Master V2** is a professional-grade automated market intelligence system. Built on a serverless architecture using **GitHub Actions**, it provides 24/7 monitoring and buy-side analyst-level insights for A-shares, Hong Kong, and US stock markets.

### ✨ Key Capabilities
* **Global Multi-Market Tracking**: Seamlessly monitors Shanghai (SS), Shenzhen (SZ), Hong Kong (HK), and US exchanges.
* **Buy-Side Intelligence**: Integrates **Alibaba Qwen-Max/Plus** LLMs to generate high-density reports (approx. 150 words) covering macro policy, industry trends, and fundamental catalysts.
* **Pre-Market Briefing**: Automatically synthesizes the last 24h global news into a clean report before market open.
* **Smart Volatility Alerts**: Real-time tracking with 3% and 6% thresholds, triggering automated AI causal analysis.
* **Stateful Monitoring**: Maintains a local state to prevent redundant notifications within the same trading day.

---

<a name="chinese"></a>
## 🚀 项目简介 (中文)
**AI-stock-monitor** 是一款专业级的全球市场自动化情报系统。基于 **GitHub Actions** 的无服务器架构，实现对 A股、港股及美股市场的 24/7 全天候监控，并提供买方研究员级别的深度洞察。

### ✨ 核心功能
* **全球多市场追踪**：完美支持沪深 (SS/SZ)、港股 (HK) 及美股市场。
* **买方级 AI 洞察**：集成 **通义千问 (Qwen-Max/Plus)** 大模型，生成涵盖宏观政策、行业动态及基本面的深度报告（约 150 字）。
* **盘前深度汇总**：开盘前自动抓取全球过去 24 小时资讯，生成逻辑闭环的盘前简报。
* **智能异动告警**：实时监控股价波动，设定 3%/6% 阶梯阈值，自动触发 AI 归因分析。
* **状态化管理**：自动记录每日告警级别，确保同级别异动不重复推送，拒绝信息轰炸。

---

## 🛠️ Setup & Configuration / 配置指南

### 1. Stock Symbols / 代码规范
Please ensure symbols in `data/watchlist.csv` follow these formats:
请确保 `data/watchlist.csv` 中的代码符合以下格式：

| Market / 市场 | Format / 格式 | Example / 示例 |
| :--- | :--- | :--- |
| **Shanghai / 上证** | `Code.SS` | `600519.SS` |
| **Shenzhen / 深证** | `Code.SZ` | `000001.SZ` |
| **Hong Kong / 港股** | `Code.HK` | `0700.HK` |
| **US / 美股** | `Symbol` | `NVDA`, `AAPL` |

### 2. GitHub Secrets / 环境变量
Configure the following in **Settings > Secrets and variables > Actions**:
请在仓库设置中配置以下密钥：
* `BARK_URL`: Your Bark push endpoint (e.g., `https://api.day.app/KEY/`)
* `DASHSCOPE_API_KEY`: Alibaba DashScope (Qwen) API Key.

---

## 📂 Project Architecture / 项目架构
* `.github/workflows/ai-stock-monitor.yml`: Automated pipeline (runs every 5m).
* `main_scheduler.py`: The "Brain" - handles fetching, analysis, and scheduling.
* `data/watchlist.csv`: Your tracking list.
* `data/alert_state.json`: Daily status cache (auto-generated).

---
## 📅 Scheduling Logic / 调度逻辑
* **CN/HK Pre-market**: 08:30 CST
* **US Pre-market**: 08:30 EST (21:30 CST)
* **Market Monitoring**: Active during official trading hours for all three regions.

*Developed for disciplined and intelligent investing.*
