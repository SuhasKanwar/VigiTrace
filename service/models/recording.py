"""Standardized recording-index and acquisition models."""

from datetime import datetime

from pydantic import Field

from models.common import ProbeMethod
from models.device import VigiTraceModel


class TimeSpan(VigiTraceModel):
    start: datetime
    end: datetime

    @property
    def duration_seconds(self) -> float:
        return max((self.end - self.start).total_seconds(), 0.0)


class StandardizedRecording(VigiTraceModel):
    """One recording segment as reported by the recorder's own index.

    ``playback_uri`` and ``file_path`` are vendor-native locators kept verbatim
    so acquisition can round-trip them without re-deriving.
    """

    recording_id: str
    channel_id: str = Field(
        description="Normalized channel identifier, matching ChannelInfo.channel_id."
    )
    track_id: str | None = Field(
        default=None,
        description="Vendor-native locator the segment was indexed under "
        "(Hikvision reports track 101 for channel 1 main stream).",
    )
    span: TimeSpan
    codec: str | None = None
    size_bytes: int | None = None
    playback_uri: str | None = None
    file_path: str | None = None
    event_type: str | None = None
    record_trigger: str | None = Field(
        default=None, description="Timing, Manual, Marker, Event, Mosaic, Cutout."
    )
    overwrite_count: int | None = Field(
        default=None,
        description="Dahua reports how many times the region was overwritten; "
        "relevant to retention and wipe reasoning.",
    )
    source_method: ProbeMethod
    raw: dict = Field(default_factory=dict)


class RecordingIndex(VigiTraceModel):
    """The result of searching a recorder's recording index."""

    recordings: list[StandardizedRecording] = Field(default_factory=list)
    searched_span: TimeSpan | None = None
    channels_searched: list[str] = Field(default_factory=list)
    truncated: bool = Field(
        default=False,
        description="True when the recorder capped results and more exist.",
    )
    warnings: list[str] = Field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(r.size_bytes or 0 for r in self.recordings)

    def gaps(self, channel_id: str) -> list[TimeSpan]:
        """Unindexed intervals between consecutive segments on one channel.

        Gaps are where deleted or unindexed footage would live, so they are the
        starting point for recovery rather than an afterthought.
        """
        segments = sorted(
            (r for r in self.recordings if r.channel_id == channel_id),
            key=lambda r: r.span.start,
        )
        found: list[TimeSpan] = []
        for earlier, later in zip(segments, segments[1:]):
            if later.span.start > earlier.span.end:
                found.append(TimeSpan(start=earlier.span.end, end=later.span.start))
        return found


class AcquisitionResult(VigiTraceModel):
    """A completed controlled export, with integrity material attached."""

    recording_id: str
    channel_id: str
    span: TimeSpan
    stored_path: str
    size_bytes: int
    md5: str
    sha256: str
    container: str | None = None
    acquired_at: datetime
    duration_ms: int
    source_uri: str | None = None
    warnings: list[str] = Field(default_factory=list)
