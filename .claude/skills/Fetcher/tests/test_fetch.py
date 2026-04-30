"""
Fetcher Skill 单元测试
测试文件：.claude/skills/Fetcher/tests/test_fetch.py

覆盖 §6 中全部 7 个测试用例：
  - test_arxiv_normal      正常抓取，字段完整
  - test_arxiv_holiday     arXiv 空 feed，返回 []
  - test_hf_merge          HF 点赞数正确合并
  - test_pwc_enrich        PWC code_url / pwc_stars 正确写入
  - test_dedup             重复 arxiv_id 只保留一条
  - test_retry             前两次超时，第三次成功
  - test_skip_bad_entry    单条解析失败不影响其他条目

运行：
    conda activate ai_base
    pip install pytest respx pytest-asyncio   # 首次
    pytest                                    # 在项目根目录执行
"""

import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

import httpx
import pytest
import respx

# ── 将 scripts 目录加入 sys.path，使 fetch 可直接导入 ────────────────────────
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import fetch  # noqa: E402  （必须在 sys.path 修改后导入）
from fetch import (
    fetch_arxiv,
    fetch_huggingface,
    fetch_pwc,
    fetch_with_retry,
    merge_papers,
    normalize_arxiv_id,
    ARXIV_API_URL,
    HF_API_URL,
    PWC_API_URL,
)

# ──────────────────────────────────────────────────────────────────────────────
# 测试夹具 & 常量
# ──────────────────────────────────────────────────────────────────────────────

TEST_DATE = "2026-04-30"

# 合法的 arXiv Atom XML（含一条完整条目）
VALID_ARXIV_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2404.07143v1</id>
    <title>Test Paper on LLM Alignment</title>
    <author><name>Author One</name></author>
    <author><name>Author Two</name></author>
    <summary>This is the abstract of the test paper about LLM alignment.</summary>
    <published>2026-04-30T00:00:00Z</published>
    <updated>2026-04-30T00:00:00Z</updated>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.LG" scheme="http://arxiv.org/schemas/atom"/>
    <link href="http://arxiv.org/abs/2404.07143v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="https://arxiv.org/pdf/2404.07143v1" rel="related" type="application/pdf"/>
  </entry>
</feed>"""

# 空 feed（节假日）
EMPTY_ARXIV_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
</feed>"""

# 含一条合法 + 一条日期非法条目的 Atom XML
MIXED_ARXIV_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2404.07143v1</id>
    <title>Good Paper</title>
    <author><name>Author One</name></author>
    <summary>Good abstract.</summary>
    <published>2026-04-30T00:00:00Z</published>
    <updated>2026-04-30T00:00:00Z</updated>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2404.99999v1</id>
    <title>Bad Entry With Invalid Date</title>
    <author><name>Author X</name></author>
    <summary>This entry has a malformed published date.</summary>
    <published>NOT_A_VALID_DATE</published>
    <updated>NOT_A_VALID_DATE</updated>
    <category term="cs.CV" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>"""

# 含两条相同 arxiv_id 的 Atom XML（用于去重测试）
DUPLICATE_ARXIV_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2404.07143v1</id>
    <title>Duplicate Paper First</title>
    <author><name>Author One</name></author>
    <summary>Abstract one.</summary>
    <published>2026-04-30T00:00:00Z</published>
    <updated>2026-04-30T00:00:00Z</updated>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2404.07143v2</id>
    <title>Duplicate Paper Second (same bare ID)</title>
    <author><name>Author One</name></author>
    <summary>Abstract two.</summary>
    <published>2026-04-30T00:00:00Z</published>
    <updated>2026-04-30T00:00:00Z</updated>
    <category term="cs.AI" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>"""

# HuggingFace API 响应 JSON
HF_RESPONSE_JSON = [
    {
        "paper": {"id": "2404.07143", "title": "Test Paper on LLM Alignment"},
        "upvotes": 312,
    }
]

# Papers With Code API 响应 JSON
PWC_RESPONSE_JSON = {
    "results": [
        {
            "arxiv_id": "2404.07143",
            "repositories": [
                {"url": "https://github.com/example/rlvr", "stars": 1847}
            ],
        }
    ]
}


# ──────────────────────────────────────────────────────────────────────────────
# 辅助：为所有测试禁用 asyncio.sleep 以加快速度
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def mock_sleep():
    """将 asyncio.sleep 替换为空操作，避免测试等待重试间隔。"""
    with patch("fetch.asyncio.sleep", new_callable=AsyncMock) as m:
        yield m


# ──────────────────────────────────────────────────────────────────────────────
# 工具函数测试
# ──────────────────────────────────────────────────────────────────────────────

def test_normalize_arxiv_id_with_url():
    """带 URL 前缀和版本号后缀的 ID 应被正确规范化。"""
    assert normalize_arxiv_id("http://arxiv.org/abs/2401.12345v1") == "arxiv:2401.12345"


def test_normalize_arxiv_id_bare():
    """纯版本号 ID 也应被正确规范化。"""
    assert normalize_arxiv_id("2404.07143v2") == "arxiv:2404.07143"


# ──────────────────────────────────────────────────────────────────────────────
# 测试用例 1：test_arxiv_normal
# ──────────────────────────────────────────────────────────────────────────────

@respx.mock
async def test_arxiv_normal():
    """
    正常日期：arXiv 返回合法 Atom XML，
    验证返回列表 ≥1 条且所有必填字段非空。
    """
    respx.get(url__startswith=ARXIV_API_URL).mock(
        return_value=httpx.Response(200, text=VALID_ARXIV_XML)
    )

    async with httpx.AsyncClient() as client:
        papers = await fetch_arxiv(client, TEST_DATE)

    assert len(papers) >= 1, "正常情况下应至少返回 1 篇论文"

    paper = papers[0]
    # 检查所有必填字段
    required_fields = ["id", "title", "authors", "abstract", "url", "pdf_url",
                       "published_date", "categories", "source",
                       "hf_upvotes", "pwc_stars", "code_url", "citation_count"]
    for field in required_fields:
        assert field in paper, f"字段 '{field}' 缺失"

    # 检查关键字段内容
    assert paper["id"] == "arxiv:2404.07143"
    assert paper["title"] == "Test Paper on LLM Alignment"
    assert "Author One" in paper["authors"]
    assert paper["abstract"] != ""
    assert paper["url"].startswith("https://arxiv.org/abs/")
    assert paper["pdf_url"].startswith("https://arxiv.org/pdf/")
    assert paper["published_date"] == TEST_DATE
    assert "cs.AI" in paper["categories"]
    assert paper["source"] == "arxiv"
    # 默认值
    assert paper["hf_upvotes"] == 0
    assert paper["pwc_stars"] == 0
    assert paper["code_url"] is None
    assert paper["citation_count"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# 测试用例 2：test_arxiv_holiday
# ──────────────────────────────────────────────────────────────────────────────

@respx.mock
async def test_arxiv_holiday():
    """
    节假日/周末：arXiv 返回空 feed，
    验证函数返回 [] 且不抛出任何异常。
    """
    respx.get(url__startswith=ARXIV_API_URL).mock(
        return_value=httpx.Response(200, text=EMPTY_ARXIV_XML)
    )

    async with httpx.AsyncClient() as client:
        papers = await fetch_arxiv(client, TEST_DATE)

    assert papers == [], "空 feed 时应返回空列表"


# ──────────────────────────────────────────────────────────────────────────────
# 测试用例 3：test_hf_merge
# ──────────────────────────────────────────────────────────────────────────────

@respx.mock
async def test_hf_merge():
    """
    HuggingFace 数据与 arXiv 正确合并：
    - fetch_huggingface 返回 {arxiv_id: upvotes} 映射
    - merge_papers 将 hf_upvotes 正确填充到对应论文
    """
    respx.get(HF_API_URL).mock(
        return_value=httpx.Response(200, json=HF_RESPONSE_JSON)
    )

    async with httpx.AsyncClient() as client:
        hf_map = await fetch_huggingface(client, TEST_DATE)

    # 验证映射结构
    assert "arxiv:2404.07143" in hf_map
    assert hf_map["arxiv:2404.07143"] == 312

    # 验证 merge_papers 填充
    arxiv_papers = [
        {
            "id": "arxiv:2404.07143",
            "title": "Test Paper",
            "authors": ["Author One"],
            "abstract": "Abstract",
            "url": "https://arxiv.org/abs/2404.07143",
            "pdf_url": "https://arxiv.org/pdf/2404.07143",
            "published_date": TEST_DATE,
            "categories": ["cs.AI"],
            "source": "arxiv",
            "hf_upvotes": 0,
            "pwc_stars": 0,
            "code_url": None,
            "citation_count": 0,
        }
    ]
    merged = merge_papers(arxiv_papers, hf_map)
    assert len(merged) == 1
    assert merged[0]["hf_upvotes"] == 312, "hf_upvotes 应被正确填充为 312"


# ──────────────────────────────────────────────────────────────────────────────
# 测试用例 4：test_pwc_enrich
# ──────────────────────────────────────────────────────────────────────────────

@respx.mock
async def test_pwc_enrich():
    """
    Papers With Code 数据补充：
    验证 code_url 和 pwc_stars 正确写入匹配论文。
    """
    respx.get(PWC_API_URL).mock(
        return_value=httpx.Response(200, json=PWC_RESPONSE_JSON)
    )

    papers = [
        {
            "id": "arxiv:2404.07143",
            "title": "Test Paper",
            "authors": [],
            "abstract": "",
            "url": "https://arxiv.org/abs/2404.07143",
            "pdf_url": "https://arxiv.org/pdf/2404.07143",
            "published_date": TEST_DATE,
            "categories": ["cs.AI"],
            "source": "arxiv",
            "hf_upvotes": 0,
            "pwc_stars": 0,
            "code_url": None,
            "citation_count": 0,
        }
    ]

    async with httpx.AsyncClient() as client:
        enriched = await fetch_pwc(client, TEST_DATE, papers)

    assert len(enriched) == 1
    assert enriched[0]["code_url"] == "https://github.com/example/rlvr", "code_url 应被正确写入"
    assert enriched[0]["pwc_stars"] == 1847, "pwc_stars 应为 1847"


# ──────────────────────────────────────────────────────────────────────────────
# 测试用例 5：test_dedup
# ──────────────────────────────────────────────────────────────────────────────

@respx.mock
async def test_dedup():
    """
    去重：arXiv 返回同一论文的 v1 和 v2，
    规范化后 arxiv_id 相同，merge_papers 只应保留第一条。
    """
    respx.get(url__startswith=ARXIV_API_URL).mock(
        return_value=httpx.Response(200, text=DUPLICATE_ARXIV_XML)
    )

    async with httpx.AsyncClient() as client:
        arxiv_papers = await fetch_arxiv(client, TEST_DATE)

    # fetch_arxiv 不去重，但 merge_papers 会去重
    merged = merge_papers(arxiv_papers, {})

    assert len(merged) == 1, "相同 arxiv_id 应只保留一条"
    assert merged[0]["id"] == "arxiv:2404.07143"


# ──────────────────────────────────────────────────────────────────────────────
# 测试用例 6：test_retry
# ──────────────────────────────────────────────────────────────────────────────

@respx.mock
async def test_retry():
    """
    指数退避重试：前两次请求触发 TimeoutException，
    第三次成功返回 200，函数应最终返回正常 Response。
    """
    # respx side_effect 列表：前两次超时，第三次成功
    respx.get(url__startswith=ARXIV_API_URL).mock(
        side_effect=[
            httpx.TimeoutException("timeout #1"),
            httpx.TimeoutException("timeout #2"),
            httpx.Response(200, text=VALID_ARXIV_XML),
        ]
    )

    async with httpx.AsyncClient() as client:
        resp = await fetch_with_retry(client, "GET", ARXIV_API_URL)

    assert resp is not None, "第三次重试成功后应返回 Response"
    assert resp.status_code == 200


# ──────────────────────────────────────────────────────────────────────────────
# 测试用例 7：test_skip_bad_entry
# ──────────────────────────────────────────────────────────────────────────────

@respx.mock
async def test_skip_bad_entry():
    """
    单条解析失败不影响其他条目：
    feed 含 1 条合法 + 1 条 published 为非法日期的条目，
    函数应跳过异常条目，返回包含 1 条合法论文的列表。
    """
    respx.get(url__startswith=ARXIV_API_URL).mock(
        return_value=httpx.Response(200, text=MIXED_ARXIV_XML)
    )

    async with httpx.AsyncClient() as client:
        papers = await fetch_arxiv(client, TEST_DATE)

    assert len(papers) == 1, "非法日期条目应被跳过，只保留 1 条合法论文"
    assert papers[0]["id"] == "arxiv:2404.07143"
    assert papers[0]["title"] == "Good Paper"
