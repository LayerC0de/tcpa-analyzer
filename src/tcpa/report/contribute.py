"""Build a corpus contribution: shareable observations about spam infrastructure.

WHAT IS SAFE TO SHARE, AND WHY

The numbers that called you are the *caller's* numbers, not yours. Publishing
"this number placed calls in April 2026" says nothing about who received them.
That asymmetry is what makes a community corpus possible at all.

THE RISK THAT IS NOT OBVIOUS

Any single spam number is harmless. The complete SET of numbers that called you
is not -- it is effectively a fingerprint of you, and anyone holding another copy
of that set (a data broker, or the operation itself) could correlate it back.

So contributions are deliberately limited to numbers already attributed to a
detected CAMPAIGN, never the full list of unknown callers. A campaign is shared
infrastructure that many people saw; your long tail of one-off callers is closer
to a personal signature.

Two further mitigations:

  - Observation counts are bucketed and dates coarsened to year-month. Exact
    counts and timestamps are behavioural detail about the recipient.
  - No field describes the recipient at all: no number, area code, carrier,
    state, contact name, or duration. Not even coarsened. Location plus timing
    is the classic re-identification pair, so neither is included.

Anything not on ALLOWED_FIELDS is rejected by CI rather than trusted to review.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import fingerprint as fp

SCHEMA_VERSION = 1

# Allowlist enforced by scripts/validate_contribution.py in CI. A field that is
# not listed here cannot be merged, whatever a contributor writes by hand.
ALLOWED_FIELDS = {
    "schema", "generated_utc", "tool_version", "contributor_note",
    "fingerprint", "numbers",
}
ALLOWED_NUMBER_FIELDS = {
    "number", "npa_nxx", "carrier_name", "carrier_ocn", "line_type",
    "first_month", "last_month", "observations",
}
# Fields that must NEVER appear. Named explicitly so the failure message can
# explain the risk rather than emit a generic schema error.
FORBIDDEN_HINTS = {
    "own_number", "recipient", "contact_name", "local_iso", "ts_utc",
    "duration_s", "geo", "state", "zip", "name", "email", "address",
}


def _bucket(n: int) -> str:
    for hi, label in ((2, "1-2"), (5, "3-5"), (10, "6-10"), (25, "11-25")):
        if n <= hi:
            return label
    return "25+"


def build(con, campaign_id: int, note: str | None = None) -> dict:
    """Assemble a contribution for one detected campaign."""
    members = [r["number"] for r in con.execute(
        "SELECT number FROM campaign_numbers WHERE campaign_id=? ORDER BY number",
        (campaign_id,))]
    if not members:
        raise ValueError(f"campaign {campaign_id} has no members")

    marks = ",".join("?" * len(members))
    rows = con.execute(f"""
        SELECT n.number, n.npa_nxx, n.carrier_name, n.carrier_ocn, n.line_type,
               n.call_count, n.first_seen, n.last_seen
        FROM numbers n WHERE n.number IN ({marks}) ORDER BY n.number
    """, tuple(members)).fetchall()

    numbers = [{
        "number": r["number"],
        "npa_nxx": r["npa_nxx"],
        "carrier_name": r["carrier_name"],
        "carrier_ocn": r["carrier_ocn"],
        "line_type": r["line_type"],
        # Year-month only. A precise first/last contact is a fact about the
        # recipient's timeline, not about the caller's infrastructure.
        "first_month": (r["first_seen"] or "")[:7] or None,
        "last_month": (r["last_seen"] or "")[:7] or None,
        "observations": _bucket(r["call_count"]),
    } for r in rows]

    return {
        "schema": SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "tool_version": __import__("tcpa").__version__,
        "contributor_note": note,
        "fingerprint": fp.build(con, campaign_id),
        "numbers": numbers,
    }


def audit(doc: dict) -> list[str]:
    """Return human-readable problems. Empty list means the document is clean.

    Run locally before opening a pull request; CI runs the same checks.
    """
    problems = []
    for key in doc:
        if key not in ALLOWED_FIELDS:
            problems.append(f"top-level field not allowed: {key!r}")
    for key in FORBIDDEN_HINTS:
        if key in doc:
            problems.append(f"forbidden field present: {key!r}")

    for i, n in enumerate(doc.get("numbers", [])):
        for key in n:
            if key not in ALLOWED_NUMBER_FIELDS:
                problems.append(f"numbers[{i}]: field not allowed: {key!r}")
        num = n.get("number") or ""
        if not (isinstance(num, str) and num.isdigit() and len(num) == 10):
            problems.append(f"numbers[{i}]: number must be 10 digits, got {num!r}")
        for field in ("first_month", "last_month"):
            v = n.get(field)
            if v is not None and not (isinstance(v, str) and len(v) == 7 and v[4] == "-"):
                problems.append(f"numbers[{i}]: {field} must be YYYY-MM, got {v!r}")

    fpd = doc.get("fingerprint", {})
    for key in ("own_number", "recipient_number", "timestamps"):
        if key in fpd:
            problems.append(f"fingerprint contains recipient data: {key!r}")

    note = doc.get("contributor_note")
    if isinstance(note, str) and any(ch.isdigit() for ch in note):
        problems.append("contributor_note contains digits -- remove anything "
                        "that could be a phone number or date")
    return problems
