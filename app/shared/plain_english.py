from __future__ import annotations

"""
Discrete math class chapter 1: Plain-English labels for machine-readable status codes.
Plain-English display labels for the machine-readable status codes used
throughout Optimization (pressure flags, recommended actions, priorities,
trends) and the tier-change log's `source` field.

This is purely cosmetic. The underlying SNAKE_CASE / hyphenated values keep
driving filtering, sorting, and comparisons unchanged everywhere else in the
app -- this module only maps them to friendlier text at display time.
"""

PRESSURE_FLAG_LABELS: dict[str, str] = {
    "NORMAL": "Normal usage",
    "ELEVATED_PRESSURE_80_PLUS": "Elevated — over 80% of cap",
    "HIGH_PRESSURE_90_PLUS": "High — over 90% of cap",
    "AT_OR_ABOVE_CAP": "At or over cap",
    "ABOVE_CAP_110_PLUS": "Over cap by 10%+",
}

PRESSURE_TREND_LABELS: dict[str, str] = {
    "INCREASING_PRESSURE": "Rising",
    "DECREASING_PRESSURE": "Falling",
    "STABLE_PRESSURE": "Steady",
}

RECOMMENDED_ACTION_LABELS: dict[str, str] = {
    "MONITOR_MORE_HISTORY_NEEDED": "Keep watching — not enough history yet",
    "CONSIDER_MOVE_UP_TIER": "Consider a higher tier",
    "CONSIDER_MOVE_DOWN_TIER": "Consider a lower tier",
    "MONITOR_RECENT_SPIKE": "Keep watching — recent spike",
    "NO_CHANGE": "No change needed",
}

REVIEW_PRIORITY_LABELS: dict[str, str] = {
    "ACTIONABLE": "Action needed",
    "MONITOR": "Keep an eye on",
    "INFORMATIONAL": "For your information",
}

TIER_ASSIGNMENT_SOURCE_LABELS: dict[str, str] = {
    "assigned": "Manually assigned",
    "default": "Tierlist default",
}

TIER_CHANGE_SOURCE_LABELS: dict[str, str] = {
    "manual": "Manually changed",
    "manual-reset": "Manually reset to Baseline",
    "reset-to-tierlist": "Reset to tierlist",
    "reset-all-to-tierlist": "Bulk reset to tierlist",
    "import": "Tierlist import",
    "tierlist_history": "From tierlist history (no exact date)",
}

# One combined lookup so a single filter can translate any of the above
# without callers needing to know which category a value belongs to.
STATUS_LABELS: dict[str, str] = {
    **PRESSURE_FLAG_LABELS,
    **PRESSURE_TREND_LABELS,
    **RECOMMENDED_ACTION_LABELS,
    **REVIEW_PRIORITY_LABELS,
    **TIER_ASSIGNMENT_SOURCE_LABELS,
    **TIER_CHANGE_SOURCE_LABELS,
}


def plain_english(value: object) -> str:
    """Translate a machine status code to a plain-English label.

    Falls back to the old "SNAKE_CASE" -> "Snake Case" conversion for any
    value not in STATUS_LABELS, so new/unmapped codes still degrade gracefully.
    """
    if not value:
        return "—"
    text = str(value)
    if text in STATUS_LABELS:
        return STATUS_LABELS[text]
    return text.replace("_", " ").replace("-", " ").title()
