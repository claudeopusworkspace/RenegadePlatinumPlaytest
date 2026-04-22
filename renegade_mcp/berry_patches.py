"""Read BerryPatch records from MiscSaveBlock in RAM.

Each Sinnoh berry soil map-object stores its patch index in
`MapObject.data[0]` (offset 0x38 in the 0x128-byte slot). The save block
holds a 128-entry array of 14-byte BerryPatch records at
`SAVE_BLOCK_BASE + 0x20C4`.

BerryPatch layout (see ref/pokeplatinum/include/berry_patches.h):
    0x00 u8  berryID        1-based berry index; 0 = empty, 0xFF = unused slot
    0x01 u8  growthStage    0..5 (NONE/PLANTED/SPROUTED/GROWING/BLOOMING/FRUIT)
    0x02 u16 stageMinutesRemaining
    0x04 u16 moistureMinutesRemaining
    0x06 u8  replantCount
    0x07 pad
    0x08 u16 yield          berries available at FRUIT stage
    0x0A u8  moistureRating 0..100
    0x0B u8  yieldRating    0..5 (5 = max)
    0x0C u8  mulchType      0..4 (NONE/GROWTH/DAMP/STABLE/GOOEY)
    0x0D u8  isGrowing      1 when the player is in range and the timer ticks

Struct size is 14 bytes (even, so array stride = 14 — u8 trailing member
only forces 2-byte alignment, not 4).

Patch state is RTC-driven: the game ticks growth on a wall-clock schedule
whenever the field system processes an RTC delta and the patch has
isGrowing=1 (i.e. the player is on-map). Distant patches stay frozen
until the player returns.
"""

from __future__ import annotations

import struct
from typing import Any

from renegade_mcp.addresses import addr
from renegade_mcp.data import item_names

PATCH_SIZE = 14
MAX_PATCHES = 128

_STAGE_NAMES = {
    0: "none",
    1: "planted",
    2: "sprouted",
    3: "growing",
    4: "blooming",
    5: "fruit",
}

_MULCH_NAMES = {
    0: "none",
    1: "growth",
    2: "damp",
    3: "stable",
    4: "gooey",
}

# Soil moisture tiers (derived from moistureRating).
# Decomp: SOIL_VERY_DRY=0, SOIL_DRY=1, SOIL_MOIST=2. Threshold mapping is
# approximate — the game's exact cutoffs aren't critical for display.
def _moisture_label(rating: int) -> str:
    if rating >= 50:
        return "moist"
    if rating >= 1:
        return "dry"
    return "very_dry"


# Berry item IDs are contiguous starting at 149 (ITEM_CHERI_BERRY). The
# BerryPatch.berryID field is 1-based over this range, so itemID = bid + 148.
_BERRY_ITEM_ID_OFFSET = 148


def _berry_name(bid: int) -> str | None:
    """Map a 1-based berry id to the in-game berry name, or None if invalid."""
    if bid <= 0 or bid > 64:
        return None
    name = item_names().get(bid + _BERRY_ITEM_ID_OFFSET)
    if not name:
        return None
    # Names come through as "Oran Berry" — strip the suffix for brevity.
    return name.removesuffix(" Berry")


def read_patch(emu: Any, patch_id: int) -> dict[str, Any] | None:
    """Read and decode a single BerryPatch by index (0..127).

    Returns None if `patch_id` is out of range or the bytes don't decode to
    a plausible record (berryID > 64 or growthStage > 5 — the usual
    signature for unused/uninitialized slots left over from
    sBerryInitTable).
    """
    if not (0 <= patch_id < MAX_PATCHES):
        return None
    base = addr("BERRY_PATCH_BASE") + patch_id * PATCH_SIZE
    try:
        buf = emu.read_memory_block(base, PATCH_SIZE)
    except Exception:
        return None
    if len(buf) < PATCH_SIZE:
        return None

    bid = buf[0]
    stage = buf[1]
    # Reject obviously-uninitialized slots (0xFF-filled or nonsense).
    if bid > 64 or stage > 5:
        return None

    yield_count = struct.unpack_from("<H", buf, 8)[0]
    stage_min = struct.unpack_from("<H", buf, 2)[0]
    moist_min = struct.unpack_from("<H", buf, 4)[0]
    moist_rating = buf[10]
    yield_rating = buf[11]
    mulch = buf[12]
    is_growing = buf[13]

    if bid == 0:
        # Empty patch.
        return {
            "patch_id": patch_id,
            "planted": False,
        }

    berry_name = _berry_name(bid)
    stage_name = _STAGE_NAMES.get(stage, f"stage_{stage}")
    mulch_name = _MULCH_NAMES.get(mulch, f"mulch_{mulch}")

    return {
        "patch_id": patch_id,
        "planted": True,
        "berry": berry_name or f"berry_{bid}",
        "berry_id": bid,
        "growth_stage": stage_name,
        "growth_stage_id": stage,
        "stage_minutes_remaining": stage_min,
        "moisture_minutes_remaining": moist_min,
        "moisture_rating": moist_rating,
        "moisture": _moisture_label(moist_rating),
        "yield": yield_count,
        "yield_rating": yield_rating,
        "mulch": mulch_name,
        "is_growing": bool(is_growing),
        "harvestable": stage == 5 and yield_count > 0,
    }
