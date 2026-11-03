import { describe, expect, it } from 'vitest';
import { confidencePercent, confirmable, sheetExtraction } from './sheetOcr';
import type { SheetRow } from './types';

const row = (extraction?: Record<string, unknown>) =>
  ({ metadata: extraction ? { extraction } : {} }) as unknown as SheetRow;

describe('sheetOcr', () => {
  it('ignores sheets read from the text layer', () => {
    expect(sheetExtraction(row({ source: 'text', confidence: 1, needs_review: false }))).toBeNull();
    expect(sheetExtraction(row())).toBeNull();
  });

  it('reads the OCR reading and its percent', () => {
    const e = sheetExtraction(row({ source: 'ocr', confidence: 0.724, needs_review: true }));
    expect(e).not.toBeNull();
    expect(confidencePercent(e!)).toBe(72);
    expect(e!.needsReview).toBe(true);
  });

  it('confirms only flagged sheets at or above the threshold', () => {
    const high = row({ source: 'ocr', confidence: 0.9, needs_review: true });
    const low = row({ source: 'ocr', confidence: 0.5, needs_review: true });
    const done = row({ source: 'ocr', confidence: 0.95, needs_review: false });
    expect(confirmable([high, low, done])).toEqual([high]);
  });
});
