"""Build an evidence packet a TCPA attorney can evaluate in one sitting.

What a lawyer needs to triage an intake, in the order they will look for it:

  1. Is this person a plaintiff? -- consent posture, revocation, DNC registration
  2. Is there a defendant? -- attribution, and whether it is collectable
  3. How much is it worth? -- countable violations, per statutory section
  4. Can it be proven? -- what evidence exists and where it came from

The packet answers those in that order and, critically, states what is NOT
established. An intake packet that hides its gaps wastes the attorney's time and
destroys the client's credibility on the first phone call.
"""
from __future__ import annotations

from datetime import datetime

from ..phone import display

PER_CALL = 500
PER_CALL_WILLFUL = 1500


def build(con, campaign_id: int | None = None, number: str | None = None,
          jurisdiction: str = "[STATE]", dnc_since: str | None = None) -> str:
    if campaign_id:
        members = [r["number"] for r in con.execute(
            "SELECT number FROM campaign_numbers WHERE campaign_id=?", (campaign_id,))]
        title = f"CAMPAIGN #{campaign_id}"
    elif number:
        members = [number]
        title = f"CALLER {display(number)}"
    else:
        raise ValueError("pass campaign_id or number")
    if not members:
        return "No numbers to report."

    marks = ",".join("?" * len(members))
    calls = con.execute(f"""
        SELECT local_iso, local_date, local_hour, number, duration_s, source,
               duration_estimated
        FROM calls
        WHERE number IN ({marks})
          AND direction IN ('INCOMING','MISSED','REJECTED','BLOCKED')
          AND dup_of_device = 0
        ORDER BY ts_utc
    """, tuple(members)).fetchall()
    if not calls:
        return "No calls on record."

    revs = con.execute(f"""
        SELECT ts_utc, method, verbatim, evidence_path FROM revocations
        WHERE number IN ({marks}) OR campaign_id = ?
        ORDER BY ts_utc
    """, tuple(members) + (campaign_id or -1,)).fetchall()

    carriers = con.execute(f"""
        SELECT carrier_name, carrier_ocn, line_type, COUNT(*) c
        FROM numbers WHERE number IN ({marks}) AND carrier_name IS NOT NULL
        GROUP BY carrier_name ORDER BY c DESC
    """, tuple(members)).fetchall()

    ents = con.execute(
        "SELECT * FROM entities WHERE campaign_id = ?", (campaign_id or -1,)).fetchall()

    comp = con.execute(f"""
        SELECT COUNT(*) n,
               SUM(CASE WHEN LOWER(COALESCE(call_type,'')) LIKE '%prerecorded%'
                   THEN 1 ELSE 0 END) pre,
               SUM(exact_match) exact
        FROM complaints WHERE npa_nxx IN (SELECT DISTINCT substr(number,1,6)
                                          FROM numbers WHERE number IN ({marks}))
    """, tuple(members)).fetchone()

    after_rev = 0
    if revs:
        first_rev = min(r["ts_utc"] for r in revs)
        after_rev = sum(1 for c in calls
                        if con.execute("SELECT ts_utc FROM calls WHERE local_iso=? LIMIT 1",
                                       (c["local_iso"],)).fetchone()[0] > first_rev)

    est_only = sum(1 for c in calls if c["duration_estimated"])
    out = [
        f"TCPA INTAKE PACKET -- {title}",
        "=" * 78,
        f"Generated {datetime.now().strftime('%Y-%m-%d')} by tcpa-analyzer",
        "This is an organized evidence summary, not legal advice, and not an",
        "assessment of whether a claim exists.",
        "",
        "1. PLAINTIFF POSTURE",
        "-" * 78,
        f"  Jurisdiction: {jurisdiction}",
        f"  National DNC registration date: {dnc_since or '[NOT PROVIDED -- supply this]'}",
        f"  Documented revocations: {len(revs)}",
    ]
    for r in revs:
        stamp = datetime.utcfromtimestamp(r["ts_utc"] / 1000).strftime("%Y-%m-%d")
        out.append(f"    {stamp}  {r['method']}  "
                   f"{'recording: ' + r['evidence_path'] if r['evidence_path'] else 'no recording'}")
    if not revs:
        out.append("    NONE RECORDED. Without a documented revocation there is no")
        out.append("    willfulness predicate, and damages stay at the base rate.")
    out += ["",
            "2. DEFENDANT ATTRIBUTION",
            "-" * 78,
            f"  Calling numbers involved: {len(members)}"]
    if carriers:
        for c in carriers:
            out.append(f"    {c['c']:>3} numbers  {c['carrier_name']} "
                       f"(OCN {c['carrier_ocn']}, {c['line_type']})")
        out += ["  Carriers hold the number blocks; they are the subpoena and",
                "  traceback path, NOT the caller."]
    else:
        out.append("    Carrier data not resolved. Run `enrich` before filing.")

    if ents:
        out.append("")
        for e in ents:
            out.append(f"  Entity: {e['legal_name']}  [{e['role']}]")
            out.append(f"    Registration: {e['state_of_reg']}")
            out.append(f"    Registered agent: {e['registered_agent']}")
            out.append(f"    Agent address: {e['agent_address']}")
            out.append(f"    Source: {e['source_url']}")
    else:
        out += ["", "  NO LEGAL ENTITY IDENTIFIED. This is the blocking issue:",
                "  a campaign without a named, servable defendant cannot be filed."]

    out += ["",
            "3. COUNTABLE VIOLATIONS",
            "-" * 78,
            f"  Total calls on record: {len(calls)}",
            f"  Calls after first documented revocation: {after_rev}",
            f"  Calls outside 8am-9pm local: "
            f"{sum(1 for c in calls if c['local_hour'] < 8 or c['local_hour'] >= 21)}",
            "",
            "  Statutory exposure, arithmetic only -- NOT a valuation:",
            f"    {len(calls)} x ${PER_CALL} = ${len(calls) * PER_CALL:,}",
            f"    {after_rev} x ${PER_CALL_WILLFUL} (willful) = ${after_rev * PER_CALL_WILLFUL:,}",
            "  Counsel decides which calls are actually countable and under which",
            "  section. 227(c)(5) requires 2+ calls in 12 months; 227(b) requires",
            "  proving an ATDS or artificial/prerecorded voice.",
            "",
            "4. EVIDENCE AND ITS LIMITS",
            "-" * 78,
            f"  Device call log records: {sum(1 for c in calls if c['source'] == 'android')}",
            f"  Carrier records: {sum(1 for c in calls if c['source'] == 'att')}",
            f"  Records with estimated (billed-minute) duration: {est_only}",
            "    Carrier records round to the minute and omit calls that were",
            "    never answered. Treat their durations as approximate.",
            ]
    if comp and comp["n"]:
        out += ["",
                f"  Third-party FCC complaints about these number blocks: {comp['n']}",
                f"    reporting a prerecorded voice: {comp['pre'] or 0}",
                f"    naming these exact numbers: {comp['exact'] or 0}",
                "    Complaints about neighbouring numbers in the same block are",
                "    circumstantial, not direct evidence about these calls."]

    out += ["", "5. WHAT IS NOT ESTABLISHED", "-" * 78]
    gaps = []
    if not ents:
        gaps.append("No legal entity identified -- no one to serve.")
    if not revs:
        gaps.append("No documented revocation -- no willfulness multiplier.")
    if not dnc_since:
        gaps.append("DNC registration date not supplied -- 227(c) anchor missing.")
    if not any(c["source"] == "android" for c in calls):
        gaps.append("No device-log records -- unanswered calls likely missing.")
    gaps.append("No call recordings referenced -- ATDS/prerecorded voice unproven.")
    out += [f"  - {g}" for g in gaps]

    out += ["", "FULL CALL LOG", "-" * 78]
    for c in calls:
        d = f"{c['duration_s'] // 60}m{c['duration_s'] % 60:02d}s" if c["duration_s"] else "no answer"
        est = " (est)" if c["duration_estimated"] else ""
        out.append(f"  {c['local_iso']}  {display(c['number'])}  {d}{est}  [{c['source']}]")

    out += ["", "=" * 78,
            "Produced by tcpa-analyzer. Not legal advice. Verify every fact",
            "independently before relying on it."]
    return "\n".join(out)
