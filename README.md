# 🌍 Global Macro & Asset Monitor (CIO Edition) 
### 全球全资产 CIO 智能监控实验室



**Version:** 4.0.0 (Batching & Advanced Layout)  
**Core Engine:** Alibaba Qwen-Max/Plus (DashScope)  
**Delivery:** Bark Push (iOS/macOS)  
**License:** MIT

---

## 📖 Introduction / 简介

This is an AI-driven, professional-grade market monitoring system designed for **"Chief Investment Officers" (CIOs)**. It tracks global multi-asset movements in real-time, providing deep logical attribution and strategic guidance rather than simple price alerts.

这是一个基于 AI 驱动的“买方投资总监级”全球市场监控系统。它能够自动跟踪全球核心资产异动，并提供深度逻辑研判。系统不仅播报涨跌，更专注于分析宏观定价逻辑、多空博弈边际以及大级别趋势机会。

---

## ✨ Key Features / 核心功能

### 1. Multi-Asset Coverage / 全球全资产覆盖
* **Stocks / 股票**: A-Shares (CN) & US Stocks with $\alpha/\beta$ attribution analysis. (A股及美股异动分析)
* **Futures / 期货**: Gold, Oil, Copper, and Index Futures with trend & inventory logic. (金/油/铜及股指期货趋势研判)
* **Macro Anchors / 宏观锚点**: Dollar Index (DXY), US 10Y Yield (^TNX), Offshore RMB (CNY=X). (美元/美债/汇率定价锚点)
* **Crypto / 数字资产**: Bitcoin (BTC) as a global risk-appetite indicator. (比特币等风险偏好风向标)

### 2. CIO-Level Intelligence / 投资总监级研判
* **Strategic Direction / 多空判别**: Distinguishes between "Single-side trends" and "Wide fluctuations". (明确区分单边趋势与宽幅震荡)
* **Opening Guidance / 开仓指引**: Evaluates whether current volatility possesses "large-cycle" entry value. (评估是否具备大级别周期开仓价值)
* **Contextual Attribution / 深度归因**: Identifies drivers from macro policy, geopolitical events, or stock-specific fundamentals. (识别宏观政策、地缘或基本面驱动力)

### 3. Smart Delivery / 智能交付系统
* **Dynamic Thresholds / 分级预警**: 
    * 🌐 **Macro**: 0.5% (High sensitivity / 极度灵敏)
    * 🌋 **Futures**: 1.5% (Trend trigger / 趋势启动)
    * 🔔 **Stocks**: 3.0% (Noise filtering / 过滤杂音)
* **Batch & Chunking / 分批汇总**: Automatically bundles alerts into groups of 6 to prevent notification fatigue. (每 6 条异动自动合并推送，拒绝信息轰炸)
* **Cooldown Mechanism / 冷却机制**: 1-hour "silence" per asset per level to ensure focus. (标的 1 小时冷却逻辑，防止反复横跳干扰)

---

## 🛠️ Configuration / 配置说明

### `data/watchlist.csv`
Add your assets here. Use `=F` for futures. (在此处添加标的，期货需带 `=F` 后缀)
```csv
symbol,name
GC=F,黄金期货
NQ=F,纳指100期货
DX-Y.NYB,美元指数
600519.SS,贵州茅台
