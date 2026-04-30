---
name: fetcher
description: 从 arXiv、HuggingFace Daily Papers 抓取当日最新 AI 论文元数据，合并去重后保存为 JSON 文件；另提供热门论文排行榜工具。当需要获取今日 AI 论文列表或最近热门论文时使用。
argument-hint: "[YYYY-MM-DD]"
allowed-tools: WebFetch Bash Read Write
context: fork
effort: high
---

# Fetcher Skill — AI 论文抓取

本 Skill 包含两个独立脚本：

| 脚本 | 用途 |
|------|------|
| `scripts/fetch.py` | 每日抓取，输出标准化 JSON |
| `scripts/hot_papers.py` | 过去 N 天热门论文排行榜 |

---

## 一、每日抓取脚本 `fetch.py`

### 执行步骤

1. **确定目标日期**：如果用户未提供日期参数（`$ARGUMENTS`），使用今天的日期（UTC+8）。

2. **运行抓取脚本**：
   ```bash
   cd $CLAUDE_SKILL_DIR
   python3 scripts/fetch.py --date "$ARGUMENTS"
   ```
   脚本将依次完成：
   - 并发请求 arXiv API 和 HuggingFace Daily Papers API
   - 以 `arxiv_id` 为主键合并去重
   - HF API 自带 GitHub 代码链接和 Stars（`githubRepo` / `githubStars`）
   - （可选）通过 Semantic Scholar 补充引用数
   - 输出标准化 JSON 到 `data/YYYY-MM-DD-raw.json`

3. **验证输出**：读取输出文件，确认每条记录包含以下字段（均非空或有合理默认值）：
   - `id` / `title` / `authors` / `abstract`
   - `url` / `pdf_url` / `published_date` / `categories`
   - `hf_upvotes` / `github_stars` / `code_url` / `citation_count`

4. **处理异常**：
   - 若 arXiv 返回空（节假日/周末），输出空列表并附带 WARN 日志，退出码为 0。
   - 若 HuggingFace API 失败，降级跳过，不中断主流程，仅记录 WARN。
   - 若 Semantic Scholar 返回 429，静默跳过引用数补充，`citation_count` 保持 0。

5. **返回结果**：向调用方输出：
   - 输出文件的绝对路径：`data/YYYY-MM-DD-raw.json`
   - 本次抓取的论文总数
   - 各数据源的条数（arXiv / HF 匹配数）

### 输出数据格式

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
  "hf_upvotes": 42,
  "github_stars": 128,
  "code_url": "https://github.com/xxx/yyy",
  "citation_count": 0
}
```

---

## 二、热门论文排行榜 `hot_papers.py`

抓取过去 N 天 HF Daily Papers 所有有点赞数据的论文，按综合热度排名，生成 Markdown 报告。

### 用法

```bash
python3 scripts/hot_papers.py --days 30           # 过去 30 天 Top-20（默认）
python3 scripts/hot_papers.py --days 7 --top 50  # 过去 7 天 Top-50
python3 scripts/hot_papers.py --skip-citations    # 跳过 S2 引用数（更快）
```

### 数据来源

- **HuggingFace Daily Papers API**：点赞数 + GitHub 代码链接 + GitHub Stars（一次请求全部获得）
- **Semantic Scholar**（可选）：引用数（批量查询，每批 50 篇，限速 3s/批）

### 热度评分公式

```
score = hf_upvotes × 2.0 + github_stars × 0.05 + citation_count × 0.5
```

### 输出

- 控制台：排名表（排名 / HF赞 / GitHub Stars / 引用数 / 标题）
- 文件：`reports/hot-papers-YYYY-MM-DD-{N}d.md`

---

## 注意事项

- **时区**：arXiv 使用 UTC，脚本内部统一转换为 UTC+8 判断「当日」
- **ID 规范化**：`http://arxiv.org/abs/2401.12345v1` → `arxiv:2401.12345`（去除版本号后缀）
- **去重主键**：`arxiv_id`，同一论文来自多源时合并字段
- **S2 限流**：免费 API 约 100 次/分钟；配置 `SEMANTIC_SCHOLAR_API_KEY` 可提升至 1000 次/分钟
