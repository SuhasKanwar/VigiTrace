"""Device detection and identification endpoints.

These are called by the VigiTrace server, never by a browser: the server is the
only client of this service and owns all persistence.
"""

from fastapi import APIRouter

from models.probe import DeviceTarget, ProbeResponse
from services.probe import detect_device, identify_device
from utils.logger import logger
from vendors.registry import supported_vendors

router = APIRouter(prefix="/api/devices", tags=["Devices"])


@router.get("/vendors")
def list_vendors() -> dict:
    """Report the adapter registry, including each adapter's evidential basis."""
    vendors = supported_vendors()
    return {
        "success": True,
        "message": f"{len(vendors)} vendor adapter(s) registered.",
        "data": {"vendors": vendors},
    }


@router.post("/detect", response_model=ProbeResponse)
def detect(target: DeviceTarget) -> ProbeResponse:
    """Fingerprint a recorder without authenticating."""
    logger.info("Detect requested for %s:%s", target.host, target.http_port)
    return detect_device(target)


@router.post("/identify", response_model=ProbeResponse)
def identify(target: DeviceTarget) -> ProbeResponse:
    """Produce the full standardized device object for a recorder."""
    logger.info("Identify requested for %s:%s", target.host, target.http_port)
    return identify_device(target)


@router.post("/enumerate", response_model=ProbeResponse)
def enumerate_device(target: DeviceTarget) -> ProbeResponse:
    """Refresh channel and storage state for an already-identified recorder.

    Disks fill and fail between probes, so this exists to re-read that state
    without repeating a full identification.
    """
    logger.info("Enumerate requested for %s:%s", target.host, target.http_port)
    return identify_device(target)
