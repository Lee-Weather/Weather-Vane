"""
test_notify.py — Notifier 模块单元测试

测试配置加载、模板渲染、HTML 转换和 dry-run 模式，不实际发送邮件。

运行方式：
    python -m pytest .claude/skills/Notifier/tests/ -v
"""

import json
import shutil
import sys
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# 将 scripts 目录加入 path
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import notify as N

# 在项目根目录下创建临时目录，避免 Windows tmp_path 权限问题
_TEST_TMP_ROOT = Path(__file__).resolve().parents[5] / ".test_tmp_notifier"


@pytest.fixture
def work_dir():
    """提供项目内的临时工作目录"""
    d = _TEST_TMP_ROOT / str(uuid.uuid4())[:8]
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)
    # 尝试清理根目录（如果为空）
    try:
        _TEST_TMP_ROOT.rmdir()
    except OSError:
        pass

# ──────────────────────────────────────────────────────────────────────────────
# 测试数据
# ──────────────────────────────────────────────────────────────────────────────

SAMPLE_DATA = {
    "date": "2026-04-30",
    "daily_robot": [
        {
            "id": "arxiv:2501.00001",
            "title": "Robot Gait Planning",
            "authors": ["Author A"],
            "abstract": "Abstract...",
            "summary_zh": "机器人步态规划摘要",
            "url": "https://arxiv.org/abs/2501.00001",
            "pdf_url": "https://arxiv.org/pdf/2501.00001",
            "code_url": "https://github.com/test/repo",
            "hf_upvotes": 10,
            "pwc_stars": 50,
            "citation_count": 2,
            "score": 22.5,
        }
    ],
    "daily_ai": [
        {
            "id": "arxiv:2501.00002",
            "title": "LLM Survey",
            "authors": ["Author B", "Author C"],
            "abstract": "Abstract...",
            "summary_zh": "大语言模型综述",
            "url": "https://arxiv.org/abs/2501.00002",
            "pdf_url": "https://arxiv.org/pdf/2501.00002",
            "code_url": None,
            "hf_upvotes": 100,
            "score": 200.0,
        }
    ],
    "weekly_hot": {
        "id": "arxiv:2501.00003",
        "title": "Weekly Hot Paper",
        "authors": ["Author D"],
        "summary_zh": "周热门短摘要",
        "detail_zh": "周热门详细介绍内容...",
        "url": "https://arxiv.org/abs/2501.00003",
        "pdf_url": "https://arxiv.org/pdf/2501.00003",
        "code_url": None,
        "hf_upvotes": 200,
        "pwc_stars": 500,
        "citation_count": 15,
    },
    "monthly_hot": None,
}


# ──────────────────────────────────────────────────────────────────────────────
# 配置加载测试
# ──────────────────────────────────────────────────────────────────────────────

class TestLoadConfig:
    def test_missing_config_returns_default(self, work_dir):
        """config.yaml 不存在时应返回默认配置"""
        conf = N.load_config(str(work_dir / "nonexistent.yaml"))
        assert conf["email"]["enabled"] is False
        assert conf["local"]["enabled"] is True

    def test_valid_config(self, work_dir):
        """正常 config.yaml 应正确解析"""
        cfg_file = work_dir / "config.yaml"
        cfg_file.write_text("""
email:
  enabled: true
  sender: "test@gmail.com"
  recipients:
    - "user@example.com"
local:
  enabled: true
  output_dir: "my_reports"
""", encoding="utf-8")
        conf = N.load_config(str(cfg_file))
        assert conf["email"]["enabled"] is True
        assert conf["email"]["sender"] == "test@gmail.com"
        assert "user@example.com" in conf["email"]["recipients"]
        assert conf["local"]["output_dir"] == "my_reports"


# ──────────────────────────────────────────────────────────────────────────────
# 模板渲染测试
# ──────────────────────────────────────────────────────────────────────────────

class TestRenderReport:
    @pytest.fixture
    def template_dir(self):
        return Path(__file__).parent.parent / "templates"

    def test_render_basic(self, template_dir):
        """基本渲染应包含日期和论文标题"""
        result = N.render_report(SAMPLE_DATA, template_dir)
        assert "2026-04-30" in result
        assert "Robot Gait Planning" in result
        assert "LLM Survey" in result
        assert "Weekly Hot Paper" in result

    def test_render_contains_summary(self, template_dir):
        """渲染结果应包含中文摘要"""
        result = N.render_report(SAMPLE_DATA, template_dir)
        assert "机器人步态规划摘要" in result
        assert "大语言模型综述" in result
        assert "周热门详细介绍内容" in result

    def test_render_contains_links(self, template_dir):
        """渲染结果应包含论文链接"""
        result = N.render_report(SAMPLE_DATA, template_dir)
        assert "https://arxiv.org/abs/2501.00001" in result
        assert "https://github.com/test/repo" in result

    def test_render_empty_monthly(self, template_dir):
        """月热门为 None 时应显示暂无数据"""
        result = N.render_report(SAMPLE_DATA, template_dir)
        # monthly_hot 为 None，应渲染"暂无数据"
        assert "暂无数据" in result

    def test_render_all_empty(self, template_dir):
        """所有板块为空时不应报错"""
        empty_data = {
            "date": "2026-04-30",
            "daily_robot": [],
            "daily_ai": [],
            "weekly_hot": None,
            "monthly_hot": None,
        }
        result = N.render_report(empty_data, template_dir)
        assert "2026-04-30" in result
        assert "共推送 0 篇" in result

    def test_render_stats(self, template_dir):
        """统计行应正确显示篇数"""
        result = N.render_report(SAMPLE_DATA, template_dir)
        assert "机器人 1 篇" in result
        assert "AI 1 篇" in result
        assert "周热门 1 篇" in result
        assert "月热门 0 篇" in result


# ──────────────────────────────────────────────────────────────────────────────
# Markdown → HTML 转换测试
# ──────────────────────────────────────────────────────────────────────────────

class TestMarkdownToHtml:
    def test_basic_conversion(self):
        """基本 Markdown 应转换为 HTML"""
        html = N.markdown_to_html("# Hello\n\nWorld")
        assert "<h1>" in html or "<h1" in html
        assert "World" in html

    def test_contains_style(self):
        """HTML 应包含内联样式"""
        html = N.markdown_to_html("test")
        assert "<style>" in html
        assert "font-family" in html

    def test_link_preserved(self):
        """链接应正确转换"""
        html = N.markdown_to_html("[test](https://example.com)")
        assert "https://example.com" in html


# ──────────────────────────────────────────────────────────────────────────────
# 本地归档测试
# ──────────────────────────────────────────────────────────────────────────────

class TestSaveLocal:
    def test_save_creates_file(self, work_dir):
        """保存应创建 Markdown 文件"""
        original = N.PROJECT_ROOT
        N.PROJECT_ROOT = work_dir
        try:
            path = N.save_local("# Test Report", "2026-04-30", "reports")
            assert path.exists()
            assert path.read_text(encoding="utf-8") == "# Test Report"
            assert path.name == "2026-04-30.md"
        finally:
            N.PROJECT_ROOT = original

    def test_save_creates_directory(self, work_dir):
        """输出目录不存在时应自动创建"""
        original = N.PROJECT_ROOT
        N.PROJECT_ROOT = work_dir
        try:
            path = N.save_local("content", "2026-04-30", "nested/dir")
            assert path.exists()
        finally:
            N.PROJECT_ROOT = original


# ──────────────────────────────────────────────────────────────────────────────
# Gmail 发送测试（Mock）
# ──────────────────────────────────────────────────────────────────────────────

class TestSendGmail:
    def test_no_sender_returns_false(self):
        """未配置发件人应返回 False"""
        config = {"email": {"sender": "", "recipients": ["a@b.com"]}}
        result = N.send_gmail(config, "<html></html>", "text", "subject")
        assert result is False

    def test_no_recipients_returns_false(self):
        """收件人为空应返回 False"""
        config = {"email": {"sender": "x@gmail.com", "recipients": []}}
        result = N.send_gmail(config, "<html></html>", "text", "subject")
        assert result is False

    @patch.dict("os.environ", {"EMAIL_PASSWORD": ""})
    def test_no_password_returns_false(self):
        """未设置密码应返回 False"""
        config = {"email": {"sender": "x@gmail.com", "recipients": ["a@b.com"]}}
        result = N.send_gmail(config, "<html></html>", "text", "subject")
        assert result is False

    @patch("notify.smtplib.SMTP")
    @patch.dict("os.environ", {"EMAIL_PASSWORD": "fake-password"})
    def test_successful_send(self, mock_smtp_cls):
        """模拟成功发送"""
        mock_server = MagicMock()
        mock_smtp_cls.return_value = mock_server

        config = {
            "email": {
                "sender": "test@gmail.com",
                "sender_name": "Test",
                "recipients": ["user@example.com"],
                "smtp_host": "smtp.gmail.com",
                "smtp_port": 587,
                "use_tls": True,
            }
        }
        result = N.send_gmail(config, "<html>body</html>", "plain text", "Test Subject")
        assert result is True
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once()
        mock_server.sendmail.assert_called_once()
        mock_server.quit.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# 数据加载测试
# ──────────────────────────────────────────────────────────────────────────────

class TestLoadSummarized:
    def test_file_not_found_exits(self, work_dir):
        """文件不存在应退出"""
        original = N.DATA_DIR
        N.DATA_DIR = work_dir
        try:
            with pytest.raises(SystemExit):
                N.load_summarized("9999-99-99")
        finally:
            N.DATA_DIR = original

    def test_valid_json(self, work_dir):
        """正常 JSON 应成功加载"""
        path = work_dir / "2026-04-30-summarized.json"
        path.write_text(json.dumps(SAMPLE_DATA), encoding="utf-8")
        original = N.DATA_DIR
        N.DATA_DIR = work_dir
        try:
            data = N.load_summarized("2026-04-30")
            assert data["date"] == "2026-04-30"
        finally:
            N.DATA_DIR = original
