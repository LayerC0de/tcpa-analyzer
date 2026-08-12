# Privacy

## Where your data lives

On your machine, in `data/`. That directory is gitignored in full — raw exports,
the SQLite database, generated packets, and any audio.

There are no accounts, no telemetry, no analytics, and no upload path. The tool
has no server.

## What leaves your machine

Only two things, both optional, and neither sends your phone number.

**Carrier lookups** (`enrich`) request a **six-digit prefix** of a calling
number — the NPA-NXX of the number that called *you* — from a public
number-administration service. Your own number is never transmitted.

**FCC complaint queries** (`complaints`, `callbacks`) query a public government
dataset by calling-number prefix or by callback number. Again, these are the
spam operation's numbers, not yours.

Nothing else makes network requests. You can run the entire ingest, campaign
detection, targeting, packet, and fingerprint pipeline fully offline; only the
two enrichment steps need a connection.

## Fingerprints: the one thing designed to be shared

A fingerprint describes the **caller's infrastructure** and nothing about the
recipient.

### Included

| Field | Why it is safe |
|---|---|
| `did_blocks` | Six-digit prefixes of the *spammer's* numbers |
| `area_codes` | Spammer's area codes |
| `carriers`, `ocn` | Which carriers the spammer bought numbers from |
| `callback_numbers` | Numbers the spammer advertised for people to call |
| `hour_shape` | 24 digits, 0–9, normalized — the dialer's working pattern |
| `active_months` | Year-month only, e.g. `2026-03` |
| `call_volume_bucket` | A range such as `51-100`, never an exact count |
| `number_count`, `confidence` | Aggregate campaign statistics |

### Deliberately excluded

- **Your phone number, name, carrier, or location.** Nothing identifies the
  recipient.
- **Exact call timestamps.** A precise timeline is a record of your life, and it
  is the field most likely to re-identify you by correlation against any other
  dataset you appear in. Month buckets and a normalized hour shape match
  campaigns just as well.
- **Durations, contact names, text content.** Not needed to match a campaign.

This still matches reliably, because operations are identified by the
infrastructure they reuse across victims — not by whom they happened to dial. Two
strangers hit by one operation share number blocks and carriers while sharing
nothing personal.

Inspect any fingerprint before sharing it. It is plain JSON:

```bash
python cli.py fingerprint --out mine.json && cat mine.json
```

## What to be careful about

**Intake packets and complaint text contain your full call history.** That is the
point — they are for your attorney or a regulator. They are not for a public
forum, an issue tracker, or a group chat. Share fingerprints publicly; share
packets privately.

**Bug reports.** Never paste raw records into an issue. Redact numbers, or better,
report the shape of the problem rather than the data.

**Recordings**, if you make any, are audio of real conversations and may contain
third-party voices. `.gitignore` excludes common audio formats, but check before
committing anything.

## Threat model, stated plainly

This tool protects against *accidental* disclosure — committing your records,
leaking them through telemetry, or exposing yourself when coordinating with
strangers.

It does not protect against someone with access to your computer. The database is
not encrypted. If that matters for your situation, use full-disk encryption.
