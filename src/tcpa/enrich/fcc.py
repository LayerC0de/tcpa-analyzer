"""FCC consumer complaint cross-reference (open data, no API key).

Dataset `vakf-fz8e` -- "Consumer Complaints Data - Unwanted Calls" -- carries
~1.8M consumer-filed complaints with the reported caller ID, the callback
number the pitch advertised, and crucially the *type* of call: values like
"Prerecorded Voice" and "Autodialed".

Why this matters more than it looks:

  Section 227(b) liability attaches to prerecorded/artificial-voice and ATDS
  calls, and needs only ONE call rather than the two that 227(c)(5) requires.
  The hard part is proving the technology, which a call log cannot show.
  Independent complainants describing numbers from the *same DID blocks* as
  prerecorded is strong circumstantial evidence of how a campaign dials.

  It is circumstantial, not direct. Complaints about neighbouring numbers in a
  block are not complaints about the specific number that called you, and any
  filing must characterise them that way. `exact_match` on each stored row
  records which kind of evidence it is, so the two are never conflated.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

DATASET = "https://opendata.fcc.gov/resource/vakf-fz8e.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) tcpa-analyzer/0.1"
PAGE = 1000
RATE_LIMIT_S = 0.4

PRERECORDED_MARKERS = ("prerecorded", "auto", "robo", "artificial")


def _dashed(number: str) -> str:
    """This dataset stores caller IDs as 555-123-4567."""
    return f"{number[:3]}-{number[3:6]}-{number[6:]}"


def _get(params: dict, timeout: int = 45) -> list[dict]:
    url = DATASET + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace"))


def by_number(number: str) -> list[dict]:
    """Complaints naming this exact number as the caller ID."""
    return _get({"caller_id_number": _dashed(number), "$limit": PAGE})


def by_block(npa_nxx: str) -> list[dict]:
    """Every complaint about any number in one NPA-NXX block, paged."""
    prefix = f"{npa_nxx[:3]}-{npa_nxx[3:]}"
    out, offset = [], 0
    while True:
        page = _get({
            "$where": f"starts_with(caller_id_number, '{prefix}')",
            "$limit": PAGE, "$offset": offset,
            "$order": "issue_date DESC",
        })
        out.extend(page)
        if len(page) < PAGE:
            return out
        offset += PAGE
        time.sleep(RATE_LIMIT_S)


def by_advertiser(number: str) -> list[dict]:
    """Every nationwide complaint naming this callback number in the pitch.

    Callback numbers are the opposite of burner DIDs: an operation must be able
    to RECEIVE on them, so they persist and accumulate a national complaint
    history. That history is the best free proxy for a campaign's true scale --
    and its date range shows when the operation rotated to a new line.
    """
    return _get({"advertiser_business_phone_number": _dashed(number), "$limit": PAGE,
                 "$select": "id,issue_date,state,type_of_call_or_messge,caller_id_number"})


def profile_callbacks(con, min_complaints: int = 2) -> list[dict]:
    """Rank callback numbers seen in this campaign by national complaint volume."""
    rows = con.execute("""
        SELECT advertiser_phone, COUNT(*) local FROM complaints
        WHERE advertiser_phone IS NOT NULL
        GROUP BY advertiser_phone HAVING local >= ? ORDER BY local DESC
    """, (min_complaints,)).fetchall()

    out = []
    for r in rows:
        number = r["advertiser_phone"]
        try:
            national = by_advertiser(number)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            national = []
        dates = sorted(x.get("issue_date", "")[:10] for x in national if x.get("issue_date"))
        out.append({
            "number": number,
            "local": r["local"],
            "national": len(national),
            "states": len({x.get("state") for x in national if x.get("state")}),
            "prerecorded": sum(1 for x in national if is_prerecorded(x)),
            "first": dates[0] if dates else None,
            "last": dates[-1] if dates else None,
        })
        time.sleep(RATE_LIMIT_S)
    return sorted(out, key=lambda d: -d["national"])


def is_prerecorded(row: dict) -> bool:
    kind = (row.get("type_of_call_or_messge") or "").lower()
    return any(m in kind for m in PRERECORDED_MARKERS)


# Complainants type these by hand, so the field carries placeholder junk that
# would otherwise surface as the top "lead" in a callback-number ranking.
_JUNK_PHONE = {"", "NONE", "UNKNOWN", "NA", "N/A", "0000000000", "1111111111",
               "1234567890", "9999999999"}


def clean_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = "".join(c for c in str(raw) if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if str(raw).strip().upper() in _JUNK_PHONE or digits in _JUNK_PHONE:
        return None
    if len(digits) != 10 or len(set(digits)) <= 2:
        return None
    return digits


def _store(con, rows: list[dict], campaign_numbers: set[str]) -> int:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    added = 0
    for r in rows:
        cid = (r.get("caller_id_number") or "").replace("-", "")
        cur = con.execute("""
            INSERT OR IGNORE INTO complaints
              (fcc_id, caller_id_number, npa_nxx, advertiser_phone, call_type,
               issue, issue_date, state, zip, method, exact_match, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            r.get("id"), cid or None, cid[:6] if len(cid) == 10 else None,
            clean_phone(r.get("advertiser_business_phone_number")),
            r.get("type_of_call_or_messge"), r.get("issue"),
            (r.get("issue_date") or "")[:10], r.get("state"), r.get("zip"),
            r.get("method"), 1 if cid in campaign_numbers else 0, now,
        ))
        added += cur.rowcount
    con.commit()
    return added


def enrich_campaign(con, campaign_id: int, verbose: bool = True) -> dict:
    """Pull complaints for every DID block the campaign touches."""
    members = {r["number"] for r in con.execute(
        "SELECT number FROM campaign_numbers WHERE campaign_id=?", (campaign_id,))}
    blocks = sorted({n[:6] for n in members})

    stats = {"blocks": len(blocks), "complaints": 0, "prerecorded": 0,
             "exact": 0, "distinct_numbers": 0, "failed": 0}
    seen_numbers = set()

    for blk in blocks:
        try:
            rows = by_block(blk)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            stats["failed"] += 1
            if verbose:
                print(f"  FAILED {blk}: {exc}")
            continue
        _store(con, rows, members)
        pre = sum(1 for r in rows if is_prerecorded(r))
        nums = {(r.get("caller_id_number") or "").replace("-", "") for r in rows}
        seen_numbers |= nums
        stats["complaints"] += len(rows)
        stats["prerecorded"] += pre
        stats["exact"] += sum(1 for n in nums if n in members)
        if verbose:
            print(f"  {blk[:3]}-{blk[3:]}  {len(rows):>3} complaints, "
                  f"{len(nums):>3} numbers, {pre:>3} prerecorded")
        time.sleep(RATE_LIMIT_S)

    stats["distinct_numbers"] = len(seen_numbers)
    return stats
