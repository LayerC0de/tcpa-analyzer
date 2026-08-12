"""Text message analysis.

Under the TCPA a text to a cell phone is a "call" (*Satterfield v. Simon &
Schuster*), so unsolicited marketing texts carry the same $500/$1,500 statutory
damages as voice calls. Carrier exports are the only source for them -- the
Android call log export contains no text history at all.

Two classes of sender need separating, because they have opposite profiles:

  SHORT CODES (5-6 digits) are A2P messaging leased through aggregators and tied
  to a registered brand. They are the MOST attributable senders in the entire
  dataset -- a short code cannot be spoofed and its lessee is documented. But
  they are also overwhelmingly legitimate: 2FA codes, delivery alerts,
  appointment reminders. Volume alone means nothing here.

  LONG CODES (10-digit) are cheap, disposable, and routinely used for spam.
  Attribution is weak for the same reasons it is weak for voice DIDs.

As with voice, replying to a sender is treated as evidence of a relationship and
removes them from consideration.
"""
from __future__ import annotations

from collections import Counter, defaultdict

SHORT_CODE_MAX_LEN = 6


def _known(con) -> set[str]:
    """Numbers the account holder engaged with, by any channel."""
    rows = con.execute("""
        SELECT number FROM texts WHERE direction='OUTGOING' AND number IS NOT NULL
        UNION
        SELECT number FROM calls WHERE direction='OUTGOING' AND number IS NOT NULL
        UNION
        SELECT number FROM calls
        WHERE contact_name IS NOT NULL AND contact_name != '' AND number IS NOT NULL
    """).fetchall()
    return {r[0] for r in rows}


def summarize(con) -> dict:
    known = _known(con)
    rows = con.execute("""
        SELECT number, number_raw, kind, local_date, ts_utc
        FROM texts WHERE direction='INCOMING'
    """).fetchall()

    by_sender: dict[str, list] = defaultdict(list)
    short_codes: dict[str, list] = defaultdict(list)
    for r in rows:
        raw = (r["number_raw"] or "").strip()
        digits = "".join(c for c in raw if c.isdigit())
        if r["number"] is None and 0 < len(digits) <= SHORT_CODE_MAX_LEN:
            short_codes[digits].append(r)
        elif r["number"]:
            by_sender[r["number"]].append(r)

    unknown = {n: v for n, v in by_sender.items() if n not in known}
    replied = {n: v for n, v in by_sender.items() if n in known}

    return {
        "total_incoming": len(rows),
        "short_code_senders": len(short_codes),
        "short_code_messages": sum(len(v) for v in short_codes.values()),
        "long_code_senders": len(by_sender),
        "unknown_senders": len(unknown),
        "unknown_messages": sum(len(v) for v in unknown.values()),
        "replied_senders": len(replied),
        "unknown": unknown,
        "short_codes": short_codes,
    }


def rank_unknown(summary: dict, min_messages: int = 2) -> list[dict]:
    """Unknown long-code senders, most persistent first."""
    out = []
    for number, msgs in summary["unknown"].items():
        if len(msgs) < min_messages:
            continue
        dates = sorted(m["local_date"] for m in msgs)
        span_days = len(set(dates))
        kinds = Counter(m["kind"] for m in msgs)
        # Messages arriving in a single burst read as one campaign push; the same
        # count spread over months is a sender who will not stop.
        out.append({
            "number": number,
            "messages": len(msgs),
            "distinct_days": span_days,
            "first": dates[0],
            "last": dates[-1],
            "kinds": dict(kinds),
            "persistent": span_days >= 3,
        })
    return sorted(out, key=lambda d: (-d["messages"], d["first"]))


def rank_short_codes(summary: dict, top: int = 15) -> list[dict]:
    out = []
    for code, msgs in summary["short_codes"].items():
        dates = sorted(m["local_date"] for m in msgs)
        out.append({
            "code": code, "messages": len(msgs),
            "distinct_days": len(set(dates)),
            "first": dates[0], "last": dates[-1],
        })
    return sorted(out, key=lambda d: -d["messages"])[:top]
