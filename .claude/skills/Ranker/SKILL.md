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

# Ranker Skill — 论文过滤与排名

读取 `fetcher` 输出的 `data/YYYY-MM-DD-raw.json`，按主题分组、热度评分、排名筛选，输出四板块结构的 `data/YYYY-MM-DD-ranked.json`。

---

## 执行步骤

1. **确定目标日期**：如果用户未提供日期参数（`$ARGUMENTS`），使用昨天的日期（UTC+8）。

2. **运行排名脚本**：
   ```bash
   cd $CLAUDE_SKILL_DIR
   python3 scripts/rank.py --date "$ARGUMENTS"
   ```
   脚本将依次完成：
   - 读取 `data/YYYY-MM-DD-raw.json`
   - 计算热度评分：`score = hf_upvotes × 2.0 + pwc_stars × 0.05 + citation_count × 0.5`
   - 按 `categories` 分组：机器人组（含 cs.RO）取 Top-15，AI 组（含 cs.AI 且不含 cs.RO）取 Top-5
   - **每日精选不按热度过滤**：新论文尚未积累热度信号，全量进入分组，score=0 自然落底
   - 选取周热门（过去 7 天 score 最高 1 篇，查推送历史去重）
   - 选取月热门（过去 30 天 score 最高 1 篇，查推送历史去重）
   - 周/月热门数据源：优先读取 `reports/hot-papers-*-{7d,30d}.json`（含真实 HF 热度），缺失时回退到多日 `raw.json` 合并
   - 输出 `data/YYYY-MM-DD-ranked.json`

3. **验证输出**：读取输出文件，确认包含四个板块：
   - `daily_robot`：机器人组论文列表（≤15 篇）
   - `daily_ai`：AI 组论文列表（≤5 篇）
   - `weekly_hot`：本周热门 1 篇（或 null）
   - `monthly_hot`：本月热门 1 篇（或 null）

4. **处理异常**：
   - 若 `raw.json` 不存在，报错退出，提示先运行 fetcher。
   - 若某组论文不足数量，有多少输出多少，记录 WARN。
   - 若周/月热门无候选数据，对应字段输出 `null`。

5. **返回结果**：向调用方输出：
   - 输出文件路径：`data/YYYY-MM-DD-ranked.json`
   - 各板块论文数量统计

---

## 输出格式

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
