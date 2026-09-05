"""Read a HIKVISION recorder volume from an acquired image.

The image is opened read-only and mapped, never written to. Nothing here
modifies the source: derived artifacts are returned to the caller, which keeps
the original bytes exactly as acquired.

Structure offsets come from ``layout``; see that module for their provenance.
"""

import mmap
import os
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone

from disk.hikvision import layout as L


class DiskFormatError(Exception):
    """The image is not a volume this parser understands."""

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail


@dataclass(frozen=True)
class MasterSector:
    """The volume header, as the recorder wrote it."""

    version: str
    total_capacity_bytes: int
    system_log_offset: int
    system_log_size: int
    data_area_offset: int
    data_block_size: int
    data_block_count: int
    btree_offset: int
    btree_size: int
    btree_backup_offset: int
    btree_backup_size: int
    initialised_at: datetime | None


@dataclass(frozen=True)
class BlockEntry:
    """One index entry: a channel's footage occupying one data block."""

    channel: int
    start: datetime | None
    end: datetime | None
    data_offset: int
    raw_start: int
    raw_end: int
    page_index: int
    entry_index: int

    @property
    def unfinalised(self) -> bool:
        """True when the recorder was still writing this block at imaging time.

        Such blocks carry the most recent footage on the volume and are fully
        readable, so they must not be discarded for having an absurd timestamp.
        """
        return self.raw_start == L.UNFINALISED_TIME

    @property
    def duration_seconds(self) -> float | None:
        if self.unfinalised or self.start is None or self.end is None:
            return None
        return max((self.end - self.start).total_seconds(), 0.0)


def _unix(value: int) -> datetime | None:
    if value in (0, L.UNFINALISED_TIME):
        return None
    try:
        return datetime.fromtimestamp(value, timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


class HikvisionVolume:
    """A parsed HIKVISION volume, backed by a read-only mapping."""

    def __init__(self, path: str):
        self.path = path
        self.size = os.path.getsize(path)
        self._file = open(path, "rb")
        try:
            self._map = mmap.mmap(self._file.fileno(), 0, access=mmap.ACCESS_READ)
        except ValueError as exc:  # an empty file cannot be mapped
            self._file.close()
            raise DiskFormatError("Image is empty.", str(exc))
        try:
            self.master = self._read_master()
        except Exception:
            self.close()
            raise

    def __enter__(self) -> "HikvisionVolume":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        for closable in (getattr(self, "_map", None), getattr(self, "_file", None)):
            try:
                if closable is not None:
                    closable.close()
            except Exception:
                pass

    # -- header -----------------------------------------------------------

    @staticmethod
    def looks_like_hikvision(path: str) -> bool:
        """Cheap signature probe, for deciding which parser owns an image."""
        try:
            with open(path, "rb") as handle:
                handle.seek(L.SIGNATURE_OFFSET)
                return handle.read(L.SIGNATURE_LENGTH) == L.SIGNATURE
        except OSError:
            return False

    def _u32(self, offset: int) -> int:
        return struct.unpack_from("<I", self._map, offset)[0]

    def _u64(self, offset: int) -> int:
        return struct.unpack_from("<Q", self._map, offset)[0]

    def _read_master(self) -> MasterSector:
        if self.size < L.MASTER_SECTOR_OFFSET + L.MASTER_SECTOR_SIZE:
            raise DiskFormatError("Image is too small to contain a master sector.")

        signature = self._map[L.SIGNATURE_OFFSET : L.SIGNATURE_OFFSET + L.SIGNATURE_LENGTH]
        if signature != L.SIGNATURE:
            raise DiskFormatError(
                "Image does not carry the HIKVISION volume signature.",
                f"Expected {L.SIGNATURE!r} at offset {hex(L.SIGNATURE_OFFSET)}, found {signature!r}.",
            )

        raw_version = self._map[L.VERSION_OFFSET : L.VERSION_OFFSET + L.VERSION_LENGTH]
        version = raw_version.split(b"\x00")[0]
        if version not in L.KNOWN_VERSIONS:
            # Other generations exist and are undocumented. Guessing at a layout
            # would produce confident, wrong evidence, so refuse instead.
            raise DiskFormatError(
                f"Unsupported HIKVISION format generation {version.decode('ascii', 'replace')!r}.",
                "Only "
                + ", ".join(v.decode() for v in L.KNOWN_VERSIONS)
                + " is documented. Parsing an undocumented generation would risk "
                "misattributing footage, so it is refused rather than guessed.",
            )

        return MasterSector(
            version=version.decode("ascii"),
            total_capacity_bytes=self._u64(L.TOTAL_CAPACITY_OFFSET),
            system_log_offset=self._u64(L.SYSTEM_LOG_OFFSET_OFFSET),
            system_log_size=self._u64(L.SYSTEM_LOG_SIZE_OFFSET),
            data_area_offset=self._u64(L.DATA_AREA_OFFSET_OFFSET),
            data_block_size=self._u64(L.DATA_BLOCK_SIZE_OFFSET),
            data_block_count=self._u32(L.DATA_BLOCK_COUNT_OFFSET),
            btree_offset=self._u64(L.HIKBTREE1_OFFSET_OFFSET),
            btree_size=self._u32(L.HIKBTREE1_SIZE_OFFSET),
            btree_backup_offset=self._u64(L.HIKBTREE2_OFFSET_OFFSET),
            btree_backup_size=self._u32(L.HIKBTREE2_SIZE_OFFSET),
            initialised_at=_unix(self._u32(L.INIT_TIME_OFFSET)),
        )

    # -- index ------------------------------------------------------------

    def entries(self, *, use_backup: bool = False) -> list[BlockEntry]:
        """Walk the HIKBTREE page chain and decode every allocated entry.

        ``use_backup`` reads the mirror tree, which is how a damaged primary
        index is worked around and how the two can be compared for tampering.
        """
        tree_at = self.master.btree_backup_offset if use_backup else self.master.btree_offset
        if tree_at + L.BTREE_SIGNATURE_OFFSET + 8 > self.size:
            raise DiskFormatError("HIKBTREE offset lies outside the image.")

        signature_at = tree_at + L.BTREE_SIGNATURE_OFFSET
        signature = self._map[signature_at : signature_at + len(L.BTREE_SIGNATURE)]
        if signature != L.BTREE_SIGNATURE:
            raise DiskFormatError(
                "HIKBTREE signature missing.",
                f"Expected {L.BTREE_SIGNATURE!r} at {hex(signature_at)}, found {signature!r}.",
            )

        found: list[BlockEntry] = []
        page_at = self._u64(tree_at + L.BTREE_FIRST_PAGE_OFFSET)
        seen_pages: set[int] = set()
        page_index = 0

        while page_at not in (0, L.NO_NEXT_PAGE):
            if page_at in seen_pages:
                # A self-referential chain would otherwise spin forever on a
                # corrupted or deliberately looped index.
                break
            if page_at + L.PAGE_SIZE > self.size:
                break
            seen_pages.add(page_at)

            count = self._u32(page_at + L.PAGE_ENTRY_COUNT_OFFSET)
            count = min(count, L.MAX_ENTRIES_PER_PAGE)
            for slot in range(count):
                entry_at = page_at + L.PAGE_ENTRIES_OFFSET + slot * L.ENTRY_SIZE
                entry = self._decode_entry(entry_at, page_index, slot)
                if entry is not None:
                    found.append(entry)

            page_at = self._u64(page_at + L.PAGE_NEXT_PAGE_OFFSET)
            page_index += 1

        return found

    def _decode_entry(self, entry_at: int, page_index: int, slot: int) -> BlockEntry | None:
        if entry_at + L.ENTRY_SIZE > self.size:
            return None
        in_use = self._u64(entry_at + L.ENTRY_IN_USE_OFFSET)
        if in_use != L.IN_USE_MARKER:
            return None
        if self._u64(entry_at + L.ENTRY_VIDEO_EXISTS_OFFSET) != L.VIDEO_PRESENT:
            return None

        # Channel is the one big-endian field in the structure.
        channel = struct.unpack_from(">H", self._map, entry_at + L.ENTRY_CHANNEL_OFFSET)[0]
        raw_start = self._u32(entry_at + L.ENTRY_START_TIME_OFFSET)
        raw_end = self._u32(entry_at + L.ENTRY_END_TIME_OFFSET)
        data_offset = self._u64(entry_at + L.ENTRY_DATA_OFFSET_OFFSET)
        if data_offset >= self.size:
            return None

        return BlockEntry(
            channel=channel,
            start=_unix(raw_start),
            end=_unix(raw_end),
            data_offset=data_offset,
            raw_start=raw_start,
            raw_end=raw_end,
            page_index=page_index,
            entry_index=slot,
        )

    def read_block(self, data_offset: int) -> memoryview:
        """A read-only view of one data block. No copy is made."""
        end = min(data_offset + self.master.data_block_size, self.size)
        return memoryview(self._map)[data_offset:end]
