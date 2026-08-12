# Community corpus

Shared observations about **spam calling infrastructure**. Every file here
describes callers, never recipients.

## Why this exists

One person's records show a fragment of an operation. The same campaign hitting
a hundred people, from different numbers in different states, is visible only in
aggregate — and that aggregate is what identifies a defendant, supports a
regulatory referral, or establishes commonality across a putative class.

## Contribute

```bash
python cli.py contribute --out corpus/<your-campaign-id>.json
python scripts/validate_contribution.py corpus/<your-campaign-id>.json
```

Then open a pull request adding that one file.

**Read the file before you submit it.** It is plain JSON and short enough to
check by eye. If anything in it looks like it describes *you* rather than the
caller, do not submit it — open an issue instead, because that would be a bug.

## What a contribution contains

Only the caller's infrastructure:

- the calling numbers, their NPA-NXX blocks, and carrier/OCN
- coarse activity window, as year-month only
- bucketed observation counts (`3-5`, `11-25`) rather than exact figures
- the campaign fingerprint: dialing-hour shape, advertised callback numbers

## What it must never contain

Your phone number, name, location, area code, carrier, contact names, call
durations, or exact timestamps.

**Location plus timing is the classic re-identification pair**, so neither
appears — not even coarsened.

## Only campaign-attributed numbers

Contributions cover numbers already attributed to a detected campaign. They are
deliberately not "my whole call log, anonymized."

Any single spam number is harmless to publish. The complete *set* of numbers that
called you is not — that set is effectively a fingerprint of you, and anyone
holding another copy could correlate it back. A campaign is infrastructure many
people saw; your long tail of one-off callers is closer to a personal signature.

## Enforcement

`scripts/validate_contribution.py` runs on every pull request and enforces a
strict field allowlist. Anything outside it fails the build. This is a gate
rather than a review checklist, because reviewers cannot reliably spot a leak in
a JSON blob and should not be asked to.

CI also refuses any commit containing spreadsheets, databases, or files under
`data/`.

## Accuracy

Contributions are self-reported and unverified. Treat the corpus as a research
aid, not as evidence. Anyone can hand-write a JSON file, so a match here is a
lead to investigate — never a fact to assert in a filing.
