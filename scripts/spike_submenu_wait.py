"""Spike: find the minimum frame wait between A (open key-item submenu)
and DOWN (navigate to REGISTER).

Method:
  - Load a save state with player in overworld.
  - For each candidate wait:
      - Open bag, navigate to Bicycle, press A (submenu).
      - Advance `wait` frames.
      - Press DOWN.
      - Check which option the cursor landed on.
      - If REGISTER → this wait works.
  - Report the smallest passing wait.

The submenu-cursor position isn't in a memory field we've catalogued, so we
use a proxy: press A again and observe the result. If the cursor is on USE
(wait too short) → A triggers USE, Bicycle mounts (CYCLING_GEAR_ADDR flips).
If the cursor is on REGISTER (wait sufficient) → A commits REGISTER silently
and Bag.registeredItem updates to 450.

Run from project root:
  .venv/bin/python scripts/spike_submenu_wait.py
"""

from __future__ import annotations

import sys

from pathlib import Path

from melonds_mcp.client import EmulatorClient
from renegade_mcp import addresses
from renegade_mcp.bag import read_bag
from renegade_mcp.use_item import (
    REGISTERED_ITEM_OFFSET,
    _find_item_in_bag,
    _navigate_to_bag_pocket,
    _get_registered_item,
)
from renegade_mcp.addresses import addr

SOCK = ".melonds_bridge.sock"
STATE_PATH = str(Path(__file__).parent.parent / "savestates" / "test_eterna_city_overworld.mst")
CANDIDATES = [5, 10, 15, 20, 30, 45, 60]


def attempt(emu: EmulatorClient, wait: int) -> dict:
    """Return outcome of pressing DOWN→A at `wait` frames after submenu open."""
    # Force non-bike registered so the sub-menu shows REGISTER (not DESELECT).
    emu.write_memory(addr("BAG_BASE") + REGISTERED_ITEM_OFFSET, 0, size="long")
    assert _get_registered_item(emu) == 0, "failed to clear registered slot"

    # Reset to overworld (load state fresh).
    emu.load_state(STATE_PATH)
    addresses.reset()
    addresses.detect_shift(emu)
    emu.advance_frames(120)  # let the state settle

    was_cycling = emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")
    emu.write_memory(addr("BAG_BASE") + REGISTERED_ITEM_OFFSET, 0, size="long")

    bag = read_bag(emu)
    pocket, idx, entry = _find_item_in_bag(bag, "bicycle")
    assert entry is not None

    ok = _navigate_to_bag_pocket(emu, pocket, idx)
    assert ok, "could not open bag"

    # Press A to open submenu.
    emu.press_buttons(["a"], frames=8)
    emu.advance_frames(wait)

    # Press DOWN.
    emu.press_buttons(["down"], frames=8)
    emu.advance_frames(60)

    # Press A — commits whichever option the cursor lands on.
    emu.press_buttons(["a"], frames=8)
    emu.advance_frames(300)  # let any animation or write complete

    # Did REGISTER commit? Bag.registeredItem would be 450 now.
    after_reg = _get_registered_item(emu)
    after_cycling = emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short")

    # Close any open menus / dialogs.
    for _ in range(6):
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(120)

    return {
        "wait": wait,
        "registered": after_reg,
        "cycling": after_cycling,
        "success": after_reg == 450,  # DOWN landed on REGISTER, A committed
    }


def main() -> None:
    emu = EmulatorClient(SOCK)
    addresses.reset()
    addresses.detect_shift(emu)

    print(f"Using state: {STATE_PATH}")
    results = []
    for w in CANDIDATES:
        try:
            r = attempt(emu, w)
        except Exception as e:
            r = {"wait": w, "error": str(e)}
        print(f"  wait={w:4d} → {r}")
        results.append(r)

    # Find the smallest wait that succeeded.
    passing = [r for r in results if r.get("success")]
    if passing:
        smallest = min(r["wait"] for r in passing)
        print(f"\nMINIMUM PASSING: {smallest}f")
        print(f"Recommended SUBMENU_READY_WAIT: {smallest + 30} (smallest + 30f buffer)")
    else:
        print("\nNo candidate passed — widen the search")
        sys.exit(1)


if __name__ == "__main__":
    main()
