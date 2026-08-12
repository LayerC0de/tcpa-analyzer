# CLAUDE.md

Guidance for AI agents working in this repository.

## What this project is

A local-first tool that turns raw phone records into **attributable** TCPA claims.
Users are typically pro se litigants who intend to file real cases, not just
organize data. Output quality is measured by whether it survives contact with a
courtroom. Jurisdiction is configurable; defaults assume US federal TCPA plus a
state overlay set in `config`.

## The single most important idea

**Pattern severity and suability are nearly uncorrelated.** Do not build features
that rank by call volume. The number that called forty times is usually a burner
DID belonging to nobody. The suable defendant hides behind numbers that each
called twice and were then retired.

Every design decision follows from this:

- A phone number is **evidence of** a defendant, never the defendant itself.
- `campaigns` is the unit of legal action. `numbers` hang off campaigns.
- Attribution work beats detection work. Detection is already good enough;
  nothing in a call log carries identity, so value comes from enrichment,
  entity resolution, and captured call content.

## Domain vocabulary

| Term | Meaning |
|---|---|
| **DID** | Direct Inward Dial number. Dialers lease these in contiguous blocks. |
| **NPA-NXX** | First 6 digits. The block-allocation unit — the strongest infrastructure signal available from a call log alone. |
| **OCN** | Operating Company Number. Identifies the carrier holding a block; the starting point for a subpoena or ITG traceback. |
| **Campaign** | One operation, inferred from shared infrastructure and behavior across many disposable numbers. |
| **Caller vs. Seller** | The dialer is often an offshore shell with no assets. The *seller* — whoever the pitch was for — is domestic, collectable, and potentially vicariously liable for its lead generators. The seller is usually the real defendant. |
| **Revocation** | The moment the owner said "stop calling." The willfulness predicate: damages go from $500 to $1,500 per subsequent call. |
| **Fingerprint** | Burn-after-use signature: exactly 2 calls, same day, one brief connect + one that never connects, number then retired. |

## Legal framing that constrains the code

- **§ 227(c)(5)** needs **2+ calls in 12 months**. This is why single-call numbers
  are near-worthless individually — and why campaign-level aggregation matters,
  since it satisfies the threshold across rotating DIDs.
- **§ 227(b)** (prerecorded voice / ATDS to a cell) needs only **one** call, but
  requires proving the technology. That proof lives in recordings, not metadata.
- **New York is a one-party consent state** — the owner may lawfully record their
  own calls. Recordings are the highest-value evidence this project can ingest.
- Target venue is **NY small claims** (NYC Civil Court cap: $10,000). Damage
  calculations should therefore report the optimal *slice* of calls to plead per
  campaign, not just gross exposure.

## Invariants — do not violate these

1. **All numbers pass through `phone.normalize()` exactly once.** Call logs mix
   E.164, national, and formatted representations of the same line. Comparing raw
   strings silently double-counts. This bug already occurred once.
2. **Never conflate corroborated evidence with leads.** A DID block only joins a
   campaign if it shares a number with the behavioral cluster. Unattributed blocks
   are reported separately and labelled. Local businesses (hospitals, school
   districts) legitimately hold consecutive DIDs and look identical on the block
   signal alone.
3. **Keep the two detection signals separate.** Behavioral and infrastructure
   signals must be able to corroborate each other. Never blend them into one
   opaque score.
4. **Nothing in `data/` ever leaves the machine.** Call records are PII and
   litigation evidence. `.gitignore` excludes the whole directory. Do not add
   cloud sync, telemetry, or remote APIs that transmit call content.
5. **Auto-detected campaigns are derived data** — recomputed from scratch on each
   `analyze` run. Campaigns with `detection_method = 'manual'` are curated and
   must be preserved.
6. **Report findings honestly, including deflating ones.** Long call durations
   mean a real conversation and a legitimate business. Say so. An inflated case
   assessment is worse than no tool.

## Architecture

```
cli.py                    pull / ingest / analyze / report
src/tcpa/
  phone.py                NANP normalization. Everything routes through here.
  db.py                   Schema + rebuild_numbers() rollup.
  ingest/android.py       adb content-query pull and parse.
  analyze/campaign.py     Behavioral fingerprint + DID-block clustering.
data/raw/                 Source dumps (gitignored)
data/tcpa.db              SQLite (gitignored)
```

Standard library only, plus `tzdata`. **`tzdata` is not optional on Windows** —
without it `zoneinfo` fails and the 8am–9pm calling-window analysis silently
falls back to an approximation.

## Current state

Working: Android ingest, normalization, campaign clustering.
Not started: entity resolution, AT&T statement ingest, evidence-packet export,
recording ingest + transcription.

Known gap: device call log caps around 2,000 entries (~5 months here). Anything
older must come from AT&T statements, which are only retained ~16 months online.

## Tone

Do not oversell findings. The owner is going to stand in front of a judge with
this output. When the data does not support a claim, say that plainly and
explain what evidence would change the answer.

## Not legal advice

This produces prioritized leads and organized evidence. Whether to file is a
question for a lawyer.
