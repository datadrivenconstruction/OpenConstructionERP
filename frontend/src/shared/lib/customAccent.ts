// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A free company colour as the accent: WCAG contrast checks, derived
 * hover/active/text shades for light and dark mode, and the stylesheet that
 * points the `--oe-blue-*` tokens at them under `html[data-accent='custom']`.
 */

export const HEX_RE = /^#[0-9a-f]{6}$/i;
/** Cached stylesheet so the boot script in index.html paints it before React. */
export const CUSTOM_ACCENT_CSS_KEY = 'oe_custom_accent_css_v1';
const STYLE_ID = 'oe-custom-accent';

type Rgb = [number, number, number];

export function normalizeHex(raw: string): string | null {
  let v = raw.trim().toLowerCase();
  if (!v.startsWith('#')) v = `#${v}`;
  if (/^#[0-9a-f]{3}$/.test(v)) v = `#${v[1]}${v[1]}${v[2]}${v[2]}${v[3]}${v[3]}`;
  return HEX_RE.test(v) ? v : null;
}

function toRgb(hex: string): Rgb {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function toHex([r, g, b]: Rgb): string {
  return `#${[r, g, b].map((c) => Math.round(Math.min(255, Math.max(0, c))).toString(16).padStart(2, '0')).join('')}`;
}

/** Mix toward black (amount > 0 means darker) or white (amount < 0). */
function shade(hex: string, amount: number): string {
  const target = amount >= 0 ? 0 : 255;
  const t = Math.abs(amount);
  return toHex(toRgb(hex).map((c) => c + (target - c) * t) as Rgb);
}

function luminance(hex: string): number {
  const [r, g, b] = toRgb(hex).map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  }) as Rgb;
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** Step toward black or white until `against` reaches `min` contrast. */
function untilContrast(hex: string, against: string, min: number, darker: boolean): string {
  let out = hex;
  for (let i = 1; i <= 20 && contrastRatio(out, against) < min; i++) {
    out = shade(hex, darker ? i * 0.05 : -i * 0.05);
  }
  return out;
}

export interface AccentCheck {
  /** White button text on the colour. */
  ratio: number;
  passesAA: boolean;
  /** The nearest darker shade that passes AA with white text. */
  accessible: string;
}

export function checkAccent(hex: string): AccentCheck {
  const ratio = contrastRatio(hex, '#ffffff');
  return { ratio, passesAA: ratio >= 4.5, accessible: untilContrast(hex, '#ffffff', 4.5, true) };
}

const DARK_PAGE = '#0f172a';

export function customAccentCss(hex: string): string {
  const [r, g, b] = toRgb(hex);
  const darkBase = untilContrast(hex, DARK_PAGE, 4.5, false);
  const [dr, dg, db] = toRgb(darkBase);
  const light = {
    '': hex,
    hover: shade(hex, 0.08),
    active: shade(hex, 0.16),
    dark: untilContrast(shade(hex, 0.3), '#ffffff', 4.5, true),
    text: untilContrast(hex, '#ffffff', 4.5, true),
    subtle: shade(hex, -0.94),
  };
  const dark = {
    '': darkBase,
    hover: shade(darkBase, -0.2),
    active: shade(darkBase, 0.1),
    dark: untilContrast(shade(hex, 0.3), '#ffffff', 4.5, true),
    text: untilContrast(darkBase, DARK_PAGE, 7, false),
    subtle: `rgba(${dr}, ${dg}, ${db}, 0.15)`,
  };
  const block = (tokens: Record<string, string>, ch: string) =>
    Object.entries(tokens)
      .map(([k, v]) => `--oe-blue${k ? `-${k}` : ''}:${v};`)
      .join('') + `--oe-blue-ch:${ch};`;
  return (
    `html[data-accent='custom']{${block(light, `${r} ${g} ${b}`)}}` +
    `html.dark[data-accent='custom']{${block(dark, `${dr} ${dg} ${db}`)}}`
  );
}

/** Point the accent tokens at a custom colour, or remove it (null). */
export function applyCustomAccent(hex: string | null): void {
  if (typeof document === 'undefined') return;
  let el = document.getElementById(STYLE_ID);
  const css = hex ? customAccentCss(hex) : '';
  try {
    if (css) localStorage.setItem(CUSTOM_ACCENT_CSS_KEY, css);
    else localStorage.removeItem(CUSTOM_ACCENT_CSS_KEY);
  } catch {
    /* storage unavailable: the colour still applies for this session */
  }
  if (!css) {
    el?.remove();
    return;
  }
  if (!el) {
    el = document.createElement('style');
    el.id = STYLE_ID;
    document.head.appendChild(el);
  }
  el.textContent = css;
}
