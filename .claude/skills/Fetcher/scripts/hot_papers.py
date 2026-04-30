#!/usr/bin/env python3
"""
hot_papers.py — 过去 N 天最火 AI 论文排行榜

完全独立工具，不依赖 fetch.py。
直接从 HuggingFace Daily Papers API 抓取过去 N 天有点赞的论文
（HF API 内置 GitHub 代码链接和 Stars，无需额外查询 PWC）。
可选补充 Semantic Scholar 引用数，按综合热度评分排名，输出 Markdown 报告。

热度评分公式：
    score = hf_upvotes * 2.0 + github_stars * 0.05 + citation_count * 0.5

用法：
    python hot_papers.py                  # 过去 30 天 Top-20
    python hot_papers.py --days 7         # 过去 7 天
    python hot_papers.py --top 50         # 显示 Top-50
    python hot_papers.py --skip-citations # 跳过 S2 引用数（更快）
    python hot_papers.py --output report.md  # 输出到指定文件

输出：
    控制台打印排名表 + 自动保存至 reports/hot-papers-YYYY-MM-DD-{N}d.md
"""

import argparse
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

# ──────────────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────────────

TZ_CST = timezone(timedelta(hours=8))

HF_API_URL   = "https://huggingface.co/api/daily_papers"
S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
S2_API_KEY   = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")

HTTP_TIMEOUT = 20.0
RETRY_DELAYS = [1, 2, 4]

# 默认输出目录（脚本同级的 reports/ 相对于项目根）
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports"

# ──────────────────────────────────────────────────────────────────────────────
# 日志
# ──────────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 参数解析
# ──────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="抓取过去 N 天 HuggingFace 热门 AI 论文并综合排名"
    )
    parser.add_argument("--days",  type=int, default=30,
                        help="统计过去几天（默认：30）")
    parser.add_argument("--top",   type=int, default=20,
                        help="输出 Top-N 论文（默认：20）")
    parser.add_argument("--skip-citations", action="store_true",
                        help="跳过 Semantic Scholar 引用数补充")
    parser.add_argument("--output", type=str, default=None,
                        help="输出 Markdown 文件路径（默认：只打印到控制台）")
    return parser.parse_args()


# ──────────────────────────────────────────────────────────────────────────────
# HTTP 工具
# ──────────────────────────────────────────────────────────────────────────────

async def get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    **kwargs,
) -> httpx.Response | None:
    """GET 请求，带指数退避重试（最多 3 次）。"""
    for attempt, delay in enumerate([0] + RETRY_DELAYS, start=1):
        if delay:
            await asyncio.sleep(delay)
        try:
            resp = await client.get(url, **kwargs)
            if resp.status_code < 500:
                return resp
            logger.warning("HTTP %d（第 %d 次），重试：%s", resp.status_code, attempt, url)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            logger.warning("请求失败（第 %d 次）：%s", attempt, exc)
    logger.error("所有重试失败：%s", url)
    return None


async def post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    **kwargs,
) -> httpx.Response | None:
    """POST 请求，带指数退避重试。"""
    for attempt, delay in enumerate([0] + RETRY_DELAYS, start=1):
        if delay:
            await asyncio.sleep(delay)
        try:
            resp = await client.post(url, **kwargs)
            if resp.status_code < 500:
                return resp
            logger.warning("HTTP %d（第 %d 次），重试：%s", resp.status_code, attempt, url)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            logger.warning("POST 失败（第 %d 次）：%s", attempt, exc)
    return None


# ──────────────────────────────────────────────────────────────────────────────
# 数据抓取
# ──────────────────────────────────────────────────────────────────────────────

async def fetch_hf_one_day(
    client: httpx.AsyncClient,
    date_str: str,
) -> list[dict]:
    """
    抓取单日 HuggingFace Daily Papers。
    返回包含 hf_upvotes 的论文列表，失败返回 []。
    """
    resp = await get_with_retry(client, HF_API_URL, params={"date": date_str})
    if resp is None or resp.status_code != 200:
        logger.warning("[%s] HF API 失败，跳过", date_str)
        return []
    try:
        items = resp.json()
    except Exception:
        return []

    papers = []
    for item in items:
        try:
            p = item.get("paper", {})
            raw_id = p.get("id", "")
            if not raw_id:
                continue
            # upvotes 在 paper 对象内部（不是顶层 item）
            upvotes = p.get("upvotes", 0) or 0
            # githubRepo 和 githubStars 也在 paper 内部
            github_repo = p.get("githubRepo") or None
            github_stars = p.get("githubStars", 0) or 0
            papers.append({
                "id": f"arxiv:{raw_id}",
                "title": p.get("title", ""),
                "authors": [a.get("name", "") for a in p.get("authors", [])],
                "abstract": p.get("summary", ""),
                "url": f"https://arxiv.org/abs/{raw_id}",
                "pdf_url": f"https://arxiv.org/pdf/{raw_id}",
                "published_date": date_str,
                "categories": [],
                "hf_upvotes": upvotes,
                "github_stars": github_stars,
                "code_url": github_repo,
                "citation_count": 0,
            })
        except Exception as exc:
            logger.debug("解析 HF 条目失败：%s", exc)
    return papers



async def enrich_s2(
    client: httpx.AsyncClient,
    papers: list[dict],
) -> None:
    """
    批量补充 Semantic Scholar 引用数（就地修改）。
    每批 50 篇，批次间隔 3s，429 时等待 10s 再重试一次。
    """
    headers = {"Content-Type": "application/json"}
    if S2_API_KEY:
        headers["x-api-key"] = S2_API_KEY

    BATCH_SIZE = 50  # 降低每批数量减少限流风险
    for i in range(0, len(papers), BATCH_SIZE):
        batch = papers[i: i + BATCH_SIZE]
        s2_ids = [f"ARXIV:{p['id'].removeprefix('arxiv:')}" for p in batch]

        resp = await post_with_retry(
            client, S2_BATCH_URL,
            json={"ids": s2_ids},
            params={"fields": "citationCount"},
            headers=headers,
        )

        if resp is None:
            logger.warning("[S2] 请求失败，跳过剩余")
            return

        if resp.status_code == 429:
            logger.warning("[S2] 限流 429，等待 15s 后重试最后一批...")
            await asyncio.sleep(15)
            # 重试一次
            resp = await post_with_retry(
                client, S2_BATCH_URL,
                json={"ids": s2_ids},
                params={"fields": "citationCount"},
                headers=headers,
            )
            if resp is None or resp.status_code != 200:
                logger.warning("[S2] 重试失败，放弃剩余批次")
                return

        if resp.status_code != 200:
            logger.warning("[S2] HTTP %d，跳过该批", resp.status_code)
            await asyncio.sleep(3)
            continue

        try:
            results = resp.json()
            for paper, s2 in zip(batch, results):
                if isinstance(s2, dict):
                    paper["citation_count"] = s2.get("citationCount") or 0
        except Exception as exc:
            logger.warning("[S2] 响应解析失败：%s", exc)

        # 每批间隔 3s，降低 429 风险
        if i + BATCH_SIZE < len(papers):
            await asyncio.sleep(3)


# ──────────────────────────────────────────────────────────────────────────────
# 热度评分
# ──────────────────────────────────────────────────────────────────────────────

def compute_score(paper: dict) -> float:
    """
    综合热度评分：
      - HF 点赞数权重最高（社区真实热度）
      - GitHub Stars 反映代码质量和关注度
      - 引用数反映学术影响力
    """
    return (
        paper["hf_upvotes"] * 2.0
        + paper.get("github_stars", 0) * 0.05
        + paper["citation_count"] * 0.5
    )


# ──────────────────────────────────────────────────────────────────────────────
# 报告生成
# ──────────────────────────────────────────────────────────────────────────────

def format_report(papers: list[dict], days: int, top_n: int) -> str:
    """将论文列表格式化为 Markdown 报告。"""
    now = datetime.now(TZ_CST).strftime("%Y-%m-%d")
    start = (datetime.now(TZ_CST) - timedelta(days=days)).strftime("%Y-%m-%d")

    lines = [
        f"# 🔥 AI 论文热度排行榜",
        f"",
        f"**统计周期**：{start} ～ {now}（过去 {days} 天）",
        f"**数据来源**：HuggingFace Daily Papers / Semantic Scholar",
        f"**生成时间**：{datetime.now(TZ_CST).strftime('%Y-%m-%d %H:%M:%S')} UTC+8",
        f"",
        f"---",
        f"",
        f"## Top-{min(top_n, len(papers))} 论文",
        f"",
    ]

    for rank, p in enumerate(papers[:top_n], start=1):
        score = compute_score(p)
        code_badge = f"[💻 Code]({p['code_url']})" if p["code_url"] else "🚫 无代码"
        authors_str = ", ".join(p["authors"][:3])
        if len(p["authors"]) > 3:
            authors_str += f" 等 {len(p['authors'])} 人"

        lines += [
            f"### #{rank} {p['title']}",
            f"",
            f"| 指标 | 数值 |",
            f"|------|------|",
            f"| 🔥 HF 点赞 | {p['hf_upvotes']} |",
            f"| ⭐ GitHub Stars | {p.get('github_stars', 0)} |",
            f"| 📖 引用数 | {p['citation_count']} |",
            f"| 📊 综合评分 | {score:.1f} |",
            f"| 📅 发布日期 | {p['published_date']} |",
            f"",
            f"**作者**：{authors_str}",
            f"",
            f"**摘要**：{p['abstract'][:300]}{'...' if len(p['abstract']) > 300 else ''}",
            f"",
            f"🔗 [论文]({p['url']}) | [PDF]({p['pdf_url']}) | {code_badge}",
            f"",
            f"---",
            f"",
        ]

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    args = parse_args()
    today = datetime.now(TZ_CST)

    logger.info("=" * 60)
    logger.info("🔥 AI 论文热度榜 — 过去 %d 天", args.days)
    logger.info("=" * 60)

    # 生成日期列表
    dates = [
        (today - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(args.days, 0, -1)
    ]

    all_papers: list[dict] = []
    seen_ids: set[str] = set()  # 跨日期去重

    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
    ) as client:
        # Step 1：逐日抓取 HF 热门论文
        logger.info("Step 1: 抓取 HuggingFace Daily Papers（%d 天）...", args.days)
        for date_str in dates:
            papers_today = await fetch_hf_one_day(client, date_str)
            new_count = 0
            for p in papers_today:
                if p["id"] not in seen_ids:
                    seen_ids.add(p["id"])
                    all_papers.append(p)
                    new_count += 1
            if papers_today:
                logger.info("  [%s] %d 篇（新增 %d）", date_str, len(papers_today), new_count)
            await asyncio.sleep(0.3)  # HF API 限速

        logger.info("HF 共收集 %d 篇（跨日去重后）", len(all_papers))
        code_count = sum(1 for p in all_papers if p["code_url"])
        logger.info("   ├── 有 GitHub 代码链接：%d 篇", code_count)

        if not all_papers:
            logger.error("未抓取到任何论文，请检查网络或 API 状态")
            return

        # Step 2：补充 S2 引用数
        if not args.skip_citations:
            logger.info("Step 2: 补充 Semantic Scholar 引用数（共 %d 篇）...", len(all_papers))
            await enrich_s2(client, all_papers)
            cit_count = sum(1 for p in all_papers if p["citation_count"] > 0)
            logger.info("S2 补充完成：%d / %d 篇有引用数据", cit_count, len(all_papers))
        else:
            logger.info("Step 2: 跳过 S2（--skip-citations）")

    # Step 3：按热度评分排名
    all_papers.sort(key=compute_score, reverse=True)
    top_papers = all_papers[: args.top]

    # Step 4：控制台摘要
    separator = "=" * 60
    print(f"\n{separator}")
    print(f"🔥 过去 {args.days} 天 AI 论文热度 Top-{len(top_papers)}")
    print(separator)
    print(f"{'排名':<4} {'HF赞':>5} {'GH⭐':>6} {'引用':>5}  标题")
    print("-" * 60)
    for rank, p in enumerate(top_papers, start=1):
        title_short = p["title"][:45] + "…" if len(p["title"]) > 45 else p["title"]
        print(f"#{rank:<3} {p['hf_upvotes']:>5} {p.get('github_stars', 0):>6} {p['citation_count']:>5}  {title_short}")
    print(separator)

    # Step 6：输出 Markdown
    report_md = format_report(all_papers, args.days, args.top)

    if args.output:
        out_path = Path(args.output)
    else:
        DEFAULT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        today_str = today.strftime("%Y-%m-%d")
        out_path = DEFAULT_OUTPUT_DIR / f"hot-papers-{today_str}-{args.days}d.md"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report_md, encoding="utf-8")
    print(f"\n📄 Markdown 报告已保存：{out_path.resolve()}\n")


if __name__ == "__main__":
    asyncio.run(main())
