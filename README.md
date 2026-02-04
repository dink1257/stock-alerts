# 🌍 Global Macro & Asset Monitor (CIO Edition)

### 全球全资产 CIO 智能监控实验室

**Version:** 6.6.0 (High-Efficiency Asymmetric Edition)

**Core Engine:** Alibaba Qwen-Max/Plus (DashScope)

**Delivery:** Bark Push (iOS/macOS)

**License:** MIT

---

## 📖 Introduction / 简介

This is an AI-driven, professional-grade market monitoring system designed for **"Chief Investment Officers" (CIOs)**. It tracks global multi-asset movements in real-time, providing deep logical attribution and strategic guidance rather than simple price alerts.

这是一个基于 AI 驱动的“买方投资总监级”全球市场监控系统。它能够自动跟踪全球核心资产异动，并提供深度逻辑研判。系统不仅播报涨跌，更专注于分析宏观定价逻辑、多空博弈边际以及大级别趋势机会。

---

## ✨ System Parameters / 系统参数说明

### 1. Dynamic Thresholds / 分级预警阈值

System logic adjusts sensitivity based on asset volatility profiles:
系统根据资产属性自动切换预警灵敏度：

* 🌐 **Macro (宏观锚点)**: **0.5%** *Covers DXY, US10Y, CNY/USD. High sensitivity to catch global liquidity shifts.* *(覆盖美元指数、美债收益率、人民币汇率。极高灵敏度捕捉流动性拐点。)*
* 🌋 **Futures (期货/大宗)**: **1.5%** *Covers Gold, Crude Oil, Index Futures. Designed to catch trend start-up.* *(覆盖黄金、原油、股指期货。旨在捕捉趋势行情启动。)*
* 🔔 **Stocks (股票异动)**: **3.0%** *Covers Global Equities. Filters out daily market noise.* *(覆盖全球个股。有效过滤日内杂波噪音。)*

### 2. Monitoring Schedule / 运行调度 (UTC+8)

Optimized for the 2,000-min free tier on GitHub Actions:
针对 GitHub 每月 2,000 分钟免费额度优化的非对称调度：

| Time Block (Beijing Time) | Frequency | Focus |
| --- | --- | --- |
| **09:30 - 16:00** | **Every 6 mins** | A-Shares & HK Market (火力全开) |
| **16:00 - 24:00** | **Every 20 mins** | US Pre-market & Early Session (活跃时段) |
| **00:00 - 09:30** | **2 Snapshots** | US Closing & Global Settlement (深夜静默) |

---

## 🧠 Core Intelligence / 核心智能逻辑

* **Batch & Chunking (分批汇总)**: Bundles up to 6 alerts into a single, beautifully formatted message to prevent notification fatigue. (每 6 条异动自动合并推送，拒绝信息轰炸。)
* **Cooldown Mechanism (冷却机制)**: 1-hour "silence" per asset per level. Only level-ups (e.g., from 3% to 6%) can break the cooldown. (标的 1 小时冷却逻辑，防止临界点反复横跳。)
* **Contextual Attribution (深度归因)**: AI distinguishes between Macro  (policy/rates) and Alpha  (earnings/news). (AI 自动拆解宏观系数  与个股超额收益 。)

---

## 🛠️ Configuration / 配置指引

### `data/watchlist.csv`

Add symbols here. Use `=F` suffix for futures logic. (期货需带 `=F` 后缀)

```csv
symbol,name
GC=F,黄金期货
NQ=F,纳指100期货
DX-Y.NYB,美元指数
600519.SS,贵州茅台
NVDA,英伟达

```

### GitHub Secrets

* `DASHSCOPE_API_KEY`: Alibaba Qwen API (通义千问)
* `BARK_URL`: Your private Bark Push URL (Bark 推送地址)

---

## 📊 Notification Preview / 推送预览

> **📊 市场异动内参 (1/1)**
> 🌐 **美元指数 +0.52%** (现价: 103.4)
> **研判**：利率路径预期修正引发。强美元将压制黄金及成长股估值，关注晚间非农数据传导。
> 🌋 **黄金期货 -1.20%** (现价: 2024.5)
> **研判**：受美元走强及避险溢价回落压制。目前处于震荡下沿，关注 2010 支撑，不宜盲目追空。

---

## ⚖️ Disclaimer / 免责声明

**English:**
This project is for research and educational purposes only. AI-generated insights are based on historical data and model inference, and do not constitute financial advice. Market investments involve risks. The author shall not be held responsible for any investment losses or decisions made based on this system.

**中文:**
本项目仅供科研与学习使用。AI 生成的内容基于历史数据与模型推理，不构成任何形式的投资建议或操作指南。市场有风险，投资需谨慎。作者不对使用本系统导致的任何投资损失承担责任，亦不对 AI 研判的准确性做出法律保证。
