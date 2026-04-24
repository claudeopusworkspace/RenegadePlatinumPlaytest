"""BUG-046: does writing 0 to FOW gear address make the slope succeed?

If yes, FOW (0x0227f4bc = PLAYER_POS_BASE + 0x6c) is the authoritative
cyclingGear address and we should retarget `_set_bike_gear` at it.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from renegade_mcp.connection import get_client


SAVE_STATE = "bug_slope_ascent_mount_thrash"
FOW_GEAR = 0x0227f4bc  # candidate authoritative gear address


def pos(emu):
    from renegade_mcp.addresses import addr
    base = addr("PLAYER_POS_BASE")
    return (
        emu.read_memory(base + 8, size="long"),
        emu.read_memory(base + 12, size="long"),
    )


def step_dir(emu, direction, max_frames=60):
    from renegade_mcp.addresses import addr
    axis = 8 if direction in ("left", "right") else 12
    res = emu.advance_frames_until(
        max_frames=max_frames,
        conditions=[{"type": "changed", "address": addr("PLAYER_POS_BASE") + axis, "size": "long"}],
        poll_interval=1,
        buttons=[direction],
    )
    emu.advance_frames(8)  # let animation settle
    return bool(res.get("triggered"))


def main():
    emu = get_client()
    from renegade_mcp.addresses import addr
    from renegade_mcp.use_item import use_item

    emu.load_state(SAVE_STATE)
    emu.advance_frames(60)  # generous settle after load

    cycling = bool(emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short"))
    print(f"After load:  pos={pos(emu)}  cycling={cycling}  FOW={emu.read_memory(FOW_GEAR, size='byte')}")

    # Dismount if cycling (so we're on foot for the pre-slope walk)
    if cycling:
        use_item(emu, "Bicycle")
        emu.advance_frames(30)
        print(f"After dism:  pos={pos(emu)}  cycling={bool(emu.read_memory(addr('CYCLING_GEAR_ADDR'), size='short'))}  FOW={emu.read_memory(FOW_GEAR, size='byte')}")

    # Walk on foot to (7, 31) — 2 steps down from (7, 29)
    for i in range(2):
        ok = step_dir(emu, "down", max_frames=60)
        print(f"After down {i+1}: pos={pos(emu)} ok={ok}  FOW={emu.read_memory(FOW_GEAR, size='byte')}")

    # Mount fresh
    use_item(emu, "Bicycle")
    emu.advance_frames(90)
    print(f"After mount: pos={pos(emu)}  cycling={bool(emu.read_memory(addr('CYCLING_GEAR_ADDR'), size='short'))}  FOW={emu.read_memory(FOW_GEAR, size='byte')}")

    # Force FOW = 0 (fast gear)
    emu.write_memory(FOW_GEAR, value=0, size="byte")
    emu.advance_frames(30)
    print(f"After FOW=0: pos={pos(emu)}  FOW={emu.read_memory(FOW_GEAR, size='byte')}")

    # Hold UP continuously
    target_y = 25
    player_y_addr = addr("PLAYER_POS_BASE") + 12
    result = emu.advance_frames_until(
        max_frames=600,
        conditions=[{
            "type": "value",
            "address": player_y_addr,
            "size": "long",
            "operator": "<=",
            "value": target_y,
        }],
        poll_interval=1,
        buttons=["up"],
    )
    emu.advance_frames(120)
    final = pos(emu)
    triggered = result.get("triggered", False)
    frames = result.get("frames_elapsed", "?")
    print(f"\nHold result: triggered={triggered} frames_elapsed={frames}")
    print(f"Final pos after settle: {final}")
    print(f"Final FOW: {emu.read_memory(FOW_GEAR, size='byte')}")


if __name__ == "__main__":
    main()
