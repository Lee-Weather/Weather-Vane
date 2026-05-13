# 📅 AI & 机器人论文日报 — {{ date }}

---

## 🤖 板块一：昨日机器人/具身智能论文（{{ daily_robot | length }} 篇）

{% if daily_robot %}
{% for paper in daily_robot %}
### {{ loop.index }}. 《{{ paper.title }}》

📝 {{ paper.summary_zh or "摘要生成中…" }}

🔗 [论文]({{ paper.url }}){% if paper.pdf_url %} | [PDF]({{ paper.pdf_url }}){% endif %}{% if paper.code_url %} | [代码]({{ paper.code_url }}){% endif %}

{% endfor %}
{% else %}
> 暂无数据

{% endif %}

---

## 🧠 板块二：昨日 AI 论文精选（{{ daily_ai | length }} 篇）

{% if daily_ai %}
{% for paper in daily_ai %}
### {{ loop.index }}. 《{{ paper.title }}》

📝 {{ paper.summary_zh or "摘要生成中…" }}

🔗 [论文]({{ paper.url }}){% if paper.pdf_url %} | [PDF]({{ paper.pdf_url }}){% endif %}{% if paper.code_url %} | [代码]({{ paper.code_url }}){% endif %}

{% endfor %}
{% else %}
> 暂无数据

{% endif %}

---

{% if weekly_hot %}
## 🔥 板块三：本周最热论文（{{ weekly_hot | length }} 篇）

{% for paper in weekly_hot %}
### {{ loop.index }}. 《{{ paper.title }}》

👥 作者：{{ paper.authors | join(', ') }}
🔥 HF 点赞：{{ paper.hf_upvotes or 0 }} | ⭐ Stars：{{ paper.pwc_stars or 0 }} | 📖 引用：{{ paper.citation_count or 0 }}

{{ paper.detail_zh or paper.summary_zh or "详细介绍生成中…" }}

🔗 [论文]({{ paper.url }}){% if paper.pdf_url %} | [PDF]({{ paper.pdf_url }}){% endif %}{% if paper.code_url %} | [代码]({{ paper.code_url }}){% endif %}
{% if not loop.last %}

{% endif %}
{% endfor %}

---
{% else %}
## 🔥 板块三：本周最热论文

> 暂无数据

---
{% endif %}

{% if monthly_hot %}
## 🏆 板块四：本月最热论文（{{ monthly_hot | length }} 篇）

{% for paper in monthly_hot %}
### {{ loop.index }}. 《{{ paper.title }}》

👥 作者：{{ paper.authors | join(', ') }}
🔥 HF 点赞：{{ paper.hf_upvotes or 0 }} | ⭐ Stars：{{ paper.pwc_stars or 0 }} | 📖 引用：{{ paper.citation_count or 0 }}

{{ paper.detail_zh or paper.summary_zh or "详细介绍生成中…" }}

🔗 [论文]({{ paper.url }}){% if paper.pdf_url %} | [PDF]({{ paper.pdf_url }}){% endif %}{% if paper.code_url %} | [代码]({{ paper.code_url }}){% endif %}
{% if not loop.last %}

{% endif %}
{% endfor %}

---
{% else %}
## 🏆 板块四：本月最热论文

> 暂无数据

---
{% endif %}

📊 统计：共推送 {{ stats.total }} 篇 | 🤖 机器人 {{ stats.robot }} 篇 | 🧠 AI {{ stats.ai }} 篇 | 🔥 周热门 {{ stats.weekly }} 篇 | 🏆 月热门 {{ stats.monthly }} 篇
