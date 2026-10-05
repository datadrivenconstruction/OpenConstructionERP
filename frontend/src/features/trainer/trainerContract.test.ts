// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The frontend half of the trainer contract freeze.
//
// Type-level: the fixtures in __fixtures__/ are object literals assigned to the
// interfaces in types.ts, so `tsc` (run by `npm run build`) checks every field,
// every literal value and every extra key. vitest does not type-check, so the
// runtime half below re-checks the literal values against the same const arrays
// and pins the lock list against the backend's locks.py.
//
// The backend half, backend/tests/unit/trainer/test_trainer_contract_parity.py,
// checks the same fixtures against the Pydantic schemas and these interfaces
// against the schema fields.

import { describe, it, expect } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

import { attemptFailFixture } from './__fixtures__/attemptFail';
import { attemptPassFixture } from './__fixtures__/attemptPass';
import { meFixture } from './__fixtures__/me';
import { readbackFixture } from './__fixtures__/readback';
import { taskFixture } from './__fixtures__/task';
import { BADGE_PREFIX, LOCK_REGISTRY, isBadgeLockId, isKnownLockId, lockKind } from './lockRegistry';
import {
  ANSWER_KINDS,
  ATTEMPT_VERDICTS,
  CHECK_KINDS,
  DIAGNOSIS_KINDS,
  ITEM_SOURCES,
  ITEM_VERDICTS,
  LOCK_KINDS,
  LOCK_STATES,
  OUTSIDE_COURSE_MODES,
  READBACK_STATES,
  TASK_STATUSES,
  VALUE_KINDS,
  WEEK_DAY_STATES,
  type AttemptResult,
} from './types';

// Resolved from the working directory, as Header.titleKeys.test.ts does: vitest
// runs from frontend/, a repo-root runner from the repo root.
const SRC = [resolve(process.cwd(), 'src'), resolve(process.cwd(), 'frontend/src')].find((p) =>
  existsSync(join(p, 'features/trainer/types.ts')),
);
if (!SRC) throw new Error('frontend/src not found from ' + process.cwd());
const REPO = resolve(SRC, '../..');

const LOCKS_PY = join(REPO, 'backend/app/modules/trainer/locks.py');
const COURSE_FIXTURE = join(REPO, 'backend/tests/fixtures/trainer/course_fixture_v1.json');

interface PyLock {
  lockId: string;
  kind: string;
  module: string;
}

function readPythonLocks(): { locks: PyLock[]; badgePrefix: string } {
  const text = readFileSync(LOCKS_PY, 'utf8');
  const locks = [...text.matchAll(/LockSpec\("([^"]+)", "([^"]+)", "([^"]+)"\)/g)].map((m) => ({
    lockId: m[1]!,
    kind: m[2]!,
    module: m[3]!,
  }));
  const prefix = /^BADGE_PREFIX = "([^"]+)"$/m.exec(text);
  return { locks, badgePrefix: prefix?.[1] ?? '' };
}

function expectIn(values: readonly string[], value: string, where: string): void {
  expect(values, `${where}: ${value}`).toContain(value);
}

function checkAttempt(attempt: AttemptResult, where: string): void {
  expectIn(ATTEMPT_VERDICTS, attempt.verdict, `${where}.verdict`);
  expectIn(TASK_STATUSES, attempt.task_status, `${where}.task_status`);
  for (const field of attempt.fields) {
    expectIn(ITEM_SOURCES, field.source, `${where}.fields.source`);
    expectIn(ITEM_VERDICTS, field.verdict, `${where}.fields.verdict`);
    if (field.diagnosis) {
      expectIn(DIAGNOSIS_KINDS, field.diagnosis.kind, `${where}.diagnosis.kind`);
      for (const rel of field.diagnosis.related) expectIn(VALUE_KINDS, rel.kind, `${where}.related.kind`);
    }
  }
  for (const id of attempt.unlocked) expect(isKnownLockId(id), `${where}.unlocked ${id}`).toBe(true);
  expect(attempt.passed_items).toBeLessThanOrEqual(attempt.graded_items);
  expect(attempt.fields).toHaveLength(attempt.graded_items);
}

describe('trainer lock registry matches backend locks.py', () => {
  const py = readPythonLocks();

  it('reads a non-empty list from locks.py (a wrong path would make every check vacuous)', () => {
    expect(py.locks.length).toBeGreaterThanOrEqual(5);
  });

  it('holds the same ids, kinds and modules in the same order', () => {
    const ts = LOCK_REGISTRY.map(({ lockId, kind, module }) => ({ lockId, kind, module }));
    expect(ts).toEqual(py.locks);
  });

  it('uses the same badge prefix', () => {
    expect(BADGE_PREFIX).toBe(py.badgePrefix);
  });

  it('classifies badge ids and refuses unknown ones', () => {
    expect(isKnownLockId('badge:fx-quillmere-1')).toBe(true);
    expect(lockKind('badge:fx-quillmere-1')).toBe('badge');
    expect(isBadgeLockId(BADGE_PREFIX)).toBe(false);
    for (const unknown of ['finance', 'tendering', 'changeorders', 'markups', '']) {
      expect(isKnownLockId(unknown), unknown).toBe(false);
    }
  });

  it('every kind is a declared lock kind', () => {
    for (const entry of LOCK_REGISTRY) expectIn(LOCK_KINDS, entry.kind, entry.lockId);
  });
});

describe('trainer lock registry points at real screens', () => {
  const app = readFileSync(join(SRC, 'app/App.tsx'), 'utf8');
  const nav = readFileSync(join(SRC, 'app/layout/navCatalog.ts'), 'utf8');

  it('every gated route is a route in App.tsx', () => {
    for (const entry of LOCK_REGISTRY) {
      for (const route of entry.routes) {
        expect(app.includes(`path="${route}"`), `${entry.lockId}: ${route}`).toBe(true);
      }
    }
  });

  it('every catalogue row exists in navCatalog.ts', () => {
    for (const entry of LOCK_REGISTRY) {
      if (entry.catalogueRow === null) continue;
      expect(nav.includes(`to: '${entry.catalogueRow}'`), `${entry.lockId}: ${entry.catalogueRow}`).toBe(true);
    }
  });

  it('never gates /markups, which is the PDF markups module', () => {
    for (const entry of LOCK_REGISTRY) {
      for (const route of entry.routes) expect(route.startsWith('/markups')).toBe(false);
      expect(entry.catalogueRow).not.toBe('/markups');
    }
  });

  it('never gates the public bidder link', () => {
    for (const entry of LOCK_REGISTRY) {
      for (const route of entry.routes) expect(route.startsWith('/tendering/bid')).toBe(false);
    }
  });
});

describe('the shared fixture course opens only registered locks', () => {
  const course = JSON.parse(readFileSync(COURSE_FIXTURE, 'utf8')) as { tasks: { id: string; opens: string }[] };

  it('has five tasks', () => {
    expect(course.tasks).toHaveLength(5);
  });

  it('every task opens a known lock id', () => {
    for (const task of course.tasks) expect(isKnownLockId(task.opens), `${task.id}: ${task.opens}`).toBe(true);
  });
});

describe('trainer API fixtures use only declared values', () => {
  it('me', () => {
    for (const task of meFixture.tasks) {
      expectIn(TASK_STATUSES, task.status, `task ${task.id}`);
      expect(isKnownLockId(task.opens), task.opens).toBe(true);
      if (task.status !== 'locked') expect(task.target, `task ${task.id} target`).not.toBeNull();
    }
    for (const unlock of meFixture.unlocks) {
      expectIn(LOCK_STATES, unlock.state, unlock.lock_id);
      expect(lockKind(unlock.lock_id), unlock.lock_id).toBe(unlock.kind);
    }
    expectIn(OUTSIDE_COURSE_MODES, meFixture.nav.outside_course, 'nav');
    for (const day of meFixture.week?.days ?? []) expectIn(WEEK_DAY_STATES, day.state, day.date);
    expect(meFixture.tasks.map((t) => t.n)).toEqual([1, 2, 3, 4, 5]);
  });

  it('task', () => {
    for (const check of taskFixture.checks) expectIn(CHECK_KINDS, check.kind, check.id);
    for (const answer of taskFixture.answers) expectIn(ANSWER_KINDS, answer.kind, answer.name);
    for (const item of taskFixture.readback) expectIn(VALUE_KINDS, item.kind, item.id);
    expect(taskFixture.hints.length).toBeLessThanOrEqual(taskFixture.hints_total);
    if (taskFixture.last_attempt) checkAttempt(taskFixture.last_attempt, 'task.last_attempt');
  });

  it('attempts', () => {
    checkAttempt(attemptPassFixture, 'attemptPass');
    checkAttempt(attemptFailFixture, 'attemptFail');
    expect(attemptPassFixture.verdict).toBe('pass');
    expect(attemptFailFixture.verdict).toBe('fail');
    expect(attemptFailFixture.unlocked).toEqual([]);
  });

  it('readback', () => {
    for (const item of readbackFixture.items) {
      expectIn(READBACK_STATES, item.state, item.id);
      expectIn(VALUE_KINDS, item.kind, item.id);
    }
  });

  it('no fixture carries a field that would leak a graded value', () => {
    const text = JSON.stringify([meFixture, taskFixture, attemptPassFixture, attemptFailFixture, readbackFixture]);
    for (const leak of ['"correct"', '"wrong_value"', '"expected"', '"answer_key"', '"delta"']) {
      expect(text.includes(leak), leak).toBe(false);
    }
  });
});
