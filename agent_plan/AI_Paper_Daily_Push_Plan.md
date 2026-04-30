# AI 论文每日推送工具 — 多 Skill Agent 计划

## 项目概述

基于 **Claude Code 原生 Skill 机制**驱动的多 Skill Agent 系统，每天定时抓取最新人工智能领域论文，自动生成中文摘要并推送给用户。

每个功能单元是一个标准 Claude Code Skill：`.claude/skills/<name>/SKILL.md` + 辅助脚本。Claude 读取 Skill 指令后自主调用脚本完成任务，无需额外 Agent 框架。

---

## Skill 机制说明

### Claude Code Skill 的标准结构

```
.claude/skills/<skill-name>/
├── SKILL.md          ← 必须。YAML frontmatter（元数据）+ Markdown 指令体
├── scripts/          ← 可选。Claude 执行的辅助脚本
│   └── main.py
├── examples/         ← 可选。示例输出，帮助 Claude 理解预期格式
│   └── sample.md
└── templates/        ← 可选。输出模板
    └── report.md
```

### SKILL.md Frontmatter 关键字段

```yaml
---
name: skill-name           # 技能标识符，用于调用
description: ...           # 触发时机描述，Claude 依此决定何时使用
argument-hint: "[参数]"    # 参数提示
allowed-tools: WebFetch Bash Read Write   # 限制可用工具
context: fork              # fork = 在独立 subagent 中运行
effort: high               # 推理深度
---
```

### 调用方式

- **自动触发**：Claude 根据 `description` 字段判断何时调用
- **手动触发**：`/skill-name [参数]`
- **Orchestrator 调度**：主 Skill 通过 `context: fork` 启动子 Skill

---

## 系统架构

```
┌──────────────────────────────────────────────────────┐
│              Scheduler（cron 定时触发）                │
│         每日 08:00 执行: claude -p "运行每日论文推送"   │
└─────────────────────┬────────────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────────────┐
│          Skill: daily-paper-push  (Orchestrator)      │
│   .claude/skills/daily-paper-push/SKILL.md            │
│   context: fork  |  按顺序调用下列各 Skill              │
└───┬──────────────┬──────────────┬────────────────────┘
    │              │              │
    ▼              ▼              ▼
┌────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
│Skill 1 │  │ Skill 2  │  │ Skill 3  │  │ Skill 4  │  │ Skill 5  │
│fetcher │  │  ranker  │  │summarizer│  │ storage  │  │ notifier │
│论文抓取 │  │ 过滤排名  │  │ 摘要生成  │  │ 数据存储  │  │ 推送通知  │
└────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘
```

**数据流**：`fetcher` 输出 JSON → `ranker` 过滤排序 → `summarizer` 生成摘要 → `storage` 持久化 → `notifier` 推送日报

---

## Skill 详细设计

### Skill 1 — 论文抓取 (fetcher)

**Skill 路径**：`.claude/skills/fetcher/`

**SKILL.md frontmatter**：
```yaml
---
name: fetcher
description: 从 arXiv、HuggingFace Daily Papers 抓取当日最新 AI 论文元数据。当需要获取今日 AI 论文列表时使用。
argument-hint: "[YYYY-MM-DD]"
allowed-tools: WebFetch Bash Read Write
context: fork
effort: high
---
```

**辅助脚本**：
- `scripts/fetch.py`（每日多源并发抓取、去重、标准化输出）
- `scripts/hot_papers.py`（历史热榜工具，按需手动调用，不接入主流水线）

**数据源**：arXiv API / HuggingFace Daily Papers（内含 GitHub 链接和 Stars）/ Semantic Scholar（引用数，可选）

**输出**：`data/YYYY-MM-DD-raw.json`，每条记录含 `id / title / authors / abstract / url / pdf_url / categories / hf_upvotes / github_stars / code_url / citation_count`

**详细计划**：见 `agent_plan/skills/Fetcher.md` 及 `.claude/skills/Fetcher/SKILL.md`

---

### Skill 2 — 过滤与排名 (ranker)

**Skill 路径**：`.claude/skills/ranker/`

**SKILL.md frontmatter**：
```yaml
---
name: ranker
description: 对论文列表进行去重、热度评分、主题分类和重要性排序，筛选每类 Top-N。当需要从原始论文列表中筛选精华时使用。
argument-hint: "[raw-json-path]"
allowed-tools: Bash Read Write
context: fork
---
```

**辅助脚本**：`scripts/rank.py`

**评分公式**：
```
score = hf_upvotes × 2.0 + github_stars × 0.05 + citation_count × 0.5
```

**策略**：
- 硬过滤：hf_upvotes / github_stars / citation_count 三项全为 0 的论文丢弃
- 主题分类：LLM / 多模态 / AI Agent / 计算机视觉 / 强化学习 / 其他
- 按 score 降序截取 Top-N（默认 Top-20，可通过 `$ARGUMENTS` 传入覆盖）

**输出**：`data/YYYY-MM-DD-ranked.json`

---

### Skill 3 — 摘要生成 (summarizer)

**Skill 路径**：`.claude/skills/summarizer/`

**SKILL.md frontmatter**：
```yaml
---
name: summarizer
description: 对论文列表中的每篇论文生成中文摘要，包含核心问题、方法、结论和意义。当需要为论文生成中文摘要时使用。
argument-hint: "[ranked-json-path]"
allowed-tools: Read Write
effort: high
---
```

**指令体**（SKILL.md body）直接内嵌 Prompt 模板，Claude 逐篇处理：
```
对每篇论文按以下格式生成 200 字以内中文摘要：
1. 核心问题（1句）
2. 主要方法（2-3句）
3. 关键结论/指标（1-2句）
4. 实际意义（1句）
```

**输出**：`data/YYYY-MM-DD-summarized.json`（在 ranked JSON 中追加 `summary_zh` 字段）

---

### Skill 4 — 数据存储 (storage)

**Skill 路径**：`.claude/skills/storage/`

**SKILL.md frontmatter**：
```yaml
---
name: storage
description: 将处理完成的论文数据持久化到 SQLite 数据库，支持历史查询和去重判断。当需要保存或查询论文数据时使用。
argument-hint: "[summarized-json-path]"
allowed-tools: Bash Read Write
---
```

**辅助脚本**：`scripts/save.py`（写入 SQLite，表：`papers(id, title, authors, abstract, summary_zh, url, date, categories, score, code_url)`）

**输出**：写入 `data/papers.db`，同时保留 `data/YYYY-MM-DD-summarized.json` 归档

---

### Skill 5 — 推送通知 (notifier)

**Skill 路径**：`.claude/skills/notifier/`

**SKILL.md frontmatter**：
```yaml
---
name: notifier
description: 将今日 AI 论文日报推送给用户（Email / Telegram / 本地文件）。当需要发送论文日报时使用。
argument-hint: "[date]"
allowed-tools: Bash Read Write
---
```

**辅助脚本**：`scripts/notify.py`（支持 Email SMTP / Telegram Bot / 本地 Markdown）

**模板文件**：`templates/report.md`（日报 Markdown 模板）

**推送渠道**（可配置）：Email（SMTP）/ Telegram Bot / 本地 `reports/YYYY-MM-DD.md`

**日报格式示例**：
```
📅 AI 论文日报 — 2026-04-29

🔥 今日精选 (共 15 篇)

【LLM】
1. 《...》
   👥 作者：...  📁 arXiv:2401.xxxxx
   📝 摘要：...
   🔗 [论文链接] | [PDF] | [代码]

【多模态】
...
```

---

### Skill 0 — 主调度器 (daily-paper-push)

**Skill 路径**：`.claude/skills/daily-paper-push/`

**SKILL.md frontmatter**：
```yaml
---
name: daily-paper-push
description: 执行完整的 AI 论文每日推送流程：抓取→排名→摘要→存储→推送。当用户要求"推送今日论文"或定时任务触发时使用。
argument-hint: "[YYYY-MM-DD]"
allowed-tools: Bash Read Write
context: fork
effort: high
---
```

**指令体**：按顺序依次调用 fetcher → ranker → summarizer → storage → notifier，并在每步失败时记录错误并继续（除 fetcher 全空时终止）。

---

## 项目目录结构

```
.claude/
├── skills/
│   ├── daily-paper-push/       # Skill 0: 主调度器（Orchestrator）
│   │   └── SKILL.md
│   ├── fetcher/                # Skill 1: 论文抓取
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       └── fetch.py
│   ├── ranker/                 # Skill 2: 过滤排名
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       └── rank.py
│   ├── summarizer/             # Skill 3: 摘要生成
│   │   └── SKILL.md
│   ├── storage/                # Skill 4: 数据存储
│   │   ├── SKILL.md
│   │   └── scripts/
│   │       └── save.py
│   └── notifier/               # Skill 5: 推送通知
│       ├── SKILL.md
│       ├── scripts/
│       │   └── notify.py
│       └── templates/
│           └── report.md
├── agent_plan/
│   ├── AI_Paper_Daily_Push_Plan.md    # 本文件（总计划）
│   └── skills/
│       ├── Fetcher.md                 # Skill 1 详细设计文档
│       └── Ranker.md                  # Skill 2 详细设计文档
data/
├── papers.db                          # SQLite 持久化
└── YYYY-MM-DD-*.json                  # 每日中间产物
reports/
└── YYYY-MM-DD.md                      # 每日本地报告
.env                                   # 环境变量（不入 git）
.env.example                           # 环境变量示例
```

---

## 技术栈

| 组件 | 技术选型 |
|------|---------|
| **Skill 运行时** | Claude Code（原生 Skill 机制） |
| **定时调度** | Linux cron（`claude -p "运行每日论文推送"`） |
| **HTTP 抓取脚本** | Python 3.11 + httpx（异步） |
| **数据解析** | feedparser（arXiv Atom）/ json |
| **数据存储** | SQLite3（内置）+ JSON 归档 |
| **推送通知脚本** | Python + smtplib / python-telegram-bot |
| **配置管理** | python-dotenv + .env |
| **Skill 工具权限** | `WebFetch` / `Bash` / `Read` / `Write` |

---

## 环境变量 (.env)

```bash
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_USER=...
EMAIL_PASSWORD=...
EMAIL_TO=...
```

---

## 实施阶段

### Phase 1 — 基础 Skill 骨架（第 1-2 天）
- [x] 创建 `.claude/skills/Fetcher/SKILL.md`，编写 frontmatter 和抓取指令
- [x] 编写 `Fetcher/scripts/fetch.py`（arXiv + HF 双源抓取）
- [x] 编写 `Fetcher/scripts/hot_papers.py`（历史热榜独立工具）
- [ ] 手动触发 `/fetcher` 验证输出 JSON 格式正确
- [ ] 创建 `.claude/skills/storage/SKILL.md` + `save.py`，验证 SQLite 写入

### Phase 2 — 核心处理 Skill（第 3-4 天）
- [ ] 创建 `.claude/skills/Ranker/SKILL.md` + `rank.py`，验证排名逻辑
- [ ] 创建 `.claude/skills/summarizer/SKILL.md`，验证中文摘要生成质量

### Phase 3 — 推送与编排（第 5-6 天）
- [ ] 创建 `.claude/skills/notifier/SKILL.md` + `notify.py`（先实现本地文件输出）
- [ ] 创建 `.claude/skills/daily-paper-push/SKILL.md`（Orchestrator，串联所有 Skill）
- [ ] 配置 cron：`0 8 * * * claude -p "运行每日论文推送"`
- [ ] 端到端测试

### Phase 4 — 推送渠道与优化（后续）
- [ ] notifier 接入 Telegram Bot
- [ ] notifier 接入 Email SMTP
- [ ] 支持用户关键词订阅过滤（传入 `$ARGUMENTS`）
- [ ] Docker 容器化（包含 Claude Code CLI）

---

## 风险与注意事项

- **arXiv API 限流**：单 IP 每秒请求不超过 3 次，`fetch.py` 需加 rate limiter
- **Claude 摘要费用**：每篇约 0.01-0.03 USD，每日 15 篇约 $0.3-0.5
- **Skill 工具权限**：`Bash` 工具需在 Claude Code 权限配置中显式允许
- **时区处理**：arXiv 使用 UTC，`fetch.py` 需转换为本地时区判断"当日"
- **推送稳定性**：建议 Telegram / Email 主渠道 + 本地 `reports/` 文件双重保障
