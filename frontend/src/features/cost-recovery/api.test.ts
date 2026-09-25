import { describe, expect, it } from 'vitest';
import { sourceBackChargeBody } from './api';

describe('sourceBackChargeBody', () => {
  it('links a punch item and a subcontractor and sends no figures', () => {
    expect(sourceBackChargeBody({ kind: 'punch_item', id: 'p1' }, 's1', '')).toEqual({
      punch_item_id: 'p1',
      subcontractor_id: 's1',
    });
  });

  it('links an NCR and keeps a typed party as the label', () => {
    expect(sourceBackChargeBody({ kind: 'ncr', id: 'n1' }, '', '  Glazing supplier ')).toEqual({
      ncr_id: 'n1',
      responsible_party: 'Glazing supplier',
    });
  });
});
