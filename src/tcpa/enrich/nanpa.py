"""NPA-NXX-X carrier attribution via the public NANPA block-assignment data.

Free, no API key. Resolves each number to the carrier holding its **thousand
block** (NPA-NXX-X), which is materially more precise than NPA-NXX alone --
a single exchange is routinely split across a wireless carrier, an ILEC, and
a VoIP wholesaler, and only the block tells you which one issued the DID.

IMPORTANT LIMITATION: this identifies the *block holder*, not the current
subscriber. Numbers can be ported away from their original block. For dialer
DIDs that distinction rarely matters -- spam operations buy blocks wholesale
and don't port -- but never state in a filing that the block holder *is* the
caller. It is the carrier you subpoena, and the entry point for an ITG
traceback. That is its value.
"""
from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ENDPOINT = "https://localcallingguide.com/xmlprefix.php?npa={npa}&nxx={nxx}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) tcpa-analyzer/0.1"
RATE_LIMIT_S = 1.2  # be a good citizen: this is a free community service

# Name fragments used to classify a carrier's LINE TYPE -- wholesale VoIP versus
# wireless versus incumbent landline. This is a technical classification and
# nothing more.
#
# Appearing here is NOT an accusation. These are large, entirely legitimate
# carriers that sell numbers wholesale to thousands of customers, the same way a
# hosting provider sells servers. The classification is useful only because a
# spam campaign's numbers concentrating on one or two wholesalers identifies who
# holds the records worth subpoenaing.
#
# Do not add a carrier here because it showed up in your own call records. That
# would publish a private finding as though it were a general fact.
VOIP_WHOLESALE = (
    "ONVOY", "SINCH", "BANDWIDTH", "TWILIO", "TELNYX", "PEERLESS", "INTELIQUENT",
    "FLOWROUTE", "THINQ", "COMMIO", "IDT", "AIRESPRING", "VONAGE", "LEVEL 3",
    "LUMEN", "NEUTRAL TANDEM", "SYNIVERSE", "VOIP",
    "MAGICJACK", "CALLFIRE", "PLIVO", "VITELITY", "SIP", "TELECOM",
)
WIRELESS = ("CELLCO", "VERIZON WIRELESS", "T-MOBILE", "AT&T MOBILITY", "SPRINT",
            "NEW CINGULAR", "USCOC", "US CELLULAR", "METROPCS", "METRO PCS",
            "CRICKET", "BOOST")

# Carriers operate as families of per-state subsidiaries ("ONVOY, LLC - NC",
# "CORETEL KENTUCKY, INC. - KY"). Grouping by raw company name badly
# understates concentration: one operation buying DIDs from one carrier's
# state subsidiaries looks like a dozen unrelated carriers.
_FAMILY_SUFFIX = re.compile(
    r"\s*[-,]\s*[A-Z]{2}$"                      # trailing " - NC"
    r"|\s*,?\s*(LLC|INC\.?|CORP\.?|LP|CO\.?)\s*$"  # entity suffixes
    r"|\s+(OF\s+)?(ALABAMA|ALASKA|ARIZONA|ARKANSAS|CALIFORNIA|COLORADO|CONNECTICUT"
    r"|DELAWARE|FLORIDA|GEORGIA|HAWAII|IDAHO|ILLINOIS|INDIANA|IOWA|KANSAS|KENTUCKY"
    r"|LOUISIANA|MAINE|MARYLAND|MASSACHUSETTS|MICHIGAN|MINNESOTA|MISSISSIPPI"
    r"|MISSOURI|MONTANA|NEBRASKA|NEVADA|NEW\s+HAMPSHIRE|NEW\s+JERSEY|NEW\s+MEXICO"
    r"|NEW\s+YORK|NORTH\s+CAROLINA|NORTH\s+DAKOTA|OHIO|OKLAHOMA|OREGON"
    r"|PENNSYLVANIA|RHODE\s+ISLAND|SOUTH\s+CAROLINA|SOUTH\s+DAKOTA|TENNESSEE"
    r"|TEXAS|UTAH|VERMONT|VIRGINIA|WASHINGTON|WEST\s+VIRGINIA|WISCONSIN|WYOMING)\b")


def carrier_family(company: str) -> str:
    """Collapse per-state subsidiaries to the parent carrier name."""
    name = (company or "").upper().strip()
    prev = None
    while name and name != prev:
        prev = name
        name = _FAMILY_SUFFIX.sub("", name).strip(" ,-.")
    return name or "UNKNOWN"

_PREFIX_BLOCK = re.compile(r"<prefixdata>(.*?)</prefixdata>", re.S)


def _tag(block: str, name: str) -> str:
    m = re.search(rf"<{name}>(.*?)</{name}>", block, re.S)
    if not m:
        return ""
    return (m.group(1).replace("&amp;", "&").replace("&apos;", "'")
            .replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">").strip())


def classify(company: str) -> str:
    up = (company or "").upper()
    if any(w in up for w in WIRELESS):
        return "WIRELESS"
    if any(w in up for w in VOIP_WHOLESALE):
        return "VOIP_WHOLESALE"
    if not up:
        return "UNKNOWN"
    return "CLEC_ILEC"


def fetch_exchange(npa: str, nxx: str, timeout: int = 25) -> list[dict]:
    """Return every thousand-block record for one NPA-NXX."""
    req = urllib.request.Request(ENDPOINT.format(npa=npa, nxx=nxx), headers={"User-Agent": UA})
    body = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
    out = []
    for block in _PREFIX_BLOCK.findall(body):
        company = _tag(block, "company-name")
        out.append({
            "npa": _tag(block, "npa"), "nxx": _tag(block, "nxx"),
            "x": _tag(block, "x"),
            "ocn": _tag(block, "ocn"), "company": company,
            "carrier_type": classify(company),
            "rate_center": _tag(block, "rc"), "region": _tag(block, "region"),
            "lata": _tag(block, "lata"), "ilec": _tag(block, "ilec-name"),
        })
    return out


def _pick_block(records: list[dict], thousands_digit: str) -> dict | None:
    """Choose the record covering a specific number's thousand block.

    'A' means the whole exchange is assigned to one carrier; an exact digit
    match is more specific and wins over it.
    """
    exact = [r for r in records if r["x"] == thousands_digit]
    if exact:
        return exact[0]
    whole = [r for r in records if r["x"].upper() == "A"]
    return whole[0] if whole else (records[0] if records else None)


def enrich(con, numbers: list[str], sleep: float = RATE_LIMIT_S, verbose: bool = True) -> dict:
    """Resolve carrier for each number. Exchanges are fetched once and cached."""
    cache: dict[tuple[str, str], list[dict]] = {}
    stats = {"resolved": 0, "failed": 0, "exchanges_fetched": 0}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for number in numbers:
        npa, nxx, x = number[:3], number[3:6], number[6]
        key = (npa, nxx)
        if key not in cache:
            try:
                cache[key] = fetch_exchange(npa, nxx)
                stats["exchanges_fetched"] += 1
                if verbose:
                    print(f"  fetched {npa}-{nxx}  ({len(cache[key])} blocks)")
                time.sleep(sleep)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
                cache[key] = []
                if verbose:
                    print(f"  FAILED {npa}-{nxx}: {exc}")

        rec = _pick_block(cache[key], x)
        if not rec:
            stats["failed"] += 1
            continue
        con.execute("""
            UPDATE numbers SET carrier_name=?, carrier_ocn=?, line_type=?,
                   rate_center=?, lata=?, ilec_name=?, enriched_at=?
            WHERE number=?
        """, (rec["company"], rec["ocn"], rec["carrier_type"], rec["rate_center"],
              rec["lata"], rec["ilec"], now, number))
        stats["resolved"] += 1
    con.commit()
    return stats
