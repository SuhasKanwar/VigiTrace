"""Build a synthetic HIKVISION recorder volume.

The offsets and magic values below are written from the published format
description, NOT imported from ``disk.hikvision.layout``. That separation is
the point: if the parser's idea of an offset drifts from the specification, the
two sides disagree and a test fails. Sharing one constants module would let a
single mistake cancel itself out and produce a green suite over a broken parser.

What this cannot establish is whether real Hikvision firmware writes what the
literature says it writes. It exercises the parser against the documented
format; it is not a substitute for a seized disk.

Layout produced (offsets absolute, little-endian unless noted):

    0x00000  sector 0, unused
    0x00200  master sector
    0x10000  system log area
    0x20000  HIKBTREE (primary)
    0x30000  HIKBTREE (backup copy)
    0x40000  data area, `block_size` bytes per block
"""

import struct
from dataclasses import dataclass, field

SECTOR = 512
MASTER_AT = 0x200
LOG_AREA_AT = 0x10000
LOG_AREA_SIZE = 0x10000
BTREE_AT = 0x20000
BTREE_BACKUP_AT = 0x30000
BTREE_SIZE = 0x10000
DATA_AREA_AT = 0x40000

PAGE_BYTES = 0x1000
ENTRY_BYTES = 0x30
ENTRIES_PER_PAGE = (PAGE_BYTES - 0x60) // ENTRY_BYTES
ALL_ONES_64 = 0xFFFFFFFFFFFFFFFF
UNFINALISED = 0x7FFFFFFF


@dataclass
class Recording:
    """One recording the builder will place in a data block."""

    channel: int
    start: int
    end: int
    payload: bytes
    #: Written into the data area but given no index entry, which is what a
    #: deleted or never-indexed recording looks like on a real volume.
    orphaned: bool = False
    #: Emits the 0x7FFFFFFF sentinel, i.e. the recorder was mid-write.
    unfinalised: bool = False
    idr_offsets: list[int] = field(default_factory=list)


class HikvisionImageBuilder:
    """Assemble a byte-exact synthetic volume."""

    def __init__(
        self,
        block_size: int = 1 << 20,
        block_count: int = 8,
        version: bytes = b"HIK.2011.03.08",
        init_time: int = 1_600_000_000,
    ):
        # Real recorders use 1 GiB blocks; the size is a field the parser reads,
        # so a smaller one keeps test images to a few megabytes without making
        # the layout any less faithful.
        self.block_size = block_size
        self.block_count = block_count
        self.version = version
        self.init_time = init_time
        self.recordings: list[Recording] = []
        self.logs: list[tuple[int, int, str]] = []

    def add_recording(self, channel, start, end, payload, *, orphaned=False, unfinalised=False):
        self.recordings.append(
            Recording(channel, start, end, payload, orphaned=orphaned, unfinalised=unfinalised)
        )
        return self

    def add_log(self, when: int, log_type: int, description: str):
        self.logs.append((when, log_type, description))
        return self

    # -- section writers --------------------------------------------------

    def _master_sector(self) -> bytes:
        block = bytearray(0x100)
        block[0x10 : 0x10 + 18] = b"HIKVISION@HANGZHOU"
        block[0x30 : 0x30 + len(self.version)] = self.version
        struct.pack_into("<Q", block, 0x48, DATA_AREA_AT + self.block_count * self.block_size)
        struct.pack_into("<Q", block, 0x60, LOG_AREA_AT)
        struct.pack_into("<Q", block, 0x68, LOG_AREA_SIZE)
        struct.pack_into("<Q", block, 0x78, DATA_AREA_AT)
        struct.pack_into("<Q", block, 0x88, self.block_size)
        struct.pack_into("<I", block, 0x90, self.block_count)
        struct.pack_into("<Q", block, 0x98, BTREE_AT)
        struct.pack_into("<I", block, 0xA0, BTREE_SIZE)
        struct.pack_into("<Q", block, 0xA8, BTREE_BACKUP_AT)
        struct.pack_into("<I", block, 0xB0, BTREE_SIZE)
        struct.pack_into("<I", block, 0xF0, self.init_time)
        return bytes(block)

    def _entry(self, rec: Recording, data_offset: int) -> bytes:
        entry = bytearray(ENTRY_BYTES)
        struct.pack_into("<Q", entry, 0x00, ALL_ONES_64)          # in use
        struct.pack_into("<Q", entry, 0x08, 0)                    # video present
        struct.pack_into(">H", entry, 0x10, rec.channel)          # channel is BIG-endian
        start = UNFINALISED if rec.unfinalised else rec.start
        struct.pack_into("<I", entry, 0x18, start)
        struct.pack_into("<I", entry, 0x1C, rec.end)
        struct.pack_into("<Q", entry, 0x20, data_offset)
        return bytes(entry)

    def _btree(self, indexed: list[tuple[Recording, int]]) -> bytes:
        tree = bytearray(BTREE_SIZE)
        tree[0x10 : 0x10 + 8] = b"HIKBTREE"
        struct.pack_into("<I", tree, 0x3C, self.init_time)
        first_page = 0x1000
        struct.pack_into("<Q", tree, 0x40, BTREE_AT + BTREE_SIZE)     # footer
        struct.pack_into("<Q", tree, 0x50, BTREE_AT + first_page)     # page list
        struct.pack_into("<Q", tree, 0x58, BTREE_AT + first_page)     # first page

        pages = [indexed[i : i + ENTRIES_PER_PAGE] for i in range(0, len(indexed), ENTRIES_PER_PAGE)] or [[]]
        for index, page_entries in enumerate(pages):
            page_at = first_page + index * PAGE_BYTES
            page = bytearray(PAGE_BYTES)
            struct.pack_into("<I", page, 0x10, len(page_entries))
            is_last = index == len(pages) - 1
            next_page = ALL_ONES_64 if is_last else BTREE_AT + page_at + PAGE_BYTES
            struct.pack_into("<Q", page, 0x20, next_page)
            cursor = 0x60
            for rec, data_offset in page_entries:
                page[cursor : cursor + ENTRY_BYTES] = self._entry(rec, data_offset)
                cursor += ENTRY_BYTES
            tree[page_at : page_at + PAGE_BYTES] = page
        return bytes(tree)

    def _logs(self) -> bytes:
        area = bytearray(LOG_AREA_SIZE)
        cursor = 0
        for when, log_type, description in self.logs:
            body = description.encode("utf-8")[:200]
            record = bytearray(8 + 4 + 1 + 2 + len(body))
            record[0:8] = b"RATS\x01\x00\x00\x00"
            struct.pack_into("<I", record, 8, when)
            record[12] = log_type
            struct.pack_into("<H", record, 13, len(body))
            record[15 : 15 + len(body)] = body
            if cursor + len(record) > LOG_AREA_SIZE:
                break
            area[cursor : cursor + len(record)] = record
            cursor += len(record)
        return bytes(area)

    def _data_block(self, rec: Recording) -> bytes:
        """Video from the front, IDR records growing downward from the end."""
        block = bytearray(self.block_size)
        payload = rec.payload[: self.block_size - 4096]
        block[0 : len(payload)] = payload

        # Index every pack header as an IDR record, which is what the recorder's
        # own table gives a player to seek with.
        positions = []
        cursor = 0
        while True:
            cursor = payload.find(b"\x00\x00\x01\xba", cursor)
            if cursor < 0:
                break
            positions.append(cursor)
            cursor += 4
        rec.idr_offsets = positions

        write_at = self.block_size
        for order, position in enumerate(positions):
            write_at -= 56
            if write_at < len(payload):
                break
            record = bytearray(56)
            record[0:4] = b"OFNI"
            struct.pack_into("<I", record, 4, order)
            struct.pack_into("<H", record, 8, rec.channel)
            struct.pack_into("<I", record, 12, rec.start)
            struct.pack_into("<Q", record, 16, position)
            block[write_at : write_at + 56] = record
        return bytes(block)

    def build(self) -> bytes:
        image = bytearray(DATA_AREA_AT + self.block_count * self.block_size)
        image[MASTER_AT : MASTER_AT + 0x100] = self._master_sector()
        image[LOG_AREA_AT : LOG_AREA_AT + LOG_AREA_SIZE] = self._logs()

        indexed: list[tuple[Recording, int]] = []
        for slot, rec in enumerate(self.recordings):
            if slot >= self.block_count:
                raise ValueError("more recordings than data blocks")
            data_offset = DATA_AREA_AT + slot * self.block_size
            image[data_offset : data_offset + self.block_size] = self._data_block(rec)
            # An orphaned recording is written but never indexed, so only a scan
            # of the data area will find it.
            if not rec.orphaned:
                indexed.append((rec, data_offset))

        tree = self._btree(indexed)
        image[BTREE_AT : BTREE_AT + BTREE_SIZE] = tree
        image[BTREE_BACKUP_AT : BTREE_BACKUP_AT + BTREE_SIZE] = tree
        return bytes(image)

    def write(self, path: str) -> str:
        with open(path, "wb") as handle:
            handle.write(self.build())
        return path
