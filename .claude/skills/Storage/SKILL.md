---
name: storage
description: 将生成的 summarized.json 论文数据持久化到 SQLite 数据库，并记录推送历史用于去重。也提供查询接口判断论文是否已推送过。
argument-hint: "[summarized-json-path]"
allowed-tools: Bash Read Write
context: fork
effort: low
---

# Storage Skill — 数据持久化与去重管理

读取 Summarizer 输出的 `summarized.json` 数据，并将其存入 SQLite 数据库（`data/papers.db`），同时更新论文推送记录。

## 执行步骤

1. **确定 JSON 文件路径**：默认使用昨天的 `data/YYYY-MM-DD-summarized.json`，也可通过 `$ARGUMENTS` 传入明确路径。
2. **运行保存脚本**：
   ```bash
   python3 scripts/save.py --save "data/YYYY-MM-DD-summarized.json"
   ```
3. **数据入库**：脚本会自动连接/创建 `papers.db`，将四板块中的所有论文保存至 `papers` 表（通过 `INSERT OR REPLACE` 处理重复写入），并将当天的推送类型存入 `push_history` 表。
4. **命令行查询功能**：
   ```bash
   # 查询是否已作为周热门推送
   python3 scripts/save.py --check-pushed "arxiv:2501.12345" --type "weekly_hot"
   
   # 手动标记已推送
   python3 scripts/save.py --mark-pushed "arxiv:2501.12345" --type "monthly_hot" --date "2026-04-30"
   ```

## 注意事项
- SQLite3 属于 Python 内置库，无需额外安装依赖。
- 入库是幂等的，同一天多次运行 `--save` 不会导致数据异常。
