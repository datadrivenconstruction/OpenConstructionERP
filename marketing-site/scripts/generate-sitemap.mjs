#!/usr/bin/env node
/* ================================================================
 * generate-sitemap.mjs
 *
 * Self-updating sitemap generator for the OpenConstructionERP
 * marketing site. It scans the static web root for every public,
 * indexable HTML page and emits a valid sitemap.xml (sitemaps
 * protocol 0.9) plus keeps robots.txt pointed at it.
 *
 * Design goals:
 *   - Deterministic and idempotent: re-running regenerates the
 *     full sitemap from the current file set, so new pages (a new
 *     /news entry, a new top-level page, a new /xx/ language
 *     snapshot) are picked up automatically on the next run.
 *   - No third-party dependencies. Plain Node + git CLI (optional).
 *   - Works against either the repo source tree or the live VPS
 *     docroot; pass --root to point it at the served directory.
 *
 * Usage:
 *   node generate-sitemap.mjs                 # root = repo marketing-site
 *   node generate-sitemap.mjs --root /path    # explicit web root
 *   node generate-sitemap.mjs --base https://example.com
 *   node generate-sitemap.mjs --dry-run       # print, do not write
 *
 * URL conventions (match what the site already serves via Caddy
 * try_files {path} {path}.html {path}/index.html):
 *   - Top-level pages use clean, extensionless URLs (/download).
 *   - index.html maps to the directory with a trailing slash
 *     (root index -> "/", de/index.html -> "/de/").
 *   - News entries are extensionless under /news/ (/news/v8-3-0).
 *   - The home page carries the full hreflang alternate cluster
 *     for every localized /xx/ home snapshot that exists on disk.
 * ================================================================ */

import { execFileSync } from 'node:child_process';
import { readdirSync, readFileSync, statSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url));

// ---- config ----------------------------------------------------

const DEFAULT_BASE = 'https://openconstructionerp.com';

// Languages that ship as static /xx/index.html home snapshots.
// Anything outside this list found as a top-level two-letter dir is
// still scanned, but only these get an hreflang code on the home
// alternate cluster. Order here drives alternate ordering.
const LANG_CODES = [
  'de', 'fr', 'es', 'it', 'pt', 'nl', 'pl', 'cs', 'ru', 'bg',
  'tr', 'sv', 'no', 'fi', 'da', 'ar', 'zh', 'ja', 'ko',
];

// Directories never scanned (relative to web root, matched by name
// at any depth). Assets, runtime i18n, locale JSON, backups.
const DENY_DIRS = new Set([
  'partials', 'includes', 'templates', 'locales', 'i18n',
  'assets', 'node_modules', 'scripts',
  // /pro is a self-contained set of white-label / design-variant
  // landing sites (each with its own robots.txt + sitemap.xml). It is
  // a separate property, not part of the openconstructionerp.com
  // marketing pages, so it stays out of this sitemap.
  'pro',
]);

// Exact top-level filenames that are not public, standalone pages:
// dev/lab surfaces, internal helpers, and redirect stubs.
const DENY_FILES = new Set([
  '404.html',
  'terms.html',                     // noindex redirect stub -> terms-of-service
  'button-lab.html',                // internal component lab
  'hero-effects.html',              // internal visual lab
  'viz-lab.html',                   // internal visual lab
  'download-module-variants.html',  // internal variant helper, not linked publicly
]);

// Caddy serves a few pages at a canonical path that differs from the
// raw filename (see the marketing Caddyfile `handle` blocks). Map the
// file's natural URL to the canonical one so the sitemap lists the URL
// users and the rest of the site actually link to.
//   demo-register.html is served at /demo (handle /demo { rewrite ... }).
const URL_REWRITES = new Map([
  ['/demo-register', '/demo'],
]);

// changefreq / priority heuristics keyed by URL shape.
function seoHints(pathname) {
  if (pathname === '/') return { changefreq: 'daily', priority: '1.0' };
  if (/^\/[a-z]{2}\/$/.test(pathname)) return { changefreq: 'weekly', priority: '0.8' };
  if (pathname === '/news') return { changefreq: 'daily', priority: '0.8' };
  if (pathname.startsWith('/news/')) return { changefreq: 'monthly', priority: '0.6' };
  if (/^\/(download|partners|services|industries|standards|docs|contact|demo|license-request|maturity)$/.test(pathname)) {
    return { changefreq: 'weekly', priority: '0.8' };
  }
  if (/^\/(privacy-policy|terms-of-service|cookie-policy|imprint)$/.test(pathname)) {
    return { changefreq: 'yearly', priority: '0.3' };
  }
  return { changefreq: 'monthly', priority: '0.5' };
}

// ---- args ------------------------------------------------------

function parseArgs(argv) {
  const out = { root: null, base: DEFAULT_BASE, dryRun: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--root') out.root = argv[++i];
    else if (a === '--base') out.base = argv[++i];
    else if (a === '--dry-run') out.dryRun = true;
  }
  // Default root: the marketing-site dir, i.e. the parent of /scripts.
  if (!out.root) out.root = resolve(SCRIPT_DIR, '..');
  out.root = resolve(out.root);
  out.base = out.base.replace(/\/+$/, '');
  return out;
}

// ---- helpers ---------------------------------------------------

function walkHtml(rootDir) {
  const files = [];
  (function walk(dir) {
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const ent of entries) {
      const name = ent.name;
      if (name.startsWith('.') || name.startsWith('_')) continue;
      const full = join(dir, name);
      if (ent.isDirectory()) {
        if (DENY_DIRS.has(name)) continue;
        walk(full);
      } else if (ent.isFile() && name.toLowerCase().endsWith('.html')) {
        // Skip backups and editor leftovers like index.html.bak-*.
        if (/\.bak\b/i.test(name) || /\.(orig|tmp|old)$/i.test(name)) continue;
        if (/\.html\.[^/]+$/i.test(name)) continue; // e.g. index.html.bak-trust
        files.push(full);
      }
    }
  })(rootDir);
  return files.sort();
}

// A page is non-indexable if it declares robots noindex or is a
// meta-refresh / instant client redirect. Reading only the <head>
// keeps this fast even for the 1 MB index.html. This is what makes
// the generator self-maintaining: a future draft marked noindex is
// excluded automatically, no name-list edit required.
function isNonIndexable(absPath) {
  let head;
  try {
    const buf = readFileSync(absPath, 'utf8');
    const m = buf.search(/<\/head>/i);
    head = m === -1 ? buf.slice(0, 4096) : buf.slice(0, m);
  } catch {
    return false;
  }
  head = head.toLowerCase();
  if (/<meta[^>]+name=["']robots["'][^>]*content=["'][^"']*noindex/i.test(head)) return true;
  if (/<meta[^>]+http-equiv=["']refresh["'][^>]*content=["']\s*0\s*;/i.test(head)) return true;
  return false;
}

function gitLastmod(absPath, rootDir) {
  try {
    const out = execFileSync(
      'git',
      ['log', '-1', '--format=%cI', '--', absPath],
      { cwd: rootDir, stdio: ['ignore', 'pipe', 'ignore'], encoding: 'utf8' },
    ).trim();
    if (out) return out.slice(0, 10); // YYYY-MM-DD
  } catch {
    // not a git repo, or file untracked -> fall through to mtime
  }
  return null;
}

function mtimeDate(absPath) {
  try {
    return statSync(absPath).mtime.toISOString().slice(0, 10);
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
}

// Map an absolute file path to its clean public URL path.
function toUrlPath(absPath, rootDir) {
  let rel = relative(rootDir, absPath).split(sep).join('/');
  if (rel.toLowerCase().endsWith('/index.html')) {
    rel = rel.slice(0, -'index.html'.length); // keep trailing slash
  } else if (rel.toLowerCase() === 'index.html') {
    rel = '';
  } else if (rel.toLowerCase().endsWith('.html')) {
    rel = rel.slice(0, -'.html'.length); // strip extension
  }
  const urlPath = '/' + rel;
  return URL_REWRITES.get(urlPath) || urlPath;
}

function xmlEscape(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&apos;');
}

// ---- build -----------------------------------------------------

function build({ root, base }) {
  const htmlFiles = walkHtml(root);
  const pages = [];

  for (const abs of htmlFiles) {
    const relName = relative(root, abs).split(sep).join('/');
    const topName = relName.includes('/') ? null : relName;

    if (topName && DENY_FILES.has(topName)) continue;
    if (isNonIndexable(abs)) continue;

    const urlPath = toUrlPath(abs, root);
    const lastmod = gitLastmod(abs, root) || mtimeDate(abs);
    pages.push({ abs, urlPath, lastmod });
  }

  // Which localized home snapshots actually exist on disk, in the
  // configured language order. Drives the hreflang cluster.
  const presentLangs = LANG_CODES.filter((c) =>
    pages.some((p) => p.urlPath === `/${c}/`),
  );

  // The shared alternate cluster attached to the home page and to
  // every localized home (Google wants alternates to be reciprocal).
  const homeAlternates = [
    { hreflang: 'x-default', href: `${base}/` },
    { hreflang: 'en', href: `${base}/` },
    ...presentLangs.map((c) => ({ hreflang: c, href: `${base}/${c}/` })),
  ];

  const isHome = (p) => p.urlPath === '/' || /^\/[a-z]{2}\/$/.test(p.urlPath);

  // Deterministic ordering: home first, then language homes in
  // configured order, then non-news top-level pages alphabetically,
  // then news entries newest-first (semantic version desc when we
  // can parse it, else lastmod desc, else path).
  const rank = (p) => {
    if (p.urlPath === '/') return 0;
    if (/^\/[a-z]{2}\/$/.test(p.urlPath)) return 1;
    if (p.urlPath.startsWith('/news/')) return 3;
    return 2;
  };
  const langOrder = (p) => {
    const m = p.urlPath.match(/^\/([a-z]{2})\/$/);
    const idx = m ? presentLangs.indexOf(m[1]) : -1;
    return idx === -1 ? 999 : idx;
  };
  const newsKey = (p) => {
    const m = p.urlPath.match(/\/news\/v(\d+)-(\d+)-(\d+)$/);
    if (m) return [1, Number(m[1]), Number(m[2]), Number(m[3])];
    return [0, 0, 0, 0];
  };

  pages.sort((a, b) => {
    const ra = rank(a), rb = rank(b);
    if (ra !== rb) return ra - rb;
    if (ra === 1) return langOrder(a) - langOrder(b);
    if (ra === 3) {
      const ka = newsKey(a), kb = newsKey(b);
      for (let i = 0; i < ka.length; i++) {
        if (ka[i] !== kb[i]) return kb[i] - ka[i]; // newest first
      }
      if (a.lastmod !== b.lastmod) return a.lastmod < b.lastmod ? 1 : -1;
      return a.urlPath < b.urlPath ? 1 : -1;
    }
    return a.urlPath < b.urlPath ? -1 : 1;
  });

  // ---- emit XML ----
  const lines = [];
  lines.push('<?xml version="1.0" encoding="UTF-8"?>');
  lines.push('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"');
  lines.push('        xmlns:xhtml="http://www.w3.org/1999/xhtml">');

  for (const p of pages) {
    const loc = `${base}${p.urlPath}`;
    const { changefreq, priority } = seoHints(p.urlPath);
    lines.push('  <url>');
    lines.push(`    <loc>${xmlEscape(loc)}</loc>`);
    lines.push(`    <lastmod>${p.lastmod}</lastmod>`);
    if (isHome(p)) {
      for (const alt of homeAlternates) {
        lines.push(
          `    <xhtml:link rel="alternate" hreflang="${alt.hreflang}" href="${xmlEscape(alt.href)}"/>`,
        );
      }
    }
    lines.push(`    <changefreq>${changefreq}</changefreq>`);
    lines.push(`    <priority>${priority}</priority>`);
    lines.push('  </url>');
  }
  lines.push('</urlset>');
  lines.push('');

  return { xml: lines.join('\n'), count: pages.length, pages, presentLangs };
}

// Ensure robots.txt exists at the web root and points at the sitemap.
// Never loosens or tightens existing Allow/Disallow rules.
function ensureRobots(root, base) {
  const robotsPath = join(root, 'robots.txt');
  const sitemapLine = `Sitemap: ${base}/sitemap.xml`;
  if (existsSync(robotsPath)) {
    const cur = readFileSync(robotsPath, 'utf8');
    // House rule: no long dashes anywhere. Normalize em/en dashes in
    // any existing comment text to a plain hyphen. Allow/Disallow rules
    // are left exactly as found.
    let next = cur.replace(/[‒–—―]/g, '-');
    if (/^\s*Sitemap:\s*\S+/im.test(next)) {
      // Normalize an existing Sitemap line to the canonical URL.
      next = next.replace(/^\s*Sitemap:\s*\S+.*$/im, sitemapLine);
    } else {
      const sep = next.endsWith('\n') ? '' : '\n';
      next = `${next}${sep}\n${sitemapLine}\n`;
    }
    if (next === cur) return { path: robotsPath, action: 'unchanged' };
    writeFileSync(robotsPath, next);
    return { path: robotsPath, action: 'updated' };
  }
  const body = [
    '# https://openconstructionerp.com/robots.txt',
    '#',
    '# OpenConstructionERP is open-source, built on open construction data and',
    '# open systems. Search engines and AI / LLM crawlers are explicitly welcome',
    '# to crawl, index and cite this site - there is no AI opt-out here by design.',
    '',
    'User-agent: *',
    'Allow: /',
    'Disallow: /api/',
    'Disallow: /tools/',
    '',
    sitemapLine,
    '',
  ].join('\n');
  writeFileSync(robotsPath, body);
  return { path: robotsPath, action: 'created' };
}

// ---- main ------------------------------------------------------

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!existsSync(args.root)) {
    console.error(`generate-sitemap: web root not found: ${args.root}`);
    process.exit(1);
  }

  const { xml, count, pages, presentLangs } = build(args);
  const outPath = join(args.root, 'sitemap.xml');

  if (args.dryRun) {
    console.log(xml);
    console.error(`\n[dry-run] ${count} urls (root: ${args.root})`);
    return;
  }

  writeFileSync(outPath, xml);
  const robots = ensureRobots(args.root, args.base);

  const news = pages.filter((p) => p.urlPath.startsWith('/news/')).length;
  console.log(`sitemap: wrote ${count} urls to ${outPath}`);
  console.log(`  language home snapshots: ${presentLangs.length} (${presentLangs.join(', ') || 'none'})`);
  console.log(`  news entries: ${news}`);
  console.log(`  robots.txt: ${robots.action} (${robots.path})`);
}

main();
