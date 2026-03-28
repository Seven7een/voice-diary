# WORKFLOW.md — Voice Diary

## Prerequisites
- Docker & Docker Compose
- mkcert (for local TLS certs)

## Initial Setup

### 1. Environment
```bash
cp .env.example .env
# Edit .env — set DB_PASS and API_KEY to strong random values
```

### 2. TLS Certificates (mkcert)
```bash
# Install mkcert if needed: https://github.com/FiloSottile/mkcert
mkcert -install                          # one-time: install local CA
mkdir -p certs
mkcert -cert-file certs/local-cert.pem -key-file certs/local-key.pem localhost 127.0.0.1 ::1
```
Add any additional hostnames/IPs you'll access the app from.

### 3. Build & Run
```bash
docker compose up --build -d
```

### 4. Access
Open `https://localhost:8080` (accept the self-signed cert if your browser hasn't trusted the mkcert CA).

## Development

### Rebuild after code changes
```bash
docker compose up --build -d
```

### View logs
```bash
docker compose logs -f app
docker compose logs -f db
```

### Database shell
```bash
docker compose exec db psql -U voicediary -d voicediary
```

### Reset everything
```bash
docker compose down -v   # WARNING: destroys all data
```

## Testing the API

```bash
# Health check
curl -k https://localhost:8080/api/v1/health

# Upload a recording
curl -k -X POST https://localhost:8080/api/v1/recordings \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@recording.ogg" \
  -F "recorded_at=2026-03-22T15:00:00Z"

# List today's recordings
curl -k https://localhost:8080/api/v1/recordings?date=2026-03-22 \
  -H "X-API-Key: YOUR_KEY"

# Delete a recording
curl -k -X DELETE https://localhost:8080/api/v1/recordings/RECORDING_UUID \
  -H "X-API-Key: YOUR_KEY"
```
