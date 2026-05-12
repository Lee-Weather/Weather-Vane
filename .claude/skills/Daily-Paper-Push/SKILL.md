---
name: daily-paper-push
description: >
  执行完整的 AI 论文每日推送流程：抓取→排名→摘要→存储→推送。
  当用户要求"推送今日论文"或定时任务触发时使用。
argument-hint: "[YYYY-MM-DD]"
allowed-tools: Bash Read Write
context: fork
effort: high
---

# Daily-Paper-Push — 主调度器

按顺序执行完整的论文推送流水线：Fetcher → Ranker → Summarizer → Storage → Notifier。

## 使用方式

### 通过独立脚本运行（推荐）

```bash
# 完整流水线（默认昨天 UTC+8）
python3 scripts/run_pipeline.py

# 指定日期
python3 scripts/run_pipeline.py --date 2026-04-30

# 调试模式（不调 API、不发邮件）
python3 scripts/run_pipeline.py --dry-run

# 跳过某步骤
python3 scripts/run_pipeline.py --skip-fetch       # 已有 raw.json
python3 scripts/run_pipeline.py --skip-summarize   # 已有 summarized.json

# 从某步开始
python3 scripts/run_pipeline.py --start-from ranker
```

### 通过 Claude Code 触发

直接告诉 Claude："推送今日论文" 或 "/daily-paper-push 2026-04-30"。

## 错误处理

- Fetcher / Ranker 失败 → **终止**（无数据则后续无意义）
- Summarizer 失败 → **继续**（降级推送无摘要版本）
- Storage 失败 → **继续**（不影响推送，下次补录）
- Notifier 失败 → **记录 ERROR**（本地归档仍保存）
