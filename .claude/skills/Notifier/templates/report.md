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
## 🔥 板块三：本周最热论文

### 《{{ weekly_hot.title }}》

👥 作者：{{ weekly_hot.authors | join(', ') }}
🔥 HF 点赞：{{ weekly_hot.hf_upvotes or 0 }} | ⭐ Stars：{{ weekly_hot.pwc_stars or 0 }} | 📖 引用：{{ weekly_hot.citation_count or 0 }}

{{ weekly_hot.detail_zh or weekly_hot.summary_zh or "详细介绍生成中…" }}

🔗 [论文]({{ weekly_hot.url }}){% if weekly_hot.pdf_url %} | [PDF]({{ weekly_hot.pdf_url }}){% endif %}{% if weekly_hot.code_url %} | [代码]({{ weekly_hot.code_url }}){% endif %}

---
{% else %}
## 🔥 板块三：本周最热论文

> 暂无数据

---
{% endif %}

{% if monthly_hot %}
## 🏆 板块四：本月最热论文

### 《{{ monthly_hot.title }}》

👥 作者：{{ monthly_hot.authors | join(', ') }}
🔥 HF 点赞：{{ monthly_hot.hf_upvotes or 0 }} | ⭐ Stars：{{ monthly_hot.pwc_stars or 0 }} | 📖 引用：{{ monthly_hot.citation_count or 0 }}

{{ monthly_hot.detail_zh or monthly_hot.summary_zh or "详细介绍生成中…" }}

🔗 [论文]({{ monthly_hot.url }}){% if monthly_hot.pdf_url %} | [PDF]({{ monthly_hot.pdf_url }}){% endif %}{% if monthly_hot.code_url %} | [代码]({{ monthly_hot.code_url }}){% endif %}

---
{% else %}
## 🏆 板块四：本月最热论文

> 暂无数据

---
{% endif %}

📊 统计：共推送 {{ stats.total }} 篇 | 🤖 机器人 {{ stats.robot }} 篇 | 🧠 AI {{ stats.ai }} 篇 | 🔥 周热门 {{ stats.weekly }} 篇 | 🏆 月热门 {{ stats.monthly }} 篇
