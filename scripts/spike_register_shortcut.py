"""Spike: Y-button registered-item shortcut via use_item.

Exercises the new ``_drive_shortcut_use`` helper end-to-end:
  1. Read initial registeredItem.
  2. Call ``use_item('Bicycle')`` — slow path if bike isn't registered,
     fast Y-path otherwise.
  3. Verify the mount by reading CYCLING_GEAR_ADDR.
  4. Call ``use_item('Bicycle')`` again — should now be fast Y-path.
  5. Dismount and confirm.

Run from project root with a save state loaded in the overworld:
  .venv/bin/python scripts/spike_register_shortcut.py
"""

from __future__ import annotations

from melonds_mcp.client import EmulatorClient
from renegade_mcp import addresses
from renegade_mcp.use_item import (
    REGISTERED_ITEM_OFFSET,
    _get_registered_item,
    use_item,
)

SOCK = ".melonds_bridge.sock"


def main() -> None:
    emu = EmulatorClient(SOCK)
    addresses.reset()
    addresses.detect_shift(emu)

    bag_base = addresses.addr("BAG_BASE")
    print(f"BAG_BASE=0x{bag_base:x}, registeredItem @ +0x{REGISTERED_ITEM_OFFSET:x}")

    def snapshot(tag: str) -> None:
        ri = _get_registered_item(emu)
        cyc = emu.read_memory(addresses.addr("CYCLING_GEAR_ADDR"), size="short")
        fc = emu.get_status().get("frame_count")
        print(f"  [{tag}] registered={ri} cycling={cyc} frame={fc}")

    snapshot("start")

    print("\n[1] use_item('Bicycle') — expect slow path if bike not registered, else Y.")
    t0 = emu.get_status().get("frame_count")
    r1 = use_item(emu, "Bicycle")
    t1 = emu.get_status().get("frame_count")
    print(f"    result: {r1.get('formatted')}")
    print(f"    frames spent: {t1 - t0}")
    snapshot("after use #1")

    print("\n[2] use_item('Bicycle') again — expect fast Y path.")
    t0 = emu.get_status().get("frame_count")
    r2 = use_item(emu, "Bicycle")
    t1 = emu.get_status().get("frame_count")
    print(f"    result: {r2.get('formatted')}")
    print(f"    frames spent: {t1 - t0}")
    snapshot("after use #2")


if __name__ == "__main__":
    main()
