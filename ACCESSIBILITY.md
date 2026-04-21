# Accessibility Statement

**Effective date:** 2026-04-21
**Last reviewed:** 2026-04-21

This statement describes the accessibility status of
OpenConstructionERP ("the Software") and of the hosted instance
operated by DataDrivenConstruction ("DDC") at
<https://openconstructionerp.com> ("the Service").

## 1. Standards we target

OpenConstructionERP targets conformance with:

- **WCAG 2.1 Level AA** (W3C, 2018) across all user-facing
  web surfaces;
- **EN 301 549 V3.2.1** (European harmonised standard for
  ICT accessibility), which incorporates WCAG 2.1 AA;
- **BITV 2.0** (Barrierefreie-Informationstechnik-Verordnung)
  for deployments to German federal public bodies.

These standards are the reference points for the **European
Accessibility Act** (Directive (EU) 2019/882, national
transposition effective 28 June 2025) and for the U.S.
Section 508 procurement framework.

## 2. Current conformance status

**Partially conformant.** The Software meets most but not all
WCAG 2.1 Level AA criteria. Known non-conformance and
compensating information are documented in Section 4.

A formal accessibility audit (external party, manual + AT
testing) is planned; results will be published as a signed
**VPAT 2.5 (revised)** report alongside the next minor
release.

## 3. Measures taken

To support accessibility we:

- Ship the web UI as semantic HTML with ARIA landmarks and
  labels where native semantics are insufficient.
- Use Tailwind tokens for colour contrast and test primary
  palettes against WCAG AA contrast ratios (≥ 4.5:1 normal
  text, ≥ 3:1 large text).
- Support full keyboard navigation on all interactive
  controls (modal focus-trap, visible focus ring, logical tab
  order).
- Expose a dark / light theme that inherits the user's
  `prefers-color-scheme`.
- Respect the user's `prefers-reduced-motion` signal for
  animations.
- Localise strings through i18next (no client-side
  concatenation of translated fragments, which would break
  screen-reader announcements).
- Label form inputs with their text; error messages are
  associated to inputs via `aria-describedby`.

## 4. Known non-conformance (as of 2026-04)

| Area | Status | WCAG criterion | Plan |
|---|---|---|---|
| Complex BOQ tables - column-header association in deeply nested groups | Partial | 1.3.1 Info and Relationships | Refactoring to `scope`/`headers` attributes in the next minor. |
| AG Grid contextual menus - screen-reader announcements for filter pop-ups | Partial | 4.1.2 Name, Role, Value | Tracking upstream AG Grid roadmap; ARIA live-region wrapper planned. |
| PDF Markups canvas (three.js overlays) | Non-conformant | 1.1.1 Non-text Content | Alternative keyboard-accessible data view documented in the user manual; non-canvas alternative in backlog. |
| Onboarding wizard animations | Conformant when `prefers-reduced-motion` is honoured | 2.3.3 Animation from Interactions | - |

## 5. Accessibility features for self-hosters

If you deploy OpenConstructionERP on your own infrastructure,
you inherit the accessibility characteristics above. When you
extend the product:

- run `axe-core` or `lighthouse --accessibility` against your
  build before shipping;
- keep `prefers-reduced-motion` respect on any custom
  animations;
- use the project's i18next patterns rather than inline
  string concatenation.

## 6. Feedback and escalation

Accessibility feedback (issue, blocker, unmet need): email
`info@datadrivenconstruction.io` with subject line
**"Accessibility: <topic>"**. We respond to accessibility
feedback within **5 business days** and publish a resolution
timeline within **10 business days**.

If you are not satisfied with the response you may escalate to
the supervisory authority in your jurisdiction:

- **Germany:** Überwachungsstelle des Bundes für Barrierefreiheit
  von Informationstechnik (BFIT-Bund).
- **EU member states:** the national supervisory body designated
  under the European Accessibility Act (varies by country).
- **United States (federal procurement):** the GSA Section 508
  Accessibility office.

## 7. Contact

`info@datadrivenconstruction.io`
