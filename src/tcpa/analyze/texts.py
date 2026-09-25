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

A sender is treated as a relationship if the owner reached out FIRST (texted or
called before the sender ever did), held a conversation (3+ replies), saved them
as a contact, or listed them in known_numbers.txt. One or two replies AFTER the
sender texted are not: that may well have been STOP, a revocation, not consent. Carrier
exports carry no message bodies, so the tool cannot tell which -- replies are
counted and flagged for the owner to check on the phone instead of hiding the
sender, which is what an earlier version did.
"""
from __future__ import annotations

from collections import Counter, defaultdict

SHORT_CODE_MAX_LEN = 6

# A STOP is one reply, occasionally two. Three or more replies is a
# conversation, and a conversation is a relationship -- including ones that
# began before the data window, which otherwise look like the sender "texted
# first". Calls do not get this rule: an owner investigating a robocaller may
# call it back several times.
CONVERSATION_REPLIES = 3


def _known(con) -> set[str]:
    """Numbers with a real relationship: a contact name, the known-numbers list,
    the owner making first contact by text or call, or a text conversation."""
    rows = con.execute(f"""
        SELECT number FROM calls
        WHERE contact_name IS NOT NULL AND contact_name != '' AND number IS NOT NULL
        UNION
        SELECT number FROM known_numbers
        UNION
        SELECT number FROM texts WHERE direction = 'OUTGOING' AND number IS NOT NULL
        GROUP BY number HAVING COUNT(*) >= {CONVERSATION_REPLIES}
        UNION
        SELECT number FROM (
            SELECT number, ts_utc, direction FROM texts WHERE number IS NOT NULL
            UNION ALL
            SELECT number, ts_utc, direction FROM calls WHERE number IS NOT NULL
              AND direction IN ('OUTGOING','INCOMING','MISSED','REJECTED','BLOCKED')
        )
        GROUP BY number
        HAVING MIN(CASE WHEN direction = 'OUTGOING' THEN ts_utc END)
             < COALESCE(MIN(CASE WHEN direction != 'OUTGOING' THEN ts_utc END), 9e18)
    """).fetchall()
    return {r[0] for r in rows}


def _replies(con) -> dict[str, list[int]]:
    """Owner's outgoing text times, keyed by long-code number or short code."""
    out: dict[str, list[int]] = defaultdict(list)
    for r in con.execute("""
        SELECT number, number_raw, ts_utc FROM texts WHERE direction = 'OUTGOING'
    """):
        key = r["number"] or "".join(c for c in (r["number_raw"] or "") if c.isdigit())
        if key:
            out[key].append(r["ts_utc"])
    return out


def _reply_stats(msgs, replies: list[int]) -> dict:
    # Messages that kept arriving after the owner first replied: if that reply
    # was STOP, these are the ones sent after a revocation.
    first = min(replies) if replies else None
    return {"replies": len(replies),
            "after_reply": sum(1 for m in msgs if first is not None and m["ts_utc"] > first)}


def summarize(con) -> dict:
    known = _known(con)
    replies = _replies(con)
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
    first_contact = {n: v for n, v in by_sender.items() if n in known}

    return {
        "total_incoming": len(rows),
        "short_code_senders": len(short_codes),
        "short_code_messages": sum(len(v) for v in short_codes.values()),
        "long_code_senders": len(by_sender),
        "unknown_senders": len(unknown),
        "unknown_messages": sum(len(v) for v in unknown.values()),
        "replied_unknown": sum(1 for n in unknown if replies.get(n)),
        "known_senders": len(first_contact),
        "unknown": unknown,
        "short_codes": short_codes,
        "replies": replies,
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
            **_reply_stats(msgs, summary["replies"].get(number, [])),
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
            **_reply_stats(msgs, summary["replies"].get(code, [])),
        })
    return sorted(out, key=lambda d: -d["messages"])[:top]
