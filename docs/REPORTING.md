# Reporting to regulators

## Why bother

Most robocall operations are not worth suing. The worst ones are offshore shells
with no assets — enormous violation counts, zero collectability.

Regulators are the answer to exactly that problem. The FCC and FTC act on
**aggregated** complaint data: patterns across many complainants are what
identify a campaign, justify enforcement, and get carriers cut off from the
network. Your individual complaint is one data point in a case you could never
bring yourself.

This is the highest-value action for the majority of campaigns this tool finds.

## Generate the narrative

```bash
python cli.py complaint --state "New York" --out out/complaint.txt

# or one specific caller
python cli.py complaint --number 5551234567 --state "New York"
```

The output includes your call log for the caller or campaign, the carrier of
record, and any related public complaints.

## Then file it yourself

| Where | For |
|---|---|
| [reportfraud.ftc.gov](https://reportfraud.ftc.gov) | Fraud, scams, unwanted calls generally |
| [donotcall.gov/report.html](https://www.donotcall.gov/report.html) | Do Not Call registry violations |
| [consumercomplaints.fcc.gov](https://consumercomplaints.fcc.gov) | FCC informal complaint (Form 1088) |

**The tool does not submit anything, by design.**

A complaint is a sworn-ish statement you personally attest to. Software must not
attest on your behalf, and an automated filing you never read is a statement you
cannot stand behind. Automated submission would also violate those sites' terms,
and — most importantly — the agencies' value comes from aggregation across *real*
complainants. Machine-generated volume degrades the signal they depend on.

## Edit before filing

The generated text contains a bracketed `STATEMENT` section. Fill it in and
delete anything you cannot personally swear to.

What actually helps an investigator, roughly in order:

1. **What the caller said.** The pitch, the company name they claimed, the
   product. This is worth more than any volume statistic.
2. **The callback number** they gave you. Callback numbers persist and are
   traceable in a way disposable dialing numbers are not.
3. **Whether you asked them to stop**, and the date. Continuing after a request
   is a separate, more serious violation.
4. **Whether it sounded prerecorded**, or there was a pause before a human
   picked up. That pause is the signature of a dialer bridging you to an agent.

Volume alone is the weakest thing you can lead with. Specifics are what let an
investigator connect your complaint to others.

## What happens next

Nothing visible, usually. Agencies do not report back on individual complaints.
That is not the mechanism — you are contributing to a dataset that, in aggregate,
supports enforcement actions and traceback investigations.

The FCC complaint dataset this tool queries is that same corpus. Complaints filed
today become the evidence that corroborates someone else's campaign next year.

## Preservation letters

If you think you may eventually sue, consider sending your **carrier** a records
preservation request now. Self-service portals typically show 12–18 months, but
carriers retain internal records considerably longer. A preservation letter costs
postage, puts them on notice not to destroy call detail for your line, and keeps
the option open while you decide.

It is the only genuinely time-sensitive step here. Everything else waits; records
aging out of an archive do not.
