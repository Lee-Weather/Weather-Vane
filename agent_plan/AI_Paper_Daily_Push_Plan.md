# AI 论文每日推送工具 — 多 Skill Agent 计划

## 项目概述

基于 **Claude Code 原生 Skill 机制**驱动的多 Skill Agent 系统，每天定时抓取最新**人工智能**和**具身智能/机器人控制**领域论文，按主题分类、生成中文摘要，并以固定日报格式推送给用户。

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

**数据流**：
1. `fetcher` 抓取 cs.AI + cs.RO 论文 → `data/YYYY-MM-DD-raw.json`
2. `ranker` 按主题分类（机器人 / AI）+ 筛选每日 Top-N + 选取周/月热门 → `data/YYYY-MM-DD-ranked.json`
3. `summarizer` 生成中文摘要（每日论文：短摘要；热门论文：详细介绍） → `data/YYYY-MM-DD-summarized.json`
4. `storage` 持久化 + 记录推送历史（用于去重周/月热门） → `data/papers.db`
5. `notifier` 组装四板块日报并推送 → `reports/YYYY-MM-DD.md`

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

**配置文件**：`config.yaml`（搜索主题，当前配置 `cs.AI` + `cs.RO`，修改此文件即可调整抓取领域）

**辅助脚本**：
- `scripts/fetch.py`（每日多源并发抓取、去重、标准化输出）
- `scripts/hot_papers.py`（历史热榜工具，供 ranker 调用获取周/月热门数据）

**数据源**：arXiv API / HuggingFace Daily Papers / Papers With Code（代码链接 + Stars）/ Semantic Scholar（引用数，可选）

**输出**：`data/YYYY-MM-DD-raw.json`，每条记录含 `id / title / authors / abstract / url / pdf_url / categories / hf_upvotes / pwc_stars / code_url / citation_count`

**已实现**，详见 `.claude/skills/Fetcher/SKILL.md`

---

### Skill 2 — 过滤与排名 (ranker)

**Skill 路径**：`.claude/skills/ranker/`

**SKILL.md frontmatter**：
```yaml
---
name: ranker
description: 对论文列表按主题分类（机器人/AI）、热度评分、排名筛选。产出每日 Top-N 和周/月热门候选。当需要从原始论文列表中筛选精华时使用。
argument-hint: "[raw-json-path]"
allowed-tools: Bash Read Write
context: fork
---
```

**辅助脚本**：`scripts/rank.py`

**评分公式**：
```
score = hf_upvotes × 2.0 + pwc_stars × 0.05 + citation_count × 0.5
```

**核心逻辑**：

1. **主题分类**：按论文 `categories` 字段将论文分为两组
   - **机器人组**：包含 `cs.RO` 的论文（具身智能、机器人控制方向）
   - **AI 组**：包含 `cs.AI` 但不含 `cs.RO` 的论文（通用 AI 方向）
   - 同时包含两者的，优先归入机器人组

2. **每日筛选**（基于昨天 `raw.json`）：
   - 机器人组：按 score 降序取 **Top-15**
   - AI 组：按 score 降序取 **Top-5**

3. **周热门**（基于过去 7 天数据）：
   - 调用 `hot_papers.py --days 7` 或从近 7 天 `raw.json` 汇总
   - 取 score 最高的 **1 篇**
   - 查询 `storage`（`papers.db`）的推送历史，若该篇已推过则取第 2 名，依此类推

4. **月热门**（基于过去 30 天数据）：
   - 调用 `hot_papers.py --days 30` 或从近 30 天 `raw.json` 汇总
   - 取 score 最高的 **1 篇**
   - 同样查推送历史去重，避免重复推送

**输出**：`data/YYYY-MM-DD-ranked.json`，结构如下：
```json
{
  "date": "2026-04-30",
  "daily_robot": [ /* 15 篇机器人论文 */ ],
  "daily_ai": [ /* 5 篇 AI 论文 */ ],
  "weekly_hot": { /* 1 篇周热门 */ },
  "monthly_hot": { /* 1 篇月热门 */ }
}
```

---

### Skill 3 — 摘要生成 (summarizer)

**Skill 路径**：`.claude/skills/summarizer/`

**SKILL.md frontmatter**：
```yaml
---
name: summarizer
description: 对论文生成中文摘要。每日论文生成短摘要，周/月热门生成详细介绍。当需要为论文生成中文摘要时使用。
argument-hint: "[ranked-json-path]"
allowed-tools: Read Write
effort: high
---
```

**两级摘要策略**：

**A. 短摘要**（用于每日 15+5 篇论文）：
```
对每篇论文生成 150 字以内中文摘要，格式：
1. 核心问题（1句）
2. 方法与创新点（1-2句）
3. 关键结论/指标（1句）
```
追加字段：`summary_zh`

**B. 详细介绍**（用于周/月热门各 1 篇）：
```
对该论文生成 500-800 字中文详细介绍，格式：
1. 研究背景与动机（2-3句）
2. 核心问题定义（1-2句）
3. 方法论详解（3-5句，包含技术细节）
4. 实验结果与关键指标（2-3句）
5. 与现有工作对比（1-2句）
6. 实际意义与未来展望（1-2句）
7. 推荐理由（1句）
```
追加字段：`detail_zh`

**输出**：`data/YYYY-MM-DD-summarized.json`（在 ranked JSON 各板块中追加摘要字段）

---

### Skill 4 — 数据存储 (storage)

**Skill 路径**：`.claude/skills/storage/`

**SKILL.md frontmatter**：
```yaml
---
name: storage
description: 将论文数据持久化到 SQLite，记录推送历史用于去重。支持写入、查询推送记录、判断论文是否已推过。
argument-hint: "[summarized-json-path]"
allowed-tools: Bash Read Write
---
```

**辅助脚本**：`scripts/save.py`

**数据库表设计**：

```sql
-- 论文主表
CREATE TABLE papers (
    id          TEXT PRIMARY KEY,  -- arxiv:XXXX.XXXXX
    title       TEXT,
    authors     TEXT,              -- JSON 数组序列化
    abstract    TEXT,
    summary_zh  TEXT,              -- 短摘要
    detail_zh   TEXT,              -- 详细介绍（仅热门论文有值）
    url         TEXT,
    pdf_url     TEXT,
    categories  TEXT,              -- JSON 数组序列化
    score       REAL,
    code_url    TEXT,
    published_date TEXT,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

-- 推送历史表（用于周/月热门去重）
CREATE TABLE push_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id    TEXT NOT NULL,     -- 关联 papers.id
    push_date   TEXT NOT NULL,     -- 推送日期 YYYY-MM-DD
    push_type   TEXT NOT NULL,     -- 'daily_robot' / 'daily_ai' / 'weekly_hot' / 'monthly_hot'
    UNIQUE(paper_id, push_type)   -- 同一论文同一类型只推一次
);
```

**对外接口**（供 ranker 调用）：
- `save.py --save <json-path>`：写入论文数据
- `save.py --check-pushed <paper-id> --type weekly_hot`：查询某篇是否已作为周热门推过
- `save.py --mark-pushed <paper-id> --type monthly_hot --date 2026-04-30`：标记为已推送

**输出**：写入 `data/papers.db`，同时保留 `data/YYYY-MM-DD-summarized.json` 归档

---

### Skill 5 — 推送通知 (notifier)

**Skill 路径**：`.claude/skills/notifier/`

**SKILL.md frontmatter**：
```yaml
---
name: notifier
description: 将论文日报按四板块格式组装并推送（15篇机器人+5篇AI+周热门+月热门）。当需要发送论文日报时使用。
argument-hint: "[date]"
allowed-tools: Bash Read Write
---
```

**辅助脚本**：`scripts/notify.py`（支持 Email SMTP / Telegram Bot / 本地 Markdown）

**模板文件**：`templates/report.md`（日报 Markdown 模板）

**推送渠道**（可配置，优先级从高到低）：
1. Telegram Bot（即时推送）
2. Email SMTP（备选）
3. 本地 `reports/YYYY-MM-DD.md`（兜底，始终生成）

**核心职责**：
1. 读取 `data/YYYY-MM-DD-summarized.json`
2. 按模板组装四板块日报
3. 调用 `storage` 标记本次推送的论文（`push_history`）
4. 通过配置的渠道推送

---

#### 日报格式（四板块）

```markdown
📅 AI & 机器人论文日报 — 2026-04-30

═══════════════════════════════════════

🤖 板块一：昨日机器人/具身智能论文（15 篇）

1. 《论文标题》
   📝 核心问题 ... 方法 ... 结论 ...
   🔗 论文 | PDF | 代码

2. 《论文标题》
   � ...

... (共 15 篇)

═══════════════════════════════════════

🧠 板块二：昨日 AI 论文精选（5 篇）

1. 《论文标题》
   📝 核心问题 ... 方法 ... 结论 ...
   🔗 论文 | PDF | 代码

... (共 5 篇)

═══════════════════════════════════════

� 板块三：本周最热论文（1 篇）

### 《论文标题》

� 作者：Author One, Author Two 等
� 发布日期：2026-04-28
🔥 HF 点赞：128 | ⭐ Stars：256 | 📖 引用：12

📝 详细介绍：
  研究背景与动机 ...
  核心问题 ...
  方法论详解 ...
  实验结果 ...
  与现有工作对比 ...
  实际意义 ...
  推荐理由 ...

🔗 论文 | PDF | 代码

═══════════════════════════════════════

🏆 板块四：本月最热论文（1 篇）

### 《论文标题》

👥 作者：...
📅 发布日期：...
🔥 HF 点赞：... | ⭐ Stars：... | 📖 引用：...

📝 详细介绍：
  （同上格式，500-800 字）

🔗 论文 | PDF | 代码

═══════════════════════════════════════
📊 统计：共推送 22 篇 | 机器人 15 篇 | AI 5 篇 | 周热门 1 篇 | 月热门 1 篇
```

**边界处理**：
- 若昨日机器人论文不足 15 篇，有多少推多少，标注实际篇数
- 若昨日 AI 论文不足 5 篇，同上
- 若周热门和月热门选中同一篇论文，月热门顺延至第 2 名
- 周/月热门的 `detail_zh` 由 summarizer 生成，notifier 直接使用

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
│   ├── Fetcher/                # Skill 1: 论文抓取（已实现）
│   │   ├── SKILL.md
│   │   ├── config.yaml          # 搜索主题配置（cs.AI + cs.RO）
│   │   └── scripts/
│   │       ├── fetch.py
│   │       └── hot_papers.py
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
- **Claude 摘要费用**：短摘要每篇约 $0.01-0.03，详细介绍约 $0.05-0.10；每日 20 篇短摘要 + 2 篇详细介绍 ≈ $0.3-0.8
- **Skill 工具权限**：`Bash` 工具需在 Claude Code 权限配置中显式允许
- **时区处理**：arXiv 使用 UTC，`fetch.py` 需转换为本地时区判断"当日"
- **推送稳定性**：建议 Telegram / Email 主渠道 + 本地 `reports/` 文件双重保障
