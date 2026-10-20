// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Appearance styles: value handling, and the WCAG AA table for every accent
// read straight from index.css, so a palette edit that sinks a pair below
// 4.5:1 goes red here instead of on a customer's screen.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, it, expect } from 'vitest';
import {
  ACCENTS,
  ACCENT_SWATCH,
  APPEARANCE_PRESETS,
  PLATFORM_APPEARANCE,
  matchPreset,
  resolveAppearance,
  sanitizeAppearance,
} from '../appearance';

const CSS = readFileSync(resolve(__dirname, '../../../index.css'), 'utf-8');

function block(selector: string): Record<string, string> {
  const at = CSS.indexOf(`${selector} {`);
  if (at < 0) throw new Error(`no block ${selector}`);
  const body = CSS.slice(at, CSS.indexOf('}', at));
  const out: Record<string, string> = {};
  for (const m of body.matchAll(/--oe-([\w-]+):\s*([^;]+);/g)) out[m[1]!] = m[2]!.trim();
  return out;
}

function rgb(color: string): [number, number, number] {
  const hex = /^#([0-9a-f]{6})$/i.exec(color);
  if (hex) {
    const n = parseInt(hex[1]!, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  throw new Error(`not a hex colour: ${color}`);
}

function lum([r, g, b]: [number, number, number]): number {
  const f = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

function ratio(a: string | [number, number, number], b: string | [number, number, number]): number {
  const la = lum(typeof a === 'string' ? rgb(a) : a);
  const lb = lum(typeof b === 'string' ? rgb(b) : b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** Flatten an `rgba(r, g, b, a)` wash over a surface. */
function over(rgba: string, surface: string): [number, number, number] {
  const m = /rgba\((\d+),\s*(\d+),\s*(\d+),\s*([\d.]+)\)/.exec(rgba);
  if (!m) throw new Error(`not rgba: ${rgba}`);
  const a = Number(m[4]);
  const bg = rgb(surface);
  return [0, 1, 2].map((i) => Math.round(Number(m[i + 1]) * a + bg[i]! * (1 - a))) as [number, number, number];
}

const AA = 4.5;
const WHITE = '#ffffff';
const INK = '#0f1117';
const LIGHT_SURFACES = ['#ffffff', '#f5f5f7', '#eeeef2'];
const DARK_SURFACES = ['#0f1117', '#161822', '#1a1d2b', '#1e2130'];
// Blue is the platform's original palette, kept byte-for-byte as it was.
const ADDED = ACCENTS.filter((a) => a !== 'blue');

describe('accent contrast (WCAG AA)', () => {
  it.each(ADDED)('%s clears AA in light mode', (accent) => {
    const t = block(`html[data-accent='${accent}']`);
    for (const fill of ['blue', 'blue-hover', 'blue-active', 'blue-dark']) {
      expect(ratio(WHITE, t[fill]!), `white on ${fill}`).toBeGreaterThanOrEqual(AA);
    }
    for (const surface of [...LIGHT_SURFACES, t['blue-subtle']!]) {
      expect(ratio(t['blue-text']!, surface), `text on ${surface}`).toBeGreaterThanOrEqual(AA);
      expect(ratio(t.blue!, surface), `base as text on ${surface}`).toBeGreaterThanOrEqual(AA);
    }
  });

  it.each(ADDED)('%s clears AA in dark mode', (accent) => {
    const t = block(`html.dark[data-accent='${accent}']`);
    for (const fill of ['blue', 'blue-hover', 'blue-active']) {
      expect(ratio(INK, t[fill]!), `ink on ${fill}`).toBeGreaterThanOrEqual(AA);
    }
    expect(ratio(WHITE, t['blue-dark']!), 'white on blue-dark').toBeGreaterThanOrEqual(AA);
    for (const surface of DARK_SURFACES) {
      expect(ratio(t['blue-text']!, surface), `text on ${surface}`).toBeGreaterThanOrEqual(AA);
      expect(ratio(t.blue!, surface), `base as text on ${surface}`).toBeGreaterThanOrEqual(AA);
      expect(ratio(t['blue-text']!, over(t['blue-subtle']!, surface)), `text on pill/${surface}`).toBeGreaterThanOrEqual(AA);
    }
  });

  it.each(ADDED)('%s keeps its channel triplet in step with the hex', (accent) => {
    for (const sel of [`html[data-accent='${accent}']`, `html.dark[data-accent='${accent}']`]) {
      const t = block(sel);
      expect(t['blue-ch']).toBe(rgb(t.blue!).join(' '));
    }
  });

  it('preview swatches match the light accent base', () => {
    for (const accent of ADDED) expect(ACCENT_SWATCH[accent]).toBe(block(`html[data-accent='${accent}']`).blue);
    expect(ACCENT_SWATCH.blue).toBe(block(':root').blue);
  });
});

describe('appearance values', () => {
  it('drops unknown axes and values', () => {
    expect(sanitizeAppearance({ accent: 'teal', font: 'comic', density: 'compact', x: 1 })).toEqual({
      accent: 'teal',
      density: 'compact',
    });
    expect(sanitizeAppearance({ accent: 'pink' })).toBeNull();
    expect(sanitizeAppearance('teal')).toBeNull();
  });

  it('layers user over workspace over platform, per axis', () => {
    expect(resolveAppearance(null, null)).toEqual(PLATFORM_APPEARANCE);
    expect(resolveAppearance(null, { accent: 'crimson' })).toEqual({ ...PLATFORM_APPEARANCE, accent: 'crimson' });
    expect(resolveAppearance({ radius: 'sharp' }, { accent: 'crimson', radius: 'round' })).toEqual({
      ...PLATFORM_APPEARANCE,
      accent: 'crimson',
      radius: 'sharp',
    });
  });

  it('names the preset a value matches, or none for a custom mix', () => {
    for (const p of APPEARANCE_PRESETS) expect(matchPreset(p.value)).toBe(p.id);
    expect(matchPreset({ ...PLATFORM_APPEARANCE, accent: 'crimson' })).toBeNull();
  });

  it('presets are distinct', () => {
    const keys = APPEARANCE_PRESETS.map((p) => JSON.stringify(p.value));
    expect(new Set(keys).size).toBe(keys.length);
  });
});
