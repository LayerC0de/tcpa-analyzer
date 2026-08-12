# Quickstart

## Requirements

- Python 3.11+
- `pip install -r requirements.txt`
- For Android ingest: [Android platform-tools](https://developer.android.com/tools/releases/platform-tools) (`adb` on your PATH)

> On Windows the `tzdata` package is **required**, not optional. Windows has no
> system timezone database, and without it the 8am–9pm calling-window analysis
> silently falls back to an approximation.

## Step 1 — get your call records

### Android (best source)

1. Settings → About phone → tap **Build number** seven times
2. Settings → System → Developer options → enable **USB debugging**
3. Connect by USB, set the connection to **File transfer**
4. Accept the **"Allow USB debugging?"** prompt on the phone

```bash
python cli.py pull
```

Verify with `adb devices` — it should list your phone as `device`, not
`unauthorized`. If nothing appears at all, the usual culprit is a charge-only
USB cable.

**Do this soon.** Android caps the call log (often ~2,000 entries). At a few
calls a day that can be well under a year, and the oldest records roll off
permanently.

### Carrier records (reaches further back)

Most carriers offer 12–18 months of usage detail. Download each bill cycle as a
spreadsheet into `data/raw/`, then:

```bash
python scripts/organize_att.py   # rename by internal bill-cycle label, drop duplicates
python cli.py ingest-att
```

Currently only AT&T's `.xlsx` export is implemented. Other carriers are very
welcome — see [CONTRIBUTING.md](../CONTRIBUTING.md).

**Carrier records are a supplement, not a substitute.** They bill *usage*, so
calls that rang unanswered generally do not appear, and durations are rounded to
billed minutes. In one measured comparison the carrier record was missing 51% of
inbound events.

## Step 2 — analyze

```bash
python cli.py analyze     # cluster rotating-number campaigns
python cli.py enrich      # carrier + OCN per number (public NANPA data, free)
python cli.py complaints  # cross-reference the FCC complaint dataset
python cli.py targets     # rank callers by suability
python cli.py texts       # incoming text analysis (carrier sources only)
```

`enrich` is rate-limited to be polite to a free community service — budget about
a second per exchange. Results are cached, and re-running `ingest` will not wipe
them.

## Step 3 — produce output

```bash
python cli.py complaint --state "New York" --out out/complaint.txt
python cli.py packet --state "New York" --dnc-since 2019-06-01 --out out/packet.txt
python cli.py fingerprint --out out/campaign.json
```

See [REPORTING.md](REPORTING.md), [FOR-LAWYERS.md](FOR-LAWYERS.md), and
[CLASS-ACTIONS.md](CLASS-ACTIONS.md).

## Reading `targets`

| Tier | Meaning |
|---|---|
| **A** | Identifiable business with a telemarketing complaint history — best candidates |
| **B** | Identifiable business, no complaint history — verify before acting |
| **C** | Partially identifiable — needs enrichment or a callback to resolve |
| **D** | Disposable or unattributable — not worth pursuing |

Attribution **gates** the other scores. Perfect violation facts against a caller
you cannot name are worth nothing, which is why a high-volume burner lands in D
while a two-call caller on a traceable line can land in A.

Run `targets -v` to see the reasoning behind every score.

## Two things worth doing on day one

**Record your calls, if your state allows it.** Some states require all parties
to consent — check yours first. A recording is the only practical way to prove a
prerecorded voice or an autodialer, which is what §227(b) turns on, and §227(b)
needs only one call rather than two.

**Say the words clearly, and log them.** *"Stop calling this number. Put me on
your internal do-not-call list."* That timestamp is the willfulness predicate
that moves damages from $500 to $1,500 per subsequent call. Record it in the
`revocations` table so packets can count calls that came after it.
