# Storage Skill 设计文档

**Skill 路径**：`.claude/skills/Storage/`
**对应总计划**：`agent_plan/AI_Paper_Daily_Push_Plan.md` — Skill 4

---

## 1. 职责

系统的**数据管理与持久化中心**。负责将携带了摘要信息的 `summarized.json` 数据写入本地 SQLite 数据库，并管理推送历史记录。

主要功能：
- **数据持久化**：将每篇论文的元数据（标题、作者、摘要、URL 等）以及生成的中文摘要（短摘要和详细介绍）保存到 `papers.db` 中。
- **推送记录管理**：记录某篇论文在什么时间作为什么类型的板块（每日、周热门、月热门）推送过，防止同一篇论文被重复推送到同一热门板块。
- **去重检查接口**：供 `ranker` 在生成报告时调用，过滤掉之前已经推送过的周/月热门论文。

---

## 2. Skill 文件结构

```
.claude/skills/Storage/
├── SKILL.md                  ← 必须。frontmatter 元数据 + 调用说明
└── scripts/
    └── save.py               ← 驱动脚本，封装了所有对 SQLite 的操作
```

---

## 3. 数据库表设计

数据库文件位置：`data/papers.db`

### 3.1 论文主表 `papers`
用于存储所有获取并处理过的论文详细信息。

```sql
CREATE TABLE IF NOT EXISTS papers (
    id              TEXT PRIMARY KEY,  -- 论文唯一标识，如 arxiv:2501.XXXXX
    title           TEXT,
    authors         TEXT,              -- JSON 数组序列化字符串
    abstract        TEXT,
    summary_zh      TEXT,              -- 短摘要
    detail_zh       TEXT,              -- 详细介绍（仅热门论文有值）
    url             TEXT,
    pdf_url         TEXT,
    code_url        TEXT,
    hf_upvotes      INTEGER,
    pwc_stars       INTEGER,
    citation_count  INTEGER,
    categories      TEXT,              -- JSON 数组序列化字符串
    score           REAL,
    published_date  TEXT,              -- 论文发布日期
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP -- 入库时间
);
```

### 3.2 推送历史表 `push_history`
用于记录哪些论文在何时作为什么类型被推送过，防止周/月热门重复推送。

```sql
CREATE TABLE IF NOT EXISTS push_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id        TEXT NOT NULL,     -- 关联 papers.id
    push_date       TEXT NOT NULL,     -- 推送日期 YYYY-MM-DD
    push_type       TEXT NOT NULL,     -- 类型：'daily_robot', 'daily_ai', 'weekly_hot', 'monthly_hot'
    UNIQUE(paper_id, push_type),       -- 核心去重约束：同一论文同一类型只推一次
    FOREIGN KEY(paper_id) REFERENCES papers(id)
);
```

---

## 4. `save.py` 接口设计

脚本 `save.py` 既可以处理 `summarized.json` 文件进行批量导入，也可以作为命令行工具被其他 Skill 调用。

### 4.1 参数设计

```bash
# 场景 1：整体保存（流水线最后一步调用，解析 summarized.json 入库并记录推送历史）
python3 scripts/save.py --save data/2026-04-30-summarized.json

# 场景 2：去重检查（供 ranker 调用，判断某论文是否已作为周/月热门推送过）
python3 scripts/save.py --check-pushed arxiv:2501.12345 --type weekly_hot
# 输出：True 或 False

# 场景 3：手动标记（通常在 --save 时自动完成，也支持手动调用）
python3 scripts/save.py --mark-pushed arxiv:2501.12345 --type monthly_hot --date 2026-04-30
```

### 4.2 保存逻辑流程 (`--save`)

1. 连接 SQLite `data/papers.db`，若不存在则初始化表结构。
2. 读取输入的 `YYYY-MM-DD-summarized.json` 文件。
3. 开启数据库事务。
4. 遍历四个板块 (`daily_robot`, `daily_ai`, `weekly_hot`, `monthly_hot`)：
   - 对于每篇论文，使用 `INSERT OR REPLACE INTO papers` 更新论文主表。
   - 使用 `INSERT OR IGNORE INTO push_history` 记录该论文的此次推送类型和日期。
5. 提交事务，打印保存统计信息。

---

## 5. SKILL.md frontmatter

```yaml
---
name: storage
description: 将生成的 summarized.json 论文数据持久化到 SQLite 数据库，并记录推送历史用于去重。也提供查询接口判断论文是否已推送过。
argument-hint: "[summarized-json-path]"
allowed-tools: Bash Read Write
context: fork
effort: low
---
```

---

## 6. 异常处理

| 场景 | 处理方式 |
|------|---------|
| 数据库文件无法创建/无权限 | 报错退出，提示检查文件系统权限 |
| 传入的 JSON 文件不存在 | 报错退出，提示文件路径有误 |
| JSON 文件格式损坏 | 报错退出，提示重新运行 Summarizer |
| 论文数据字段缺失 | 允许字段为 NULL 或提供默认值（如 0 或空字符串），使用 `.get()` 安全提取 |
| 重复推送同一天的数据 | `INSERT OR REPLACE` 和 `INSERT OR IGNORE` 机制保证幂等性，不会插入重复脏数据 |

---

## 7. 实施检查清单

- [x] 创建 `.claude/skills/Storage/SKILL.md`
- [x] 创建 `.claude/skills/Storage/scripts/save.py`
  - [x] 实现 `init_db()` 初始化数据库与表
  - [x] 实现 `--save` 逻辑：解析 JSON 并执行 `INSERT OR REPLACE` 和 `INSERT OR IGNORE`
  - [x] 实现 `--check-pushed` 逻辑：查询 `push_history` 表并返回 True/False
  - [x] 实现 `--mark-pushed` 逻辑
- [x] 创建 `.claude/skills/Storage/tests/test_save.py`
  - [x] 测试表创建
  - [x] 测试数据解析与入库
  - [x] 测试去重逻辑是否生效
  - [x] 测试命令行参数解析
- [x] 在 `ranker` 脚本中实际接入 `save.py --check-pushed` (注：`rank.py` 中已通过原生 `sqlite3` 实现 `get_pushed_ids`，逻辑等价且更高效)
