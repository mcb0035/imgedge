# Accessibility

ImgEdge hides one narrow category of images (arachnids) so that people who find
them distressing can browse the web comfortably. Most of its users can see the
rest of the page perfectly well — so low-vision, colour-blind, and
keyboard-/motor-impaired users are squarely in scope, and the two surfaces they
touch are held to **WCAG 2.1 AA** basics:

- the **settings popup** (all configuration), and
- the **blocked-image placeholder** that replaces a hidden image in the page.

This document records what we do, how we checked it, and the honest limits.

## Keyboard operability

Everything is reachable and operable without a mouse:

- The popup is built from **native controls** (`<input>`, `<button>`,
  `<details>`, radio buttons) inside `<label>`s, so Tab / Shift-Tab, Space, Enter,
  and arrow keys work as the platform expects — no custom widgets to trap focus.
- The **blocked-image placeholder** is a real control: `role="button"`,
  `tabindex="0"`, a visible focus outline, and it reveals the image on **Enter**
  or **Space** as well as on click.
- The **"explain decision" debug overlay** is focusable and can be dismissed with
  **Esc** (as well as by clicking it); it also auto-closes after a few seconds.

## Labelled controls

Every interactive control has a programmatic name: popup inputs are wrapped in
`<label>` elements, the detection-mode presets are native radio buttons with text
labels, the placeholder exposes its blocked URL via `title`, and the debug
overlay carries `role="status"` + an `aria-label` so a screen reader announces it.

## Colour is never the only signal

- The health line pairs its coloured status dot with **text** ("connected",
  "degraded", "offline"), so the state is clear without colour perception.
- The detection-mode presets are conveyed by label text and the native
  radio-selected state, not colour alone.
- The placeholder shows the word **"Blocked"** plus the reason as text, not just a
  colour or icon.

## Contrast

The popup declares `color-scheme: light dark` and follows the OS theme, so a
single fixed grey cannot pass in both themes. Muted and status text is therefore
driven by CSS custom properties (`--fg-muted`, `--fg-ok`, `--fg-warn`,
`--fg-bad`) with a `@media (prefers-color-scheme: dark)` override, and each value
is chosen for **≥ 4.5:1** contrast against its background (WCAG 1.4.3):

| Role   | Light (on white) | Dark (on ~`#1e1e1e`) |
| ------ | ---------------- | -------------------- |
| muted  | `#5f6368`        | `#9aa0a6`            |
| ok     | `#2e7d32`        | `#81c784`            |
| warn   | `#856404`        | `#e6b800`            |
| bad    | `#b3261e`        | `#f2896b`            |

The in-page placeholder renders on its own fixed light background (independent of
the site), and its red-on-`#fff5f5` text clears 4.5:1.

## Motion

ImgEdge has no animations, transitions, autoplay, or flashing content, so there
is nothing to disable for `prefers-reduced-motion` or the three-flashes
threshold.

## How this was checked

- Contrast ratios were computed with the WCAG relative-luminance formula for the
  light and dark values in the table above.
- Keyboard paths (popup tab order, placeholder Enter/Space, overlay Esc) were
  exercised manually.
- The popup and content script use only native, already-accessible HTML controls;
  the placeholder's `role`/`tabindex`/keyboard handlers live in
  [`extension/content.js`](../extension/content.js) and its focus style in
  [`extension/content.css`](../extension/content.css).

## Known limitations & scope

- The product's core value — *not showing* certain images — is inherently visual;
  a user who relies **entirely** on a screen reader and never sees images is not
  the primary audience. That said, the configuration UI is fully labelled and
  keyboard-operable for them, and the placeholder announces itself rather than
  leaving a silent gap.
- The popup is a **fixed-width** panel with pixel font sizes; it honours the
  browser's page/zoom but does not itself reflow to arbitrary widths.
- We have not run a formal audit with assistive-technology users. Findings are
  welcome.

## Reporting an accessibility issue

Please open an issue (or use the private channel in [`SECURITY.md`](../SECURITY.md)
if you prefer). Accessibility reports are triaged like bug reports under the
response targets documented in `SECURITY.md`.
