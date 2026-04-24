"""Check BIKE_GEAR_STATE_ADDR byte in known fast and slow gear saves.

We have two checkpoint-labeled saves:
  - spike_eterna_open_bike_fast  (labeled FAST gear, was verified manually)
  - spike_eterna_open_bike_slow  (labeled SLOW gear)

Read the gear byte at PPB+0x8c on each; whichever value appears
in the "fast" save IS the fast encoding.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from renegade_mcp.connection import get_client


def main():
    emu = get_client()
    from renegade_mcp.addresses import addr, reset, detect_shift

    for save, label in [
        ("spike_eterna_open_bike_fast", "FAST"),
        ("spike_eterna_open_bike_slow", "SLOW"),
    ]:
        emu.load_state(save)
        emu.advance_frames(120)
        reset()
        detect_shift(emu)
        gear_addr = addr("BIKE_GEAR_STATE_ADDR")
        cycling_addr = addr("CYCLING_GEAR_ADDR")
        gear_byte = emu.read_memory(gear_addr, size="byte")
        cycling = bool(emu.read_memory(cycling_addr, size="short"))
        # Also dump bytes at PPB+0x80..0x90 to see the layout
        ppb = addr("PLAYER_POS_BASE")
        scan = emu.read_memory_block(ppb + 0x80, 0x14)  # 20 bytes from +0x80
        print(f"\n{save} (labeled {label}):")
        print(f"  cycling: {cycling}")
        print(f"  PPB_actual=0x{ppb:08x}  BIKE_GEAR_STATE_ADDR=0x{gear_addr:08x}  byte={gear_byte}")
        print(f"  +0x80..0x93: {scan.hex()}")


if __name__ == "__main__":
    main()
