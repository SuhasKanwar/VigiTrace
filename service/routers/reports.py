"""Report generation endpoint.

The server supplies the persisted material (device, index, acquisitions,
findings, custody). This service assembles it into a standardized report; it
does not read or write any of it.
"""

from fastapi import APIRouter
from pydantic import Field

from models.device import StandardizedDevice, VigiTraceModel
from models.recording import AcquisitionResult, RecordingIndex
from services.reporting import REPORT_VERSION, build_report
from utils.logger import logger

router = APIRouter(prefix="/api/reports", tags=["Reports"])


class ReportRequest(VigiTraceModel):
    device: StandardizedDevice
    index: RecordingIndex | None = None
    acquisitions: list[AcquisitionResult] = Field(default_factory=list)
    findings: list[dict] = Field(default_factory=list)
    custody: list[dict] = Field(default_factory=list)
    case_reference: str | None = None
    examiner: str | None = None


@router.post("/generate")
def generate(request: ReportRequest) -> dict:
    """Assemble a standardized case report."""
    logger.info(
        "Report requested for %s (%s acquisition(s))",
        request.device.identity.vendor.value,
        len(request.acquisitions),
    )
    report = build_report(
        device=request.device,
        index=request.index,
        acquisitions=request.acquisitions,
        findings=request.findings,
        custody=request.custody,
        case_reference=request.case_reference,
        examiner=request.examiner,
    )
    return {
        "success": True,
        "message": f"Generated report version {REPORT_VERSION}.",
        "data": {"report": report},
    }
