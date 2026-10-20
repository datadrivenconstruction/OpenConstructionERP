// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Menu look: values, presets, and the WCAG AA table for every icon colour mode,
// read from index.css, so a palette edit that sinks an icon below 4.5:1 on the
// sidebar goes red here.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  MENU_AXES,
  MENU_AXIS_VALUES,
  MENU_PRESETS,
  MENU_PRESET_IDS,
  MENU_STROKE_WIDTH,
  PLATFORM_MENU,
  SECTION_TONES,
  matchMenuPreset,
  resolveMenu,
  sanitizeIconOverrides,
  sanitizeMenu,
} from '../menuAppearance';

const CSS = readFileSync(resolve(__dirname, '../../../index.css'), 'utf-8');
const MENU_CSS = CSS.slice(CSS.indexOf('/* ── Menu look'));

function vars(selector: string): Record<string, string> {
  const at = MENU_CSS.indexOf(`${selector} {`);
  if (at < 0) throw new Error(`no block ${selector}`);
  const body = MENU_CSS.slice(at, MENU_CSS.indexOf('}', at));
  const out: Record<string, string> = {};
  for (const m of body.matchAll(/--oe-([\w-]+):\s*([^;]+);/g)) out[m[1]!] = m[2]!.trim();
  return out;
}

type RGB = [number, number, number];

function rgb(hex: string): RGB {
  const n = parseInt(/^#([0-9a-f]{6})$/i.exec(hex)![1]!, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function lum([r, g, b]: RGB): number {
  const f = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

function ratio(a: RGB, b: RGB): number {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** `color` at `alpha` over `surface`, as the browser flattens it. */
function mix(color: RGB, alpha: number, surface: RGB): RGB {
  return [0, 1, 2].map((i) => Math.round(color[i]! * alpha + surface[i]! * (1 - alpha))) as RGB;
}

const AA = 4.5;
// Sidebar surface, row hover (surface-secondary) and the active row tint
// (accent blue at 14% light / 25% dark, see SidebarItem).
const LIGHT = { surfaces: ['#ffffff', '#f5f5f7'], accent: '#0071e3', activeAlpha: 0.14 };
const DARK = { surfaces: ['#0f1117', '#161822'], accent: '#3b82f6', activeAlpha: 0.25 };
// The icon tile washes the icon colour at 12% (index.css, container tile/circle).
const TILE_ALPHA = 0.12;

describe('menu look values', () => {
  it('drops unknown axes and values', () => {
    expect(sanitizeMenu({ view: 'rail', stroke: 'heavy', extra: 'x' })).toEqual({ view: 'rail' });
    expect(sanitizeMenu({ view: 'sideways' })).toBeNull();
    expect(sanitizeMenu('rail')).toBeNull();
  });

  it('layers user over workspace over platform, per axis', () => {
    expect(resolveMenu(null, null)).toEqual(PLATFORM_MENU);
    expect(resolveMenu({ color: 'accent' }, { color: 'sections', view: 'floating' })).toEqual({
      ...PLATFORM_MENU,
      color: 'accent',
      view: 'floating',
    });
  });

  it('every platform default is an allowed value and stroke weights are the spec ones', () => {
    for (const axis of MENU_AXES) expect(MENU_AXIS_VALUES[axis]).toContain(PLATFORM_MENU[axis]);
    expect(MENU_STROKE_WIDTH).toEqual({ light: 1.25, regular: 1.75, bold: 2.25 });
    expect(CSS).toContain("html[data-menu-stroke='light'] { --oe-menu-stroke: 1.25; }");
    expect(CSS).toContain("html[data-menu-stroke='bold'] { --oe-menu-stroke: 2.25; }");
  });

  it('keeps only well-formed icon overrides', () => {
    expect(
      sanitizeIconOverrides({ '/boq': 'Calculator', '/x': 'lower', bad: 'Truck', '/rfi': 3, '/a': '<b>' }),
    ).toEqual({ '/boq': 'Calculator' });
    expect(sanitizeIconOverrides(['/boq'])).toEqual({});
  });
});

describe('menu presets', () => {
  it('are the six named bundles, Classic first and equal to the platform menu', () => {
    expect(MENU_PRESETS.map((p) => p.id)).toEqual([...MENU_PRESET_IDS]);
    expect(MENU_PRESETS[0]!.value).toEqual(PLATFORM_MENU);
  });

  it('are distinct, complete and valid, and each one is recognised', () => {
    const seen = new Set<string>();
    for (const preset of MENU_PRESETS) {
      expect(sanitizeMenu(preset.value)).toEqual(preset.value);
      expect(matchMenuPreset(preset.value)).toBe(preset.id);
      seen.add(JSON.stringify(MENU_AXES.map((a) => preset.value[a])));
    }
    expect(seen.size).toBe(MENU_PRESETS.length);
  });

  it('one changed axis makes a custom look', () => {
    expect(matchMenuPreset({ ...PLATFORM_MENU, active: 'pill' })).toBeNull();
  });
});

describe('section tones (WCAG AA)', () => {
  const light = vars(':root');
  const dark = vars('.dark');

  it('index.css carries exactly SECTION_TONES', () => {
    SECTION_TONES.forEach((tone, i) => {
      expect(light[`tone-${i}`]).toBe(tone.light);
      expect(dark[`tone-${i}`]).toBe(tone.dark);
    });
    expect(CSS).toContain(`[data-tone='${SECTION_TONES.length - 1}']`);
  });

  for (const [theme, spec, key] of [
    ['light', LIGHT, 'light'],
    ['dark', DARK, 'dark'],
  ] as const) {
    it(`every tone clears 4.5:1 in ${theme} mode on surfaces, the active row and its own tile`, () => {
      const failures: string[] = [];
      SECTION_TONES.forEach((tone, i) => {
        const ink = rgb(tone[key]);
        for (const s of spec.surfaces) {
          const surface = rgb(s);
          const backgrounds: [string, RGB][] = [
            [s, surface],
            [`${s}+active`, mix(rgb(spec.accent), spec.activeAlpha, surface)],
            [`${s}+tile`, mix(ink, TILE_ALPHA, surface)],
          ];
          for (const [name, bg] of backgrounds) {
            const r = ratio(ink, bg);
            if (r < AA) failures.push(`tone ${i} ${tone[key]} on ${name}: ${r.toFixed(2)}`);
          }
        }
      });
      expect(failures).toEqual([]);
    });
  }
});
