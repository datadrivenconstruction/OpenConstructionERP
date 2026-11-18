import { describe, expect, it } from 'vitest';
import {
  getGaebLongText,
  positionRowHeight,
  sectionRowHeight,
  visibleTextLines,
  wrappedLineCount,
} from './longText';

// Every character is 10px wide, so a 100px column holds 10 characters.
const mono = (s: string) => s.length * 10;

describe('longText helpers', () => {
  it('reads gaeb_long_text and normalises line breaks', () => {
    expect(getGaebLongText({ gaeb_long_text: ' a\r\nb ' })).toBe('a\nb');
  });
  it('returns null for missing, blank or non-string values', () => {
    expect(getGaebLongText(undefined)).toBeNull();
    expect(getGaebLongText({})).toBeNull();
    expect(getGaebLongText({ gaeb_long_text: '   ' })).toBeNull();
    expect(getGaebLongText({ gaeb_long_text: 5 })).toBeNull();
  });

  it('counts wrapped lines and honours hard breaks', () => {
    expect(wrappedLineCount('', 100, mono)).toBe(0);
    expect(wrappedLineCount('abcd efgh', 100, mono)).toBe(1);
    expect(wrappedLineCount('abcd efgh ijkl', 100, mono)).toBe(2);
    expect(wrappedLineCount('a\nb\n\nc', 100, mono)).toBe(4);
    expect(wrappedLineCount('x'.repeat(25), 100, mono)).toBe(3);
  });

  it('shows no Langtext when the mode is off and the row is folded', () => {
    const lines = visibleTextLines({ shortText: 'Beton', longText: 'a\nb\nc', mode: 'compact', expanded: false, widthPx: 100, measure: mono });
    expect(lines).toEqual({ shortLines: 1, longLines: 0, longTotal: 3 });
    expect(positionRowHeight(32, lines)).toBe(32);
  });

  it('clamps to two lines in preview and shows everything in full or when unfolded', () => {
    const base = { shortText: 'Beton', longText: 'a\nb\nc\nd', widthPx: 100, measure: mono };
    expect(visibleTextLines({ ...base, mode: 'comfortable', expanded: false }).longLines).toBe(2);
    expect(visibleTextLines({ ...base, mode: 'tall', expanded: false }).longLines).toBe(4);
    expect(visibleTextLines({ ...base, mode: 'compact', expanded: true }).longLines).toBe(4);
  });

  it('sizes rows to the visible lines', () => {
    expect(positionRowHeight(32, { shortLines: 1, longLines: 2 })).toBe(10 + 18 + 4 + 36);
    expect(positionRowHeight(32, { shortLines: 2, longLines: 0 })).toBe(46);
    expect(sectionRowHeight(0)).toBe(38);
    expect(sectionRowHeight(3)).toBe(38 + 8 + 54);
  });
});
