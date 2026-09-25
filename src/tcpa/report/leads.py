"""Leads that sit outside the detected campaign, for the intake packet.

Everything here is reported SEPARATELY from the campaign and never added to
its call counts (see CLAUDE.md, invariant 2). A lead is something an attorney
may want to pursue; it is not corroborated evidence about the campaign.
"""
from __future__ import annotations

from collections import Counter

from ..enrich import resporg
from ..phone import display, is_canadian

INBOUND = "('INCOMING','MISSED','REJECTED','BLOCKED')"
WIDTH = 78


def _campaign_numbers(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT number FROM campaign_numbers")}


def _same_company(a: str | None, b: str | None) -> bool:
    key = lambda s: "".join(ch for ch in (s or "").casefold() if ch.isalnum())
    return bool(a and b) and (key(a).startswith(key(b)) or key(b).startswith(key(a)))


def _basis(r, holder_name: str | None) -> str:
    """Where the holder shown came from, without overstating a Somos check.

    Somos's public form shows only who holds a number TODAY, by name. It
    confirms the holder shown only when that is the same company; for a number
    that has since moved or been released, say what Somos shows instead.
    """
    if r["method"] == "auto":
        return "resporgs.com (lead)"
    if r["method"] != "manual":
        return "not looked up"
    if _same_company(r["resporg_name"], holder_name):
        return "confirmed on somos.com"
    return f"somos.com now: {r['resporg_name'] or 'available'}"


def _toll_free(con) -> list[str]:
    in_campaign = _campaign_numbers(con)
    callers = [r for r in resporg.worklist(con)
               if r["calls"] and r["number"] not in in_campaign]
    out = ["  A. TOLL-FREE CALLERS",
           "  A toll-free number has no carrier block. The RespOrg managing it in the",
           "  Somos registry is the subpoena path -- it is NOT the caller, and it only",
           "  knows its own customer, who may be a reseller or call-center platform.",
           ""]
    if not callers:
        return out + ["    No toll-free numbers called this line.", ""]

    def holder(r):
        # Who managed the number when it last called -- the subpoena target for
        # that call -- falling back to the latest known holder.
        if r["at_call"]:
            return r["at_call"]["resporg_id"], r["at_call"]["resporg_name"]
        return r["resporg_id"], r["resporg_name"]

    checked = [r for r in callers if r["checked_on"]]
    out += [f"    {len(callers)} toll-free numbers called; RespOrg looked up for "
            f"{len(checked)}.",
            "    'Holder' is who managed the number on the date of its last call,",
            "    from registry history; 'now' is its current registry status."]
    shown = [r for r in callers if r["calls"] >= 2 or r["method"] == "manual"]
    if shown:
        out += ["", f"    {'number':<16}{'calls':>5}  {'last call':<11}{'resporg':<8}"
                    f"{'holder':<22}{'now':<9}basis"]
        for r in shown:
            rid, name = holder(r)
            basis = _basis(r, name)
            now = r["status"] or ""
            out.append(f"    {display(r['number']):<16}{r['calls']:>5}  "
                       f"{r['last_call'] or '-':<11}{rid or '-':<8}"
                       f"{(name or '')[:21]:<22}{now[:8]:<9}{basis}")

    rest = Counter(holder(r)[1] or "no registry record"
                   for r in callers if r not in shown and r["checked_on"])
    if rest:
        out += ["", f"    Single-call toll-free numbers, by holder "
                    f"({sum(rest.values())}):"]
        out += [f"      {n:>3}  {name}" for name, n in rest.most_common(8)]
        if len(rest) > 8:
            out.append(f"      ... {len(rest) - 8} more RespOrgs")

    retired = [r for r in callers
               if r["status"] and r["status"] not in ("WORKING", "NOT_FOUND")]
    if retired:
        out += ["", "    Retired since calling (disconnected or returned to the spare pool --",
                "    the burn-after-use signal; the holder at the time of the call is the",
                "    one that matters):"]
        for r in retired:
            rid, name = holder(r)
            out.append(f"      {display(r['number'])}  called {r['last_call']}  "
                       f"held by {rid or '?'} {name or ''}  -> {r['status']}")

    missing = [r for r in callers if r["status"] == "NOT_FOUND"]
    if missing:
        out += ["", "    No toll-free registry record at all (caller ID likely spoofed):"]
        out += [f"      {display(r['number'])}  {r['calls']} call(s), last {r['last_call']}"
                for r in missing]
    out += ["",
            "    Platform RespOrgs (Amazon, Twilio, Five9, Genesys, Bandwidth) keep",
            "    customer account records; a subpoena can name the account holder.",
            "    Large carriers (AT&T, Verizon) manage millions of numbers, so a",
            "    number resolving to one of them says little on its own.",
            ""]
    return out


def _callbacks(con) -> list[str]:
    rows = [r for r in resporg.worklist(con) if r["fcc_callbacks"]]
    out = ["  B. FCC COMPLAINT CALLBACK NUMBERS"]
    if not rows:
        return out + ["    No toll-free callback numbers in stored FCC complaints.", ""]
    checked = [r for r in rows if r["checked_on"]]
    # Last known holder: a callback number since released still points to
    # the RespOrg that managed it while complaints were being filed.
    by = Counter(r["resporg_name"] or "no registry record" for r in checked)
    out += [f"    {len(rows)} toll-free callback numbers named in "
            f"{sum(r['fcc_callbacks'] for r in rows)} stored complaints; "
            f"{len(checked)} looked up.",
            "    By RespOrg:"]
    for name, n in by.most_common(6):
        out.append(f"      {n:>3}  ({n / len(checked) * 100:>3.0f}%)  {name}")
    top = sorted(rows, key=lambda r: -r["fcc_callbacks"])[:5]
    out += ["", "    Most-named callback numbers:"]
    out += [f"      {display(r['number'])}  {r['fcc_callbacks']} complaints  "
            f"{r['resporg_id'] or '-'}  {r['resporg_name'] or 'no record'}" for r in top]
    out += ["",
            "    These are OTHER people's complaints, stored because they name numbers",
            "    in this campaign's DID blocks -- circumstantial, not evidence about",
            "    calls to this line. Callback numbers often lead to the seller rather",
            "    than the dialer. Concentration on a few RespOrgs is a lead; whether it",
            "    is meaningful depends on how large those RespOrgs are. All results",
            "    here are automated (resporgs.com) unless confirmed on somos.com.",
            ""]
    return out


def _canadian(con, months: int = 12) -> list[str]:
    in_campaign = _campaign_numbers(con)
    nums = [r["number"] for r in con.execute("SELECT number FROM numbers")
            if is_canadian(r["number"]) and r["number"] not in in_campaign]
    out = ["  C. CANADIAN CALLER IDS"]
    if not nums:
        return out + ["    No unknown calls from Canadian area codes.", ""]
    marks = ",".join("?" * len(nums))
    calls = con.execute(f"""
        SELECT number, local_date, direction, duration_s FROM calls
        WHERE number IN ({marks}) AND dup_of_device = 0 AND direction IN {INBOUND}
        ORDER BY ts_utc
    """, nums).fetchall()
    per_number = Counter(c["number"] for c in calls)
    by_month = Counter(c["local_date"][:7] for c in calls)
    answered = sorted(c["duration_s"] for c in calls
                      if c["direction"] == "INCOMING" and c["duration_s"] > 0)

    out += [f"    {len(calls)} calls from {len(nums)} numbers across "
            f"{len({n[:3] for n in nums})} Canadian area codes; "
            f"{sum(1 for v in per_number.values() if v == 1)} numbers called once.",
            "    By month (most recent last):"]
    out += [f"      {m}  {by_month[m]:>3}" for m in sorted(by_month)[-months:]]
    if answered:
        out.append(f"    Answered: {len(answered)} calls, "
                   f"{answered[0]}-{answered[-1]}s (median {answered[len(answered)//2]}s).")
    out += ["",
            "    Many unrelated numbers from across Canada, each calling once, is",
            "    consistent with spoofed caller ID. If spoofed, the Canadian carriers",
            "    holding these numbers had no part in the calls and are not a path to",
            "    the caller. Nothing links these numbers to the campaign above; they",
            "    are not counted in it. Single calls meet 227(c)(5)'s 2-call threshold",
            "    only if the calls can be attributed to one caller -- a recording of",
            "    the pitch is the realistic way to do that.",
            ""]
    return out


def section(con) -> list[str]:
    return (["6. OTHER LEADS -- NOT PART OF THIS CAMPAIGN", "-" * WIDTH,
             "  Reported separately and excluded from every count above.", ""]
            + _toll_free(con) + _callbacks(con) + _canadian(con))
