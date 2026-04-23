"""Verify chained-ramp execution reaches the east-chamber Pokéball at (31, 16).

Pre-fix (BIKE_HOLD_FRAMES + idle 36f per ramp step), the executor released
the direction button for 36 frames between ramps, draining bike gear and
failing to re-fire the second ramp. Post-fix (advance_frames_until polling
through to the BFS-predicted landing), the button is held continuously per
step and released only briefly between iterations — momentum is preserved.

This script loads `session31_wayward_cave_bike_ramps`, runs
`navigate_to(31, 16)`, and prints the final position. Expected: player
arrives at (31, 16). Pre-fix: stalls before the second ramp.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from melonds_mcp.client import EmulatorClient  # noqa: E402
from renegade_mcp import addresses  # noqa: E402
from renegade_mcp.navigation import navigate_to as _navigate_to  # noqa: E402
from helpers import do_load_state  # noqa: E402


SAVE = "session31_wayward_cave_bike_ramps"
SOCK = ".melonds_test_bridge.sock"


def run(emu: EmulatorClient, target: tuple[int, int], tag: str) -> None:
    do_load_state(emu, SAVE, redetect_shift=True)
    pos_base = addresses.addr("PLAYER_POS_BASE")
    x0 = emu.read_memory(pos_base + 8, size="long")
    y0 = emu.read_memory(pos_base + 12, size="long")
    print(f"\n=== {tag}: ({x0}, {y0}) → {target} ===")
    result = _navigate_to(emu, target_x=target[0], target_y=target[1],
                          flee_encounters=True)
    x1 = emu.read_memory(pos_base + 8, size="long")
    y1 = emu.read_memory(pos_base + 12, size="long")
    ok = (x1, y1) == target
    print(f"Final: ({x1}, {y1})  {'✓' if ok else '✗ MISS'}")
    for k in ("path", "steps", "repaths", "stopped_early", "blocked_at",
              "blocked_reason", "note"):
        if k in result:
            print(f"  {k}: {result[k]}")
    enc = result.get("encounter") or {}
    if enc:
        print(f"  encounter: {enc.get('encounter')}"
              f" {enc.get('dialogue', {}).get('text', '') if isinstance(enc.get('dialogue'), dict) else ''}")


def main() -> None:
    emu = EmulatorClient(SOCK)
    # First ramp only: (7, 22) → (14, 17) (known simple case, landing = ramp+4)
    run(emu, (14, 17), "Single ramp")
    # Chained ramps: (7, 22) → (31, 16) (east-chamber Pokéball)
    run(emu, (31, 16), "Chained ramps to east chamber")


if __name__ == "__main__":
    main()
