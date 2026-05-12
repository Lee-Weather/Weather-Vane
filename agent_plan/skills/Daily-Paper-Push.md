# Daily-Paper-Push 设计文档（Skill 0 — 主调度器）

**Skill 路径**：`.claude/skills/Daily-Paper-Push/`
**对应总计划**：`agent_plan/AI_Paper_Daily_Push_Plan.md` — Skill 0

---

## 1. 职责

系统的**总指挥**。按顺序串联五个子 Skill，完成从论文抓取到邮件推送的完整流水线。

```
Fetcher → Ranker → Summarizer → Storage → Notifier
```

可通过 Claude Code 自然语言触发（如"推送今日论文"），也可通过 cron 定时任务自动运行。

---

## 2. 实现方式

本 Skill **无独立 Python 脚本**。它通过 `SKILL.md` 中的指令体，让 Claude Code 依序调用各子脚本。同时提供一个可选的 `run_pipeline.py` 脚本，支持脱离 Claude Code 直接在命令行运行完整流水线。

### 文件结构

```
.claude/skills/Daily-Paper-Push/
├── SKILL.md                  ← Claude Code 入口（指令体串联子 Skill）
└── scripts/
    └── run_pipeline.py       ← 独立调度脚本（脱离 Claude Code 运行）
```

---

## 3. 流水线步骤

| 步骤 | 子 Skill | 脚本命令 | 输入 | 输出 |
|------|---------|---------|------|------|
| 1 | Fetcher | `fetch.py --date {DATE}` | arXiv/HF API | `data/{DATE}-raw.json` |
| 2 | Ranker | `rank.py --date {DATE}` | `raw.json` | `data/{DATE}-ranked.json` |
| 3 | Summarizer | `summarize.py --date {DATE}` | `ranked.json` | `data/{DATE}-summarized.json` |
| 4 | Storage | `save.py --save data/{DATE}-summarized.json` | `summarized.json` | `data/papers.db` |
| 5 | Notifier | `notify.py --date {DATE}` | `summarized.json` | `reports/{DATE}.md` + Gmail |

---

## 4. 错误处理策略

| 步骤 | 失败时行为 |
|------|-----------|
| Fetcher | **终止整个流水线**（无数据则后续无意义） |
| Ranker | 终止（ranked.json 是后续必需输入） |
| Summarizer | **继续**（可降级推送无摘要的版本，但记录 WARNING） |
| Storage | **继续**（入库失败不影响推送，下次运行会补录） |
| Notifier | **记录 ERROR**（本地归档仍会保存，邮件失败不阻断） |

---

## 5. `run_pipeline.py` 参数设计

```bash
# 完整流水线（默认昨天）
python scripts/run_pipeline.py

# 指定日期
python scripts/run_pipeline.py --date 2026-04-30

# 跳过某些步骤
python scripts/run_pipeline.py --skip-fetch        # 跳过抓取（使用已有 raw.json）
python scripts/run_pipeline.py --skip-summarize    # 跳过摘要生成
python scripts/run_pipeline.py --skip-email        # 跳过邮件推送
python scripts/run_pipeline.py --dry-run           # 全流程但不发邮件、不调API

# 从某一步开始（前面步骤的输出文件必须已存在）
python scripts/run_pipeline.py --start-from ranker
```

---

## 6. SKILL.md frontmatter

```yaml
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
```

---

## 7. 定时任务配置

### Linux/macOS (cron)

```bash
# 每日 08:00 UTC+8 自动运行
crontab -e
0 0 * * * cd /path/to/Weather-Vane && /path/to/python scripts/run_pipeline.py >> logs/cron.log 2>&1
```

### Windows (任务计划程序)

```powershell
# 通过 PowerShell 创建每日任务
$action = New-ScheduledTaskAction -Execute "D:\ProgramData\miniconda3\envs\ai_base\python.exe" `
    -Argument "E:\github\Weather-Vane\.claude\skills\Daily-Paper-Push\scripts\run_pipeline.py" `
    -WorkingDirectory "E:\github\Weather-Vane"
$trigger = New-ScheduledTaskTrigger -Daily -At 8:00AM
Register-ScheduledTask -TaskName "WeatherVane-DailyPush" -Action $action -Trigger $trigger
```

---

## 8. 实施检查清单

- [x] 创建 `.claude/skills/Daily-Paper-Push/SKILL.md`
- [x] 创建 `.claude/skills/Daily-Paper-Push/scripts/run_pipeline.py`
  - [x] 实现参数解析（`--date`, `--skip-*`, `--start-from`, `--dry-run`）
  - [x] 实现五步串联调用（subprocess 调用各子脚本）
  - [x] 实现错误处理（Fetcher/Ranker 失败终止，其余继续）
  - [x] 实现流水线统计摘要打印
- [x] 端到端测试（`--skip-fetch --skip-summarize --skip-email` 模式验证通过）
- [ ] 配置定时任务（可选）

