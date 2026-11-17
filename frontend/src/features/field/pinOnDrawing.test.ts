// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
import { describe, expect, it } from 'vitest';
import { MAX_CACHED_SHEETS, buildPlanPinOp, clamp01, overflowKeys } from './pinOnDrawing';

describe('plan_pin queue op', () => {
  it('names the record it follows and keeps the position inside the sheet', () => {
    const op = buildPlanPinOp('pin-1', 'punch', 'punch-1', { documentId: 'd1', page: 2, x: 1.4, y: -0.2 });
    expect(op).toMatchObject({
      clientOpId: 'pin-1',
      method: 'POST',
      path: '/v1/field-diary/capture/plan-pin/',
      kind: 'field.plan_pin',
      body: { record_kind: 'punch', record_client_op_id: 'punch-1', document_id: 'd1', page: 2, x: 1, y: 0 },
    });
  });

  it('clamps to 0..1', () => {
    expect([clamp01(-1), clamp01(0.3), clamp01(7)]).toEqual([0, 0.3, 1]);
  });

  it('drops the oldest cached sheets beyond the cap', () => {
    const keys = Array.from({ length: MAX_CACHED_SHEETS + 3 }, (_, i) => `k${i}`);
    expect(overflowKeys(keys)).toEqual(['k0', 'k1', 'k2']);
    expect(overflowKeys(keys.slice(0, 5))).toEqual([]);
  });
});
