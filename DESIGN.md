---
version: 1.0
name: OpenWhistle — Signal
description: >
  The design system for OpenWhistle, a self-hosted whistleblower reporting
  platform (HinSchG / EU 2019/1937). A calm, monochrome "ink on surface"
  system broken by a single emerald accent used as full-bleed reassurance
  blocks. Sora carries display and body; JetBrains Mono carries every
  identifier a reporter must trust — case number, PIN, timestamps, deadlines.
  Depth comes from a surface ladder, hairlines, and colour — not decoration.
  First-class light and dark. All fonts are self-hosted (no CDN) to keep the
  reporter's browser from making a single third-party request.

colors:
  # Brand anchor — the emerald IS OpenWhistle's identity colour. `primary` names it
  # for tooling (light value); `accent` (below) carries the same emerald with its
  # light/dark pair and usage role.
  primary: "#0c7253"

  # Neutrals — the monochrome ground. Warm-neutral, chosen not defaulted.
  canvas:        { light: "#ffffff", dark: "#08080a" }   # page background
  surface:       { light: "#f6f6f5", dark: "#131315" }   # raised panels, table headers, inputs
  surface-2:     { light: "#ffffff", dark: "#1b1b1e" }   # cards floated above surface
  surface-3:     { light: "#e9e9e8", dark: "#232327" }   # one step above surface-2 (inline code, hover on a card)
  ink:           { light: "#0a0a0b", dark: "#fafafa" }   # headings, primary text
  body:          { light: "#3d3d40", dark: "#bcbcc0" }   # body copy
  muted:         { light: "#6a6a6e", dark: "#8e8e93" }   # secondary / metadata
  hairline:      { light: "#e6e6e4", dark: "#262629" }   # 1px borders & dividers
  hairline-strong: { light: "#d8d8d6", dark: "#34343a" } # borders that must read (outline button, toggle)

  # Inverse — a dark fill in BOTH themes: site footer, code blocks, terminal illustrations.
  inverse:       { light: "#0a0a0b", dark: "#050506" }   # the fill
  inverse-ink:   { light: "#fafafa", dark: "#fafafa" }   # text on inverse
  inverse-muted: { light: "#a1a1aa", dark: "#a1a1aa" }   # secondary text on inverse
  inverse-accent: { light: "#23c088", dark: "#23c088" }  # the dark-theme emerald, for marks on inverse (terminal prompt)
  inverse-warning: { light: "#d6a13c", dark: "#d6a13c" } # the dark-theme warning, for highlights on inverse (terminal string)

  # Accent — emerald. The ONE brand colour. Scarce as a button, generous as a block.
  accent:        { light: "#0c7253", dark: "#23c088" }   # one primary CTA, focus, selected state
  accent-strong: { light: "#0b6249", dark: "#1fa878" }   # accent hover
  accent-ink:    { light: "#ffffff", dark: "#06120d" }   # text/marks on an accent fill
  accent-weak:   { light: "#e5f3ee", dark: "#0d211a" }   # accent tint (selected chips, hover)

  # Semantic — status & feedback. SEPARATE from the accent, never used as brand colour.
  info:          { light: "#2f57e6", dark: "#6d8dff" }
  info-weak:     { light: "#eaeefc", dark: "#171b2e" }
  success:       { light: "#0c7253", dark: "#23c088" }   # equals accent by design — "resolved" is on-brand
  success-weak:  { light: "#e5f3ee", dark: "#0d211a" }
  warning:       { light: "#8a5a12", dark: "#d6a13c" }
  warning-weak:  { light: "#f6ecd9", dark: "#241c0d" }
  danger:        { light: "#bf3529", dark: "#f0776b" }
  danger-strong: { light: "#a82e23", dark: "#e0604f" }   # danger hover
  danger-weak:   { light: "#f8e7e4", dark: "#2a1512" }

typography:
  fonts:
    display: "Sora"                       # display + headings
    body:    "Sora"                        # body + UI
    mono:    "JetBrains Mono"              # identifiers, eyebrows, code
  # weight ceiling: 700 (hero only); 600 for every other heading; 400 body.
  scale:
    display-hero: { font: display, size: "clamp(34px, 5vw, 52px)", weight: 700, tracking: "-0.035em", leading: 1.05 }
    display-lg:   { font: display, size: "30px", weight: 700, tracking: "-0.03em",  leading: 1.1 }   # stat numbers
    heading:      { font: display, size: "24px", weight: 600, tracking: "-0.02em",  leading: 1.15 }
    heading-sm:   { font: display, size: "19px", weight: 600, tracking: "-0.01em",  leading: 1.2 }
    lead:         { font: body,    size: "18px", weight: 400, tracking: "0",        leading: 1.6 }
    body:         { font: body,    size: "16px", weight: 400, tracking: "0",        leading: 1.6 }
    body-sm:      { font: body,    size: "14px", weight: 400, tracking: "0",        leading: 1.55 }
    label:        { font: body,    size: "13.5px", weight: 600, tracking: "0",      leading: 1.4 }   # form labels
    hint:         { font: body,    size: "12.5px", weight: 400, tracking: "0",      leading: 1.5 }   # helper text
    eyebrow:      { font: mono,    size: "11.5px", weight: 700, tracking: "0.16em", transform: "uppercase" }
    mono-id-lg:   { font: mono,    size: "26px", weight: 700, tracking: "-0.01em", numeric: "tabular-nums" }  # receipt case number
    mono-id:      { font: mono,    size: "14px", weight: 400, numeric: "tabular-nums" }                       # table ids, PIN, dates

spacing:
  base: "4px"
  scale:
    x1: "4px"
    x2: "8px"
    x3: "12px"
    x4: "16px"
    x5: "20px"
    x6: "24px"
    x8: "32px"
    x10: "40px"
    x12: "48px"
    x16: "64px"
    x20: "80px"
    x24: "96px"     # section rhythm
  container:
    content: "960px"    # reading / form / status width
    app: "1080px"       # admin shell
    measure: "62ch"     # max line length for running text

rounded:
  none: "0px"
  sm:   "6px"      # inputs, chips, pills, small controls
  md:   "8px"      # buttons, cards, panels, the accent block
  lg:   "12px"     # frame / modal shells
  full: "9999px"   # circles only (dots, bullets, avatars) — never a CTA

elevation:
  flat:   "none (1px {colors.hairline} ring, drawn as box-shadow)"
  card:   { light: "0 1px 2px rgba(0,0,0,.05)", dark: "0 1px 2px rgba(0,0,0,.40)" }
  block:  "none — an accent fill IS the depth"
  overlay: { light: "0 8px 24px rgba(0,0,0,.12)", dark: "0 8px 24px rgba(0,0,0,.55)" }
---

# OpenWhistle — DESIGN.md

## Overview

OpenWhistle is where a person reports serious wrongdoing and is protected for
doing it. The interface has one job before any other: make an anxious first-time
reporter feel **safe, in control, and taken seriously** — then get out of the way.

"Signal" is a calm, monochrome system with a single emerald accent. Almost every
surface is ink-on-neutral; the accent appears rarely and deliberately — as the one
primary action on a screen, as focus, and — its signature move — as a **full-bleed
emerald block** that carries the three promises the platform makes: *anonymous, no
IP logging, encrypted*. Because the accent is scarce everywhere else, that block
lands with real weight.

Every value a reporter must remember or verify is set in **JetBrains Mono** — the
case number, the PIN, timestamps, deadlines. Mono signals "this is an exact,
machine-kept fact," and it visually separates the reporter's identifiers from
prose the way a receipt separates a total from marketing.

### Key characteristics

- **One accent, mostly withheld.** Emerald (`{colors.accent}`) is the only brand
  colour. Scarce as a button; generous as a reassurance block. Never decorative.
  Exception: a style C diagram uses it twice, for start and end (maintainer's
  choice, 2026-10-02, spec P2-4).
- **Type-forward, weight-restrained.** Sora everywhere, tight negative tracking on
  display, weight ceiling **700 for the hero and 600 for everything else**. No
  italics for emphasis; no third typeface for "personality."
- **Mono for facts.** Identifiers use `{typography.scale.mono-id}` with
  `tabular-nums` so digits line up and can't be misread.
- **Depth from structure, not shadow.** A three-step surface ladder
  (`{colors.canvas}` → `{colors.surface}` → `{colors.surface-2}`), 1px hairlines,
  and the accent block do the work. Shadows are a whisper (`{elevation.card}`).
- **Sober geometry.** `{rounded.md}` corners; **no pill CTAs**; `{rounded.full}`
  is reserved for status dots and avatars.
- **Both themes are real.** Dark is a warm-neutral near-black, not an inverted
  light theme. The accent brightens on dark (`#0c7253` → `#23c088`) to hold contrast.
- **Privacy is a design constraint.** Self-hosted fonts only — no CDN, no external
  request from the reporter's browser. Nothing that could log or fingerprint them.

## Colors

The ground is a warm-neutral monochrome ramp used for 95% of every screen. Pick
neutrals from the ladder by role, never by eye:

- `{colors.canvas}` — the page. Pure at rest.
- `{colors.surface}` — anything raised one step: panels, input fields, table
  headers, the browser-chrome of a framed screen.
- `{colors.surface-2}` — cards that float above a `surface` context.
- `{colors.ink}` / `{colors.body}` / `{colors.muted}` — a three-step text ramp.
  Carry hierarchy with these plus **weight**, not with mid-greys invented per page.
- `{colors.surface-3}` — one step above `surface-2`: inline code, hover on a card.
- `{colors.hairline}` — every 1px border and divider;
  `{colors.hairline-strong}` where it must read (outline button, toggle).
- `{colors.inverse}` — a dark fill in both themes (site footer, code, terminal);
  text on it is `{colors.inverse-ink}` / `{colors.inverse-muted}`; marks on it use
  `{colors.inverse-accent}` and `{colors.inverse-warning}` (the terminal illustration).
- `{colors.accent-strong}` / `{colors.danger-strong}` — hover of the accent and of danger.

**The accent is a budget, not a palette.** On any given screen the emerald appears,
at most: once as the primary button, on focus rings, on the selected chip
(`{colors.accent-weak}`), and — where the screen makes a promise — as one
full-bleed block filled with `{colors.accent}` and text in `{colors.accent-ink}`.
If a second emerald element wants to exist, remove one.

**Themes.** `[data-theme="light"] { color-scheme: only light }` and
`[data-theme="dark"] { color-scheme: dark }`: the toggle, not the OS, decides, so a
dark-mode browser cannot auto-darken a light page (forced dark would invert the tokens
above) and native controls and scrollbars follow the chosen theme.

**The app.** `--accent` follows the operator's primary colour: with the default brand
it equals `{colors.accent}` / `{colors.accent-strong}` / `{colors.accent-weak}` in both
themes; a custom `primary_color` derives its own family with `color-mix`
(`brand_accent()` in `app/templating.py`). Every other app token is a DESIGN.md value
(`tests/test_site_css.py::APP_TOKENS`).

**Semantic colours are not the accent.** Status and feedback use
`{colors.info}` / `{colors.success}` / `{colors.warning}` / `{colors.danger}` and
their `-weak` tints. `{colors.success}` deliberately equals the accent hue —
"resolved / received / safe" is the platform's happy path and reads as on-brand.
Because of that overlap, **never place a success pill and the primary CTA in the
same eyeline**; let context disambiguate.

### Report status → colour mapping

The `ReportStatus` values map to fixed semantic roles (keep this table and the
`ReportStatus` enum in sync):

| Status              | Role      | Pill background        | Pill text / dot    |
| ------------------- | --------- | --------------------- | ------------------ |
| `received`          | neutral   | `{colors.surface-2}`  | `{colors.muted}`   |
| `in_review`         | info      | `{colors.info-weak}`  | `{colors.info}`    |
| `pending_feedback`  | warning   | `{colors.warning-weak}` | `{colors.warning}` |
| `closed`            | success   | `{colors.success-weak}` | `{colors.success}` |

## Typography

Two families, three voices:

- **Sora** — display and body. A geometric-humanist sans: confident at large
  sizes, quiet at reading sizes. One family keeps the system coherent.
- **JetBrains Mono** — every identifier and the uppercase eyebrow label.

Set the scale from `{typography.scale}` and stay on it. The full ramp, largest to
smallest: `display-hero` → `display-lg` → `heading` → `heading-sm` → `lead` →
`body` → `body-sm` → `label` → `hint`, with `eyebrow`, `mono-id-lg`, and `mono-id`
as the mono voices.

### Principles

- **Negative tracking scales with size.** `-0.035em` on the hero, easing to `0` by
  body. Never track body or mono positively (except the eyebrow's `0.16em`).
- **Weight ceiling 700, and only the hero uses it.** Every other heading is 600.
  Nothing on the platform is heavier than the hero.
- **Eyebrows are mono, uppercase, `0.16em`.** They label a section or state
  (`CONFIDENTIAL REPORTING CHANNEL`, `CASE STATUS`); they are not decoration and
  must describe what follows.
- **Identifiers are mono with `tabular-nums`.** Case numbers, PINs, timestamps,
  deadlines, stat figures. Digits must align in columns and never re-flow.
- **Keep running text at `{spacing.container.measure}` (~62ch).** Reports and
  guidance are read, not skimmed.
- **`text-wrap: balance` on headings.** No orphaned single words on a hero line.

**Self-hosted fonts.** Sora (400/500/600/700) and JetBrains Mono (400/700) ship
from `app/static/fonts/` via `@font-face` in `app/static/css/fonts.css`. Never link
a font CDN — it would leak a request from the reporter's browser. If a face is
missing, the fallback is `system-ui, sans-serif` (body) / `monospace` (mono);
a missing face is a **bug to fix**, not a fallback to accept.

## Spacing & Layout

A 4px base grid; compose with `{spacing.scale}`. Lay groups out with flex/grid and
`gap` — never per-element margins that collapse or double.

- **Section rhythm is `{spacing.scale.x24}` (96px).** Major blocks breathe.
- **Inside cards: tight then loose.** ~`{spacing.scale.x2}` between a label and its
  value, a wider gap before the next group. "Large gaps outside, tight inside."
- **Containers.** Reading/form/status content maxes at
  `{spacing.container.content}` (960px); the admin shell at
  `{spacing.container.app}` (1080px). Wide content (tables, code) gets its own
  `overflow-x: auto` — the page body never scrolls sideways.
- **Framed screens.** Public screens render inside a `{rounded.lg}` frame with a
  faux browser bar showing the real host (`demo.openwhistle.net`) — it reassures
  the reporter they are on the right, safe surface.

## Elevation & Depth

Depth is structural. In priority order:

1. **Surface ladder** — `{colors.canvas}` → `{colors.surface}` → `{colors.surface-2}`.
2. **Hairlines** — a 1px `{colors.hairline}` ring (`box-shadow`) defines most edges
   (`{elevation.flat}`).
3. **Colour** — the accent block needs no shadow; the fill *is* the lift
   (`{elevation.block}`).
4. **A whisper of shadow** — cards may take `{elevation.card}`. Only true overlays
   (dropdowns, the session-expiry banner) use `{elevation.overlay}`.

Cards do not float dramatically. If two things need separating, prefer a hairline
or a ladder step before reaching for shadow.

## Shapes

- `{rounded.md}` (8px) — buttons, cards, panels, the accent block. The default.
- `{rounded.sm}` (6px) — inputs, chips, status pills, small controls.
- `{rounded.lg}` (12px) — frame and modal shells.
- `{rounded.full}` — circles only: status dots, list bullets, avatars, round icon badges.
- **No pill CTAs.** A pill-shaped button is off-system; buttons are `{rounded.md}`.
- The site reads the same scale from `docs/assets/css/tokens.css` (`--radius-sm` …
  `--radius-full`); its sheets write no other radius. A card or callout with an accent bar
  rounds only the corners away from the bar.

## Components

### Brand mark (K3)

A speech bubble with a keyhole: one evenodd path on a 24-unit grid, drawn in ink
(`currentColor`), never in the accent. It sits beside the "OpenWhistle" wordmark in
`display` weight 600, at 22px in the site nav, 18px in the site footer
(`{colors.inverse-ink}` at 50% opacity) and 24px in the app nav.

- The geometry lives in `scripts/render_icons.py` (`MARK`), which also renders the
  rasters (apple-touch 180px, `favicon.ico`, `github-avatar.png` 500px).
- Copies in `app/templates/base.html`, `docs/_includes/nav.html`, `footer.html` and both
  `favicon.svg` files are held identical by `tests/test_mark.py`.
- Favicons are the three-file set: ICO (`sizes="32x32"`), SVG switching ink by
  `prefers-color-scheme`, apple-touch.
- An operator's `brand.logo_url` replaces the mark in the app.
- Wordmark: OpenWhistle in ink, one weight, `translate="no"`.

### Buttons

- **Primary** — `{colors.accent}` fill, `{colors.accent-ink}` text, `{rounded.md}`,
  ~`12px 20px` padding, weight 600. **One per view.**
- **Secondary** — `{colors.canvas}` fill, a 1px `{colors.hairline}` ring, `{colors.body}` text;
  hover lifts to `{colors.surface}` and a `{colors.hairline-strong}` ring.
- **Ghost** — transparent fill, transparent border, `{colors.muted}` text; a low-emphasis
  action beside a primary/secondary one (e.g. an export alongside a reveal).
- **Danger** — `{colors.danger}` fill, white text, `{colors.danger-weak}` tint for its banner; destructive actions only.
- `:disabled` drops to `opacity: .4`. Focus is a 2px `{colors.accent}` outline,
  `2px` offset — always visible.

### Reassurance block (signature)

A single full-width band split into three cells, filled with `{colors.accent}`.
Each cell: a mono eyebrow in a lightened `{colors.accent-ink}`, a 600 headline, and
one line of `{typography.scale.body-sm}`. This is the platform's emotional anchor —
*Anonymous · No IP logging · Encrypted*. Use it **once** on the entry screen. It is
the only place the accent is used generously.

### Cards & panels

`{colors.surface-2}` fill, 1px `{colors.hairline}`, `{rounded.md}`, `{spacing.scale.x6}`
padding, optional `{elevation.card}`. A panel is the same at `{colors.surface}`.
Card titles use a mono `eyebrow` over a hairline rule.
The page's main content panel (`.panel-primary`, the report on the case page) carries a
3px inset top stripe in `{colors.ink}`, never `{colors.accent}`: the accent stays with the
view's one primary action.

### Stat cards (admin)

`{colors.surface}` card, mono `eyebrow` label, a `display-lg` figure with
`tabular-nums`, and a faint accent **sparkline** (SVG polyline in `{colors.accent}`)
showing trend. An `alert` variant recolours the label and figure to
`{colors.danger}` when a metric needs attention (e.g. overdue cases). Used only on
the statistics page.

### Charts

Bars in `{colors.ink}`, the current period in `{colors.accent}`, axis labels
muted, no gradients. Statistics-page only.

### Tables

Full-width, hairline row dividers, no vertical rules. `thead th` is a mono
`eyebrow`; `td` is `{typography.scale.body-sm}`. Case IDs and dates use `mono-id`
with `tabular-nums`. Row hover fills `{colors.surface}`. Wrap in `overflow-x: auto`.

### Status pills

`{rounded.sm}`, ~`4px 10px`, weight 600, a leading `{rounded.full}` dot in
`currentColor`. Colour strictly by the [status→colour table](#report-status--colour-mapping).
Pills read state at a glance and must never borrow the accent for a non-success state.

### Forms

- **Field** — a 600 `label`, the control, an optional `hint` in `{colors.muted}`.
- **Control** — `{colors.surface}` fill, 1px `{colors.hairline}`, `{rounded.sm}`,
  ~`11px 13px` padding, `{colors.ink}` text. Focus: `{colors.accent}` border + a
  soft `{colors.accent-weak}` ring.
- **Choice chips** — used for category and reply-channel selection. Unselected:
  `{colors.surface}` + hairline. Selected: `{colors.accent-weak}` fill,
  `{colors.accent}` text/border, weight 600.

### Submission wizard stepper

A single horizontal stepper (Category → Your report → Review & send). Done steps: a
`{colors.accent}`-outlined circle with a check; the active step: a filled
`{colors.accent}` dot and `{colors.ink}` label; upcoming: hairline circle,
`{colors.muted}`. Connector lines are 1.5px `{colors.hairline}`. **One** stepper
component platform-wide — do not fork a second progress pattern.

### Case-number / PIN receipt (signature)

The reporter's key to their report, framed like a receipt: a `{colors.surface}`
panel with a mono `eyebrow` ("YOUR CASE NUMBER"), the case number in `mono-id-lg`,
and the current status pill aligned opposite. Immediately below, a **PIN callout**
on `{colors.warning-weak}`: a warning glyph, the "keep this safe — it is the only
way back, we cannot recover it" message, and the PIN in a bordered mono token.
Treat the PIN with the visual gravity of a password.

### Status timeline

A vertical rail of nodes: done nodes filled `{colors.success}`; the current node
filled `{colors.accent}` with a `{colors.accent-weak}` ring; future nodes a hairline
circle. Each entry: a 600 title, a `body-sm` description, a mono timestamp. The
active node may carry an SLA chip (mono, `{colors.warning}` on `{colors.warning-weak}`)
showing the statutory deadline countdown (HinSchG acknowledgement / feedback windows).

### Secure message thread

Two-sided bubbles. Handler messages (`them`): `{colors.surface}` + hairline,
left-aligned. Reporter messages (`you`): `{colors.accent-weak}` + accent-tinted
border, right-aligned. Each bubble carries a mono `who` label ("CASE HANDLER",
"YOU · ANONYMOUS"). Max width ~80%.

### Alerts / banners

One banner system: `{rounded.md}`, `-weak` tint background, matching semantic
border and text, from `{colors.info}` / `{colors.success}` / `{colors.warning}` /
`{colors.danger}`. The demo banner and IP-warning banner are variants of this —
not separate components. Notification emails are plain text on purpose — no
tracking pixels, no remote images.

### Navigation & footer

Sticky nav on an opaque `{colors.canvas}` with a bottom hairline: mark +
wordmark left, utility controls (theme, language) right as equal-sized icon buttons
(1px hairline ring, `{rounded.md}`). Footer sits on `{colors.inverse}` in both themes,
text in `{colors.inverse-muted}`; the version string in mono.

### Printed case record

The PDF export is a printed record, not a screen — fixed ink on paper, so it takes its
own restrained palette rather than the live app's accent-forward one: section headings
`#0A0A0B` (ink) 13pt bold, one emerald `#0C7253` rule 0.6mm under the title only, row
labels muted `#6A6A6E`, values ink. Section dividers below the title use a hairline
`#D8D8D6`, not the accent — the accent marks the document once, at the top, the way a
letterhead does. Times the whistleblower caused — submission, the receipt, their messages —
print as the day only (`YYYY-MM-DD`, UTC), as on screen; the office's own times (its
messages, notes, acknowledged, closed, "Generated") keep `YYYY-MM-DD HH:MM UTC`. By
default the confidential name and contact are left out of the export — a row reads
"Identity: [on file — not included]" — the same rule as the on-screen case view: identity
is shown only through the audited reveal, whether that produces a page view or this PDF.
Text is set in DejaVu LGC Sans (Regular/Bold, bundled under `app/fonts/`, see its
`README`), not fpdf2's core Helvetica — a report written in Latin (with any diacritic),
Greek or Cyrillic script prints intact. CJK and right-to-left scripts (Arabic, Hebrew)
are outside this font and are not supported: those characters render as missing-glyph
boxes, not as the report's own text.

## Diagrams

Diagrams are drawn in **style C**: filled `{colors.surface}` cards, `{colors.ink}` arrows,
start and end in `{colors.accent}`, the result in `{colors.ink}`.

- Labels sit **beside** a line, never on it.
- Colours are **roles** (ink, surface, accent), never hex; each diagram ships a light and
  a dark twin picked by `data-theme`.
- Accent budget: the two accent nodes are the only exception to the one-accent rule.

How to draw one: `docs-tech/diagrams.md`.

## Motion

Restraint. Motion confirms, it does not entertain.

- **One page-load reveal.** Screens rise `~10px` and fade over `~0.5s`, staggered
  `~60ms`. That is the whole entrance.
- **Micro-feedback only** elsewhere: a `~0.15s` hover/focus transition on
  interactive surfaces, the accent focus ring.
- **Theme change** cross-fades background and text over `~0.3s`.
- Everything is wrapped in `@media (prefers-reduced-motion: no-preference)`; with
  reduced motion, state changes are instant.

## Voice & Copy

- **Address the reporter directly and calmly.** "Report a concern. Stay protected."
  Short sentences. Active voice.
- **Name things by what they are to a person**: *case number*, *PIN*, *reply
  channel* — never *token*, *UUID*, *thread ID*.
- **A control says exactly what it does** ("Submit a report"), and the result
  confirms it ("Report received & sealed").
- **Errors explain the fix, without apology or blame.** "Keep your PIN safe — it is
  the only way back to this report. We cannot recover it for you."
- **Never imply more safety than is true**, and never ask for identifying detail the
  report doesn't need — the copy is part of the protection.

## Do's & Don'ts

### Do

- Reserve `{colors.accent}` for one primary action, focus, selected state, and the
  single reassurance block per screen.
- Set every identifier a reporter must trust in `mono` with `tabular-nums`.
- Build depth from the surface ladder and hairlines first.
- Keep the report-status pills mapped exactly to the enum.
- Give dark mode the same care as light; verify the accent's contrast on both.

### Rules

| Rule | Status |
| --- | --- |
| `text-wrap: balance` on h1–h3 (site and app) | holds |
| `tabular-nums` for figures: site tables, code and pre; app tables, code, stat cards, case numbers, counters | holds |
| Never `transition: all`; name the properties | holds (tested) |
| Prose at most ~70 characters wide (measured at 1920px on docs, a post, the roadmap) | holds (tested) |
| Borders as shadows: a decorative edge is `box-shadow: 0 0 0 1px {colors.hairline}` | holds (tested) |
| Concentric radii: inner = outer − padding while the padding is below the outer radius | holds (tested) |
| `translate="no"` on the brand name and code | P3 |
| Persistent docs sidebar on desktop, search on top | P3 |
| At most three nav levels | P3 |
| Icons always with a text label | P3 |
| Copy: active voice, specific button labels, errors that name the way out | P3 (content work) |

**Borders as shadows.** Cards, panels, buttons, pills, code and terminal blocks draw their
edge as a ring (`box-shadow`), which takes no layout space and follows the radius. A
**structural** border stays a border: table row separators, section rules, and a callout's
or card's accent bar (`border-left` / `border-top`). Form controls keep a real 1px border too,
because it carries their focus state: inputs, selects, textareas, and the admin tables'
per-page select. Pagination pages are buttons and take the ring. Forced-colours mode drops shadows, so a
`forced-colors` block gives the same components a real border there.

**Concentric radii.** A rounded child in a rounded parent uses `outer − padding`. With a
padding at or above the outer radius the child is independent: its corner no longer follows
the parent's curve, so squaring every inner control would be wrong. Full pills nest as pills.

"P3" is page and content work in `docs-tech/specs/2026-10-01-website-redesign-design.md`
§ Delivery; the CSS-level rules above are kept by the stylesheets today.

### Don't

- Don't scatter emerald across icons, links, and borders — if a second accent
  element appears, remove one.
- Don't use `{rounded.full}` on a button, or any pill CTA.
- Don't exceed weight 700, or use 700 anywhere but the hero.
- Don't invent per-page greys, off-scale font sizes, or one-off radii — pull from
  the tokens.
- Don't add a third typeface, a gradient, or a decorative illustration.
- Don't let a success pill and the primary CTA share an eyeline (both are emerald).
- Don't load a font, script, or asset from any third-party host.
- Don't put an eyebrow above a heading that already says the same thing.
- Don't put more than five panels on a page.

## Responsive Behavior

- **Breakpoints** — desktop (default); layouts adapt at `900px`, `768px`, `640px`
  and `540px`; the admin shell alone breaks at `1024px`.
- **Touch targets** — interactive elements are `≥44×44px` on touch.
- **Reassurance block & stat grid** — 3/4-up on desktop → 2-up on tablet → 1-up on
  mobile.
- **Admin shell** — the sidebar sits beside the content at `≥1024px`; below that it
  collapses to a single column with the menu below the content.
- **Tables** — stack into labelled rows at `≤640px`; the page never scrolls
  sideways.
- **Report form** — the submit page's split layout stacks at `≤900px`, report form
  first, reassurance sidebar second.
- **Hero** — `display-hero` clamps down to ~30px on mobile.
- **Wizard & nav** — the stepper stays horizontal but tightens; nav padding
  collapses; the session-expiry banner docks to the bottom, full-width.

## Iteration Guide

- **Change a token, not a value.** Edit the front-matter (and its CSS custom
  property); never hardcode a hex, size, or radius in a component.
- **Verify both themes and the accent budget** on every screen touched: is emerald
  used more than once (plus the block)? If so, cut back.
- **Keep the three sources of truth in sync** — the app CSS (`app/static/css/`), the
  docs pages (`docs/en/index.html` and `docs/en/docs/index.html`), and `docker-compose.prod.yml`
  — in the same change (see the project design-sync rule).
- **`site.css` is hand-edited source; keep one rule per block.** The CSS is formatted for
  readability (not minified) and maintained by hand as the source of truth; the minified
  build artifact is generated at deployment time.
- **Lint** — `npx @google/design.md lint DESIGN.md` (format check) and `markdownlint`.
- **Every `{token}` used in prose must exist in the front-matter.** Adding a
  component may mean adding a token first.
