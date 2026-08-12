"""Rank repeat callers by SUABILITY, which is not the same as spamminess.

The rotating-DID campaign is the loudest thing in the data and also the least
collectable: an operation that burns numbers by design leaves nothing to serve
and nothing to collect. The defendants worth finding are the quiet ones -- real
businesses with a name, an address, assets, and insurance, that happen to run
aggressive telemarketing.

So this module scores three axes separately and refuses to average them:

  ATTRIBUTION   Can this caller be named and served? Driven by line type,
                a stable CNAM, and whether real conversations happened.
  VIOLATION     How much statutory exposure exists? Call count, and calls
                that continued after a recorded revocation.
  COLLECTABILITY Is there anything to recover? A named business with a
                registered agent is collectable; a burner DID is not.

A tier is assigned from the combination, because attribution GATES the other
two -- perfect violation facts against an unidentifiable caller are worth zero.
"""
from __future__ import annotations

# Call duration is a WEAK legitimacy signal and was originally over-trusted here.
# Advance-fee scams hold multi-minute conversations by design -- the pitch needs
# time to build trust and extract an SSN or bank number. A 3-minute call is
# therefore evidence of a human on the line, not of a lawful business.
#
# What actually separates a suable business from an offshore ring is the LINE:
# a real company answers on a line its carrier can tie to a subscriber, while a
# fraud operation dials from wholesale VoIP precisely because it cannot be
# traced. So VoIP caps attribution no matter how long the calls ran.
REAL_CONVERSATION_S = 120
BRIEF_S = 30
VOIP_ATTRIBUTION_CAP = 0.35


def repeat_callers(con, min_calls: int = 2, exclude_campaign: bool = True):
    """Unknown inbound numbers called min_calls+ times, excluding the campaign."""
    sql = """
        SELECT n.* FROM numbers n
        WHERE n.call_count >= ?
    """
    if exclude_campaign:
        sql += " AND n.number NOT IN (SELECT number FROM campaign_numbers)"
    sql += " ORDER BY n.call_count DESC, n.max_duration_s DESC"
    return con.execute(sql, (min_calls,)).fetchall()


def complaint_profile(con, number: str) -> dict:
    """Complaints already stored locally that name this exact number."""
    row = con.execute("""
        SELECT COUNT(*) n,
               SUM(CASE WHEN LOWER(COALESCE(call_type,'')) LIKE '%prerecorded%'
                        OR LOWER(COALESCE(call_type,'')) LIKE '%auto%'
                   THEN 1 ELSE 0 END) pre
        FROM complaints WHERE caller_id_number = ?
    """, (number,)).fetchone()
    return {"complaints": row["n"] or 0, "prerecorded": row["pre"] or 0}


def score(row, complaints: dict, revocations: int = 0) -> dict:
    """Return tier plus the reasoning, so a human can audit every call."""
    reasons: list[str] = []

    # --- ATTRIBUTION -------------------------------------------------------
    attribution = 0.0
    line = (row["line_type"] or "").upper()
    if line == "WIRELESS":
        attribution += 0.30
        reasons.append("wireless line (subscriber on file with carrier)")
    elif line == "CLEC_ILEC":
        attribution += 0.25
        reasons.append("landline/CLEC (subscriber on file)")
    elif line == "VOIP_WHOLESALE":
        attribution += 0.05
        reasons.append("wholesale VoIP (disposable, weak attribution)")

    if row["max_duration_s"] >= REAL_CONVERSATION_S:
        attribution += 0.45
        reasons.append(f"held a real conversation ({row['max_duration_s']//60}m"
                       f"{row['max_duration_s']%60:02d}s)")
    elif row["max_duration_s"] >= BRIEF_S:
        attribution += 0.20
        reasons.append("brief connects only")
    else:
        reasons.append("never connected meaningfully")

    if row["answered_count"] >= 2:
        attribution += 0.15
        reasons.append(f"{row['answered_count']} answered calls")

    if line == "VOIP_WHOLESALE" and attribution > VOIP_ATTRIBUTION_CAP:
        attribution = VOIP_ATTRIBUTION_CAP
        reasons.append("attribution CAPPED: wholesale VoIP has no traceable subscriber")
    attribution = min(attribution, 1.0)

    # --- VIOLATION ---------------------------------------------------------
    violation = min(row["call_count"] / 12.0, 1.0) * 0.6
    if revocations:
        violation += 0.4
        reasons.append(f"{revocations} recorded revocation(s) -- willfulness, 3x damages")
    if complaints["complaints"]:
        reasons.append(f"{complaints['complaints']} FCC complaint(s) name this number")
    if complaints["prerecorded"]:
        reasons.append(f"{complaints['prerecorded']} report prerecorded voice -- 227(b)")
    violation = min(violation, 1.0)

    # --- COLLECTABILITY ----------------------------------------------------
    # A caller that talks at length and holds a non-disposable line is almost
    # certainly an operating business with assets. That is what makes a
    # judgment worth obtaining.
    if row["max_duration_s"] >= REAL_CONVERSATION_S and line in ("WIRELESS", "CLEC_ILEC"):
        collectable = 0.9
    elif line in ("WIRELESS", "CLEC_ILEC"):
        collectable = 0.4
    else:
        # Long calls from wholesale VoIP are the advance-fee signature, not a
        # sign of an operating business with assets to collect from.
        collectable = 0.1

    # --- TIER --------------------------------------------------------------
    # Attribution gates everything: you cannot sue who you cannot name.
    if attribution >= 0.6 and complaints["complaints"] > 0 and row["call_count"] >= 2:
        tier = "A"   # identifiable business WITH a telemarketing complaint history
    elif attribution >= 0.6 and collectable >= 0.6:
        tier = "B"   # identifiable business, no complaint history -- verify first
    elif attribution >= 0.35:
        tier = "C"   # partially identifiable, needs enrichment or a callback
    else:
        tier = "D"   # disposable / unattributable -- not worth pursuing

    return {
        "tier": tier,
        "attribution": round(attribution, 2),
        "violation": round(violation, 2),
        "collectability": round(collectable, 2),
        "reasons": reasons,
    }


def build(con, min_calls: int = 2):
    out = []
    for row in repeat_callers(con, min_calls=min_calls):
        comp = complaint_profile(con, row["number"])
        s = score(row, comp)
        out.append({
            "number": row["number"],
            "calls": row["call_count"],
            "answered": row["answered_count"],
            "max_duration_s": row["max_duration_s"],
            "first": row["first_seen"], "last": row["last_seen"],
            "geo": row["geo"] or "",
            "carrier": row["carrier_name"] or "",
            "line_type": row["line_type"] or "",
            "complaints": comp["complaints"],
            **s,
        })
    order = {"A": 0, "B": 1, "C": 2, "D": 3}
    return sorted(out, key=lambda d: (order[d["tier"]],
                                      -d["violation"], -d["attribution"]))
