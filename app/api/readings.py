from fastapi import APIRouter, HTTPException, status

from app.schemas import IngestResult, ReadingsBatch

router = APIRouter(prefix="/api/v1", tags=["readings"])


@router.post("/readings", status_code=status.HTTP_201_CREATED)
async def ingest_readings(batch: ReadingsBatch) -> IngestResult:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
