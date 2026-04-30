# Ranker Skill 设计文档

**Skill 路径**：`.claude/skills/Ranker/`
**对应总计划**：`agent_plan/AI_Paper_Daily_Push_Plan.md` — Skill 2

---

## 1. 职责

系统的**质量过滤器与分发器**。读取 `fetcher` 输出的原始论文列表（`raw.json`），完成以下四项任务：

1. **主题分组**：按 `cs.RO`（机器人）和 `cs.AI`（AI）拆分为两组
2. **每日筛选**：机器人组 Top-15 + AI 组 Top-5
3. **周热门**：过去 7 天热度最高的 1 篇（已推过则顺延）
4. **月热门**：过去 30 天热度最高的 1 篇（已推过则顺延）

输出 `ranked.json` 供 `summarizer` 消费。

**核心原则**：宁可漏掉，不要刷屏。确保推送给用户的每篇都值得一读。

---

## 2. Skill 文件结构

```
.claude/skills/Ranker/
├── SKILL.md                  ← 必须。frontmatter 元数据 + 执行指令体
└── scripts/
    └── rank.py               ← 评分、分组、过滤、排名、周/月热门选取
```

**外部依赖**：
- `Fetcher/scripts/hot_papers.py`：调用其获取周/月热门数据
- `storage/scripts/save.py`：查询推送历史（周/月热门去重）

---

## 3. 输入 / 输出

### 输入

- **每日数据**：`data/YYYY-MM-DD-raw.json`（由 `fetcher` 生成）
- **周热门数据**：过去 7 天的 `raw.json` 或调用 `hot_papers.py --days 7`
- **月热门数据**：过去 30 天的 `raw.json` 或调用 `hot_papers.py --days 30`
- **推送历史**：`data/papers.db` 的 `push_history` 表（通过 `save.py --check-pushed` 查询）

每条论文记录包含：
```json
{
  "id": "arxiv:2401.xxxxx",
  "title": "...",
  "authors": [...],
  "abstract": "...",
  "hf_upvotes": 120,
  "pwc_stars": 256,
  "code_url": "https://github.com/xxx/yyy",
  "citation_count": 5,
  "categories": ["cs.AI", "cs.RO"],
  "published_date": "2026-04-30"
}
```

### 输出

`data/YYYY-MM-DD-ranked.json`，四板块结构：

```json
{
  "date": "2026-04-30",
  "daily_robot": [
    { "...原有字段...", "score": 285.3, "group": "robot", "rank": 1 }
  ],
  "daily_ai": [
    { "...原有字段...", "score": 120.5, "group": "ai", "rank": 1 }
  ],
  "weekly_hot": { "...原有字段...", "score": 450.0, "hot_type": "weekly" },
  "monthly_hot": { "...原有字段...", "score": 820.0, "hot_type": "monthly" }
}
```

---

## 4. 评分公式

```
score = hf_upvotes × 2.0 + pwc_stars × 0.05 + citation_count × 0.5
```

| 信号 | 权重 | 含义 |
|------|------|------|
| `hf_upvotes` | × 2.0 | HuggingFace 社区真实热度（最重要） |
| `pwc_stars` | × 0.05 | Papers With Code 代码关注度 |
| `citation_count` | × 0.5 | 学术引用影响力 |

---

## 5. 过滤规则

### 5.1 硬过滤（仅用于每日筛选，满足其一即可进入候选）

| 条件 | 说明 |
|------|------|
| `hf_upvotes >= 5` | HF 有人关注 |
| `pwc_stars >= 10` | 有代码且有人 Star |
| `citation_count >= 3` | 已有引用 |

> 三项全为 0 的论文直接丢弃（无任何热度信号，不值得推送）。

### 5.2 每日分组截取

按主题分组后，各组内按 score 降序：
- **机器人组**：截取 Top-15
- **AI 组**：截取 Top-5
- 不足时有多少输出多少

### 5.3 周/月热门去重

- 查询 `push_history` 表，跳过已作为 `weekly_hot` / `monthly_hot` 推过的论文
- 若周热门和月热门选中同一篇，月热门顺延至第 2 名

---

## 6. 主题分组

核心是把论文分为两组，对应日报的前两个板块：

| 分组 | 匹配规则 | 日报板块 |
|------|---------|----------|
| **机器人组** (`robot`) | `categories` 包含 `cs.RO` | 🤖 板块一（15 篇） |
| **AI 组** (`ai`) | `categories` 包含 `cs.AI` 且不含 `cs.RO` | 🧠 板块二（5 篇） |

> 同时包含 `cs.RO` + `cs.AI` 的论文，优先归入机器人组。

周/月热门不区分分组，从全部论文中按 score 排名。

---

## 7. `rank.py` 执行流程

```
Step 1: 读取 data/YYYY-MM-DD-raw.json
Step 2: 硬过滤 — 去除三项热度信号均为 0 的论文
Step 3: 计算 score = hf_upvotes×2 + pwc_stars×0.05 + citation_count×0.5
Step 4: 主题分组（按 categories 分为机器人组 / AI 组）
Step 5: 各组内按 score 降序，机器人组取 Top-15，AI 组取 Top-5
Step 6: 获取周热门（过去 7 天 score 最高 1 篇，查推送历史去重）
Step 7: 获取月热门（过去 30 天 score 最高 1 篇，查推送历史去重）
Step 8: 若周热门与月热门同一篇，月热门顺延
Step 9: 写入 data/YYYY-MM-DD-ranked.json
Step 10: 打印摘要统计
```

### 输出摘要示例

```
============================================================
✅ Ranker 完成 — 2026-04-30
============================================================
📥 原始论文：152 篇
🔍 硬过滤后：87 篇（丢弃 65 篇无热度信号）
📊 每日筛选：
   ├── 🤖 机器人组： 15 篇（候选 42 篇）
   └── 🧠 AI 组：      5 篇（候选 45 篇）
🔥 周热门：《Xxx Yyy Zzz》(score=450.0)
🏆 月热门：《Aaa Bbb Ccc》(score=820.0)
📄 输出路径：data/2026-04-30-ranked.json
============================================================
```

---

## 8. 参数设计

```bash
python3 scripts/rank.py --date 2026-04-30       # 指定日期（默认昨天 UTC+8）
python3 scripts/rank.py --robot-top 15           # 机器人组 Top-N（默认 15）
python3 scripts/rank.py --ai-top 5               # AI 组 Top-N（默认 5）
python3 scripts/rank.py --skip-weekly             # 跳过周热门选取
python3 scripts/rank.py --skip-monthly            # 跳过月热门选取
python3 scripts/rank.py --db-path data/papers.db  # 指定数据库路径
```

---

## 9. SKILL.md frontmatter

```yaml
---
name: ranker
description: >
  读取 fetcher 输出的原始论文 JSON，按主题分组（机器人 15 篇 / AI 5 篇），
  并选取周/月热门各 1 篇（查推送历史去重），输出 ranked.json。
  当需要从原始论文列表中筛选精华时使用。
argument-hint: "[YYYY-MM-DD]"
allowed-tools: Bash Read Write
context: fork
effort: medium
---
```

---

## 10. 错误处理

| 场景 | 处理方式 |
|------|----------|
| `raw.json` 不存在 | 报错退出，提示先运行 fetcher |
| `raw.json` 为空数组 | 输出空 ranked.json（四板块均为空），记录 WARN，退出码 0 |
| 硬过滤后某组不足数量 | 有多少输出多少，记录 WARN |
| 周/月热门无候选数据 | 对应字段输出 `null`，记录 WARN |
| `papers.db` 不存在（首次运行） | 跳过推送历史去重，直接取热度最高的 |
| 周热门与月热门撞号 | 月热门自动顺延至第 2 名 |
| 单篇处理异常 | 跳过该篇，继续处理其余 |

---

## 11. 实施检查清单

- [ ] 创建 `.claude/skills/Ranker/SKILL.md`
- [ ] 创建 `.claude/skills/Ranker/scripts/rank.py`
  - [ ] 实现 `load_raw(date)` 读取 raw.json
  - [ ] 实现 `hard_filter(papers)` 热度信号过滤
  - [ ] 实现 `compute_score(paper)` 评分公式
  - [ ] 实现 `classify_group(paper)` 主题分组（`robot` / `ai`）
  - [ ] 实现 `select_daily(papers)` 每日筛选（机器人 15 + AI 5）
  - [ ] 实现 `select_hot(days, hot_type, db_path)` 周/月热门选取（含推送历史去重）
  - [ ] 实现 `resolve_collision(weekly, monthly)` 周月撞号处理
  - [ ] 实现 `write_ranked(result, date)` 输出 ranked.json（四板块结构）
  - [ ] 实现 `print_summary(stats)` 控制台摘要
- [ ] 手动运行：`python3 rank.py --date 2026-04-30`，验证输出格式
- [ ] 验证 `summarizer` 可消费 `ranked.json` 四板块结构
- [ ] 验证周/月热门去重逻辑（连续两天运行，确认不重复推送）
