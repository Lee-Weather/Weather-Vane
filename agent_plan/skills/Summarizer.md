# Summarizer Skill 设计文档

**Skill 路径**：`.claude/skills/Summarizer/`
**对应总计划**：`agent_plan/AI_Paper_Daily_Push_Plan.md` — Skill 3

---

## 1. 职责

系统的**内容生成器**。读取 `ranker` 输出的 `ranked.json`，为四个板块中的论文生成中文摘要：

- **每日论文**（机器人组 + AI 组，共 15+5=20 篇）：生成简洁的**短摘要**（150 字以内）
- **周/月热门**（各 1 篇）：生成深度的**详细介绍**（500~800 字）

输出 `summarized.json` 供 `storage` 持久化和 `notifier` 组装日报使用。

**核心原则**：摘要必须准确忠实于原文，不夸大、不捏造数据，以中文读者视角提炼价值。

---

## 2. Skill 文件结构

```
.claude/skills/Summarizer/
├── SKILL.md                  ← 必须。frontmatter 元数据 + Prompt 模板
└── scripts/
    └── summarize.py          ← 驱动脚本（调度 Claude API 或本地推理）
```

---

## 3. 输入 / 输出

### 输入

`data/YYYY-MM-DD-ranked.json`（由 `ranker` 生成），四板块结构：

```json
{
  "date": "2026-04-30",
  "daily_robot": [
    {
      "id": "arxiv:2501.xxxxx",
      "title": "...",
      "authors": ["..."],
      "abstract": "...",
      "url": "...", "pdf_url": "...", "code_url": "...",
      "hf_upvotes": 45, "pwc_stars": 120, "citation_count": 3,
      "categories": ["cs.RO", "cs.AI"],
      "score": 105.0, "group": "robot", "rank": 1
    }
  ],
  "daily_ai": [ /* 同结构，group=ai */ ],
  "weekly_hot": { /* 同结构，hot_type=weekly */ },
  "monthly_hot": { /* 同结构，hot_type=monthly */ }
}
```

### 输出

`data/YYYY-MM-DD-summarized.json`，在原结构基础上为每篇论文追加摘要字段：

```json
{
  "date": "2026-04-30",
  "daily_robot": [
    {
      "...原有字段...",
      "summary_zh": "本文提出一种用于四足机器人在非结构地形行走的自适应步态规划方法..."
    }
  ],
  "daily_ai": [ /* 同，追加 summary_zh */ ],
  "weekly_hot": {
    "...原有字段...",
    "summary_zh": "...",
    "detail_zh": "【研究背景】近年来大语言模型在 ... 【核心问题】... 【方法论】..."
  },
  "monthly_hot": {
    "...原有字段...",
    "summary_zh": "...",
    "detail_zh": "..."
  }
}
```

---

## 4. 两级摘要策略

### 4.1 短摘要（`summary_zh`）— 用于每日 20 篇

**目标**：让读者在 5 秒内了解论文价值，决定是否深入阅读。

**Prompt 模板**：

```
你是一位 AI 和机器人领域的研究助手，请对以下论文生成简洁的中文摘要。

论文标题：{title}
论文摘要（英文）：{abstract}

请按以下格式生成 **150 字以内** 的中文摘要：
1. 核心问题（1句）：这篇论文要解决什么问题？
2. 方法与创新点（1-2句）：用了什么方法，有什么独特之处？
3. 关键结论/指标（1句）：取得了什么效果？

要求：
- 使用中文技术术语，但保留关键英文缩写（如 LLM, RL, SLAM）
- 数据必须准确，不编造实验数据
- 不超过 150 字
```

**调用策略**：
- 批量串行处理（每篇之间 0.5s 间隔，避免 API 限流）
- 单篇失败时记录 WARN，`summary_zh` 设为 `null`，不中断整体流程

### 4.2 详细介绍（`detail_zh`）— 用于周/月热门各 1 篇

**目标**：让读者全面理解论文贡献，如同阅读一篇深度技术博客。

**Prompt 模板**：

```
你是一位 AI 和机器人领域的资深研究员，请对以下论文写一篇详细的中文技术介绍。

论文标题：{title}
论文摘要（英文）：{abstract}
HF 点赞数：{hf_upvotes}，GitHub Stars：{pwc_stars}，学术引用数：{citation_count}
论文链接：{url}

请按以下格式生成 **500-800 字** 的中文详细介绍：

### 1. 研究背景与动机（2-3 句）
为什么这个问题值得研究？当前有哪些局限性？

### 2. 核心问题定义（1-2 句）
论文精确要解决什么问题？

### 3. 方法论详解（3-5 句）
核心技术路线是什么？有哪些技术细节值得关注？（可使用技术术语，保留关键英文缩写）

### 4. 实验结果与关键指标（2-3 句）
在哪些数据集/场景上测试？取得了哪些可量化的效果？

### 5. 与现有工作对比（1-2 句）
相比 SOTA 或主流方法，优势在哪里？

### 6. 实际意义与未来展望（1-2 句）
这项工作对工业界/学术界有何影响？

### 7. 推荐理由（1 句）
为何本周/月特别值得关注？

要求：
- 准确忠实于原文，不编造数据
- 技术细节具体，不说空话
- 500-800 字，不超过上限
```

**调用策略**：
- 周/月热门各单独调用一次，优先级高于短摘要（先处理）
- 失败时最多重试 2 次

---

## 5. `summarize.py` 执行流程

```
Step 1: 读取 data/YYYY-MM-DD-ranked.json
Step 2: 验证输入完整性（四板块均存在）
Step 3: 处理周热门（详细介绍，优先）
Step 4: 处理月热门（详细介绍，若与周热门同篇则复用 detail_zh）
Step 5: 逐篇处理 daily_robot（短摘要，15 篇）
Step 6: 逐篇处理 daily_ai（短摘要，5 篇）
Step 7: 写入 data/YYYY-MM-DD-summarized.json
Step 8: 打印摘要统计
```

### 输出摘要示例

```
============================================================
✅ Summarizer 完成 — 2026-04-30
============================================================
📥 输入论文：22 篇（15 机器人 + 5 AI + 1 周热门 + 1 月热门）
✍️  短摘要生成：20 / 20 篇成功
📖 详细介绍生成：2 / 2 篇成功
⚠️  失败记录：0 篇
📄 输出路径：data/2026-04-30-summarized.json
============================================================
```

---

## 6. 参数设计

```bash
python3 scripts/summarize.py --date 2026-04-30         # 指定日期（默认昨天）
python3 scripts/summarize.py --skip-daily               # 跳过短摘要（调试用）
python3 scripts/summarize.py --skip-detail              # 跳过详细介绍（调试用）
python3 scripts/summarize.py --model claude-sonnet-4-5  # 指定调用模型
python3 scripts/summarize.py --dry-run                  # 不调用 API，仅打印 Prompt
```

---

## 7. SKILL.md frontmatter

```yaml
---
name: summarizer
description: >
  读取 ranker 输出的 ranked.json，为每日论文生成 150 字短摘要，
  为周/月热门生成 500-800 字详细介绍，输出 summarized.json。
  当需要为论文生成中文摘要时使用。
argument-hint: "[YYYY-MM-DD]"
allowed-tools: Bash Read Write
context: fork
effort: high
---
```

---

## 8. 错误处理

| 场景 | 处理方式 |
|------|---------|
| `ranked.json` 不存在 | 报错退出，提示先运行 ranker |
| `ranked.json` 某板块为空 | 跳过该板块，其余正常处理 |
| API 调用超时（>30s） | 重试最多 2 次，失败后 `summary_zh` 置 `null` |
| API 429 限流 | 等待 60s 后重试，超过 3 次则跳过该篇 |
| 摘要超过字数限制 | 截断并追加 `...`，记录 WARN |
| 摘要包含英文（未中文化） | 记录 WARN，不过滤（保留原文） |
| 周热门与月热门是同一篇 | 复用 `detail_zh`，不重复调用 API |

---

## 10. 实施检查清单

- [x] 创建 `.claude/skills/Summarizer/SKILL.md`
- [x] 创建 `.claude/skills/Summarizer/scripts/summarize.py`
  - [x] 实现 `load_ranked(date)` 读取 ranked.json
  - [x] 实现 `build_short_prompt(paper)` 短摘要 Prompt 构建
  - [x] 实现 `build_detail_prompt(paper)` 详细介绍 Prompt 构建
  - [x] 实现 `call_llm(prompt, model)` LLM 调用（DeepSeek API 兑容接口）
  - [x] 实现 `summarize_daily(papers)` 批量短摘要（含限流间隔）
  - [x] 实现 `summarize_hot(paper, hot_type)` 详细介绍（含重复检测）
  - [x] 实现 `write_summarized(result, date)` 输出 summarized.json
  - [x] 实现 `print_summary(stats)` 控制台摘要
- [x] 创建 `.claude/skills/Summarizer/tests/test_summarize.py`（20 项测试，全部通过）
- [x] `--dry-run` 模式验证 Prompt 格式正确
- [ ] 实际调用 API 验证短摘要质量（检查是否忠实原文）
- [ ] 实际调用 API 验证详细介绍质量（检查字数和结构）
- [ ] 验证 `notifier` 可消费 `summarized.json` 结构
- [ ] 验证周热门和月热门同篇时的去重逻辑（连续两天运行，确认不重复推送）
