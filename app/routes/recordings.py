"""Recording CRUD endpoints."""

import os
import uuid
import logging
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from sqlalchemy import select, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Recording

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/recordings", tags=["recordings"])

AUDIO_ROOT = Path("/data/audio")

# Magic bytes → (extension, MIME type)
_FORMAT_SIGNATURES: list[tuple[bytes, str, str]] = [
    (b"OggS", "ogg", "audio/ogg"),
    (b"\x1aE\xdf\xa3", "webm", "audio/webm"),  # EBML header (WebM/Matroska)
]
_DEFAULT_EXT = "ogg"
_DEFAULT_MIME = "audio/ogg"


def _detect_audio_format(data: bytes) -> tuple[str, str]:
    """Detect audio format from magic bytes.

    Args:
        data: Raw file bytes (only first 4 needed).

    Returns:
        Tuple of (file extension, MIME type).
    """
    for signature, ext, mime in _FORMAT_SIGNATURES:
        if data[:len(signature)] == signature:
            return ext, mime
    return _DEFAULT_EXT, _DEFAULT_MIME


def _detect_file_mime(path: Path) -> str:
    """Detect MIME type of an audio file on disk.

    Args:
        path: Path to the audio file.

    Returns:
        MIME type string.
    """
    try:
        with open(path, "rb") as f:
            header = f.read(4)
        _, mime = _detect_audio_format(header)
        return mime
    except OSError:
        return _DEFAULT_MIME


@router.post("", status_code=201)
async def upload_recording(
    file: UploadFile = File(...),
    recorded_at: str = Form(...),
    duration_seconds: int | None = Form(None),
    tags: str | None = Form(None),
    mood: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upload an audio recording with metadata.

    Args:
        file: Audio file (OGG/Opus expected).
        recorded_at: ISO 8601 timestamp of when the recording was made.
        duration_seconds: Duration of the recording in seconds.
        tags: Comma-separated tags.
        mood: Mood label.
        db: Database session.

    Returns:
        The created recording metadata.
    """
    try:
        recorded_dt = datetime.fromisoformat(recorded_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid recorded_at format. Use ISO 8601.")

    recording_id = uuid.uuid4()
    date_str = recorded_dt.strftime("%Y-%m-%d")
    file_dir = AUDIO_ROOT / date_str
    file_dir.mkdir(parents=True, exist_ok=True)

    # Read content and detect actual format from magic bytes
    content = await file.read()
    file_size = len(content)
    ext, mime = _detect_audio_format(content)
    file_path = file_dir / f"{recording_id}.{ext}"

    logger.info("Detected audio format: %s (%s) for upload %s", ext, mime, recording_id)
    try:
        file_path.write_bytes(content)
    except OSError as e:
        logger.error("Failed to write audio file: %s", e)
        raise HTTPException(status_code=500, detail="Failed to store audio file.")

    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None

    recording = Recording(
        id=recording_id,
        recorded_at=recorded_dt,
        duration_seconds=duration_seconds,
        file_path=str(file_path),
        file_size_bytes=file_size,
        tags=tag_list,
        mood=mood,
    )
    db.add(recording)
    await db.commit()
    await db.refresh(recording)

    logger.info("Uploaded recording %s (%d bytes)", recording_id, file_size)
    return _serialize(recording)


@router.get("")
async def list_recordings(
    date: date = Query(..., description="Date in YYYY-MM-DD format"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List all recordings for a given date.

    Args:
        date: The date to filter by.
        db: Database session.

    Returns:
        List of recording metadata dicts.
    """
    stmt = (
        select(Recording)
        .where(cast(Recording.recorded_at, Date) == date)
        .order_by(Recording.recorded_at.asc())
    )
    result = await db.execute(stmt)
    recordings = result.scalars().all()
    return [_serialize(r) for r in recordings]


@router.delete("/{recording_id}", status_code=204)
async def delete_recording(
    recording_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a recording by ID.

    Removes both the database row and the audio file on disk.

    Args:
        recording_id: UUID of the recording.
        db: Database session.
    """
    stmt = select(Recording).where(Recording.id == recording_id)
    result = await db.execute(stmt)
    recording = result.scalar_one_or_none()

    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found.")

    # Remove audio file
    audio_path = Path(recording.file_path)
    if audio_path.exists():
        try:
            audio_path.unlink()
        except OSError as e:
            logger.warning("Failed to delete audio file %s: %s", audio_path, e)

    await db.delete(recording)
    await db.commit()
    logger.info("Deleted recording %s", recording_id)


@router.get("/{recording_id}/audio")
async def stream_audio(
    recording_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Stream the audio file for a recording.

    Args:
        recording_id: UUID of the recording.
        db: Database session.

    Returns:
        The audio file as a streaming response.
    """
    stmt = select(Recording).where(Recording.id == recording_id)
    result = await db.execute(stmt)
    recording = result.scalar_one_or_none()

    if not recording:
        raise HTTPException(status_code=404, detail="Recording not found.")

    audio_path = Path(recording.file_path)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found on disk.")

    # Detect actual format from file content (handles .ogg files that are really WebM)
    mime = _detect_file_mime(audio_path)

    return FileResponse(
        path=str(audio_path),
        media_type=mime,
        filename=f"{recording_id}{audio_path.suffix}",
    )


def _serialize(recording: Recording) -> dict:
    """Convert a Recording model to a JSON-safe dict."""
    return {
        "id": str(recording.id),
        "recorded_at": recording.recorded_at.isoformat(),
        "uploaded_at": recording.uploaded_at.isoformat() if recording.uploaded_at else None,
        "duration_seconds": recording.duration_seconds,
        "file_size_bytes": recording.file_size_bytes,
        "transcript": recording.transcript,
        "tags": recording.tags,
        "mood": recording.mood,
        "compiled": recording.compiled,
    }
