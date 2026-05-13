# Weather-Vane 🌤️

> **AI 论文每日推送系统** — 基于 Claude Code 原生 Skill 机制，每天定时抓取最新 AI 论文，利用 DeepSeek API 自动生成中文摘要并推送。

📖 **语言** | [English](./README.md) | 中文

---

## 功能概览

| Skill | 职责 |
|-------|------|
| `Fetcher` | 从 arXiv / HuggingFace / Semantic Scholar 抓取当日论文 |
| `Ranker` | 热度评分、主题分类、筛选 Top-N 及热门 |
| `Summarizer` | 使用 DeepSeek 生成每篇论文的深度中文摘要（支持超时自动重试与 fallback 兜底） |
| `Storage` | 持久化到 SQLite，支持推送历史查询去重 |
| `Notifier` | 推送日报（Telegram / Email / 本地 Markdown）|
| `Daily-Paper-Push` | 主调度器，串联以上所有 Skill |

---

## 快速开始

### 1. 克隆并配置环境

```bash
git clone https://github.com/<your-org>/Weather-Vane.git
cd Weather-Vane

# 复制环境变量模板
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY 等配置
```

### 2. 安装 Python 依赖

```bash
# 推荐使用 conda 环境
conda activate ai_base
pip install -r requirements.txt
```

### 3. 运行完整流水线

```bash
# 一键执行抓取、排名、摘要、入库到推送的全流程
python .claude/skills/Daily-Paper-Push/scripts/run_pipeline.py

# 或者指定特定日期执行
python .claude/skills/Daily-Paper-Push/scripts/run_pipeline.py --date 2026-04-30
```

### 4. 分步调试运行

```bash
# 直接分步运行各模块（用于调试或跳过某步骤）
python .claude/skills/Fetcher/scripts/fetch.py        --date 2026-04-30
python .claude/skills/Ranker/scripts/rank.py          --date 2026-04-30
python .claude/skills/Summarizer/scripts/summarize.py --date 2026-04-30
python .claude/skills/Storage/scripts/save.py         --save data/2026-04-30-summarized.json
python .claude/skills/Notifier/scripts/notify.py      --date 2026-04-30
```

---

## 环境变量说明

| 变量 | 必填 | 说明 |
|------|:----:|------|
| `DEEPSEEK_API_KEY` | ✅ | DeepSeek API 密钥 |
| `DEEPSEEK_BASE_URL` | ✅ | DeepSeek API 地址 |
| `DEEPSEEK_MODEL` | ✅ | DeepSeek 模型名（如 `deepseek-v4-pro`）|
| `SEMANTIC_SCHOLAR_API_KEY` | ❌ | 有 key 则引用数限速更宽松 |
| `TELEGRAM_BOT_TOKEN` | ❌ | Telegram Bot 推送 |
| `TELEGRAM_CHAT_ID` | ❌ | Telegram 目标 Chat ID |
| `EMAIL_SMTP_HOST` | ❌ | SMTP 服务器（如 smtp.gmail.com）|
| `EMAIL_SMTP_PORT` | ❌ | SMTP 端口（默认 587）|
| `EMAIL_USER` | ❌ | 发件人邮箱 |
| `EMAIL_PASSWORD` | ❌ | 发件人密码（建议用应用专用密码）|
| `EMAIL_TO` | ❌ | 收件人邮箱 |

---

## 实施进度

- [x] Skill 1 Fetcher — 数据抓取
- [x] Skill 2 Ranker — 过滤排名
- [x] Skill 3 Summarizer — 摘要生成（DeepSeek 接入，支持长文本深度解析与超时降级）
- [x] Skill 4 Storage — 数据库存储去重
- [x] Skill 5 Notifier — 渲染与多渠道推送
- [x] Skill 0 Daily-Paper-Push — 流水线调度与自动化

---

## License

MIT
