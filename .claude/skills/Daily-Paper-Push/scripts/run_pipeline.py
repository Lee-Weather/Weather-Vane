#!/usr/bin/env python3
"""
run_pipeline.py — AI 论文每日推送系统 主调度器

按顺序串联五个子 Skill 脚本，完成从论文抓取到邮件推送的完整流水线。

用法：
    python run_pipeline.py                         # 默认处理昨天 (UTC+8)
    python run_pipeline.py --date 2026-04-30       # 指定日期
    python run_pipeline.py --dry-run               # 全流程但不调API、不发邮件
    python run_pipeline.py --skip-fetch            # 跳过抓取（使用已有 raw.json）
    python run_pipeline.py --skip-summarize        # 跳过摘要生成
    python run_pipeline.py --skip-email            # 跳过邮件推送
    python run_pipeline.py --start-from ranker     # 从某步开始

流水线：
    Fetcher → Ranker → Summarizer → Storage → Notifier
"""

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────────────

TZ_CST = timezone(timedelta(hours=8))

# 项目根目录（run_pipeline.py 位于 .claude/skills/Daily-Paper-Push/scripts/）
PROJECT_ROOT = Path(__file__).resolve().parents[4]
SKILLS_DIR   = PROJECT_ROOT / ".claude" / "skills"
DATA_DIR     = PROJECT_ROOT / "data"

# Python 解释器：使用与当前脚本相同的解释器
PYTHON = sys.executable

# ──────────────────────────────────────────────────────────────────────────────
# 日志
# ──────────────────────────────────────────────────────────────────────────────

# Windows 终端 GBK 编码兼容
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# 步骤定义
# ──────────────────────────────────────────────────────────────────────────────

# 各步骤的脚本路径、参数构建函数和是否为关键步骤（失败时终止流水线）
STEPS = [
    {
        "name": "fetcher",
        "label": "1/5 Fetcher  — 论文抓取",
        "emoji": "📥",
        "script": SKILLS_DIR / "Fetcher" / "scripts" / "fetch.py",
        "critical": True,   # 失败则终止
    },
    {
        "name": "ranker",
        "label": "2/5 Ranker   — 过滤排名",
        "emoji": "📊",
        "script": SKILLS_DIR / "Ranker" / "scripts" / "rank.py",
        "critical": True,
    },
    {
        "name": "summarizer",
        "label": "3/5 Summarizer — 摘要生成",
        "emoji": "📝",
        "script": SKILLS_DIR / "Summarizer" / "scripts" / "summarize.py",
        "critical": False,  # 失败可降级
    },
    {
        "name": "storage",
        "label": "4/5 Storage  — 数据入库",
        "emoji": "💾",
        "script": SKILLS_DIR / "Storage" / "scripts" / "save.py",
        "critical": False,
    },
    {
        "name": "notifier",
        "label": "5/5 Notifier — 日报推送",
        "emoji": "📧",
        "script": SKILLS_DIR / "Notifier" / "scripts" / "notify.py",
        "critical": False,
    },
]


def build_step_args(step_name: str, date_str: str, dry_run: bool, skip_email: bool) -> list[str]:
    """根据步骤名称构建命令行参数列表。"""
    if step_name == "fetcher":
        args = ["--date", date_str]
        if dry_run:
            args.append("--skip-citations")
        return args

    elif step_name == "ranker":
        return ["--date", date_str]

    elif step_name == "summarizer":
        args = ["--date", date_str]
        if dry_run:
            args.append("--dry-run")
        return args

    elif step_name == "storage":
        json_path = str(DATA_DIR / f"{date_str}-summarized.json")
        return ["--save", json_path]

    elif step_name == "notifier":
        args = ["--date", date_str]
        if dry_run or skip_email:
            args.append("--skip-email")
        return args

    return []


# ──────────────────────────────────────────────────────────────────────────────
# 步骤执行
# ──────────────────────────────────────────────────────────────────────────────

def run_hot_papers(date_str: str, dry_run: bool) -> None:
    """
    Fetcher 完成后，运行 hot_papers.py 生成 7d / 30d 热门论文 JSON。
    Ranker 依赖这些文件获取真实热度（hf_upvotes / pwc_stars / score），
    若文件缺失则回退到 raw.json（所有 score=0，周/月热门无意义）。
    本步骤非关键：失败仅记录 WARNING，不终止流水线。
    """
    hot_papers_script = SKILLS_DIR / "Fetcher" / "scripts" / "hot_papers.py"
    if not hot_papers_script.exists():
        logger.warning("hot_papers.py 不存在，跳过热度数据生成")
        return

    for days in [7, 30]:
        cmd = [PYTHON, str(hot_papers_script), "--days", str(days), "--skip-citations"]
        logger.info("  🌡️  生成 %dd 热门论文 JSON...", days)
        try:
            result = subprocess.run(
                cmd, cwd=str(PROJECT_ROOT),
                capture_output=False, timeout=300,
            )
            if result.returncode != 0:
                logger.warning("  hot_papers.py --days %d 执行失败（非关键，继续）", days)
        except Exception as exc:
            logger.warning("  hot_papers.py --days %d 异常：%s（非关键，继续）", days, exc)


def run_step(step: dict, date_str: str, dry_run: bool, skip_email: bool) -> bool:
    """
    执行单个流水线步骤。
    返回 True 表示成功，False 表示失败。
    """
    name   = step["name"]
    label  = step["label"]
    emoji  = step["emoji"]
    script = step["script"]

    logger.info("%s %s", emoji, label)

    if not script.exists():
        logger.error("脚本不存在：%s", script)
        return False

    args = build_step_args(name, date_str, dry_run, skip_email)
    cmd = [PYTHON, str(script)] + args

    logger.info("  命令：%s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            capture_output=False,  # 直接输出到终端
            timeout=1800,          # 30 分钟超时（summarizer 可能较慢）
        )
        if result.returncode == 0:
            logger.info("  %s 完成 ✅", name)
            return True
        else:
            logger.error("  %s 失败 ❌ (exit code: %d)", name, result.returncode)
            return False
    except subprocess.TimeoutExpired:
        logger.error("  %s 超时 ⏰ (>30min)", name)
        return False
    except Exception as e:
        logger.error("  %s 异常：%s", name, e)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily-Paper-Push — 论文推送流水线")
    parser.add_argument("--date", type=str, default=None,
                        help="目标日期 YYYY-MM-DD（默认：昨天 UTC+8）")
    parser.add_argument("--dry-run", action="store_true",
                        help="调试模式：Summarizer 不调 API，Notifier 不发邮件")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="跳过 Fetcher（使用已有 raw.json）")
    parser.add_argument("--skip-summarize", action="store_true",
                        help="跳过 Summarizer（使用已有 summarized.json）")
    parser.add_argument("--skip-email", action="store_true",
                        help="跳过邮件发送（Notifier 仅生成本地文件）")
    parser.add_argument("--start-from", type=str, default=None,
                        choices=["fetcher", "ranker", "summarizer", "storage", "notifier"],
                        help="从指定步骤开始执行（前置步骤的输出文件需已存在）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start_time = time.time()

    # 确定日期
    if args.date:
        date_str = args.date
    else:
        yesterday = datetime.now(TZ_CST) - timedelta(days=1)
        # 跳过周末：周一(0)取上周五，周日(6)同样回退到周五
        if yesterday.weekday() == 0:    # 昨天是周一 → 今天是周二，正常取周一
            pass
        elif yesterday.weekday() == 5:  # 昨天是周六 → 今天是周日，回退到周五
            yesterday -= timedelta(days=1)
        elif yesterday.weekday() == 6:  # 昨天是周日 → 今天是周一，回退到周五
            yesterday -= timedelta(days=2)
        date_str = yesterday.strftime("%Y-%m-%d")

    sep = "=" * 60
    logger.info(sep)
    logger.info("🚀 Daily-Paper-Push 流水线启动")
    logger.info("   日期：%s", date_str)
    logger.info("   模式：%s", "DRY RUN" if args.dry_run else "正式运行")
    logger.info(sep)

    # 构建跳过集合
    skip_set: set[str] = set()
    if args.skip_fetch:
        skip_set.add("fetcher")
    if args.skip_summarize:
        skip_set.add("summarizer")

    # 确定起始步骤
    start_reached = args.start_from is None

    results: dict[str, str] = {}  # name -> "成功" / "失败" / "跳过"

    for step in STEPS:
        name = step["name"]

        # --start-from 逻辑
        if not start_reached:
            if name == args.start_from:
                start_reached = True
            else:
                results[name] = "跳过"
                logger.info("⏭️  跳过 %s（--start-from %s）", name, args.start_from)
                continue

        # --skip-* 逻辑
        if name in skip_set:
            results[name] = "跳过"
            logger.info("⏭️  跳过 %s（用户指定）", name)
            continue

        # 执行步骤
        success = run_step(step, date_str, args.dry_run, args.skip_email)
        results[name] = "成功" if success else "失败"

        # Fetcher 成功后生成热门论文 JSON（供 Ranker 获取真实热度）
        if name == "fetcher" and success:
            run_hot_papers(date_str, args.dry_run)

        # 关键步骤失败 → 终止
        if not success and step["critical"]:
            logger.error("❌ 关键步骤 %s 失败，终止流水线", name)
            break

    # 打印统计
    elapsed = time.time() - start_time
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    print(f"\n{sep}")
    print(f"🏁 Daily-Paper-Push 流水线结束 — {date_str}")
    print(sep)
    for step in STEPS:
        name = step["name"]
        emoji = step["emoji"]
        status = results.get(name, "未执行")
        icon = {"成功": "✅", "失败": "❌", "跳过": "⏭️"}.get(status, "⬜")
        print(f"  {emoji} {name:12s} {icon} {status}")
    print(f"\n  ⏱️  耗时：{minutes}m {seconds}s")
    print(sep + "\n")

    # 如果有失败的关键步骤，以非零退出码结束
    if any(results.get(s["name"]) == "失败" and s["critical"] for s in STEPS):
        sys.exit(1)


if __name__ == "__main__":
    main()
