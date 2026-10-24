// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A style as a small portable file or link: the appearance axes plus the theme.
 *
 * Input from a file or a URL is untrusted. `parseStyle` keeps only known axes
 * with allowed values and refuses anything else, so a shared style can never
 * set more than the settings page itself could.
 */
import { type Appearance, PLATFORM_APPEARANCE, sanitizeAppearance } from './appearance';
import { type ThemeMode, type ThemeSchedule, isThemeMode, sanitizeSchedule } from './theme';

export const STYLE_FORMAT = 'openconstructionerp-style';
export const STYLE_VERSION = 1;
/** Far above any real style; stops a pasted megabyte from being parsed. */
export const STYLE_MAX_BYTES = 4096;
export const STYLE_URL_PARAM = 'appearance';

export interface SharedStyle {
  appearance: Appearance;
  theme?: ThemeMode;
  schedule?: ThemeSchedule;
}

export type StyleParseError = 'too_large' | 'not_json' | 'wrong_format' | 'wrong_version' | 'empty';
export type StyleParseResult = { ok: true; style: SharedStyle } | { ok: false; error: StyleParseError };

export function styleToJson(style: SharedStyle): string {
  const out: Record<string, unknown> = { format: STYLE_FORMAT, version: STYLE_VERSION, appearance: style.appearance };
  if (style.theme) out.theme = style.theme;
  if (style.theme === 'schedule' && style.schedule) out.schedule = style.schedule;
  return JSON.stringify(out, null, 2);
}

export function parseStyle(text: string): StyleParseResult {
  if (text.length > STYLE_MAX_BYTES) return { ok: false, error: 'too_large' };
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return { ok: false, error: 'not_json' };
  }
  if (!raw || typeof raw !== 'object' || (raw as Record<string, unknown>).format !== STYLE_FORMAT) {
    return { ok: false, error: 'wrong_format' };
  }
  const src = raw as Record<string, unknown>;
  if (src.version !== STYLE_VERSION) return { ok: false, error: 'wrong_version' };
  const appearance = sanitizeAppearance(src.appearance);
  const theme = isThemeMode(src.theme) ? src.theme : undefined;
  if (!appearance && !theme) return { ok: false, error: 'empty' };
  const style: SharedStyle = { appearance: { ...PLATFORM_APPEARANCE, ...(appearance ?? {}) } };
  if (theme) style.theme = theme;
  const schedule = theme === 'schedule' ? sanitizeSchedule(src.schedule) : null;
  if (schedule) style.schedule = schedule;
  return { ok: true, style };
}

function toBase64Url(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fromBase64Url(code: string): string | null {
  if (!/^[A-Za-z0-9_-]*$/.test(code)) return null;
  try {
    const bin = atob(code.replace(/-/g, '+').replace(/_/g, '/'));
    return new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
  } catch {
    return null;
  }
}

/** Compact share code: the JSON without whitespace, base64url. */
export function encodeStyleCode(style: SharedStyle): string {
  return toBase64Url(JSON.stringify(JSON.parse(styleToJson(style))));
}

export function decodeStyleCode(code: string): StyleParseResult {
  if (code.length > STYLE_MAX_BYTES * 2) return { ok: false, error: 'too_large' };
  const text = fromBase64Url(code);
  return text === null ? { ok: false, error: 'not_json' } : parseStyle(text);
}

export function styleShareUrl(style: SharedStyle, origin: string): string {
  const url = new URL('/settings', origin);
  url.searchParams.set(STYLE_URL_PARAM, encodeStyleCode(style));
  return url.toString();
}
