// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Runs the real boot script from index.html, the one that paints the saved
// style before the bundle loads, and checks it agrees with appearance.ts on
// keys, values, layering and font stylesheet paths.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  AXIS_VALUES,
  PLATFORM_APPEARANCE,
  USER_APPEARANCE_KEY,
  WORKSPACE_APPEARANCE_KEY,
  fontStylesheetHref,
} from '../appearance';
import { MENU_AXES, MENU_AXIS_VALUES, PLATFORM_MENU, USER_MENU_KEY, WORKSPACE_MENU_KEY } from '../menuAppearance';

const HTML = readFileSync(resolve(__dirname, '../../../../index.html'), 'utf-8');
const SCRIPT = /<script id="oe-appearance-boot">([\s\S]*?)<\/script>/.exec(HTML)?.[1] ?? '';

function boot() {
  new Function(SCRIPT)();
}

function attrs() {
  const d = document.documentElement.dataset;
  return { accent: d.accent, font: d.font, density: d.density, radius: d.radius };
}

function menuAttrs() {
  const root = document.documentElement;
  return Object.fromEntries(MENU_AXES.map((axis) => [axis, root.getAttribute(`data-menu-${axis}`)]));
}

beforeEach(() => {
  localStorage.clear();
  const root = document.documentElement;
  for (const k of ['accent', 'font', 'density', 'radius']) root.removeAttribute(`data-${k}`);
  for (const k of MENU_AXES) root.removeAttribute(`data-menu-${k}`);
  root.classList.remove('dark');
  document.head.querySelectorAll('link[data-oe-font]').forEach((l) => l.remove());
});

afterEach(() => localStorage.clear());

describe('index.html appearance boot script', () => {
  it('exists and runs before the app bundle', () => {
    expect(SCRIPT).not.toBe('');
    expect(HTML.indexOf('oe-appearance-boot')).toBeLessThan(HTML.indexOf('/src/main.tsx'));
  });

  it('allows exactly the values appearance.ts allows', () => {
    for (const [axis, values] of Object.entries(AXIS_VALUES)) {
      expect(SCRIPT).toContain(`${axis}: [${values.map((v) => `'${v}'`).join(', ')}]`);
    }
  });

  it('paints the platform default with nothing stored', () => {
    boot();
    expect(attrs()).toEqual(PLATFORM_APPEARANCE);
    expect(document.head.querySelector('link[data-oe-font]')).toBeNull();
  });

  it('follows the workspace default when the user has no choice', () => {
    localStorage.setItem(WORKSPACE_APPEARANCE_KEY, JSON.stringify({ accent: 'teal', density: 'compact' }));
    boot();
    expect(attrs()).toEqual({ ...PLATFORM_APPEARANCE, accent: 'teal', density: 'compact' });
  });

  it('lets the user choice win and links the chosen font stylesheet', () => {
    localStorage.setItem(WORKSPACE_APPEARANCE_KEY, JSON.stringify({ accent: 'teal' }));
    localStorage.setItem(
      USER_APPEARANCE_KEY,
      JSON.stringify({ accent: 'violet', font: 'inter', density: 'comfortable', radius: 'round' }),
    );
    boot();
    expect(attrs()).toEqual({ accent: 'violet', font: 'inter', density: 'comfortable', radius: 'round' });
    const link = document.head.querySelector<HTMLLinkElement>('link[data-oe-font="inter"]');
    expect(link?.getAttribute('href')).toBe(fontStylesheetHref('inter'));
  });

  it('ignores junk in storage', () => {
    localStorage.setItem(USER_APPEARANCE_KEY, '{not json');
    localStorage.setItem(WORKSPACE_APPEARANCE_KEY, JSON.stringify({ accent: 'pink', font: '../../x' }));
    boot();
    expect(attrs()).toEqual(PLATFORM_APPEARANCE);
  });

  it('allows exactly the menu values menuAppearance.ts allows', () => {
    for (const [axis, values] of Object.entries(MENU_AXIS_VALUES)) {
      expect(SCRIPT).toContain(`${axis}: [${values.map((v) => `'${v}'`).join(', ')}]`);
    }
  });

  it('paints the classic menu with nothing stored', () => {
    boot();
    expect(menuAttrs()).toEqual(PLATFORM_MENU);
  });

  it('layers the user menu look over the workspace one and drops junk', () => {
    localStorage.setItem(WORKSPACE_MENU_KEY, JSON.stringify({ view: 'floating', color: 'sections' }));
    localStorage.setItem(USER_MENU_KEY, JSON.stringify({ view: 'rail', stroke: 'heavy', icons: 'hidden' }));
    boot();
    expect(menuAttrs()).toEqual({ ...PLATFORM_MENU, view: 'rail', color: 'sections', icons: 'hidden' });
  });

  it('applies the saved dark theme before paint', () => {
    localStorage.setItem('oe_theme', 'dark');
    boot();
    expect(document.documentElement.classList.contains('dark')).toBe(true);
  });
});
