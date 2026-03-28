# SPEC.md — Voice Diary

## Overview
Voice Diary is a self-hosted Progressive Web App for recording voice notes. Users open the app on their phone, tap record, and the audio is uploaded and stored server-side. Recordings are transcribed and compiled into cohesive diary entries using AI.

## Phase 1 — Backend MVP + PWA Frontend

### Backend
- **Framework:** FastAPI (async, Python 3.12+)
- **Database:** PostgreSQL 17 via SQLAlchemy (async)
- **Auth:** API key via `X-API-Key` header
- **Storage:** Audio files on a Docker volume at `/data/audio/{date}/{uuid}.ogg`

### API Endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/recordings` | Upload audio + metadata (multipart) |
| GET | `/api/v1/recordings?date=YYYY-MM-DD` | List recordings for a date |
| DELETE | `/api/v1/recordings/{id}` | Delete a recording |
| GET | `/api/v1/recordings/{id}/audio` | Stream audio file |
| GET | `/api/v1/health` | Health check |

### Frontend
- Single-page PWA served from `/static/`
- MediaRecorder API (OGG/Opus)
- Timeline view with playback
- Mobile-first, dark theme
- Service Worker for static asset caching

### Infrastructure
- Docker Compose: app container + postgres
- HTTPS via mkcert certificates
- Uvicorn with SSL on port 8080

## Phase 2 — Diary Compiler + UI

### Backend
- **Diary Compiler:** Transcribes recordings via AWS Bedrock (Claude) and compiles into markdown diary entries
- **Scheduler:** APScheduler runs daily compilation at configurable time (default 03:00)
- **Model:** `DiaryEntry` table with date, content, metadata

### New API Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/entries?date=YYYY-MM-DD` | Get diary entry for a date |
| GET | `/api/v1/entries?limit=N&offset=N` | List all entries (paginated) |
| POST | `/api/v1/entries/compile` | Trigger compilation for a date |
| DELETE | `/api/v1/entries/{id}` | Delete entry (un-compiles recordings) |

### Compiler Pipeline
1. Gather uncompiled recordings for a date
2. Read and encode audio files
3. Transcribe each via Bedrock Converse API (Claude)
4. Compile all transcriptions into a diary entry with system prompt
5. Store entry, mark recordings as compiled

### Frontend Additions
- Today/Diary navigation tabs
- Compile button with loading spinner
- Diary entry display with markdown rendering
- Compiled badge on recording cards
- Diary list view with pagination

### Configuration (env vars)
| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_ACCESS_KEY_ID` | — | AWS credentials |
| `AWS_SECRET_ACCESS_KEY` | — | AWS credentials |
| `AWS_REGION` | `us-east-1` | Bedrock region |
| `BEDROCK_MODEL_ID` | `us.anthropic.claude-sonnet-4-20250514` | Claude model |
| `COMPILE_TIME` | `03:00` | Daily auto-compile time (HH:MM) |

## Phase 3+ (planned)
- Offline recording queue (IndexedDB sync)
- Search across diary entries
- Export (markdown/PDF)
- Push notifications
- Tests
- Settings page
