// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The parts of the proposal flow that decide what is sent and what is shown,
 * tested without rendering: the list query, error codes and field errors, the
 * editing round trip, and the shared store's two guarantees (newer copy wins,
 * one request per action at a time).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { TFunction } from 'i18next';
import { ApiError } from '@/shared/lib/api';

vi.mock('../api', () => ({
  listChatActions: vi.fn(),
  getChatAction: vi.fn(),
  patchChatAction: vi.fn(),
  applyChatAction: vi.fn(),
  rejectChatAction: vi.fn(),
  applyChatActionsBatch: vi.fn(),
  revertChatAction: vi.fn(),
}));

import * as api from '../api';
import {
  describeFailure,
  describeRequestError,
  readErrorCode,
  readFieldErrors,
  toActionRequestError,
} from '../actionErrors';
import { draftFromValue, isChangedField, parseDraft, sameFieldValue } from '../actionFormat';
import { isChatAction, normalizeActionList, normalizeChatAction, type ActionField } from '../types';
import {
  BATCH_APPLY_LIMIT,
  domainQueryKeys,
  performActionOp,
  performBatchApply,
  useChatActionStore,
} from '../useChatActions';
import { appliedAction, makeAction, makeQueryClient } from './fixtures';

const { buildActionListQuery: realBuild } = await vi.importActual<typeof import('../api')>('../api');

/** Shows which key was asked for and which English fallback came with it. */
const keyT = ((key: string, opts?: { defaultValue?: unknown }) =>
  `${key}|${String(opts?.defaultValue ?? '')}`) as unknown as TFunction;

function field(overrides: Partial<ActionField>): ActionField {
  return { key: 'k', label: 'K', kind: 'text', value: null, before: null, editable: true, required: false, ...overrides };
}

beforeEach(() => {
  useChatActionStore.getState().reset();
  vi.mocked(api.applyChatAction).mockReset();
  vi.mocked(api.getChatAction).mockReset();
  vi.mocked(api.applyChatActionsBatch).mockReset();
});

describe('list query string', () => {
  it('leaves unset filters out entirely', () => {
    // The module is mocked for the hooks; the query builder is pure, so test the real one.
    expect(realBuild({ project_id: 'p-1', limit: 50, offset: 0 })).toBe('?project_id=p-1&limit=50&offset=0');
    expect(realBuild({ status: 'proposed', project_id: undefined })).toBe('?status=proposed');
    expect(realBuild({})).toBe('');
  });

  it('sends several statuses as one comma-separated value', () => {
    expect(realBuild({ status: ['proposed', 'failed'] })).toBe('?status=proposed%2Cfailed');
  });
});

describe('DTO normalisation', () => {
  it('recognises a proposal and fills missing parts', () => {
    expect(isChatAction({ id: 'a', action_type: 'task.create', status: 'proposed' })).toBe(true);
    expect(isChatAction({ id: 'a' })).toBe(false);
    const a = normalizeChatAction({ id: 'a', action_type: 'task.create', status: 'proposed', can_apply: true });
    expect(a.fields).toEqual([]);
    expect(a.payload).toEqual({});
    expect(a.can_edit).toBe(false);
    expect(a.confidence).toBeNull();
  });

  it('never offers a write for an unknown status the server did not allow', () => {
    expect(normalizeChatAction({ id: 'a', action_type: 'x', status: 'weird' }).status).toBe('failed');
  });

  it('reads counts as zero when the server omits them', () => {
    const page = normalizeActionList({ items: [makeAction()], total: 1 });
    expect(page.counts).toEqual({ proposed: 0, applied: 0, rejected: 0, failed: 0, reverted: 0 });
    expect(page.items).toHaveLength(1);
  });
});

describe('refused requests', () => {
  it('reads the machine code from every accepted body shape', () => {
    expect(readErrorCode({ detail: { code: 'locked', message: 'x' } })).toBe('locked');
    expect(readErrorCode({ detail: { error_code: 'target_changed' } })).toBe('target_changed');
    expect(readErrorCode({ code: 'changed_since_apply' })).toBe('changed_since_apply');
    expect(readErrorCode({ detail: 'plain text' })).toBeNull();
  });

  it('reads keyed field errors from the server detail', () => {
    const body = {
      detail: {
        code: 'validation_error',
        message: 'Some values are not valid.',
        message_key: 'erp_chat.action.error.validation_error',
        field_errors: {
          quantity: {
            code: 'must_be_positive',
            message_key: 'erp_chat.action.field_error.must_be_positive',
            message: 'Must be greater than 0.',
          },
        },
      },
    };
    expect(readFieldErrors(body)).toEqual({
      quantity: { message: 'Must be greater than 0.', key: 'erp_chat.action.field_error.must_be_positive' },
    });
  });

  it('reads field errors from FastAPI 422 and from older shapes', () => {
    expect(
      readFieldErrors({ detail: [{ loc: ['body', 'payload', 'quantity'], msg: 'must be greater than 0' }] }),
    ).toEqual({ quantity: { message: 'must be greater than 0', key: null } });
    expect(readFieldErrors({ detail: { code: 'invalid', fields: { due_date: 'in the past' } } })).toEqual({
      due_date: { message: 'in the past', key: null },
    });
    expect(readFieldErrors({ detail: { errors: [{ field: 'title', message: 'required' }] } })).toEqual({
      title: { message: 'required', key: null },
    });
  });

  it('prefers the server sentence key, with its English text as the fallback', () => {
    const keyed = toActionRequestError(
      new ApiError(409, 'This bill of quantities is locked.', {
        detail: {
          code: 'locked',
          message: 'This bill of quantities is locked.',
          message_key: 'erp_chat.action.error.locked',
          params: { boq: 'Main' },
        },
      }),
      'apply',
    );
    expect(keyed.messageKey).toBe('erp_chat.action.error.locked');
    expect(keyed.params).toEqual({ boq: 'Main' });
    expect(describeRequestError(keyed, keyT)).toBe('erp_chat.action.error.locked|This bill of quantities is locked.');

    // Without a server key, a known code gets this build's own sentence.
    const bare = toActionRequestError(new ApiError(409, 'Conflict', { detail: { code: 'locked' } }), 'apply');
    expect(describeRequestError(bare, keyT)).toMatch(/^erp_chat\.action\.request_error\.locked\|/);
  });

  it('explains a failed write by its code, or by the stored reason for a generic one', () => {
    const locked = makeAction({ status: 'failed', error: 'Locked.', error_code: 'locked' });
    expect(describeFailure(locked, keyT)).toBe('erp_chat.action.error.locked|Locked.');
    const domain = makeAction({ status: 'failed', error: 'Position 03.012 no longer exists.', error_code: 'domain_error' });
    expect(describeFailure(domain, keyT)).toBe('Position 03.012 no longer exists.');
  });

  it('keeps the HTTP status next to the code', () => {
    const e = toActionRequestError(new ApiError(409, 'Conflict', { detail: { code: 'locked' } }), 'apply');
    expect(e).toMatchObject({ op: 'apply', status: 409, code: 'locked' });
  });
});

describe('editing round trip', () => {
  it('parses both decimal conventions and keeps the money wire type', () => {
    const qty = field({ kind: 'number', value: 80 });
    expect(parseDraft(qty, '1.234,5')).toEqual({ ok: true, value: 1234.5 });
    expect(parseDraft(qty, '1,234.5')).toEqual({ ok: true, value: 1234.5 });
    expect(parseDraft(qty, 'abc')).toEqual({ ok: false, error: 'number' });

    const rateAsString = field({ kind: 'money', value: '145.50' });
    expect(parseDraft(rateAsString, '150,25')).toEqual({ ok: true, value: '150.25' });
    const rateAsNumber = field({ kind: 'money', value: 145.5 });
    expect(parseDraft(rateAsNumber, '150,25')).toEqual({ ok: true, value: 150.25 });
  });

  it('refuses an empty required field and clears an optional one to null', () => {
    expect(parseDraft(field({ required: true }), '  ')).toEqual({ ok: false, error: 'required' });
    expect(parseDraft(field({ required: false }), '')).toEqual({ ok: true, value: null });
  });

  it('starts a draft from a canonical, ungrouped value', () => {
    expect(draftFromValue(field({ kind: 'number', value: 1234.5 }))).toBe('1234.5');
    expect(draftFromValue(field({ kind: 'money', value: '1234.50' }))).toBe('1234.50');
    expect(draftFromValue(field({ kind: 'date', value: '2026-09-25T00:00:00Z' }))).toBe('2026-09-25');
  });

  it('compares numbers by value, so "80.00" is not a change from 80', () => {
    const qty = field({ kind: 'number' });
    expect(sameFieldValue(qty, '80.00', 80)).toBe(true);
    expect(isChangedField(field({ kind: 'number', before: 80, value: 120 }))).toBe(true);
    expect(isChangedField(field({ kind: 'number', before: '120.0', value: 120 }))).toBe(false);
    expect(isChangedField(field({ kind: 'text', before: null, value: 'new' }))).toBe(false);
  });
});

describe('shared store', () => {
  it('keeps the newer copy and ignores an older snapshot', () => {
    const store = useChatActionStore.getState();
    store.upsert(appliedAction());
    store.upsert(makeAction()); // older transcript snapshot
    expect(useChatActionStore.getState().byId['act-1']?.status).toBe('applied');
    store.upsert(makeAction(), { force: true });
    expect(useChatActionStore.getState().byId['act-1']?.status).toBe('proposed');
  });

  it('does not notify subscribers when nothing is newer', () => {
    const store = useChatActionStore.getState();
    store.upsertMany([makeAction()]);
    const before = useChatActionStore.getState();
    store.upsertMany([makeAction()]);
    expect(useChatActionStore.getState()).toBe(before);
  });
});

describe('one request per action', () => {
  it('sends a second apply only after the first has settled', async () => {
    let resolve!: (a: ReturnType<typeof appliedAction>) => void;
    vi.mocked(api.applyChatAction).mockImplementation(
      () => new Promise((r) => {
        resolve = r;
      }),
    );
    const qc = makeQueryClient();
    const first = performActionOp(qc, 'act-1', 'apply', () => api.applyChatAction('act-1'));
    const second = await performActionOp(qc, 'act-1', 'apply', () => api.applyChatAction('act-1'));
    expect(second).toBeNull();
    expect(api.applyChatAction).toHaveBeenCalledTimes(1);
    expect(useChatActionStore.getState().pending['act-1']).toBe('apply');
    resolve(appliedAction());
    await first;
    expect(useChatActionStore.getState().pending['act-1']).toBeUndefined();
    expect(useChatActionStore.getState().byId['act-1']?.status).toBe('applied');
  });

  it('refreshes the project screens only when something was written', async () => {
    const qc = makeQueryClient();
    const spy = vi.spyOn(qc, 'invalidateQueries');
    vi.mocked(api.applyChatAction).mockResolvedValueOnce(makeAction({ status: 'failed', error: 'x', updated_at: '2026-09-23T10:01:00Z' }));
    await performActionOp(qc, 'act-1', 'apply', () => api.applyChatAction('act-1'));
    expect(spy).toHaveBeenCalledWith({ queryKey: ['erp-chat-actions'] });
    expect(spy).not.toHaveBeenCalledWith({ queryKey: ['boq'] });

    spy.mockClear();
    vi.mocked(api.applyChatAction).mockResolvedValueOnce(appliedAction({ updated_at: '2026-09-23T10:06:00Z' }));
    await performActionOp(qc, 'act-1', 'apply', () => api.applyChatAction('act-1'));
    expect(spy).toHaveBeenCalledWith({ queryKey: ['boq'] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['timeline'] });
  });

  it('re-reads the action after a conflict so the card shows the server truth', async () => {
    const qc = makeQueryClient();
    vi.mocked(api.applyChatAction).mockRejectedValueOnce(
      new ApiError(409, 'Conflict', { detail: { code: 'target_changed' } }),
    );
    vi.mocked(api.getChatAction).mockResolvedValueOnce(makeAction({ updated_at: '2026-09-23T10:02:00Z' }));
    await expect(performActionOp(qc, 'act-1', 'apply', () => api.applyChatAction('act-1'))).rejects.toBeInstanceOf(
      ApiError,
    );
    expect(useChatActionStore.getState().errors['act-1']).toMatchObject({ code: 'target_changed', status: 409 });
    await vi.waitFor(() => expect(api.getChatAction).toHaveBeenCalledWith('act-1'));
  });

  it('applies a batch once and skips ids already in flight', async () => {
    const qc = makeQueryClient();
    useChatActionStore.getState().setPending(['act-2'], 'reject');
    vi.mocked(api.applyChatActionsBatch).mockResolvedValueOnce({ items: [appliedAction()], errors: [] });
    const items = await performBatchApply(qc, ['act-1', 'act-2', 'act-1']);
    expect(api.applyChatActionsBatch).toHaveBeenCalledWith(['act-1']);
    expect(items).toHaveLength(1);
  });

  it('puts a refused id of a batch on its own card and re-reads it', async () => {
    const qc = makeQueryClient();
    vi.mocked(api.applyChatActionsBatch).mockResolvedValueOnce({
      items: [appliedAction({ id: 'act-1' }), makeAction({ id: 'act-2' })],
      errors: [
        {
          id: 'act-2',
          status_code: 409,
          code: 'locked',
          message: 'This bill of quantities is locked.',
          message_key: 'erp_chat.action.error.locked',
        },
      ],
    });
    vi.mocked(api.getChatAction).mockResolvedValueOnce(makeAction({ id: 'act-2', updated_at: '2026-09-23T10:03:00Z' }));
    const items = await performBatchApply(qc, ['act-1', 'act-2']);
    expect(items.map((a) => a.status)).toEqual(['applied', 'proposed']);
    const state = useChatActionStore.getState();
    expect(state.errors['act-1']).toBeUndefined();
    expect(state.errors['act-2']).toMatchObject({
      op: 'apply',
      status: 409,
      code: 'locked',
      messageKey: 'erp_chat.action.error.locked',
      serverMessage: 'This bill of quantities is locked.',
    });
    expect(state.pending).toEqual({});
    await vi.waitFor(() => expect(api.getChatAction).toHaveBeenCalledWith('act-2'));
  });

  it('splits a batch larger than the server takes and keeps what got through', async () => {
    const qc = makeQueryClient();
    const ids = Array.from({ length: BATCH_APPLY_LIMIT + 1 }, (_, i) => `act-${i + 1}`);
    vi.mocked(api.applyChatActionsBatch)
      .mockResolvedValueOnce({ items: [appliedAction({ id: 'act-1' })], errors: [] })
      .mockRejectedValueOnce(new ApiError(503, 'Service Unavailable', null));
    const items = await performBatchApply(qc, ids);
    const calls = vi.mocked(api.applyChatActionsBatch).mock.calls;
    expect(calls).toHaveLength(2);
    expect(calls[0]?.[0]).toHaveLength(BATCH_APPLY_LIMIT);
    expect(calls[1]?.[0]).toEqual([`act-${BATCH_APPLY_LIMIT + 1}`]);
    expect(items.map((a) => a.id)).toEqual(['act-1']);
    // The request that did not get through marks only its own ids.
    const state = useChatActionStore.getState();
    expect(state.errors[`act-${BATCH_APPLY_LIMIT + 1}`]).toMatchObject({ op: 'apply', status: 503 });
    expect(state.errors['act-2']).toBeUndefined();
    expect(state.pending).toEqual({});
  });

  it('rejects a batch when no request got through', async () => {
    const qc = makeQueryClient();
    vi.mocked(api.applyChatActionsBatch).mockRejectedValueOnce(new ApiError(500, 'Server error', null));
    await expect(performBatchApply(qc, ['act-1'])).rejects.toBeInstanceOf(ApiError);
    expect(useChatActionStore.getState().errors['act-1']).toMatchObject({ status: 500 });
  });
});

describe('domain refresh keys', () => {
  it('names the screens of the domain and the audit trail', () => {
    const keys = domainQueryKeys('boq.add_position');
    expect(keys).toContainEqual(['boq']);
    expect(keys).toContainEqual(['timeline']);
    expect(domainQueryKeys('task.create')).toContainEqual(['tasks']);
    expect(domainQueryKeys('punch.create_item')).toContainEqual(['punchlist']);
    expect(domainQueryKeys('unknown.thing')).toEqual([['timeline'], ['activity-feed']]);
  });
});
