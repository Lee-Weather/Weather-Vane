"""
test_save.py — Storage 模块单元测试

运行方式：
    python -m pytest .claude/skills/Storage/tests/ -v
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

# 将 scripts 目录加入 path
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import save as S

# ──────────────────────────────────────────────────────────────────────────────
# 测试数据
# ──────────────────────────────────────────────────────────────────────────────

DUMMY_JSON_CONTENT = {
    "date": "2026-04-30",
    "daily_robot": [
        {
            "id": "arxiv:2501.00001",
            "title": "Robot Test Paper",
            "authors": ["A", "B"],
            "abstract": "Abstract R",
            "summary_zh": "机器人摘要",
            "url": "http://test1",
            "hf_upvotes": 10,
            "categories": ["cs.RO"],
            "score": 10.0
        }
    ],
    "daily_ai": [],
    "weekly_hot": {
        "id": "arxiv:2501.00002",
        "title": "Weekly AI Paper",
        "authors": ["C"],
        "abstract": "Abstract W",
        "summary_zh": "周热门短摘要",
        "detail_zh": "周热门详细",
        "url": "http://test2",
        "hf_upvotes": 50,
        "categories": ["cs.AI"],
        "score": 50.0
    },
    "monthly_hot": None
}


# ──────────────────────────────────────────────────────────────────────────────
# 测试类
# ──────────────────────────────────────────────────────────────────────────────

class TestStorage:
    @pytest.fixture
    def db_path(self, tmp_path):
        """提供临时数据库文件路径"""
        return tmp_path / "test_papers.db"

    @pytest.fixture
    def json_path(self, tmp_path):
        """提供临时 JSON 数据文件"""
        jp = tmp_path / "dummy.json"
        jp.write_text(json.dumps(DUMMY_JSON_CONTENT), encoding="utf-8")
        return jp

    def test_init_db(self, db_path):
        """测试数据库初始化，建表是否成功"""
        S.init_db(db_path)
        assert db_path.exists()
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='papers'")
        assert cursor.fetchone() is not None
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='push_history'")
        assert cursor.fetchone() is not None
        
        conn.close()

    def test_save_summarized_data(self, json_path, db_path):
        """测试解析 JSON 并完整入库"""
        S.save_summarized_data(json_path, db_path)
        
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # 检查 papers 表
        cursor.execute("SELECT id, title, summary_zh, detail_zh FROM papers ORDER BY id")
        rows = cursor.fetchall()
        assert len(rows) == 2
        
        assert rows[0][0] == "arxiv:2501.00001"
        assert rows[0][2] == "机器人摘要"
        assert rows[0][3] is None  # daily_robot 无详细介绍
        
        assert rows[1][0] == "arxiv:2501.00002"
        assert rows[1][2] == "周热门短摘要"
        assert rows[1][3] == "周热门详细"

        # 检查 push_history 表
        cursor.execute("SELECT paper_id, push_type FROM push_history ORDER BY paper_id")
        history = cursor.fetchall()
        assert len(history) == 2
        assert ("arxiv:2501.00001", "daily_robot") in history
        assert ("arxiv:2501.00002", "weekly_hot") in history

        conn.close()

    def test_idempotent_save(self, json_path, db_path):
        """测试重复调用保存是幂等的（由于 INSERT OR REPLACE/IGNORE）"""
        # 第一次保存
        S.save_summarized_data(json_path, db_path)
        # 第二次保存
        S.save_summarized_data(json_path, db_path)

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        
        # 应该仍然只有2篇记录，不报错
        cursor.execute("SELECT count(*) FROM papers")
        assert cursor.fetchone()[0] == 2
        
        cursor.execute("SELECT count(*) FROM push_history")
        assert cursor.fetchone()[0] == 2

        conn.close()

    def test_check_pushed(self, db_path):
        """测试推送查询接口"""
        S.init_db(db_path)
        
        assert S.check_pushed(db_path, "arxiv:9999", "weekly_hot") is False
        
        # 手动标记一条
        S.mark_pushed(db_path, "arxiv:9999", "weekly_hot", "2026-04-30")
        
        assert S.check_pushed(db_path, "arxiv:9999", "weekly_hot") is True
        # 不同类型不受影响
        assert S.check_pushed(db_path, "arxiv:9999", "monthly_hot") is False
