# tcpa-analyzer

Turn your phone records into **attributable** robocall claims — then report them,
hand them to a lawyer, or find other people hit by the same operation.

Runs entirely on your machine. Your call records never leave it.

> ### Tested on Android + AT&T only
>
> That is the honest state of this project — one phone, one carrier. Everything
> else is untested, and other carriers' exports almost certainly need their own
> parser.
>
> **You can help without writing any code.** Plug in your device, run it, and
> tell us what broke. A redacted sample of your carrier's export is usually
> enough for someone else to write the parser. iOS ingest and non-AT&T carriers
> are the biggest open gaps — see [CONTRIBUTING.md](CONTRIBUTING.md).

```bash
git clone https://github.com/YOURNAME/tcpa-analyzer
cd tcpa-analyzer && pip install -r requirements.txt
python cli.py pull        # pull the call log off a connected Android phone
python cli.py analyze     # cluster rotating-number campaigns
python cli.py enrich      # resolve carrier of record from public NANPA data
python cli.py targets     # rank callers by whether you could actually sue them
```

---

## The idea this is built on

**Pattern severity and suability are nearly uncorrelated.**

The number that called you forty times is usually a burner that belongs to
nobody. Real operations rotate through disposable numbers precisely so they
cannot be found. Meanwhile the defendant actually worth naming may have called
only twice — from a line whose subscriber is documented.

So this tool does not rank by volume. It optimizes for **attribution**: turning a
call event into a legal entity that can be named, served, and collected from.
Everything else follows from that.

A worked example from the dataset this was built on: the loudest thing in 16
months of records was a campaign of 51 rotating numbers across 35 area codes.
Enrichment traced 25 of them to a single VoIP wholesaler, and the callback
numbers led to an overseas advance-fee loan ring — enormous violation volume,
essentially zero collectability. The tool's job was to say so, early, instead of
producing an impressive-looking case against a defendant who would never pay.

## What it actually does

**Detects campaigns, not just numbers.** Two independent signals, kept separate
so they can corroborate rather than blur: a behavioural fingerprint
(burn-after-use call patterns) and infrastructure overlap (numbers drawn from the
same carrier blocks). Neither is trusted alone.

**Resolves the carrier of record** from public NANPA thousand-block assignment
data — free, no API key. This is who a subpoena or an industry traceback routes
through.

**Corroborates against 1.8M FCC complaints** (public dataset) to find independent
reports about the same infrastructure — including whether other people described
a *prerecorded voice*, which is the predicate for a §227(b) claim.

**Separates known contacts from strangers**, including the numbers you called
back. Calling someone is evidence of a relationship, which is the opposite of
what a TCPA claim requires.

## Three things you can do with the output

### 1. Report to regulators

```bash
python cli.py complaint --state "New York" --out complaint.txt
```

Produces complaint narratives with the call log, carrier of record, and related
public complaints. **It does not submit anything** — you read it, edit it, and
file it yourself at [reportfraud.ftc.gov](https://reportfraud.ftc.gov),
[donotcall.gov](https://www.donotcall.gov/report.html), or
[consumercomplaints.fcc.gov](https://consumercomplaints.fcc.gov). A complaint is
a statement you personally attest to; software should not attest for you.

### 2. Prepare an attorney intake packet

```bash
python cli.py packet --state "New York" --dnc-since 2019-06-01 --out packet.txt
```

Answers what a TCPA attorney checks first, in order: are you a plaintiff, is
there a defendant, what is it worth, can it be proven. Critically, it has a
**"what is not established"** section — an intake packet that hides its gaps
wastes the lawyer's time and costs you credibility on the first call.

### 3. Find others hit by the same operation

```bash
python cli.py fingerprint --out my-campaign.json
python cli.py fingerprint --match theirs.json mine.json
```

A class action needs many people hit by one operation. Finding each other
normally means publishing call records — who you bank with, which clinic called,
when you were awake.

A **fingerprint** describes only the caller: the number blocks it leased, the
carriers it bought from, the callback numbers it advertised, and the shape of its
dialing hours. No phone number of yours, no names, no exact timestamps. Two
strangers hit by the same operation will match on infrastructure while sharing
nothing personal.

See [docs/CLASS-ACTIONS.md](docs/CLASS-ACTIONS.md).

## What it does not do

It does not tell you whether you have a case. It does not submit complaints, file
anything, or contact anyone. It does not identify who is behind a number — call
logs carry no identity, and that limit is real.

It also cannot see what a carrier does not bill. Measured against a device log
over the same period, carrier records omitted **51%** of inbound calls — every
call that rang unanswered, plus true durations, since billing rounds to the
minute. Use carrier statements to reach further back in time, not as your primary
evidence.

## Data sources

| Source | Reach | Detail |
|---|---|---|
| Android call log (ADB) | ~2,000 entries | exact seconds, missed calls, contact names |
| AT&T usage export | ~17 bill cycles | billed minutes, no missed calls, texts |
| NANPA block data | public, free | carrier + OCN per thousand-block |
| FCC complaints | public, free | 1.8M records incl. call type |

iOS ingest and device SMS (with message bodies) are open — see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Privacy

Everything runs locally. `data/` is gitignored in full. No telemetry, no accounts,
no uploads. The only outbound requests are to public government and NANPA
endpoints, and they send a phone number prefix — never your own number.

Fingerprints are the one thing designed to be shared, and they are built to
contain nothing about you. [docs/PRIVACY.md](docs/PRIVACY.md) lists every field
and why it is safe.

## Not legal advice

This produces organized information. Whether a claim exists, is worth filing, or
is time-barred is a question for a lawyer. See [DISCLAIMER.md](DISCLAIMER.md).

## License

MIT — see [LICENSE](LICENSE).
