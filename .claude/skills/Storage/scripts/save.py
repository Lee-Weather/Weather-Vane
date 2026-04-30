#!/usr/bin/env python3
"""
save.py — AI 论文每日推送系统 数据存储模块

功能：
1. `--save <json>`: 读取 summarized.json 入库 (papers 表) 并记录推送 (push_history 表)
2. `--check-pushed <id> --type <type>`: 检查某论文是否已推送
3. `--mark-pushed <id> --type <type> --date <date>`: 手动标记推送历史

使用示例:
    python scripts/save.py --save ../../data/2026-04-30-summarized.json
"""

import argparse
import json
import logging
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# 配置与日志
# ──────────────────────────────────────────────────────────────────────────────

TZ_CST = timezone(timedelta(hours=8))
PROJECT_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB = DATA_DIR / "papers.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# 数据库初始化
# ──────────────────────────────────────────────────────────────────────────────

def init_db(db_path: Path) -> None:
    """初始化数据库与表结构"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # 论文主表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS papers (
            id              TEXT PRIMARY KEY,
            title           TEXT,
            authors         TEXT,
            abstract        TEXT,
            summary_zh      TEXT,
            detail_zh       TEXT,
            url             TEXT,
            pdf_url         TEXT,
            code_url        TEXT,
            hf_upvotes      INTEGER,
            pwc_stars       INTEGER,
            citation_count  INTEGER,
            categories      TEXT,
            score           REAL,
            published_date  TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 推送历史表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS push_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id        TEXT NOT NULL,
            push_date       TEXT NOT NULL,
            push_type       TEXT NOT NULL,
            UNIQUE(paper_id, push_type),
            FOREIGN KEY(paper_id) REFERENCES papers(id)
        )
    """)

    conn.commit()
    conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# 保存逻辑
# ──────────────────────────────────────────────────────────────────────────────

def save_paper(cursor: sqlite3.Cursor, paper: dict) -> None:
    """将单篇论文元数据存入 papers 表"""
    authors = json.dumps(paper.get("authors", []), ensure_ascii=False)
    categories = json.dumps(paper.get("categories", []), ensure_ascii=False)

    cursor.execute("""
        INSERT OR REPLACE INTO papers (
            id, title, authors, abstract, summary_zh, detail_zh,
            url, pdf_url, code_url, hf_upvotes, pwc_stars, citation_count,
            categories, score, published_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        paper.get("id"),
        paper.get("title"),
        authors,
        paper.get("abstract"),
        paper.get("summary_zh"),
        paper.get("detail_zh"),
        paper.get("url"),
        paper.get("pdf_url"),
        paper.get("code_url"),
        paper.get("hf_upvotes", 0) or 0,
        paper.get("pwc_stars", 0) or 0,
        paper.get("citation_count", 0) or 0,
        categories,
        paper.get("score", 0.0),
        paper.get("published_date")
    ))


def record_push_history(cursor: sqlite3.Cursor, paper_id: str, push_date: str, push_type: str) -> None:
    """记录推送历史（同一篇论文同一类型忽略重复插入）"""
    cursor.execute("""
        INSERT OR IGNORE INTO push_history (paper_id, push_date, push_type)
        VALUES (?, ?, ?)
    """, (paper_id, push_date, push_type))


def save_summarized_data(json_path: Path, db_path: Path) -> None:
    """解析 summarized.json 并完整入库"""
    if not json_path.exists():
        logger.error("文件不存在：%s", json_path)
        sys.exit(1)

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error("JSON 解析失败：%s", e)
        sys.exit(1)

    date_str = data.get("date", "")
    if not date_str:
        logger.error("JSON 缺少 date 字段")
        sys.exit(1)

    init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    stats = {"robot": 0, "ai": 0, "weekly": 0, "monthly": 0}

    try:
        # daily_robot
        for p in data.get("daily_robot", []):
            save_paper(cursor, p)
            record_push_history(cursor, p["id"], date_str, "daily_robot")
            stats["robot"] += 1

        # daily_ai
        for p in data.get("daily_ai", []):
            save_paper(cursor, p)
            record_push_history(cursor, p["id"], date_str, "daily_ai")
            stats["ai"] += 1

        # weekly_hot
        weekly = data.get("weekly_hot")
        if weekly:
            save_paper(cursor, weekly)
            record_push_history(cursor, weekly["id"], date_str, "weekly_hot")
            stats["weekly"] += 1

        # monthly_hot
        monthly = data.get("monthly_hot")
        if monthly:
            save_paper(cursor, monthly)
            record_push_history(cursor, monthly["id"], date_str, "monthly_hot")
            stats["monthly"] += 1

        conn.commit()
        logger.info("入库完成 — 🤖 机器人组 %d 篇, 🧠 AI 组 %d 篇, 🔥 周热门 %d 篇, 🏆 月热门 %d 篇",
                    stats["robot"], stats["ai"], stats["weekly"], stats["monthly"])
    except Exception as e:
        conn.rollback()
        logger.error("入库过程出错，已回滚事务：%s", e)
        sys.exit(1)
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# 查询与手动标记逻辑
# ──────────────────────────────────────────────────────────────────────────────

def check_pushed(db_path: Path, paper_id: str, push_type: str) -> bool:
    """检查论文是否已推送过"""
    if not db_path.exists():
        return False
    
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    # 检查表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='push_history'")
    if not cursor.fetchone():
        conn.close()
        return False

    cursor.execute("""
        SELECT 1 FROM push_history 
        WHERE paper_id = ? AND push_type = ?
    """, (paper_id, push_type))
    
    exists = cursor.fetchone() is not None
    conn.close()
    
    status = "已推送" if exists else "未推送"
    logger.info("检查 %s [%s] -> %s", paper_id, push_type, status)
    print("True" if exists else "False")
    return exists


def mark_pushed(db_path: Path, paper_id: str, push_type: str, date_str: str) -> None:
    """手动标记推送记录（由于缺少 papers 记录，外键约束可能会报错，所以建议配合 --save 自动处理）"""
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    try:
        # 为了避免外键约束失败，尝试先插入一个空的 paper
        cursor.execute("INSERT OR IGNORE INTO papers (id) VALUES (?)", (paper_id,))
        record_push_history(cursor, paper_id, date_str, push_type)
        conn.commit()
        logger.info("手动标记成功：%s [%s] @ %s", paper_id, push_type, date_str)
    except Exception as e:
        conn.rollback()
        logger.error("手动标记失败：%s", e)
        sys.exit(1)
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# 命令行入口
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Storage 模块 - 论文数据入库")
    parser.add_argument("--save", type=str, help="要保存的 summarized.json 文件路径")
    parser.add_argument("--check-pushed", type=str, help="检查此论文ID是否已推送")
    parser.add_argument("--mark-pushed", type=str, help="手动标记此论文ID为已推送")
    parser.add_argument("--type", type=str, choices=["daily_robot", "daily_ai", "weekly_hot", "monthly_hot"],
                        help="推送板块类型（用于 check/mark）")
    parser.add_argument("--date", type=str, help="推送日期 YYYY-MM-DD（用于 mark-pushed）")
    parser.add_argument("--db-path", type=str, default=str(DEFAULT_DB), help="SQLite 数据库路径")

    args = parser.parse_args()
    db_path = Path(args.db_path)

    if args.save:
        save_summarized_data(Path(args.save), db_path)
    
    elif args.check_pushed:
        if not args.type:
            logger.error("--check-pushed 必须指定 --type")
            sys.exit(1)
        check_pushed(db_path, args.check_pushed, args.type)
        
    elif args.mark_pushed:
        if not args.type:
            logger.error("--mark-pushed 必须指定 --type")
            sys.exit(1)
        date_str = args.date or datetime.now(TZ_CST).strftime("%Y-%m-%d")
        mark_pushed(db_path, args.mark_pushed, args.type, date_str)
        
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
