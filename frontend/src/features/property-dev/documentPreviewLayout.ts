// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What the document previews share: the sheet's size, the defaults of the page,
 * header, footer and watermark settings, and how the footer words them.
 *
 * Two previews draw from this, the small one in the appearance panel and the
 * letterhead preview of Company & documents, so they cannot disagree about what
 * a setting does. The strings here are not interface copy. They are the text
 * the PDF prints ("Page 3 of 7", "Printed: ..."), which the server writes in
 * English whatever the reader's language, so the preview shows exactly that.
 */

import type { DocumentAppearance } from './api';

/** Paper sizes in millimetres, portrait. */
export const PAGE_MM: Record<string, { w: number; h: number }> = {
  A4: { w: 210, h: 297 },
  LETTER: { w: 216, h: 279 },
  LEGAL: { w: 216, h: 356 },
};

/** The sheet's width and height in millimetres, turned for landscape. */
export function sheetMm(pageSize: string, orientation?: string): { w: number; h: number } {
  const base = PAGE_MM[pageSize] ?? PAGE_MM.A4!;
  return orientation === 'landscape' ? { w: base.h, h: base.w } : base;
}

/** Margin shortcuts for the margin field; the field still takes any value in range. */
export const MARGIN_PRESETS = [
  { key: 'narrow', mm: 15 },
  { key: 'normal', mm: 25 },
  { key: 'wide', mm: 35 },
] as const;

/** What the server sends for a setting an older server does not know. */
export const NEW_APPEARANCE_DEFAULTS = {
  watermark_opacity: 14,
  watermark_layout: 'diagonal',
  page_orientation: 'portrait',
  header_show_contact: false,
  header_rule: true,
  page_number_format: 'page_of',
  print_stamp: 'auto',
  footer_show_registration: false,
} as const;

export type ResolvedAppearance = DocumentAppearance &
  Required<Pick<DocumentAppearance, keyof typeof NEW_APPEARANCE_DEFAULTS>>;

/** The appearance with every newer setting filled in from the platform defaults. */
export function withAppearanceDefaults(appearance: DocumentAppearance): ResolvedAppearance {
  return {
    ...NEW_APPEARANCE_DEFAULTS,
    ...Object.fromEntries(Object.entries(appearance).filter(([, v]) => v !== undefined)),
  } as ResolvedAppearance;
}

/** The sample page number in a `page_number_format`, as the footer prints it. */
export function pageNumberSample(format: string, page = 1, total = 3): string {
  switch (format) {
    case 'number':
      return String(page);
    case 'short':
      return `${page} / ${total}`;
    case 'page':
      return `Page ${page}`;
    default:
      return `Page ${page} of ${total}`;
  }
}

/** The "Printed: ..." line for a `print_stamp`, empty when the footer prints none. */
export function printStampSample(mode: string): string {
  if (mode === 'date') return 'Printed: 2026-01-01';
  if (mode === 'datetime') return 'Printed: 2026-01-01 14:05 UTC';
  return '';
}
