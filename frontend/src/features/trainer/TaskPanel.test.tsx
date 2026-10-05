// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The task panel against a small fake of the trainer API: the PUT replaces
// the whole answer set and moves the revision, the check grades and stores
// the attempt, the task GET returns what the fake holds.

import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: unknown) => {
      const o = (typeof opts === 'string' ? { defaultValue: opts } : (opts ?? {})) as Record<string, unknown>;
      const template = typeof o.defaultValue === 'string' ? o.defaultValue : key;
      return template.replace(/\{\{(\w+)\}\}/g, (_, n: string) => String(o[n] ?? ''));
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPut: vi.fn() }));
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

import { ApiError } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { attemptFailFixture } from './__fixtures__/attemptFail';
import { attemptPassFixture } from './__fixtures__/attemptPass';
import { meFixture } from './__fixtures__/me';
import { readbackFixture } from './__fixtures__/readback';
import { taskFixture } from './__fixtures__/task';
import { TaskPanel, buildAnswerSet, TRAINER_RESULT_ID } from './TaskPanel';
import { trainerFieldInputId } from './NumbersCheck';
import type { AnswersPut, AttemptResult, CheckRequest, SavedAnswer, TaskView } from './types';
import { useTrainerUiStore } from './useTrainerUiStore';

const TASK = 't2-markups';
const TARGET = '/boq/7a4c1f0e-2b3d-4e5f-8a9b-0c1d2e3f4a5b';
const FIELD_ID = trainerFieldInputId('t2-numbers', 'overheads_amount');

let client: QueryClient;
let server: { task: TaskView; nextCheck: (body: CheckRequest) => Promise<AttemptResult> };

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}

function failWith(fields: AttemptResult['fields'], rings = attemptFailFixture.rings): AttemptResult {
  return { ...clone(attemptFailFixture), attempt_id: `a-${Math.random()}`, fields, rings };
}

function installServer(task: TaskView) {
  server = { task, nextCheck: async () => clone(attemptFailFixture) };
  api.apiGet.mockImplementation(async (path: string) => {
    if (path === '/system/status') return { academy_mode: true };
    if (path === `/v1/trainer/tasks/${TASK}`) return clone(server.task);
    if (path === `/v1/trainer/tasks/${TASK}/readback`) return clone(readbackFixture);
    throw new Error(`unexpected GET ${path}`);
  });
  api.apiPut.mockImplementation(async (_path: string, body: AnswersPut) => {
    if (body.revision !== server.task.answers_revision) throw new ApiError(409, 'Conflict', { detail: 'stale' });
    const answers: SavedAnswer[] = body.answers
      .filter((a) => a.value_text !== null || a.option_index !== null)
      .map((a) => ({
        name: a.name,
        kind: a.option_index !== null ? 'option' : 'number',
        value_text: a.value_text,
        option_index: a.option_index,
      }));
    server.task = { ...server.task, answers, answers_revision: server.task.answers_revision + 1 };
    return { task_id: TASK, revision: server.task.answers_revision, answers };
  });
  api.apiPost.mockImplementation(async (path: string, body: CheckRequest) => {
    if (path.endsWith('/check')) {
      const result = await server.nextCheck(body);
      server.task = { ...server.task, last_attempt: result, status: result.task_status };
      return result;
    }
    return undefined;
  });
}

function renderPanel(path = TARGET) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <TaskPanel taskId={TASK} me={meFixture} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const field = () => document.getElementById(FIELD_ID) as HTMLInputElement;
const puts = () => api.apiPut.mock.calls as Array<[string, AnswersPut]>;
const checks = () =>
  (api.apiPost.mock.calls as Array<[string, CheckRequest]>).filter(([p]) => p.endsWith('/check'));

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  api.apiGet.mockReset();
  api.apiPost.mockReset();
  api.apiPut.mockReset();
  useAuthStore.setState({ isAuthenticated: true, userId: 'user-a', accessToken: null });
  useTrainerUiStore.getState().reset();
  installServer(clone(taskFixture));
});
afterEach(() => {
  cleanup();
  client.clear();
  useAuthStore.setState({ isAuthenticated: false, userId: null, accessToken: null });
  Object.defineProperty(navigator, 'onLine', { configurable: true, value: true });
});

describe('TaskPanel: what it shows', () => {
  it('shows the brief, the given figures, the saved answer and the last check', async () => {
    renderPanel();
    expect(await screen.findByText(taskFixture.brief)).toBeTruthy();
    expect(screen.getByText('Task 2 · Add overheads and profit')).toBeTruthy();
    expect(screen.getByText('Overheads rate').closest('div')?.textContent).toContain('8%');
    expect(field().value).toBe('2,433.12');
    // The fixture's last attempt failed on the ERP grand total.
    expect(screen.getByTestId('trainer-result-summary').textContent).toBe(
      '2 of 3 figures match. The notes below say what to look at.',
    );
    expect(screen.getByTestId('trainer-diagnosis').textContent).toContain('Profit was charged on the overheads as well.');
    expect(screen.getByTestId('trainer-erp-verdicts').textContent).toContain('Does not match yet');
    expect(screen.getByTestId('trainer-hint-count').textContent).toBe('Hint 1 of 2');
    expect((await screen.findByTestId('trainer-readback-rb0')).getAttribute('data-state')).toBe('mismatch');
    expect(screen.getByTestId('trainer-closes').textContent).toContain('Watch: Markups on direct cost');
  });

  it('sends the learner to the task page when they are somewhere else', async () => {
    renderPanel('/dashboard');
    const banner = await screen.findByTestId('trainer-wrong-place');
    expect(banner.textContent).toContain('This task happens in Bill of Quantities.');
    expect(within(banner).getByRole('link').getAttribute('href')).toBe(`${TARGET}#boq-markups-panel`);
  });

  it('keeps trace and explain back until the numbers are verified', async () => {
    installServer({ ...clone(taskFixture), answers: [clone(taskFixture.answers[0]!)], last_attempt: null });
    renderPanel();
    await screen.findByText(taskFixture.brief);
    expect(screen.queryByTestId('trainer-choice-t2-trace')).toBeNull();
    server.nextCheck = async () =>
      failWith(
        [
          { key: 'overheads_amount', source: 'panel', verdict: 'ok', observed: '2433.12', diagnosis: null, feedback: null },
          { key: 't2-trace', source: 'panel', verdict: 'missing', observed: null, diagnosis: null, feedback: null },
        ],
        { numbers: true, trace: false, explain: false },
      );
    fireEvent.click(screen.getByTestId('trainer-check-submit'));
    expect(await screen.findByTestId('trainer-choice-t2-trace')).toBeTruthy();
    expect(screen.getByTestId('trainer-result-summary').textContent).toBe(
      'Numbers verified. Now answer the questions below.',
    );
    // A question not answered yet shows no "missing" verdict.
    expect(within(screen.getByTestId('trainer-choice-t2-trace')).queryByTestId('trainer-choice-verdict')).toBeNull();
  });

  it('offers "Check my work" when the task has no figures to type', async () => {
    installServer({
      ...clone(taskFixture),
      checks: taskFixture.checks.filter((c) => c.kind !== 'numbers'),
      last_attempt: null,
    });
    renderPanel();
    expect((await screen.findByTestId('trainer-check-submit')).textContent).toBe('Check my work');
    expect(screen.getByTestId('trainer-choice-t2-trace')).toBeTruthy();
  });
});

describe('TaskPanel: checking', () => {
  it('PUTs the whole answer set, then checks the revision that PUT returned', async () => {
    renderPanel();
    await screen.findByText(taskFixture.brief);
    fireEvent.change(field(), { target: { value: '2,500.00' } });
    fireEvent.click(screen.getByTestId('trainer-check-submit'));
    await waitFor(() => expect(checks()).toHaveLength(1));
    const [, body] = puts()[0]!;
    expect(body.revision).toBe(3);
    expect(body.answers).toEqual(
      expect.arrayContaining([
        { name: 'overheads_amount', value_text: '2500.00', option_index: null },
        // Hidden or not, the options already saved go back: the PUT replaces the set.
        { name: 't2-trace', value_text: null, option_index: 0 },
        { name: 't2-explain', value_text: null, option_index: 1 },
      ]),
    );
    const [, check] = checks()[0]!;
    expect(check.revision).toBe(4);
    expect(check.client_attempt_id).toMatch(/^[0-9a-f-]{36}$/);
  });

  it('skips the PUT when nothing changed and checks the revision on screen', async () => {
    renderPanel();
    await screen.findByText(taskFixture.brief);
    fireEvent.click(screen.getByTestId('trainer-check-submit'));
    await waitFor(() => expect(checks()).toHaveLength(1));
    expect(puts()).toHaveLength(0);
    expect(checks()[0]![1].revision).toBe(3);
  });

  it('refuses a malformed number in plain words, sends nothing and puts focus on it', async () => {
    renderPanel();
    await screen.findByText(taskFixture.brief);
    fireEvent.change(field(), { target: { value: '2433,12' } });
    fireEvent.click(screen.getByTestId('trainer-check-submit'));
    expect((await screen.findByTestId('trainer-field-problem')).textContent).toBe(
      'Use a point for decimals in this course',
    );
    await waitFor(() => expect(document.activeElement).toBe(field()));
    expect(puts()).toHaveLength(0);
    expect(checks()).toHaveLength(0);
  });

  it('moves focus to the first figure that failed and announces the result politely', async () => {
    renderPanel();
    await screen.findByText(taskFixture.brief);
    server.nextCheck = async () =>
      failWith([
        {
          key: 'overheads_amount',
          source: 'panel',
          verdict: 'wrong',
          observed: '2500.00',
          diagnosis: { id: 'd-rate', kind: 'error', message: 'Overheads were taken at 8.2 per cent.', related: [] },
          feedback: null,
        },
      ]);
    fireEvent.change(field(), { target: { value: '2500' } });
    fireEvent.click(screen.getByTestId('trainer-check-submit'));
    await waitFor(() => expect(document.activeElement).toBe(field()));
    expect(screen.getByTestId('trainer-field-verdict').textContent).toBe('Does not match yet');
    const live = document.getElementById(TRAINER_RESULT_ID)!;
    expect(live.getAttribute('aria-live')).toBe('polite');
    expect(live.textContent).toContain('0 of 1 figures match');
    expect(live.textContent).toContain('Overheads were taken at 8.2 per cent.');
  });

  it('clears the last check as soon as an answer changes', async () => {
    renderPanel();
    await screen.findByTestId('trainer-diagnosis');
    fireEvent.change(field(), { target: { value: '2433.13' } });
    expect(screen.getByTestId('trainer-result-summary').textContent).toBe(
      'You changed an answer, so the last check no longer counts.',
    );
    expect(screen.queryByTestId('trainer-diagnosis')).toBeNull();
    expect(screen.queryByTestId('trainer-field-verdict')).toBeNull();
  });

  it('on a pass shows the done card, updates the rings and leaves the celebration to the unlock host', async () => {
    renderPanel();
    await screen.findByText(taskFixture.brief);
    server.nextCheck = async () => clone(attemptPassFixture);
    fireEvent.click(screen.getByTestId('trainer-check-submit'));
    const done = await screen.findByTestId('trainer-done');
    expect(done.textContent).toContain('Task 2 verified');
    expect(within(done).getByTestId('trainer-done-open').getAttribute('href')).toBe('/bid-management');
    expect(screen.queryByTestId('trainer-check-form')).toBeNull();
    const closes = screen.getByTestId('trainer-closes');
    expect(closes.querySelectorAll('[data-closed="true"]')).toHaveLength(3);
    await waitFor(() => expect(document.activeElement?.id).toBe(TRAINER_RESULT_ID));
    expect(useTrainerUiStore.getState().celebrated).toEqual([]);
  });

  it('picking an option saves it with the other answers and checks at once', async () => {
    renderPanel();
    await screen.findByTestId('trainer-choice-t2-explain');
    const explain = screen.getByTestId('trainer-choice-t2-explain');
    fireEvent.click(within(explain).getAllByTestId('trainer-choice-option')[0]!);
    await waitFor(() => expect(checks()).toHaveLength(1));
    expect(puts()[0]![1].answers).toEqual(
      expect.arrayContaining([
        { name: 't2-explain', value_text: null, option_index: 0 },
        { name: 'overheads_amount', value_text: '2433.12', option_index: null },
      ]),
    );
  });
  it('reads out the verdict of a wrong pick and keeps focus on the question', async () => {
    renderPanel();
    const explain = await screen.findByTestId('trainer-choice-t2-explain');
    server.nextCheck = async () =>
      failWith(
        [
          { key: 'overheads_amount', source: 'panel', verdict: 'ok', observed: '2433.12', diagnosis: null, feedback: null },
          { key: 't2-explain', source: 'panel', verdict: 'wrong', observed: '2', diagnosis: null, feedback: 'Nothing is counted twice here.' },
        ],
        { numbers: true, trace: true, explain: false },
      );
    fireEvent.click(within(explain).getAllByTestId('trainer-choice-option')[2]!);
    const live = within(screen.getByTestId('trainer-choice-t2-explain')).getByTestId('trainer-choice-live');
    expect(live.getAttribute('aria-live')).toBe('polite');
    await waitFor(() => expect(live.textContent).toContain('Not this one'));
    expect(live.textContent).toContain('Nothing is counted twice here.');
    await waitFor(() => expect(document.activeElement?.id).toBe('oe-trainer-choice-t2-explain'));
  });

  it('a right pick closes the question without dropping focus to the page', async () => {
    renderPanel();
    const explain = await screen.findByTestId('trainer-choice-t2-explain');
    const option = within(explain).getAllByTestId('trainer-choice-option')[0]!;
    option.focus();
    server.nextCheck = async () =>
      failWith(
        [
          { key: 'overheads_amount', source: 'panel', verdict: 'ok', observed: '2433.12', diagnosis: null, feedback: null },
          { key: 't2-explain', source: 'panel', verdict: 'ok', observed: '0', diagnosis: null, feedback: 'Right: 5% of 2433.12.' },
          { key: 'grand_total', source: 'erp', verdict: 'wrong', observed: '34489.48', diagnosis: null, feedback: null },
        ],
        { numbers: false, trace: true, explain: true },
      );
    fireEvent.click(option);
    await waitFor(() =>
      expect(within(screen.getByTestId('trainer-choice-t2-explain')).queryAllByTestId('trainer-choice-option')).toHaveLength(0),
    );
    await waitFor(() => expect(document.activeElement?.id).toBe('oe-trainer-choice-t2-explain'));
    expect(document.activeElement).not.toBe(document.body);
  });
});

describe('TaskPanel: when the check cannot run', () => {
  it('says plainly when the task changed elsewhere (409) and refetches it', async () => {
    renderPanel();
    await screen.findByText(taskFixture.brief);
    const gets = () => api.apiGet.mock.calls.filter(([p]) => p === `/v1/trainer/tasks/${TASK}`).length;
    const before = gets();
    server.nextCheck = async () => {
      throw new ApiError(409, 'Conflict', { detail: 'stale revision' });
    };
    fireEvent.click(screen.getByTestId('trainer-check-submit'));
    const alert = await screen.findByTestId('trainer-check-problem');
    expect(alert.getAttribute('role')).toBe('alert');
    expect(alert.textContent).toContain('Your task changed since this panel opened. We reloaded it');
    await waitFor(() => expect(gets()).toBeGreaterThan(before));
  });

  it('says plainly when the browser is offline and sends nothing', async () => {
    renderPanel();
    await screen.findByText(taskFixture.brief);
    Object.defineProperty(navigator, 'onLine', { configurable: true, value: false });
    fireEvent.change(field(), { target: { value: '2500' } });
    fireEvent.click(screen.getByTestId('trainer-check-submit'));
    const alert = await screen.findByTestId('trainer-check-problem');
    expect(alert.getAttribute('data-problem')).toBe('offline');
    expect(alert.textContent).toContain('You are offline, so nothing was sent.');
    expect(api.apiPut).not.toHaveBeenCalled();
    // The typed answer is still there.
    expect(field().value).toBe('2500');
  });

  it('keeps the answers after a network failure and retries the same press with the same key', async () => {
    renderPanel();
    await screen.findByText(taskFixture.brief);
    let fail = true;
    server.nextCheck = async () => {
      if (fail) {
        fail = false;
        throw new Error('network down');
      }
      return clone(attemptFailFixture);
    };
    fireEvent.change(field(), { target: { value: '2500' } });
    fireEvent.click(screen.getByTestId('trainer-check-submit'));
    const alert = await screen.findByTestId('trainer-check-problem');
    expect(alert.textContent).toContain('The check did not run. Your answers are kept.');
    fireEvent.click(screen.getByTestId('trainer-check-retry'));
    await waitFor(() => expect(checks()).toHaveLength(2));
    expect(checks()[1]![1].client_attempt_id).toBe(checks()[0]![1].client_attempt_id);
    expect(puts()).toHaveLength(1);
  });

  it('a double click is one attempt', async () => {
    renderPanel();
    await screen.findByText(taskFixture.brief);
    const submit = screen.getByTestId('trainer-check-submit');
    fireEvent.click(submit);
    fireEvent.click(submit);
    await waitFor(() => expect(checks()).toHaveLength(1));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(checks()).toHaveLength(1);
  });
});

describe('TaskPanel: the readback follows the learner', () => {
  it('refetches after a BOQ markups query updates, but never after its own trainer queries', async () => {
    renderPanel();
    await screen.findByTestId('trainer-readback-rb0');
    const reads = () => api.apiGet.mock.calls.filter(([p]) => String(p).endsWith('/readback')).length;
    const before = reads();
    act(() => {
      client.setQueryData(['trainer', 'something-else'], { x: 1 });
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 1000));
    });
    expect(reads()).toBe(before);
    act(() => {
      client.setQueryData(['boq-markups', 'b1'], { x: 1 });
    });
    await waitFor(() => expect(reads()).toBe(before + 1), { timeout: 2500 });
  });
});

describe('buildAnswerSet', () => {
  it('lays drafts over every saved answer and never sends an unread string', () => {
    const built = buildAnswerSet(taskFixture, { overheads_amount: 'twelve' }, 'en-GB', null);
    expect(built.problems).toEqual(['overheads_amount']);
    expect(built.answers.find((a) => a.name === 'overheads_amount')?.value_text).toBe('2433.12');
    expect(built.changed).toBe(false);
  });

  it('sends a cleared field as a clear, and only for an answer the server holds', () => {
    const built = buildAnswerSet(taskFixture, { overheads_amount: '' }, 'en-GB', null);
    expect(built.answers.find((a) => a.name === 'overheads_amount')).toEqual({
      name: 'overheads_amount',
      value_text: null,
      option_index: null,
    });
    expect(built.changed).toBe(true);
    const none = buildAnswerSet({ ...taskFixture, answers: [] }, { overheads_amount: '' }, 'en-GB', null);
    expect(none.answers).toEqual([]);
    expect(none.changed).toBe(false);
  });
});
