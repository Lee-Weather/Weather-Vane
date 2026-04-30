# Fetcher Skill 设计文档

**Skill 路径**：`.claude/skills/Fetcher/`
**对应总计划**：`agent_plan/AI_Paper_Daily_Push_Plan.md` — Skill 1

---

## 1. 职责

系统的**数据入口**。从多个学术平台并发抓取当日最新 AI 论文元数据，合并去重后写入标准化 JSON，供 `ranker` → `summarizer` → `storage` → `notifier` 依次消费。

另提供 `hot_papers.py` 独立工具，可按需查询过去 N 天热门论文排行榜（不接入主流水线）。

---

## 2. Skill 文件结构

```
.claude/skills/Fetcher/
├── SKILL.md                  ← 必须。frontmatter 元数据 + 执行指令体
├── scripts/
│   ├── fetch.py              ← 每日抓取脚本（主流水线）
│   └── hot_papers.py         ← 历史热榜工具（按需手动调用）
└── tests/
    └── test_fetch.py         ← 单元测试
```

各文件说明：

| 文件 | 是否必须 | 用途 |
|------|---------|------|
| `SKILL.md` | ✅ 必须 | Skill 入口，Claude 读取后获得执行指令 |
| `scripts/fetch.py` | ✅ 必须 | 每日论文抓取，输出 `raw.json` |
| `scripts/hot_papers.py` | 可选工具 | 历史热榜，手动调用，不参与自动流水线 |
| `tests/test_fetch.py` | 可选 | 脚本独立测试 |

---

## 3. 数据源

| 数据源 | 用途 | 状态 |
|--------|------|------|
| **arXiv API** | 主数据源，抓取当日新论文 | ✅ 已实现 |
| **HuggingFace Daily Papers API** | 补充 HF 点赞数 + GitHub 代码链接 + Stars | ✅ 已实现 |
| **Semantic Scholar**（可选） | 补充引用数 | ✅ 已实现（可跳过） |
| ~~Papers With Code~~ | ~~代码链接~~ | ❌ 已废弃（HF API 已内置 GitHub 信息） |

> **说明**：PWC API 已废弃，因为 HuggingFace Daily Papers API 的响应体中已内置
> `paper.githubRepo`（代码链接）和 `paper.githubStars`（Stars 数），无需额外请求 PWC。

---

## 4. 输出数据格式（`fetch.py`）

每条论文记录的 JSON 结构：

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
  "hf_upvotes": 120,
  "github_stars": 256,
  "code_url": "https://github.com/xxx/yyy",
  "citation_count": 0
}
```

**输出路径**：`data/YYYY-MM-DD-raw.json`

---

## 5. `fetch.py` 执行流程

```
Step 1: 并发请求 arXiv API + HuggingFace Daily Papers API
Step 2: 以 arxiv_id 为主键合并去重
        HF 数据补充：hf_upvotes / github_stars / code_url
Step 3: 批量请求 Semantic Scholar，补充 citation_count（可选）
Step 4: 写入 data/YYYY-MM-DD-raw.json
```

### 错误处理

| 场景 | 处理方式 |
|------|---------|
| 网络超时（>10s） | 指数退避重试 3 次（1s / 2s / 4s） |
| arXiv 返回空 | 记录 WARN，写入空 JSON 数组，退出码 0 |
| HF API 404 / 超时 | 降级跳过，仅用 arXiv 数据 |
| Semantic Scholar 429 | 跳过引用数补充，`citation_count` 保持 0 |
| 单篇解析异常 | 记录 ERROR + arxiv_id，跳过该篇，继续处理 |

---

## 6. `hot_papers.py` — 历史热榜工具

**定位**：独立的按需工具，不参与 `fetcher → ranker → ...` 主流水线。

**用途**：直接从 HF Daily Papers API 拉取过去 N 天论文，一键生成排行榜报告。

### 用法

```bash
python3 scripts/hot_papers.py --days 30           # 过去 30 天 Top-20（默认）
python3 scripts/hot_papers.py --days 7 --top 50  # 过去 7 天 Top-50
python3 scripts/hot_papers.py --skip-citations    # 跳过 S2 引用数（更快）
```

### 热度评分公式

```
score = hf_upvotes × 2.0 + github_stars × 0.05 + citation_count × 0.5
```

### 输出

- 控制台：排名表（排名 / HF赞 / GitHub Stars / 引用数 / 标题）
- 文件：`reports/hot-papers-YYYY-MM-DD-{N}d.md`

---

## 7. 环境变量

```bash
SEMANTIC_SCHOLAR_API_KEY=...   # 可选；有 key 则限速从 100次/分 提升至 1000次/分
```

---

## 8. 测试计划

| 测试用例 | 验证点 |
|---------|--------|
| `test_arxiv_normal` | 正常日期返回 ≥1 篇，所有必填字段非空 |
| `test_arxiv_holiday` | 空返回不抛异常，输出空 JSON 数组 |
| `test_hf_merge` | HF 数据与 arXiv 正确合并，`hf_upvotes` / `github_stars` 填充 |
| `test_dedup` | 相同 arxiv_id 只保留一条 |
| `test_retry` | 超时后自动重试，成功后正常输出 |
| `test_skip_bad_entry` | 单篇解析失败不影响其他条目 |

运行方式：
```bash
python3 -m pytest .claude/skills/Fetcher/tests/ -v
```

---

## 9. 实施检查清单

- [x] 创建 `.claude/skills/Fetcher/SKILL.md`
- [x] 创建 `.claude/skills/Fetcher/scripts/fetch.py`
  - [x] 实现 `fetch_arxiv(date)` + XML 解析
  - [x] 实现 `fetch_huggingface(date)` + github_stars/code_url 提取
  - [x] 实现 `merge_papers()` 去重逻辑
  - [x] 实现 `enrich_s2()` 可选引用数补充
  - [x] 实现错误处理（重试 + 静默降级）
  - [x] 写入 `data/YYYY-MM-DD-raw.json`
- [x] 创建 `.claude/skills/Fetcher/scripts/hot_papers.py`（历史热榜工具）
- [ ] 手动运行 `fetch.py` 并验证 `ranker` 可消费其输出格式
- [ ] 编写并通过所有单元测试
