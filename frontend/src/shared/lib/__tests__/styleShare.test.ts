// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { APPEARANCE_PRESETS, PLATFORM_APPEARANCE } from '../appearance';
import { STYLE_FORMAT, decodeStyleCode, encodeStyleCode, parseStyle, styleShareUrl, styleToJson } from '../styleShare';

const site = APPEARANCE_PRESETS.find((p) => p.id === 'site')!;

describe('style export and import', () => {
  it('round-trips through the JSON file', () => {
    const json = styleToJson({ appearance: site.value, theme: 'light' });
    expect(parseStyle(json)).toEqual({ ok: true, style: { appearance: site.value, theme: 'light' } });
  });

  it('round-trips through the share code, schedule included', () => {
    const style = {
      appearance: PLATFORM_APPEARANCE,
      theme: 'schedule' as const,
      schedule: { darkFrom: 20, darkTo: 6 },
    };
    const code = encodeStyleCode(style);
    expect(code).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(decodeStyleCode(code)).toEqual({ ok: true, style });
    expect(new URL(styleShareUrl(style, 'https://x.test')).searchParams.get('appearance')).toBe(code);
  });

  it('drops unknown axes and bad values, fills the rest from the platform', () => {
    const r = parseStyle(
      JSON.stringify({ format: STYLE_FORMAT, version: 1, appearance: { accent: 'teal', font: '<b>', evil: 1 } }),
    );
    expect(r).toEqual({ ok: true, style: { appearance: { ...PLATFORM_APPEARANCE, accent: 'teal' } } });
  });

  it('refuses what is not a style', () => {
    expect(parseStyle('not json')).toEqual({ ok: false, error: 'not_json' });
    expect(parseStyle('{"accent":"teal"}')).toEqual({ ok: false, error: 'wrong_format' });
    expect(parseStyle(JSON.stringify({ format: STYLE_FORMAT, version: 2, appearance: {} }))).toEqual({
      ok: false,
      error: 'wrong_version',
    });
    expect(parseStyle(JSON.stringify({ format: STYLE_FORMAT, version: 1, appearance: { accent: 'pink' } }))).toEqual({
      ok: false,
      error: 'empty',
    });
    expect(parseStyle('x'.repeat(5000))).toEqual({ ok: false, error: 'too_large' });
    expect(decodeStyleCode('%%%')).toEqual({ ok: false, error: 'not_json' });
  });
});
