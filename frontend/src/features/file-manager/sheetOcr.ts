import type { SheetRow } from './types';

/** What the backend recorded about how a sheet's title block was read. */
export interface SheetExtraction {
  source: 'text' | 'ocr';
  confidence: number;
  needsReview: boolean;
  reason: string | null;
}

/** The OCR reading of a sheet, or null for a sheet read from its text layer. */
export function sheetExtraction(sheet: Pick<SheetRow, 'metadata'>): SheetExtraction | null {
  const raw = sheet.metadata?.extraction as Record<string, unknown> | undefined;
  if (!raw || raw.source !== 'ocr') return null;
  const confidence = typeof raw.confidence === 'number' ? raw.confidence : 0;
  return {
    source: 'ocr',
    confidence,
    needsReview: raw.needs_review === true,
    reason: typeof raw.reason === 'string' ? raw.reason : null,
  };
}

/** Whole percent, 0..100, for the badge. */
export function confidencePercent(extraction: SheetExtraction): number {
  return Math.round(Math.min(1, Math.max(0, extraction.confidence)) * 100);
}

/** Flagged sheets read at or above `min` (0..1): what "Confirm all above 80%" acts on. */
export function confirmable(sheets: SheetRow[], min = 0.8): SheetRow[] {
  return sheets.filter((s) => {
    const e = sheetExtraction(s);
    return e !== null && e.needsReview && e.confidence >= min;
  });
}
