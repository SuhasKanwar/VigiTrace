"""Orchestrate on-disk analysis of an acquired recorder volume.

The image is treated as evidence: opened read-only, hashed before anything is
derived from it, and never written to. Carved artifacts go to a separate
directory so derived material is never mixed with the source.
"""

import hashlib
import os
from datetime import datetime, timezone

from config import EVIDENCE_DIR
from models.common import ErrorCode, Vendor, VendorFamily
from models.disk import (
    CarvedArtifact,
    IndexedRecording,
    RecordedGap,
    RecoveredBlock,
    VolumeEvidence,
    VolumeIdentity,
)
from disk.hikvision.carve import carve_block, verify_with_decoder, write_segment
from disk.hikvision.reader import DiskFormatError, HikvisionVolume
from disk.hikvision.recovery import find_timeline_gaps, scan_unreferenced_blocks
from utils.logger import logger

HASH_CHUNK = 1024 * 1024
#: Hashing a multi-terabyte image is minutes of I/O, so it is opt-in per call
#: rather than forced on an operator who only wants to see what is on the disk.
HASH_LIMIT_BYTES = 4 * 1024 * 1024 * 1024


class DiskAnalysisError(Exception):
    def __init__(self, code: ErrorCode, message: str, detail: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


def hash_image(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(HASH_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def identify_image(path: str) -> dict:
    """Say which parser owns an image, without committing to a full analysis."""
    if not os.path.isfile(path):
        raise DiskAnalysisError(
            ErrorCode.NOT_CONFIGURED,
            "No readable image at that path.",
            f"{path} is not a file this service can open.",
        )
    if HikvisionVolume.looks_like_hikvision(path):
        return {"vendor": Vendor.HIKVISION.value, "family": VendorFamily.HIKVISION.value}
    return {"vendor": Vendor.UNKNOWN.value, "family": VendorFamily.UNKNOWN.value}


def analyse_image(
    path: str,
    *,
    carve: bool = True,
    carve_limit: int = 8,
    compute_hash: bool = True,
    verify_decode: bool = True,
) -> VolumeEvidence:
    """Parse a volume, sweep for unreferenced footage, and optionally carve it."""
    if not os.path.isfile(path):
        raise DiskAnalysisError(
            ErrorCode.NOT_CONFIGURED,
            "No readable image at that path.",
            f"{path} is not a file this service can open.",
        )

    size = os.path.getsize(path)
    warnings: list[str] = []

    image_hash = None
    if compute_hash:
        if size > HASH_LIMIT_BYTES:
            warnings.append(
                f"Image is {size} bytes; whole-image hashing was skipped to keep this "
                "call responsive. Hash it out of band before relying on it as evidence."
            )
        else:
            image_hash = hash_image(path)

    try:
        volume = HikvisionVolume(path)
    except DiskFormatError as exc:
        raise DiskAnalysisError(ErrorCode.UNSUPPORTED_VENDOR, exc.message, exc.detail)

    with volume:
        master = volume.master
        entries = volume.entries()

        identity = VolumeIdentity(
            vendor=Vendor.HIKVISION,
            family=VendorFamily.HIKVISION,
            format_version=master.version,
            total_capacity_bytes=master.total_capacity_bytes,
            data_block_size=master.data_block_size,
            data_block_count=master.data_block_count,
            initialised_at=master.initialised_at,
        )

        recordings = [
            IndexedRecording(
                channel=e.channel,
                start=e.start,
                end=e.end,
                duration_seconds=e.duration_seconds,
                data_offset=e.data_offset,
                unfinalised=e.unfinalised,
            )
            for e in entries
        ]
        if any(e.unfinalised for e in entries):
            warnings.append(
                "At least one block was still being written when the volume was imaged. "
                "Those blocks carry the most recent footage and are readable despite "
                "their placeholder timestamp."
            )

        unreferenced = scan_unreferenced_blocks(volume, entries)
        recovered = [
            RecoveredBlock(
                block_index=b.block_index,
                data_offset=b.data_offset,
                pack_headers=b.pack_headers,
                keyframe_boundaries=b.keyframe_boundaries,
                channel=b.idr_channel,
                timestamp=b.idr_timestamp,
                confidence=b.confidence,
            )
            for b in unreferenced
        ]
        if recovered:
            warnings.append(
                f"{len(recovered)} block(s) hold video that the recorder's index does not "
                "reference. That is what was observed; it does not by itself establish "
                "that an entry was deleted."
            )

        gaps = [
            RecordedGap(
                channel=g.channel, start=g.start, end=g.end, duration_seconds=g.duration_seconds
            )
            for g in find_timeline_gaps(entries)
        ]

        artifacts: list[CarvedArtifact] = []
        if carve:
            artifacts = _carve(volume, entries, unreferenced, path, carve_limit, verify_decode, warnings)

    return VolumeEvidence(
        image_path=path,
        image_size_bytes=size,
        image_sha256=image_hash,
        identity=identity,
        recordings=recordings,
        recovered_blocks=recovered,
        gaps=gaps,
        artifacts=artifacts,
        warnings=warnings,
        examined_at=datetime.now(timezone.utc),
    )


def _carve(volume, entries, unreferenced, image_path, limit, verify_decode, warnings):
    """Extract segments, keeping derived output away from the source image."""
    out_dir = os.path.join(EVIDENCE_DIR, "carved", os.path.basename(image_path).replace(os.sep, "_"))
    os.makedirs(out_dir, exist_ok=True)

    targets = [("INDEXED", e.channel, e.data_offset) for e in entries]
    targets += [("RECOVERED", b.idr_channel or 0, b.data_offset) for b in unreferenced]

    artifacts: list[CarvedArtifact] = []
    for source, channel, offset in targets[:limit]:
        segment = carve_block(volume.read_block(offset), channel=channel, block_offset=offset)
        if segment is None:
            warnings.append(f"Block at {hex(offset)} held no recoverable program stream.")
            continue

        destination = os.path.join(out_dir, f"{source.lower()}_ch{channel}_{offset:012x}.ps")
        write_segment(segment, destination)

        artifact = CarvedArtifact(
            channel=channel,
            data_offset=offset,
            stored_path=destination,
            size_bytes=segment.length,
            sha256=segment.sha256,
            keyframe_aligned=segment.keyframe_aligned,
            source=source,
        )
        if not segment.keyframe_aligned:
            warnings.append(
                f"The carve at {hex(offset)} did not land on a keyframe boundary, so its "
                "opening frames may not decode."
            )

        if verify_decode:
            verdict = verify_with_decoder(destination)
            artifact.decoded = verdict.decoded
            artifact.codec = verdict.codec
            artifact.width = verdict.width
            artifact.height = verdict.height
            artifact.frames = verdict.frames
            artifact.decode_reason = verdict.reason
            if not verdict.decoded:
                # A carve that parses but will not play is not recovered
                # evidence, so it is reported rather than counted as a success.
                warnings.append(
                    f"The artifact carved from {hex(offset)} did not decode: {verdict.reason}"
                )

        artifacts.append(artifact)

    if len(targets) > limit:
        warnings.append(
            f"{len(targets)} block(s) were eligible for carving; the first {limit} were "
            "extracted. Raise the limit to take the rest."
        )
    logger.info("Carved %s artifact(s) from %s", len(artifacts), image_path)
    return artifacts
