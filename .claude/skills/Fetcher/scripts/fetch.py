#!/usr/bin/env python3
"""
Fetcher Skill 抓取脚本 — AI 论文每日推送系统

从 arXiv、HuggingFace Daily Papers、Papers With Code、Semantic Scholar
并发/串行抓取当日最新 AI 论文元数据，合并去重后写入标准化 JSON 文件。

用法：
    python3 fetch.py --date YYYY-MM-DD
    python3 fetch.py                    # 默认今日 UTC+8
    python3 fetch.py --skip-citations   # 跳过引用数补充，加快速度

输出：
    data/YYYY-MM-DD-raw.json
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import httpx
import yaml
from dateutil import parser as date_parser

# ──────────────────────────────────────────────────────────────────────────────
# 常量与配置
# ──────────────────────────────────────────────────────────────────────────────

# 项目根目录（fetch.py 位于 <project>/.claude/skills/Fetcher/scripts/fetch.py）
# parents[0]=scripts  parents[1]=Fetcher  parents[2]=skills  parents[3]=.claude  parents[4]=project_root
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data"

# 时区 UTC+8
TZ_CST = timezone(timedelta(hours=8))

# arXiv API
ARXIV_API_URL = "https://export.arxiv.org/api/query"  # 使用 HTTPS，避免 301 重定向

# 从配置文件读取搜索主题与参数
_SKILL_DIR = Path(__file__).resolve().parents[1]
_CONFIG_PATH = _SKILL_DIR / "config.yaml"
_DEFAULT_CATEGORIES = "cat:cs.AI+OR+cat:cs.RO"
_DEFAULT_MAX_RESULTS = 100
try:
    _cfg = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
    _topics = _cfg.get("topics", [])
    ARXIV_CATEGORIES = "+OR+".join(
        f"cat:{t['arxiv_category']}" for t in _topics if t.get("arxiv_category")
    ) or _DEFAULT_CATEGORIES
    ARXIV_MAX_RESULTS = _cfg.get("arxiv", {}).get("max_results", _DEFAULT_MAX_RESULTS)
except Exception:
    logging.warning("配置文件 %s 加载失败，使用默认分类", _CONFIG_PATH)
    ARXIV_CATEGORIES = _DEFAULT_CATEGORIES
    ARXIV_MAX_RESULTS = _DEFAULT_MAX_RESULTS

# HuggingFace Daily Papers API
HF_API_URL = "https://huggingface.co/api/daily_papers"

# Papers With Code API
PWC_API_URL = "https://paperswithcode.com/api/v1/papers/"

# Semantic Scholar Batch API
S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"
S2_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")

# HTTP 超时与重试
HTTP_TIMEOUT = 30.0
RETRY_DELAYS = [1, 2, 4]  # 指数退避间隔（秒）

# arXiv 限速：单 IP 每秒不超过 3 次请求
ARXIV_RATE_LIMIT_SECONDS = 1.0 / 3

# arXiv API 可用性检查：不可用时等待后重试
ARXIV_CHECK_INTERVAL    = 300  # 重试间隔（秒），即 5 分钟
ARXIV_CHECK_MAX_RETRIES = 3    # 最大重试次数

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 3-1: 参数解析
# ──────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """解析命令行参数，默认日期为今日 UTC+8。"""
    parser = argparse.ArgumentParser(
        description="抓取当日最新 AI 论文元数据并保存为 JSON 文件"
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="目标日期，格式 YYYY-MM-DD（默认：今日 UTC+8）",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"输出目录（默认：{DEFAULT_OUTPUT_DIR}）",
    )
    parser.add_argument(
        "--skip-citations",
        action="store_true",
        default=False,
        help="跳过 Semantic Scholar 引用数补充（加快速度）",
    )

    args = parser.parse_args()

    # 未指定日期时使用今日 UTC+8
    if args.date is None:
        args.date = datetime.now(TZ_CST).strftime("%Y-%m-%d")
        logger.info("未指定日期，使用今日 UTC+8：%s", args.date)
    else:
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            logger.error("日期格式错误：%s，应为 YYYY-MM-DD", args.date)
            sys.exit(1)

    return args


# ──────────────────────────────────────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────────────────────────────────────

def normalize_arxiv_id(raw_id: str) -> str:
    """
    将 arXiv 原始 ID 规范化为 'arxiv:XXXX.XXXXX' 格式，去除版本号后缀。
    示例：http://arxiv.org/abs/2401.12345v1 → arxiv:2401.12345
    """
    match = re.search(r"(\d{4}\.\d{4,5})", raw_id)
    if match:
        return f"arxiv:{match.group(1)}"
    return f"arxiv:{raw_id}"


def make_paper_template(arxiv_id: str) -> dict:
    """
    创建具有默认值的论文记录模板。
    hf_upvotes / pwc_stars / code_url / citation_count 不预设，
    只在真正获取到有效值时才写入。
    """
    bare_id = arxiv_id.removeprefix("arxiv:")
    return {
        "id": arxiv_id,
        "title": "",
        "authors": [],
        "abstract": "",
        "url": f"https://arxiv.org/abs/{bare_id}",
        "pdf_url": f"https://arxiv.org/pdf/{bare_id}",
        "published_date": "",
        "categories": [],
        "source": "arxiv",
    }


async def fetch_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs,
) -> httpx.Response | None:
    """
    带指数退避重试的 HTTP 请求（3-8: 错误处理层）。
    - 超时 / ConnectError：重试最多 3 次（间隔 1s / 2s / 4s）
    - 5xx：重试；4xx / 2xx：直接返回
    - 全部重试失败：返回 None，由调用方执行降级
    """
    for attempt, delay in enumerate([0] + RETRY_DELAYS, start=1):
        if delay > 0:
            logger.debug("第 %d 次重试，等待 %ds...", attempt, delay)
            await asyncio.sleep(delay)
        try:
            resp = await client.request(method, url, **kwargs)
            if resp.status_code < 500:
                return resp  # 2xx / 4xx 直接返回，不重试
            logger.warning("HTTP %d（第 %d 次），将重试：%s", resp.status_code, attempt, url)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            logger.warning("请求失败（第 %d 次）：%s — %s", attempt, url, exc)

    logger.error("所有重试均失败，放弃：%s", url)
    return None


# ──────────────────────────────────────────────────────────────────────────────
# 3-2: 抓取 arXiv
# ──────────────────────────────────────────────────────────────────────────────

async def check_arxiv_available(client: httpx.AsyncClient) -> bool:
    """
    发送轻量探测请求，检查 arXiv API 当前是否可用。
    使用 max_results=1 的最小查询，成功响应且 feed 可解析则返回 True。
    """
    probe_url = f"{ARXIV_API_URL}?search_query=cat:cs.AI&max_results=1"
    try:
        resp = await client.get(probe_url, timeout=15)
        if resp.status_code != 200:
            return False
        feed = feedparser.parse(resp.text)
        # feed 结构存在即视为可用（entries 可为空，如周末正常）
        return feed.get("feed") is not None or hasattr(feed, "entries")
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        logger.debug("arXiv 探测失败：%s", exc)
        return False


async def fetch_arxiv(client: httpx.AsyncClient, date: str) -> list[dict]:
    """
    从 arXiv API 抓取当日论文（分类由 config.yaml 配置）。
    端点：https://export.arxiv.org/api/query
    空结果时返回 [] 并记录 WARN（节假日/周末正常现象）。
    """
    logger.info("开始抓取 arXiv（日期：%s）...", date)

    # 正式抓取前先检查 API 可用性，不可用时等待 5 分钟重试，最多 3 次
    for check_attempt in range(1, ARXIV_CHECK_MAX_RETRIES + 1):
        if await check_arxiv_available(client):
            logger.debug("arXiv API 可用（第 %d 次检查通过）", check_attempt)
            break
        if check_attempt < ARXIV_CHECK_MAX_RETRIES:
            logger.warning(
                "arXiv API 暂不可用（第 %d/%d 次），%d 分钟后重试...",
                check_attempt, ARXIV_CHECK_MAX_RETRIES, ARXIV_CHECK_INTERVAL // 60,
            )
            await asyncio.sleep(ARXIV_CHECK_INTERVAL)
        else:
            logger.error(
                "arXiv API 连续 %d 次检查均不可用，跳过本次抓取",
                ARXIV_CHECK_MAX_RETRIES,
            )
            return []

    target_dt = datetime.strptime(date, "%Y-%m-%d")

    # arXiv 周一公告包含上周四/五/周末的提交，需扩大查询窗口
    # weekday(): 0=Mon, 1=Tue, ..., 6=Sun
    if target_dt.weekday() == 0:  # 周一
        submit_lookback = 4       # submittedDate 回溯到上周四
        filter_lookback = 5       # published_date 过滤回溯到上周三（含时区余量）
    else:
        submit_lookback = 1       # 正常 ±1 天
        filter_lookback = 2

    # published_date 过滤范围
    # arXiv submittedDate 查询用 UTC，但 published 转 UTC+8 后日期可能 +1 天，
    # 因此过滤窗口需要比查询窗口更宽，避免时区偏移导致误过滤
    date_filter_from = (target_dt - timedelta(days=filter_lookback)).strftime("%Y-%m-%d")
    date_filter_to   = (target_dt + timedelta(days=2)).strftime("%Y-%m-%d")

    # arXiv submittedDate 范围格式：YYYYMMDD0000
    date_from_arxiv = (target_dt - timedelta(days=submit_lookback)).strftime("%Y%m%d") + "0000"
    date_to_arxiv   = (target_dt + timedelta(days=1)).strftime("%Y%m%d") + "2359"
    date_range = f"submittedDate:[{date_from_arxiv}+TO+{date_to_arxiv}]"

    # arXiv 限速等待
    await asyncio.sleep(ARXIV_RATE_LIMIT_SECONDS)

    # 注意：直接拼接 URL 字符串，不使用 params={}。
    # httpx 会将 params 中的 ":" 编码为 "%3A"，"+" 编码为 "%2B"，
    # 但 arXiv API 要求这两个字符保持原样（未编码），否则返回空 feed。
    # 查询格式：(分类过滤) AND submittedDate:[from TO to]
    search_query = f"({ARXIV_CATEGORIES})+AND+{date_range}"
    raw_url = (
        f"{ARXIV_API_URL}"
        f"?search_query={search_query}"
        f"&sortBy=submittedDate"
        f"&sortOrder=descending"
        f"&max_results={ARXIV_MAX_RESULTS}"
    )
    resp = await fetch_with_retry(client, "GET", raw_url)
    if resp is None or resp.status_code != 200:
        logger.warning("arXiv API 请求失败，返回空列表")
        return []

    feed = feedparser.parse(resp.text)
    if not feed.entries:
        logger.warning("arXiv 返回空 feed（可能为节假日/周末），日期：%s", date)
        return []

    papers = []
    for entry in feed.entries:
        try:
            arxiv_id = normalize_arxiv_id(entry.get("id", ""))

            # 发布日期：UTC → UTC+8
            published_raw = entry.get("published", "")
            published_dt = date_parser.parse(published_raw).astimezone(TZ_CST)
            published_date = published_dt.strftime("%Y-%m-%d")

            # 仅保留目标日期 ±1 天范围内的论文（双边过滤，防止 arXiv 返回其他日期数据）
            if published_date < date_filter_from or published_date > date_filter_to:
                continue

            # 提取 PDF 链接
            pdf_url = next(
                (lk.get("href", "") for lk in entry.get("links", [])
                 if lk.get("type") == "application/pdf"),
                f"https://arxiv.org/pdf/{arxiv_id.removeprefix('arxiv:')}",
            )

            categories = [tag.get("term", "") for tag in entry.get("tags", [])]

            paper = make_paper_template(arxiv_id)
            paper.update({
                "title": entry.get("title", "").replace("\n", " ").strip(),
                "authors": [a.get("name", "") for a in entry.get("authors", [])],
                "abstract": entry.get("summary", "").replace("\n", " ").strip(),
                "url": f"https://arxiv.org/abs/{arxiv_id.removeprefix('arxiv:')}",
                "pdf_url": pdf_url,
                "published_date": published_date,
                "categories": categories,
            })
            papers.append(paper)

        except Exception as exc:
            logger.error("解析条目失败（%s）：%s，跳过", entry.get("id", "?"), exc)

    logger.info("arXiv 抓取完成：%d 篇", len(papers))
    return papers


# ──────────────────────────────────────────────────────────────────────────────
# 3-3: 抓取 HuggingFace Daily Papers
# ──────────────────────────────────────────────────────────────────────────────

async def fetch_huggingface(client: httpx.AsyncClient, date: str) -> dict[str, dict]:
    """
    从 HuggingFace Daily Papers API 获取热门论文点赞数、GitHub 代码链接和 Stars。
    端点：https://huggingface.co/api/daily_papers?date=YYYY-MM-DD
    返回 {arxiv_id: {upvotes, github_stars, code_url}} 映射字典，失败时返回 {}（静默降级）。
    """
    logger.info("开始抓取 HuggingFace Daily Papers（日期：%s）...", date)

    resp = await fetch_with_retry(client, "GET", HF_API_URL, params={"date": date})

    if resp is None or resp.status_code not in (200,):
        code = resp.status_code if resp else "无响应"
        logger.warning("HuggingFace API 失败（HTTP %s），降级跳过", code)
        return {}

    try:
        items = resp.json()
    except Exception as exc:
        logger.warning("HuggingFace 响应解析失败：%s，降级跳过", exc)
        return {}

    hf_map: dict[str, dict] = {}
    for item in items:
        try:
            paper = item.get("paper", {})
            raw_id = paper.get("id", "")
            if raw_id:
                hf_map[f"arxiv:{raw_id}"] = {
                    "upvotes": paper.get("upvotes", 0) or 0,
                    "github_stars": paper.get("githubStars", 0) or 0,
                    "code_url": paper.get("githubRepo") or None,
                }
        except Exception as exc:
            logger.error("解析 HF 条目失败：%s，跳过", exc)

    logger.info("HuggingFace 抓取完成：%d 篇有点赞数据", len(hf_map))
    return hf_map


# ──────────────────────────────────────────────────────────────────────────────
# 3-4: 合并 arXiv + HF 数据
# ──────────────────────────────────────────────────────────────────────────────

def merge_papers(arxiv_papers: list[dict], hf_map: dict[str, dict]) -> list[dict]:
    """
    以 arxiv_id 为主键合并 arXiv 和 HuggingFace 数据，去除重复条目。
    HF 数据补充 hf_upvotes、github_stars、code_url，基础记录以 arXiv 为准。
    """
    seen: set[str] = set()
    merged: list[dict] = []

    for paper in arxiv_papers:
        pid = paper["id"]
        if pid in seen:
            logger.debug("去重：跳过重复 ID %s", pid)
            continue
        seen.add(pid)

        # 补充 HF 数据（点赞数、GitHub Stars、代码链接）
        hf = hf_map.get(pid)
        if hf:
            if hf["upvotes"] > 0:
                paper["hf_upvotes"] = hf["upvotes"]
            if hf["github_stars"] > 0:
                paper["pwc_stars"] = hf["github_stars"]
            if hf["code_url"]:
                paper["code_url"] = hf["code_url"]

        merged.append(paper)

    hf_matched = sum(1 for p in merged if p.get("hf_upvotes", 0) > 0)
    logger.info("合并完成：%d 篇（去重后），其中 %d 篇有 HF 点赞数", len(merged), hf_matched)
    return merged


# ──────────────────────────────────────────────────────────────────────────────
# 3-5: 补充 Papers With Code 数据
# ──────────────────────────────────────────────────────────────────────────────

async def fetch_pwc(
    client: httpx.AsyncClient,
    date: str,
    papers: list[dict],
) -> list[dict]:
    """
    从 Papers With Code API 补充代码链接和 stars。
    端点：https://paperswithcode.com/api/v1/papers/
    按 arxiv_id 匹配，失败时静默降级，不中断主流程。
    """
    logger.info("开始补充 Papers With Code 数据...")

    date_after = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    resp = await fetch_with_retry(
        client, "GET", PWC_API_URL,
        params={"ordering": "-published", "date_after": date_after, "page_size": 50},
    )

    if resp is None or resp.status_code != 200:
        logger.warning("Papers With Code API 失败，降级跳过")
        return papers

    try:
        pwc_items = resp.json().get("results", [])
    except Exception as exc:
        logger.warning("PWC 响应解析失败：%s，降级跳过", exc)
        return papers

    # 构建 arxiv_id → {code_url, pwc_stars} 映射
    pwc_map: dict[str, dict] = {}
    for item in pwc_items:
        try:
            raw_arxiv = item.get("arxiv_id", "")
            if not raw_arxiv:
                continue
            repos = item.get("repositories", [])
            pwc_map[f"arxiv:{raw_arxiv}"] = {
                "code_url": repos[0].get("url") if repos else None,
                "pwc_stars": sum(r.get("stars", 0) for r in repos),
            }
        except Exception as exc:
            logger.error("解析 PWC 条目失败：%s，跳过", exc)

    # 按 arxiv_id 匹配补充（只写入有效值）
    matched = 0
    for paper in papers:
        entry = pwc_map.get(paper["id"])
        if entry is None:
            continue
        if entry["code_url"]:
            paper["code_url"] = entry["code_url"]
        if entry["pwc_stars"] > 0:
            paper["pwc_stars"] = entry["pwc_stars"]
        if entry["code_url"] or entry["pwc_stars"] > 0:
            matched += 1

    logger.info("PWC 匹配完成：%d / %d 篇有代码链接或 Stars", matched, len(papers))
    return papers


# ──────────────────────────────────────────────────────────────────────────────
# 3-6: 补充 Semantic Scholar 引用数（可选）
# ──────────────────────────────────────────────────────────────────────────────

async def enrich_citations(
    client: httpx.AsyncClient,
    papers: list[dict],
) -> list[dict]:
    """
    批量请求 Semantic Scholar API 补充引用数（可选增强）。
    端点：POST https://api.semanticscholar.org/graph/v1/paper/batch
    429 限流或任何失败时静默跳过，citation_count 不写入（字段不存在表示未获取到）。
    """
    logger.info("开始补充 Semantic Scholar 引用数（共 %d 篇）...", len(papers))

    headers = {"Content-Type": "application/json"}
    if S2_API_KEY:
        headers["x-api-key"] = S2_API_KEY

    BATCH_SIZE = 50
    enriched = 0

    for i in range(0, len(papers), BATCH_SIZE):
        batch = papers[i: i + BATCH_SIZE]
        s2_ids = [f"ARXIV:{p['id'].removeprefix('arxiv:')}" for p in batch]

        resp = await fetch_with_retry(
            client, "POST", S2_BATCH_URL,
            json={"ids": s2_ids},
            params={"fields": "citationCount"},
            headers=headers,
        )

        if resp is None or resp.status_code == 429:
            logger.warning("Semantic Scholar 不可用（限流或失败），跳过剩余批次")
            break

        if resp.status_code != 200:
            logger.warning("Semantic Scholar 返回 HTTP %d，跳过该批", resp.status_code)
            await asyncio.sleep(3)
            continue

        try:
            results = resp.json()
            for paper, s2 in zip(batch, results):
                if isinstance(s2, dict):
                    count = s2.get("citationCount") or 0
                    if count > 0:
                        paper["citation_count"] = count
                        enriched += 1
        except Exception as exc:
            logger.warning("Semantic Scholar 响应解析失败：%s，跳过", exc)

        # 每批间隔 3s，降低 429 风险
        if i + BATCH_SIZE < len(papers):
            await asyncio.sleep(3)

    logger.info("引用数补充完成：%d / %d 篇有引用数据", enriched, len(papers))
    return papers


# ──────────────────────────────────────────────────────────────────────────────
# 3-7: 写入输出文件
# ──────────────────────────────────────────────────────────────────────────────

def save_output(papers: list[dict], date: str, output_dir: str) -> str:
    """
    将论文列表写入 data/YYYY-MM-DD-raw.json。
    自动创建输出目录，返回输出文件的绝对路径。
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    filename = out_path / f"{date}-raw.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(papers, f, ensure_ascii=False, indent=2)

    abs_path = str(filename.resolve())
    logger.info("已写入：%s（%d 篇）", abs_path, len(papers))
    return abs_path


# ──────────────────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    args = parse_args()
    date: str = args.date
    output_dir: str = args.output_dir
    skip_citations: bool = args.skip_citations

    logger.info("=" * 60)
    logger.info("AI 论文抓取开始 — 目标日期：%s", date)
    logger.info("=" * 60)

    counts = {"arxiv": 0, "hf_matched": 0, "pwc_matched": 0, "citation_enriched": 0}

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        # Step 1：并发请求 arXiv + HuggingFace
        arxiv_papers, hf_map = await asyncio.gather(
            fetch_arxiv(client, date),
            fetch_huggingface(client, date),
        )
        counts["arxiv"] = len(arxiv_papers)

        # Step 2：合并去重
        papers = merge_papers(arxiv_papers, hf_map)
        counts["hf_matched"] = sum(1 for p in papers if p.get("hf_upvotes", 0) > 0)

        # arXiv 全空（节假日）：保存空列表并提前退出
        if not papers:
            output_path = save_output([], date, output_dir)
            print(f"\n{'=' * 60}")
            print(f"[WARN] 今日 ({date}) 无新论文（arXiv 未更新）")
            print(f"输出路径：{output_path}")
            print(f"{'=' * 60}")
            return

        # Step 3：串行补充 PWC 数据
        papers = await fetch_pwc(client, date, papers)
        counts["pwc_matched"] = sum(1 for p in papers if p.get("code_url"))

        # Step 4：批量补充引用数（可跳过）
        if not skip_citations:
            papers = await enrich_citations(client, papers)
            counts["citation_enriched"] = sum(1 for p in papers if p.get("citation_count", 0) > 0)
        else:
            logger.info("已跳过 Semantic Scholar 引用数补充（--skip-citations）")

    # Step 5：写入文件
    output_path = save_output(papers, date, output_dir)

    # 最终摘要报告（供 ranker Skill 和用户读取）
    separator = "=" * 60
    print(f"\n{separator}")
    print(f"AI 论文抓取完成 - {date}")
    print(f"{separator}")
    print(f"输出路径: {output_path}")
    print(f"论文总数: {len(papers)} 篇")
    print(f"  arXiv 来源:       {counts['arxiv']} 篇")
    print(f"  HF 有点赞数:      {counts['hf_matched']} 篇")
    print(f"  PWC 有代码链接:   {counts['pwc_matched']} 篇")
    print(f"  有引用数据:       {counts['citation_enriched']} 篇")
    print(f"{separator}\n")


if __name__ == "__main__":
    asyncio.run(main())
