"""Curated workout template library — the variety engine's vocabulary.

The planner LLM SELECTS and SCALES from these templates; it never invents
session structure. Templates encode the classic methodologies:
- Daniels' E/M/T/I/R intensity taxonomy (paces come from VDOT via
  metrics.training_paces; HR bands from LTHR zones).
- Pfitzinger long-run variants (fast-finish, marathon-pace segments).
- Lydiard-style phase gating: which sessions are appropriate at each
  distance-from-race phase (base / build / peak / taper).

Structure strings speak in E/M/T/I/R and HR zones; the model resolves them to
concrete steps using the athlete's training_paces / hr_zones and training_mode.
`flavors` maps to coach_style: personas change WHICH quality flavors appear,
never how much quality the week holds.
"""

from __future__ import annotations

PHASES = ("base", "build", "peak", "taper")

ALL = ("default", "chill", "strict")

LIBRARY: list[dict] = [
    # --- easy / recovery -------------------------------------------------------
    {
        "id": "easy_run",
        "name": "Easy run",
        "workout_type": "easy_run",
        "phases": list(PHASES),
        "flavors": list(ALL),
        "structure": "Steady E pace (z1-z2) for the full duration. Single step.",
    },
    {
        "id": "easy_strides",
        "name": "Easy run + strides",
        "workout_type": "easy_run",
        "phases": list(PHASES),
        "flavors": list(ALL),
        "structure": "E pace, then 4-6 x (20s @ R pace, 60-90s easy jog). "
                     "Strides = relaxed fast leg turnover, not sprints.",
    },
    {
        "id": "recovery_jog",
        "name": "Recovery jog",
        "workout_type": "recovery",
        "phases": list(PHASES),
        "flavors": list(ALL),
        "structure": "Very easy (bottom of z1 / slower than E). Single short step.",
    },
    # --- long runs --------------------------------------------------------------
    {
        "id": "long_easy",
        "name": "Classic long run",
        "workout_type": "long_run",
        "phases": ["base", "build", "peak"],
        "flavors": list(ALL),
        "structure": "E pace (z1-z2) throughout. Single step.",
    },
    {
        "id": "long_fast_finish",
        "name": "Fast-finish long run (Pfitzinger)",
        "workout_type": "long_run",
        "phases": ["build", "peak"],
        "flavors": ["default", "strict"],
        "structure": "First 70-80% @ E, final 20-30% @ M pace (or z3). Two steps.",
    },
    {
        "id": "long_progression",
        "name": "Progression long run",
        "workout_type": "long_run",
        "phases": ["build", "peak"],
        "flavors": ["default", "chill"],
        "structure": "Thirds: E -> upper E -> M pace (z2 -> z3). Three steps, "
                     "each one gear quicker; finish strong, not strained.",
    },
    {
        "id": "long_mp_segments",
        "name": "Long run with M-pace segments (Pfitzinger)",
        "workout_type": "long_run",
        "phases": ["peak"],
        "flavors": ["default", "strict"],
        "structure": "E base with 2-3 x (10-15min @ M pace, 5min E float) in the "
                     "middle. Marathon-specific; only with a primary race >= half.",
    },
    # --- threshold --------------------------------------------------------------
    {
        "id": "tempo_continuous",
        "name": "Continuous tempo (Daniels T)",
        "workout_type": "tempo",
        "phases": ["build", "peak", "taper"],
        "flavors": list(ALL),
        "structure": "WU 10-15min E + 20-40min @ T pace (z3-z4) + CD 10min E. "
                     "Comfortably hard, controlled.",
    },
    {
        "id": "cruise_intervals",
        "name": "Cruise intervals (Daniels T)",
        "workout_type": "tempo",
        "phases": ["build", "peak"],
        "flavors": ["default", "strict"],
        "structure": "WU 15min E + 3-5 x (1.6km or 8-10min @ T pace, 60-90s easy "
                     "jog) + CD 10min E. More T volume than continuous tempo at "
                     "the same strain.",
    },
    {
        "id": "tempo_sandwich",
        "name": "Tempo sandwich",
        "workout_type": "tempo",
        "phases": ["build", "peak"],
        "flavors": ["chill", "default"],
        "structure": "WU 10min E + 2 x (12-15min @ T, 3min easy) + CD 10min E. "
                     "The break keeps it friendly while banking T time.",
    },
    # --- VO2max / intervals -----------------------------------------------------
    {
        "id": "vo2_classic",
        "name": "VO2max intervals (Daniels I)",
        "workout_type": "intervals",
        "phases": ["build", "peak"],
        "flavors": ["default", "strict"],
        "structure": "WU 15min E + 5-6 x (800-1000m or 3-4min @ I pace / z5, "
                     "equal-time easy jog recovery) + CD 10min E.",
    },
    {
        "id": "hill_repeats",
        "name": "Hill repeats",
        "workout_type": "intervals",
        "phases": ["base", "build"],
        "flavors": list(ALL),
        "structure": "WU 15min E + 6-10 x (60-90s uphill hard @ I effort, jog "
                     "down recovery) + CD 10min E. Strength + form with less "
                     "impact than track work.",
    },
    {
        "id": "fartlek_surges",
        "name": "Fartlek surges",
        "workout_type": "intervals",
        "phases": ["base", "build", "peak"],
        "flavors": ["chill", "default"],
        "structure": "WU 10min E + 8-12 x (1-2min strong @ ~T-I feel, equal easy "
                     "float) + CD 10min E. Unstructured feel, structured dose.",
    },
    {
        "id": "reps_speed",
        "name": "Speed reps (Daniels R)",
        "workout_type": "intervals",
        "phases": ["peak", "taper"],
        "flavors": ["default", "strict"],
        "structure": "WU 15min E + 8-10 x (200-400m @ R pace, full 2-3min jog "
                     "recovery) + CD 10min E. Fast but never straining; stop when "
                     "form degrades.",
    },
    {
        "id": "taper_sharpener",
        "name": "Taper sharpener",
        "workout_type": "intervals",
        "phases": ["taper"],
        "flavors": list(ALL),
        "structure": "WU 10min E + 4-5 x (60-90s @ race pace, 2min easy) + CD "
                     "10min E. Keeps the legs awake without adding fatigue.",
    },
]


def phase_for(days_to_primary_race: int | None) -> str:
    """Lydiard-style phase from distance to the primary race."""
    if days_to_primary_race is None or days_to_primary_race > 84:
        return "base"
    if days_to_primary_race <= 13:
        return "taper"
    if days_to_primary_race <= 42:
        return "peak"
    return "build"


def library_menu(phase: str, coach_style: str) -> list[dict]:
    """The compact template menu handed to the planner prompt: only templates
    valid for this phase, quality flavored by the coach persona (easy/long/
    recovery templates always pass so every persona can build a full week)."""
    style = coach_style if coach_style in ALL else "default"
    out = []
    for t in LIBRARY:
        if phase not in t["phases"]:
            continue
        if style not in t["flavors"]:
            continue
        out.append({k: t[k] for k in ("id", "name", "workout_type", "structure")})
    return out
