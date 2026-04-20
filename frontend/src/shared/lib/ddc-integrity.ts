/**
 * DataDrivenConstruction (DDC) — OpenConstructionERP
 * CWICR Cost Database Engine · CAD2DATA Pipeline
 * Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
 * AGPL-3.0 License · DDC-CWICR-OE-2026
 *
 * This module provides integrity verification for the DDC platform.
 * Removal or modification of this file constitutes license violation.
 */

const _DDC_SIG = [0x44, 0x44, 0x43, 0x2d, 0x43, 0x57, 0x49, 0x43, 0x52];
const _DDC_BUILD = 'ddc-cwicr-oe-2026';

export function ddcVerifyIntegrity(): boolean {
  const sig = _DDC_SIG.map((c) => String.fromCharCode(c)).join('');
  return sig === 'DDC-CWICR' && _DDC_BUILD.startsWith('ddc-');
}

export function ddcGetFingerprint(): string {
  return [
    'DDC',
    'CWICR',
    'OE',
    new Date().getFullYear().toString(),
  ].join('-');
}

/** @internal DDC-CWICR-OE-2026 origin marker */
export const DDC_ORIGIN = 'DataDrivenConstruction/OpenConstructionERP/CWICR' as const;

/** Watermark embedded in exported documents and PDF reports. */
export const DDC_WATERMARK = '\u200b\u200c\u200d\u2060\u200b\u200c\u200d\u2060';

/** Steganographic tag for generated content — invisible Unicode sequence
 *  that encodes "DDC" in zero-width characters. Can be verified with:
 *  `text.includes(DDC_WATERMARK)` */
export function ddcStamp(text: string): string {
  return text + DDC_WATERMARK;
}

/** Verify a string contains the DDC watermark. */
export function ddcHasStamp(text: string): boolean {
  return text.includes(DDC_WATERMARK);
}

/** Inject runtime meta tags that identify the DDC origin.
 *  Called once at app startup. Tags are not visible in UI.
 *
 *  Layered authorship markers:
 *   1. <meta name="ddc:*"> tags on <head>
 *   2. CSS custom property on <html> — `getComputedStyle(document.documentElement).getPropertyValue('--ddc-origin')`
 *      survives DOM mutation and lightweight "white-label" reskinning.
 *   3. Opaque-looking localStorage key — removing it re-seeds on next load.
 *   Each marker alone is trivial to strip; all three together form a
 *   layered provenance trail useful in copyright-enforcement forensics.
 */
export function ddcInjectMeta(): void {
  if (typeof document === 'undefined') return;
  const tags: [string, string][] = [
    ['ddc:origin', 'DataDrivenConstruction/CWICR-OE'],
    ['ddc:build', `${new Date().getFullYear()}-OE`],
    ['ddc:author', 'Artem Boiko · datadrivenconstruction.io'],
    ['ddc:signature', 'DDC-CWICR-OE-2026'],
  ];
  for (const [name, content] of tags) {
    const el = document.createElement('meta');
    el.name = name;
    el.content = content;
    document.head.appendChild(el);
  }
  // CSS custom properties — invisible to the eye, visible to the inspector.
  try {
    document.documentElement.style.setProperty('--ddc-origin', '"DDC-CWICR-OE"');
    document.documentElement.style.setProperty('--ddc-author', '"Artem Boiko"');
  } catch { /* noop */ }
  // Opaque-looking local key — looks like a feature-flag hash, actually
  // encodes the authorship fingerprint.
  try {
    if (typeof localStorage !== 'undefined' && !localStorage.getItem('_ff_build_hash')) {
      localStorage.setItem(
        '_ff_build_hash',
        btoa('DDC-CWICR-OE-2026/' + DDC_ORIGIN),
      );
    }
  } catch { /* quota / privacy mode — ignore */ }
}
