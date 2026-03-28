# Architecture — Voice Diary

## Overview

Voice Diary is a self-hosted Progressive Web App for recording voice notes and compiling them into diary entries using AI. It runs as two Docker containers (FastAPI app + PostgreSQL) behind an Nginx TLS reverse proxy.

```
┌─────────────────────────────────────────────────────────────┐
│  Android Phone (PWA — home screen icon)                     │
│                                                             │
│  Browser → MediaRecorder API → audio blob (OGG/Opus)        │
│         → fetch() with X-API-Key header                     │
└──────────────────────┬──────────────────────────────────────┘
                       │ HTTPS (port 8444)
                       │ Host: <your-ip>
                       ▼
┌─────────────────────────────────────────────────────────────┐
│  Docker Compose: voice-diary                                │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  voice_diary_app (FastAPI + Uvicorn)                 │    │
│  │                                                      │    │
│  │  HTTP only (TLS terminated by nginx-tls sidecar)     │    │
│  │  ├── Middleware: API key auth                        │    │
│  │  ├── Routes: /api/v1/recordings/*                    │    │
│  │  ├── Routes: /api/v1/entries/*                       │    │
│  │  ├── Routes: /api/v1/health                          │    │
│  │  ├── Static: PWA frontend at /                       │    │
│  │  └── Scheduler: APScheduler (daily compile)          │    │
│  │                                                      │    │
│  │  Volumes:                                            │    │
│  │    audio_data → /data/audio/                         │    │
│  └──────────────────┬──────────────────────────────────┘    │
│                     │ postgresql+asyncpg://                  │
│                     ▼                                        │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  voice_diary_db (PostgreSQL 17 Alpine)               │   │
│  │                                                      │   │
│  │  Database: voice_diary                               │   │
│  │  Tables: recordings, diary_entries                    │   │
│  │  Volume: db_data → /var/lib/postgresql/data          │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  External:                                                  │
│    voice_diary_app ──► AWS Bedrock (us-east-1)              │
│                        Model: claude-sonnet (configurable)  │
└─────────────────────────────────────────────────────────────┘
```

---

## Request Flow

Every request from the phone follows this path:

```
Phone browser
  │
  │  HTTPS request (fetch API or page load)
  │  Host: <your-ip>:8444
  │  Headers: X-API-Key: <key>
  ▼
Uvicorn (HTTPS, TLS via mkcert certs)
  │
  │  TLS termination at nginx-tls sidecar
  ▼
FastAPI Middleware Stack
  │
  ├── api_key_middleware()
  │     Checks request.url.path:
  │       /api/* (except PUBLIC_PATHS) → require X-API-Key header
  │       Anything else → pass through (static files, root, health)
  │
  │     On failure: return JSONResponse(401)
  │     (Note: uses JSONResponse, not raise HTTPException —
  │      FastAPI middleware cannot raise HTTPException)
  ▼
Router dispatch
  │
  ├── GET /                          → FileResponse("app/static/index.html")
  ├── GET /static/*                  → StaticFiles (PWA assets)
  ├── GET /api/v1/health             → {"status": "ok"} (no auth)
  ├── POST /api/v1/recordings        → Upload recording
  ├── GET /api/v1/recordings?date=   → List recordings
  ├── DELETE /api/v1/recordings/{id} → Delete recording
  ├── GET /api/v1/recordings/{id}/audio → Stream audio file
  ├── GET /api/v1/entries            → List diary entries
  ├── GET /api/v1/entries?date=      → Get entry by date
  ├── POST /api/v1/entries/compile   → Trigger compilation
  └── DELETE /api/v1/entries/{id}    → Delete entry + un-compile recordings
```

### Public Paths (no API key required)

```python
PUBLIC_PATHS = {"/api/v1/health", "/", "/favicon.ico"}
```

All `/static/*` paths are also unprotected (mounted separately, before middleware applies).

### Protected Paths (API key required)

Everything under `/api/` except the public paths above. The middleware checks:

```python
if path.startswith("/api/") and path not in PUBLIC_PATHS:
    key = request.headers.get("X-API-Key", "")
    if key != API_KEY:
        return JSONResponse(status_code=401, ...)
```

---

## Recording Pipeline

### 1. Capture (Browser)

```
User taps Record
  │
  ▼
MediaRecorder API
  MIME: audio/ogg;codecs=opus (preferred)
  Fallback: audio/webm;codecs=opus (Safari/Chrome compat)
  │
  │  Collects audio chunks into Blob
  ▼
User taps Stop
  │
  ▼
Browser creates FormData:
  file: Blob (audio)
  recorded_at: ISO 8601 timestamp
  mood: optional string
  tags: optional (not yet in UI)
  duration_seconds: optional int
```

**HTTPS requirement:** MediaRecorder API only works on secure origins. The app serves over HTTPS using mkcert certificates. On first visit to `https://<your-ip>:8444`, the browser shows a certificate warning (self-signed). After accepting, it works permanently.

### 2. Upload (API)

```
POST /api/v1/recordings
Content-Type: multipart/form-data

  ┌─────────────────────────────────────────────┐
  │  recordings.py: upload_recording()          │
  │                                              │
  │  1. Generate UUID for recording              │
  │  2. Read uploaded file bytes                 │
  │  3. Create directory: /data/audio/{date}/    │
  │  4. Write file: /data/audio/{date}/{uuid}.ogg│
  │  5. Create DB record with metadata           │
  │  6. Return JSON response with recording info │
  └─────────────────────────────────────────────┘
```

### 3. Storage

**File storage:** Docker named volume `audio_data` mounted at `/data/audio/`.

```
/data/audio/
├── 2026-03-22/
│   ├── a1b2c3d4-e5f6-7890-abcd-ef1234567890.ogg
│   └── f0e1d2c3-b4a5-9876-fedc-ba0987654321.ogg
├── 2026-03-23/
│   └── ...
```

Files are organized by date for easy browsing and cleanup. File names are UUIDs (no collision risk).

**Database record:**

```sql
INSERT INTO recordings (id, recorded_at, file_path, file_size_bytes, mood, ...)
VALUES (uuid, timestamp, '/data/audio/2026-03-22/uuid.ogg', 10240, 'happy', ...);
```

### 4. Retrieval

```
GET /api/v1/recordings?date=2026-03-22
  → Returns JSON array of recording metadata (no audio data)

GET /api/v1/recordings/{id}/audio
  → Streams the audio file back (FileResponse with media type detection)
  → Used by the <audio> player in the PWA frontend
```

### 5. Deletion

```
DELETE /api/v1/recordings/{id}
  1. Look up recording in DB
  2. Delete file from disk (Path.unlink)
  3. Delete DB record
  4. Return 204
```

---

## Compilation Pipeline

### Trigger

Compilation can be triggered two ways:

**1. Scheduled (APScheduler)**

```python
# In app/main.py lifespan():
scheduler = AsyncIOScheduler()
scheduler.add_job(
    scheduled_compile,
    CronTrigger(hour=int(hour), minute=int(minute)),  # default: 03:00
    id="daily_compile",
)
```

The scheduled job compiles **yesterday's** recordings (the day that just ended).

**2. Manual (API)**

```
POST /api/v1/entries/compile
Body: {"date": "2026-03-22"}

  → Returns 202 with the compiled entry
  → Returns 409 if entry already exists or no uncompiled recordings
```

### Pipeline Steps

```
compile_diary_entry(target_date)
  │
  │  Step 1: Check for existing entry
  │    SELECT * FROM diary_entries WHERE entry_date = target_date
  │    If exists → skip (return None)
  │
  │  Step 2: Gather uncompiled recordings
  │    SELECT * FROM recordings
  │    WHERE date(recorded_at) = target_date
  │      AND compiled = false
  │    ORDER BY recorded_at ASC
  │
  │    If none → return None
  │
  │  Step 3: Transcribe each recording
  │    For each recording:
  │      │
  │      ▼
  │    ┌────────────────────────────────────────────┐
  │    │  transcribe_recording(client, recording)   │
  │    │                                             │
  │    │  1. Read audio file from disk               │
  │    │  2. Determine MIME type from extension      │
  │    │  3. Send to Bedrock Converse API:           │
  │    │     message.content = [                     │
  │    │       {document: {source: {bytes: audio}}}  │
  │    │       {text: "Transcribe this audio..."}    │
  │    │     ]                                       │
  │    │  4. Return transcript text                  │
  │    │  5. Store transcript on recording.transcript│
  │    │                                             │
  │    │  On failure: log error, return None         │
  │    │  (other recordings still processed)         │
  │    └────────────────────────────────────────────┘
  │
  │  Step 4: Compile diary entry
  │    Concatenate all transcripts with timestamps:
  │      "[14:30] (45s)\nTranscript text...\n\n[16:00] (30s)\n..."
  │
  │    Send to Bedrock Converse API:
  │      system: "You are writing a personal diary entry..."
  │      user: "Date: Monday, March 22, 2026\n\nTranscriptions:\n\n{text}"
  │
  │    Returns: compiled markdown diary entry
  │
  │  Step 5: Store entry
  │    INSERT INTO diary_entries (entry_date, content, recording_count, ...)
  │
  │  Step 6: Mark recordings compiled
  │    UPDATE recordings SET compiled = true
  │    WHERE date(recorded_at) = target_date
  │
  ▼
  DiaryEntry (or None if nothing to compile)
```

### Bedrock Integration

```
┌──────────────────────────────────────────┐
│  AWS Bedrock Runtime (Converse API)      │
│                                          │
│  Region: AWS_REGION (default: us-east-1) │
│  Model: BEDROCK_MODEL_ID                 │
│    default: us.anthropic.claude-sonnet-4-20250514 │
│  Auth: AWS_ACCESS_KEY_ID +               │
│        AWS_SECRET_ACCESS_KEY (env vars)  │
│                                          │
│  Two calls per compilation:              │
│    1. N calls for transcription          │
│       (one per recording, audio in)      │
│    2. 1 call for compilation             │
│       (all transcripts in, diary out)    │
│                                          │
│  Error handling:                         │
│    BotoCoreError / ClientError caught    │
│    → logged, RuntimeError raised         │
│    → caller catches, skips that step     │
│    → app never crashes from Bedrock      │
└──────────────────────────────────────────┘
```

**Audio MIME type mapping:**

| Extension | MIME Type |
|---|---|
| `.ogg`, `.opus` | `audio/ogg` |
| `.webm` | `audio/webm` |
| `.mp3` | `audio/mpeg` |
| `.wav` | `audio/wav` |
| `.m4a`, `.mp4` | `audio/mp4` |

---

## Data Model

### recordings

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK, default gen_random_uuid() | Unique recording ID |
| `recorded_at` | TIMESTAMPTZ | NOT NULL | When the user recorded it |
| `uploaded_at` | TIMESTAMPTZ | DEFAULT now() | When it was uploaded |
| `duration_seconds` | INTEGER | nullable | Audio duration |
| `file_path` | TEXT | NOT NULL | Absolute path: `/data/audio/{date}/{uuid}.ogg` |
| `file_size_bytes` | BIGINT | nullable | File size |
| `transcript` | TEXT | nullable | AI transcription (populated during compilation) |
| `tags` | TEXT[] | nullable | User-defined tags |
| `mood` | VARCHAR(50) | nullable | Mood label (happy, sad, etc.) |
| `compiled` | BOOLEAN | DEFAULT FALSE | Whether this recording has been compiled into a diary entry |

**Indexes:** `idx_recordings_date` on `recorded_at::date` (for date-based queries).

### diary_entries

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK, default gen_random_uuid() | Unique entry ID |
| `entry_date` | DATE | UNIQUE, NOT NULL | One entry per day |
| `content` | TEXT | NOT NULL | Compiled diary entry (markdown) |
| `recording_count` | INTEGER | nullable | How many recordings were compiled |
| `total_duration_seconds` | INTEGER | nullable | Sum of all recording durations |
| `model_used` | VARCHAR(100) | nullable | Bedrock model ID used |
| `compiled_at` | TIMESTAMPTZ | DEFAULT now() | When compilation happened |

**Indexes:** `idx_entries_date` on `entry_date`.

### Relationship

```
recordings.recorded_at::date ──── diary_entries.entry_date

Not a formal FK — linked by date.
A diary entry covers all recordings for that date.
When a diary entry is deleted, its recordings are un-marked (compiled = false).
```

---

## Infrastructure

### Docker Compose Topology

```yaml
services:
  app:                          # voice_diary_app
    build: .                    # Python 3.12-slim + FastAPI + boto3
    ports: ["${APP_PORT:-8080}:8080"]
    volumes:
      - audio_data:/data/audio  # Persistent audio storage
      -  TLS certificates (read-only)# TLS certificates (read-only)
    depends_on:
      db: { condition: service_healthy }
    restart: unless-stopped
    command: uvicorn app.main:app --host 0.0.0.0 --port 8080

  db:                           # voice_diary_db
    image: postgres:17-alpine
    volumes:
      - db_data:/var/lib/postgresql/data
    healthcheck:
      test: pg_isready -U $POSTGRES_USER
      interval: 10s, retries: 5, start_period: 30s
    restart: always

volumes:
  db_data:     # PostgreSQL data files
  audio_data:  # Audio recordings
```

### Volume Details

| Volume | Mount | Owner | Content | Backup priority |
|---|---|---|---|---|
| `voice-diary_db_data` | `/var/lib/postgresql/data` (db) | postgres | Database files | CRITICAL |
| `voice-diary_audio_data` | `/data/audio` (app) | root | Audio recordings | HIGH |
| `./certs` (bind) | `/certs` (app, ro) | host user | TLS cert + key | LOW (regeneratable) |

### Network

- **Docker network:** `voice-diary_default` (bridge, internal)
- **Exposed port:** `${APP_PORT:-8080}` mapped to host
- **Current deployment:** port 8444 on host
- **Access:** `https://<your-ip>:8444`
- **TLS:** Self-signed mkcert certificate (browser warning on first visit)

---

## Environment Variables

| Variable | Required | Default | Used By | Description |
|---|---|---|---|---|
| `DB_USER` | Yes | — | compose → postgres | PostgreSQL username |
| `DB_PASS` | Yes | — | compose → postgres + app | PostgreSQL password |
| `DB_NAME` | Yes | — | compose → postgres + app | Database name |
| `API_KEY` | Yes | — | app | X-API-Key for all protected routes |
| `APP_PORT` | No | 8080 | compose | Host-side HTTPS port |
| `COMPILE_TIME` | No | 03:00 | app | Daily compilation time (HH:MM) |
| `AWS_ACCESS_KEY_ID` | For compilation | — | app → boto3 | Bedrock auth |
| `AWS_SECRET_ACCESS_KEY` | For compilation | — | app → boto3 | Bedrock auth |
| `AWS_REGION` | No | us-east-1 | app → boto3 | Bedrock region |
| `BEDROCK_MODEL_ID` | No | us.anthropic.claude-sonnet-4-20250514 | app | Model for transcription + compilation |

---

## Scheduled Tasks

| Task | Trigger | Time | What it does |
|---|---|---|---|
| Daily compilation | APScheduler CronTrigger | `COMPILE_TIME` (default 03:00) | Compiles yesterday's uncompiled recordings into a diary entry |

The scheduler is initialized in the FastAPI lifespan handler. If `apscheduler` is not installed, a warning is logged and the scheduler is skipped (the app still works for recording, just no auto-compile).
