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

# Notifier Skill — 日报渲染与 Gmail 推送

读取 Summarizer 输出的 `summarized.json`，渲染四板块日报并推送。

## 执行步骤

1. **确定目标日期**：使用 `$ARGUMENTS` 中的日期，未提供则默认昨天（UTC+8）。

2. **运行推送脚本**：
   ```bash
   python3 scripts/notify.py --date "$ARGUMENTS"
   ```

3. **输出**：
   - 📄 本地归档：`reports/YYYY-MM-DD.md`（始终生成）
   - 📧 Gmail 推送：HTML 邮件发送至 `config.yaml` 中配置的收件人

4. **调试模式**：
   ```bash
   python3 scripts/notify.py --date 2026-04-30 --dry-run      # 仅生成本地文件
   python3 scripts/notify.py --date 2026-04-30 --skip-email    # 跳过邮件
   ```

## 配置文件

- `config.yaml`：邮件地址、SMTP 参数（可入库）
- `.env`：`EMAIL_PASSWORD`（Gmail 应用专用密码，不入库）

## 异常处理

- `summarized.json` 不存在：报错退出
- Gmail 认证/发送失败：记录 ERROR，跳过邮件，本地归档正常保存
- 某板块为空：正常渲染，显示"暂无数据"
