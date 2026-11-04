import { describe, expect, it, vi } from 'vitest';
import type { QueuedOp } from '@/shared/lib/offline';
import { createFieldSender } from '@/shared/lib/offline/fieldQueue';
import {
  KIND_FIELD_TIME,
  KIND_HAUL,
  KIND_NCR,
  KIND_SAFETY,
  buildHaulOp,
  buildNcrOp,
  buildSafetyOp,
  fieldTimeAsQueueItems,
  kindLabelKey,
  parseTonnes,
  reasonKey,
} from './fieldKinds';

const AT = '2026-11-04T08:00:00.000Z';

describe('op builders', () => {
  it('queues an NCR to the capture route, idempotent on the given id', () => {
    const op = buildNcrOp({ title: ' Cracked slab ', description: '', severity: 'major', capturedAt: AT }, 'op-12345678');
    expect(op.path).toBe('/v1/field-diary/capture/ncr/');
    expect(op.kind).toBe(KIND_NCR);
    expect(op.clientOpId).toBe('op-12345678');
    expect(op.method).toBe('POST');
    // an empty description falls back to the title: the server requires one
    expect((op.body as { description: string }).description).toBe('Cracked slab');
    expect((op.body as { severity: string }).severity).toBe('major');
  });

  it('queues a safety observation with its risk inputs', () => {
    const op = buildSafetyOp(
      { observationType: 'near_miss', description: 'Load swung', severity: 5, likelihood: 3, capturedAt: AT },
      'op-12345678',
    );
    expect(op.kind).toBe(KIND_SAFETY);
    expect(op.body).toMatchObject({ observation_type: 'near_miss', severity: 5, likelihood: 3 });
  });

  it('queues a haul ticket and refuses a weight that is not a number', () => {
    const ok = buildHaulOp(
      { materialName: 'Gravel', netT: '24,5', plate: 'B-XY 1', direction: 'inbound', capturedAt: AT },
      'op-12345678',
    );
    expect(ok?.kind).toBe(KIND_HAUL);
    expect((ok?.body as { net_t: string }).net_t).toBe('24.5');
    expect(
      buildHaulOp({ materialName: 'Gravel', netT: 'lots', plate: '', direction: 'inbound', capturedAt: AT }, 'op-12345678'),
    ).toBeNull();
  });

  it('allows a ticket with no weight yet', () => {
    const op = buildHaulOp({ materialName: 'Sand', netT: '', plate: '', direction: 'inbound', capturedAt: AT }, 'op-12345678');
    expect((op?.body as { net_t?: string }).net_t).toBeUndefined();
  });
});

describe('parseTonnes', () => {
  it('accepts comma decimals and spaces, up to three decimals', () => {
    expect(parseTonnes('1 024,125')).toBe('1024.125');
    expect(parseTonnes('0')).toBe('0');
  });
  it('rejects negatives, text and four decimals', () => {
    expect(parseTonnes('-1')).toBeNull();
    expect(parseTonnes('1.2345')).toBeNull();
    expect(parseTonnes('abc')).toBeNull();
  });
});

describe('labels and reasons', () => {
  it('maps queue kinds to translation keys', () => {
    expect(kindLabelKey(KIND_NCR)).toBe('field.report.kind_ncr');
    expect(kindLabelKey(KIND_FIELD_TIME)).toBe('field.sync_queue.kind_field_time');
    expect(kindLabelKey('field.diary.entry')).toBeNull();
  });
  it('explains the stale-op reason and nothing else', () => {
    expect(reasonKey('op_too_old')).toBe('field.sync_queue.reason_op_too_old');
    expect(reasonKey('other')).toBeNull();
    expect(reasonKey(undefined)).toBeNull();
  });
});

describe('crew time folded into the shared list', () => {
  it('shows crew-time ops as pending or failing items of one kind', () => {
    const ops = [
      { clientOpId: 'a', method: 'POST', path: '/x', kind: 'field_time.entry', queuedAt: 5, retries: 0 },
      { clientOpId: 'b', method: 'POST', path: '/x', kind: 'field_time.withdraw', queuedAt: 6, retries: 2 },
    ] as QueuedOp[];
    const items = fieldTimeAsQueueItems(ops);
    expect(items.map((i) => i.kind)).toEqual([KIND_FIELD_TIME, KIND_FIELD_TIME]);
    expect(items.map((i) => i.status)).toEqual(['pending', 'failing']);
  });
});

describe('field sender', () => {
  const op = { clientOpId: 'op-12345678', method: 'POST', path: '/v1/field-diary/capture/ncr/', body: {}, kind: KIND_NCR } as QueuedOp;
  const reply = (status: number, body: unknown) =>
    vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));

  it('treats a refused capture as a permanent rejection with its reason', async () => {
    vi.stubGlobal('fetch', reply(422, { status: 'rejected', reason_code: 'op_too_old' }));
    const out = await createFieldSender(() => ({}))(op);
    expect(out).toMatchObject({ kind: 'rejected', detail: 'op_too_old' });
    vi.unstubAllGlobals();
  });

  it('reads an applied answer, and does not mistake a batch list for a rejection', async () => {
    vi.stubGlobal('fetch', reply(200, [{ status: 'rejected', reason_code: 'op_too_old' }]));
    expect((await createFieldSender(() => ({}))(op)).kind).toBe('applied'); // a list is not a single capture answer
    vi.stubGlobal('fetch', reply(201, { status: 'applied', result_id: 'r1' }));
    expect(await createFieldSender(() => ({}))(op)).toMatchObject({ kind: 'applied', resultId: 'r1' });
    vi.unstubAllGlobals();
  });
});
