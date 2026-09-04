"""Investigator-assistance analysis.

The findings here are deterministic and rule-based, so this endpoint is fully
functional with no AI credentials configured. When NVIDIA_API_KEY is present the
same findings are additionally narrated by a language model through NVIDIA NIM;
when it is absent the endpoint says so plainly instead of failing or silently
returning less.

Nothing here replaces source evidence. Findings are review prompts for a human
analyst, and each carries the observation it was derived from.
"""

import time
from datetime import datetime, timezone
from typing import Any

import requests
from fastapi import APIRouter
from pydantic import Field

from config import AI_ENABLED, NVIDIA_API_KEY, NVIDIA_BASE_URL, NVIDIA_MODEL
from models.device import StandardizedDevice, VigiTraceModel
from models.recording import RecordingIndex
from services.normalization import normalize_index, summarize_coverage
from utils.logger import logger

router = APIRouter(prefix="/api/analysis", tags=["Analysis"])

#: NIM exposes an OpenAI-compatible chat-completions surface.
CHAT_COMPLETIONS_PATH = "/chat/completions"
#: Narration is an enhancement, so it is given a bounded slice of the request
#: rather than being allowed to hold the findings hostage. NIM has been observed
#: to hang or return 5xx under throttling, which is precisely when the
#: deterministic findings still need to come back promptly.
NARRATION_TIMEOUT_SECONDS = 20
NARRATION_ATTEMPTS = 2
NARRATION_BACKOFF_SECONDS = 1.5

#: A recorder more than five minutes off the reference clock materially affects
#: any cross-camera correlation drawn from its timestamps.
DRIFT_WARNING_SECONDS = 300
DRIFT_CRITICAL_SECONDS = 3600
#: Free space below this fraction means the ring buffer is close to overwriting.
LOW_FREE_SPACE_RATIO = 0.05


class Finding(VigiTraceModel):
    severity: str = Field(description="INFO, WARNING or CRITICAL.")
    category: str
    title: str
    detail: str
    observation: str = Field(description="The measured value the finding rests on.")


class AnalysisRequest(VigiTraceModel):
    device: StandardizedDevice
    index: RecordingIndex | None = None
    narrate: bool = Field(
        default=True, description="Add an LLM narrative when credentials are configured."
    )


def _clock_findings(device: StandardizedDevice) -> list[Finding]:
    findings: list[Finding] = []
    drift = device.clock.drift_seconds

    if drift is None:
        findings.append(
            Finding(
                severity="WARNING",
                category="clock",
                title="Recorder clock offset could not be measured",
                detail=(
                    "Timestamps from this recorder cannot be placed on a reference "
                    "timeline with a known error bound."
                ),
                observation="No device time was returned during identification.",
            )
        )
        return findings

    magnitude = abs(drift)
    if magnitude >= DRIFT_CRITICAL_SECONDS:
        severity = "CRITICAL"
    elif magnitude >= DRIFT_WARNING_SECONDS:
        severity = "WARNING"
    else:
        severity = "INFO"

    direction = "ahead of" if drift > 0 else "behind"
    findings.append(
        Finding(
            severity=severity,
            category="clock",
            title=f"Recorder clock is {magnitude:.0f}s {direction} the reference clock",
            detail=(
                "All recorded timestamps carry this offset. Normalization applies it, "
                "but the recorder's own exports and on-screen burn-in will not."
            ),
            observation=f"drift_seconds = {drift:.2f}",
        )
    )

    if device.clock.ntp_enabled is False:
        findings.append(
            Finding(
                severity="WARNING",
                category="clock",
                title="NTP synchronisation is disabled",
                detail="Clock drift will accumulate without correction, widening timestamp error over time.",
                observation="ntp_enabled = false",
            )
        )
    return findings


def _storage_findings(device: StandardizedDevice) -> list[Finding]:
    findings: list[Finding] = []
    for disk in device.storage:
        status = (disk.status or "").lower()
        if status in ("error", "smartfailed", "unformatted", "mismatch", "offline", "notexist"):
            findings.append(
                Finding(
                    severity="CRITICAL",
                    category="storage",
                    title=f"Disk {disk.storage_id} reports status '{disk.status}'",
                    detail=(
                        "Recordings on a failing or unmounted disk may be unreadable or "
                        "incomplete. Image this disk before any further interaction."
                    ),
                    observation=f"status = {disk.status}",
                )
            )
        if disk.capacity_bytes and disk.free_bytes is not None:
            ratio = disk.free_bytes / disk.capacity_bytes
            if ratio < LOW_FREE_SPACE_RATIO:
                findings.append(
                    Finding(
                        severity="WARNING",
                        category="storage",
                        title=f"Disk {disk.storage_id} is {(1 - ratio) * 100:.1f}% full",
                        detail=(
                            "The recorder is overwriting its oldest footage. Every hour of "
                            "delay costs the earliest surviving recordings."
                        ),
                        observation=f"free {disk.free_bytes} of {disk.capacity_bytes} bytes",
                    )
                )
    if not device.storage:
        findings.append(
            Finding(
                severity="WARNING",
                category="storage",
                title="No storage devices were enumerated",
                detail="Retention and overwrite pressure cannot be assessed.",
                observation="storage list is empty",
            )
        )
    return findings


def _index_findings(device: StandardizedDevice, index: RecordingIndex | None) -> list[Finding]:
    if index is None:
        return []

    findings: list[Finding] = []
    if index.truncated:
        findings.append(
            Finding(
                severity="INFO",
                category="index",
                title="Recording index was truncated",
                detail="More segments exist than were returned. Narrow the window to enumerate them all.",
                observation=f"{len(index.recordings)} segment(s) returned with truncation flagged",
            )
        )

    for channel_id in sorted({r.channel_id for r in index.recordings}):
        gaps = index.gaps(channel_id)
        if not gaps:
            continue
        longest = max(gaps, key=lambda g: g.duration_seconds)
        findings.append(
            Finding(
                severity="WARNING",
                category="index",
                title=f"Channel {channel_id} has {len(gaps)} gap(s) in its recording index",
                detail=(
                    "Gaps are where deleted, unindexed or never-recorded footage would sit. "
                    "They are candidates for carving from the disk image, not proof of deletion."
                ),
                observation=(
                    f"longest gap {longest.duration_seconds:.0f}s "
                    f"from {longest.start.isoformat()} to {longest.end.isoformat()}"
                ),
            )
        )

    overwritten = [r for r in index.recordings if (r.overwrite_count or 0) > 0]
    if overwritten:
        findings.append(
            Finding(
                severity="INFO",
                category="index",
                title=f"{len(overwritten)} segment(s) sit in regions the recorder has reused",
                detail="Overwritten regions reduce the chance of recovering prior footage from those blocks.",
                observation=f"max overwrite count {max(r.overwrite_count or 0 for r in overwritten)}",
            )
        )
    return findings


def _identity_findings(device: StandardizedDevice) -> list[Finding]:
    findings: list[Finding] = []
    if device.identity.confidence.value != "CONFIRMED":
        findings.append(
            Finding(
                severity="INFO",
                category="identity",
                title=f"Vendor attribution is {device.identity.confidence.value}, not confirmed",
                detail=(
                    "This vendor is identified by fingerprint rather than by a vendor-published "
                    "protocol. State the basis for attribution in any report."
                ),
                observation=f"vendor={device.identity.vendor.value}, family={device.identity.family.value}",
            )
        )
    if not device.identity.serial_number:
        findings.append(
            Finding(
                severity="WARNING",
                category="identity",
                title="Recorder reported no serial number",
                detail="Device identification in the chain of custody will rest on weaker identifiers.",
                observation="serial_number is absent from the vendor payload",
            )
        )
    return findings


def _narrate(findings: list[Finding], device: StandardizedDevice) -> dict[str, Any]:
    """Optional LLM narration. Never raises into the response path."""
    if not AI_ENABLED or not NVIDIA_API_KEY:
        return {
            "available": False,
            "reason": (
                "No AI credentials configured. Set NVIDIA_API_KEY in the service "
                "environment to enable narrative summaries. All findings above are "
                "produced deterministically and are unaffected."
            ),
        }

    bullet_list = "\n".join(f"- [{f.severity}] {f.title}: {f.observation}" for f in findings)
    prompt = (
        "You are assisting a digital forensics investigator reviewing a CCTV recorder. "
        "Summarise these machine-generated findings in plain English for a case note. "
        "Do not invent facts beyond the findings. Do not assert that evidence was tampered "
        "with; describe only what was observed.\n\n"
        f"Device: {device.identity.vendor.value} {device.identity.model_name or 'unknown model'}\n"
        f"Findings:\n{bullet_list}"
    )

    url = f"{NVIDIA_BASE_URL.rstrip('/')}{CHAT_COMPLETIONS_PATH}"
    payload = {
        "model": NVIDIA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 700,
    }
    headers = {
        "Authorization": f"Bearer {NVIDIA_API_KEY}",
        "Content-Type": "application/json",
    }

    last_transient = "the request did not complete"
    for attempt in range(1, NARRATION_ATTEMPTS + 1):
        try:
            response = requests.post(
                url, headers=headers, json=payload, timeout=NARRATION_TIMEOUT_SECONDS
            )
        except Exception as exc:
            # Deliberately broad: narration is an enhancement and must degrade,
            # never raise into the analysis response. Timeouts and connection
            # resets are the throttling signature; one retry is worth it, an
            # indefinite wait is not.
            last_transient = str(exc)
            logger.warning("NIM narration attempt %s failed: %s", attempt, exc)
            if attempt < NARRATION_ATTEMPTS:
                time.sleep(NARRATION_BACKOFF_SECONDS)
                continue
            return {
                "available": False,
                "reason": (
                    f"NVIDIA NIM did not respond within {NARRATION_TIMEOUT_SECONDS}s "
                    f"across {NARRATION_ATTEMPTS} attempt(s). Findings above are "
                    f"unaffected. Last error: {last_transient}"
                ),
            }

        if response.status_code >= 500:
            last_transient = f"HTTP {response.status_code}"
            logger.warning("NIM narration attempt %s returned %s", attempt, response.status_code)
            if attempt < NARRATION_ATTEMPTS:
                time.sleep(NARRATION_BACKOFF_SECONDS)
                continue
            return {
                "available": False,
                "reason": (
                    f"NVIDIA NIM returned {last_transient} on every attempt, which usually "
                    "means the endpoint is throttling or temporarily unavailable. "
                    "Findings above are unaffected."
                ),
            }
        break

    try:
        # NIM entitlements are per-account: a model can be listed by /v1/models
        # and still 404 for a given key. Say which model was refused, because
        # "not found" alone sends people looking for a network fault.
        if response.status_code == 404:
            return {
                "available": False,
                "reason": (
                    f"The configured model '{NVIDIA_MODEL}' is not available to this "
                    "NVIDIA API key. Set NVIDIA_MODEL to a model your account is "
                    "entitled to; listing /v1/models is not proof of access."
                ),
            }
        if response.status_code in (401, 403):
            return {
                "available": False,
                "reason": "NVIDIA rejected the configured API key.",
            }
        response.raise_for_status()

        payload = response.json()
        choices = payload.get("choices") or []
        text = (choices[0].get("message", {}).get("content") or "").strip() if choices else ""
        if not text:
            return {
                "available": False,
                "reason": f"Model '{NVIDIA_MODEL}' returned an empty narration.",
            }
        return {
            "available": True,
            "provider": "NVIDIA NIM",
            "model": NVIDIA_MODEL,
            "summary": text,
            "usage": payload.get("usage"),
        }
    except Exception as exc:
        # Narration is an enhancement; its failure must not fail the analysis.
        logger.warning("LLM narration unavailable: %s", exc)
        return {"available": False, "reason": f"Narration failed: {exc}"}


@router.get("/health")
def analysis_health() -> dict:
    """Report whether optional AI enrichment is configured."""
    return {
        "success": True,
        "message": "Analysis module is available.",
        "data": {
            "deterministic_findings": True,
            "ai_narration_configured": AI_ENABLED,
            "provider": "NVIDIA NIM" if AI_ENABLED else None,
            "model": NVIDIA_MODEL if AI_ENABLED else None,
        },
    }


@router.post("/summary")
def summarize(request: AnalysisRequest) -> dict:
    """Produce reviewable findings for one identified device."""
    device = request.device
    findings = (
        _identity_findings(device)
        + _clock_findings(device)
        + _storage_findings(device)
        + _index_findings(device, request.index)
    )
    order = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    findings.sort(key=lambda f: order.get(f.severity, 3))

    data: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "device": {
            "vendor": device.identity.vendor.value,
            "family": device.identity.family.value,
            "model": device.identity.model_name,
            "serial_number": device.identity.serial_number,
        },
        "findings": [f.model_dump() for f in findings],
        "counts": {
            severity: sum(1 for f in findings if f.severity == severity)
            for severity in ("CRITICAL", "WARNING", "INFO")
        },
        "evidence_digest": device.evidence.combined_sha256,
    }
    if request.index is not None:
        data["timeline"] = normalize_index(request.index, device)
        data["coverage"] = summarize_coverage(request.index)
    if request.narrate:
        data["narrative"] = _narrate(findings, device)

    return {
        "success": True,
        "message": f"Produced {len(findings)} finding(s).",
        "data": data,
    }
