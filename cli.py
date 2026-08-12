#!/usr/bin/env python3
"""tcpa-analyzer -- command line entry point.

    python cli.py pull        # pull call log off a connected Android phone
    python cli.py ingest      # parse the latest raw dump into SQLite
    python cli.py analyze     # detect campaigns
    python cli.py report      # summary of what's in the database
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from tcpa import db                                  # noqa: E402
from tcpa.analyze import campaign as campaign_mod    # noqa: E402
from tcpa.ingest import android                      # noqa: E402
from tcpa.phone import display                       # noqa: E402

RAW_DIR = ROOT / "data" / "raw"
DEFAULT_RAW = RAW_DIR / "android_calllog.txt"


def cmd_pull(args):
    dest = Path(args.out) if args.out else DEFAULT_RAW
    print(f"pulling call log -> {dest}")
    android.pull(dest)
    print(f"  wrote {dest.stat().st_size:,} bytes")
    return cmd_ingest(argparse.Namespace(raw=str(dest), tz=args.tz))


def cmd_ingest(args):
    raw = Path(args.raw) if args.raw else DEFAULT_RAW
    if not raw.exists():
        sys.exit(f"no raw dump at {raw} -- run `pull` first")
    con = db.connect()
    records = android.parse(raw, tz_name=args.tz)
    added = android.load(con, records)
    total = con.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
    n = db.rebuild_numbers(con)
    print(f"parsed {len(records):,} rows; {added:,} new ({total:,} total calls)")
    print(f"rollup: {n:,} distinct unknown inbound numbers")
    con.close()


def cmd_ingest_att(args):
    from tcpa.ingest import att

    files = sorted((ROOT / "data" / "raw").glob("att_*.xlsx"))
    if not files:
        sys.exit("no att_*.xlsx in data/raw -- run scripts/organize_att.py first")

    con = db.connect()
    tot_calls = tot_dups = tot_texts = 0
    print(f"loading {len(files)} AT&T bill cycles\n")
    for f in files:
        parsed = att.parse(f, tz_name=args.tz)
        cs = att.load(con, parsed["calls"])
        ts = att.load_texts(con, parsed["texts"])
        tot_calls += cs["inserted"]
        tot_dups += cs["duplicates"]
        tot_texts += ts
        print(f"  {f.name:<20} {parsed['cycle']:<28} "
              f"calls +{cs['inserted']:<4} (dup {cs['duplicates']:<3}) texts +{ts}")

    n = db.rebuild_numbers(con)
    print(f"\ncalls added {tot_calls} ({tot_dups} duplicate device records)")
    print(f"texts added {tot_texts}")
    print(f"rollup: {n} distinct unknown inbound numbers")

    span = con.execute("SELECT MIN(local_date), MAX(local_date) FROM calls").fetchone()
    print(f"coverage now: {span[0]} .. {span[1]}")
    con.close()


def cmd_analyze(args):
    con = db.connect()
    result = campaign_mod.build(con)
    print(f"\n=== CAMPAIGN #{result['campaign_id']}  "
          f"confidence {result['confidence']:.2f} ===")
    print(f"  behavioral fingerprint matches : {result['fingerprint_numbers']}")
    print(f"  DID blocks (2+ numbers)        : {result['did_blocks']}")
    print(f"  corroborated by both signals   : {result['corroborated']}")
    print(f"  total member numbers           : {result['member_numbers']}")
    print(f"  total calls attributed         : {result['total_calls']}")

    if result["enriched_numbers"]:
        print(f"  carrier concentration          : {result['carrier_share']*100:.0f}% "
              f"on {result['top_carrier']} "
              f"({result['enriched_numbers']} enriched)")
        print("\n  carrier families (the subpoena / traceback path):")
        print(f"    {'nums':>4} {'calls':>5} {'NPAs':>5}  family")
        for c in result["carriers"]:
            print(f"    {c['numbers']:>4} {c['calls']:>5} {len(c['npas']):>5}  "
                  f"{c['family']}")
    else:
        print("  carrier concentration          : not enriched -- run `enrich`")

    print("\n  most recent activity:")
    for hit in result["fingerprint"][-10:]:
        print(f"    {hit['date']}  {display(hit['number']):<16} "
              f"{hit['answered_s']:>3}s  {hit['geo']}")

    confirmed = [b for b in result["blocks"] if b["corroborated"]]
    leads = [b for b in result["blocks"] if not b["corroborated"]]

    if confirmed:
        print("\n  DID blocks IN this campaign (share a fingerprint number):")
        for b in confirmed:
            print(f"    {b['block'][:3]}-{b['block'][3:]}  "
                  f"{len(b['numbers'])} numbers, {b['calls']} calls  {b['geo']}")
    if leads:
        print("\n  unattributed blocks (leads only -- NOT campaign members):")
        for b in leads[:8]:
            print(f"    {b['block'][:3]}-{b['block'][3:]}  "
                  f"{len(b['numbers'])} numbers, {b['calls']} calls  {b['geo']}")
    con.close()


def cmd_enrich(args):
    from tcpa.enrich import nanpa

    con = db.connect()
    if args.all:
        rows = con.execute("SELECT number FROM numbers ORDER BY number").fetchall()
        scope = "all known numbers"
    else:
        rows = con.execute("""
            SELECT n.number FROM numbers n
            JOIN campaign_numbers cn ON cn.number = n.number
            ORDER BY n.number
        """).fetchall()
        scope = "campaign members"
    if not args.refresh:
        rows = [r for r in rows if con.execute(
            "SELECT enriched_at FROM numbers WHERE number=?", (r["number"],)
        ).fetchone()["enriched_at"] is None]

    numbers = [r["number"] for r in rows]
    if not numbers:
        print("nothing to enrich (use --refresh to re-fetch, --all to widen scope)")
        return
    print(f"enriching {len(numbers)} numbers ({scope}) via public NANPA block data")
    stats = nanpa.enrich(con, numbers)
    print(f"\nresolved {stats['resolved']}, failed {stats['failed']}, "
          f"{stats['exchanges_fetched']} exchanges fetched")
    con.close()
    cmd_carriers(args)


def cmd_carriers(args):
    con = db.connect()
    rows = con.execute("""
        SELECT n.carrier_name, n.carrier_ocn, n.line_type,
               COUNT(*) numbers, SUM(n.call_count) calls
        FROM numbers n
        JOIN campaign_numbers cn ON cn.number = n.number
        WHERE n.carrier_name IS NOT NULL
        GROUP BY n.carrier_name, n.carrier_ocn, n.line_type
        ORDER BY numbers DESC, calls DESC
    """).fetchall()
    if not rows:
        print("no enriched campaign numbers yet -- run `enrich` first")
        con.close()
        return

    print("\n=== CARRIER CONCENTRATION (campaign numbers) ===")
    print(f"  {'numbers':>7} {'calls':>6}  {'OCN':<6} {'type':<15} carrier")
    for r in rows:
        print(f"  {r['numbers']:>7} {r['calls']:>6}  {r['carrier_ocn'] or '':<6} "
              f"{r['line_type'] or '':<15} {r['carrier_name']}")

    tot = con.execute("""
        SELECT n.line_type, COUNT(*) c FROM numbers n
        JOIN campaign_numbers cn ON cn.number = n.number
        WHERE n.line_type IS NOT NULL GROUP BY n.line_type ORDER BY c DESC
    """).fetchall()
    print("\n  by line type:")
    total = sum(r["c"] for r in tot)
    for r in tot:
        print(f"    {r['line_type']:<16} {r['c']:>3}  ({r['c']/total*100:.0f}%)")
    con.close()


def cmd_complaints(args):
    from tcpa.enrich import fcc

    con = db.connect()
    camp = con.execute("SELECT id FROM campaigns ORDER BY id DESC LIMIT 1").fetchone()
    if not camp:
        sys.exit("no campaign yet -- run `analyze` first")

    print("querying FCC consumer complaints (dataset vakf-fz8e) by DID block")
    stats = fcc.enrich_campaign(con, camp["id"])
    print(f"\n{stats['complaints']} complaints across {stats['blocks']} blocks, "
          f"{stats['distinct_numbers']} distinct numbers")
    print(f"  prerecorded/autodialed : {stats['prerecorded']} "
          f"({stats['prerecorded']/stats['complaints']*100:.0f}%)"
          if stats["complaints"] else "  no complaints found")
    print(f"  naming YOUR exact numbers: {stats['exact']}")

    rows = con.execute("""
        SELECT call_type, COUNT(*) c FROM complaints
        GROUP BY call_type ORDER BY c DESC LIMIT 10
    """).fetchall()
    if rows:
        print("\n  complaint call types:")
        for r in rows:
            print(f"    {r['call_type'] or '(blank)':<28} {r['c']:>4}")

    adv = con.execute("""
        SELECT advertiser_phone, COUNT(*) c FROM complaints
        WHERE advertiser_phone IS NOT NULL AND advertiser_phone != ''
        GROUP BY advertiser_phone HAVING c > 1 ORDER BY c DESC LIMIT 15
    """).fetchall()
    if adv:
        print("\n  repeated callback numbers (these can lead to the seller):")
        for r in adv:
            print(f"    {display(r['advertiser_phone']):<18} {r['c']} complaints")
    con.close()


def cmd_targets(args):
    from tcpa.analyze import targets

    con = db.connect()
    rows = targets.build(con, min_calls=args.min)
    if not rows:
        sys.exit("no repeat callers outside the campaign")

    unenriched = sum(1 for r in rows if not r["line_type"])
    if unenriched:
        print(f"NOTE: {unenriched}/{len(rows)} not yet enriched -- "
              f"run `enrich --all` for accurate tiering\n")

    labels = {
        "A": "identifiable business WITH telemarketing complaints -- best candidates",
        "B": "identifiable business, no complaint history -- verify before acting",
        "C": "partially identifiable -- needs enrichment or a callback",
        "D": "disposable / unattributable -- not worth pursuing",
    }
    for tier in "ABCD":
        group = [r for r in rows if r["tier"] == tier]
        if not group:
            continue
        print(f"\n=== TIER {tier}  ({len(group)})  {labels[tier]} ===")
        print(f"  {'number':<16}{'calls':>6}{'ans':>4}{'longest':>9}{'cmpl':>6}  "
              f"{'line':<15} geo")
        for r in group:
            d = r["max_duration_s"]
            print(f"  {display(r['number']):<16}{r['calls']:>6}{r['answered']:>4}"
                  f"{d//60:>6}m{d%60:02d}{r['complaints']:>6}  "
                  f"{r['line_type'] or '?':<15} {r['geo']}")
            if args.verbose and r["reasons"]:
                for reason in r["reasons"]:
                    print(f"      - {reason}")
    con.close()


def cmd_texts(args):
    from tcpa.analyze import texts as tx

    con = db.connect()
    s = tx.summarize(con)
    if not s["total_incoming"]:
        sys.exit("no texts loaded -- run `ingest-att` first")

    print(f"incoming texts        : {s['total_incoming']:,}")
    print(f"  short-code senders  : {s['short_code_senders']} "
          f"({s['short_code_messages']:,} messages)")
    print(f"  long-code senders   : {s['long_code_senders']}")
    print(f"    you replied to    : {s['replied_senders']}  (excluded)")
    print(f"    never engaged     : {s['unknown_senders']} "
          f"({s['unknown_messages']:,} messages)")

    ranked = tx.rank_unknown(s, min_messages=args.min)
    print(f"\n=== UNKNOWN SENDERS WITH {args.min}+ MESSAGES ({len(ranked)}) ===")
    if ranked:
        print(f"  {'number':<16}{'msgs':>6}{'days':>6}  {'first':<12}{'last':<12} kinds")
        for r in ranked[:30]:
            flag = " *" if r["persistent"] else ""
            print(f"  {display(r['number']):<16}{r['messages']:>6}{r['distinct_days']:>6}  "
                  f"{r['first']:<12}{r['last']:<12} "
                  f"{','.join(f'{k}:{v}' for k, v in r['kinds'].items())}{flag}")
        print("\n  * = spread over 3+ distinct days (persistent, not a single burst)")
    else:
        print("  none")

    print("\n=== TOP SHORT CODES (A2P -- highly attributable, usually legitimate) ===")
    print(f"  {'code':<10}{'msgs':>6}{'days':>6}  {'first':<12}last")
    for r in tx.rank_short_codes(s):
        print(f"  {r['code']:<10}{r['messages']:>6}{r['distinct_days']:>6}  "
              f"{r['first']:<12}{r['last']}")
    con.close()


def cmd_callbacks(args):
    from tcpa.enrich import fcc

    con = db.connect()
    print("profiling callback numbers against nationwide FCC complaints\n")
    rows = fcc.profile_callbacks(con, min_complaints=args.min)
    if not rows:
        sys.exit("no callback numbers stored -- run `complaints` first")

    print(f"  {'callback':<16}{'natl':>6}{'states':>7}{'prerec':>7}  active period")
    for r in rows:
        span = f"{r['first']} .. {r['last']}" if r["first"] else "-"
        print(f"  {display(r['number']):<16}{r['national']:>6}{r['states']:>7}"
              f"{r['prerecorded']:>7}  {span}")

    print("\n  Callback numbers persist while dialing DIDs are burned, so the date"
          "\n  ranges above show when the operation rotated to a fresh line.")
    con.close()


def _latest_campaign(con):
    row = con.execute("SELECT id FROM campaigns ORDER BY id DESC LIMIT 1").fetchone()
    return row["id"] if row else None


def cmd_complaint(args):
    from tcpa.report import ftc

    con = db.connect()
    if args.number:
        text = ftc.for_number(con, args.number, your_state=args.state)
    else:
        cid = args.campaign or _latest_campaign(con)
        if not cid:
            sys.exit("no campaign found -- run `analyze`, or pass --number")
        text = ftc.for_campaign(con, cid, your_state=args.state)
    _emit(text, args.out, "complaint.txt")
    con.close()


def cmd_packet(args):
    from tcpa.report import packet

    con = db.connect()
    cid = None if args.number else (args.campaign or _latest_campaign(con))
    if not cid and not args.number:
        sys.exit("no campaign found -- run `analyze`, or pass --number")
    text = packet.build(con, campaign_id=cid, number=args.number,
                        jurisdiction=args.state, dnc_since=args.dnc_since)
    _emit(text, args.out, "intake-packet.txt")
    con.close()


def cmd_fingerprint(args):
    import json
    from tcpa.report import fingerprint as fp

    con = db.connect()
    if args.match:
        a = json.loads(Path(args.match[0]).read_text(encoding="utf-8"))
        b = json.loads(Path(args.match[1]).read_text(encoding="utf-8"))
        res = fp.match(a, b)
        print(f"verdict          : {res['verdict'].upper()}  (score {res['score']:.2f})")
        print(f"  DID blocks     : {res['block_overlap']:.2f}")
        print(f"  carriers       : {res['carrier_overlap']:.2f}")
        print(f"  callback nums  : {res['callback_overlap']:.2f}")
        if res["shared_callbacks"]:
            print(f"  shared callbacks: {', '.join(res['shared_callbacks'])}")
        if res["shared_blocks"]:
            print(f"  shared blocks   : {', '.join(res['shared_blocks'])}")
        con.close()
        return

    cid = args.campaign or _latest_campaign(con)
    if not cid:
        sys.exit("no campaign found -- run `analyze` first")
    data = fp.build(con, cid)
    text = json.dumps(data, indent=2)
    _emit(text, args.out, f"fingerprint-{data['id']}.json")
    print("\nThis file contains NO personal information -- no phone number of "
          "yours,\nno names, no exact timestamps. It is safe to share publicly.")
    con.close()


def _emit(text: str, out: str | None, default_name: str):
    if out:
        p = Path(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        print(f"written: {p}")
    else:
        print(text)


def cmd_contribute(args):
    import json
    from tcpa.report import contribute

    con = db.connect()
    cid = args.campaign or _latest_campaign(con)
    if not cid:
        sys.exit("no campaign found -- run `analyze` first")
    doc = contribute.build(con, cid, note=args.note)
    problems = contribute.audit(doc)
    if problems:
        print("REFUSING TO WRITE -- contribution failed its own audit:")
        for p in problems:
            print(f"  {p}")
        sys.exit(1)

    _emit(json.dumps(doc, indent=2), args.out, f"contribution-{doc['fingerprint']['id']}.json")
    print(f"\n{len(doc['numbers'])} calling numbers, campaign "
          f"{doc['fingerprint']['id']}.")
    print("Contains only the CALLER's infrastructure -- no number of yours, no")
    print("name, no location, no durations, no exact timestamps.")
    print("Read it before opening a pull request. See corpus/README.md.")
    con.close()


def cmd_entities(args):
    con = db.connect()
    rows = con.execute("SELECT * FROM entities ORDER BY role, legal_name").fetchall()
    if not rows:
        print("no entities recorded -- run scripts/seed_entities.py")
        con.close()
        return
    for r in rows:
        print(f"\n{r['legal_name']}   [{r['role']}]  confidence {r['confidence']:.2f}")
        print(f"  registration     : {r['state_of_reg']}")
        print(f"  registered agent : {r['registered_agent']}")
        print(f"  agent address    : {r['agent_address']}")
        print(f"  source           : {r['source_url']}")
        if r["role"] == "carrier":
            print("  NOTE: carrier of record, NOT a defendant on this evidence.")
    con.close()


def cmd_report(args):
    con = db.connect()
    q = lambda s, *a: con.execute(s, a).fetchall()
    total = q("SELECT COUNT(*) c, MIN(local_date) lo, MAX(local_date) hi FROM calls")[0]
    if not total["c"]:
        sys.exit("database is empty -- run `pull` first")
    print(f"calls: {total['c']:,}   range: {total['lo']} .. {total['hi']}")

    print("\ndirection:")
    for r in q("SELECT direction, COUNT(*) c FROM calls GROUP BY direction ORDER BY c DESC"):
        print(f"  {r['direction']:<20} {r['c']:>5}")

    print("\nunknown inbound numbers by call count:")
    for r in q("""SELECT call_count, COUNT(*) c FROM numbers
                  GROUP BY call_count ORDER BY call_count"""):
        print(f"  {r['call_count']:>3} call(s): {r['c']:>4} numbers")

    off = q("""SELECT COUNT(*) c FROM calls
               WHERE direction IN ('INCOMING','MISSED','REJECTED','BLOCKED')
                 AND (contact_name IS NULL OR contact_name='')
                 AND (local_hour < 8 OR local_hour >= 21)""")[0]["c"]
    print(f"\noutside 8am-9pm local: {off} calls")

    camps = q("SELECT * FROM campaigns ORDER BY id DESC")
    if camps:
        print("\ncampaigns:")
        for c in camps:
            n = q("SELECT COUNT(*) c FROM campaign_numbers WHERE campaign_id=?",
                  c["id"])[0]["c"]
            print(f"  #{c['id']} {c['label']} -- {n} numbers, "
                  f"confidence {c['confidence']:.2f}")
    con.close()


def main():
    p = argparse.ArgumentParser(prog="tcpa-analyzer", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tz", default="America/New_York",
                   help="local timezone for calling-window analysis")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("pull", help="pull call log from connected Android device")
    sp.add_argument("--out")
    sp.set_defaults(func=cmd_pull)

    sp = sub.add_parser("ingest", help="parse a raw dump into SQLite")
    sp.add_argument("--raw")
    sp.set_defaults(func=cmd_ingest)

    sp = sub.add_parser("ingest-att", help="load AT&T xlsx exports from data/raw")
    sp.set_defaults(func=cmd_ingest_att)

    sp = sub.add_parser("analyze", help="detect campaigns")
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser("enrich", help="resolve carrier/OCN via public NANPA data")
    sp.add_argument("--all", action="store_true",
                    help="enrich every known number, not just campaign members")
    sp.add_argument("--refresh", action="store_true",
                    help="re-fetch numbers that are already enriched")
    sp.set_defaults(func=cmd_enrich)

    sp = sub.add_parser("carriers", help="carrier concentration for campaign numbers")
    sp.set_defaults(func=cmd_carriers)

    sp = sub.add_parser("complaints", help="cross-reference FCC consumer complaint data")
    sp.set_defaults(func=cmd_complaints)

    sp = sub.add_parser("targets", help="rank repeat callers by suability")
    sp.add_argument("--min", type=int, default=2, help="minimum call count")
    sp.add_argument("--verbose", "-v", action="store_true", help="show scoring reasons")
    sp.set_defaults(func=cmd_targets)

    sp = sub.add_parser("texts", help="analyze incoming text messages")
    sp.add_argument("--min", type=int, default=2, help="minimum messages per sender")
    sp.set_defaults(func=cmd_texts)

    sp = sub.add_parser("callbacks", help="profile callback numbers nationwide")
    sp.add_argument("--min", type=int, default=2,
                    help="minimum local complaints to profile a number")
    sp.set_defaults(func=cmd_callbacks)

    sp = sub.add_parser("complaint", help="generate FTC/FCC complaint text")
    sp.add_argument("--number", help="single calling number instead of a campaign")
    sp.add_argument("--campaign", type=int)
    sp.add_argument("--state", default="[YOUR STATE]")
    sp.add_argument("--out", help="write to a file instead of stdout")
    sp.set_defaults(func=cmd_complaint)

    sp = sub.add_parser("packet", help="generate an attorney intake packet")
    sp.add_argument("--number")
    sp.add_argument("--campaign", type=int)
    sp.add_argument("--state", default="[STATE]")
    sp.add_argument("--dnc-since", help="date you joined the National DNC Registry")
    sp.add_argument("--out")
    sp.set_defaults(func=cmd_packet)

    sp = sub.add_parser("fingerprint",
                        help="export/compare an anonymous campaign fingerprint")
    sp.add_argument("--campaign", type=int)
    sp.add_argument("--out")
    sp.add_argument("--match", nargs=2, metavar=("A.json", "B.json"),
                    help="compare two fingerprint files instead of exporting")
    sp.set_defaults(func=cmd_fingerprint)

    sp = sub.add_parser("contribute", help="build a corpus contribution for a PR")
    sp.add_argument("--campaign", type=int)
    sp.add_argument("--note", help="short note (no digits -- see corpus/README.md)")
    sp.add_argument("--out")
    sp.set_defaults(func=cmd_contribute)

    sp = sub.add_parser("entities", help="show resolved legal entities")
    sp.set_defaults(func=cmd_entities)

    sp = sub.add_parser("report", help="summarize the database")
    sp.set_defaults(func=cmd_report)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
