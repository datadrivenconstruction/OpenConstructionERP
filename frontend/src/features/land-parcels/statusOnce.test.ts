import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

describe('parcel schedule status cell', () => {
  it('prints the status once: StatusDot already renders its label', () => {
    const src = readFileSync(resolve(__dirname, 'LandParcelsPage.tsx'), 'utf8');
    const uses = src.match(/statusLabel\(p\.status\)/g) ?? [];
    expect(uses).toHaveLength(1);
    expect(src).toMatch(/<StatusDot[^>]*label=\{statusLabel\(p\.status\)\}/);
  });
});
