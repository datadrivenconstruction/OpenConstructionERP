// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import type { TFunction } from 'i18next';
import { awardPreview, awardPreviewMessage, awardRatesMessage } from '../awardRates';

// Echo the key and the interpolation, so the test reads which sentence was
// chosen and with what number.
const t = ((key: string, opts?: Record<string, unknown>) =>
  opts && 'n' in opts
    ? `${key}:${String(opts.n)}`
    : opts && 'count' in opts
      ? `${key}:${String(opts.count)}`
      : key) as unknown as TFunction;

const base = { package_id: 'p', bid_id: 'b', boq_id: 'q' };

describe('awardRatesMessage', () => {
  it('counts the positions an award wrote', () => {
    expect(awardRatesMessage({ ...base, positions_updated: 7, rates_skipped_reason: null }, t)).toBe(
      'tendering.award_rates_written:7',
    );
  });

  it('says a locked bill was left as approved', () => {
    expect(awardRatesMessage({ ...base, positions_updated: 0, rates_skipped_reason: 'boq_locked' }, t)).toBe(
      'tendering.award_rates_locked',
    );
  });

  it('says a lump-sum bid had no rates to write', () => {
    expect(awardRatesMessage({ ...base, positions_updated: 0, rates_skipped_reason: 'no_line_rates' }, t)).toBe(
      'tendering.award_rates_lump_sum',
    );
  });

  it('counts the lines kept when the winner priced none of them, as the dialog did', () => {
    expect(
      awardRatesMessage(
        { ...base, positions_updated: 0, positions_unpriced: 4, rates_skipped_reason: 'no_line_rates' },
        t,
      ),
    ).toBe('tendering.award_rates_lump_sum tendering.award_unpriced_keep:4');
  });
});

describe('awardPreview', () => {
  const rows = [
    { position_id: 'p1', ordinal: '01.010', budget_rate: 18.37 },
    { position_id: 'p2', ordinal: '01.020', budget_rate: '41.93' },
    { position_id: 'p3', ordinal: '01.030', budget_rate: 57.61 },
  ];

  it('counts every rated line the award writes and the ones that change', () => {
    const preview = awardPreview(
      [
        { position_id: 'p1', unit_rate: '18.37' },
        { position_id: 'p2', unit_rate: 40 },
        { position_id: 'p3', unit_rate: '60.00' },
        // No position, or no rate: apply_winner skips them and the bill keeps
        // its rate.
        { unit_rate: 10 },
        { position_id: 'p5' },
        { position_id: 'p4', unit_rate: null },
        { position_id: 'p6', unit_rate: '' },
      ],
      rows,
    );
    expect(preview).toEqual({ written: 3, changed: 2, changedOrdinals: ['01.020', '01.030'], unpriced: 0 });
  });

  it('counts the lines the bid left unpriced, a priced zero excepted', () => {
    const lines = [
      { position_id: 'h', ordinal: '01', budget_rate: 0, unit: '', description: 'Shell', budget_quantity: 0 },
      { position_id: 'p1', ordinal: '01.010', budget_rate: 50, unit: 'm3', description: 'Wall', budget_quantity: 10 },
      { position_id: 'p2', ordinal: '01.020', budget_rate: 50, unit: 'm3', description: 'Slab', budget_quantity: 10 },
      { position_id: 'p3', ordinal: '01.030', budget_rate: 50, unit: 'm2', description: 'Roof', budget_quantity: 10 },
      { position_id: 'p4', ordinal: '01.040', budget_rate: 50, unit: 'pcs', description: 'Item', budget_quantity: 1 },
    ];
    const preview = awardPreview(
      [
        { position_id: 'p1', unit_rate: '70' },
        { position_id: 'p2', unit_rate: null },
        // p3 is not in the bid at all; p4 is included at no charge.
        { position_id: 'p4', unit_rate: '0' },
      ],
      lines,
    );
    expect(preview.written).toBe(2);
    expect(preview.unpriced).toBe(2);
    expect(awardPreviewMessage(preview, t)).toContain('tendering.award_unpriced_keep:2');
  });

  it('does not count a blank placeholder row, which no bidder was sent', () => {
    const lines = [
      { position_id: 'p1', ordinal: '01.010', budget_rate: 50, unit: 'm3', description: 'Wall', budget_quantity: 10 },
      { position_id: 'p2', ordinal: '01.020', budget_rate: 50, unit: 'm3', description: 'Slab', budget_quantity: 10 },
      // "Add Position" left this row empty: no text, no quantity.
      { position_id: 'blank', ordinal: '01.030', budget_rate: 0, unit: 'm2', description: '', budget_quantity: 0 },
    ];
    const preview = awardPreview(
      [
        { position_id: 'p1', unit_rate: '60' },
        { position_id: 'p2', unit_rate: '60' },
      ],
      lines,
    );
    expect(preview.unpriced).toBe(0);
    expect(awardPreviewMessage(preview, t)).not.toContain('award_unpriced_keep');
  });

  it('says in the toast how many positions kept their rate', () => {
    const result = { ...base, positions_updated: 2, positions_unpriced: 3, rates_skipped_reason: null };
    expect(awardRatesMessage(result, t)).toBe('tendering.award_rates_written:2 tendering.award_unpriced_keep:3');
    expect(awardRatesMessage({ ...result, positions_unpriced: 0 }, t)).toBe('tendering.award_rates_written:2');
  });

  it('says a lump-sum bid changes nothing', () => {
    expect(awardPreviewMessage(awardPreview([], rows), t)).toBe('tendering.award_preview_no_rates');
  });

  it('says when no written rate differs from the bill', () => {
    const preview = awardPreview([{ position_id: 'p1', unit_rate: 18.37 }], rows);
    expect(awardPreviewMessage(preview, t)).toBe(
      'tendering.award_preview_written:1 tendering.award_preview_none_changed',
    );
  });

  it('names the changed positions and folds a long list', () => {
    const many = Array.from({ length: 7 }, (_, i) => ({ position_id: `q${i}`, ordinal: `02.0${i}`, budget_rate: 1 }));
    const preview = awardPreview(many.map((r) => ({ position_id: r.position_id, unit_rate: 2 })), many);
    expect(preview.changedOrdinals).toHaveLength(7);
    const withList = ((key: string, opts?: Record<string, unknown>) =>
      opts && 'list' in opts ? `${key}:${String(opts.list)}` : t(key, opts as never)) as unknown as TFunction;
    const message = awardPreviewMessage(preview, withList);
    expect(message).toContain('02.00');
    expect(message).toContain('02.04');
    expect(message).not.toContain('02.05');
    expect(message).toContain('tendering.award_preview_more:2');
  });
});
