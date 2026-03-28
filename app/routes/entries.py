"""Diary entry endpoints."""

import asyncio
import uuid
import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, and_, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import DiaryEntry, Recording
from app.compiler import compile_diary_entry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/entries", tags=["entries"])


class CompileRequest(BaseModel):
    """Request body for diary compilation."""
    date: date
    force: bool = False


@router.get("")
async def list_entries(
    date: date | None = Query(None, description="Filter by specific date (YYYY-MM-DD)"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List diary entries, optionally filtered by date.

    If `date` is provided, returns the single entry for that date (or empty).
    Otherwise, returns paginated entries sorted newest-first.

    Args:
        date: Optional date filter.
        limit: Max entries to return.
        offset: Pagination offset.
        db: Database session.

    Returns:
        Dict with entries list and total count.
    """
    if date:
        stmt = select(DiaryEntry).where(DiaryEntry.entry_date == date)
        result = await db.execute(stmt)
        entry = result.scalar_one_or_none()
        return {
            "entries": [_serialize(entry)] if entry else [],
            "total": 1 if entry else 0,
        }

    # Count total
    count_stmt = select(DiaryEntry)
    count_result = await db.execute(count_stmt)
    total = len(count_result.scalars().all())

    # Fetch page
    stmt = (
        select(DiaryEntry)
        .order_by(DiaryEntry.entry_date.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    entries = result.scalars().all()

    return {
        "entries": [_serialize(e) for e in entries],
        "total": total,
    }


@router.post("/compile", status_code=202)
async def compile_entry(body: CompileRequest) -> dict:
    """Trigger diary compilation for a specific date.

    Runs the compiler pipeline: transcribe recordings, compile into entry.
    This may take a while depending on the number/size of recordings.

    Args:
        body: Request body with the target date.

    Returns:
        The compiled diary entry, or an error message.
    """
    logger.info("Manual compilation triggered for %s (force=%s)", body.date, body.force)

    try:
        entry = await compile_diary_entry(body.date, force=body.force)
    except Exception as e:
        logger.error("Compilation failed for %s: %s", body.date, e)
        raise HTTPException(status_code=500, detail=f"Compilation failed: {str(e)}")

    if entry is None:
        raise HTTPException(
            status_code=409,
            detail="No uncompiled recordings found for this date, or entry already exists.",
        )

    return _serialize(entry)


@router.delete("/{entry_id}", status_code=204)
async def delete_entry(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a diary entry and un-mark its source recordings.

    Args:
        entry_id: UUID of the diary entry to delete.
        db: Database session.
    """
    stmt = select(DiaryEntry).where(DiaryEntry.id == entry_id)
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()

    if not entry:
        raise HTTPException(status_code=404, detail="Diary entry not found.")

    # Un-mark recordings for this date as compiled
    rec_stmt = select(Recording).where(
        and_(
            cast(Recording.recorded_at, Date) == entry.entry_date,
            Recording.compiled == True,  # noqa: E712
        )
    )
    rec_result = await db.execute(rec_stmt)
    recordings = rec_result.scalars().all()
    for rec in recordings:
        rec.compiled = False

    await db.delete(entry)
    await db.commit()

    logger.info(
        "Deleted diary entry %s for %s, un-compiled %d recordings",
        entry_id, entry.entry_date, len(recordings),
    )


def _serialize(entry: DiaryEntry) -> dict:
    """Convert a DiaryEntry model to a JSON-safe dict."""
    return {
        "id": str(entry.id),
        "entry_date": entry.entry_date.isoformat(),
        "content": entry.content,
        "recording_count": entry.recording_count,
        "total_duration_seconds": entry.total_duration_seconds,
        "model_used": entry.model_used,
        "compiled_at": entry.compiled_at.isoformat() if entry.compiled_at else None,
    }
