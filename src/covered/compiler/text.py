"""Whitespace normalization shared by clause checks and mock fixture lookup."""

import hashlib


def normalize_whitespace(text: str) -> str:
    """Collapse every run of whitespace (spaces, tabs, newlines) into one space."""
    return " ".join(text.split())


def text_sha256(text: str) -> str:
    """Hex SHA-256 of the whitespace-normalized text (mock fixture file name)."""
    return hashlib.sha256(normalize_whitespace(text).encode("utf-8")).hexdigest()


def clause_in_text(clause: str, text: str) -> bool:
    """True if `clause` is a literal substring of `text`, ignoring whitespace runs.

    An empty clause never matches (it would be a substring of anything).
    """
    needle = normalize_whitespace(clause)
    return bool(needle) and needle in normalize_whitespace(text)
