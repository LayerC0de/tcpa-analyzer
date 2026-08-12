# For attorneys

## What this produces

An intake packet built to be triaged in one sitting, structured in the order a
TCPA practitioner actually evaluates a file.

```bash
python cli.py packet --state "New York" --dnc-since 2019-06-01 --out packet.txt
```

## Packet structure

**1. Plaintiff posture** — jurisdiction, National DNC registration date, and
every documented revocation with its method and whether a recording exists. If
there are no revocations the packet says so explicitly, and notes that the
willfulness multiplier is unavailable.

**2. Defendant attribution** — the calling numbers, the carrier of record and OCN
for each block, and any resolved legal entity with its registered agent and the
public source it came from. When no entity has been identified the packet states
that this is the blocking issue rather than burying it.

**3. Countable violations** — total calls, calls after the first documented
revocation, calls outside 8am–9pm local. Statutory figures are presented as
arithmetic on call counts and labelled as such. The packet does not characterize
which calls are countable or under which section; that is your call.

**4. Evidence and its limits** — a per-source breakdown with the known
deficiencies stated inline. Carrier-derived rows are flagged
`duration_estimated` because billing rounds to the minute and omits unanswered
calls entirely.

**5. What is not established** — the section that makes the rest usable.

## Why the gaps section exists

Consumer-generated intake material is usually worse than useless: inflated
damages, no consent analysis, no distinction between direct and circumstantial
evidence, and no acknowledgment of what is missing. It costs you a phone call to
discover the client has no case, and it costs the client credibility.

So the packet enumerates its own holes — no entity identified, no documented
revocation, no DNC date supplied, no device-log coverage, no recordings
referenced. If a packet reaches you claiming a strong case, the gaps section is
where you check that claim first.

## Provenance you can verify

Every enrichment fact traces to a public source you can independently check:

- **Carrier and OCN** from public NANPA thousand-block assignment data.
  Identifies the *block holder*, not the subscriber. Numbers port. The packet
  never asserts a carrier placed a call.
- **Entity records** from state corporate registries, stored with the source URL
  and a confidence value.
- **Third-party complaints** from the FCC's public consumer complaint dataset,
  with complaints about the client's exact numbers separated from complaints
  about neighbouring numbers in the same block.

## What it deliberately does not do

It does not assess whether a claim exists, estimate settlement value, calculate
limitations periods, or apply circuit-specific law on ATDS definitions,
revocation, or standing. Those judgments are yours.

It also does not identify who placed a call. Call records carry no identity. The
tool surfaces infrastructure and the subpoena path — carrier of record, OCN, and
callback numbers — which is where discovery starts, not where it ends.

## Class coordination

Users can export an anonymized campaign fingerprint describing only the caller's
infrastructure — number blocks, carriers, advertised callback numbers, dialing
pattern — with no personal data. Two clients hit by the same operation will match
on infrastructure while sharing nothing about themselves.

That may be useful for establishing commonality across a putative class before
anyone exchanges records. See [CLASS-ACTIONS.md](CLASS-ACTIONS.md).

## A note on scope

This project takes no fee, refers no clients, and has no relationship with any
firm. It is a data tool that produces documents its user owns and chooses what to
do with. It offers no legal conclusions — see [../DISCLAIMER.md](../DISCLAIMER.md).

Corrections from practitioners are genuinely welcome, particularly where the
packet's framing would not survive contact with a real docket. Open an issue.
