/* ============================================================
 * OpenConstructionERP — "More from the blog" related-articles widget.
 * Drop one <script src="/news/assets/related-articles.js" defer></script>
 * into any /news/*.html page; the widget renders itself, excludes
 * the current article, and works against the inline article catalog
 * below. No deps, no tracking, no external requests.
 * ============================================================ */
(function () {
  'use strict';

  // ---- Article catalog (mirrors marketing-site/news.html) -------
  // slug is the file basename without .html; href is the URL; thumb
  // can be an /screenshots/*.png path, a /news/assets/* path, or null
  // for "draw the on-brand SVG placeholder".
  var ARTICLES = [
    {
      slug: 'open-erp-own-your-stack',
      href: '/news/open-erp-own-your-stack.html',
      title: 'An open construction ERP for teams who want to own their stack.',
      date: '2026-05-25',
      tag: 'Concept paper',
      tagClass: 'release',
      thumb: '/news/assets/open-erp-own-your-stack/images/hero-overview.jpg'
    },
    {
      slug: 'v5-3-0',
      href: '/news/v5-3-0.html',
      title: 'v5.3.0 — Geo Hub round 2 + Brazil Tier-1 + login dark-mode + WCAG-AA.',
      date: '2026-05-27',
      tag: 'Release',
      tagClass: 'release',
      thumb: null
    },
    {
      slug: 'v5-2-8',
      href: '/news/v5-2-8.html',
      title: 'v5.2.8 — /geo tabs reliability + /markups deep-link + /resources inline edit.',
      date: '2026-05-27',
      tag: 'Release',
      tagClass: 'release',
      thumb: null
    },
    {
      slug: 'v5-2-7',
      href: '/news/v5-2-7.html',
      title: 'v5.2.7 — Project-detail widget grid + one-click in-app upgrade.',
      date: '2026-05-27',
      tag: 'Release',
      tagClass: 'release',
      thumb: null
    },
    {
      slug: 'v5-2-6',
      href: '/news/v5-2-6.html',
      title: 'v5.2.6 — Demo login JustWorks. WCAG-AA contrast. Reporting renderer.',
      date: '2026-05-27',
      tag: 'Release',
      tagClass: 'release',
      thumb: null
    },
    {
      slug: 'v5-2-5',
      href: '/news/v5-2-5.html',
      title: 'v5.2.5 — Install-crash fix. Fresh pip install works again.',
      date: '2026-05-27',
      tag: 'Hotfix',
      tagClass: 'hotfix',
      thumb: null
    },
    {
      slug: 'v5-2-3',
      href: '/news/v5-2-3.html',
      title: 'v5.2.3 — Vector-backend gate. Semantic search on by default.',
      date: '2026-05-27',
      tag: 'Hotfix',
      tagClass: 'hotfix',
      thumb: null
    },
    {
      slug: 'v5-2-2',
      href: '/news/v5-2-2.html',
      title: 'v5.2.2 — /dashboard route + W10/W13/SAF-A3 + a11y bundle.',
      date: '2026-05-27',
      tag: 'Release',
      tagClass: 'release',
      thumb: null
    },
    {
      slug: 'v5-2-0',
      href: '/news/v5-2-0.html',
      title: 'v5.2.0 — International BOQ. GAEB · BC3 · NRM · MasterFormat under one roof.',
      date: '2026-05-26',
      tag: 'Release',
      tagClass: 'release',
      thumb: null
    },
    {
      slug: 'v5-1-0',
      href: '/news/v5-1-0.html',
      title: 'v5.1.0 — Wave 1 polish. TypeScript strict everywhere, dispatcher hardening.',
      date: '2026-05-26',
      tag: 'Release',
      tagClass: 'release',
      thumb: null
    },
    {
      slug: 'v5-0-0',
      href: '/news/v5-0-0.html',
      title: 'v5.0.0 — Deep-Coordination foundation. Notifications · file versioning · audit.',
      date: '2026-05-26',
      tag: 'Release',
      tagClass: 'release',
      thumb: null
    },
    {
      slug: 'v4-0-0',
      href: '/news/v4-0-0.html',
      title: 'v4.0.0 — Stable Major. 103 modules, public API, multi-tenant security pass.',
      date: '2026-05-20',
      tag: 'Release',
      tagClass: 'release',
      thumb: '/screenshots/02-dashboard.png'
    },
    {
      slug: 'v3-11-0',
      href: '/news/v3-11-0.html',
      title: 'v3.11.0 — Validation@Import. GAEB X84 writer. RVT diagnostics.',
      date: '2026-05-20',
      tag: 'v3',
      tagClass: 'v3',
      thumb: '/screenshots/07-ai-estimate.png'
    },
    {
      slug: 'v3-6-0',
      href: '/news/v3-6-0.html',
      title: 'v3.6.0 / v3.6.1 — Multi-level BOQ hierarchy. Recursive parent_id walk.',
      date: '2026-05-18',
      tag: 'v3',
      tagClass: 'v3',
      thumb: '/screenshots/04-boq-list.png'
    },
    {
      slug: 'v3-0-0',
      href: '/news/v3-0-0.html',
      title: 'v3.0.0 — First stable v3 major. 18 modules, FSM engine, ISO 16739-1 IFC.',
      date: '2026-05-13',
      tag: 'v3',
      tagClass: 'v3',
      thumb: '/screenshots/hero-overview.jpg'
    }
  ];

  // ---- Helpers --------------------------------------------------
  function currentSlug() {
    try {
      var path = window.location.pathname || '';
      // /news/v5-3-0.html  -> v5-3-0
      var m = path.match(/\/news\/([^/]+?)\.html?$/i);
      return m ? m[1].toLowerCase() : '';
    } catch (e) {
      return '';
    }
  }

  function truncate(s, n) {
    if (!s) return '';
    if (s.length <= n) return s;
    // Trim back to last space so we don't cut a word in half.
    var cut = s.slice(0, n);
    var lastSpace = cut.lastIndexOf(' ');
    if (lastSpace > n * 0.6) cut = cut.slice(0, lastSpace);
    return cut.replace(/[\s\.,;:!\?\-]+$/, '') + '…';
  }

  function escapeHtml(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function pickRelated(slug, limit) {
    var filtered = ARTICLES.filter(function (a) { return a.slug !== slug; });
    filtered.sort(function (a, b) { return a.date < b.date ? 1 : (a.date > b.date ? -1 : 0); });
    return filtered.slice(0, limit);
  }

  // ---- Inline CSS — uses the page's own theme tokens ------------
  var CSS = [
    '.oce-more-rail{',
    '  margin:clamp(48px,7vw,80px) auto 0;',
    '  padding:0 clamp(20px,4vw,48px);',
    '  max-width:1180px;',
    '  font-family:"Inter",system-ui,-apple-system,Segoe UI,Roboto,sans-serif;',
    '}',
    '.oce-more-rail__head{',
    '  display:flex;align-items:baseline;justify-content:space-between;',
    '  gap:16px;flex-wrap:wrap;',
    '  padding-bottom:18px;margin-bottom:22px;',
    '  border-bottom:1px solid var(--line-1, rgba(15,23,42,0.09));',
    '}',
    '.oce-more-rail__title{',
    '  font-family:"Inter Tight",sans-serif;font-weight:700;',
    '  font-size:clamp(20px,2.2vw,26px);letter-spacing:-0.015em;',
    '  margin:0;color:var(--ink-0, #0b1220);',
    '}',
    '.oce-more-rail__title .oce-accent{color:var(--accent,#0284c7);}',
    '.oce-more-rail__all{',
    '  font-family:"Inter Tight",sans-serif;font-weight:600;font-size:14px;',
    '  color:var(--accent,#0284c7);text-decoration:none;',
    '  display:inline-flex;align-items:center;gap:6px;',
    '}',
    '.oce-more-rail__all:hover{color:var(--accent-2,var(--accent,#0284c7));}',
    '.oce-more-rail__all .oce-arrow{transition:transform .15s ease;}',
    '.oce-more-rail__all:hover .oce-arrow{transform:translateX(3px);}',
    '.oce-more-rail__grid{',
    '  display:grid;gap:clamp(14px,1.6vw,22px);',
    '  grid-template-columns:repeat(auto-fill,minmax(220px,1fr));',
    '}',
    '@media (max-width:640px){',
    '  .oce-more-rail__grid{grid-template-columns:1fr;}',
    '}',
    '.oce-mini-card{',
    '  position:relative;background:var(--card,#ffffff);',
    '  border:1px solid var(--line-1, rgba(15,23,42,0.09));',
    '  border-radius:14px;overflow:hidden;',
    '  display:flex;flex-direction:column;',
    '  transition:transform .22s cubic-bezier(.22,.61,.36,1),',
    '              border-color .2s ease,box-shadow .25s ease;',
    '  text-decoration:none;color:inherit;',
    '}',
    '.oce-mini-card:hover{',
    '  transform:translateY(-2px);',
    '  border-color:color-mix(in oklab, var(--accent,#0284c7) 45%, var(--line-1,rgba(15,23,42,0.09)));',
    '  box-shadow:0 14px 28px -16px rgba(2,90,160,0.18),0 2px 6px -2px rgba(15,23,42,0.06);',
    '  color:inherit;',
    '}',
    '.oce-mini-card__media{',
    '  position:relative;width:100%;aspect-ratio:16/9;',
    '  background:linear-gradient(135deg,var(--bg-1,#edf5ff),var(--bg-2,#e7f2fd));',
    '  overflow:hidden;',
    '}',
    '.oce-mini-card__media img{',
    '  width:100%;height:100%;object-fit:cover;display:block;',
    '  transition:transform .5s cubic-bezier(.22,.61,.36,1);',
    '}',
    '.oce-mini-card:hover .oce-mini-card__media img{transform:scale(1.04);}',
    '.oce-mini-card__media--ph{',
    '  display:grid;place-items:center;',
    '  background:radial-gradient(circle at 70% 30%, color-mix(in oklab, var(--accent,#0284c7) 18%, transparent), transparent 60%),',
    '              linear-gradient(135deg,var(--bg-1,#edf5ff),var(--bg-2,#e7f2fd));',
    '}',
    '.oce-mini-card__media--ph svg{',
    '  width:48px;height:48px;opacity:.7;',
    '  color:color-mix(in oklab, var(--accent,#0284c7) 60%, var(--ink-3,#94a3b8));',
    '}',
    '.oce-mini-card__body{',
    '  padding:14px 16px 16px;',
    '  display:flex;flex-direction:column;gap:8px;flex:1;',
    '}',
    '.oce-mini-card__meta{',
    '  display:flex;align-items:center;gap:8px;flex-wrap:wrap;',
    '  font-size:11.5px;color:var(--ink-2,#475569);',
    '}',
    '.oce-chip{',
    '  display:inline-flex;align-items:center;padding:2px 8px;border-radius:999px;',
    '  font-family:"Inter Tight",sans-serif;font-size:10.5px;font-weight:600;',
    '  letter-spacing:0.03em;text-transform:uppercase;',
    '}',
    '.oce-chip--release{',
    '  background:color-mix(in oklab,var(--accent,#0284c7) 10%,transparent);',
    '  color:var(--accent,#0284c7);',
    '  border:1px solid color-mix(in oklab,var(--accent,#0284c7) 24%,transparent);',
    '}',
    '.oce-chip--hotfix{',
    '  background:color-mix(in oklab,#f59e0b 14%,transparent);',
    '  color:#b45309;',
    '  border:1px solid color-mix(in oklab,#f59e0b 30%,transparent);',
    '}',
    '[data-theme="dark"] .oce-chip--hotfix{color:#fbbf24;border-color:color-mix(in oklab,#f59e0b 36%,transparent);}',
    '.oce-chip--v3{',
    '  background:color-mix(in oklab,var(--accent-4,#6366f1) 12%,transparent);',
    '  color:var(--accent-4,#6366f1);',
    '  border:1px solid color-mix(in oklab,var(--accent-4,#6366f1) 28%,transparent);',
    '}',
    '.oce-mini-card__date{',
    '  font-family:"JetBrains Mono",monospace;font-size:11px;',
    '  color:var(--ink-3,#94a3b8);letter-spacing:0.01em;',
    '}',
    '.oce-mini-card__title{',
    '  font-family:"Inter Tight",sans-serif;font-weight:600;',
    '  font-size:14.5px;line-height:1.32;letter-spacing:-0.01em;',
    '  margin:2px 0 0;color:var(--ink-0,#0b1220);',
    '  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;',
    '  overflow:hidden;',
    '}',
    '.oce-mini-card:hover .oce-mini-card__title{color:var(--accent,#0284c7);}',
    /* ----- Right-rail behaviour on very wide screens ----- */
    /* Article body uses max-width:720px centred inside a 1180px wrap. */
    /* From 1400px+ there is ~310px of margin on each side; turn the   */
    /* widget into a 2-up sticky rail anchored to the right margin.    */
    '@media (min-width:1400px){',
    '  .oce-more-rail{',
    '    max-width:none;',
    '    padding:0;',
    '    margin:0;',
    '    position:absolute;',
    '    top:var(--oce-rail-top,640px);',
    '    right:max(24px,calc(50% - 600px));',
    '    width:300px;',
    '    pointer-events:none;',
    '  }',
    '  .oce-more-rail__inner{',
    '    pointer-events:auto;',
    '    position:sticky;top:96px;',
    '  }',
    '  .oce-more-rail__head{',
    '    padding-bottom:14px;margin-bottom:16px;',
    '  }',
    '  .oce-more-rail__title{font-size:16px;}',
    '  .oce-more-rail__all{font-size:13px;}',
    '  .oce-more-rail__grid{grid-template-columns:1fr;gap:14px;}',
    '  .oce-mini-card__media{aspect-ratio:16/9;}',
    '  .oce-mini-card__title{font-size:13.5px;-webkit-line-clamp:3;}',
    '  /* Below-the-fold band on these screens stays as fallback only */',
    '  .oce-more-rail--inline{display:none;}',
    '}',
    '@media (max-width:1399px){',
    '  .oce-more-rail--rail{display:none;}',
    '}'
  ].join('\n');

  // ---- Render ---------------------------------------------------
  function cardHTML(a) {
    var title = escapeHtml(truncate(a.title, 70));
    var date = escapeHtml(a.date);
    var href = escapeHtml(a.href);
    var tag = escapeHtml(a.tag);
    var chipCls = 'oce-chip oce-chip--' + escapeHtml(a.tagClass || 'release');
    var media;
    if (a.thumb) {
      media = '<div class="oce-mini-card__media">' +
              '<img src="' + escapeHtml(a.thumb) + '" alt="" loading="lazy" decoding="async" />' +
              '</div>';
    } else {
      // On-brand SVG placeholder — same shield/check used on news.html
      media = '<div class="oce-mini-card__media oce-mini-card__media--ph" aria-hidden="true">' +
              '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' +
              '<path d="M12 2L3 7v6c0 5 4 9 9 11 5-2 9-6 9-11V7l-9-5z"/><path d="M9 12l2 2 4-4"/>' +
              '</svg></div>';
    }
    return (
      '<a class="oce-mini-card" href="' + href + '" aria-label="Read: ' + title + '">' +
        media +
        '<div class="oce-mini-card__body">' +
          '<div class="oce-mini-card__meta">' +
            '<span class="' + chipCls + '">' + tag + '</span>' +
            '<span class="oce-mini-card__date">' + date + '</span>' +
          '</div>' +
          '<h3 class="oce-mini-card__title">' + title + '</h3>' +
        '</div>' +
      '</a>'
    );
  }

  function buildWidget(variant, items) {
    var grid = items.map(cardHTML).join('');
    var headerArrow = '<svg class="oce-arrow" viewBox="0 0 24 24" width="13" height="13" ' +
      'fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" ' +
      'stroke-linejoin="round" aria-hidden="true"><line x1="5" y1="12" x2="19" y2="12"/>' +
      '<polyline points="12 5 19 12 12 19"/></svg>';
    return (
      '<aside class="oce-more-rail oce-more-rail--' + variant + '" aria-label="More from the blog">' +
        '<div class="oce-more-rail__inner">' +
          '<div class="oce-more-rail__head">' +
            '<h2 class="oce-more-rail__title">More from the <span class="oce-accent">OpenConstructionERP</span> blog</h2>' +
            '<a class="oce-more-rail__all" href="/news.html">All news ' + headerArrow + '</a>' +
          '</div>' +
          '<div class="oce-more-rail__grid">' + grid + '</div>' +
        '</div>' +
      '</aside>'
    );
  }

  function injectStyles() {
    if (document.getElementById('oce-more-rail-styles')) return;
    var style = document.createElement('style');
    style.id = 'oce-more-rail-styles';
    style.appendChild(document.createTextNode(CSS));
    document.head.appendChild(style);
  }

  function injectWidget() {
    var slug = currentSlug();
    if (!slug) return;
    // Only render on /news/<slug>.html pages, not /news.html itself.
    if (slug === 'news' || slug === 'index') return;

    var relatedInline = pickRelated(slug, 6);
    var relatedRail = pickRelated(slug, 4);
    if (!relatedInline.length) return;

    injectStyles();

    // Below-article inline band — visible on all screens up to 1399px,
    // hidden on >=1400px where the right rail takes over.
    var inlineHTML = buildWidget('inline', relatedInline);
    var railHTML = buildWidget('rail', relatedRail);

    // Find the best insertion point. Prefer just before <footer>. Fall
    // back to end of <article> or just before </body>.
    var footer = document.querySelector('footer.pagefoot, .footer-band');
    var inlineNode = document.createElement('div');
    inlineNode.innerHTML = inlineHTML;
    inlineNode = inlineNode.firstChild;

    if (footer && footer.parentNode) {
      footer.parentNode.insertBefore(inlineNode, footer);
    } else {
      // Last-resort: append to body
      document.body.appendChild(inlineNode);
    }

    // Right-rail variant (only visible >=1400px). Append to <body> so it
    // can float independently of the article column.
    var railNode = document.createElement('div');
    railNode.innerHTML = railHTML;
    railNode = railNode.firstChild;
    document.body.appendChild(railNode);

    // Compute a sensible top offset so the rail begins around where the
    // article body starts (after hero/cover).
    try {
      var anchor = document.querySelector('article.article, .body, .content') ||
                   document.querySelector('.article-hero');
      if (anchor) {
        var rect = anchor.getBoundingClientRect();
        var top = Math.max(540, rect.top + window.scrollY);
        railNode.style.setProperty('--oce-rail-top', top + 'px');
      }
    } catch (e) { /* non-fatal */ }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectWidget);
  } else {
    injectWidget();
  }
})();
