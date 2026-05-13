#!/usr/bin/env python3
"""
notify.py — AI 论文每日推送系统 通知模块

读取 summarized.json，按 Jinja2 模板渲染四板块日报，
通过 Gmail SMTP 发送 HTML 邮件，并保存本地 Markdown 归档。

用法：
    python notify.py                         # 默认处理昨天
    python notify.py --date 2026-04-30
    python notify.py --skip-email            # 跳过邮件推送
    python notify.py --dry-run               # 仅生成本地文件，不发送
    python notify.py --config path.yaml      # 指定配置文件

输出：
    reports/YYYY-MM-DD.md       （本地 Markdown 归档）
    Gmail HTML 邮件             （根据 config.yaml 配置）
"""

import argparse
import json
import logging
import os
import smtplib
import socket
import sys

import time
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# HTTP 代理支持（通过 CONNECT 隧道连接 SMTP）
def _setup_proxy():
    proxy_host = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    if not proxy_host:
        return
    import re
    m = re.match(r"https?://([^:/]+):(\d+)", proxy_host)
    if not m:
        print(f"[WARN] 无法解析 HTTP_PROXY：{proxy_host}", file=sys.stderr)
        return
    addr, port = m.group(1), int(m.group(2))
    try:
        import socks
        socks.setdefaultproxy(socks.PROXY_TYPE_HTTP, addr, port)
        socket.socket = socks.socksocket
        print(f"[INFO] HTTP 代理已配置：{addr}:{port}", file=sys.stderr)
    except ImportError:
        print("[WARN] PySocks 未安装，SMTP 将直连", file=sys.stderr)

_setup_proxy()

import yaml
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader

load_dotenv()

# Windows 终端 GBK 编码兼容：强制 stdout/stderr 使用 UTF-8
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ──────────────────────────────────────────────────────────────────────────────
# 常量
# ──────────────────────────────────────────────────────────────────────────────

TZ_CST = timezone(timedelta(hours=8))

PROJECT_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR     = PROJECT_ROOT / "data"
SKILL_DIR    = Path(__file__).resolve().parents[1]   # .claude/skills/Notifier/
DEFAULT_CONFIG = SKILL_DIR / "config.yaml"
TEMPLATE_DIR   = SKILL_DIR / "templates"

SMTP_RETRY_DELAYS = [5, 10]  # 重试间隔（秒）

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
# 参数解析
# ──────────────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Notifier — 论文日报推送")
    parser.add_argument("--date", type=str, default=None,
                        help="目标日期 YYYY-MM-DD（默认：昨天 UTC+8）")
    parser.add_argument("--skip-email", action="store_true",
                        help="跳过邮件推送（仅生成本地文件）")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG),
                        help=f"配置文件路径（默认：{DEFAULT_CONFIG}）")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅生成本地文件，不发送邮件")
    return parser.parse_args()

# ──────────────────────────────────────────────────────────────────────────────
# 配置加载
# ──────────────────────────────────────────────────────────────────────────────

# 默认配置（config.yaml 不存在时的回退）
DEFAULT_CONF = {
    "email": {
        "enabled": False,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "use_tls": True,
        "sender": "",
        "sender_name": "Weather-Vane 论文日报",
        "recipients": [],
        "subject_template": "📅 AI & 机器人论文日报 — {date}",
    },
    "local": {
        "enabled": True,
        "output_dir": "reports",
    },
}


def load_config(config_path: str) -> dict:
    """加载 config.yaml，不存在时返回默认配置。"""
    path = Path(config_path)
    if not path.exists():
        logger.warning("配置文件不存在：%s，使用默认配置（仅本地输出）", path)
        return DEFAULT_CONF.copy()

    with open(path, "r", encoding="utf-8") as f:
        conf = yaml.safe_load(f) or {}

    # 合并默认值
    result = DEFAULT_CONF.copy()
    if "email" in conf:
        result["email"].update(conf["email"])
    if "local" in conf:
        result["local"].update(conf["local"])

    logger.info("加载配置：%s", path)
    return result

# ──────────────────────────────────────────────────────────────────────────────
# 数据加载
# ──────────────────────────────────────────────────────────────────────────────

def load_summarized(date_str: str) -> dict:
    """读取 summarized.json。"""
    path = DATA_DIR / f"{date_str}-summarized.json"
    if not path.exists():
        logger.error("summarized.json 不存在：%s", path)
        logger.error("请先运行 Summarizer 脚本生成数据")
        sys.exit(1)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        logger.info("读取 summarized.json 成功：%s", path)
        return data
    except json.JSONDecodeError as e:
        logger.error("summarized.json 解析失败：%s", e)
        sys.exit(1)

# ──────────────────────────────────────────────────────────────────────────────
# 模板渲染
# ──────────────────────────────────────────────────────────────────────────────

def render_report(data: dict, template_dir: Path = TEMPLATE_DIR) -> str:
    """使用 Jinja2 渲染日报 Markdown。"""
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("report.md")

    daily_robot = data.get("daily_robot", [])
    daily_ai    = data.get("daily_ai", [])
    weekly_hot  = data.get("weekly_hot")
    monthly_hot = data.get("monthly_hot")

    stats = {
        "robot":   len(daily_robot),
        "ai":      len(daily_ai),
        "weekly":  1 if weekly_hot else 0,
        "monthly": 1 if monthly_hot else 0,
    }
    stats["total"] = stats["robot"] + stats["ai"] + stats["weekly"] + stats["monthly"]

    rendered = template.render(
        date=data.get("date", ""),
        daily_robot=daily_robot,
        daily_ai=daily_ai,
        weekly_hot=weekly_hot,
        monthly_hot=monthly_hot,
        stats=stats,
    )

    logger.info("模板渲染完成，共 %d 篇", stats["total"])
    return rendered

# ──────────────────────────────────────────────────────────────────────────────
# 本地归档
# ──────────────────────────────────────────────────────────────────────────────

def save_local(markdown: str, date_str: str, output_dir: str) -> Path:
    """保存 Markdown 日报到本地文件。"""
    out_dir = PROJECT_ROOT / output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{date_str}.md"
    out_path.write_text(markdown, encoding="utf-8")
    logger.info("本地归档保存：%s", out_path)
    return out_path

# ──────────────────────────────────────────────────────────────────────────────
# Markdown → HTML
# ──────────────────────────────────────────────────────────────────────────────

def markdown_to_html(md_text: str) -> str:
    """将 Markdown 转换为 HTML，包裹在简洁的样式中。"""
    try:
        import markdown as md_lib
        body = md_lib.markdown(md_text, extensions=["tables", "fenced_code"])
    except ImportError:
        logger.warning("markdown 库未安装，使用 <pre> 纯文本回退")
        body = f"<pre>{md_text}</pre>"

    # 包裹基础 CSS 样式
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: -apple-system, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; color: #333; line-height: 1.6; }}
  h1 {{ color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 8px; }}
  h2 {{ color: #2d3748; margin-top: 32px; }}
  h3 {{ color: #4a5568; }}
  a {{ color: #1a73e8; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  hr {{ border: none; border-top: 1px solid #e2e8f0; margin: 24px 0; }}
  blockquote {{ border-left: 4px solid #e2e8f0; margin: 16px 0; padding: 8px 16px; color: #718096; background: #f7fafc; }}
  p {{ margin: 8px 0; }}
</style>
</head>
<body>
{body}
</body>
</html>"""
    return html

# ──────────────────────────────────────────────────────────────────────────────
# Gmail 发送
# ──────────────────────────────────────────────────────────────────────────────

def send_gmail(
    config: dict,
    html_body: str,
    plain_body: str,
    subject: str,
) -> bool:
    """
    通过 Gmail SMTP 发送 HTML 邮件。
    返回 True 表示发送成功，False 表示失败。
    """
    email_conf = config["email"]
    sender     = email_conf["sender"]
    sender_name = email_conf.get("sender_name", "Weather-Vane")
    recipients = email_conf.get("recipients", [])
    smtp_host  = email_conf.get("smtp_host", "smtp.gmail.com")
    smtp_port  = email_conf.get("smtp_port", 587)
    use_tls    = email_conf.get("use_tls", True)
    password   = os.getenv("EMAIL_PASSWORD", "")

    if not sender:
        logger.error("[Gmail] 未配置发件人地址（config.yaml → email.sender）")
        return False
    if not recipients:
        logger.warning("[Gmail] 收件人列表为空，跳过邮件推送")
        return False
    if not password:
        logger.error("[Gmail] 未设置 EMAIL_PASSWORD 环境变量")
        return False

    # 构建 MIME 邮件
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"{sender_name} <{sender}>"
    msg["To"]      = ", ".join(recipients)

    # 纯文本回退 + HTML 正文
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    # 带重试的发送
    for attempt, delay in enumerate([0] + SMTP_RETRY_DELAYS, start=1):
        if delay > 0:
            logger.warning("[Gmail] 第 %d 次重试，等待 %ds", attempt, delay)
            time.sleep(delay)
        try:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
            if use_tls:
                server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipients, msg.as_string())
            server.quit()
            logger.info("[Gmail] 发送成功 → %s", ", ".join(recipients))
            return True
        except smtplib.SMTPAuthenticationError as e:
            logger.error("[Gmail] 认证失败：%s", e)
            return False  # 认证错误不重试
        except Exception as e:
            logger.warning("[Gmail] 发送失败（第 %d 次）：%s", attempt, e)

    logger.error("[Gmail] 全部 %d 次尝试失败，放弃", len(SMTP_RETRY_DELAYS) + 1)
    return False

# ──────────────────────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()

    # 确定目标日期
    if args.date:
        date_str = args.date
    else:
        date_str = (datetime.now(TZ_CST) - timedelta(days=1)).strftime("%Y-%m-%d")

    logger.info("=" * 60)
    logger.info("📧 Notifier 开始 — 目标日期：%s", date_str)
    logger.info("=" * 60)

    # Step 1: 加载配置
    config = load_config(args.config)

    # Step 2: 读取 summarized.json
    data = load_summarized(date_str)

    # Step 3: 渲染日报
    markdown_report = render_report(data)

    # Step 4: 本地归档（始终执行）
    local_conf = config.get("local", {})
    local_path = None
    if local_conf.get("enabled", True):
        output_dir = local_conf.get("output_dir", "reports")
        local_path = save_local(markdown_report, date_str, output_dir)

    # Step 5: 邮件推送
    email_sent = False
    email_conf = config.get("email", {})
    should_send = (
        email_conf.get("enabled", False)
        and not args.skip_email
        and not args.dry_run
    )

    if should_send:
        subject_tpl = email_conf.get("subject_template", "📅 论文日报 — {date}")
        subject = subject_tpl.format(date=date_str)
        html_body = markdown_to_html(markdown_report)
        email_sent = send_gmail(config, html_body, markdown_report, subject)
    elif args.dry_run:
        logger.info("[DRY RUN] 跳过邮件发送")
    elif args.skip_email:
        logger.info("已跳过邮件推送（--skip-email）")
    elif not email_conf.get("enabled", False):
        logger.info("邮件推送已禁用（config.yaml → email.enabled = false）")

    # Step 6: 打印统计
    daily_robot = data.get("daily_robot", [])
    daily_ai    = data.get("daily_ai", [])
    weekly_hot  = data.get("weekly_hot")
    monthly_hot = data.get("monthly_hot")
    total = len(daily_robot) + len(daily_ai) + (1 if weekly_hot else 0) + (1 if monthly_hot else 0)

    sep = "=" * 60
    print(f"\n{sep}")
    print(f"✅ Notifier 完成 — {date_str}")
    print(sep)
    if local_path:
        print(f"📄 本地归档：{local_path}（{total} 篇论文）")

    if should_send:
        status = "✅ 成功" if email_sent else "❌ 失败"
        print(f"📧 邮件推送：{status}")
        if email_sent:
            recipients = email_conf.get("recipients", [])
            print(f"   ├── 发件人：{email_conf.get('sender_name', '')} <{email_conf.get('sender', '')}>")
            print(f"   └── 收件人：{', '.join(recipients)}")
    elif args.dry_run:
        print("📧 邮件推送：[DRY RUN] 未发送")
    else:
        print("📧 邮件推送：已跳过")

    print(sep + "\n")


if __name__ == "__main__":
    main()
