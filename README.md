# Weather-Vane 🌤️

> **AI 论文每日推送系统** — 基于 Claude Code 原生 Skill 机制，每天定时抓取最新 AI 论文，自动生成中文摘要并推送。

---

## 功能概览

| Skill | 职责 |
|-------|------|
| `fetcher` | 从 arXiv / HuggingFace / Papers With Code 抓取当日论文 |
| `ranker` | 热度评分、主题分类、筛选 Top-N |
| `summarizer` | 生成每篇论文的 200 字中文摘要 |
| `storage` | 持久化到 SQLite，支持历史查询 |
| `notifier` | 推送日报（Telegram / Email / 本地 Markdown）|
| `daily-paper-push` | 主调度器，串联以上所有 Skill |

---

## 快速开始

### 1. 克隆并配置环境

```bash
git clone https://github.com/<your-org>/Weather-Vane.git
cd Weather-Vane

# 复制环境变量模板
cp .env.example .env
# 编辑 .env，填入 ANTHROPIC_API_KEY 等配置
```

### 2. 安装 Python 依赖

```bash
# 推荐使用 conda 环境
conda activate ai_base
pip install -r requirements.txt
```

### 3. 手动触发抓取

```bash
# 直接运行脚本（不依赖 Claude Code）
python .claude/skills/Fetcher/scripts/fetch.py --date 2026-04-30

# 跳过引用数补充（加快速度）
python .claude/skills/Fetcher/scripts/fetch.py --skip-citations
```

### 4. 通过 Claude Code Skill 触发

```bash
# 在 Claude Code 中手动调用
/fetcher 2026-04-30

# 运行完整推送流程
/daily-paper-push
```

### 5. 配置定时任务（Linux/macOS）

```bash
# 每日 08:00 UTC+8 自动运行
crontab -e
# 添加以下行：
0 8 * * * cd /path/to/Weather-Vane && claude -p "运行每日论文推送"
```

---

## 项目结构

```
Weather-Vane/
├── .claude/
│   └── skills/
│       ├── daily-paper-push/   # Skill 0: 主调度器
│       ├── Fetcher/            # Skill 1: 论文抓取
│       │   ├── SKILL.md
│       │   ├── examples/
│       │   │   └── sample-output.json
│       │   ├── scripts/
│       │   │   └── fetch.py
│       │   └── tests/
│       │       └── test_fetch.py
│       ├── ranker/             # Skill 2: 过滤排名
│       ├── summarizer/         # Skill 3: 摘要生成
│       ├── storage/            # Skill 4: 数据存储
│       └── notifier/           # Skill 5: 推送通知
├── agent_plan/                 # 设计文档
│   ├── AI_Paper_Daily_Push_Plan.md
│   └── skills/
│       └── Fetcher.md
├── data/                       # 运行时数据（.gitignore 部分忽略）
│   ├── papers.db               # SQLite 持久化
│   └── YYYY-MM-DD-raw.json     # 每日中间产物
├── reports/                    # 每日本地日报
│   └── YYYY-MM-DD.md
├── .env.example                # 环境变量模板
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 数据流

```
Scheduler (cron)
    │
    ▼
daily-paper-push (Orchestrator)
    │
    ├─► fetcher     → data/YYYY-MM-DD-raw.json
    ├─► ranker      → data/YYYY-MM-DD-ranked.json
    ├─► summarizer  → data/YYYY-MM-DD-summarized.json
    ├─► storage     → data/papers.db
    └─► notifier    → reports/YYYY-MM-DD.md / Telegram / Email
```

---

## 环境变量说明

| 变量 | 必填 | 说明 |
|------|:----:|------|
| `ANTHROPIC_API_KEY` | ✅ | Claude API 密钥 |
| `SEMANTIC_SCHOLAR_API_KEY` | ❌ | 有 key 则引用数限速更宽松 |
| `TELEGRAM_BOT_TOKEN` | ❌ | Telegram Bot 推送 |
| `TELEGRAM_CHAT_ID` | ❌ | Telegram 目标 Chat ID |
| `EMAIL_SMTP_HOST` | ❌ | SMTP 服务器（如 smtp.gmail.com）|
| `EMAIL_SMTP_PORT` | ❌ | SMTP 端口（默认 587）|
| `EMAIL_USER` | ❌ | 发件人邮箱 |
| `EMAIL_PASSWORD` | ❌ | 发件人密码（建议用应用专用密码）|
| `EMAIL_TO` | ❌ | 收件人邮箱 |

---

## 技术栈

| 组件 | 技术 |
|------|------|
| Skill 运行时 | Claude Code 原生 Skill 机制 |
| 定时调度 | Linux cron |
| HTTP 客户端 | Python `httpx`（异步） |
| Feed 解析 | `feedparser` |
| 数据存储 | SQLite3 + JSON 归档 |
| 推送通知 | `smtplib` / `python-telegram-bot` |
| 测试框架 | `pytest` + `respx` |

---

## 实施进度

- [x] Skill 1 Fetcher — SKILL.md 入口文件
- [x] Skill 1 Fetcher — examples/sample-output.json
- [x] Skill 1 Fetcher — scripts/fetch.py
- [ ] Skill 1 Fetcher — tests/test_fetch.py
- [ ] Skill 2 ranker
- [ ] Skill 3 summarizer
- [ ] Skill 4 storage
- [ ] Skill 5 notifier
- [ ] Skill 0 daily-paper-push（Orchestrator）
- [ ] cron 定时配置与端到端测试

---

## 注意事项

- **arXiv 限速**：单 IP 每秒不超过 3 次请求，`fetch.py` 内置限速
- **费用估算**：摘要生成每篇约 $0.01–0.03，每日 15 篇约 $0.3–0.5
- **时区**：arXiv 使用 UTC，系统统一以 UTC+8 判断"当日"
- **数据安全**：`.env` 已加入 `.gitignore`，请勿将密钥提交到版本库

---

## License

MIT
