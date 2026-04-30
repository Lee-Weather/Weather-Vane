---
name: fetcher
description: 从 arXiv、HuggingFace Daily Papers、Papers With Code 抓取当日最新 AI 论文元数据，合并去重后保存为 JSON 文件。当需要获取今日 AI 论文列表时使用。
argument-hint: "[YYYY-MM-DD]"
allowed-tools: WebFetch Bash Read Write
context: fork
effort: high
---

# Fetcher Skill — AI 论文抓取

使用本 Skill 目录下的 `scripts/fetch.py` 脚本抓取当日 AI 领域最新论文。

## 执行步骤

1. **确定目标日期**：如果用户未提供日期参数（`$ARGUMENTS`），使用今天的日期（UTC+8）。

2. **运行抓取脚本**：
   ```bash
   cd $CLAUDE_SKILL_DIR
   python3 scripts/fetch.py --date "$ARGUMENTS"
   ```
   脚本将依次完成：
   - 并发请求 arXiv API 和 HuggingFace Daily Papers API
   - 以 `arxiv_id` 为主键合并去重
   - 补充 Papers With Code 代码链接和 stars
   - （可选）通过 Semantic Scholar 补充引用数
   - 输出标准化 JSON 到 `data/YYYY-MM-DD-raw.json`

3. **验证输出**：读取输出文件，确认每条记录包含以下字段（均非空或有合理默认值）：
   - `id` / `title` / `authors` / `abstract`
   - `url` / `pdf_url` / `published_date` / `categories`
   - `hf_upvotes` / `pwc_stars` / `code_url` / `citation_count`

4. **处理异常**：
   - 若 arXiv 返回空（节假日/周末），输出空列表并附带 WARN 日志，告知调用方今日无新论文，退出码为 0。
   - 若 HuggingFace 或 Papers With Code API 失败，降级跳过，不中断主流程，仅记录 WARN。
   - 若 Semantic Scholar 返回 429，静默跳过引用数补充，`citation_count` 保持 0。

5. **返回结果**：向调用方（`ranker` Skill 或用户）输出：
   - 输出文件的绝对路径：`data/YYYY-MM-DD-raw.json`
   - 本次抓取的论文总数
   - 各数据源的条数（arXiv / HF / PWC 匹配数）

## 输出数据格式

每条论文记录的 JSON 结构如下：

```json
{
  "id": "arxiv:2401.xxxxx",
  "title": "论文标题",
  "authors": ["Author One", "Author Two"],
  "abstract": "论文摘要原文（英文）",
  "url": "https://arxiv.org/abs/2401.xxxxx",
  "pdf_url": "https://arxiv.org/pdf/2401.xxxxx",
  "published_date": "2026-04-30",
  "categories": ["cs.AI", "cs.LG"],
  "source": "arxiv",
  "hf_upvotes": 0,
  "pwc_stars": 0,
  "code_url": null,
  "citation_count": 0
}
```

## 注意事项

- arXiv API 限速：单 IP 每秒不超过 3 次请求，`fetch.py` 内置 rate limiter
- 时区：arXiv 使用 UTC，脚本内部统一转换为 UTC+8 判断"当日"
- ID 规范化：`http://arxiv.org/abs/2401.12345v1` → `arxiv:2401.12345`（去除版本号后缀）
- 去重主键：`arxiv_id`，同一论文来自多源时合并字段，不重复计入
