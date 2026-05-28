# CLAUDE.md — marketing-site

Static marketing surface for **openconstructionerp.com**. Vanilla HTML/CSS/JS, **zero build step**, **no platform code**. An agent working here can ship copy edits, new pages, news articles, locale strings, and Caddy/SEO tweaks **without ever touching `backend/`, `frontend/`, `services/`, or `packages/`**.

This document is the **boundary contract** for the parallel-agent split:
- `marketing-site/**` + this CLAUDE.md → website agent's territory.
- `backend/`, `frontend/`, `services/`, `packages/`, `data/`, `deploy/` → platform agent's territory.
- Root `CHANGELOG.md` and `README.md` → **platform agent only** (PyPI long-description). News articles about a release belong here; the changelog/README about that release lives in the platform tree.

---

## Identity

OpenConstructionERP's public website. Five surfaces:

| Surface | Purpose | Updated when |
|---|---|---|
| Landing (`index.html`) | Headline, demo CTA, feature carousel, social proof | Major releases, positioning shifts |
| Practices / Industries / Standards / Maturity | Vertical-specific pages | Quarterly |
| News (`news.html` + `news/v*.html`) | Release announcements + concept papers | Every PyPI release |
| Partners / Docs / Pricing | Static reference content | Rare |
| Demo register (`demo-register.html` + `demo-register-api.py`) | Lead capture for /license-request | Pricing / form changes |

The site is **read-only** from the user's perspective except for one form: `demo-register.html` POSTs to a tiny Python sidecar (`demo-register-api.py`) that appends a JSON line to `/root/clawd/license-requests.jsonl` on the VPS. **This sidecar is the only dynamic piece on the marketing surface** — everything else is plain HTML.

---

## Tech stack

- **Plain HTML + CSS-in-page + vanilla JS.** No React, no Vite, no build pipeline, no `node_modules`. Save the file → reload the browser.
- **CSS variables for theming.** Both light and dark themes live in inline `<style>` blocks at the top of each page (search for `:root {` and `[data-theme="dark"]`). Theme is persisted in `localStorage` as `oce-theme`.
- **Fonts**: Inter (body), Inter Tight (display), JetBrains Mono (code). Loaded from `fonts.googleapis.com` with `preconnect` hints in `<head>`.
- **No external JS frameworks.** The "More from the blog" widget (`news/assets/related-articles.js`) is ~470 lines of vanilla JS with its own inline article catalog — no fetch, no XHR, no tracking.
- **i18n** is JSON files under `locales/` (20+ languages). Loaded at page boot by `assets/i18n.js` (lazy, on demand). Each top-level key maps 1:1 to a CSS-selector-targeted node group via `data-i18n` attributes in the HTML.

No package.json. No `npm install`. No tsconfig. **If you find yourself reaching for a build tool, stop** — the answer is almost always a tiny vanilla snippet.

---

## Directory structure

```
marketing-site/
├── CLAUDE.md                  ← this file
├── Caddyfile                  ← reverse-proxy + SSL + headers, deployed at openconstructionerp.com
├── llms.txt                   ← machine-readable site summary for LLM crawlers (Anthropic, OpenAI, etc.)
│
├── index.html                 ← landing page
├── services.html              ← Practices
├── industries.html            ← Industries
├── standards.html             ← Standards (DIN 276, NRM, MasterFormat, GAEB)
├── maturity.html              ← Maturity-curve marketing page
├── partners.html              ← Affiliate program (Kristijan-style deals)
├── docs.html                  ← "Docs" tile that points at the in-app /docs
├── imprint.html               ← Legal imprint (German Impressum)
├── contact.html               ← Contact info, single page
├── license-request.html       ← 3-tier license-tier picker
├── demo-register.html         ← demo lead form
├── demo-register-api.py       ← Python sidecar that captures form POSTs
│
├── news.html                  ← News index (card grid)
└── news/
    ├── assets/
    │   ├── related-articles.js          ← right-rail widget rendered on every article
    │   └── open-erp-own-your-stack/     ← per-article image assets
    ├── open-erp-own-your-stack.html     ← concept paper
    ├── v5-5-0.html                       ← release announcement (latest)
    ├── v5-3-0.html, v5-2-8.html, ...    ← prior releases
    └── v3-0-0.html                       ← oldest article still indexed

locales/
├── en.json, de.json, fr.json, es.json, it.json, pt.json, nl.json,
├── ru.json, pl.json, cs.json, sv.json, no.json, da.json, fi.json,
├── tr.json, bg.json, zh.json, ja.json, ko.json, ar.json
└── (one JSON per language — keys mirror index.html data-i18n attributes)
```

The sibling `website-marketing/` directory at repo root contains older marketing material (~330 MB of pre-built assets). **Do not edit `website-marketing/`** — it's preserved for archival but not deployed.

---

## News article workflow (most common task)

When platform ships a new release (e.g. `v5.5.0`), the website agent ships a matching news article. Sequence:

1. **Read the changelog entry.** Open root `CHANGELOG.md`, find the `## [5.5.0] - …` section. Distil the 8–12 most user-visible items into a 5–6 minute read.
2. **Copy the closest prior article as a starting template.** `marketing-site/news/v5-3-0.html` is the canonical stable-release shape. `v5-2-8.html` is the polish-wave shape. The HTML/CSS is repeated verbatim across articles — **do not extract to a shared layout file**, the trade-off is paid for in static-hosting simplicity.
3. **Update only these blocks** in the new file:
   - `<title>` and meta description / og:title / og:description / twitter:* tags
   - JSON-LD `headline` + `datePublished` + `mainEntityOfPage`
   - `<section class="article-hero">`: crumbs, pill-row (release date, read time), `<h1>`, `.lede`
   - `.cover-art` version label
   - `<div class="highlights">` — 4–8 `.hi-card` blocks, one per bundle
   - Each `<h2>` section in the narrow body
   - Upgrade codeblock — usually no change, just `pip install --upgrade openconstructionerp`
4. **Add a card to `news.html`** at the top of the card grid. Mirror the structure of the previous top card. Include the date, read-time pill, headline, and excerpt.
5. **Add the article to the related-articles catalog** in `news/assets/related-articles.js`: insert a new object at the top of the `ARTICLES` array with `slug`, `href`, `title`, `date`, `tag`, `tagClass`, and `thumb` (null if no hero image yet).
6. **Commit** as `docs(news): add v5.5.0 marketing article + news.html index card`. Push to `main`. The VPS pulls on a cron (or deploy via Caddyfile mount — see Deploy section).

**Do not regenerate prior articles** when you add a new one. Each article is frozen at the moment it shipped — version-pinned anchors are intentional.

---

## i18n workflow (locales/)

- `en.json` is the **source of truth.** All other locales mirror its key structure.
- Adding a new string: append to `en.json`, then mirror in every other locale. Missing keys fall back to the English value at runtime (graceful), so partial coverage is OK.
- **Do not auto-translate via an LLM without a human pass.** Construction terminology has specific vendor / regulator terms in each region (e.g. DACH `Leistungsverzeichnis`, US `Bill of Quantities`, RU `Локальная смета`) — sloppy MT will be wrong.
- Locale files are flat-ish: nested objects 2–3 levels deep. Don't go deeper.
- The marketing-site locales are **independent** of the platform's `frontend/src/app/locales/*.ts`. Strings duplicate; that's deliberate — keeps the website ship-ready without the platform compiled.

---

## Caddy + deploy

`Caddyfile` is the reverse-proxy config that runs on the VPS at `31.97.123.81` (also serves `chat.datadrivenconstruction.io` and `prozesswerk.31.97.123.81.nip.io`). The site is served as static files from a Caddy `file_server` at `/srv` inside the container.

**Deploy path** (when changing HTML/CSS/locales):
1. Commit + push to `main`.
2. SSH to `root@31.97.123.81`, `cd /srv/openconstructionerp.com && git pull`.
3. No restart required — Caddy serves files directly.

**Deploy path** (when changing `Caddyfile`):
1. Commit + push.
2. SSH, `git pull`, `docker compose restart caddy` (or whatever the running orchestration is — check the live host first).
3. Verify with `curl -I https://openconstructionerp.com/` returning the new headers.

---

## Brand tokens (keep consistent across pages)

```
Accent (primary blue):   #0284c7 (light) / #38bdf8 (dark)
Accent secondary:        #0ea5e9 / #7dd3fc
Accent tertiary:         #2563eb / #60a5fa
Background:              #f7fbff / #0b1220
Ink primary:             #0b1220 / #eff6ff
Ink secondary:           #1e293b / #cfe0f5
Ink tertiary:            #475569 / #94a3b8
Card background:         #ffffff / #111a2c
Line / divider:          rgba(15, 23, 42, 0.05–0.14) / rgba(255, 255, 255, 0.06–0.16)
Code panel background:   #0f172a / #0a0f1c
Code panel foreground:   #e2e8f0
```

Border radii: `6 / 8 / 10 / 12 px` (sm/md/lg/xl). Standard for "Apple-tight" — do not enlarge.

Buttons:
- Primary CTA: `linear-gradient(135deg, var(--accent), var(--accent-3))`, white text, `box-shadow` with inset highlight.
- Ghost: transparent, `border: 1px solid var(--line-2)`, hover flips to accent border.
- GitHub-pill: tight 36×36 icon button on nav strip.

Brand name should appear as **three segments** in nav: `Open` (ink-0) / `Construction` (ink-2) / `ERP` (accent, weight 800).

---

## SEO + analytics

- **Google Analytics with Consent Mode v2** is wired in every page (`G-JYQXK2652T`). Default consent is **denied** — users opt in via the cookie banner.
- Every page has full `<meta name="description">`, OG tags, Twitter cards, and `application/ld+json` Schema.org markup.
- Canonical URLs are set per page (`<link rel="canonical">`).
- `llms.txt` at root is the machine-readable summary for LLM crawlers (Anthropic, OpenAI, Perplexity). Update it when shipping a major feature.

When adding a new page, copy the **complete `<head>` block** from `index.html` and adjust the title / description / canonical / OG fields. Do not skip the JSON-LD — the site has organic search traffic worth defending.

---

## What the website agent should NOT touch

Hard "do not edit" list — those belong to the platform agent:

- `backend/` (Python FastAPI app)
- `frontend/` (React SPA — the in-app marketing surfaces like `/about` Changelog live here)
- `services/` (cad-converter, cv-pipeline, ai-service)
- `packages/` (Pydantic schemas, SDK, UI kit)
- `data/` (seed data, CWICR cost database)
- `deploy/docker/`, `deploy/kubernetes/`, `deploy/terraform/` (platform infra)
- `docs/` (developer docs — different from `docs.html` on the site)
- Root `CHANGELOG.md` (sole source for PyPI long-description)
- Root `README.md` (PyPI long-description, GitHub repo landing)
- `pyproject.toml`, `package.json`, `pnpm-lock.yaml`, `requirements*.txt`
- `.github/workflows/` (CI/CD — platform releases)
- `alembic/` directories (DB migrations)

If a user request mixes marketing + platform changes (e.g. "ship v5.5.1 and write a news article"), the platform agent ships the release first, then the website agent writes the news article in a separate commit. Two PRs is fine; one bundled PR is also fine but the website-only commit must not change platform files.

---

## What the website agent CAN do

- Add / edit any HTML page under `marketing-site/`
- Add / edit any locale JSON under `marketing-site/locales/`
- Add / edit any news article under `marketing-site/news/`
- Add / edit `news/assets/related-articles.js` (the article catalog)
- Update `Caddyfile`
- Update `llms.txt`
- Update brand tokens (rarely)
- Update `demo-register-api.py` (the tiny lead-capture sidecar)
- Add image assets under `news/assets/<slug>/` for hero illustrations

For anything that needs a screenshot of the running platform, the website agent should ask the platform agent to take and commit it under `docs/screenshots/`, then `<img src="/docs/screenshots/...">` from the marketing page.

---

## Local preview

```bash
# Vanilla static server — no build step.
cd marketing-site
python -m http.server 8000
# → http://localhost:8000/index.html
# → http://localhost:8000/news.html
# → http://localhost:8000/news/v5-5-0.html
```

Or VS Code Live Server. Or any static file server. There is **nothing to build**.

---

## Done-criteria checklist for any website change

1. ✅ Renders at `http://localhost:8000/<page>.html` with no console errors.
2. ✅ Dark and light themes both legible (toggle via the moon/sun icon in the nav).
3. ✅ Mobile breakpoint at 540 / 720 / 980 px doesn't regress (test in DevTools device emulator).
4. ✅ Lighthouse / axe-core score on the touched page hasn't dropped below the previous run (perf 85+, a11y 95+).
5. ✅ If a new page: added to the global nav, added to `llms.txt`, has full `<head>` SEO block, has canonical URL.
6. ✅ If a new news article: added card to `news.html`, added entry to `related-articles.js`, copied from a recent template, version-stamped meta tags.
7. ✅ If a locale string was added: present in `en.json` AND mirrored in all other JSONs (or graceful fallback explicitly noted).
8. ✅ No platform files touched (run `git status --short` and verify only `marketing-site/` paths show up).
