# CLAUDE.md — Voice Diary

## Forge Conventions

This project was scaffolded following [The Forge](https://github.com/seven7een/the-forge) conventions.

- **Priority order:** Privacy/Security > Functionality > Extensibility > Elegance
- **Never commit:** secrets, API keys, tokens, PII, personal details, .env files
- **Environment variables:** anything that can be an env var must be one. See `.env.example`.
- `.internal/` is gitignored scratch space
- `docs/SPEC.md` — what this project does
- `docs/STATE.md` — what's done and what's blocked (update before every commit)
- `docs/WORKFLOW.md` — how to develop, test, and deploy
- A gitleaks pre-commit hook scans every commit for secrets. Treat findings as hard blockers.

## Project Overview

Voice Diary is a self-hosted PWA for recording voice notes throughout the day. At end-of-day, a compiler transcribes recordings and compiles them into a diary entry using AWS Bedrock (Claude).

**Stack:** FastAPI + PostgreSQL + vanilla JS PWA, Docker Compose, HTTPS via mkcert.

## Key Conventions

- API key auth via `X-API-Key` header on all `/api/` routes (except health)
- Audio stored at `/data/audio/{date}/{uuid}.ogg`
- Diary entries are markdown, stored in PostgreSQL
- Bedrock errors are caught and logged, never crash the app
- APScheduler runs daily compilation at configurable time

## Project Structure

```
app/
├── main.py              # FastAPI app, middleware, scheduler
├── database.py          # Async SQLAlchemy engine
├── models.py            # Recording + DiaryEntry models
├── compiler.py          # Bedrock transcription + diary compilation
├── routes/
│   ├── recordings.py    # Recording CRUD
│   ├── entries.py       # Diary entry CRUD + compile trigger
│   └── health.py        # Health check
└── static/              # PWA frontend (served by FastAPI)
```

## Build & Run

```bash
docker compose up -d --build
# Access at https://<host>:8080
```
