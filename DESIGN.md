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
  primary: "#0e7c5a"

  # Neutrals — the monochrome ground. Warm-neutral, chosen not defaulted.
  canvas:        { light: "#ffffff", dark: "#08080a" }   # page background
  surface:       { light: "#f6f6f5", dark: "#131315" }   # raised panels, table headers, inputs
  surface-2:     { light: "#ffffff", dark: "#1b1b1e" }   # cards floated above surface
  ink:           { light: "#0a0a0b", dark: "#fafafa" }   # headings, primary text
  body:          { light: "#3d3d40", dark: "#bcbcc0" }   # body copy
  muted:         { light: "#737377", dark: "#808085" }   # secondary / metadata
  hairline:      { light: "#e6e6e4", dark: "#262629" }   # 1px borders & dividers

  # Accent — emerald. The ONE brand colour. Scarce as a button, generous as a block.
  accent:        { light: "#0e7c5a", dark: "#23c088" }   # seal mark, one primary CTA, focus
  accent-ink:    { light: "#ffffff", dark: "#06120d" }   # text/marks on an accent fill
  accent-weak:   { light: "#e5f3ee", dark: "#0d211a" }   # accent tint (selected chips, hover)

  # Semantic — status & feedback. SEPARATE from the accent, never used as brand colour.
  info:          { light: "#2f57e6", dark: "#6d8dff" }
  info-weak:     { light: "#eaeefc", dark: "#171b2e" }
  success:       { light: "#0e7c5a", dark: "#23c088" }   # equals accent by design — "resolved" is on-brand
  success-weak:  { light: "#e5f3ee", dark: "#0d211a" }
  warning:       { light: "#8a5a12", dark: "#d6a13c" }
  warning-weak:  { light: "#f6ecd9", dark: "#241c0d" }
  danger:        { light: "#bf3529", dark: "#f0776b" }
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
  full: "9999px"   # avatars & status dots ONLY — never a CTA

elevation:
  flat:   "none (1px {colors.hairline} border)"
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
  light theme. The accent brightens on dark (`#0e7c5a` → `#23c088`) to hold contrast.
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
- `{colors.hairline}` — every 1px border and divider.

**The accent is a budget, not a palette.** On any given screen the emerald appears,
at most: once as the primary button, on focus rings, on the selected chip
(`{colors.accent-weak}`), and — where the screen makes a promise — as one
full-bleed block filled with `{colors.accent}` and text in `{colors.accent-ink}`.
If a second emerald element wants to exist, remove one.

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
2. **Hairlines** — a 1px `{colors.hairline}` border defines most edges
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
- `{rounded.full}` — status dots and avatars **only**.
- **No pill CTAs.** A pill-shaped button is off-system; buttons are `{rounded.md}`.

## Components

### Brand / seal mark

A small emerald square (`{rounded.sm}`, `{colors.accent}`) with an inset outline in
`{colors.accent-ink}` — a stylised wax seal — set beside the "OpenWhistle" wordmark
in `display` weight 600. The mark is the one place the accent always appears.

### Buttons

- **Primary** — `{colors.accent}` fill, `{colors.accent-ink}` text, `{rounded.md}`,
  ~`12px 20px` padding, weight 600. **One per view.**
- **Secondary** — transparent fill, `{colors.hairline}` border, `{colors.ink}` text.
- **Danger** — `{colors.danger}` fill, white text; destructive actions only.
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

### Stat cards (admin)

`{colors.surface}` card, mono `eyebrow` label, a `display-lg` figure with
`tabular-nums`, and a faint accent **sparkline** (SVG polyline in `{colors.accent}`)
showing trend. An `alert` variant recolours the label and figure to
`{colors.danger}` when a metric needs attention (e.g. overdue cases).

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
not separate components.

### Navigation & footer

Sticky nav on a translucent `{colors.canvas}` with a bottom hairline: seal +
wordmark left, utility controls (theme, language) right as equal-sized icon buttons
(1px hairline, `{rounded.md}`). Footer sits on `{colors.surface}` with a top
hairline; muted metadata; the version string in mono.

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

## Responsive Behavior

- **Breakpoints** — desktop (default), tablet `≤768px`, mobile `≤480px`.
- **Touch targets** — interactive elements are `≥44×44px` on touch.
- **Reassurance block & stat grid** — 3/4-up on desktop → 2-up on tablet → 1-up on
  mobile.
- **Tables** — below `480px` they scroll horizontally inside their wrapper
  (`min-width` floor); the page never scrolls sideways.
- **Hero** — `display-hero` clamps down to ~30px on mobile.
- **Wizard & nav** — the stepper stays horizontal but tightens; nav padding
  collapses; the session-expiry banner docks to the bottom, full-width.

## Iteration Guide

- **Change a token, not a value.** Edit the front-matter (and its CSS custom
  property); never hardcode a hex, size, or radius in a component.
- **Verify both themes and the accent budget** on every screen touched: is emerald
  used more than once (plus the block)? If so, cut back.
- **Keep the three sources of truth in sync** — the app CSS (`app/static/css/`), the
  docs pages (`docs/index.html` and `docs/docs.html`), and `docker-compose.prod.yml`
  — in the same change (see the project design-sync rule).
- **Lint** — `npx @google/design.md lint DESIGN.md` (format check) and `markdownlint`.
- **Every `{token}` used in prose must exist in the front-matter.** Adding a
  component may mean adding a token first.

## Known Gaps

- The tokens above are the **target** system. The live app CSS has not yet been
  migrated onto them — see the fix-list below.
- Charts beyond the stat sparkline (distributions, trends over time) are not yet
  specified.
- Email / webhook notification templates are outside this system and unstyled.
- No printed / PDF export style is defined for a case record.

## Migration Fix-List

The current frontend has drifted from any system. This is the prioritised cleanup
to perform when implementing "Signal" into `app/static/css/site.css`, the templates,
and `docs/`. It is a backlog, not part of writing this document.

### P1 — bugs (broken today)

- **Ship a real, loading typeface.** `fonts.css` declares `dm-sans-*.woff2` files
  that do not exist → the app silently falls back to `system-ui`. Adopt Sora +
  JetBrains Mono (already committed) and delete the phantom DM Sans wiring.
- **Style the public status pills.** `status.html` renders `.status-badge
  .status-*` classes that have **no CSS anywhere** — the reporter's status page
  pills are unstyled. Implement them per the status→colour table.
- **Define or remove undefined vars** referenced in templates: `--radius-sm`,
  `--bg-code`, `--text-primary` (a docs-only token leaking into `status.html`),
  `--surface-2` (login).
- **Dark mode must honour the accent.** Dark currently hardcodes `--accent:#3d7ec9`,
  ignoring the configured brand colour. Drive the accent from one token in both
  themes.

### P1 — token layer

- Wire the dead `--radius-*` scale and add a `--space-*` scale and a type scale;
  stop hardcoding `8px` / `12px` / `9999px` and ad-hoc font sizes per component.
- Remove dead tokens: `--brand-secondary`, `--accent-hover`, `--ink-active`
  (defined, referenced zero times).
- Collapse duplicate hex under different names (`--ink` == `--cta-bg`, etc.) and the
  ad-hoc greys (`#a1a1aa`, `#9ca3af`) that match no token.
- **One source of truth for brand colour.** It is currently triplicated across
  `app/config.py`, the `base.html` injection, and the `site.css :root` copy. Keep
  the config → CSS-var injection; drop the stale `site.css` duplicate.

### P2 — component dedup

- Merge near-duplicates: `.env-table` ≈ bare `table`; `.info-banner` ≈ `.alert`;
  the two steppers (`.submit-progress-*` vs `.progress-steps`); the two progress
  systems. Keep one of each.
- Unify naming — the `.stat-card` family alone uses kebab, BEM `__`, and BEM `--`
  for the same states. Pick one convention.
- Replace the CSP-era one-off classes with shared component/utility classes:
  `admin/report.html`'s `.rpt-1 … .rpt-56` numbered dump, the three re-implemented
  `1fr 2fr` admin grids (`.usr-layout` / `.cat-grid` / `.loc-grid`), the duplicated
  empty-states and page-headers, and the scattered `animation-delay` one-offs.

### P2 — unification & cleanup

- Fold `docs/index.html` and `docs/docs.html` onto the same tokens as the app (they
  currently run a separate serif/gold system).
- Remove orphaned fonts (`Source Serif 4`, `Nunito Sans`, unused `Spectral`
  weights) and reconcile the three font sources of truth: `fonts.css`, the
  Dockerfile download list, and the committed files in `app/static/fonts/` — down to
  exactly Sora + JetBrains Mono.
