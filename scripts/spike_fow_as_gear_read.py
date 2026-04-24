"""BUG-046: verify FOW (PLAYER_POS_BASE + 0x6c) is reliable to READ for true
cycling gear, and that B-press toggles it predictably.

If FOW reads the authoritative PlayerData.cyclingGear, then:
  - Fresh mount: FOW reads whatever the player had before (persisted).
  - One B-press while cycling: FOW flips.
  - We can use FOW to decide "do I need to B-press to reach target gear?"
    in `_set_bike_gear`, replacing the unreliable byte read.

Does NOT write to FOW. Only reads + input-driven toggles.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from renegade_mcp.connection import get_client


SAVE_STATE = "bug_slope_ascent_mount_thrash"
FOW = 0x0227f4bc
BIKE = 0x021bf6ac


def pos(emu):
    from renegade_mcp.addresses import addr
    base = addr("PLAYER_POS_BASE")
    return (emu.read_memory(base + 8, size="long"),
            emu.read_memory(base + 12, size="long"))


def read_gears(emu):
    return (emu.read_memory(FOW, size="byte"),
            emu.read_memory(BIKE, size="byte"))


def step(emu, direction, max_frames=60):
    from renegade_mcp.addresses import addr
    axis = 8 if direction in ("left", "right") else 12
    res = emu.advance_frames_until(
        max_frames=max_frames,
        conditions=[{"type": "changed",
                     "address": addr("PLAYER_POS_BASE") + axis, "size": "long"}],
        poll_interval=1,
        buttons=[direction],
    )
    emu.advance_frames(8)
    return bool(res.get("triggered"))


def main():
    emu = get_client()
    from renegade_mcp.addresses import addr
    from renegade_mcp.use_item import use_item

    emu.load_state(SAVE_STATE)
    emu.advance_frames(60)

    fow, bike = read_gears(emu)
    cycling = bool(emu.read_memory(addr("CYCLING_GEAR_ADDR"), size="short"))
    print(f"Post-load:   pos={pos(emu)}  cycling={cycling}  FOW={fow}  BIKE={bike}")

    if cycling:
        use_item(emu, "Bicycle")  # dismount
        emu.advance_frames(30)
        fow, bike = read_gears(emu)
        print(f"Post-dism:   cycling={bool(emu.read_memory(addr('CYCLING_GEAR_ADDR'), size='short'))}  FOW={fow}  BIKE={bike}")

    # Move to runway start (7, 31) — 3 tiles down from (7, 28) / wherever load put us
    for i in range(3):
        step(emu, "down")
    fow, bike = read_gears(emu)
    print(f"After walk:  pos={pos(emu)}  FOW={fow}  BIKE={bike}")

    # Fresh mount
    use_item(emu, "Bicycle")
    emu.advance_frames(90)
    fow, bike = read_gears(emu)
    print(f"Post-mount:  pos={pos(emu)}  FOW={fow}  BIKE={bike}")
    print(f"             (FOW is what matters: 0=fast, 1=slow per decomp)")

    # If FOW reads slow, B-press once to flip to fast.
    if fow == 1:
        print("  FOW says slow — pressing B once to toggle to fast.")
        emu.press_buttons(["b"], frames=8)
        emu.advance_frames(30)
        fow, bike = read_gears(emu)
        print(f"  After B:   FOW={fow}  BIKE={bike}")
    else:
        print("  FOW already says fast — no toggle needed.")

    # Confirm
    fow, bike = read_gears(emu)
    print(f"\nPre-slope:   pos={pos(emu)}  FOW={fow}  BIKE={bike}")
    if fow != 0:
        print("  WARNING: still not fast, aborting slope test.")
        return

    # Attempt slope: hold UP continuously
    target_y = 25
    player_y_addr = addr("PLAYER_POS_BASE") + 12
    print("Holding UP (continuous) until y <= 25 or max 600f...")
    result = emu.advance_frames_until(
        max_frames=600,
        conditions=[{"type": "value",
                     "address": player_y_addr, "size": "long",
                     "operator": "<=", "value": target_y}],
        poll_interval=1,
        buttons=["up"],
    )
    emu.advance_frames(120)
    triggered = result.get("triggered", False)
    frames = result.get("frames_elapsed", "?")
    final = pos(emu)
    fow, bike = read_gears(emu)
    print(f"\nResult: triggered={triggered} frames={frames} final={final} FOW={fow} BIKE={bike}")

    if triggered and final[1] <= 25:
        print("\nSUCCESS — slope climbed with FOW-driven gear management.")
    else:
        print("\nFAILED — FOW alone isn't enough.")


if __name__ == "__main__":
    main()
