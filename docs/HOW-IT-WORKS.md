# How it works

## The problem

A call log records that a number called you. It does not record who that is. Spam
operations rotate through disposable numbers specifically so that the log is a
dead end — and the more abusive the operation, the more disciplined it usually is
about rotation.

So the useful question is not "who called most?" It is **"which of these callers
could I actually name, serve, and collect from?"**

## Campaign detection

One operation, many numbers. Two independent signals are computed separately and
never blended, so they can corroborate each other.

### Behavioural fingerprint

Burn-after-use: exactly two calls, the same day, one brief connect and one that
never connects — then the number is retired forever.

Legitimate callers do not behave this way. They either reach you or keep trying.
A number used once and abandoned is a number bought to be thrown away.

### DID block collision

Numbers are allocated to carriers in contiguous thousand-blocks. Two spam numbers
sharing an NPA-NXX prefix usually means one dialer leasing one block.

This signal has a real false-positive mode: a hospital or school district
legitimately holds consecutive numbers and looks identical. So any block where a
number held a conversation of 3+ minutes is discarded, and a block only joins a
campaign if it shares at least one number with the behavioural cluster.
Unattributed blocks are reported separately, labelled as leads rather than
members.

### Carrier concentration

The strongest signal, added after enrichment. Numbers scattered across twenty
area codes that all resolve to one small VoIP wholesaler is not coincidence —
geography can coincide, wholesale purchasing cannot. Per-state subsidiaries are
collapsed to a parent carrier first, or one operation buying from one carrier's
state entities looks like a dozen unrelated carriers.

Confidence weights cluster size 40%, block corroboration 25%, carrier
concentration 35%. These are heuristics, not probabilities.

## Carrier attribution

Public NANPA thousand-block assignment data resolves each number to the carrier
holding its block, at NPA-NXX-**X** granularity. That precision matters: one
exchange is routinely split between a wireless carrier, an incumbent, and a VoIP
wholesaler, and only the thousand-block says which one issued the number.

**This identifies the block holder, not the subscriber.** Numbers port. For
dialer numbers the distinction rarely matters — spam operations buy wholesale and
do not port — but never state in a filing that a carrier placed a call. The
carrier is who you subpoena and where a traceback starts.

## FCC complaint corroboration

The FCC publishes ~1.8M consumer complaints with the reported caller ID, the
callback number the pitch advertised, and the **type** of call — including
"Prerecorded Voice" and "Abandoned Calls."

This matters because §227(b) attaches to prerecorded and autodialed calls and
needs only one call, but the technology must be proven, and a call log cannot
show it. Independent complainants describing the same infrastructure as
prerecorded is circumstantial evidence of how the operation dials.

Circumstantial, not direct. Every stored complaint carries an `exact_match` flag
distinguishing a complaint about *your* number from one about a neighbouring
number in the same block. Do not conflate them in a filing.

## Callback numbers

Burner numbers are disposable because the operation only ever dials *out* on
them. Callback numbers are the opposite: the operation must be able to **receive**
on them, so they persist, accumulate national complaint histories, and are far
harder to make anonymous.

They are the best free path from infrastructure toward a named seller — and their
date ranges reveal when an operation rotated to a fresh line.

## Known contacts

Any number is excluded from spam analysis if an address-book name was ever
attached to it, **or if you ever placed an outgoing call to it.**

The second test carries the weight for carrier data, which exports no contact
names at all. Without it every relative and doctor's office scores as an
unsolicited caller — and because those call often, they dominate the ranking.
Calling someone is also affirmative evidence of a relationship, which is the
opposite of the "no prior express consent" a claim requires.

## Source precision

Device logs and carrier records are both stored, tagged, and kept separate:

- `duration_estimated` marks rows whose duration came from billed minutes.
  Duration-sensitive analysis excludes them — the burn-after-use fingerprint
  keys on a zero-duration call, and carriers cannot represent one.
- `dup_of_device` marks carrier rows restating a call the device log already
  has. They are kept rather than dropped, so the two sources can be compared —
  and that comparison is what quantifies how much the carrier omits.

Run `python scripts/compare_sources.py` on any overlapping period to measure it
for your own records.
