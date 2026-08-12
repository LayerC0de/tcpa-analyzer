# Finding others hit by the same operation

## The coordination problem

A class action needs many people hit by one operation. But the operation used
different numbers to call each of you — that is the whole point of rotation — so
comparing call logs looks like comparing unrelated data.

And comparing call logs means *publishing* call logs: who you bank with, which
clinic called, when you were awake. That is a lot to hand strangers on the
chance you were hit by the same dialer.

## Fingerprints

A fingerprint describes the **caller's infrastructure** and nothing about you.

```bash
python cli.py fingerprint --out my-campaign.json
```

```json
{
  "id": "a3f9c1d84b2e6071",
  "did_blocks": ["743286", "980517", "304971"],
  "carriers": [{"name": "EXAMPLE CARRIER LLC", "ocn": "321J"}],
  "callback_numbers": ["8005550147"],
  "hour_shape": "000000012456899876543210",
  "active_months": ["2026-03", "2026-04"],
  "call_volume_bucket": "51-100"
}
```

Every field is the spam operation's own infrastructure. No number of yours, no
name, no location, no exact timestamps. Full field-by-field justification in
[PRIVACY.md](PRIVACY.md).

## Matching

```bash
python cli.py fingerprint --match theirs.json mine.json
```

```
verdict          : SAME OPERATION  (score 0.71)
  DID blocks     : 0.42
  carriers       : 0.80
  callback nums  : 1.00
  shared callbacks: 8005550147
```

Weighting reflects how forgeable each signal is:

- **Callback numbers (45%)** — the strongest. An operation must be able to
  *receive* on these, so they cannot be spoofed and are rarely coincidental. A
  single shared callback number is close to conclusive.
- **DID blocks (30%)** — one dialer leasing one contiguous range.
- **Carrier OCNs (25%)** — weaker alone, since large carriers serve everyone, but
  meaningful in combination.

Any shared callback number returns *same operation* regardless of the numeric
score.

## Why this works when call logs don't

Operations are identified by the infrastructure they **reuse across victims**,
not by whom they happened to dial. You and a stranger in another state were
called from different numbers — but those numbers came from the same leased
blocks, bought from the same carriers, advertising the same callback line.

Fingerprints compare the constant and discard the variable. The variable is the
part that identifies you.

## Suggested workflow

1. Each person runs `analyze`, `enrich`, `complaints`, then `fingerprint`.
2. Publish fingerprints somewhere public — a gist, a forum thread, an issue in
   your own repo. They are safe to post.
3. Match against each other. Anything scoring `same operation` is a candidate
   group.
4. **Only then**, and only privately, exchange intake packets with counsel.

Fingerprints public, packets private. That ordering is the entire design.

## Honest limits

**A match is not proof.** It establishes that two records share calling
infrastructure. Whether one legal entity is responsible is a question for
discovery, and shared infrastructure can also mean two unrelated customers of one
wholesale carrier — which is exactly why carrier overlap is weighted lowest.

**Most matched campaigns will not be worth suing.** The operations most
disciplined about rotation are frequently offshore and judgment-proof. A large
matched group with no collectable defendant is a strong regulatory referral, not
a class action. See [REPORTING.md](REPORTING.md).

**This project coordinates data, not people.** It runs no registry, takes no fee,
refers no clients, and has no relationship with any firm. Whether a group has a
viable class — commonality, typicality, numerosity, adequacy — is a question for
licensed counsel.

## If you are organizing a group

Verify independently. Fingerprints are self-reported files; anyone can write one
by hand. Before treating a match as real, confirm the underlying records exist —
and be aware that a group forming around a shared grievance is an attractive
target for someone selling something.
