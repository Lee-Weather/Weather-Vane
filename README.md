# Weather-Vane 🌤️

> **AI Paper Daily Push System** — Based on Claude Code native Skill mechanism, fetches the latest AI papers daily, automatically generates Chinese summaries using DeepSeek API, and pushes them through multiple channels.

📖 **Language** | English | [中文](./README.zh.md)

---

## Feature Overview

| Skill | Responsibility |
|-------|----------------|
| `Fetcher` | Fetches daily papers from arXiv / HuggingFace / Semantic Scholar |
| `Ranker` | Scores popularity, classifies topics, and filters Top-N |
| `Summarizer` | Generates detailed Chinese summaries via DeepSeek API (with timeout retry & auto-fallback) |
| `Storage` | Persists data to SQLite, supports history querying and deduplication |
| `Notifier` | Pushes daily reports (Telegram / Email / Local Markdown) |
| `Daily-Paper-Push` | Main orchestrator, pipelines all the Skills above |

---

## Quick Start

### 1. Clone and Configure Environment

```bash
git clone https://github.com/<your-org>/Weather-Vane.git
cd Weather-Vane

# Copy environment variable template
cp .env.example .env
# Edit .env, fill in DEEPSEEK_API_KEY and other configurations
```

### 2. Install Python Dependencies

```bash
# Recommended to use conda environment
conda activate ai_base
pip install -r requirements.txt
```

### 3. Automated Pipeline Run

```bash
# Run the complete pipeline: fetch, rank, summarize, save, and notify
python .claude/skills/Daily-Paper-Push/scripts/run_pipeline.py

# Or run for a specific date
python .claude/skills/Daily-Paper-Push/scripts/run_pipeline.py --date 2026-04-30
```

### 4. Step-by-step Run (Debugging)

```bash
# Run each step directly
python .claude/skills/Fetcher/scripts/fetch.py       --date 2026-04-30
python .claude/skills/Ranker/scripts/rank.py         --date 2026-04-30
python .claude/skills/Summarizer/scripts/summarize.py --date 2026-04-30
python .claude/skills/Storage/scripts/save.py        --save data/2026-04-30-summarized.json
python .claude/skills/Notifier/scripts/notify.py     --date 2026-04-30
```

---

## Environment Variables

| Variable | Required | Description |
|----------|:--------:|-------------|
| `DEEPSEEK_API_KEY` | ✅ | DeepSeek API Key (used for summarization) |
| `DEEPSEEK_BASE_URL` | ✅ | DeepSeek API Base URL |
| `DEEPSEEK_MODEL` | ✅ | DeepSeek Model Name (e.g. `deepseek-v4-pro`) |
| `SEMANTIC_SCHOLAR_API_KEY` | ❌ | Relaxed rate limits if key is provided |
| `TELEGRAM_BOT_TOKEN` | ❌ | Telegram Bot token |
| `TELEGRAM_CHAT_ID` | ❌ | Telegram target Chat ID |
| `EMAIL_SMTP_HOST` | ❌ | SMTP Server (e.g. `smtp.gmail.com`) |
| `EMAIL_SMTP_PORT` | ❌ | SMTP Port (default 587) |
| `EMAIL_USER` | ❌ | Sender email address |
| `EMAIL_PASSWORD` | ❌ | Sender password (App Password recommended) |
| `EMAIL_TO` | ❌ | Recipient email address |

---

## Implementation Progress

- [x] Skill 1 — Fetcher
- [x] Skill 2 — Ranker
- [x] Skill 3 — Summarizer (DeepSeek API integrated, with deep analysis and fallback model support)
- [x] Skill 4 — Storage
- [x] Skill 5 — Notifier
- [x] Skill 0 — Daily-Paper-Push (Orchestrator)

---

## License

MIT
