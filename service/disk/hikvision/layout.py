"""Byte layout of the HIKVISION recorder filesystem.

Every constant here is an offset or magic value taken from published research,
kept in one place so a parser never carries a naked number.

Sources, which agree with each other byte for byte:
  * Han, Jeong & Lee, "Analysis of the HIKVISION DVR File System",
    ICDF2C 2015, LNICST 157:189-199 (DOI 10.1007/978-3-319-25512-5_13)
  * a1ive/FsRover, grub-core/fs/hikvision.c
  * fmpfeifer/hikextractor, src/hikvision_parser.py
  * dw2102/X-Ways-HIKVISION-X-Tension, HIKVISION/hikvision.cpp

All integers are little-endian unless a field says otherwise. Signatures are
raw ASCII.

The synthetic image builder in tests/disk/ deliberately does NOT import this
module: it writes the same structures from its own literals, so a mistake in
one side shows up as a test failure rather than cancelling out.
"""

SECTOR_SIZE = 512

# --- Master sector -------------------------------------------------------
# Lives at LBA 1. Offsets below are absolute within the image.
MASTER_SECTOR_OFFSET = 0x200
MASTER_SECTOR_SIZE = 0x100

SIGNATURE = b"HIKVISION@HANGZHOU"
SIGNATURE_OFFSET = 0x210
SIGNATURE_LENGTH = 18

#: Format-generation string, e.g. "HIK.2011.03.08". This is the discriminator:
#: other generations exist in the wild and are undocumented, so a parser reads
#: it and refuses unknown values rather than guessing at a layout.
VERSION_OFFSET = 0x230
VERSION_LENGTH = 14
KNOWN_VERSIONS = (b"HIK.2011.03.08",)

TOTAL_CAPACITY_OFFSET = 0x248          # u64, bytes
SYSTEM_LOG_OFFSET_OFFSET = 0x260       # u64, absolute offset
SYSTEM_LOG_SIZE_OFFSET = 0x268         # u64, bytes
DATA_AREA_OFFSET_OFFSET = 0x278        # u64, absolute offset
DATA_BLOCK_SIZE_OFFSET = 0x288         # u64, bytes (commonly 0x40000000 = 1 GiB)
DATA_BLOCK_COUNT_OFFSET = 0x290        # u32
HIKBTREE1_OFFSET_OFFSET = 0x298        # u64, absolute offset
HIKBTREE1_SIZE_OFFSET = 0x2A0          # u32
HIKBTREE2_OFFSET_OFFSET = 0x2A8        # u64, absolute offset of the backup tree
HIKBTREE2_SIZE_OFFSET = 0x2B0          # u32
#: Time the recorder initialised this volume. Forensically load-bearing: a
#: reformat resets it and zeroes the logs while leaving video blocks carvable,
#: so a timestamp far newer than the recordings is itself a finding.
INIT_TIME_OFFSET = 0x2F0               # u32, UNIX UTC

# --- HIKBTREE ------------------------------------------------------------
# Offsets relative to the tree's own start.
BTREE_SIGNATURE = b"HIKBTREE"
BTREE_SIGNATURE_OFFSET = 0x10
BTREE_CREATED_OFFSET = 0x3C            # u32, UNIX UTC
BTREE_FOOTER_OFFSET = 0x40             # u64
BTREE_PAGE_LIST_OFFSET = 0x50          # u64
BTREE_FIRST_PAGE_OFFSET = 0x58         # u64

# --- Page ----------------------------------------------------------------
PAGE_SIZE = 0x1000                     # 4096 bytes, fixed
PAGE_ENTRY_COUNT_OFFSET = 0x10         # u32
PAGE_NEXT_PAGE_OFFSET = 0x20           # u64; NO_NEXT_PAGE terminates the chain
PAGE_ENTRIES_OFFSET = 0x60
NO_NEXT_PAGE = 0xFFFFFFFFFFFFFFFF

# --- Data-block entry ----------------------------------------------------
ENTRY_SIZE = 0x30                      # 48 bytes
MAX_ENTRIES_PER_PAGE = (PAGE_SIZE - PAGE_ENTRIES_OFFSET) // ENTRY_SIZE   # 83

ENTRY_IN_USE_OFFSET = 0x00             # u64, IN_USE_MARKER when allocated
ENTRY_VIDEO_EXISTS_OFFSET = 0x08       # u64, 0 = holds footage, all-ones = empty
ENTRY_CHANNEL_OFFSET = 0x10            # u16 BIG-endian (the one BE field)
ENTRY_START_TIME_OFFSET = 0x18         # u32, UNIX UTC
ENTRY_END_TIME_OFFSET = 0x1C           # u32, UNIX UTC
ENTRY_DATA_OFFSET_OFFSET = 0x20        # u64, absolute offset of the data block

IN_USE_MARKER = 0xFFFFFFFFFFFFFFFF
VIDEO_PRESENT = 0x0000000000000000
VIDEO_ABSENT = 0xFFFFFFFFFFFFFFFF

#: A start time of 0x7FFFFFFF (2038-01-19T03:14:07Z) means the block was being
#: written when the volume was imaged. Such blocks are still readable and must
#: not be discarded - they are the most recent footage on the disk.
UNFINALISED_TIME = 0x7FFFFFFF

# --- Inside a data block -------------------------------------------------
#: Each block is video from the front, with a table of IDR (keyframe) records
#: growing downward from the end. "OFNI" is "INFO" byte-reversed.
IDR_SIGNATURE = b"OFNI"
IDR_RECORD_SIZE = 56

# --- System logs ---------------------------------------------------------
LOG_SIGNATURE = b"RATS\x01\x00\x00\x00"
LOG_TYPE_ALARM = 0x01
LOG_TYPE_EXCEPTION = 0x02
LOG_TYPE_OPERATION = 0x03
LOG_TYPE_INFORMATION = 0x04

# --- Video payload -------------------------------------------------------
PS_PACK_HEADER = b"\x00\x00\x01\xba"
PS_PROGRAM_STREAM_MAP = b"\x00\x00\x01\xbc"
PS_SYSTEM_HEADER = b"\x00\x00\x01\xbb"
H264_ANNEXB_START = b"\x00\x00\x00\x01"
#: Exported Hikvision files carry a 40-byte proprietary header. ffmpeg only
#: sniffs the first six bytes, and reads mu-law audio correctly only when it
#: sees this magic, so carved fragments get one synthesised on the way out.
EXPORT_MAGIC = b"IMKH"
EXPORT_HEADER_SIZE = 40
