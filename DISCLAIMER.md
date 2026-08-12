# Disclaimer

## This is not legal advice

tcpa-analyzer organizes information you already have. It does not evaluate legal
claims, and no output should be read as a statement that you do or do not have
one.

Nothing here creates an attorney-client relationship. The contributors are not
your lawyers and, in general, are not lawyers at all.

Whether a claim exists depends on facts the software cannot see — whether you
consented, whether consent was revoked and how, whether an established business
relationship exists, which statute of limitations applies, and how your circuit
has ruled on questions like what counts as an autodialer. Those are questions for
a licensed attorney in your jurisdiction.

## What the outputs are, precisely

- **Complaint text** is a draft narrative for *you* to review, edit, and file
  under your own name. You are attesting to it. Read every line. Delete anything
  you cannot personally swear to.
- **Intake packets** are organized evidence summaries for an attorney to
  evaluate. Damages figures in them are arithmetic on call counts, not
  valuations, and not a prediction of recovery.
- **Fingerprints** describe calling infrastructure. A match means two records
  share infrastructure. It does not establish that any particular person or
  company placed any particular call.

## Accuracy limits you should assume

The data sources are imperfect and the tool says so in its own output:

- Carrier records omit unanswered calls and round durations to billed minutes.
  Measured against a device log, roughly half of inbound events were missing.
- NANPA data identifies the **holder of a number block**, not the subscriber and
  not the caller. Numbers port. Never assert in a filing that a carrier placed a
  call.
- FCC complaints about neighbouring numbers in a block are circumstantial. They
  describe infrastructure, not your specific calls.
- Campaign clustering is inference. Confidence scores are heuristics, not
  probabilities, and legitimate businesses holding consecutive numbers can look
  like a dialer on infrastructure signals alone.

## Do not use this to harass anyone

Numbers get misattributed. Spoofing means the number that called you often
belongs to an uninvolved stranger whose line was forged. Do not call back, publish,
or confront anyone on the strength of this tool's output.

## Your own conduct matters

Courts scrutinize plaintiffs whose call patterns look manufactured. Do not invite,
extend, or bait calls to increase a count. Keep your posture defensive: you
revoked consent, they ignored it.

Recording laws vary by state. Some require all parties to consent. Check your
state's law before recording anything, and do not assume a neighbouring state's
rule applies to you.

## No warranty

Provided "as is" under the MIT License, without warranty of any kind. You are
responsible for verifying every fact before relying on it.
