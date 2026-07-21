"""Server-side slash-shortcut expansion.

The user's message stays exactly what they typed — it is persisted and displayed
verbatim (kind="shortcut") — while the expansion below is what actually enters
the LLM-facing history. Keeping expansion server-side means the client renders
shortcuts honestly and old clients can't drift from the prompt wording.

The frontend keeps its own command+hint list for the slash menu; commands here
are the source of truth for what expands. Unknown /commands pass through as
plain text (and /help never reaches the server — it's handled client-side).
"""

from __future__ import annotations

# command -> {"bare": prompt when no args follow, "with_args": template with {args}}
SHORTCUTS: dict[str, dict[str, str]] = {
    "/week": {
        "bare": "Give me a summary of my week and how my plan is going.",
        "with_args": "Give me a summary of my week and how my plan is going. "
                     "In particular: {args}",
    },
    "/replan": {
        "bare": "Please look at my recent training and recovery data and propose "
                "any adjustments to my upcoming plan.",
        "with_args": "Please look at my recent training and recovery data and propose "
                     "any adjustments to my upcoming plan. Context from me: {args}",
    },
    "/race-plan": {
        "bare": "Build me a race plan for my goal race: pacing strategy, fueling, "
                "and how the final training weeks should look.",
        "with_args": "Build me a race plan for my goal race: pacing strategy, fueling, "
                     "and how the final training weeks should look. Notes: {args}",
    },
    "/sport": {
        "bare": "I want to fit another sport (not running) into my week. Ask me what "
                "sport, which day, and roughly how long — then set that day "
                "accordingly and rebalance my week around it.",
        "with_args": "I'm doing another sport instead of a normal run: {args}. Set that "
                     "day accordingly (day intent) and rebalance my week around it.",
    },
}


def expand(text: str) -> tuple[str, bool]:
    """Return (llm_text, is_shortcut) for a raw user message."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return text, False
    command, _, rest = stripped.partition(" ")
    entry = SHORTCUTS.get(command.lower())
    if entry is None:
        return text, False
    rest = rest.strip()
    if rest:
        return entry["with_args"].format(args=rest), True
    return entry["bare"], True
