"""Recording index, normalization and acquisition endpoints."""

from fastapi import APIRouter

from models.probe import (
    AcquisitionRequest,
    AcquisitionResponse,
    RecordingSearchRequest,
    RecordingSearchResponse,
)
from services.normalization import normalize_index, summarize_coverage
from services.probe import acquire_recording, identify_device, search_recordings
from utils.logger import logger

router = APIRouter(prefix="/api/recordings", tags=["Recordings"])


@router.post("/search", response_model=RecordingSearchResponse)
def search(request: RecordingSearchRequest) -> RecordingSearchResponse:
    """Search the recorder's own recording index."""
    logger.info(
        "Recording search on %s for %s channel(s)",
        request.target.host,
        len(request.channel_ids) or "all",
    )
    return search_recordings(request)


@router.post("/timeline")
def timeline(request: RecordingSearchRequest) -> dict:
    """Search, then normalize onto a single clock-corrected timeline.

    Identification runs first because the clock-drift measurement it produces
    is what makes the normalized timestamps meaningful.
    """
    identified = identify_device(request.target)
    if not identified.success or identified.device is None:
        return {
            "success": False,
            "message": "Could not identify the recorder, so its clock offset is unknown.",
            "error": identified.error.model_dump() if identified.error else None,
        }

    found = search_recordings(request)
    if not found.success or found.index is None:
        return {
            "success": False,
            "message": found.message,
            "error": found.error.model_dump() if found.error else None,
        }

    return {
        "success": True,
        "message": f"Normalized {len(found.index.recordings)} segment(s).",
        "data": {
            "timeline": normalize_index(found.index, identified.device),
            "coverage": summarize_coverage(found.index),
        },
    }


@router.post("/acquire", response_model=AcquisitionResponse)
def acquire(request: AcquisitionRequest) -> AcquisitionResponse:
    """Export one segment and record its integrity hashes."""
    logger.info(
        "Acquisition requested for %s channel %s", request.target.host, request.channel_id
    )
    return acquire_recording(request)
