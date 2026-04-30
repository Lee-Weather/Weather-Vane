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

# Summarizer Skill — AI 论文中文摘要生成

读取 `ranker` 输出的四板块 `ranked.json`，调用 LLM 为每篇论文生成中文摘要。

## 执行步骤

1. **确定目标日期**：使用 `$ARGUMENTS` 中的日期，未提供则默认昨天（UTC+8）。

2. **运行摘要脚本**：
   ```bash
   python3 scripts/summarize.py --date "$ARGUMENTS"
   ```

3. **摘要策略**：
   - **短摘要**（`summary_zh`）：每日机器人组 15 篇 + AI 组 5 篇，150 字以内，三段式结构
   - **详细介绍**（`detail_zh`）：周/月热门各 1 篇，500~800 字，七维度深度分析

4. **处理顺序**：
   - 先处理周热门（详细介绍）
   - 再处理月热门（若与周热门同篇则直接复用 detail_zh）
   - 最后批量处理每日论文短摘要

5. **验证输出**：确认 `data/YYYY-MM-DD-summarized.json` 包含所有板块的摘要字段。

6. **返回结果**：输出统计（成功/失败篇数）及文件路径，供 `storage` Skill 使用。

## 异常处理

- `ranked.json` 不存在：报错退出，提示先运行 ranker
- 某板块为空：跳过该板块，其余正常处理
- 单篇 API 失败：`summary_zh` 置 `null`，记录 WARN，不中断整体流程
- API 429 限流：等待 60s 后重试，最多重试 3 次
- 周/月热门同篇：复用 `detail_zh`，不重复调用

## 输出格式

`data/YYYY-MM-DD-summarized.json`，四板块结构，每篇论文追加：
- `summary_zh`：150 字以内中文短摘要（每日论文 + 热门论文均有）
- `detail_zh`：500~800 字中文详细介绍（仅周/月热门有）
