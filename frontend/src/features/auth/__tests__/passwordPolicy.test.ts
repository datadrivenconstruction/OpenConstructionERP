// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';

import { meetsPasswordPolicy } from '../passwordPolicy';

/**
 * The client copy of `_validate_strong_password` (backend users/schemas.py).
 * Each case is one the server decides the same way, so a password the form
 * lets through is never refused for length, letter or digit.
 */
describe('meetsPasswordPolicy', () => {
  it('accepts 8 characters with a letter and a digit', () => {
    expect(meetsPasswordPolicy('abcdefg1')).toBe(true);
  });

  it('refuses a short password, one without a digit and one without a letter', () => {
    expect(meetsPasswordPolicy('abcdef1')).toBe(false);
    expect(meetsPasswordPolicy('abcdefgh')).toBe(false);
    expect(meetsPasswordPolicy('12345678')).toBe(false);
  });

  it('takes a letter in any script, as Python str.isalpha does', () => {
    expect(meetsPasswordPolicy('κωδικός12')).toBe(true);
    expect(meetsPasswordPolicy('密码密码密码12')).toBe(true);
    expect(meetsPasswordPolicy('пароль12')).toBe(true);
  });

  it('measures after trimming, as the request schema strips whitespace', () => {
    expect(meetsPasswordPolicy('  abcde1  ')).toBe(false);
  });

  it('counts code points, as Python len does', () => {
    // Seven code points, fourteen UTF-16 units: the server says too short.
    expect(meetsPasswordPolicy('a1\u{1F600}\u{1F600}\u{1F600}\u{1F600}\u{1F600}')).toBe(false);
    // 128 code points is the ceiling, though it is 254 UTF-16 units.
    expect(meetsPasswordPolicy('a1' + '\u{1F600}'.repeat(126))).toBe(true);
    expect(meetsPasswordPolicy('a1' + 'x'.repeat(127))).toBe(false);
  });
});
