"""Standardized evidence model for an acquired recorder volume.

Mirrors the network-side ``StandardizedDevice``: the same posture of keeping
provenance beside the normalized view, so a reviewer can check a conclusion
against the bytes it came from.
"""

from datetime import datetime

from pydantic import Field

from models.common import Vendor, VendorFamily
from models.device import VigiTraceModel


class VolumeIdentity(VigiTraceModel):
    vendor: Vendor = Vendor.UNKNOWN
    family: VendorFamily = VendorFamily.UNKNOWN
    #: Format generation string. Recorded because other generations exist and
    #: are undocumented, so which one this is bounds every later claim.
    format_version: str | None = None
    total_capacity_bytes: int | None = None
    data_block_size: int | None = None
    data_block_count: int | None = None
    #: When the recorder initialised the volume. A reformat resets this while
    #: leaving video carvable, so a value newer than the footage is a finding.
    initialised_at: datetime | None = None


class IndexedRecording(VigiTraceModel):
    """One recording the volume's own index accounts for."""

    channel: int
    start: datetime | None = None
    end: datetime | None = None
    duration_seconds: float | None = None
    data_offset: int
    #: The recorder was mid-write at imaging time. Still readable, and the most
    #: recent footage on the volume.
    unfinalised: bool = False


class RecoveredBlock(VigiTraceModel):
    """A block holding video that the index does not reference."""

    block_index: int
    data_offset: int
    pack_headers: int
    keyframe_boundaries: int
    channel: int | None = None
    timestamp: datetime | None = None
    #: STRONG / PROBABLE / WEAK. Never asserted as "deleted": absence of an
    #: index entry is what was observed, not why it is absent.
    confidence: str = "WEAK"


class RecordedGap(VigiTraceModel):
    channel: int
    start: datetime
    end: datetime
    duration_seconds: float


class CarvedArtifact(VigiTraceModel):
    """An extracted segment, with the decoder's independent verdict."""

    channel: int
    data_offset: int
    stored_path: str
    size_bytes: int
    sha256: str
    keyframe_aligned: bool
    source: str = Field(description="INDEXED or RECOVERED.")
    decoded: bool = False
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    frames: int | None = None
    decode_reason: str | None = None


class VolumeEvidence(VigiTraceModel):
    """Everything established about one acquired volume."""

    image_path: str
    image_size_bytes: int
    image_sha256: str | None = None
    identity: VolumeIdentity
    recordings: list[IndexedRecording] = Field(default_factory=list)
    recovered_blocks: list[RecoveredBlock] = Field(default_factory=list)
    gaps: list[RecordedGap] = Field(default_factory=list)
    artifacts: list[CarvedArtifact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    examined_at: datetime

    @property
    def channels_present(self) -> list[int]:
        return sorted({r.channel for r in self.recordings})

    @property
    def recovered_confidently(self) -> int:
        return sum(1 for b in self.recovered_blocks if b.confidence == "STRONG")
