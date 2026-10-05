// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Pins the method and the exact path of every trainer call. The app runs with
// `redirect_slashes=False`, so a path that drifts by one slash is a 404; this
// is the only test that sees it.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPut: vi.fn() }));
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

import { ApiError } from '@/shared/lib/api';
import {
  TRAINER_PATHS,
  TrainerOfflineError,
  fetchPublicStatus,
  fetchTrainerMe,
  fetchTrainerReadback,
  fetchTrainerTask,
  newClientAttemptId,
  numberAnswer,
  optionAnswer,
  postRevealHint,
  postTrainerCheck,
  postUnlockSeen,
  putTrainerAnswers,
  trainerErrorStatus,
} from './api';
import { attemptPassFixture } from './__fixtures__/attemptPass';
import { meFixture } from './__fixtures__/me';
import { taskFixture } from './__fixtures__/task';

beforeEach(() => {
  api.apiGet.mockReset();
  api.apiPost.mockReset();
  api.apiPut.mockReset();
});

describe('trainer API paths', () => {
  it('reads the public flag from /v1/trainer/public/status/ (trailing slash)', async () => {
    api.apiGet.mockResolvedValue({ academy_mode: true, store_url: null });
    await fetchPublicStatus();
    expect(api.apiGet).toHaveBeenCalledWith('/v1/trainer/public/status/');
  });

  it('reads the enrolment from /v1/trainer/me (no trailing slash)', async () => {
    api.apiGet.mockResolvedValue(meFixture);
    await expect(fetchTrainerMe()).resolves.toBe(meFixture);
    expect(api.apiGet).toHaveBeenCalledWith('/v1/trainer/me');
  });

  it('reads a task, its readback, and encodes the id', async () => {
    api.apiGet.mockResolvedValue(taskFixture);
    await fetchTrainerTask('t2-markups');
    expect(api.apiGet).toHaveBeenLastCalledWith('/v1/trainer/tasks/t2-markups');
    await fetchTrainerReadback('t2 markups/x');
    expect(api.apiGet).toHaveBeenLastCalledWith('/v1/trainer/tasks/t2%20markups%2Fx/readback');
  });

  it('PUTs answers with the revision', async () => {
    const saved = { task_id: 't2-markups', revision: 4, answers: [] };
    api.apiPut.mockResolvedValue(saved);
    const body = { answers: [numberAnswer({ key: 'overheads_amount' }, '3581310.00')], revision: 3 };
    await expect(putTrainerAnswers('t2-markups', body)).resolves.toBe(saved);
    expect(api.apiPut).toHaveBeenCalledWith('/v1/trainer/tasks/t2-markups/answers', body);
  });

  it('POSTs the check with only the idempotency key and the revision', async () => {
    api.apiPost.mockResolvedValue(attemptPassFixture);
    const body = { client_attempt_id: 'a-1', revision: 4 };
    await expect(postTrainerCheck('t2-markups', body)).resolves.toBe(attemptPassFixture);
    expect(api.apiPost).toHaveBeenCalledWith('/v1/trainer/tasks/t2-markups/check', body);
  });

  it('POSTs hint reveal and unlock seen without a body', async () => {
    api.apiPost.mockResolvedValue(undefined);
    await postRevealHint('t2-markups');
    expect(api.apiPost).toHaveBeenLastCalledWith('/v1/trainer/tasks/t2-markups/hints/reveal');
    await postUnlockSeen('badge:fx-quillmere-1');
    expect(api.apiPost).toHaveBeenLastCalledWith('/v1/trainer/unlocks/badge%3Afx-quillmere-1/seen');
  });

  it('every path is under /v1/trainer/', () => {
    const paths = [
      TRAINER_PATHS.publicStatus,
      TRAINER_PATHS.me,
      TRAINER_PATHS.task('x'),
      TRAINER_PATHS.answers('x'),
      TRAINER_PATHS.check('x'),
      TRAINER_PATHS.readback('x'),
      TRAINER_PATHS.revealHint('x'),
      TRAINER_PATHS.unlockSeen('x'),
    ];
    for (const path of paths) expect(path.startsWith('/v1/trainer/')).toBe(true);
  });
});

describe('the paths match the endpoint table in schemas.py', () => {
  const SRC = [resolve(process.cwd(), 'src'), resolve(process.cwd(), 'frontend/src')].find((p) =>
    existsSync(join(p, 'features/trainer')),
  ) as string;
  const schemas = readFileSync(resolve(SRC, '../../backend/app/modules/trainer/schemas.py'), 'utf8');
  const table = new Set(Array.from(schemas.matchAll(/^(?:GET|PUT|POST)\s+``([^`]+)``/gm), (m) => m[1]));

  it('finds the table (a wrong path would make the check vacuous)', () => {
    expect(table.size).toBeGreaterThanOrEqual(7);
  });

  it.each([
    ['publicStatus', TRAINER_PATHS.publicStatus, '/public/status/'],
    ['me', TRAINER_PATHS.me, '/me'],
    ['task', TRAINER_PATHS.task('{task_id}'), '/tasks/{task_id}'],
    ['answers', TRAINER_PATHS.answers('{task_id}'), '/tasks/{task_id}/answers'],
    ['check', TRAINER_PATHS.check('{task_id}'), '/tasks/{task_id}/check'],
    ['readback', TRAINER_PATHS.readback('{task_id}'), '/tasks/{task_id}/readback'],
    ['unlockSeen', TRAINER_PATHS.unlockSeen('{lock_id}'), '/unlocks/{lock_id}/seen'],
  ])('%s', (_name, built, documented) => {
    expect(table.has(documented)).toBe(true);
    expect(decodeURIComponent(built)).toBe(`/v1/trainer${documented}`);
  });
});

describe('trainer API failure handling', () => {
  it('reads a 404 on /me as "no enrolment"', async () => {
    api.apiGet.mockRejectedValue(new ApiError(404, 'Not Found', { detail: 'no enrolment' }));
    await expect(fetchTrainerMe()).resolves.toBeNull();
  });

  it('rethrows every other /me failure', async () => {
    api.apiGet.mockRejectedValue(new ApiError(503, 'Service Unavailable', undefined));
    await expect(fetchTrainerMe()).rejects.toBeInstanceOf(ApiError);
    api.apiGet.mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(fetchTrainerMe()).rejects.toBeInstanceOf(TypeError);
  });

  it('refuses a write that api.ts queued offline (undefined body)', async () => {
    api.apiPost.mockResolvedValue(undefined);
    await expect(postTrainerCheck('t2-markups', { client_attempt_id: 'a', revision: 1 })).rejects.toBeInstanceOf(
      TrainerOfflineError,
    );
    api.apiPut.mockResolvedValue(undefined);
    await expect(putTrainerAnswers('t2-markups', { answers: [], revision: 1 })).rejects.toBeInstanceOf(
      TrainerOfflineError,
    );
  });

  it('never hands an offline write to api.ts, which would queue it for replay', async () => {
    const onLine = vi.spyOn(navigator, 'onLine', 'get').mockReturnValue(false);
    try {
      await expect(putTrainerAnswers('t2-markups', { answers: [], revision: 1 })).rejects.toBeInstanceOf(
        TrainerOfflineError,
      );
      await expect(postTrainerCheck('t2-markups', { client_attempt_id: 'a', revision: 1 })).rejects.toBeInstanceOf(
        TrainerOfflineError,
      );
      expect(api.apiPut).not.toHaveBeenCalled();
      expect(api.apiPost).not.toHaveBeenCalled();
    } finally {
      onLine.mockRestore();
    }
  });

  it('exposes the HTTP status of a failure, null for a network error', () => {
    expect(trainerErrorStatus(new ApiError(409, 'Conflict', undefined))).toBe(409);
    expect(trainerErrorStatus(new Error('x'))).toBeNull();
  });
});

describe('answer builders', () => {
  it('names a number answer by the field key', () => {
    expect(numberAnswer({ key: 'overheads_amount' }, '12.50')).toEqual({
      name: 'overheads_amount',
      value_text: '12.50',
      option_index: null,
    });
  });

  it('names an option answer by the check id', () => {
    expect(optionAnswer({ id: 't2-trace' }, 2)).toEqual({ name: 't2-trace', value_text: null, option_index: 2 });
  });

  it('makes a fresh UUID per attempt', () => {
    const a = newClientAttemptId();
    const b = newClientAttemptId();
    expect(a).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(a).not.toBe(b);
  });
});
