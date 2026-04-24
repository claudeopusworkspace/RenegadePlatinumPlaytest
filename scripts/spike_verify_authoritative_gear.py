"""BUG-046: test which gear address is authoritative.

Write to each candidate, wait for engine re-sync, read all three.
The authoritative address is the one whose write persists AND whose write
is mirrored to the others.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from renegade_mcp.connection import get_client


SAVE_STATE = "bug_slope_ascent_mount_thrash"

CANDIDATES = [
    ("BIKE_GEAR_STATE_ADDR (known)", 0x021bf6ac),
    ("PlayerData? (heap)",           0x021ccdb4),
    ("FieldOW mirror? (+PPB)",       0x0227f4bc),
]

SETTLE = 120  # frames to let engine re-sync


def read_all(emu):
    return {name: emu.read_memory(a, size="byte") for name, a in CANDIDATES}


def main():
    emu = get_client()
    from renegade_mcp.addresses import addr
    from renegade_mcp.use_item import use_item

    emu.load_state(SAVE_STATE)
    emu.advance_frames(30)
    if not emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short"):
        print("Mounting...")
        use_item(emu, "Bicycle")
        emu.advance_frames(60)

    print("=== Initial state ===")
    for k, v in read_all(emu).items():
        print(f"  {k}: {v}")

    for write_name, write_addr in CANDIDATES:
        print(f"\n=== WRITE 1 to {write_name} (0x{write_addr:08x}) ===")
        emu.write_memory(write_addr, value=1, size="byte")
        emu.advance_frames(1)
        print("  After 1f:")
        for k, v in read_all(emu).items():
            marker = " <-- written" if k == write_name else ""
            print(f"    {k}: {v}{marker}")
        emu.advance_frames(SETTLE - 1)
        print(f"  After {SETTLE}f (engine re-sync window):")
        for k, v in read_all(emu).items():
            marker = " <-- written" if k == write_name else ""
            print(f"    {k}: {v}{marker}")

        # Reset via B-press toggle (puts it back to whatever authoritative says)
        print("  Reset via B-press (x2):")
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(30)
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(30)
        for k, v in read_all(emu).items():
            print(f"    {k}: {v}")


if __name__ == "__main__":
    main()
