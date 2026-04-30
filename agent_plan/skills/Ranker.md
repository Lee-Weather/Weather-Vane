# Ranker Skill 设计文档

**Skill 路径**：`.claude/skills/Ranker/`
**对应总计划**：`agent_plan/AI_Paper_Daily_Push_Plan.md` — Skill 2

---

## 1. 职责

系统的**质量过滤器**。读取 `fetcher` 输出的原始论文列表（`raw.json`），通过热度评分、主题分类和阈值过滤，从 100~200 篇原始论文中精选出 10~20 篇值得推送的论文，输出 `ranked.json` 供 `summarizer` 消费。

**核心原则**：宁可漏掉，不要刷屏。确保推送给用户的每篇都值得一读。

---

## 2. Skill 文件结构

```
.claude/skills/Ranker/
├── SKILL.md                  ← 必须。frontmatter 元数据 + 执行指令体
└── scripts/
    └── rank.py               ← 评分、过滤、排名脚本
```

---

## 3. 输入 / 输出

### 输入

`data/YYYY-MM-DD-raw.json`（由 `fetcher` 生成）

每条记录包含：
```json
{
  "id": "arxiv:2401.xxxxx",
  "title": "...",
  "authors": [...],
  "abstract": "...",
  "hf_upvotes": 120,
  "github_stars": 256,
  "code_url": "https://github.com/xxx/yyy",
  "citation_count": 5,
  "categories": ["cs.AI", "cs.LG"],
  "published_date": "2026-04-30"
}
```

### 输出

`data/YYYY-MM-DD-ranked.json`

在原始字段基础上追加：
```json
{
  ...原有字段...,
  "score": 285.3,
  "topic": "LLM",
  "rank": 1
}
```

---

## 4. 评分公式

```
score = hf_upvotes × 2.0 + github_stars × 0.05 + citation_count × 0.5
```

| 信号 | 权重 | 含义 |
|------|------|------|
| `hf_upvotes` | × 2.0 | 社区真实热度（最重要） |
| `github_stars` | × 0.05 | 代码实用性和关注度 |
| `citation_count` | × 0.5 | 学术影响力 |

---

## 5. 过滤规则

### 5.1 硬过滤（必须满足其一才能进入候选）

| 条件 | 说明 |
|------|------|
| `hf_upvotes >= 5` | HF 有人关注 |
| `github_stars >= 10` | 有代码且有人 Star |
| `citation_count >= 3` | 已有引用 |

> 三项全为 0 的论文直接丢弃（无任何热度信号，不值得推送）。

### 5.2 软排序（在候选中按 score 降序）

按评分降序排列，截取 Top-N（默认 Top-20，可通过参数覆盖）。

---

## 6. 主题分类

根据 `categories` 和 `title` / `abstract` 关键词分类：

| 主题标签 | 匹配规则 |
|---------|---------|
| `LLM` | cs.CL / 关键词：language model, LLM, GPT, transformer |
| `多模态` | 关键词：multimodal, vision-language, VLM, image-text |
| `AI Agent` | 关键词：agent, tool use, planning, reasoning |
| `计算机视觉` | cs.CV / 关键词：image, video, detection, segmentation |
| `强化学习` | cs.LG + 关键词：reinforcement, RL, reward, policy |
| `其他` | 以上均不匹配 |

---

## 7. `rank.py` 执行流程

```
Step 1: 读取 data/YYYY-MM-DD-raw.json
Step 2: 硬过滤 — 去除三项热度信号均为 0 的论文
Step 3: 计算 score = hf_upvotes×2 + github_stars×0.05 + citation_count×0.5
Step 4: 主题分类（按 categories + 关键词匹配）
Step 5: 按 score 降序排列，截取 Top-N
Step 6: 写入 data/YYYY-MM-DD-ranked.json
Step 7: 打印摘要统计
```

### 输出摘要示例

```
============================================================
✅ Ranker 完成 — 2026-04-30
============================================================
📥 原始论文：152 篇
🔍 硬过滤后：87 篇（丢弃 65 篇无热度信号）
📊 精选输出：20 篇
   ├── LLM：        8 篇
   ├── 多模态：     4 篇
   ├── AI Agent：   3 篇
   ├── 计算机视觉：  3 篇
   ├── 强化学习：    1 篇
   └── 其他：       1 篇
📄 输出路径：data/2026-04-30-ranked.json
============================================================
```

---

## 8. 参数设计

```bash
python3 scripts/rank.py --date 2026-04-30   # 指定日期（默认今天）
python3 scripts/rank.py --top 10            # 精选 Top-N（默认 20）
python3 scripts/rank.py --min-upvotes 10    # 覆盖硬过滤阈值
```

---

## 9. SKILL.md frontmatter

```yaml
---
name: ranker
description: >
  读取 fetcher 输出的原始论文 JSON，通过热度评分和主题分类，
  从 100+ 篇中精选出 10~20 篇值得推送的论文，输出 ranked.json。
  当需要从原始论文列表中筛选精华、或 fetcher 完成后需要过滤时使用。
argument-hint: "[YYYY-MM-DD]"
allowed-tools: Bash Read Write
context: fork
effort: medium
---
```

---

## 10. 错误处理

| 场景 | 处理方式 |
|------|---------|
| `raw.json` 不存在 | 报错退出，提示先运行 fetcher |
| `raw.json` 为空数组 | 输出空 ranked.json，记录 WARN，退出码 0 |
| 硬过滤后剩余 0 篇 | 降级：取 score 最高的 5 篇，记录 WARN |
| 单篇处理异常 | 跳过该篇，继续处理其余 |

---

## 11. 实施检查清单

- [ ] 创建 `.claude/skills/Ranker/SKILL.md`
- [ ] 创建 `.claude/skills/Ranker/scripts/rank.py`
  - [ ] 实现 `load_raw(date)` 读取 raw.json
  - [ ] 实现 `hard_filter(papers)` 热度信号过滤
  - [ ] 实现 `compute_score(paper)` 评分公式
  - [ ] 实现 `classify_topic(paper)` 主题分类
  - [ ] 实现 `write_ranked(papers, date)` 输出 ranked.json
  - [ ] 实现 `print_summary(stats)` 控制台摘要
- [ ] 手动运行：`python3 rank.py --date 2026-04-30`，验证输出格式
- [ ] 验证 `summarizer` 可消费 `ranked.json` 输出格式
