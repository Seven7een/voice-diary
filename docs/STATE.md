# STATE.md — Voice Diary

## Current Phase: 2 — Diary Compiler + UI ✅

### Phase 1 — Backend MVP + PWA Frontend ✅
- [x] Project scaffolding and docs
- [x] Database models and connection (async SQLAlchemy + asyncpg)
- [x] API endpoints (recordings CRUD + health + audio streaming)
- [x] API key auth middleware
- [x] Dockerfile and docker-compose.yml
- [x] PWA frontend (record, playback, timeline, date navigation)
- [x] Service Worker and manifest.json
- [x] HTTPS/mkcert setup documented in WORKFLOW.md
- [x] PWA icons generated

### Phase 2 — Diary Compiler + UI ✅
- [x] DiaryEntry model with migration support (auto-created on startup)
- [x] Diary compiler pipeline (transcribe via Bedrock → compile via Claude)
- [x] Entries API (list, get by date, compile, delete with un-compile)
- [x] Scheduled daily compilation via APScheduler (configurable time)
- [x] Frontend: Today/Diary nav tabs
- [x] Frontend: Compile button with spinner status
- [x] Frontend: Diary entry rendered as markdown below timeline
- [x] Frontend: Compiled badge on recording cards
- [x] Frontend: Diary list view with pagination and click-to-navigate
- [x] Docker Compose updated with AWS/Bedrock env vars
- [x] Requirements updated (boto3, apscheduler)

### Blocked
_Nothing currently blocked._

### Not Started (Phase 3+)
- Offline recording queue (IndexedDB sync)
- Search across diary entries
- Export (markdown/PDF)
- Push notifications
- Tests
- Settings page
