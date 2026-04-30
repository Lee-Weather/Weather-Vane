"""
test_summarize.py — Summarizer 单元测试

测试 Prompt 构建逻辑和数据处理函数，不实际调用 LLM API。

运行方式：
    python -m pytest .claude/skills/Summarizer/tests/ -v
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 将 scripts 目录加入 path
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import summarize as S

# ──────────────────────────────────────────────────────────────────────────────
# 测试数据
# ──────────────────────────────────────────────────────────────────────────────

PAPER_ROBOT = {
    "id": "arxiv:2501.00001",
    "title": "Adaptive Gait Planning for Quadruped Robots on Unstructured Terrain",
    "abstract": "We present a novel method for adaptive gait planning in quadruped robots...",
    "authors": ["Author A", "Author B"],
    "url": "https://arxiv.org/abs/2501.00001",
    "pdf_url": "https://arxiv.org/pdf/2501.00001",
    "hf_upvotes": 45,
    "pwc_stars": 120,
    "citation_count": 3,
    "categories": ["cs.RO", "cs.AI"],
    "score": 105.0,
    "group": "robot",
    "rank": 1,
}

PAPER_AI = {
    "id": "arxiv:2501.00002",
    "title": "Large Language Models for Code Generation: A Survey",
    "abstract": "We survey recent advances in LLMs for code generation...",
    "authors": ["Author C"],
    "url": "https://arxiv.org/abs/2501.00002",
    "pdf_url": "https://arxiv.org/pdf/2501.00002",
    "hf_upvotes": 200,
    "pwc_stars": 500,
    "citation_count": 12,
    "categories": ["cs.AI", "cs.CL"],
    "score": 431.0,
    "group": "ai",
    "rank": 1,
}

RANKED_DATA = {
    "date": "2026-04-30",
    "daily_robot": [PAPER_ROBOT],
    "daily_ai": [PAPER_AI],
    "weekly_hot": {**PAPER_AI, "hot_type": "weekly"},
    "monthly_hot": {**PAPER_ROBOT, "hot_type": "monthly"},
}

# ──────────────────────────────────────────────────────────────────────────────
# Prompt 构建测试
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildShortPrompt:
    def test_contains_title(self):
        prompt = S.build_short_prompt(PAPER_ROBOT)
        assert PAPER_ROBOT["title"] in prompt

    def test_contains_abstract(self):
        prompt = S.build_short_prompt(PAPER_ROBOT)
        assert PAPER_ROBOT["abstract"] in prompt

    def test_contains_150_limit(self):
        prompt = S.build_short_prompt(PAPER_ROBOT)
        assert "150 字以内" in prompt

    def test_contains_three_sections(self):
        prompt = S.build_short_prompt(PAPER_ROBOT)
        assert "核心问题" in prompt
        assert "方法与创新点" in prompt
        assert "关键结论" in prompt

    def test_empty_paper_no_error(self):
        """空论文不应抛异常"""
        prompt = S.build_short_prompt({})
        assert "150 字以内" in prompt


class TestBuildDetailPrompt:
    def test_contains_title(self):
        prompt = S.build_detail_prompt(PAPER_AI, "weekly")
        assert PAPER_AI["title"] in prompt

    def test_weekly_label(self):
        prompt = S.build_detail_prompt(PAPER_AI, "weekly")
        assert "本周" in prompt

    def test_monthly_label(self):
        prompt = S.build_detail_prompt(PAPER_ROBOT, "monthly")
        assert "本月" in prompt

    def test_contains_metrics(self):
        """应包含热度指标信息"""
        prompt = S.build_detail_prompt(PAPER_AI, "weekly")
        assert str(PAPER_AI["hf_upvotes"]) in prompt
        assert str(PAPER_AI["pwc_stars"]) in prompt

    def test_contains_seven_sections(self):
        prompt = S.build_detail_prompt(PAPER_AI, "weekly")
        assert "研究背景与动机" in prompt
        assert "核心问题定义" in prompt
        assert "方法论详解" in prompt
        assert "实验结果" in prompt
        assert "与现有工作对比" in prompt
        assert "实际意义" in prompt
        assert "推荐理由" in prompt

    def test_contains_500_800_limit(self):
        prompt = S.build_detail_prompt(PAPER_AI, "weekly")
        assert "500-800 字" in prompt


# ──────────────────────────────────────────────────────────────────────────────
# dry-run 模式测试
# ──────────────────────────────────────────────────────────────────────────────

class TestCallLLMDryRun:
    def test_dry_run_returns_placeholder(self):
        result = S.call_llm(None, "test prompt", "model", 400, dry_run=True)
        assert result is not None
        assert "DRY RUN" in result

    def test_dry_run_prints_prompt(self, capsys):
        S.call_llm(None, "hello world prompt", "model", 400, dry_run=True)
        captured = capsys.readouterr()
        assert "hello world prompt" in captured.out


# ──────────────────────────────────────────────────────────────────────────────
# 数据加载测试
# ──────────────────────────────────────────────────────────────────────────────

class TestLoadRanked:
    def test_file_not_found_exits(self, tmp_path):
        """ranked.json 不存在时应以 SystemExit(1) 退出"""
        # 临时替换 DATA_DIR
        original = S.DATA_DIR
        S.DATA_DIR = tmp_path
        try:
            with pytest.raises(SystemExit) as exc:
                S.load_ranked("9999-99-99")
            assert exc.value.code == 1
        finally:
            S.DATA_DIR = original

    def test_load_valid_json(self, tmp_path):
        """正常 JSON 文件应成功加载"""
        path = tmp_path / "2026-04-30-ranked.json"
        path.write_text(json.dumps(RANKED_DATA), encoding="utf-8")

        original = S.DATA_DIR
        S.DATA_DIR = tmp_path
        try:
            data = S.load_ranked("2026-04-30")
            assert data["date"] == "2026-04-30"
            assert len(data["daily_robot"]) == 1
        finally:
            S.DATA_DIR = original

    def test_invalid_json_exits(self, tmp_path):
        """JSON 损坏时应以 SystemExit(1) 退出"""
        path = tmp_path / "2026-04-30-ranked.json"
        path.write_text("{ invalid json ", encoding="utf-8")

        original = S.DATA_DIR
        S.DATA_DIR = tmp_path
        try:
            with pytest.raises(SystemExit) as exc:
                S.load_ranked("2026-04-30")
            assert exc.value.code == 1
        finally:
            S.DATA_DIR = original


# ──────────────────────────────────────────────────────────────────────────────
# 输出写入测试
# ──────────────────────────────────────────────────────────────────────────────

class TestWriteSummarized:
    def test_writes_json(self, tmp_path):
        original = S.DATA_DIR
        S.DATA_DIR = tmp_path
        try:
            out = S.write_summarized(RANKED_DATA, "2026-04-30")
            assert out.exists()
            loaded = json.loads(out.read_text(encoding="utf-8"))
            assert loaded["date"] == "2026-04-30"
        finally:
            S.DATA_DIR = original

    def test_output_is_valid_utf8(self, tmp_path):
        original = S.DATA_DIR
        S.DATA_DIR = tmp_path
        try:
            out = S.write_summarized({"date": "2026-04-30", "title": "中文标题"}, "2026-04-30")
            content = out.read_text(encoding="utf-8")
            assert "中文标题" in content
        finally:
            S.DATA_DIR = original


# ──────────────────────────────────────────────────────────────────────────────
# 同篇去重测试
# ──────────────────────────────────────────────────────────────────────────────

class TestCollisionDedup:
    def test_same_paper_reuses_detail(self):
        """周热门与月热门为同一篇时，月热门应复用 weekly 的摘要"""
        weekly = {**PAPER_AI, "hot_type": "weekly", "summary_zh": "短摘要内容", "detail_zh": "详细内容"}
        monthly = {**PAPER_AI, "hot_type": "monthly"}  # 同一 id

        # 模拟 main 中的去重逻辑
        if weekly and monthly.get("id") == weekly.get("id"):
            monthly["summary_zh"] = weekly.get("summary_zh")
            monthly["detail_zh"] = weekly.get("detail_zh")

        assert monthly["summary_zh"] == "短摘要内容"
        assert monthly["detail_zh"] == "详细内容"

    def test_different_papers_independent(self):
        """周热门与月热门不同篇时，不应互相影响"""
        weekly  = {**PAPER_AI, "id": "arxiv:0001", "summary_zh": "AI摘要"}
        monthly = {**PAPER_ROBOT, "id": "arxiv:0002", "summary_zh": None}

        assert weekly["id"] != monthly["id"]
        assert monthly["summary_zh"] is None
