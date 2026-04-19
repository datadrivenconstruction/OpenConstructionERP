# Cookie Policy

**Effective date:** 2026-04-18

This Cookie Policy explains how OpenConstructionERP ("the Software") and
the hosted instance operated by DataDrivenConstruction ("DDC") use
cookies and similar browser-storage technologies. It is intended to
satisfy the baseline transparency obligations of the EU ePrivacy
Directive 2002/58/EC (as implemented by member-state law), the UK
PECR 2003, and applicable US state privacy laws.

## What we store in your browser

The Software uses the following categories of client-side storage. No
third-party advertising or tracking cookies are set.

| Name | Type | Purpose | Retention | Strictly necessary? |
|---|---|---|---|---|
| `oe_access_token` | `localStorage` | JWT bearer for API auth | Until logout | Yes |
| `oe_refresh_token` | `localStorage` | Refresh JWT | Until logout | Yes |
| `oe_locale` | `localStorage` | UI language preference | 1 year | Yes |
| `oe_theme` | `localStorage` | Light / dark mode | 1 year | Yes |
| `oe_layout` | `localStorage` | Sidebar widths, panel sizes | 1 year | No (functional) |
| `oe_widget_settings` | `localStorage` | Dashboard widget layout | 1 year | No (functional) |
| `oe_consent` | `localStorage` | Cookie-banner decision | 1 year | Yes |

All entries are first-party and remain on your device. The hosted
instance does not embed third-party analytics cookies by default.

## Optional integrations

Self-hosters who enable optional integrations (for example, a Sentry
error-reporting DSN or a Matomo analytics script) should extend this
page with the relevant cookie names and retentions.

## Your choices

- **Block or delete** cookies and local storage in your browser
  settings. The Software requires the "strictly necessary" entries
  above to function.
- **Withdraw consent** for functional cookies by clearing the
  `oe_consent` entry; the banner will reappear on next visit.

## Do-Not-Track and Global Privacy Control

The Software respects the `Sec-GPC` HTTP header and the
`navigator.doNotTrack` signal where an interpretation exists under
applicable law (primarily Colorado, Connecticut, and California). When
these signals are present, DDC does not enable optional analytics
integrations for your session.

## Updates

We may update this policy when we add or remove storage entries.
Material changes are listed in the release notes.

## Contact

- **Email:** privacy@datadrivenconstruction.io
