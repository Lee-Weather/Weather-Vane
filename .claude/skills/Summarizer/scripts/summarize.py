#!/usr/bin/env python3
"""
summarize.py — AI 论文中文摘要生成器

读取 ranker 输出的 data/YYYY-MM-DD-ranked.json，调用 DeepSeek API 生成两级摘要：
  - 短摘要（summary_zh）：每日论文 150 字以内，三段式结构
  - 详细介绍（detail_zh）：周/月热门 500~800 字，七维度深度分析

用法：
    python summarize.py                  # 默认处理昨天
    python summarize.py --date 2026-04-30
    python summarize.py --skip-daily     # 跳过每日短摘要（调试用）
    python summarize.py --skip-detail    # 跳过详细介绍（调试用）
    python summarize.py --dry-run        # 只打印 Prompt，不调用 API
    python summarize.py --model deepseek-v4-pro  # 指定模型

输出：
    data/YYYY-MM-DD-summarized.json
"""

import argparse
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, APIStatusError, APIConnectionError, APITimeoutError

load_dotenv()  # 加载 .env 配置

# ──────────────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────────────

TZ_CST = timezone(timedelta(hours=8))

PROJECT_ROOT    = Path(__file__).resolve().parents[4]
DATA_DIR        = PROJECT_ROOT / "data"

# DeepSeek 模型配置
DEFAULT_MODEL     = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

MAX_TOKENS_SHORT  = 400    # 短摘要：150 字 ≈ 300 token，留余量
MAX_TOKENS_DETAIL = 2000   # 详细介绍：800 字 ≈ 1600 token，留余量

RETRY_DELAYS    = [2, 5, 15]  # 普通重试等待（秒）
RATE_LIMIT_WAIT = 60          # 429 限流等待（秒）
DAILY_INTERVAL  = 0.5         # 每日短摘要调用间隔（秒）

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
    parser = argparse.ArgumentParser(description="AI 论文中文摘要生成器")
    parser.add_argument("--date", type=str, default=None,
                        help="目标日期 YYYY-MM-DD（默认：昨天 UTC+8）")
    parser.add_argument("--skip-daily",  action="store_true",
                        help="跳过每日短摘要（调试用）")
    parser.add_argument("--skip-detail", action="store_true",
                        help="跳过周/月热门详细介绍（调试用）")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL,
                        help=f"DeepSeek 模型（默认：{DEFAULT_MODEL}）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印 Prompt，不实际调用 API")
    return parser.parse_args()

# ──────────────────────────────────────────────────────────────────────────────
# 数据加载
# ──────────────────────────────────────────────────────────────────────────────

def load_ranked(date_str: str) -> dict:
    """读取 ranker 输出的 ranked.json。"""
    path = DATA_DIR / f"{date_str}-ranked.json"
    if not path.exists():
        logger.error("ranked.json 不存在：%s", path)
        logger.error("请先运行 ranker 脚本生成数据")
        raise SystemExit(1)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        logger.info("读取 ranked.json 成功：%s", path)
        return data
    except json.JSONDecodeError as e:
        logger.error("ranked.json 解析失败：%s", e)
        raise SystemExit(1)

def write_summarized(data: dict, date_str: str) -> Path:
    """写入 summarized.json。"""
    out_path = DATA_DIR / f"{date_str}-summarized.json"
    out_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    logger.info("写入完成：%s", out_path)
    return out_path

# ──────────────────────────────────────────────────────────────────────────────
# Prompt 构建
# ──────────────────────────────────────────────────────────────────────────────

def build_short_prompt(paper: dict) -> str:
    """构建短摘要 Prompt（150 字以内）。"""
    return f"""你是一位 AI 和机器人领域的研究助手，请对以下论文生成简洁的中文摘要。

论文标题：{paper.get('title', '')}
论文摘要（英文）：{paper.get('abstract', '')}

请按以下格式生成 **150 字以内** 的中文摘要：
1. 核心问题（1句）：这篇论文要解决什么问题？
2. 方法与创新点（1-2句）：用了什么方法，有什么独特之处？
3. 关键结论/指标（1句）：取得了什么效果？

要求：
- 使用中文技术术语，但保留关键英文缩写（如 LLM、RL、SLAM）
- 数据必须准确，不编造实验数据
- 严格不超过 150 字，直接输出摘要正文，无需重复标题"""


def build_detail_prompt(paper: dict, hot_type: str) -> str:
    """构建详细介绍 Prompt（500~800 字）。"""
    hot_label = "本周" if hot_type == "weekly" else "本月"
    return f"""你是一位 AI 和机器人领域的资深研究员，请对以下论文写一篇详细的中文技术介绍。

论文标题：{paper.get('title', '')}
论文摘要（英文）：{paper.get('abstract', '')}
HF 点赞数：{paper.get('hf_upvotes', 0)}，GitHub Stars：{paper.get('pwc_stars', 0)}，学术引用数：{paper.get('citation_count', 0)}
论文链接：{paper.get('url', '')}

请按以下格式生成 **500-800 字** 的中文详细介绍：

**1. 研究背景与动机（2-3 句）**
为什么这个问题值得研究？当前有哪些局限性？

**2. 核心问题定义（1-2 句）**
论文精确要解决什么问题？

**3. 方法论详解（3-5 句）**
核心技术路线是什么？有哪些技术细节值得关注？（保留关键英文缩写）

**4. 实验结果与关键指标（2-3 句）**
在哪些数据集/场景上测试？取得了哪些可量化的效果？

**5. 与现有工作对比（1-2 句）**
相比 SOTA 或主流方法，优势在哪里？

**6. 实际意义与未来展望（1-2 句）**
这项工作对工业界/学术界有何影响？

**7. 推荐理由（1 句）**
为何{hot_label}特别值得关注？

要求：
- 准确忠实于原文，不编造数据
- 技术细节具体，不说空话
- 500-800 字，不超过上限
- 直接输出正文，使用加粗标题区分各段"""

# ──────────────────────────────────────────────────────────────────────────────
# LLM 调用
# ──────────────────────────────────────────────────────────────────────────────

def call_llm(
    client: OpenAI,
    prompt: str,
    model: str,
    max_tokens: int,
    dry_run: bool = False,
) -> str | None:
    """
    调用 DeepSeek API（OpenAI 射化接口），带重试逻辑。
    - 超时 / 网络错误：重试 3 次（间隔 2s / 5s / 15s）
    - 429 限流：等待 60s 后重试
    - 全部失败：返回 None
    """
    if dry_run:
        print("\n" + "─" * 60)
        print("[DRY RUN] Prompt 预览：")
        print(prompt[:500] + ("..." if len(prompt) > 500 else ""))
        print("─" * 60 + "\n")
        return "[DRY RUN 模式，未调用 API]"

    for attempt, delay in enumerate(RETRY_DELAYS + [None], start=1):
        try:
            resp = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.choices[0].message.content.strip()

        except APIStatusError as e:
            if e.status_code == 429:
                logger.warning("[LLM] 429 限流，等待 %ds 后重试（第 %d 次）", RATE_LIMIT_WAIT, attempt)
                time.sleep(RATE_LIMIT_WAIT)
            else:
                logger.error("[LLM] API 错误 %d：%s", e.status_code, e)
                return None

        except (APITimeoutError, APIConnectionError) as e:
            if delay is None:
                logger.error("[LLM] 超时/连接失败，已重试 %d 次，放弃", len(RETRY_DELAYS))
                return None
            logger.warning("[LLM] 请求异常（%s），%ds 后重试", type(e).__name__, delay)
            time.sleep(delay)

        except Exception as e:
            logger.error("[LLM] 未知错误：%s", e)
            return None

    return None

# ──────────────────────────────────────────────────────────────────────────────
# 摘要生成
# ──────────────────────────────────────────────────────────────────────────────

def summarize_one(
    client: OpenAI,
    paper: dict,
    model: str,
    dry_run: bool,
) -> str | None:
    """生成单篇短摘要。"""
    prompt = build_short_prompt(paper)
    result = call_llm(client, prompt, model, MAX_TOKENS_SHORT, dry_run)
    if result is None:
        logger.warning("[短摘要] 失败：%s", paper.get("id", "?"))
    return result


def summarize_detail(
    client: OpenAI,
    paper: dict,
    hot_type: str,
    model: str,
    dry_run: bool,
) -> tuple[str | None, str | None]:
    """
    生成热门论文的短摘要 + 详细介绍。
    返回 (summary_zh, detail_zh)。
    """
    paper_id = paper.get("id", "?")

    logger.info("[详细介绍] 开始处理：%s", paper_id)
    detail = call_llm(client, build_detail_prompt(paper, hot_type), model, MAX_TOKENS_DETAIL, dry_run)
    if detail is None:
        logger.warning("[详细介绍] 失败：%s", paper_id)

    logger.info("[短摘要] 开始处理（热门）：%s", paper_id)
    summary = call_llm(client, build_short_prompt(paper), model, MAX_TOKENS_SHORT, dry_run)
    if summary is None:
        logger.warning("[短摘要] 失败（热门）：%s", paper_id)

    return summary, detail

# ──────────────────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    # 确定目标日期
    if args.date:
        date_str = args.date
    else:
        date_str = (datetime.now(TZ_CST) - timedelta(days=1)).strftime("%Y-%m-%d")

    logger.info("=" * 60)
    logger.info("✍️  Summarizer 开始 — 目标日期：%s", date_str)
    logger.info("=" * 60)

    # 读取 ranked.json
    data = load_ranked(date_str)

    daily_robot  = data.get("daily_robot", [])
    daily_ai     = data.get("daily_ai", [])
    weekly_hot   = data.get("weekly_hot")
    monthly_hot  = data.get("monthly_hot")

    total_input = len(daily_robot) + len(daily_ai)
    hot_count   = (1 if weekly_hot else 0) + (1 if monthly_hot else 0)
    logger.info("输入论文：%d 篇每日 + %d 篇热门", total_input, hot_count)

    # 初始化 DeepSeek 客户端（OpenAI 兼容）
    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not api_key and not args.dry_run:
        logger.error("未设置 DEEPSEEK_API_KEY 环境变量")
        raise SystemExit(1)
    client: OpenAI | None = (
        OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
        if not args.dry_run else None
    )

    stats = {"short_ok": 0, "short_fail": 0, "detail_ok": 0, "detail_fail": 0}

    # ── Step 1: 处理周热门 ───────────────────────────────────────────────────
    if weekly_hot and not args.skip_detail:
        logger.info("Step 1: 处理周热门（详细介绍）...")
        summary, detail = summarize_detail(client, weekly_hot, "weekly", args.model, args.dry_run)
        weekly_hot["summary_zh"] = summary
        weekly_hot["detail_zh"]  = detail
        if detail: stats["detail_ok"] += 1
        else:       stats["detail_fail"] += 1
        if summary: stats["short_ok"] += 1
        else:        stats["short_fail"] += 1
    elif weekly_hot:
        weekly_hot["summary_zh"] = None
        weekly_hot["detail_zh"]  = None

    # ── Step 2: 处理月热门 ───────────────────────────────────────────────────
    if monthly_hot and not args.skip_detail:
        # 若与周热门是同一篇，直接复用 detail_zh
        if weekly_hot and monthly_hot.get("id") == weekly_hot.get("id"):
            logger.info("Step 2: 月热门与周热门同篇，复用摘要")
            monthly_hot["summary_zh"] = weekly_hot.get("summary_zh")
            monthly_hot["detail_zh"]  = weekly_hot.get("detail_zh")
        else:
            logger.info("Step 2: 处理月热门（详细介绍）...")
            summary, detail = summarize_detail(client, monthly_hot, "monthly", args.model, args.dry_run)
            monthly_hot["summary_zh"] = summary
            monthly_hot["detail_zh"]  = detail
            if detail: stats["detail_ok"] += 1
            else:       stats["detail_fail"] += 1
            if summary: stats["short_ok"] += 1
            else:        stats["short_fail"] += 1
    elif monthly_hot:
        monthly_hot["summary_zh"] = None
        monthly_hot["detail_zh"]  = None

    # ── Step 3: 处理 daily_robot 短摘要 ────────────────────────────────────
    if daily_robot and not args.skip_daily:
        logger.info("Step 3: 处理机器人组短摘要（%d 篇）...", len(daily_robot))
        for i, paper in enumerate(daily_robot, start=1):
            logger.info("  [%d/%d] %s", i, len(daily_robot), paper.get("id", "?"))
            result = summarize_one(client, paper, args.model, args.dry_run)
            paper["summary_zh"] = result
            if result: stats["short_ok"] += 1
            else:       stats["short_fail"] += 1
            if i < len(daily_robot) and not args.dry_run:
                time.sleep(DAILY_INTERVAL)
    else:
        for paper in daily_robot:
            paper["summary_zh"] = None

    # ── Step 4: 处理 daily_ai 短摘要 ───────────────────────────────────────
    if daily_ai and not args.skip_daily:
        logger.info("Step 4: 处理 AI 组短摘要（%d 篇）...", len(daily_ai))
        for i, paper in enumerate(daily_ai, start=1):
            logger.info("  [%d/%d] %s", i, len(daily_ai), paper.get("id", "?"))
            result = summarize_one(client, paper, args.model, args.dry_run)
            paper["summary_zh"] = result
            if result: stats["short_ok"] += 1
            else:       stats["short_fail"] += 1
            if i < len(daily_ai) and not args.dry_run:
                time.sleep(DAILY_INTERVAL)
    else:
        for paper in daily_ai:
            paper["summary_zh"] = None

    # ── Step 5: 写入输出 ────────────────────────────────────────────────────
    result_data = {
        "date":          date_str,
        "daily_robot":   daily_robot,
        "daily_ai":      daily_ai,
        "weekly_hot":    weekly_hot,
        "monthly_hot":   monthly_hot,
    }
    out_path = write_summarized(result_data, date_str)

    # ── Step 6: 打印统计 ────────────────────────────────────────────────────
    separator = "=" * 60
    print(f"\n{separator}")
    print(f"✅ Summarizer 完成 — {date_str}")
    print(separator)
    print(f"📥 输入论文：{total_input} 篇每日 + {hot_count} 篇热门")
    print(f"✍️  短摘要生成：{stats['short_ok']} 成功 / {stats['short_fail']} 失败")
    print(f"📖 详细介绍生成：{stats['detail_ok']} 成功 / {stats['detail_fail']} 失败")
    if stats["short_fail"] + stats["detail_fail"] > 0:
        print(f"⚠️  共 {stats['short_fail'] + stats['detail_fail']} 篇生成失败，已置 null")
    print(f"📄 输出路径：{out_path.resolve()}")
    print(separator + "\n")


if __name__ == "__main__":
    main()
