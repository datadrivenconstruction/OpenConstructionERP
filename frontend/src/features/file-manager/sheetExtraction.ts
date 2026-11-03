// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * How a sheet's title block was read, as the backend records it in
 * `metadata.extraction`, and what the register shows for it.
 *
 * AI suggests, a person confirms: a read that came from OCR, or from a text
 * layer too thin to trust, is held until somebody confirms it. A held sheet
 * does not supersede the revision it matches.
 */
import type { SheetRow } from './types';

export type ExtractionSource = 'text' | 'ocr';

export interface SheetExtraction {
  source: ExtractionSource;
  /** 0..1 */
  confidence: number;
  needsReview: boolean;
  reason: string | null;
  /** Ids of the current sheets this one would supersede once confirmed. */
  wouldSupersede: string[];
}

/** Title block fields the reader fills, as the edit form names them. */
export const READ_FIELDS = ['sheet_number', 'sheet_title', 'revision', 'discipline'] as const;
export type ReadField = (typeof READ_FIELDS)[number];

/** Default confidence for "confirm all": the backend's review threshold. */
export const BULK_CONFIRM_THRESHOLD = 0.8;

export function readExtraction(sheet: SheetRow): SheetExtraction | null {
  const raw = (sheet.metadata as Record<string, unknown> | undefined)?.extraction;
  if (!raw || typeof raw !== 'object') return null;
  const e = raw as Record<string, unknown>;
  const would = (sheet.metadata as Record<string, unknown>).would_supersede;
  return {
    source: e.source === 'ocr' ? 'ocr' : 'text',
    confidence: typeof e.confidence === 'number' ? e.confidence : 0,
    needsReview: e.needs_review === true,
    reason: typeof e.reason === 'string' ? e.reason : null,
    wouldSupersede: Array.isArray(would) ? would.filter((x): x is string => typeof x === 'string') : [],
  };
}

export function needsReview(sheet: SheetRow): boolean {
  return readExtraction(sheet)?.needsReview === true;
}

/** OCR could not run at all: nothing was read, so a bulk confirmation must skip it. */
export function ocrUnavailable(sheet: SheetRow): boolean {
  return readExtraction(sheet)?.reason === 'ocr_unavailable';
}

export function percent(confidence: number): number {
  return Math.round(Math.max(0, Math.min(1, confidence)) * 100);
}

/** Sheets a "confirm all above N" would accept, mirroring the server's rule. */
export function bulkConfirmable(sheets: SheetRow[], minConfidence = BULK_CONFIRM_THRESHOLD): SheetRow[] {
  return sheets.filter((s) => {
    const e = readExtraction(s);
    return !!e && e.needsReview && e.reason !== 'ocr_unavailable' && !!s.sheet_number && e.confidence >= minConfidence;
  });
}

/** Title block fields a person has not yet looked at: still the software's reading. */
export function machineReadFields(sheet: SheetRow): Set<ReadField> {
  const e = readExtraction(sheet);
  if (!e || !e.needsReview) return new Set();
  const edited = (sheet.metadata as Record<string, unknown>).manually_edited;
  const hand = new Set(Array.isArray(edited) ? (edited as string[]) : []);
  return new Set(READ_FIELDS.filter((f) => !hand.has(f) && !!sheet[f]));
}
