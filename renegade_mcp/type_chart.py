"""Pokemon type effectiveness chart — Gen 4 base + Fairy (Renegade Platinum).

Hardcoded from pret/pokeplatinum decomp (sTypeMatchupMultipliers in battle_lib.c)
with Fairy type added per Gen 6 standard matchups (as used by Renegade Platinum).

Only non-neutral matchups are stored. Absent entries default to 1.0x.
"""

from __future__ import annotations

# ── Effectiveness multipliers ──
# Key: (attacking_type, defending_type) → multiplier
# Only entries that differ from 1.0 (neutral) are listed.
_CHART: dict[tuple[str, str], float] = {
    # Normal attacking
    ("Normal", "Rock"): 0.5,
    ("Normal", "Steel"): 0.5,
    ("Normal", "Ghost"): 0.0,
    # Fire attacking
    ("Fire", "Fire"): 0.5,
    ("Fire", "Water"): 0.5,
    ("Fire", "Grass"): 2.0,
    ("Fire", "Ice"): 2.0,
    ("Fire", "Bug"): 2.0,
    ("Fire", "Rock"): 0.5,
    ("Fire", "Dragon"): 0.5,
    ("Fire", "Steel"): 2.0,
    # Water attacking
    ("Water", "Fire"): 2.0,
    ("Water", "Water"): 0.5,
    ("Water", "Grass"): 0.5,
    ("Water", "Ground"): 2.0,
    ("Water", "Rock"): 2.0,
    ("Water", "Dragon"): 0.5,
    # Electric attacking
    ("Electric", "Water"): 2.0,
    ("Electric", "Electric"): 0.5,
    ("Electric", "Grass"): 0.5,
    ("Electric", "Ground"): 0.0,
    ("Electric", "Flying"): 2.0,
    ("Electric", "Dragon"): 0.5,
    # Grass attacking
    ("Grass", "Fire"): 0.5,
    ("Grass", "Water"): 2.0,
    ("Grass", "Grass"): 0.5,
    ("Grass", "Poison"): 0.5,
    ("Grass", "Ground"): 2.0,
    ("Grass", "Flying"): 0.5,
    ("Grass", "Bug"): 0.5,
    ("Grass", "Rock"): 2.0,
    ("Grass", "Dragon"): 0.5,
    ("Grass", "Steel"): 0.5,
    # Ice attacking
    ("Ice", "Fire"): 0.5,
    ("Ice", "Water"): 0.5,
    ("Ice", "Grass"): 2.0,
    ("Ice", "Ice"): 0.5,
    ("Ice", "Ground"): 2.0,
    ("Ice", "Flying"): 2.0,
    ("Ice", "Dragon"): 2.0,
    ("Ice", "Steel"): 0.5,
    # Fighting attacking
    ("Fighting", "Normal"): 2.0,
    ("Fighting", "Ice"): 2.0,
    ("Fighting", "Poison"): 0.5,
    ("Fighting", "Flying"): 0.5,
    ("Fighting", "Psychic"): 0.5,
    ("Fighting", "Bug"): 0.5,
    ("Fighting", "Rock"): 2.0,
    ("Fighting", "Dark"): 2.0,
    ("Fighting", "Steel"): 2.0,
    ("Fighting", "Ghost"): 0.0,
    ("Fighting", "Fairy"): 0.5,
    # Poison attacking
    ("Poison", "Grass"): 2.0,
    ("Poison", "Poison"): 0.5,
    ("Poison", "Ground"): 0.5,
    ("Poison", "Rock"): 0.5,
    ("Poison", "Ghost"): 0.5,
    ("Poison", "Steel"): 0.0,
    ("Poison", "Fairy"): 2.0,
    # Ground attacking
    ("Ground", "Fire"): 2.0,
    ("Ground", "Electric"): 2.0,
    ("Ground", "Grass"): 0.5,
    ("Ground", "Poison"): 2.0,
    ("Ground", "Flying"): 0.0,
    ("Ground", "Bug"): 0.5,
    ("Ground", "Rock"): 2.0,
    ("Ground", "Steel"): 2.0,
    # Flying attacking
    ("Flying", "Electric"): 0.5,
    ("Flying", "Grass"): 2.0,
    ("Flying", "Fighting"): 2.0,
    ("Flying", "Bug"): 2.0,
    ("Flying", "Rock"): 0.5,
    ("Flying", "Steel"): 0.5,
    # Psychic attacking
    ("Psychic", "Fighting"): 2.0,
    ("Psychic", "Poison"): 2.0,
    ("Psychic", "Psychic"): 0.5,
    ("Psychic", "Dark"): 0.0,
    ("Psychic", "Steel"): 0.5,
    # Bug attacking
    ("Bug", "Fire"): 0.5,
    ("Bug", "Grass"): 2.0,
    ("Bug", "Fighting"): 0.5,
    ("Bug", "Poison"): 0.5,
    ("Bug", "Flying"): 0.5,
    ("Bug", "Psychic"): 2.0,
    ("Bug", "Ghost"): 0.5,
    ("Bug", "Dark"): 2.0,
    ("Bug", "Steel"): 0.5,
    ("Bug", "Fairy"): 0.5,
    # Rock attacking
    ("Rock", "Fire"): 2.0,
    ("Rock", "Ice"): 2.0,
    ("Rock", "Fighting"): 0.5,
    ("Rock", "Ground"): 0.5,
    ("Rock", "Flying"): 2.0,
    ("Rock", "Bug"): 2.0,
    ("Rock", "Steel"): 0.5,
    # Ghost attacking
    ("Ghost", "Normal"): 0.0,
    ("Ghost", "Psychic"): 2.0,
    ("Ghost", "Dark"): 0.5,
    ("Ghost", "Steel"): 0.5,
    ("Ghost", "Ghost"): 2.0,
    # Dragon attacking
    ("Dragon", "Dragon"): 2.0,
    ("Dragon", "Steel"): 0.5,
    ("Dragon", "Fairy"): 0.0,
    # Dark attacking
    ("Dark", "Fighting"): 0.5,
    ("Dark", "Psychic"): 2.0,
    ("Dark", "Ghost"): 2.0,
    ("Dark", "Dark"): 0.5,
    ("Dark", "Steel"): 0.5,
    ("Dark", "Fairy"): 0.5,
    # Steel attacking
    ("Steel", "Fire"): 0.5,
    ("Steel", "Water"): 0.5,
    ("Steel", "Electric"): 0.5,
    ("Steel", "Ice"): 2.0,
    ("Steel", "Rock"): 2.0,
    ("Steel", "Steel"): 0.5,
    ("Steel", "Fairy"): 2.0,
    # Fairy attacking (Gen 6 standard — Renegade Platinum addition)
    ("Fairy", "Fire"): 0.5,
    ("Fairy", "Poison"): 0.5,
    ("Fairy", "Steel"): 0.5,
    ("Fairy", "Fighting"): 2.0,
    ("Fairy", "Dragon"): 2.0,
    ("Fairy", "Dark"): 2.0,
}

# All valid type names (for input validation)
VALID_TYPES = frozenset({
    "Normal", "Fire", "Water", "Electric", "Grass", "Ice",
    "Fighting", "Poison", "Ground", "Flying", "Psychic",
    "Bug", "Rock", "Ghost", "Dragon", "Dark", "Steel", "Fairy",
})


def _normalize_type(name: str) -> str | None:
    """Normalize a type name to title case. Returns None if invalid."""
    t = name.strip().title()
    return t if t in VALID_TYPES else None


def single_effectiveness(atk_type: str, def_type: str) -> float:
    """Get multiplier for one attacking type vs one defending type.

    Returns 1.0 for neutral, 2.0 for super effective, 0.5 for not very effective,
    0.0 for immune. Returns 1.0 for unknown types.
    """
    return _CHART.get((atk_type, def_type), 1.0)


def effectiveness(atk_type: str, def_type1: str, def_type2: str | None = None) -> float:
    """Get total multiplier for an attacking type vs one or two defending types.

    Multiplies the individual matchups:
    - 2.0 × 2.0 = 4.0 (double super effective)
    - 2.0 × 0.5 = 1.0 (cancels out)
    - 0.0 × anything = 0.0 (immunity always wins)
    """
    mult = single_effectiveness(atk_type, def_type1)
    if def_type2 and def_type2 != def_type1:
        mult *= single_effectiveness(atk_type, def_type2)
    return mult


def describe(multiplier: float) -> str:
    """Human-readable label for a multiplier value."""
    if multiplier == 0.0:
        return "IMMUNE (0x)"
    elif multiplier == 0.25:
        return "DOUBLY RESISTED (0.25x)"
    elif multiplier == 0.5:
        return "NOT VERY EFFECTIVE (0.5x)"
    elif multiplier == 1.0:
        return "Neutral (1x)"
    elif multiplier == 2.0:
        return "SUPER EFFECTIVE (2x)"
    elif multiplier == 4.0:
        return "DOUBLE SUPER EFFECTIVE (4x)"
    else:
        return f"{multiplier}x"


def format_matchup(atk_type: str, def_type1: str, def_type2: str | None = None) -> str:
    """Format a full matchup result as a readable string."""
    mult = effectiveness(atk_type, def_type1, def_type2)
    def_str = def_type1
    if def_type2 and def_type2 != def_type1:
        def_str = f"{def_type1}/{def_type2}"
    return f"{atk_type} → {def_str}: {describe(mult)}"
