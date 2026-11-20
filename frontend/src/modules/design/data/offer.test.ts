import { describe, expect, it } from 'vitest';
import { installerUrl, linkExpired, linkFileName, serializeLink, shouldOffer, type LinkFile } from './offer';

const link: LinkFile = {
  schema: 'ddc-link/1', erp_url: 'http://127.0.0.1:8000', project_id: 'p', project_name: 'Wohnhaus',
  code: 'abc', expires_at: '2026-11-12T11:05:00Z', action: 'open', revision_id: null,
};

describe('shouldOffer', () => {
  it('a switched-on module needs no offer anywhere', () => {
    expect(shouldOffer('tour', true, false)).toBe(false);
    expect(shouldOffer('empty', true, false)).toBe(false);
  });

  it('the tour question stays away once dismissed, the empty-state banner does not', () => {
    expect(shouldOffer('tour', false, true)).toBe(false);
    expect(shouldOffer('empty', false, true)).toBe(true);
  });

  it('a fresh install is offered both', () => {
    expect(shouldOffer('tour', false, false)).toBe(true);
    expect(shouldOffer('empty', false, false)).toBe(true);
  });
});

describe('linkFileName', () => {
  it('keeps a plain name and the extension', () => {
    expect(linkFileName('Haus 7')).toBe('Haus-7.ddclink');
  });

  it('folds accents and umlauts, drops path separators and control characters', () => {
    expect(linkFileName('Wohnhaus Beispielstraße / ../x\u0000')).toBe('Wohnhaus-Beispielstrasse-x.ddclink');
    expect(linkFileName('Café Müller')).toBe('Cafe-Muller.ddclink');
  });

  it('a name with nothing usable still yields a file', () => {
    expect(linkFileName('Жилой дом')).toBe('project.ddclink');
    expect(linkFileName('')).toBe('project.ddclink');
  });

  it('is short', () => {
    expect(linkFileName('a'.repeat(300)).length).toBeLessThanOrEqual(48 + '.ddclink'.length);
  });
});

describe('serializeLink', () => {
  it('round-trips and ends with a newline', () => {
    const text = serializeLink(link);
    expect(text.endsWith('\n')).toBe(true);
    expect(JSON.parse(text)).toEqual(link);
  });
});

describe('installerUrl', () => {
  it('accepts an https address only', () => {
    expect(installerUrl({ VITE_DESIGN_EDITOR_URL: 'https://example.org/get' })).toBe('https://example.org/get');
    expect(installerUrl({ VITE_DESIGN_EDITOR_URL: 'http://example.org/get' })).toBeNull();
    expect(installerUrl({ VITE_DESIGN_EDITOR_URL: 'javascript:alert(1)' })).toBeNull();
  });

  it('is absent without configuration', () => {
    expect(installerUrl({})).toBeNull();
    expect(installerUrl({ VITE_DESIGN_EDITOR_URL: '  ' })).toBeNull();
  });
});

describe('linkExpired', () => {
  it('compares with the clock', () => {
    expect(linkExpired(link, Date.parse('2026-11-12T11:04:59Z'))).toBe(false);
    expect(linkExpired(link, Date.parse('2026-11-12T11:05:00Z'))).toBe(true);
  });

  it('an unreadable date counts as expired', () => {
    expect(linkExpired({ ...link, expires_at: 'soon' })).toBe(true);
  });
});
