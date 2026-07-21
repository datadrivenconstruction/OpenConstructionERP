# Sitemap generation

`generate-sitemap.mjs` builds `sitemap.xml` (and keeps `robots.txt`
pointed at it) for the OpenConstructionERP marketing site. It is
self-updating: it scans the actual web root on every run, so new pages
(a new `/news` post, a new top-level page, a new `/xx/` language
snapshot) are picked up automatically the next time it runs.

## What it includes

- The home page `/` plus every localized home snapshot `/de/`, `/fr/`,
  ... `/ko/` (19 languages). The home and each localized home carry the
  full reciprocal `hreflang` alternate cluster.
- Top-level marketing pages as clean, extensionless URLs
  (`/download`, `/services`, `/docs`, `/partners`, `/industries`,
  `/standards`, `/contact`, `/maturity`, `/license-request`, `/demo`,
  `/news`, `/privacy-policy`, `/terms-of-service`, `/cookie-policy`).
  (`imprint.html` is marked `noindex` by the page itself, so it is
  excluded automatically - see below.)
- Every news entry under `/news/` (extensionless), newest first.

## What it excludes

- Non-indexable pages: anything with `<meta name="robots" ... noindex>`
  or a `0;` meta-refresh redirect (e.g. `terms.html`). This is detected
  by reading each file's `<head>`, so future drafts are excluded
  automatically without editing a list.
- Dev/lab surfaces: `button-lab.html`, `hero-effects.html`,
  `viz-lab.html`, and the internal `download-module-variants.html`.
- `404.html`, backups (`*.bak*`), and asset/runtime dirs
  (`assets`, `i18n`, `locales`, `scripts`, ...).
- The `/pro/` tree (white-label / design-variant landing sites) - it is
  a separate property that ships its own `robots.txt` + `sitemap.xml`.

## Run locally

```sh
node scripts/generate-sitemap.mjs --dry-run     # print, do not write
node scripts/generate-sitemap.mjs               # write sitemap.xml + robots.txt
node scripts/generate-sitemap.mjs --root /path/to/webroot
```

`lastmod` uses the file's last git commit date when the tree is a git
repo, falling back to the filesystem mtime otherwise.

## Production (self-updating)

On the VPS the script lives at
`/root/clawd/openconstructionerp-tools/generate-sitemap.mjs` and runs
against the live docroot `/root/clawd/openconstructionerp` (mounted into
the Caddy container as `/srv-oce`). A daily cron regenerates it:

```
30 4 * * * /root/clawd/openconstructionerp-tools/regen-sitemap.sh >> /root/clawd/openconstructionerp-tools/regen-sitemap.log 2>&1
```

`regen-sitemap.sh` (also in this directory) is the wrapper the cron job
invokes.
