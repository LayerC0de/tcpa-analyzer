"""RespOrg attribution for toll-free numbers.

Toll-free numbers have no NPA-NXX block, so `nanpa` cannot resolve them. Their
equivalent is the Responsible Organization (RespOrg) on file in the Somos
TFNRegistry: the company that manages the number's routing record. It is the
subpoena / traceback entry point for a toll-free caller, exactly as the block
holder is for a DID.

Two ways a result gets in, kept apart by the `method` column:

  auto    resporgs.com's JSON history endpoint -- a free public directory built
          from Somos registry reports, with no key and a robots.txt that allows
          all agents. A third party: treat its answer as a LEAD.
  manual  the owner ran the official lookup on somos.com and recorded the
          answer. This is the version to cite in a filing.

PRIVACY: an automated lookup sends the caller's full toll-free number to
resporgs.com. It is the caller's number, never the owner's, and nothing else
from the call record goes with it -- but it is more than `nanpa` sends, which
is only the 6-digit prefix.

LIMITATIONS that apply to every record here:
  - A RespOrg is NOT the subscriber. It knows its customer, who may itself be
    a reseller, so reaching the caller can take a second subpoena.
  - Toll-free caller ID can be spoofed. A spoofed number's RespOrg had nothing
    to do with the call, and a call log cannot tell the difference.
  - The largest RespOrgs manage millions of numbers. Many callers sharing one
    of them means little; sharing a small one means a lot.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from datetime import date

from ..phone import is_toll_free, normalize

ENDPOINT = "https://resporgs.com/api/history/{number}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) tcpa-analyzer/0.1"
RATE_LIMIT_S = 1.5   # free community service; one request per number
AUTO_SOURCE = "resporgs.com (Somos registry reports)"
RECHECK_DAYS = 30    # RespOrgs change rarely; don't re-query more often

RESPORG_ID = re.compile(r"^[A-Z0-9]{3}[0-9]{2}$")


def parse_number(raw: str) -> str:
    """Normalize a toll-free number, or raise ValueError."""
    number = normalize(raw)
    if number is None:
        raise ValueError(f"not a NANP number: {raw!r}")
    if not is_toll_free(number):
        raise ValueError(f"not a toll-free number: {raw!r} -- "
                         f"use `enrich` for ordinary numbers")
    return number


def parse_id(raw: str) -> str:
    rid = (raw or "").strip().upper()
    if not RESPORG_ID.match(rid):
        raise ValueError(f"not a RespOrg ID (5 characters, e.g. ABC01): {raw!r}")
    return rid


# --- automated lookup --------------------------------------------------------

def fetch(number: str, timeout: int = 25) -> dict:
    """Raw JSON history for one normalized number. Raises on network or API error."""
    req = urllib.request.Request(ENDPOINT.format(number=number),
                                 headers={"User-Agent": UA})
    body = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
    data = json.loads(body)
    # The API reports bad input with HTTP 200 and an error field.
    if "error" in data:
        raise ValueError(f"resporgs.com: {data['error']}")
    return data


def _clean(text: str | None) -> str | None:
    # Names arrive with non-breaking spaces ("Independent\xa0Resporg"), which
    # print as garbage on a Windows console and break exact-match grouping.
    return " ".join((text or "").split()) or None


def _events(data: dict) -> list[dict]:
    return sorted(data.get("events") or [], key=lambda e: e.get("ts") or "")


def _code(event: dict) -> str | None:
    # Spare-pool events carry no RespOrg; their holder "name" is a label such
    # as "Returned to spare pool", which must never be read as a company.
    holder = event.get("holder") or {}
    return (holder.get("code") or event.get("org") or "").upper() or None


def _holder(event: dict) -> dict:
    holder = event.get("holder") or {}
    return {"resporg_id": _code(event),
            "resporg_name": _clean(holder.get("name")),
            "resporg_group": _clean(holder.get("group"))}


def parse_history(data: dict) -> dict:
    """Reduce a history response to the last known holder and current status.

    The holder is the most recent event that names a RespOrg, so a number since
    returned to the spare pool still shows who last managed it; `status` (e.g.
    SPARE) says it is no longer theirs. A number with no events at all has no
    registry record in the window the source covers: a caller ID with nothing
    behind it was probably spoofed.
    """
    events = _events(data)
    if not events:
        return {"resporg_id": None, "resporg_name": None, "resporg_group": None,
                "status": "NOT_FOUND", "status_since": None}
    held = [e for e in events if _code(e)]
    last = events[-1]
    holder = _holder(held[-1]) if held else \
        {"resporg_id": None, "resporg_name": None, "resporg_group": None}
    return {**holder,
            "status": (last.get("status") or "").upper() or None,
            "status_since": last.get("date")}


def holder_on(data: dict, day: str) -> dict | None:
    """Who managed the number on `day` (YYYY-MM-DD), or None if nobody did.

    For a number burned after use this is the question that matters: the
    current holder may be the spare pool, or a different company entirely.
    """
    before = [e for e in _events(data) if (e.get("date") or "") <= day]
    if not before:
        return None
    last = before[-1]
    if not _code(last) or (last.get("status") or "").upper() == "SPARE":
        return None
    return {**_holder(last), "status": (last.get("status") or "").upper(),
            "since": last.get("date")}


def _store(con, number: str, parsed: dict, method: str, source: str,
           checked_on: str, note: str | None = None, raw: dict | None = None):
    con.execute("""
        INSERT INTO resporg_lookups
            (number, resporg_id, resporg_name, resporg_group, status, status_since,
             checked_on, method, source, note, raw_json)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(number, method, checked_on) DO UPDATE SET
            resporg_id=excluded.resporg_id, resporg_name=excluded.resporg_name,
            resporg_group=excluded.resporg_group, status=excluded.status,
            status_since=excluded.status_since, source=excluded.source,
            note=excluded.note, raw_json=excluded.raw_json,
            recorded_at=CURRENT_TIMESTAMP
    """, (number, parsed["resporg_id"], parsed["resporg_name"],
          parsed["resporg_group"], parsed["status"], parsed["status_since"],
          checked_on, method, source, note,
          json.dumps(raw, separators=(",", ":")) if raw is not None else None))


def due(con, numbers: list[str], recheck_days: int = RECHECK_DAYS) -> list[str]:
    """Numbers with no automated lookup in the last `recheck_days`."""
    recent = {r[0] for r in con.execute("""
        SELECT number FROM resporg_lookups
        WHERE method = 'auto' AND checked_on >= date('now', ?)
    """, (f"-{recheck_days} days",))}
    return [n for n in numbers if n not in recent]


def lookup(con, numbers: list[str], sleep: float = RATE_LIMIT_S,
           verbose: bool = True) -> dict:
    """Look up each normalized toll-free number and log the result."""
    stats = {"resolved": 0, "not_found": 0, "failed": 0}
    today = date.today().isoformat()
    for i, number in enumerate(numbers):
        if i:
            time.sleep(sleep)
        try:
            data = fetch(number)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            stats["failed"] += 1
            if verbose:
                print(f"  FAILED {number}: {exc}")
            continue
        parsed = parse_history(data)
        _store(con, number, parsed, "auto", AUTO_SOURCE, today, raw=data)
        con.commit()
        stats["not_found" if parsed["resporg_id"] is None else "resolved"] += 1
        if verbose:
            who = (f"{parsed['resporg_id']}  {parsed['resporg_name'] or ''}"
                   if parsed["resporg_id"] else "no registry record")
            print(f"  {number}  {who}  [{parsed['status']}]")
    return stats


# --- manual entry ------------------------------------------------------------

def record_manual(con, number: str, resporg_id: str | None, source: str,
                  name: str | None = None, status: str | None = None,
                  checked_on: str | None = None, note: str | None = None) -> None:
    """Record a lookup the owner made on somos.com. `number` is normalized.

    The public somos.com form names the company but does not show the RespOrg
    ID, so a name alone is accepted. Never fill in an ID from an automated
    lookup here -- that would attribute a third-party answer to Somos.
    """
    # Anything asserted in a filing needs a citation a judge can check.
    if not source or not source.strip():
        raise ValueError("a source is required (e.g. 'somos.com lookup')")
    # An "available" result names no holder at all, so a status alone (SPARE)
    # is a valid observation too: the number is no longer anyone's.
    if not resporg_id and not (name or "").strip() and not (status or "").strip():
        raise ValueError("record a RespOrg ID (--id), company name (--name), "
                         "or status (--status, e.g. SPARE for 'available')")
    checked = date.fromisoformat(checked_on).isoformat() if checked_on \
        else date.today().isoformat()
    parsed = {"resporg_id": parse_id(resporg_id) if resporg_id else None,
              "resporg_name": _clean(name),
              "resporg_group": None,
              "status": (status or "").strip().upper() or None,
              "status_since": None}
    _store(con, number, parsed, "manual", source.strip(), checked,
           note=(note or "").strip() or None)
    con.commit()


# --- reporting -----------------------------------------------------------------

def history(con, number: str) -> list:
    """Every lookup for a normalized number, newest first; manual wins ties."""
    return con.execute("""
        SELECT * FROM resporg_lookups WHERE number = ?
        ORDER BY checked_on DESC, method = 'manual' DESC, id DESC
    """, (number,)).fetchall()


def toll_free_numbers(con) -> dict[str, dict]:
    """Toll-free numbers worth a lookup, keyed by number.

    Two origins: unknown toll-free numbers that called the owner, and
    toll-free callback numbers named in stored FCC complaints -- the latter
    often lead to the seller rather than the dialer.
    """
    items: dict[str, dict] = {}

    def item(number):
        return items.setdefault(number, {"number": number, "calls": 0,
                                         "last_call": None, "fcc_callbacks": 0})

    for r in con.execute(
            "SELECT number, call_count, last_seen FROM numbers WHERE is_toll_free = 1"):
        it = item(r["number"])
        it["calls"], it["last_call"] = r["call_count"], r["last_seen"]

    for r in con.execute("""
        SELECT advertiser_phone, COUNT(*) c FROM complaints
        WHERE advertiser_phone IS NOT NULL GROUP BY advertiser_phone
    """):
        if is_toll_free(r["advertiser_phone"]):
            item(r["advertiser_phone"])["fcc_callbacks"] = r["c"]
    return items


def worklist(con) -> list[dict]:
    """toll_free_numbers() with the latest lookup attached, most active first.

    `at_call` is the holder on the date of the most recent call, from the
    stored registry history; None when no history or nobody held it then.
    """
    out = []
    for number, it in toll_free_numbers(con).items():
        rows = history(con, number)
        latest = rows[0] if rows else None
        raw = next((r["raw_json"] for r in rows if r["raw_json"]), None)
        at_call = holder_on(json.loads(raw), it["last_call"]) \
            if raw and it["last_call"] else None
        out.append({**it,
                    "resporg_id": latest["resporg_id"] if latest else None,
                    "resporg_name": latest["resporg_name"] if latest else None,
                    # A manual Somos entry names the holder but rarely a status;
                    # fall back to the newest lookup that recorded one.
                    "status": next((r["status"] for r in rows if r["status"]), None),
                    "method": latest["method"] if latest else None,
                    "checked_on": latest["checked_on"] if latest else None,
                    "at_call": at_call})
    return sorted(out, key=lambda d: (d["last_call"] or "", d["fcc_callbacks"],
                                      d["calls"]), reverse=True)
