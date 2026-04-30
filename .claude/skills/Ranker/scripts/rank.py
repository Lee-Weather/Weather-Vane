#!/usr/bin/env python3
"""
Ranker Skill 排名脚本 — AI 论文每日推送系统

从 fetcher 输出的 raw.json 中，按主题分组（机器人/AI）、热度评分、排名筛选，
选取周/月热门各 1 篇（查推送历史去重），输出四板块结构 ranked.json。

用法：
    python3 rank.py --date 2026-04-30       # 指定日期（默认昨天 UTC+8）
    python3 rank.py --robot-top 15          # 机器人组 Top-N（默认 15）
    python3 rank.py --ai-top 5              # AI 组 Top-N（默认 5）
    python3 rank.py --skip-weekly           # 跳过周热门选取
    python3 rank.py --skip-monthly          # 跳过月热门选取
    python3 rank.py --db-path data/papers.db

输出：
    data/YYYY-MM-DD-ranked.json
"""

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# 常量与配置
# ──────────────────────────────────────────────────────────────────────────────

# 项目根目录（rank.py 位于 <project>/.claude/skills/Ranker/scripts/rank.py）
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"

# 时区 UTC+8
TZ_CST = timezone(timedelta(hours=8))

# 评分权重
W_HF_UPVOTES = 2.0
W_PWC_STARS = 0.05
W_CITATION = 0.5

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
# 1. 数据加载
# ──────────────────────────────────────────────────────────────────────────────

def load_raw(date: str) -> list[dict]:
    """读取 data/YYYY-MM-DD-raw.json，返回论文列表。"""
    raw_path = DATA_DIR / f"{date}-raw.json"
    if not raw_path.exists():
        logger.error("原始数据文件不存在：%s，请先运行 fetcher", raw_path)
        sys.exit(1)

    with open(raw_path, "r", encoding="utf-8") as f:
        papers = json.load(f)

    logger.info("加载 %d 篇论文：%s", len(papers), raw_path)
    return papers


def load_multi_day_raw(end_date: str, days: int) -> list[dict]:
    """
    加载过去 N 天的 raw.json 并合并去重（以 id 为主键）。
    用于周/月热门计算。
    """
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    seen_ids: set[str] = set()
    all_papers: list[dict] = []

    for i in range(days):
        day_str = (end_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        raw_path = DATA_DIR / f"{day_str}-raw.json"
        if not raw_path.exists():
            continue
        try:
            with open(raw_path, "r", encoding="utf-8") as f:
                papers = json.load(f)
            for p in papers:
                pid = p.get("id", "")
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    all_papers.append(p)
        except Exception as exc:
            logger.warning("读取 %s 失败：%s，跳过", raw_path, exc)

    logger.info("加载过去 %d 天数据，合并去重后共 %d 篇", days, len(all_papers))
    return all_papers


# ──────────────────────────────────────────────────────────────────────────────
# 2. 硬过滤
# ──────────────────────────────────────────────────────────────────────────────

def hard_filter(papers: list[dict]) -> list[dict]:
    """
    硬过滤：去除三项热度信号（hf_upvotes / pwc_stars / citation_count）均为 0 的论文。
    满足以下任一条件即保留：
    - hf_upvotes >= 5
    - pwc_stars >= 10
    - citation_count >= 3
    三项全为 0 则丢弃。
    """
    filtered = []
    for p in papers:
        hf = p.get("hf_upvotes", 0) or 0
        pwc = p.get("pwc_stars", 0) or 0
        cite = p.get("citation_count", 0) or 0
        # 三项全为 0 则丢弃
        if hf == 0 and pwc == 0 and cite == 0:
            continue
        filtered.append(p)
    return filtered


# ──────────────────────────────────────────────────────────────────────────────
# 3. 评分
# ──────────────────────────────────────────────────────────────────────────────

def compute_score(paper: dict) -> float:
    """计算论文热度评分。"""
    hf = (paper.get("hf_upvotes", 0) or 0)
    pwc = (paper.get("pwc_stars", 0) or 0)
    cite = (paper.get("citation_count", 0) or 0)
    return hf * W_HF_UPVOTES + pwc * W_PWC_STARS + cite * W_CITATION


# ──────────────────────────────────────────────────────────────────────────────
# 4. 主题分组
# ──────────────────────────────────────────────────────────────────────────────

def classify_group(paper: dict) -> str:
    """
    按 categories 字段将论文分组：
    - 包含 cs.RO → "robot"（优先）
    - 包含 cs.AI 且不含 cs.RO → "ai"
    - 其余 → "other"（不参与每日筛选）
    """
    cats = set(paper.get("categories", []))
    if "cs.RO" in cats:
        return "robot"
    if "cs.AI" in cats:
        return "ai"
    return "other"


# ──────────────────────────────────────────────────────────────────────────────
# 5. 每日筛选
# ──────────────────────────────────────────────────────────────────────────────

def select_daily(papers: list[dict], robot_top: int = 15, ai_top: int = 5) -> dict:
    """
    将论文分组并各组内按 score 降序截取 Top-N。
    返回 {"daily_robot": [...], "daily_ai": [...], "stats": {...}}。
    """
    # 计算 score
    for p in papers:
        p["score"] = compute_score(p)

    # 分组
    robot_group: list[dict] = []
    ai_group: list[dict] = []
    for p in papers:
        group = classify_group(p)
        p["group"] = group
        if group == "robot":
            robot_group.append(p)
        elif group == "ai":
            ai_group.append(p)

    # 排序截取
    robot_group.sort(key=lambda x: x["score"], reverse=True)
    ai_group.sort(key=lambda x: x["score"], reverse=True)

    selected_robot = robot_group[:robot_top]
    selected_ai = ai_group[:ai_top]

    # 添加排名
    for rank, p in enumerate(selected_robot, start=1):
        p["rank"] = rank
    for rank, p in enumerate(selected_ai, start=1):
        p["rank"] = rank

    if len(selected_robot) < robot_top:
        logger.warning(
            "机器人组不足 %d 篇，实际 %d 篇（候选 %d 篇）",
            robot_top, len(selected_robot), len(robot_group),
        )
    if len(selected_ai) < ai_top:
        logger.warning(
            "AI 组不足 %d 篇，实际 %d 篇（候选 %d 篇）",
            ai_top, len(selected_ai), len(ai_group),
        )

    stats = {
        "robot_candidates": len(robot_group),
        "ai_candidates": len(ai_group),
        "robot_selected": len(selected_robot),
        "ai_selected": len(selected_ai),
    }

    return {
        "daily_robot": selected_robot,
        "daily_ai": selected_ai,
        "stats": stats,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 6. 推送历史查询
# ──────────────────────────────────────────────────────────────────────────────

def get_pushed_ids(db_path: Path, push_type: str) -> set[str]:
    """
    查询已作为某类型（weekly_hot / monthly_hot）推送过的论文 ID。
    若数据库不存在或表不存在，返回空集合。
    """
    if not db_path.exists():
        logger.info("数据库 %s 不存在（首次运行），跳过推送历史去重", db_path)
        return set()

    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        # 检查表是否存在
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='push_history'"
        )
        if cursor.fetchone() is None:
            conn.close()
            logger.info("push_history 表不存在（首次运行），跳过推送历史去重")
            return set()

        cursor.execute(
            "SELECT paper_id FROM push_history WHERE push_type = ?",
            (push_type,),
        )
        ids = {row[0] for row in cursor.fetchall()}
        conn.close()
        logger.info("已推送 %s 记录 %d 条", push_type, len(ids))
        return ids
    except Exception as exc:
        logger.warning("查询推送历史失败：%s，跳过去重", exc)
        return set()


# ──────────────────────────────────────────────────────────────────────────────
# 7. 周/月热门选取
# ──────────────────────────────────────────────────────────────────────────────

def load_hot_papers_json(date: str, days: int) -> list[dict]:
    """
    从 hot_papers.py 生成的 JSON 文件读取热门论文数据。
    文件路径：reports/hot-papers-YYYY-MM-DD-{days}d.json
    包含真实的 hf_upvotes、pwc_stars、citation_count 和预计算的 score。
    """
    json_path = REPORTS_DIR / f"hot-papers-{date}-{days}d.json"
    if not json_path.exists():
        logger.info("hot-papers JSON 不存在：%s", json_path)
        return []
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            papers = json.load(f)
        logger.info("从 hot-papers JSON 加载 %d 篇（含真实热度）：%s", len(papers), json_path)
        return papers
    except Exception as exc:
        logger.warning("读取 hot-papers JSON 失败：%s", exc)
        return []


def select_hot(
    end_date: str,
    days: int,
    hot_type: str,
    db_path: Path,
    exclude_ids: set[str] | None = None,
) -> dict | None:
    """
    从过去 N 天数据中选取 score 最高的 1 篇（排除已推送和指定 ID）。
    优先从 hot_papers.py 生成的 JSON 读取（含真实热度数据），
    回退到多日 raw.json 合并。
    返回论文 dict（含 score、hot_type）或 None。
    """
    # 优先从 hot-papers JSON 读取（今天日期生成的）
    today_str = datetime.now(TZ_CST).strftime("%Y-%m-%d")
    papers = load_hot_papers_json(today_str, days)

    # 回退：从多日 raw.json 合并
    if not papers:
        logger.info("hot-papers JSON 不可用，回退到多日 raw.json")
        papers = load_multi_day_raw(end_date, days)

    if not papers:
        logger.warning("过去 %d 天无数据，无法选取 %s", days, hot_type)
        return None

    # 确保 score 字段存在
    for p in papers:
        if "score" not in p:
            p["score"] = compute_score(p)

    # 按 score 降序
    papers.sort(key=lambda x: x["score"], reverse=True)

    # 获取已推送 ID
    pushed_ids = get_pushed_ids(db_path, hot_type)

    # 合并排除集合
    all_exclude = pushed_ids.copy()
    if exclude_ids:
        all_exclude |= exclude_ids

    # 选取未推送的 score 最高论文
    for p in papers:
        pid = p.get("id", "")
        if pid not in all_exclude:
            p["hot_type"] = hot_type
            logger.info(
                "%s 选中：%s (score=%.1f)",
                hot_type, p.get("title", "")[:50], p["score"],
            )
            return p

    logger.warning("过去 %d 天全部论文已推送，%s 为空", days, hot_type)
    return None


def resolve_collision(
    weekly: dict | None,
    monthly: dict | None,
    end_date: str,
    db_path: Path,
) -> dict | None:
    """
    若周热门与月热门为同一篇论文，月热门顺延至第 2 名。
    返回更新后的月热门。
    """
    if weekly is None or monthly is None:
        return monthly
    if weekly.get("id") != monthly.get("id"):
        return monthly

    logger.info("周热门与月热门撞号 (%s)，月热门顺延", weekly.get("id"))
    # 重新选取月热门，排除周热门的 ID
    return select_hot(
        end_date, 30, "monthly_hot", db_path,
        exclude_ids={weekly["id"]},
    )


# ──────────────────────────────────────────────────────────────────────────────
# 8. 输出
# ──────────────────────────────────────────────────────────────────────────────

def write_ranked(result: dict, date: str) -> str:
    """将四板块结构写入 data/YYYY-MM-DD-ranked.json，返回文件路径。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DATA_DIR / f"{date}-ranked.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    logger.info("输出文件：%s", out_path)
    return str(out_path)


def print_summary(
    date: str,
    total: int,
    filtered: int,
    stats: dict,
    weekly: dict | None,
    monthly: dict | None,
    out_path: str,
    degraded: bool = False,
) -> None:
    """打印摘要统计到控制台。"""
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"✅ Ranker 完成 — {date}")
    print(sep)
    print(f"📥 原始论文：{total} 篇")
    if degraded:
        print(f"⚠️  硬过滤后：0 篇 → 降级保留全部 {total} 篇（score=0）")
    else:
        print(f"🔍 硬过滤后：{filtered} 篇（丢弃 {total - filtered} 篇无热度信号）")
    print(f"📊 每日筛选：")
    print(f"   ├── 🤖 机器人组： {stats['robot_selected']} 篇（候选 {stats['robot_candidates']} 篇）")
    print(f"   └── 🧠 AI 组：      {stats['ai_selected']} 篇（候选 {stats['ai_candidates']} 篇）")

    if weekly:
        title_short = weekly["title"][:40] + "…" if len(weekly["title"]) > 40 else weekly["title"]
        print(f"🔥 周热门：《{title_short}》(score={weekly['score']:.1f})")
    else:
        print("🔥 周热门：无候选")

    if monthly:
        title_short = monthly["title"][:40] + "…" if len(monthly["title"]) > 40 else monthly["title"]
        print(f"🏆 月热门：《{title_short}》(score={monthly['score']:.1f})")
    else:
        print("🏆 月热门：无候选")

    print(f"📄 输出路径：{out_path}")
    print(sep)


# ──────────────────────────────────────────────────────────────────────────────
# 9. 主函数
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Ranker — 论文过滤与排名")
    parser.add_argument(
        "--date",
        default=(datetime.now(TZ_CST) - timedelta(days=1)).strftime("%Y-%m-%d"),
        help="目标日期 YYYY-MM-DD（默认昨天 UTC+8）",
    )
    parser.add_argument("--robot-top", type=int, default=15, help="机器人组 Top-N（默认 15）")
    parser.add_argument("--ai-top", type=int, default=5, help="AI 组 Top-N（默认 5）")
    parser.add_argument("--skip-weekly", action="store_true", help="跳过周热门选取")
    parser.add_argument("--skip-monthly", action="store_true", help="跳过月热门选取")
    parser.add_argument("--db-path", default=str(DATA_DIR / "papers.db"), help="SQLite 数据库路径")
    args = parser.parse_args()

    db_path = Path(args.db_path)

    logger.info("=" * 60)
    logger.info("📊 Ranker 启动 — 日期：%s", args.date)
    logger.info("=" * 60)

    # Step 1: 加载当日数据
    raw_papers = load_raw(args.date)
    total = len(raw_papers)

    if total == 0:
        logger.warning("原始数据为空，输出空 ranked.json")
        result = {
            "date": args.date,
            "daily_robot": [],
            "daily_ai": [],
            "weekly_hot": None,
            "monthly_hot": None,
        }
        out_path = write_ranked(result, args.date)
        print_summary(args.date, 0, 0, {
            "robot_candidates": 0, "ai_candidates": 0,
            "robot_selected": 0, "ai_selected": 0,
        }, None, None, out_path)
        return

    # Step 2: 硬过滤（降级：若全部被过滤则保留全部，按 score=0 参与排序）
    filtered_papers = hard_filter(raw_papers)
    filtered_count = len(filtered_papers)
    degraded = False
    logger.info("硬过滤：%d → %d 篇", total, filtered_count)

    if filtered_count == 0:
        logger.warning("硬过滤后无论文，降级：保留全部 %d 篇（score 均为 0）", total)
        filtered_papers = raw_papers
        filtered_count = total
        degraded = True

    # Step 3-5: 每日筛选（评分 + 分组 + 截取）
    daily_result = select_daily(filtered_papers, args.robot_top, args.ai_top)

    # Step 6: 周热门
    weekly_hot = None
    if not args.skip_weekly:
        weekly_hot = select_hot(args.date, 7, "weekly_hot", db_path)

    # Step 7: 月热门
    monthly_hot = None
    if not args.skip_monthly:
        monthly_hot = select_hot(args.date, 30, "monthly_hot", db_path)

    # Step 8: 撞号处理
    monthly_hot = resolve_collision(weekly_hot, monthly_hot, args.date, db_path)

    # Step 9: 输出
    result = {
        "date": args.date,
        "daily_robot": daily_result["daily_robot"],
        "daily_ai": daily_result["daily_ai"],
        "weekly_hot": weekly_hot,
        "monthly_hot": monthly_hot,
    }
    out_path = write_ranked(result, args.date)

    # Step 10: 摘要
    print_summary(
        args.date, total, filtered_count,
        daily_result["stats"],
        weekly_hot, monthly_hot, out_path,
        degraded=degraded,
    )


if __name__ == "__main__":
    main()
