"""Evidence integrity verification.

Acquired media lives on this service's filesystem, so re-verification has to
happen here. The server records the digest at acquisition time and calls this
endpoint later to confirm the stored artifact still matches it.
"""

from fastapi import APIRouter
from pydantic import Field

from models.device import VigiTraceModel
from services.integrity import verify_file
from utils.logger import logger

router = APIRouter(prefix="/api/integrity", tags=["Integrity"])


class ArtifactCheck(VigiTraceModel):
    recording_id: str
    stored_path: str
    expected_sha256: str


class VerifyRequest(VigiTraceModel):
    artifacts: list[ArtifactCheck] = Field(default_factory=list)


@router.post("/verify")
def verify(request: VerifyRequest) -> dict:
    """Re-hash stored artifacts and compare against their recorded digests.

    A missing or altered file is reported per-artifact rather than failing the
    whole batch, so one bad artifact does not hide the state of the others.
    """
    results = []
    for artifact in request.artifacts:
        outcome = verify_file(artifact.stored_path, artifact.expected_sha256)
        outcome["recording_id"] = artifact.recording_id
        results.append(outcome)
        if not outcome["verified"]:
            logger.warning(
                "Integrity check failed for %s: %s", artifact.recording_id, outcome["reason"]
            )

    verified = sum(1 for r in results if r["verified"])
    failed = len(results) - verified
    return {
        "success": failed == 0,
        "message": (
            f"Verified {verified} of {len(results)} artifact(s)."
            if failed == 0
            else f"{failed} of {len(results)} artifact(s) failed integrity verification."
        ),
        "data": {"results": results, "verified": verified, "failed": failed},
    }
