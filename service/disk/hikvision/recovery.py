"""Find footage the recorder's own index does not account for.

The index is a claim about what the volume holds, not the whole truth. A
recording that was deleted, or that was never indexed because the recorder lost
power mid-write, leaves its data blocks intact while the entry pointing at them
is gone. Trusting the index alone would report that footage as absent.

So the data area is swept independently and every block carrying video is
compared against what the index claims. What the sweep finds is reported as
*unreferenced*, never as "deleted": this parser can see that no entry points at
a block, which is not the same as establishing that someone removed one.
"""

from dataclasses import dataclass
from datetime import datetime

from disk.hikvision import layout as L
from disk.hikvision.reader import BlockEntry, HikvisionVolume


@dataclass(frozen=True)
class UnreferencedBlock:
    """A data block holding video that no index entry points at."""

    block_index: int
    data_offset: int
    pack_headers: int
    keyframe_boundaries: int
    #: Recovered from the block's own IDR table when it survived, which is the
    #: only timestamp available once the index entry is gone.
    idr_channel: int | None
    idr_timestamp: datetime | None

    @property
    def confidence(self) -> str:
        """How strongly this looks like real recovered footage.

        A block with an intact IDR table naming a channel is far stronger than
        one recognised only by stream signatures, and a report should not put
        the two on equal footing.
        """
        if self.idr_channel is not None and self.keyframe_boundaries > 0:
            return "STRONG"
        if self.keyframe_boundaries > 0 or self.pack_headers > 2:
            return "PROBABLE"
        return "WEAK"


@dataclass(frozen=True)
class TimelineGap:
    """A stretch of time with no indexed footage on a channel."""

    channel: int
    start: datetime
    end: datetime

    @property
    def duration_seconds(self) -> float:
        return max((self.end - self.start).total_seconds(), 0.0)


def _read_idr_table(block: bytes) -> tuple[int | None, datetime | None]:
    """Recover channel and time from the block's own keyframe index."""
    position = block.rfind(L.IDR_SIGNATURE)
    if position < 0 or position + L.IDR_RECORD_SIZE > len(block):
        return None, None
    import struct

    try:
        channel = struct.unpack_from("<H", block, position + 8)[0]
        stamp = struct.unpack_from("<I", block, position + 12)[0]
    except struct.error:
        return None, None

    when: datetime | None = None
    if stamp not in (0, L.UNFINALISED_TIME):
        from datetime import timezone

        try:
            when = datetime.fromtimestamp(stamp, timezone.utc)
        except (OverflowError, OSError, ValueError):
            when = None
    return (channel if 0 < channel < 1024 else None), when


def scan_unreferenced_blocks(
    volume: HikvisionVolume, entries: list[BlockEntry] | None = None
) -> list[UnreferencedBlock]:
    """Sweep the data area for video blocks the index does not reference."""
    indexed = {entry.data_offset for entry in (entries if entries is not None else volume.entries())}
    master = volume.master
    found: list[UnreferencedBlock] = []

    for index in range(master.data_block_count):
        offset = master.data_area_offset + index * master.data_block_size
        if offset >= volume.size or offset in indexed:
            continue

        block = bytes(volume.read_block(offset))
        packs = block.count(L.PS_PACK_HEADER)
        if packs == 0:
            continue

        aligned = 0
        cursor = 0
        while True:
            cursor = block.find(L.PS_PACK_HEADER, cursor)
            if cursor < 0:
                break
            if L.PS_PROGRAM_STREAM_MAP in block[cursor : cursor + 64]:
                aligned += 1
            cursor += len(L.PS_PACK_HEADER)

        channel, when = _read_idr_table(block)
        found.append(
            UnreferencedBlock(
                block_index=index,
                data_offset=offset,
                pack_headers=packs,
                keyframe_boundaries=aligned,
                idr_channel=channel,
                idr_timestamp=when,
            )
        )
    return found


def find_timeline_gaps(entries: list[BlockEntry]) -> list[TimelineGap]:
    """Intervals between consecutive indexed recordings on each channel.

    A gap is where deleted or unindexed footage would sit, so it is the place to
    aim a block sweep rather than a conclusion in itself.
    """
    gaps: list[TimelineGap] = []
    by_channel: dict[int, list[BlockEntry]] = {}
    for entry in entries:
        if entry.start and entry.end and not entry.unfinalised:
            by_channel.setdefault(entry.channel, []).append(entry)

    for channel, channel_entries in by_channel.items():
        ordered = sorted(channel_entries, key=lambda e: e.start)  # type: ignore[arg-type]
        for earlier, later in zip(ordered, ordered[1:]):
            if later.start and earlier.end and later.start > earlier.end:
                gaps.append(TimelineGap(channel=channel, start=earlier.end, end=later.start))
    return gaps
