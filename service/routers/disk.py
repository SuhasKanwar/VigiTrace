"""On-disk forensic analysis endpoints.

The server passes a path to an image it can already reach; nothing is uploaded
through here. That matches how the work is actually done - image to a
write-blocked target, then analyse in place - and avoids moving terabytes
through HTTP.
"""

from fastapi import APIRouter
from pydantic import Field

from models.device import VigiTraceModel
from models.disk import VolumeEvidence
from services.disk_analysis import DiskAnalysisError, analyse_image, identify_image
from utils.logger import logger

router = APIRouter(prefix="/api/disk", tags=["Disk forensics"])


class ImageTarget(VigiTraceModel):
    path: str = Field(description="Absolute path to an acquired image this service can read.")


class AnalyseRequest(VigiTraceModel):
    path: str
    carve: bool = Field(default=True, description="Extract playable segments from the blocks found.")
    carve_limit: int = Field(default=8, ge=1, le=200)
    compute_hash: bool = Field(default=True, description="SHA-256 the whole image before deriving from it.")
    verify_decode: bool = Field(
        default=True,
        description="Hand each carved segment to an external decoder. A carve that "
        "parses but will not play is not recovered evidence.",
    )


class AnalyseResponse(VigiTraceModel):
    success: bool
    message: str
    evidence: VolumeEvidence | None = None
    error: dict | None = None


@router.post("/identify")
def identify(target: ImageTarget) -> dict:
    """Say which filesystem an image carries, without a full analysis."""
    try:
        result = identify_image(target.path)
    except DiskAnalysisError as exc:
        return {
            "success": False,
            "message": exc.message,
            "error": {"code": exc.code.value, "detail": exc.detail},
        }
    known = result["vendor"] != "UNKNOWN"
    return {
        "success": known,
        "message": (
            f"Image carries a {result['vendor']} volume."
            if known
            else "No supported recorder filesystem signature was found in this image."
        ),
        "data": result,
    }


@router.post("/analyse", response_model=AnalyseResponse)
def analyse(request: AnalyseRequest) -> AnalyseResponse:
    """Parse a volume, sweep for unreferenced footage, and carve what is found."""
    logger.info("Disk analysis requested for %s", request.path)
    try:
        evidence = analyse_image(
            request.path,
            carve=request.carve,
            carve_limit=request.carve_limit,
            compute_hash=request.compute_hash,
            verify_decode=request.verify_decode,
        )
    except DiskAnalysisError as exc:
        return AnalyseResponse(
            success=False,
            message=exc.message,
            error={"code": exc.code.value, "detail": exc.detail},
        )

    return AnalyseResponse(
        success=True,
        message=(
            f"Parsed {len(evidence.recordings)} indexed recording(s), "
            f"{len(evidence.recovered_blocks)} unreferenced block(s), "
            f"and carved {len(evidence.artifacts)} artifact(s)."
        ),
        evidence=evidence,
    )
