from __future__ import annotations

from rich.theme import Theme

LOBSTER_PALETTE = {
    "accent": "#FF5A2D",
    "success": "#2FBF71",
    "warn": "#FFB020",
    "error": "#E23D2D",
    "muted": "#8B7F77",
}


def build_rich_theme() -> Theme:
    return Theme(
        {
            "accent": LOBSTER_PALETTE["accent"],
            "success": LOBSTER_PALETTE["success"],
            "warn": LOBSTER_PALETTE["warn"],
            "error": LOBSTER_PALETTE["error"],
            "muted": LOBSTER_PALETTE["muted"],
            "heading": f"bold {LOBSTER_PALETTE['accent']}",
        }
    )
