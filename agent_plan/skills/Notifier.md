# Notifier Skill 设计文档

**Skill 路径**：`.claude/skills/Notifier/`
**对应总计划**：`agent_plan/AI_Paper_Daily_Push_Plan.md` — Skill 5

---

## 1. 职责

系统的**最后一公里**。读取 `summarizer` 输出的 `summarized.json`，按四板块模板渲染日报，通过 Gmail 邮件推送并保存本地 Markdown 归档。

核心能力：
- **模板渲染**：将四板块论文数据（机器人组 15 篇 + AI 组 5 篇 + 周热门 1 篇 + 月热门 1 篇）组装为美观可读的报告
- **Gmail 推送**：通过 SMTP + 应用专用密码发送 HTML 邮件
- **本地归档**：始终生成 `reports/YYYY-MM-DD.md`，即使邮件发送失败也能保留完整内容

---

## 2. Skill 文件结构

```
.claude/skills/Notifier/
├── SKILL.md                      ← 必须。frontmatter 元数据 + 调用说明
├── config.yaml                   ← 邮件收发地址等推送配置（不含密码）
├── scripts/
│   └── notify.py                 ← 驱动脚本
├── templates/
│   └── report.md                 ← 日报 Markdown 模板
└── tests/
    └── test_notify.py            ← 单元测试
```

---

## 3. 配置设计

### 3.1 `config.yaml`（推送渠道配置，可安全入库）

```yaml
# Notifier 推送配置
# 密码/Token 等敏感信息请放在 .env 中，此文件仅存放地址和格式选项

email:
  enabled: true
  smtp_host: smtp.gmail.com
  smtp_port: 587
  use_tls: true
  sender: "your-email@gmail.com"          # 发件人地址
  sender_name: "Weather-Vane 论文日报"      # 发件人显示名称
  recipients:                              # 收件人列表（支持多人）
    - "recipient1@example.com"
    - "recipient2@example.com"
  subject_template: "📅 AI & 机器人论文日报 — {date}"  # 邮件主题模板

local:
  enabled: true                            # 本地 Markdown 归档（始终建议开启）
  output_dir: "reports"                    # 输出目录（相对于项目根目录）
```

### 3.2 `.env`（敏感信息，已在 .gitignore 中）

仅需以下两个环境变量：

```
EMAIL_PASSWORD=xxxx-xxxx-xxxx-xxxx    # Gmail 应用专用密码
```

> **Gmail 配置指南**：
> 1. 开启 Google 账号的两步验证
> 2. 前往 https://myaccount.google.com/apppasswords 生成"应用专用密码"
> 3. 将生成的 16 位密码填入 `.env` 的 `EMAIL_PASSWORD`

---

## 4. 输入 / 输出

### 输入

`data/YYYY-MM-DD-summarized.json`（由 Summarizer 生成），四板块结构，每篇论文已包含 `summary_zh` 和/或 `detail_zh` 字段。

### 输出

1. **本地文件**：`reports/YYYY-MM-DD.md`（始终生成）
2. **Gmail 邮件**：HTML 格式日报（根据 `config.yaml` 中 `email.enabled` 决定）

---

## 5. 日报模板格式

`templates/report.md` 使用 Jinja2 风格占位符：

```markdown
# 📅 AI & 机器人论文日报 — {{ date }}

---

## 🤖 板块一：昨日机器人/具身智能论文（{{ daily_robot | length }} 篇）

{% for paper in daily_robot %}
### {{ loop.index }}. 《{{ paper.title }}》

📝 {{ paper.summary_zh }}

🔗 [论文]({{ paper.url }}) | [PDF]({{ paper.pdf_url }}){% if paper.code_url %} | [代码]({{ paper.code_url }}){% endif %}

{% endfor %}

---

## 🧠 板块二：昨日 AI 论文精选（{{ daily_ai | length }} 篇）

{% for paper in daily_ai %}
### {{ loop.index }}. 《{{ paper.title }}》

📝 {{ paper.summary_zh }}

🔗 [论文]({{ paper.url }}) | [PDF]({{ paper.pdf_url }}){% if paper.code_url %} | [代码]({{ paper.code_url }}){% endif %}

{% endfor %}

---

{% if weekly_hot %}
## 🔥 板块三：本周最热论文

### 《{{ weekly_hot.title }}》

👥 作者：{{ weekly_hot.authors | join(', ') }}
🔥 HF 点赞：{{ weekly_hot.hf_upvotes }} | ⭐ Stars：{{ weekly_hot.pwc_stars }} | 📖 引用：{{ weekly_hot.citation_count }}

{{ weekly_hot.detail_zh }}

🔗 [论文]({{ weekly_hot.url }}) | [PDF]({{ weekly_hot.pdf_url }}){% if weekly_hot.code_url %} | [代码]({{ weekly_hot.code_url }}){% endif %}
{% endif %}

---

{% if monthly_hot %}
## 🏆 板块四：本月最热论文

### 《{{ monthly_hot.title }}》

👥 作者：{{ monthly_hot.authors | join(', ') }}
🔥 HF 点赞：{{ monthly_hot.hf_upvotes }} | ⭐ Stars：{{ monthly_hot.pwc_stars }} | 📖 引用：{{ monthly_hot.citation_count }}

{{ monthly_hot.detail_zh }}

🔗 [论文]({{ monthly_hot.url }}) | [PDF]({{ monthly_hot.pdf_url }}){% if monthly_hot.code_url %} | [代码]({{ monthly_hot.code_url }}){% endif %}
{% endif %}

---

📊 统计：共推送 {{ stats.total }} 篇 | 机器人 {{ stats.robot }} 篇 | AI {{ stats.ai }} 篇 | 周热门 {{ stats.weekly }} 篇 | 月热门 {{ stats.monthly }} 篇
```

---

## 6. `notify.py` 执行流程

```
Step 1: 加载 config.yaml（收件人、SMTP 配置等）
Step 2: 加载 .env 中的 EMAIL_PASSWORD
Step 3: 读取 data/YYYY-MM-DD-summarized.json
Step 4: 使用 Jinja2 渲染 templates/report.md → 生成 Markdown 正文
Step 5: 保存本地文件 reports/YYYY-MM-DD.md
Step 6: 将 Markdown 转换为 HTML（邮件正文）
Step 7: 构建 MIME 邮件（HTML 正文 + 纯文本回退）
Step 8: 通过 Gmail SMTP 发送邮件
Step 9: 打印推送统计
```

### 控制台输出示例

```
============================================================
✅ Notifier 完成 — 2026-04-30
============================================================
📄 本地归档：reports/2026-04-30.md（22 篇论文）
📧 邮件推送：成功
   ├── 发件人：Weather-Vane <your-email@gmail.com>
   └── 收件人：recipient1@example.com, recipient2@example.com
============================================================
```

---

## 7. 参数设计

```bash
python3 scripts/notify.py --date 2026-04-30        # 指定日期（默认昨天）
python3 scripts/notify.py --skip-email              # 跳过邮件推送（仅生成本地文件）
python3 scripts/notify.py --config path/config.yaml # 指定配置文件
python3 scripts/notify.py --dry-run                 # 生成日报但不发送邮件
```

---

## 8. SKILL.md frontmatter

```yaml
---
name: notifier
description: >
  读取 summarized.json，按四板块模板渲染日报 Markdown，
  通过 Gmail 推送 HTML 邮件，并保存本地 reports/ 归档。
  当需要发送论文日报时使用。
argument-hint: "[YYYY-MM-DD]"
allowed-tools: Bash Read Write
context: fork
effort: low
---
```

---

## 9. 异常处理

| 场景 | 处理方式 |
|------|---------|
| `summarized.json` 不存在 | 报错退出，提示先运行 Summarizer |
| `config.yaml` 不存在 | 使用默认配置（仅本地输出），WARN 提示 |
| Gmail 认证失败 | 记录 ERROR，跳过邮件推送，本地归档正常生成 |
| Gmail 发送超时 | 重试最多 2 次（间隔 5s），失败后跳过 |
| 某板块为空 | 正常渲染，标注"暂无数据" |
| 收件人列表为空 | 跳过邮件推送，仅本地输出 |
| Markdown 转 HTML 失败 | 回退发送纯文本格式 |

---

## 10. 依赖

| 库 | 用途 | 备注 |
|----|------|------|
| `jinja2` | 模板渲染 | 需新增到 requirements.txt |
| `markdown` | Markdown → HTML 转换 | 需新增到 requirements.txt |
| `smtplib` | Gmail SMTP 发送 | Python 内置 |
| `email.mime` | MIME 邮件构建 | Python 内置 |
| `pyyaml` | config.yaml 解析 | 已在 requirements.txt |
| `python-dotenv` | 加载 .env | 已在 requirements.txt |

---

## 11. 实施检查清单

- [x] 创建 `.claude/skills/Notifier/SKILL.md`
- [x] 创建 `.claude/skills/Notifier/config.yaml`
- [x] 创建 `.claude/skills/Notifier/templates/report.md`
- [x] 创建 `.claude/skills/Notifier/scripts/notify.py`
  - [x] 实现 `load_config()` 加载 config.yaml
  - [x] 实现 `load_summarized(date)` 读取 summarized.json
  - [x] 实现 `render_report(data, template)` Jinja2 模板渲染
  - [x] 实现 `save_local(markdown, date)` 本地归档
  - [x] 实现 `markdown_to_html(md_text)` 格式转换
  - [x] 实现 `send_gmail(config, html, subject)` Gmail SMTP 发送
- [x] 创建 `.claude/skills/Notifier/tests/test_notify.py`（19 项测试，全部通过）
  - [x] 测试配置加载
  - [x] 测试模板渲染（含空板块边界）
  - [x] 测试 Markdown → HTML 转换
  - [x] 测试 dry-run 模式
- [x] 更新 `requirements.txt` 添加 `jinja2` 和 `markdown`
- [ ] Gmail 应用专用密码配置与实际发送测试
