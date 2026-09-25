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
from tcpa.phone import display, normalize            # noqa: E402

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
    db.rebuild_numbers(con)  # pick up edits to known_numbers.txt
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
    from tcpa.enrich import nanpa, resporg
    from tcpa.phone import is_toll_free

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

    # Toll-free numbers have no NANPA block; they resolve through the RespOrg
    # registry instead. With --all that includes FCC callback numbers, which
    # never appear in `numbers` but often lead to the seller.
    candidates = [r["number"] for r in rows]
    numbers = [n for n in candidates if not is_toll_free(n)]
    toll_free = [n for n in candidates if is_toll_free(n)]
    if args.all:
        toll_free = sorted(set(toll_free) | set(resporg.toll_free_numbers(con)))
    if not args.refresh:
        toll_free = resporg.due(con, toll_free)

    if not numbers and not toll_free:
        print("nothing to enrich (use --refresh to re-fetch, --all to widen scope)")
        con.close()
        return
    if numbers:
        print(f"enriching {len(numbers)} numbers ({scope}) via public NANPA block data")
        stats = nanpa.enrich(con, numbers)
        print(f"\nresolved {stats['resolved']}, failed {stats['failed']}, "
              f"{stats['exchanges_fetched']} exchanges fetched")
    if toll_free:
        print(f"\nlooking up RespOrg for {len(toll_free)} toll-free numbers "
              f"via {resporg.AUTO_SOURCE}")
        stats = resporg.lookup(con, toll_free)
        print(f"\nresolved {stats['resolved']}, no registry record "
              f"{stats['not_found']}, failed {stats['failed']}  "
              f"-- see `resporg` for the list")
    con.close()
    if numbers:
        cmd_carriers(args)


def _print_resporg_history(con, number):
    from tcpa.enrich import resporg

    rows = resporg.history(con, number)
    print(f"\n{display(number)}")
    if not rows:
        print("  no RespOrg lookups yet -- run `resporg <number> --lookup`")
        return
    for r in rows:
        if r["resporg_id"] or r["resporg_name"]:
            who = (f"{r['resporg_id'] or '(no ID shown)'}  {r['resporg_name'] or ''}"
                   + (f" ({r['resporg_group']})" if r["resporg_group"] else ""))
        elif r["status"] and r["status"] != "NOT_FOUND":
            who = "no current holder"
        else:
            who = "no registry record"
        since = f" since {r['status_since']}" if r["status_since"] else ""
        print(f"  {r['checked_on']}  {r['method']:<7} {who}  "
              f"[{r['status'] or '?'}{since}]")
        print(f"  {'':<10}  source: {r['source']}"
              + (f"  -- {r['note']}" if r["note"] else ""))
    print("\n  NOTE: a RespOrg manages the number's routing record. It is NOT the")
    print("  caller. 'auto' results are third-party leads -- confirm on somos.com")
    print("  and record it with --id or --name plus --source before citing it.")


def cmd_resporg(args):
    from tcpa.enrich import resporg

    con = db.connect()
    try:
        number = resporg.parse_number(args.number) if args.number else None
        if number and (args.id or args.name or args.status):
            resporg.record_manual(con, number, args.id, args.source, name=args.name,
                                  status=args.status, checked_on=args.date,
                                  note=args.note)
            print(f"recorded manual lookup for {display(number)}")
        elif args.id or args.name or args.status:
            raise ValueError("--id/--name/--status need a number")
    except ValueError as exc:
        con.close()
        sys.exit(str(exc))

    if number:
        if args.lookup:
            resporg.lookup(con, [number])
        _print_resporg_history(con, number)
        con.close()
        return

    if args.lookup:
        todo = resporg.due(con, list(resporg.toll_free_numbers(con)))
        if todo:
            print(f"looking up {len(todo)} toll-free numbers via {resporg.AUTO_SOURCE}")
            resporg.lookup(con, todo)
            print()

    rows = resporg.worklist(con)
    if not rows:
        print("no toll-free numbers in the data")
        con.close()
        return
    print(f"=== TOLL-FREE NUMBERS ({len(rows)}) -- RespOrg is the subpoena path ===")
    print(f"  {'number':<16}{'calls':>6}  {'last call':<11}{'fcc cb':>7}  "
          f"{'resporg':<7} {'status':<10}{'method':<8}holder")
    for r in rows:
        if r["checked_on"]:
            rid = r["resporg_id"] or "-"
            status = r["status"] or "?"
            holder = r["resporg_name"] or (
                "" if r["resporg_id"] else
                "no registry record" if r["status"] in (None, "NOT_FOUND") else
                "no current holder")
        else:
            rid, status, holder = "", "", "not looked up"
        print(f"  {display(r['number']):<16}{r['calls']:>6}  {r['last_call'] or '-':<11}"
              f"{r['fcc_callbacks']:>7}  {rid:<7} {status:<10}{r['method'] or '':<8}"
              f"{holder}")
    print("\n  fcc cb = times this number was named as the callback number in stored")
    print("  FCC complaints. 'auto' = third-party lead; 'manual' = you confirmed it.")
    con.close()


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
    if any(r["owner_calls"] for r in rows):
        print("'you' = times you called the number back after it called you. That is")
        print("not consent, but it will come up -- review these, and move any you")
        print("recognize to data/known_numbers.txt.\n")
    for tier in "ABCD":
        group = [r for r in rows if r["tier"] == tier]
        if not group:
            continue
        print(f"\n=== TIER {tier}  ({len(group)})  {labels[tier]} ===")
        print(f"  {'number':<16}{'calls':>6}{'ans':>4}{'longest':>9}{'cmpl':>6}"
              f"{'you':>4}  {'line':<15} geo")
        for r in group:
            d = r["max_duration_s"]
            print(f"  {display(r['number']):<16}{r['calls']:>6}{r['answered']:>4}"
                  f"{d//60:>6}m{d%60:02d}{r['complaints']:>6}"
                  f"{r['owner_calls'] or '':>4}  "
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
    print(f"    you contacted first: {s['known_senders']}  (excluded -- relationship)")
    print(f"    unknown senders   : {s['unknown_senders']} "
          f"({s['unknown_messages']:,} messages; you replied to {s['replied_unknown']})")

    ranked = tx.rank_unknown(s, min_messages=args.min)
    print(f"\n=== UNKNOWN SENDERS WITH {args.min}+ MESSAGES ({len(ranked)}) ===")
    if ranked:
        print(f"  {'number':<16}{'msgs':>6}{'days':>6}{'rep':>5}{'after':>6}  "
              f"{'first':<12}{'last':<12} kinds")
        for r in ranked[:30]:
            flag = " *" if r["persistent"] else ""
            print(f"  {display(r['number']):<16}{r['messages']:>6}{r['distinct_days']:>6}"
                  f"{r['replies'] or '':>5}{r['after_reply'] or '':>6}  "
                  f"{r['first']:<12}{r['last']:<12} "
                  f"{','.join(f'{k}:{v}' for k, v in r['kinds'].items())}{flag}")
        print("\n  * = spread over 3+ distinct days (persistent, not a single burst)")
    else:
        print("  none")

    print("\n=== TOP SHORT CODES (A2P -- highly attributable, usually legitimate) ===")
    print(f"  {'code':<10}{'msgs':>6}{'days':>6}{'rep':>5}{'after':>6}  {'first':<12}last")
    for r in tx.rank_short_codes(s):
        print(f"  {r['code']:<10}{r['messages']:>6}{r['distinct_days']:>6}"
              f"{r['replies'] or '':>5}{r['after_reply'] or '':>6}  "
              f"{r['first']:<12}{r['last']}")
    print("\n  rep = your replies; after = messages that arrived after your first reply.")
    print("  If that reply was STOP, 'after' counts texts sent after a revocation. The")
    print("  carrier record has no message text -- check the thread on your phone, and")
    print("  record a STOP with: revoke <number> --method sms --basis document ...")
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


def _number_arg(raw: str | None) -> str | None:
    """Normalize a --number argument once, at the boundary (CLAUDE.md invariant 1).

    Stored numbers are bare 10-digit NANP; comparing the raw spelling the user
    typed ("800-555-0199") silently matches nothing.
    """
    if raw is None:
        return None
    number = normalize(raw)
    if number is None:
        sys.exit(f"not a NANP phone number: {raw!r}")
    return number


def cmd_complaint(args):
    from tcpa.report import ftc

    con = db.connect()
    if args.number:
        text = ftc.for_number(con, _number_arg(args.number), your_state=args.state)
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
    text = packet.build(con, campaign_id=cid, number=_number_arg(args.number),
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


def cmd_known(args):
    con = db.connect()
    rows = con.execute("""
        SELECT k.number, k.note, COUNT(c.id) calls, MAX(c.local_date) last
        FROM known_numbers k
        LEFT JOIN calls c ON c.number = k.number AND c.dup_of_device = 0
             AND c.direction IN ('INCOMING','MISSED','REJECTED','BLOCKED')
        GROUP BY k.number ORDER BY k.number
    """).fetchall()
    path = db.DEFAULT_DB.parent / db.KNOWN_NUMBERS_FILE
    if not rows:
        print(f"no known numbers -- add them to {path}")
        con.close()
        return
    print(f"{len(rows)} known numbers from {path}")
    print("excluded from targets, campaigns, and text analysis\n")
    print(f"  {'number':<16}{'inbound':>8}  {'last call':<11} note")
    for r in rows:
        print(f"  {display(r['number']):<16}{r['calls']:>8}  {r['last'] or '-':<11} "
              f"{r['note']}")
    con.close()


def _print_revocations(rows):
    for r in rows:
        who = display(r["number"]) if r["number"] else "campaign-wide"
        print(f"  #{r['id']:<3} {(r['local_iso'] or '')[:16]:<17} {who:<16} "
              f"{r['method']:<8} basis: {r['basis'] or 'unstated':<13}"
              f"{r['calls_after'] if r['calls_after'] is not None else '-':>3} calls after")
        if r["verbatim"]:
            print(f"        said: \"{r['verbatim']}\"")
        if r["evidence_path"]:
            print(f"        evidence: {r['evidence_path']}")


def cmd_revoke(args):
    from tcpa import revoke

    con = db.connect()
    try:
        if args.remove:
            if not revoke.remove(con, args.remove):
                raise ValueError(f"no revocation #{args.remove}")
            print(f"removed revocation #{args.remove}")
            return

        number = _number_arg(args.number) if args.number else None
        if number and args.at:
            if not args.basis:
                raise ValueError("--basis is required: recording, document, or "
                                 "recollection (from memory)")
            res = revoke.record(con, number, args.at, args.basis, method=args.method,
                                said=args.said, evidence=args.recording,
                                note=args.note, tz=args.tz)
            print(f"recorded revocation #{res['id']}: {display(number)} at "
                  f"{res['local_iso'][:16]} -- {res['calls_after']} later call(s) "
                  f"from this number")
            if args.basis == "recollection":
                print("  basis: your recollection. That is testimony, not a recording;")
                print("  an attorney will want anything that corroborates it.")
            return
        if args.at:
            raise ValueError("--at needs a number")

        if number:
            calls = revoke.answered_calls(con, number)
            print(f"{display(number)} -- answered calls (a verbal request must be on one):")
            if any(c["duration_estimated"] for c in calls):
                print("  (<= : carrier record, billed in whole minutes)")
            if not calls:
                print("  none. A verbal revocation needs a call you picked up;")
                print("  a text or letter can use --method sms/written.")
            for c in calls:
                later = revoke.calls_after(con, number, c["ts_utc"])
                dur = (f"<={c['duration_s']}s" if c["duration_estimated"]
                       else f"{c['duration_s']}s")
                print(f"  {c['local_iso'][:16]}  {dur:>7}  "
                      f"{later:>3} later call(s)  [{c['source']}]")
            rows = revoke.listing(con, number)
            if rows:
                print("\nrecorded revocations:")
                _print_revocations(rows)
            else:
                print(f"\nrecord one with: revoke {args.number} --at YYYY-MM-DD "
                      f"--basis recollection --said \"stop calling me\"")
            return

        rows = revoke.listing(con)
        if not rows:
            print("no revocations recorded -- `revoke <number>` lists the calls to choose from")
            return
        print(f"{len(rows)} revocation(s):")
        _print_revocations(rows)
    except ValueError as exc:
        sys.exit(str(exc))
    finally:
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

    sp = sub.add_parser("resporg",
                        help="toll-free RespOrg lookups (the toll-free subpoena path)")
    sp.add_argument("number", nargs="?", help="one toll-free number (else: list all)")
    sp.add_argument("--lookup", action="store_true",
                    help="query resporgs.com now (all due numbers if no number given)")
    sp.add_argument("--id", help="record a manual somos.com result: the RespOrg ID")
    sp.add_argument("--source", help="where the manual result came from (required with --id)")
    sp.add_argument("--name", help="company name Somos shows (may be given without --id)")
    sp.add_argument("--status", help="status shown by Somos, e.g. WORKING")
    sp.add_argument("--date", help="date of the manual lookup, YYYY-MM-DD (default today)")
    sp.add_argument("--note")
    sp.set_defaults(func=cmd_resporg)

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

    sp = sub.add_parser("revoke",
                        help="record a 'stop calling' request against a specific call")
    sp.add_argument("number", nargs="?", help="the caller (omit to list all revocations)")
    sp.add_argument("--at", help="date of the call, YYYY-MM-DD, or 'YYYY-MM-DD HH:MM' "
                                 "if you answered more than one that day")
    sp.add_argument("--basis", choices=("recording", "document", "recollection"),
                    help="how you know: a recording, a document/text, or your memory")
    sp.add_argument("--method", choices=("verbal", "written", "sms"), default="verbal")
    sp.add_argument("--said", help="what you said, as closely as you can recall")
    sp.add_argument("--recording", help="path to the recording, screenshot, or letter")
    sp.add_argument("--note")
    sp.add_argument("--remove", type=int, metavar="ID", help="delete a mistaken entry")
    sp.set_defaults(func=cmd_revoke)

    sp = sub.add_parser("known", help="list numbers in data/known_numbers.txt")
    sp.set_defaults(func=cmd_known)

    sp = sub.add_parser("report", help="summarize the database")
    sp.set_defaults(func=cmd_report)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
