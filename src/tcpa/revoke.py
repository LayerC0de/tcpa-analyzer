"""Revocations: the owner telling a caller to stop.

A revocation is the willfulness predicate -- calls placed after it can carry up
to $1,500 each instead of $500. That makes it the fact most worth getting
right, and the easiest to overstate. So every record here is:

  - tied to ONE number, and for a verbal request to the specific answered call
    it was said on. Calls from that number afterwards are what it affects.
    Extending it to other numbers in a rotating campaign is a legal argument
    for counsel, never something this tool does automatically.
  - labelled with its basis:
      recording     the call was recorded; the file is the evidence
      document      a letter, email, or text (e.g. replying STOP)
      recollection  the owner remembers saying it; entered after the fact.
                    Real evidence (testimony), but the weakest kind.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

METHODS = ("verbal", "written", "sms")
BASES = ("recording", "recollection", "document")
MATCH_WINDOW_MIN = 10   # carrier records round call times to the minute

INBOUND = "('INCOMING','MISSED','REJECTED','BLOCKED')"


def answered_calls(con, number: str) -> list:
    return con.execute("""
        SELECT id, local_iso, ts_utc, duration_s, duration_estimated, source FROM calls
        WHERE number = ? AND direction = 'INCOMING' AND duration_s > 0
          AND dup_of_device = 0
        ORDER BY ts_utc
    """, (number,)).fetchall()


def calls_after(con, number: str, ts_utc: int) -> int:
    return con.execute(f"""
        SELECT COUNT(*) FROM calls
        WHERE number = ? AND ts_utc > ? AND dup_of_device = 0
          AND direction IN {INBOUND}
    """, (number, ts_utc)).fetchone()[0]


def _times(calls) -> str:
    return ", ".join(f"{c['local_iso'][11:16]} ({c['duration_s']}s)" for c in calls)


def match_call(con, number: str, at: str):
    """The answered call from `number` at `at` ('YYYY-MM-DD' or 'YYYY-MM-DD HH:MM')."""
    calls = answered_calls(con, number)
    day = at.strip()[:10]
    that_day = [c for c in calls if c["local_iso"][:10] == day]
    if not that_day:
        raise ValueError(f"no answered call from this number on {day} -- a verbal "
                         f"request needs a call you picked up")
    if len(at.strip()) <= 10:
        if len(that_day) > 1:
            raise ValueError(f"{len(that_day)} answered calls on {day}: "
                             f"{_times(that_day)} -- give --at '{day} HH:MM'")
        return that_day[0]
    want = datetime.fromisoformat(at.strip())
    gap = lambda c: abs((datetime.fromisoformat(c["local_iso"][:19]) - want)
                        .total_seconds()) / 60
    best = min(that_day, key=gap)
    if gap(best) > MATCH_WINDOW_MIN:
        raise ValueError(f"no answered call within {MATCH_WINDOW_MIN} min of {at}; "
                         f"that day: {_times(that_day)}")
    return best


def record(con, number: str, at: str, basis: str, method: str = "verbal",
           said: str | None = None, evidence: str | None = None,
           note: str | None = None, tz: str = "America/New_York") -> dict:
    """Record one revocation. `number` must already be normalized."""
    if method not in METHODS:
        raise ValueError(f"method must be one of {', '.join(METHODS)}")
    if basis not in BASES:
        raise ValueError(f"basis must be one of {', '.join(BASES)}")
    if basis in ("recording", "document") and not evidence:
        raise ValueError(f"a '{basis}' basis needs the file: --recording PATH")
    if evidence:
        path = Path(evidence).expanduser()
        if not path.is_file():
            raise ValueError(f"evidence file not found: {evidence}")
        evidence = str(path.resolve())

    if method == "verbal":
        call = match_call(con, number, at)
        call_id, ts, local_iso = call["id"], call["ts_utc"], call["local_iso"][:19]
    else:
        # A letter or text is not said on a call; take the time as given.
        local = datetime.fromisoformat(at.strip() if len(at.strip()) > 10
                                       else at.strip() + " 12:00")
        ts = int(local.replace(tzinfo=ZoneInfo(tz)).timestamp() * 1000)
        call_id, local_iso = None, local.isoformat(sep=" ")[:19]

    dup = con.execute("""
        SELECT id FROM revocations WHERE number = ?
          AND ((call_id IS NOT NULL AND call_id = ?) OR ts_utc = ?)
    """, (number, call_id, ts)).fetchone()
    if dup:
        raise ValueError(f"already recorded as revocation #{dup['id']}")

    cur = con.execute("""
        INSERT INTO revocations (number, ts_utc, method, evidence_path, verbatim,
                                 call_id, basis, note, entered_on, local_iso)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (number, ts, method, evidence, (said or "").strip() or None, call_id,
          basis, (note or "").strip() or None, date.today().isoformat(), local_iso))
    con.commit()
    return {"id": cur.lastrowid, "local_iso": local_iso,
            "calls_after": calls_after(con, number, ts)}


def listing(con, number: str | None = None) -> list[dict]:
    sql = "SELECT * FROM revocations"
    args: tuple = ()
    if number:
        sql += " WHERE number = ?"
        args = (number,)
    rows = con.execute(sql + " ORDER BY ts_utc", args).fetchall()
    return [{**dict(r), "calls_after": calls_after(con, r["number"], r["ts_utc"])
             if r["number"] else None} for r in rows]


def remove(con, rid: int) -> bool:
    cur = con.execute("DELETE FROM revocations WHERE id = ?", (rid,))
    con.commit()
    return cur.rowcount == 1


def applies(rev, call_number: str, call_ts: int, campaign_id: int | None = None) -> bool:
    """Does this revocation cover a call? Same number, later in time -- or a
    revocation deliberately recorded at campaign level (number NULL)."""
    if call_ts <= rev["ts_utc"]:
        return False
    if rev["number"]:
        return rev["number"] == call_number
    return campaign_id is not None and rev["campaign_id"] == campaign_id
