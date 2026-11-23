"""Normalisation rules shared by request schemas and services."""

from __future__ import annotations

import re

_PHONE_SEPARATORS = re.compile(r"[\s\-().]")
# "+" followed by 8-15 ASCII digits, no leading zero (E.164 style).
_E164 = re.compile(r"\+[1-9][0-9]{7,14}")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def normalize_phone_number(raw: str) -> str:
    """Return the canonical form used for storage and duplicate detection.

    Accepts spaces, dashes, dots and parentheses as separators and a leading
    "00" instead of "+". The number must include its country code.

    >>> normalize_phone_number("+1 (999) 999-9999")
    '+19999999999'
    """
    value = _PHONE_SEPARATORS.sub("", raw.strip())
    if value.startswith("00"):
        value = "+" + value[2:]
    if not _E164.fullmatch(value):
        raise ValueError(
            "phone_number must be an international number starting with + and the country code, "
            "for example +19999999999"
        )
    return value


def normalize_email(raw: str) -> str:
    value = raw.strip().lower()
    if len(value) > 320 or not _EMAIL.fullmatch(value):
        raise ValueError("email must be a valid email address")
    return value
