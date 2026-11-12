import { describe, expect, it } from 'vitest';
import { getGaebLongText, langtextBlockHeight } from './longText';

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
  it('clamps the block height', () => {
    expect(langtextBlockHeight('x')).toBe(48);
    expect(langtextBlockHeight('x\n'.repeat(100))).toBe(260);
  });
});
