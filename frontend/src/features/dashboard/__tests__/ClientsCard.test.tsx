// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Dashboard Clients widget: rows roll projects up per client with the
 * contract value summed PER CURRENCY (never blended), sorted busiest
 * first; the compact money figure rolls over to "M" where "1,000K" would
 * otherwise print; a client with hundreds of projects is one row.
 */
import { describe, it, expect } from 'vitest';
import { buildClientRows, compactMoney } from '../components/ClientsCard';
import type { Project } from '@/features/projects/api';

const ACME = 'b95fbffc-0909-46c2-89fb-91c1622fd34e';
const OTHER = '87bda4c8-2a3f-45dd-bedc-c49c93ccafb6';

function project(over: Partial<Project> & { id: string }): Project {
  return {
    name: `Project ${over.id}`,
    status: 'active',
    currency: 'AUD',
    contract_value: null,
    client_id: null,
    created_at: '2026-01-01T00:00:00Z',
    ...over,
  } as unknown as Project;
}

const labelOf = (id: string) =>
  id === ACME ? 'Acme Holdings' : id === OTHER ? 'Example Client Pty Ltd' : id;

describe('buildClientRows', () => {
  it('sums contract value per currency and never blends them', () => {
    const rows = buildClientRows(
      [
        project({ id: 'p1', client_id: ACME, currency: 'AUD', contract_value: '1250000' }),
        project({ id: 'p2', client_id: ACME, currency: 'EUR', contract_value: '900000' }),
        project({ id: 'p3', client_id: ACME, currency: 'AUD', contract_value: '50000', status: 'archived' }),
        // No value / junk value: counted as a project, adds nothing.
        project({ id: 'p4', client_id: ACME, currency: 'AUD', contract_value: 'abc' }),
        project({ id: 'p5', client_id: ACME, currency: 'AUD', contract_value: '' }),
      ],
      labelOf,
    );
    expect(rows).toHaveLength(1);
    const acme = rows[0]!;
    expect(acme.label).toBe('Acme Holdings');
    expect(acme.projects).toBe(5);
    expect(acme.active).toBe(4);
    expect(Array.from(acme.value.entries())).toEqual([
      ['AUD', 1_300_000],
      ['EUR', 900_000],
    ]);
  });

  it('skips projects with no client, keeps legacy free-text ones, sorts by count then name', () => {
    const many = Array.from({ length: 200 }, (_, i) =>
      project({ id: `m${i}`, client_id: OTHER }),
    );
    const rows = buildClientRows(
      [
        project({ id: 'n1', client_id: null }),
        project({ id: 'n2', client_id: '   ' }),
        project({ id: 'l1', client_id: 'Legacy Free Text Co' }),
        project({ id: 'a1', client_id: ACME }),
        ...many,
      ],
      labelOf,
    );
    expect(rows.map((r) => [r.label, r.projects])).toEqual([
      ['Example Client Pty Ltd', 200],
      ['Acme Holdings', 1],
      ['Legacy Free Text Co', 1],
    ]);
    expect(rows[2]!.value.size).toBe(0);
  });
});

describe('compactMoney', () => {
  it('rolls K over to M where rounding would print 1,000K', () => {
    expect(compactMoney(999_600, 'AUD')).toBe('1.0M AUD');
    expect(compactMoney(1_250_000, 'AUD')).toBe('1.3M AUD');
    expect(compactMoney(850_400, 'EUR')).toBe('850K EUR');
    expect(compactMoney(999.6, 'EUR')).toBe('1K EUR');
    expect(compactMoney(940, 'EUR')).toBe('940 EUR');
    expect(compactMoney(940, '')).toBe('940');
  });
});
