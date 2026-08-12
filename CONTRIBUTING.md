# Contributing

**Tested on Android + AT&T only.** That is the honest state of this project. If
you have a different phone or a different carrier, plugging in your device and
telling us what broke is the single most useful thing you can do — you do not
need to write any code to help.

## What we most need

### Carrier ingest modules

Only AT&T's `.xlsx` usage export is implemented. Every carrier formats records
differently, and none of it can be guessed from documentation.

Wanted: **Verizon, T-Mobile, Google Fi, Spectrum Mobile, Xfinity Mobile, US
Cellular, Mint, Visible**, and any regional carrier.

Even without code, this helps enormously:

1. Download one bill cycle of usage detail from your carrier
2. **Replace every phone number with fake ones** and delete anything personal
3. Open an issue with the redacted sample and note the format, the date range
   offered, and whether incoming calls are included at all

A redacted sample is usually enough for someone else to write the parser.

### iOS ingest

Not implemented. iPhone call history lives in an unencrypted local backup at
`HomeDomain/Library/CallHistoryDB/CallHistory.storedata` — a SQLite database.
Files are stored under hashed names, so look the path up in the backup's
`Manifest.db` rather than hardcoding a hash.

### Device SMS with message bodies

Carrier exports include text *metadata* but never message text, which makes it
impossible to tell a marketing blast from "your prescription is ready." Android
exposes `content://sms` over ADB — same mechanism as the call log — and that
does include the body. This would turn a large pile of unclassifiable messages
into something gradeable.

### Corrections from practitioners

If you work TCPA cases and the intake packet's framing would not survive contact
with a real docket, please say so. Legal framing errors are more damaging than
bugs.

## Ground rules

**Never commit real call records.** `data/` is gitignored in full. Redact
everything in issues, including in screenshots. If you need sample data for a
test, fabricate it.

**Do not add telemetry, analytics, or any upload path.** Local-first is the
entire security model, not a preference.

**Keep the two detection signals separate.** Behavioural and infrastructure
signals must be able to corroborate each other; never blend them into one opaque
score.

**Report findings honestly, including deflating ones.** A tool that inflates a
case is worse than no tool. If the data does not support a claim, the output must
say so.

See [CLAUDE.md](CLAUDE.md) for the full invariant list and domain vocabulary.

## Development

```bash
pip install -r requirements.txt
python cli.py --help
```

Standard library plus `tzdata` and `openpyxl`. If you are adding a dependency,
please justify it in the PR — a tool people run on their own legal records
should be auditable.

Run the pipeline end to end before opening a PR:

```bash
python cli.py ingest && python cli.py analyze && python cli.py targets
```

## Pull requests

Small and focused. Explain the reasoning, not just the change — this codebase
carries a lot of "why" in comments because the domain is full of traps that look
like bugs and bugs that look like features.

Pull requests are reviewed automatically by
[CodeRabbit](https://coderabbit.ai) (free for public repositories) in addition to
human review.

## Reporting a problem

Open an issue with what you ran, what happened, and what you expected. **Redact
all phone numbers.** If it involves a specific carrier or device, say which — the
answer is usually format-specific.

## Code of conduct

Be decent. This project attracts people who are frustrated and sometimes have
been defrauded; assume good faith and keep it useful. Harassment or using the
project to target individuals is not acceptable — see
[DISCLAIMER.md](DISCLAIMER.md) on misattribution.
