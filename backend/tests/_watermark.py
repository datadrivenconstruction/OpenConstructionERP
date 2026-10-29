"""Shared helper for source-hygiene tests: drop whole provenance signatures before scanning.

Mirrors scripts/check_zero_width.py: only the complete signatures are exempt; a lone
character, or a signature with any one character changed or missing, still fails.
"""

from __future__ import annotations

_SIG_A = (chr(0x200B) + chr(0x200C) + chr(0x200D) + chr(0x2060)) * 4
_SIG_B = chr(0x200C) + chr(0x2060) + chr(0x200D)


def strip_marks(text: str) -> str:
    """Return ``text`` without whole provenance signatures (longest first)."""
    return text.replace(_SIG_A, "").replace(_SIG_B, "")
