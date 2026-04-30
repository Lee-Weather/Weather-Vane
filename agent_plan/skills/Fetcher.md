# Fetcher Skill 设计文档

**Skill 路径**：`.claude/skills/fetcher/`
**对应总计划**：`agent_plan/AI_Paper_Daily_Push_Plan.md` — Skill 1

---

## 1. 职责

系统的**数据入口**。从多个学术平台并发抓取当日最新 AI 论文元数据，合并去重后写入标准化 JSON，供 `ranker` → `summarizer` → `storage` → `notifier` 依次消费。

---

## 2. Skill 文件结构

```
.claude/skills/fetcher/
├── SKILL.md                  ← 必须。frontmatter 元数据 + 执行指令体
├── examples/
│   └── sample-output.json    ← 可选。标准输出示例，帮助 Claude 理解预期格式
├── scripts/
│   └── fetch.py              ← Claude 通过 Bash 工具执行的抓取脚本
└── tests/
    └── test_fetch.py         ← 可选。脚本单元测试
```

各文件说明：

| 文件 | 是否必须 | 用途 |
|------|---------|------|
| `SKILL.md` | ✅ 必须 | Skill 入口，Claude 读取后获得执行指令；frontmatter 定义元数据 |
| `examples/sample-output.json` | 推荐 | 告知 Claude 输出 JSON 的预期结构，减少格式错误 |
| `scripts/fetch.py` | 推荐 | 实际抓取逻辑；Claude 通过 `Bash` 工具调用，不直接注入上下文 |
| `tests/test_fetch.py` | 可选 | 脚本独立测试，Claude 可通过 `Bash` 运行验证 |

---

## 3. SKILL.md 完整内容（待创建）

以下是 `.claude/skills/fetcher/SKILL.md` 的完整内容设计：

```markdown
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
   cd ${CLAUDE_SKILL_DIR}
   python3 scripts/fetch.py --date $ARGUMENTS
   ```
   脚本将依次完成：
   - 并发请求 arXiv API 和 HuggingFace Daily Papers API
   - 以 arxiv_id 为主键合并去重
   - 补充 Papers With Code 代码链接和 stars
   - （可选）通过 Semantic Scholar 补充引用数
   - 输出标准化 JSON 到 `data/YYYY-MM-DD-raw.json`

3. **验证输出**：读取输出文件，确认字段完整（id / title / authors / abstract / url / pdf_url / categories / hf_upvotes / pwc_stars / code_url）。

4. **处理异常**：
   - 若 arXiv 返回空（节假日），输出空列表并附带 WARN 日志，告知调用方今日无新论文。
   - 若 HF 或 PWC API 失败，降级跳过，不中断主流程。

5. **返回结果**：输出文件路径 `data/YYYY-MM-DD-raw.json` 及论文总数，供 `ranker` Skill 使用。
```

---

## 4. 辅助脚本设计：fetch.py

### 4.1 入口与参数

```python
# 用法：python3 fetch.py --date YYYY-MM-DD
# 输出：data/YYYY-MM-DD-raw.json
```

### 4.2 输出数据结构（每条记录）

```json
{
  "id": "arxiv:2401.xxxxx",
  "title": "...",
  "authors": ["Author One", "Author Two"],
  "abstract": "...",
  "url": "https://arxiv.org/abs/2401.xxxxx",
  "pdf_url": "https://arxiv.org/pdf/2401.xxxxx",
  "published_date": "2026-04-29",
  "categories": ["cs.AI", "cs.LG"],
  "source": "arxiv",
  "hf_upvotes": 120,
  "pwc_stars": 0,
  "code_url": null,
  "citation_count": 0
}
```

### 4.3 数据源与抓取方案

#### arXiv API（主要来源）

**端点**：`http://export.arxiv.org/api/query`

```
search_query = cat:cs.AI+OR+cat:cs.LG+OR+cat:cs.CV+OR+cat:cs.CL+OR+cat:stat.ML
sortBy       = submittedDate
sortOrder    = descending
max_results  = 100
```

**解析**：`feedparser.parse()` → 提取 `entry.id / title / authors / summary / tags / links / published`

**注意**：
- ID 规范化：`http://arxiv.org/abs/2401.12345v1` → `arxiv:2401.12345`
- 过滤：仅保留 `published_date >= target_date - 1day`（避免跨时区漏抓）
- 周末/节假日 arXiv 不更新，空结果时记录 WARN 日志

#### HuggingFace Daily Papers（热度来源）

**端点**：`https://huggingface.co/api/daily_papers?date=YYYY-MM-DD`

**关键字段**：
```json
{ "paper": { "id": "2401.xxxxx", "title": "...", "summary": "...", "authors": [...] }, "upvotes": 120 }
```

**处理**：`paper.id` → `arxiv:{id}`，`upvotes` → `hf_upvotes`，与 arXiv 数据 ID 去重合并

#### Papers With Code（代码链接来源）

**端点**：`https://paperswithcode.com/api/v1/papers/?ordering=-published&date_after=YYYY-MM-DD&page_size=50`

**处理**：通过 `paper.arxiv_id` 匹配，补充 `pwc_stars` 和 `code_url`

#### Semantic Scholar（引用数，可选增强）

**端点**：`POST https://api.semanticscholar.org/graph/v1/paper/batch`

```json
{ "ids": ["ARXIV:2401.xxxxx"], "fields": "citationCount" }
```

**策略**：失败静默处理，`citation_count` 保持 0，不中断主流程

### 4.4 执行流程

```
Step 1: 并发请求 arXiv + HuggingFace
Step 2: 以 arxiv_id 为主键合并去重
Step 3: 串行请求 PWC，补充 code_url / pwc_stars
Step 4: 批量请求 Semantic Scholar，补充 citation_count（可选）
Step 5: 写入 data/YYYY-MM-DD-raw.json
```

### 4.5 错误处理

| 场景 | 处理方式 |
|------|---------|
| 网络超时（>10s） | 指数退避重试 3 次（1s / 2s / 4s） |
| arXiv 返回空 | 记录 WARN，写入空 JSON 数组，退出码 0 |
| HF API 404 / 超时 | 降级跳过，仅用 arXiv 数据 |
| Semantic Scholar 429 | 跳过引用数补充，`citation_count` 保持 0 |
| 单篇解析异常 | 记录 ERROR + arxiv_id，跳过该篇，继续处理 |

### 4.6 依赖包

```
httpx>=0.27.0          # 异步 HTTP 客户端
feedparser>=6.0.11     # arXiv Atom XML 解析
python-dateutil>=2.9   # 日期处理
```

---

## 5. 环境变量

```bash
# fetch.py 通过 os.getenv() 读取，全部可选
SEMANTIC_SCHOLAR_API_KEY=...   # 有 key 则限速更宽松（可选）
```

---

## 6. 测试计划

| 测试用例 | 验证点 |
|---------|--------|
| `test_arxiv_normal` | 正常日期返回 ≥1 篇，所有必填字段非空 |
| `test_arxiv_holiday` | 空返回不抛异常，输出空 JSON 数组 |
| `test_hf_merge` | HF 数据与 arXiv 正确合并，`hf_upvotes` 填充 |
| `test_pwc_enrich` | `pwc_stars` / `code_url` 正确写入 |
| `test_dedup` | 相同 arxiv_id 只保留一条 |
| `test_retry` | 超时后自动重试，成功后正常输出 |
| `test_skip_bad_entry` | 单篇解析失败不影响其他条目 |

运行方式：
```bash
python3 -m pytest .claude/skills/fetcher/tests/ -v
```

---

## 7. 实施检查清单

- [ ] 创建 `.claude/skills/fetcher/SKILL.md`（按第 3 节内容）
- [ ] 创建 `.claude/skills/fetcher/scripts/fetch.py`
  - [ ] 实现 `fetch_arxiv(date)` + feedparser 解析
  - [ ] 实现 `fetch_huggingface(date)` + ID 合并
  - [ ] 实现 `merge_papers()` 去重逻辑
  - [ ] 实现 `fetch_pwc(date)` 补充代码链接
  - [ ] 实现 `enrich_citations()` 可选引用数
  - [ ] 实现错误处理（重试 + 静默降级）
  - [ ] 写入 `data/YYYY-MM-DD-raw.json`
- [ ] 手动运行：`python3 fetch.py --date 2026-04-29`，验证输出格式
- [ ] 在 Claude Code 中触发：`/fetcher 2026-04-29`，验证 Skill 正确执行脚本
- [ ] 编写并通过所有单元测试
