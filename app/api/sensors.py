from fastapi import APIRouter, HTTPException, status

from app.schemas import SensorsResponse

router = APIRouter(prefix="/api/v1", tags=["sensors"])


@router.get("/sensors")
async def list_sensors() -> SensorsResponse:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
