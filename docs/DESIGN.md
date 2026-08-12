# Design system

Reference craft: [amplemarket.com](https://www.amplemarket.com) — warm neutral
ground, near-black text, tightly-tracked display type, hairline inset borders
instead of drawn strokes, generous radii.

**Reference the craft, not the trade dress.** Do not copy their wordmark,
illustrations, colour identity, or copy. What follows is an original system that
borrows structural technique only.

---

## 1. Positioning, and why it changes everything

Amplemarket sells sales software. Its design job is to feel fast, modern, and
persuasive.

This product handles **legal evidence for people who have been defrauded**. Its
design job is the opposite: feel sober, precise, and restrained.

The tool's core value is that it tells users when they *do not* have a case. A
marketing site that oversells contradicts the product at the exact point where
the product is most valuable. Every design decision below follows from that.

**Tone rules**

| Do | Don't |
|---|---|
| "See who actually called you." | "Fight back against robocallers!" |
| State limits in the same weight as claims | Bury caveats in small grey text |
| Show a real terminal, real numbers | Fake dashboards, invented metrics |
| "Tested on Android + AT&T only" on the homepage | Imply universal support |
| Countdown-free, urgency-free | "Claim your $1,500 per call!" |

Never display a damages figure as a headline. Statutory arithmetic is not a
valuation, and a hero number promising money would attract exactly the users this
tool is worst for.

---

## 2. Colour

Warm neutrals, not grey. The ground is bone, not white; the ink is soft black,
not `#000`. This is the single most legible thing borrowed from the reference.

```css
:root {
  /* Ground — warm, low-glare, comfortable for long reading */
  --bg:            #F6F5F3;   /* page */
  --bg-raised:     #FBFAF9;   /* cards on page */
  --bg-sunken:     #EFEDEA;   /* wells, code blocks, table stripes */

  /* Ink */
  --text:          #111111;   /* primary — never pure black */
  --text-muted:    rgba(17,17,17,0.62);
  --text-faint:    rgba(17,17,17,0.40);

  /* Hairlines — see §5, these are shadows not borders */
  --line:          rgba(17,17,17,0.08);
  --line-strong:   rgba(17,17,17,0.16);

  /* Inverted surfaces — warm dark, never neutral grey */
  --ink-surface:   #272625;
  --ink-text:      #FBFAF9;
  --ink-muted:     rgba(255,255,255,0.62);

  /* Accent — used sparingly, for interaction only */
  --accent:        #1673D6;
  --accent-hover:  #1257A6;
  --accent-weak:   rgba(22,115,214,0.10);

  /* Evidence semantics — see §3 */
  --tier-a:        #1F7A4D;
  --tier-b:        #8A6A16;
  --tier-c:        #A2571C;
  --tier-d:        rgba(17,17,17,0.42);
  --warn-bg:       #FDF6E7;
  --warn-line:     rgba(138,106,22,0.28);
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg:          #171615;
    --bg-raised:   #1F1E1C;
    --bg-sunken:   #121110;
    --text:        #F6F5F3;
    --text-muted:  rgba(246,245,243,0.62);
    --text-faint:  rgba(246,245,243,0.38);
    --line:        rgba(246,245,243,0.10);
    --line-strong: rgba(246,245,243,0.20);
    --ink-surface: #F6F5F3;
    --ink-text:    #171615;
    --accent:      #5AA9F5;
    --accent-weak: rgba(90,169,245,0.14);
    --tier-a:      #5FCB92;
    --tier-b:      #E0B854;
    --tier-c:      #E8955A;
    --warn-bg:     #2A2418;
  }
}
```

Define every colour on bare `:root` first, then override in the dark block.
A colour whose only definition lives inside a media query breaks the light theme.

**Accent discipline.** Blue means *interactive*. It is never decorative, and it
never encodes evidence strength — tier colours do that, and conflating the two
would imply a link is a finding.

---

## 3. Tier colour is a semantic contract

Tier A–D is the product's core judgment. Its colours must be readable as meaning,
not decoration.

| Tier | Token | Meaning |
|---|---|---|
| A | `--tier-a` green | Identifiable business with complaint history |
| B | `--tier-b` amber | Identifiable, unverified |
| C | `--tier-c` orange | Partially identifiable |
| D | `--tier-d` grey | Unattributable — deliberately *drained of colour* |

Tier D being grey rather than red is deliberate. Red reads as *dangerous*, which
would rank the loudest burner highest — the exact inversion the whole tool
exists to correct. Unattributable means *not worth your attention*, and grey
says that.

**Never use colour alone.** Always pair with the letter and a text label; roughly
1 in 12 men has a colour-vision deficiency, and this is legal information.

---

## 4. Type

The reference uses a proprietary grotesk. Substitute an open one with a true
variable axis and tight default tracking.

```css
--font-sans: "Inter Variable", Inter, -apple-system, BlinkMacSystemFont,
             "Segoe UI", Roboto, sans-serif;
--font-mono: "JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace;
```

Display sizes are tracked **tighter** and led **shorter** as they grow — the
signature move of the reference (h1 at `-0.03em`, line-height ≈ 1.0).

| Role | Size (desktop) | Weight | Tracking | Line-height |
|---|---|---|---|---|
| Display | `clamp(2.75rem, 6vw, 4.5rem)` | 500 | `-0.035em` | 1.00 |
| H1 | `clamp(2rem, 4vw, 3rem)` | 500 | `-0.03em` | 1.05 |
| H2 | `1.75rem` | 500 | `-0.02em` | 1.15 |
| H3 | `1.25rem` | 500 | `-0.015em` | 1.25 |
| Body-lg | `1.125rem` | 400 | `-0.005em` | 1.6 |
| Body | `1rem` | 400 | `0` | 1.6 |
| Small | `0.875rem` | 400 | `0` | 1.5 |
| Caption | `0.8125rem` | 400 | `0.005em` | 1.45 |
| Mono | `0.875rem` | 400 | `0` | 1.5 |

**Phone numbers, OCNs, and carrier names are always monospace** with
`font-variant-numeric: tabular-nums`. Digits must align vertically in every
table — a misread digit is a misidentified caller.

Body copy caps at **68ch**. Never full-bleed paragraphs.

---

## 5. Hairlines: the signature technique

The reference draws almost no `border`. It uses a 1px **inset box-shadow**, which
does not affect layout, does not compound at corners with `border-radius`, and
sits visually *inside* the shape.

```css
--hairline:        inset 0 0 0 1px var(--line);
--hairline-strong: inset 0 0 0 1px var(--line-strong);

--shadow-sm: 0 1px 2px rgba(17,17,17,0.04);
--shadow-md: 0 12px 40px rgba(0,0,0,0.08);
--shadow-lg: 0 26px 60px -6px rgba(25,34,35,0.12);
```

Cards use `--hairline` **plus** `--shadow-sm`. Elevation alone reads as
weightless; hairline alone reads as flat. Both together is the look.

### Radii

```css
--r-sm: 4px;    /* inputs, chips, tags */
--r-md: 8px;    /* buttons, small cards */
--r-lg: 12px;   /* cards, panels — the dominant value */
--r-xl: 20px;   /* hero surfaces, modals */
--r-full: 999px;
```

`12px` is the default. When unsure, use `--r-lg`.

---

## 6. Space and layout

A 4px base scale: `4, 8, 12, 16, 24, 32, 48, 64, 96, 128`.

```css
--container:  1328px;   /* outer max */
--content:    728px;    /* prose max */
--card-min:   384px;    /* grid card floor */
--gutter:     clamp(1rem, 4vw, 2.5rem);
```

Vertical section rhythm: `clamp(64px, 10vw, 128px)` top and bottom. Consistent
rhythm is what makes a long page feel composed rather than stacked.

---

## 7. Components

### Button

```
Primary    bg --ink-surface, text --ink-text, --r-md, 12px/20px, weight 500
Secondary  bg --bg-raised, --hairline, text --text
Ghost      transparent, text --text-muted -> --text on hover
Danger     never used. This product performs no destructive action.
```

Hover: `translateY(-1px)` + `--shadow-sm`. Active: `translateY(0)`.
Focus: `outline: 2px solid var(--accent); outline-offset: 2px` — **never remove
it**, and never rely on hover alone to convey state.

### Card

`--bg-raised`, `--r-lg`, `--hairline`, `--shadow-sm`, padding 24–32px.

### Evidence table

The most important component in the product.

- Monospace tabular numerals for all numeric columns
- Right-align counts and durations; left-align names
- Row stripe `--bg-sunken` at 50% opacity
- Sticky header with `--hairline` beneath
- Wrap in `overflow-x: auto` — **the page body must never scroll horizontally**
- Tier badge: letter + label, `--r-sm`, tier colour at 12% as background and
  full strength as text

### Caveat block

A first-class component, not an afterthought. Used wherever the tool states a
limit — *"carrier records omit 51% of inbound calls"*, *"a match is not proof"*.

`--warn-bg`, `--hairline` in `--warn-line`, `--r-md`, 16–20px padding, an icon at
`--tier-b`. **Same type size as body copy.** Shrinking a caveat is the visual
equivalent of hiding it, and that is precisely the failure mode this product must
avoid.

### Terminal block

`--ink-surface`, `--ink-text`, `--r-lg`, mono, 20–24px padding. Show **real
output**, never a mockup. If a number appears, it is fabricated (`555-01xx`) and
labelled as an example.

---

## 8. Marketing page architecture

Twelve sections is about right; the reference uses twelve.

1. **Nav** — sticky, `--bg` at 80% + `backdrop-filter: blur(12px)`, hairline
   beneath on scroll. Left wordmark; right: Docs, GitHub, primary CTA.
2. **Hero** — display headline, one-sentence subhead, two CTAs, and the
   *"Tested on Android + AT&T only"* badge **in the hero**, not the footer.
   Right side or below: a real terminal block.
3. **The premise** — the one idea that differentiates this: severity and
   suability are nearly uncorrelated. A two-column diagram, loudest caller vs.
   suable caller.
4. **How it works** — three steps: plug in phone → analyze → act. Numbered,
   monospace step markers.
5. **What you get** — three cards mapping to the three workflows: report to
   regulators, attorney packet, find co-claimants.
6. **Privacy** — full-width `--ink-surface` inversion. The strongest visual break
   on the page, because it is the strongest claim. "Runs entirely on your
   machine. No accounts. No telemetry. No uploads."
7. **Fingerprints** — the class-action mechanism. Show a real JSON fingerprint
   in a terminal block beside a plain-language explanation of what is excluded.
8. **Honest limits** — a full caveat section, not a footnote. This is the
   section competitors would never ship, and it is the reason to trust this one.
9. **Open source** — repo, licence, contribution ask, CodeRabbit-reviewed PRs.
10. **For attorneys** — separate audience, separate card grid, link to
    `FOR-LAWYERS.md`.
11. **FAQ** — accordions; lead with "Do I have a case?" answered honestly ("this
    tool cannot tell you that").
12. **Footer** — docs, disclaimer, privacy, GitHub. Disclaimer link at body size.

---

## 9. Phase two: the app UI

The CLI becomes: **plug in phone → confirm a few settings → results**.

### Flow

```
1  Connect      detect device over ADB/WebUSB; live status, plain-language errors
                ("that looks like a charge-only cable")
2  Consent      explicit screen: what is read, where it goes, what never leaves.
                Not a checkbox in a footer.
3  Settings     state (drives calling-window + statute), DNC registration date,
                timezone. Three fields, sensible defaults, each with a one-line
                reason it matters.
4  Analyzing    real progress with named stages, not a spinner. Enrichment is
                rate-limited and slow; say so and show the count.
5  Results      tier table, campaign cards, honest empty state
6  Act          three exits: complaint / packet / fingerprint
```

### Design obligations specific to the app

**The empty state is the most important screen.** Most users will have no viable
claim. "No attributable campaigns found" must read as a *successful, informative
result* — same visual weight as a positive one, with an explanation of what that
means and what would change it. If a null result looks like failure, users will
hunt for a case that isn't there.

**Never render a damages figure without its caveat adjacent.** Same screen, same
type size, not a tooltip.

**Progress must be honest.** Enrichment takes ~1s per exchange. Show
`43 / 217 exchanges` rather than a fake percentage.

**No dark patterns.** No urgency, no artificial scarcity, no upsell interrupting
results. The user is looking at a record of being harassed.

---

## 10. Motion

Restrained. `150ms` for micro-interactions, `240ms` for surfaces, easing
`cubic-bezier(0.2, 0, 0.2, 1)`.

Fade + 8px rise on section entry, staggered 60ms. Nothing parallax, nothing
auto-playing, nothing that moves while text is being read.

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

---

## 11. Accessibility floor

Not optional. Users of this product skew older and include people already
targeted for exploitation.

- Body text ≥ **4.5:1**; large text and UI ≥ **3:1**. Verify `--text-muted` on
  `--bg-raised`, which is the pairing most likely to fail.
- Every interactive element reachable and visibly focusable by keyboard.
- Tier meaning never conveyed by colour alone.
- Tables use real `<th>` with `scope`; never a grid of divs.
- Respect `prefers-reduced-motion` and `prefers-color-scheme`.
- Minimum tap target 44×44px.
- Base font never below `16px` on mobile — smaller triggers iOS zoom-on-focus.

---

## 12. Implementation notes

Stack-agnostic; the tokens are plain CSS custom properties. If using Tailwind,
map these to theme values rather than reaching for default palette utilities —
`gray-100` is cold and will fight the warm ground.

Wide content (tables, terminal blocks, diagrams) scrolls inside its own
`overflow-x: auto` container. The body never scrolls sideways.

Ship no web fonts you cannot self-host. This project makes privacy claims; a
third-party font CDN on the marketing site would undercut them on the very page
where they are made.
