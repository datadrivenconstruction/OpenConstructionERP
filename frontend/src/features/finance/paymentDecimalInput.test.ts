// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createHash, webcrypto } from 'node:crypto';
import { paymentDecimalInput, paymentIdempotencyKey } from './paymentDecimalInput';

afterEach(() => vi.unstubAllGlobals());

describe('exact bounded payment number input', () => {
  it.each([
    ['1e3', '1000'], ['1.234e2', '123.4'], ['1.25e-1', '0.125'],
    ['9.007199254740993e15', '9007199254740993'],
    ['-1E+2', '-100'], ['+1.2300', '1.2300'], ['.50', '0.50'],
    ['1.', '1'], ['', '0'], ['  ', '0'], ['-0.000', '0'],
    ['0e999999999999999999999999999999', '0'],
    ['1e49', '1' + '0'.repeat(49)], ['1e-48', '0.' + '0'.repeat(47) + '1'],
  ])('expands %s without floating-point conversion', (input, expected) => {
    expect(paymentDecimalInput(input)).toBe(expected);
  });
  it.each(['1e50', '1e-49', '1e999999999999999999999', '1'.repeat(51), 'NaN', 'Infinity', '1e', '0x10', '10abc'])('rejects unsupported input %s', (input) => {
    expect(paymentDecimalInput(input)).toBeNull();
  });
});

describe('bounded payment idempotency identity', () => {
  it('preserves the existing key up to64 characters without crypto', async () => {
    vi.stubGlobal('crypto', undefined);
    const original = 'pay-' + 'a'.repeat(60);
    expect(await paymentIdempotencyKey(original)).toBe(original);
  });
  it('hashes long original keys with SHA256, stably and distinctly', async () => {
    vi.stubGlobal('crypto', webcrypto);
    const original = 'pay-b7e53ca8-1ad2-4cc3-8598-b91873d61920-2026-10-07-9007199254740993.00';
    const key = await paymentIdempotencyKey(original);
    expect(key).toBe(createHash('sha256').update(original).digest('hex'));
    expect(key).toHaveLength(64);
    expect(await paymentIdempotencyKey(original)).toBe(key);
    expect(await paymentIdempotencyKey(original + '0')).not.toBe(key);
  });
  it('fails closed for a long key without crypto', async () => {
    vi.stubGlobal('crypto', undefined);
    await expect(paymentIdempotencyKey('a'.repeat(65))).rejects.toThrow();
  });
});
