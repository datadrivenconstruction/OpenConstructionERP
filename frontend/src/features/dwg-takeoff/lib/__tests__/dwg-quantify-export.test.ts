// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The XLSX summary prints the same totals as the UI and the CSV, and carries
 * the manual Distance / Area / Count annotations it used to leave out.
 */

import { describe, it, expect } from 'vitest';
import type { DxfEntity } from '../../api';
import { quantifyByLayer } from '../auto-quantify';
import { buildQuantifyWorkbook } from '../dwg-quantify-export';
import { quantifyTotals } from '../takeoff-totals';

const entities: DxfEntity[] = [
  { id: 'l1', type: 'LINE', layer: '0', color: '#fff', start: { x: 0, y: 0 }, end: { x: 2850, y: 0 } },
  { id: 'a1', type: 'ARC', layer: '0', color: '#fff', start: { x: 0, y: 0 }, radius: 48, start_angle: 0, end_angle: Math.PI },
  { id: 'l2', type: 'LINE', layer: 'E-POWER', color: '#fff', start: { x: 0, y: 0 }, end: { x: 210, y: 0 } },
];

describe('buildQuantifyWorkbook', () => {
  it('writes the UI totals and a manual measurements sheet', async () => {
    const rows = quantifyByLayer(entities, 0.001);
    const totals = quantifyTotals(rows);
    const wb = await buildQuantifyWorkbook({
      drawingName: 'plan',
      layerQuantities: rows,
      totals,
      manualRows: [
        { type: 'distance', text: '', value: 0.05485, unit: 'm' },
        { type: 'area', text: 'Room', value: 0.84629, unit: 'm²' },
        { type: 'count', text: '', value: 3, unit: 'nr' },
      ],
    });

    const ws = wb.getWorksheet('Quantities by layer')!;
    let totalLength: unknown = null;
    ws.eachRow((row) => {
      if (row.getCell(1).value === 'TOTAL') totalLength = row.getCell(6).value;
    });
    expect(totalLength).toBeCloseTo(totals.length, 3);
    expect(totals.length).toBeCloseTo(2.85 + Math.PI * 0.048 + 0.21, 3);

    const manual = wb.getWorksheet('Manual measurements');
    expect(manual).toBeDefined();
    const values: unknown[] = [];
    manual!.eachRow((row, i) => {
      if (i > 1) values.push(row.getCell(3).value);
    });
    expect(values).toEqual([0.055, 0.846, 3]);
  });
});
