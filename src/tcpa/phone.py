"""NANP phone number normalization.

Every number entering the system goes through `normalize()` exactly once.
Call logs mix E.164 (+17165551234), national (7165551234), and formatted
("+1 716-555-1234") representations of the same line; comparing raw strings
silently double-counts them.
"""
from __future__ import annotations

import re

TOLL_FREE_NPA = frozenset({"800", "833", "844", "855", "866", "877", "888"})

_DIGITS = re.compile(r"\D")


def normalize(raw: str | None) -> str | None:
    """Return a bare 10-digit NANP number, or None if it isn't one.

    Short codes, international numbers, and blocked/unknown caller IDs all
    return None -- they are real call events but have no dialable identity,
    so they must not be grouped together under a shared key.
    """
    if not raw:
        return None
    digits = _DIGITS.sub("", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    if digits[0] in "01" or digits[3] in "01":
        return None  # invalid NPA or NXX
    return digits


def npa(number: str) -> str:
    """Area code."""
    return number[:3]


def nxx(number: str) -> str:
    """Central office / exchange code."""
    return number[3:6]


def npa_nxx(number: str) -> str:
    """The 6-digit block a number belongs to.

    DID blocks are allocated in contiguous ranges, so two spam numbers sharing
    an NPA-NXX usually means one dialer leasing one block. This is the single
    strongest infrastructure signal available from a call log alone.
    """
    return number[:6]


def is_toll_free(number: str) -> bool:
    return npa(number) in TOLL_FREE_NPA


def display(number: str | None) -> str:
    if not number or len(number) != 10:
        return number or "(unknown)"
    return f"({number[:3]}) {number[3:6]}-{number[6:]}"
