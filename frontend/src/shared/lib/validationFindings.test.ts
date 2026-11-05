import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useToastStore } from '@/stores/useToastStore';
import { ApiError, apiGet, apiPost, extractErrorMessageFromBody } from './api';
import { findingText, joinFindings, surfaceValidationWarnings } from './validationFindings';

const catalogue: Record<string, string> = { 'api_errors.demo_rule': 'Cost {{cost}} exceeds the budget.' };

vi.mock('i18next', () => ({
  default: {
    on: () => {},
    language: 'en',
    exists: (k: string) => k in catalogue,
    t: (k: string, o?: Record<string, unknown>) =>
      (catalogue[k] ?? (o?.defaultValue as string) ?? k).replace(/\{\{(\w+)\}\}/g, (_m, n) => String(o?.[n])),
  },
}));

beforeEach(() => {
  vi.unstubAllGlobals();
  useToastStore.setState({ toasts: [], history: [] });
});

describe('findingText', () => {
  it('uses the catalogue text filled from params when the code is known', () => {
    expect(findingText({ code: 'demo_rule', message: 'raw', params: { cost: 5 } })).toBe('Cost 5 exceeds the budget.');
  });
  it('falls back to the message, never the bare code', () => {
    expect(findingText({ code: 'boq.unknown_rule', message: 'Quantity must be positive.' })).toBe('Quantity must be positive.');
    expect(findingText({ code: 'boq.unknown_rule' })).toBeNull();
  });
});

describe('joinFindings', () => {
  it('caps the list at three and counts the rest', () => {
    const f = ['a', 'b', 'c', 'd', 'e'].map((m) => ({ message: m }));
    expect(joinFindings(f)).toBe('a; b; c (+2)');
  });
});

describe('surfaceValidationWarnings', () => {
  it('raises one non-blocking warning toast with the finding texts', () => {
    surfaceValidationWarnings({ id: 1, validation_warnings: [{ code: 'demo_rule', params: { cost: 9 } }, { message: 'Check unit.' }] });
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0]).toMatchObject({ type: 'warning', title: 'Saved with warnings', message: 'Cost 9 exceeds the budget.; Check unit.' });
  });
  it('stays silent without warnings', () => {
    surfaceValidationWarnings({ validation_warnings: [] });
    surfaceValidationWarnings({ id: 1 });
    surfaceValidationWarnings(null);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });
});

describe('rule 422 body', () => {
  const detail = {
    error: 'boq_rule_failed',
    code: 'boq.unknown_rule',
    message: 'first; second (+1)',
    errors: [{ code: 'demo_rule', params: { cost: 7 } }, { code: 'x.y', message: 'Second problem.' }],
  };
  it('shows each blocking finding as a message, not the key or a generic failure', () => {
    expect(extractErrorMessageFromBody({ detail })).toBe('Cost 7 exceeds the budget.; Second problem.');
    expect(new ApiError(422, 'Unprocessable', { detail }).message).toBe('Cost 7 exceeds the budget.; Second problem.');
  });
  it('still uses detail.message when there is no errors list', () => {
    expect(extractErrorMessageFromBody({ detail: { error: 'e', message: 'Plain.' } })).toBe('Plain.');
  });
});

describe('through the request layer', () => {
  const reply = (body: unknown, status = 200) =>
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })),
    );
  const body = { id: 'r1', validation_warnings: [{ rule_id: 'x.y', code: 'x.y', message: 'Check unit.', params: {} }] };

  it('a successful write still resolves and raises one warning toast', async () => {
    reply(body);
    await expect(apiPost('/v1/things/', { a: 1 })).resolves.toMatchObject({ id: 'r1' });
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0]).toMatchObject({ type: 'warning', message: 'Check unit.' });
  });
  it('a read never toasts', async () => {
    reply(body);
    await apiGet('/v1/things/r1');
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });
  it('a pydantic 422 keeps its field message', async () => {
    reply({ detail: [{ loc: ['body', 'name'], msg: 'Field required' }] }, 422);
    await expect(apiPost('/v1/things/', {})).rejects.toMatchObject({ message: 'name: Field required' });
  });
});
