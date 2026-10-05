// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The body of the task dock (frontend design §4, TaskPanel), after
// Task.dc.html: the dark brief card, the given figures, the steps, hints, the
// checks, the result, what the app shows now, the rings the task closes and
// the watch link.
//
// One press checks the whole task. The check grades what is SAVED, so a press
// first PUTs the task's whole answer set (decision 28: the PUT replaces it, so
// the body is every saved answer with the learner's edits laid over it, hidden
// questions included) and then POSTs the check with the revision that PUT
// returned (decision 29). The idempotency key is made once per answer set and
// reused when the same press is retried, so a double click or a retry after a
// dropped response is one attempt. A 409 (the task moved on, or the answers
// changed elsewhere) refetches and says so; offline is said plainly, and the
// typed answers stay where they are in every failure.
//
// Trace and explain questions appear once the numbers are verified (or the
// learner already answered one): in Task.dc.html the trace options name the
// base and the figure, and shown first they would give the numbers away. Once
// shown they stay, even if a later edit reopens the numbers. Picking an option
// saves and checks at once, like the mockup.
//
// The result goes to one polite live region; focus moves to the first figure
// that failed, or to the result when the failure is in the project itself.
// A pass refreshes `/me`, so the rings on the map and in the header follow.
// The unlock celebration is not shown here: UnlockHost (stream C) shows it
// from `/me.unlocks`, and only that host calls `markCelebrated`.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { Check, CircleCheck, Loader2, PlayCircle, Info, MapPin } from 'lucide-react';

import { ErrorState } from '@/shared/ui/ErrorState';
import { Skeleton } from '@/shared/ui/Skeleton';

import { TrainerOfflineError, newClientAttemptId, numberAnswer, optionAnswer, trainerErrorStatus } from './api';
import { ChoiceCheck, trainerChoiceHeadingId } from './ChoiceCheck';
import { courseDir, courseLanguageName, courseLocaleOf, sameLanguage } from './courseLocale';
import { formatCourseNumber, formatCourseValue, renderCourseText } from './courseText';
import { Diagnosis } from './Diagnosis';
import { HintStepper } from './HintStepper';
import { getLock, isBadgeLockId } from './lockRegistry';
import { NumbersCheck, readTypedValue, trainerFieldInputId } from './NumbersCheck';
import {
  trainerKeys,
  useCheckTrainerTask,
  useSaveTrainerAnswers,
  useTrainerReadback,
  useTrainerTask,
} from './queries';
import { ReadbackList } from './ReadbackList';
import { COURSE_MAP_ROUTE, matchesRoutePattern } from './routeMatch';
import type {
  AnswerIn,
  AttemptResult,
  CheckField,
  ChoiceCheckView,
  FieldResult,
  NumbersCheckView,
  RingId,
  SavedAnswer,
  TaskSummary,
  TaskView,
  TrainerMe,
} from './types';
import { useTrainerUiStore } from './useTrainerUiStore';

import './trainer.css';

export const TRAINER_RESULT_ID = 'oe-trainer-result';

/**
 * Query-key heads whose successful refetch means the learner may have changed
 * what a readback probe reads. Never `trainer`, or the readback would refetch
 * itself in a loop.
 */
export const READBACK_TRIGGER_PREFIXES: ReadonlySet<string> = new Set([
  'boq',
  'boqs',
  'boq-markups',
  'contracts',
  'variations',
  'bid-management',
]);

const READBACK_DEBOUNCE_MS = 800;

/**
 * Refetch the readback 800ms after the learner's edits land elsewhere in the
 * app (a BOQ, contracts, variations or bid-management query refetches), so
 * the panel follows the project without polling and without touching module
 * code.
 */
export function useReadbackFollowsEdits(taskId: string): void {
  const qc = useQueryClient();
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const unsubscribe = qc.getQueryCache().subscribe((event) => {
      if (event.type !== 'updated' || event.action.type !== 'success') return;
      const head = event.query.queryKey[0];
      if (typeof head !== 'string' || !READBACK_TRIGGER_PREFIXES.has(head)) return;
      if (timer !== undefined) clearTimeout(timer);
      timer = setTimeout(() => {
        void qc.invalidateQueries({ queryKey: trainerKeys.readback(taskId) });
      }, READBACK_DEBOUNCE_MS);
    });
    return () => {
      unsubscribe();
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [qc, taskId]);
}

/** The module's name in the UI language, through literal keys only. */
export function trainerModuleLabel(t: TFunction, module: string): string {
  switch (module) {
    case 'boq':
      return t('boq.title', { defaultValue: 'Bill of Quantities' });
    case 'bid_management':
      return t('nav.bid_management', { defaultValue: 'Bid Management' });
    case 'contracts':
      return t('nav.contracts', { defaultValue: 'Contracts' });
    case 'variations':
      return t('nav.variations', { defaultValue: 'Variations' });
    default:
      return t('trainer.panel.task_page', { defaultValue: 'the task page' });
  }
}

function savedToIn(answer: SavedAnswer): AnswerIn {
  return { name: answer.name, value_text: answer.value_text, option_index: answer.option_index };
}

/** The text a saved answer shows in its field, in the course locale. */
function savedFieldText(answer: SavedAnswer | undefined, field: CheckField, courseLocale: string): string {
  if (!answer || answer.value_text === null) return '';
  if (field.kind === 'money' || field.kind === 'percent' || field.kind === 'number') {
    return formatCourseNumber(answer.value_text, courseLocale);
  }
  return answer.value_text;
}

export interface BuiltAnswers {
  answers: AnswerIn[];
  /** True when the set differs from what the server holds. */
  changed: boolean;
  /** Field keys whose text does not read, in field order. */
  problems: string[];
  /** The draft texts that went into the set, to clear once saved. */
  sentDrafts: Record<string, string>;
}

/**
 * The whole answer set for the PUT: every saved answer, the learner's drafts
 * over it, and the option just picked. Never sends an unread string.
 */
export function buildAnswerSet(
  task: Pick<TaskView, 'answers' | 'checks'>,
  drafts: Record<string, string>,
  courseLocale: string,
  pick: { check: ChoiceCheckView; index: number } | null,
): BuiltAnswers {
  const saved = new Map(task.answers.map((a) => [a.name, a]));
  const out = new Map<string, AnswerIn>(task.answers.map((a) => [a.name, savedToIn(a)]));
  const problems: string[] = [];
  const sentDrafts: Record<string, string> = {};
  let changed = false;
  for (const check of task.checks) {
    if (check.kind !== 'numbers') continue;
    for (const field of check.fields) {
      if (!(field.key in drafts)) continue;
      const text = drafts[field.key] ?? '';
      const typed = readTypedValue(text, field.kind, courseLocale);
      if (typed.status === 'error') {
        problems.push(field.key);
        continue;
      }
      const valueText = typed.status === 'ok' ? typed.value : null;
      const before = saved.get(field.key);
      sentDrafts[field.key] = text;
      if (valueText === null && !before) continue;
      if ((before?.value_text ?? null) !== valueText) changed = true;
      out.set(field.key, numberAnswer(field, valueText));
    }
  }
  if (pick) {
    if ((saved.get(pick.check.id)?.option_index ?? null) !== pick.index) changed = true;
    out.set(pick.check.id, optionAnswer(pick.check, pick.index));
  }
  return { answers: [...out.values()], changed, problems, sentDrafts };
}

type Problem = 'stale' | 'offline' | 'error' | null;

export interface TaskPanelProps {
  taskId: string;
  me: TrainerMe;
}

export function TaskPanel({ taskId, me }: TaskPanelProps) {
  const { t, i18n } = useTranslation();
  const location = useLocation();
  const uiLocale = i18n.language || 'en';
  const courseLocale = courseLocaleOf(me.course);
  const currency = me.course.currency;
  const dir = courseDir(courseLocale);
  const summary: TaskSummary | null = me.tasks.find((s) => s.id === taskId) ?? null;

  const taskQ = useTrainerTask(taskId);
  const readbackQ = useTrainerReadback(taskId);
  useReadbackFollowsEdits(taskId);
  const save = useSaveTrainerAnswers(taskId);
  const check = useCheckTrainerTask(taskId);
  const drafts = useTrainerUiStore((s) => s.drafts[taskId]);
  const setDraft = useTrainerUiStore((s) => s.setDraft);
  const clearDraft = useTrainerUiStore((s) => s.clearDraft);

  const task = taskQ.data;
  const attempt: AttemptResult | null = task?.last_attempt ?? null;

  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<Problem>(null);
  const [showAllProblems, setShowAllProblems] = useState(false);
  const [pendingChoice, setPendingChoice] = useState<{ checkId: string; index: number } | null>(null);
  // Fields edited since the attempt on screen: its verdicts no longer count.
  const [edited, setEdited] = useState<{ attemptId: string | null; keys: string[] }>({ attemptId: null, keys: [] });
  const [choicesShown, setChoicesShown] = useState(false);
  const [focusRequest, setFocusRequest] = useState<{ id: string; seq: number } | null>(null);
  const busyRef = useRef(false);
  const attemptKeyRef = useRef<{ id: string; fingerprint: string } | null>(null);

  const numbersChecks = useMemo(
    () => (task?.checks ?? []).filter((c): c is NumbersCheckView => c.kind === 'numbers'),
    [task],
  );
  const choiceChecks = useMemo(
    () => (task?.checks ?? []).filter((c): c is ChoiceCheckView => c.kind !== 'numbers'),
    [task],
  );
  const choiceIds = useMemo(() => new Set(choiceChecks.map((c) => c.id)), [choiceChecks]);
  const numberFields = useMemo(() => numbersChecks.flatMap((c) => c.fields.map((f) => ({ check: c, field: f }))), [
    numbersChecks,
  ]);

  const attemptId = attempt?.attempt_id ?? null;
  const editedKeys = edited.attemptId === attemptId ? edited.keys : [];
  const cleared = editedKeys.length > 0 && attempt !== null;
  const passed = task?.status === 'passed';
  const numbersOk = passed || attempt?.rings.numbers === true;
  const anyOptionSaved = (task?.answers ?? []).some((a) => a.kind === 'option' && choiceIds.has(a.name));
  const revealChoices = numbersChecks.length === 0 || numbersOk || anyOptionSaved;

  useEffect(() => {
    if (revealChoices && choiceChecks.length > 0 && !choicesShown) setChoicesShown(true);
  }, [revealChoices, choiceChecks.length, choicesShown]);

  // Move focus once the result is on screen.
  useEffect(() => {
    if (!focusRequest) return;
    const el = document.getElementById(focusRequest.id);
    if (el) el.focus({ preventScroll: false });
  }, [focusRequest]);

  const onFieldChange = useCallback(
    (key: string, text: string) => {
      setDraft(taskId, key, text);
      setProblem(null);
      if (attemptId !== null) {
        setEdited((prev) => {
          const keys = prev.attemptId === attemptId ? prev.keys : [];
          return keys.includes(key) ? prev : { attemptId, keys: [...keys, key] };
        });
      }
    },
    [setDraft, taskId, attemptId],
  );

  const resultFocusTarget = useCallback(
    (result: AttemptResult): string => {
      if (result.verdict === 'pass') return TRAINER_RESULT_ID;
      for (const { check: c, field } of numberFields) {
        const r = result.fields.find((f) => f.key === field.key && f.source === 'panel');
        if (r && r.verdict !== 'ok') return trainerFieldInputId(c.id, field.key);
      }
      return TRAINER_RESULT_ID;
    },
    [numberFields],
  );

  const runCheck = useCallback(
    async (pick: { check: ChoiceCheckView; index: number } | null) => {
      if (!task || busyRef.current) return;
      const built = buildAnswerSet(task, drafts ?? {}, courseLocale, pick);
      if (built.problems.length > 0) {
        setShowAllProblems(true);
        const first = numberFields.find((nf) => nf.field.key === built.problems[0]);
        if (first) setFocusRequest({ id: trainerFieldInputId(first.check.id, first.field.key), seq: Date.now() });
        return;
      }
      busyRef.current = true;
      setBusy(true);
      setProblem(null);
      if (pick) setPendingChoice({ checkId: pick.check.id, index: pick.index });
      // One key per answer set: a retry of the same press reuses it.
      const fingerprint = JSON.stringify(
        [...built.answers].sort((a, b) => a.name.localeCompare(b.name)).map((a) => [a.name, a.value_text, a.option_index]),
      );
      if (attemptKeyRef.current?.fingerprint !== fingerprint) {
        attemptKeyRef.current = { id: newClientAttemptId(), fingerprint };
      }
      try {
        let revision = task.answers_revision;
        if (built.changed && built.answers.length > 0) {
          const saved = await save.mutateAsync({ answers: built.answers, revision });
          revision = saved.revision;
          const now = useTrainerUiStore.getState().drafts[taskId] ?? {};
          for (const [key, text] of Object.entries(built.sentDrafts)) {
            if (now[key] === text) clearDraft(taskId, key);
          }
        }
        const result = await check.mutateAsync({ client_attempt_id: attemptKeyRef.current.id, revision });
        attemptKeyRef.current = null;
        setShowAllProblems(false);
        // A pick keeps the learner on its question: a right pick turns the
        // option buttons into a list, and focus must not fall to <body>.
        setFocusRequest({
          id: pick && result.verdict !== 'pass' ? trainerChoiceHeadingId(pick.check.id) : resultFocusTarget(result),
          seq: Date.now(),
        });
      } catch (error) {
        if (error instanceof TrainerOfflineError) {
          setProblem('offline');
        } else if (trainerErrorStatus(error) === 409) {
          // The queries already refetch the task and /me; the next press gets a fresh key.
          attemptKeyRef.current = null;
          setProblem('stale');
        } else {
          setProblem('error');
        }
      } finally {
        busyRef.current = false;
        setBusy(false);
        setPendingChoice(null);
      }
    },
    [task, drafts, courseLocale, numberFields, save, check, taskId, clearDraft, resultFocusTarget],
  );

  // ── Early states (every hook is above this line) ──────────────────────────

  if (taskQ.isPending) {
    return (
      <div className="flex flex-col gap-3 p-4" aria-busy="true" data-testid="trainer-panel-loading">
        <span className="sr-only">{t('trainer.state.loading', { defaultValue: 'Loading your course' })}</span>
        <Skeleton height={140} rounded="lg" />
        <Skeleton height={96} rounded="lg" />
        <Skeleton height={64} rounded="lg" />
      </div>
    );
  }
  if (taskQ.isError || !task) {
    if (trainerErrorStatus(taskQ.error) === 404) {
      return (
        <div className="flex flex-col gap-3 p-4" data-testid="trainer-panel-missing">
          <p className="m-0 text-sm text-content-primary">
            {t('trainer.state.task_missing', { defaultValue: 'This task is not in your course any more.' })}
          </p>
          <Link
            to={COURSE_MAP_ROUTE}
            className="inline-flex min-h-[44px] items-center self-start rounded-full bg-oe-blue px-5 text-sm font-semibold text-white"
          >
            {t('trainer.nav.course_map', { defaultValue: 'Course map' })}
          </Link>
        </div>
      );
    }
    return (
      <div className="p-4" data-testid="trainer-panel-error">
        <ErrorState
          title={t('trainer.state.error_title', { defaultValue: 'Your course did not load' })}
          hint={t('trainer.state.error_hint', { defaultValue: 'Nothing you entered is lost. Try again in a moment.' })}
          onRetry={() => void taskQ.refetch()}
        />
      </div>
    );
  }

  // ── Derived view ───────────────────────────────────────────────────────────

  const savedByName = new Map(task.answers.map((a) => [a.name, a]));
  const fieldValues: Record<string, string> = {};
  for (const { field } of numberFields) {
    fieldValues[field.key] = drafts?.[field.key] ?? savedFieldText(savedByName.get(field.key), field, courseLocale);
  }
  const shownAttempt = attempt && !cleared ? attempt : null;
  const panelVerdicts: Record<string, FieldResult['verdict'] | undefined> = {};
  if (shownAttempt) {
    for (const { field } of numberFields) {
      const r = shownAttempt.fields.find((f) => f.key === field.key && f.source === 'panel');
      if (r) panelVerdicts[field.key] = r.verdict;
    }
  }
  const fieldLabels = new Map(numberFields.map(({ field }) => [field.key, field.label]));
  const readbackLabels = new Map(task.readback.map((r) => [r.id, r]));
  // Items about the numbers (not trace or explain), the ones the summary counts.
  const numberItems = shownAttempt ? shownAttempt.fields.filter((f) => !choiceIds.has(f.key)) : [];
  const erpItems = numberItems.filter((f) => f.source === 'erp');
  const diagnosed = numberItems.filter((f) => f.diagnosis !== null);
  const unansweredChoices = choiceChecks.filter((c) => savedByName.get(c.id)?.option_index == null);

  const subjectOf = (key: string): string | null =>
    readbackLabels.get(key)?.what ?? fieldLabels.get(key) ?? null;

  // The live summary: one sentence, polite, only when something changed.
  let summaryText = '';
  if (busy) {
    summaryText = t('trainer.check.checking', { defaultValue: 'Checking…' });
  } else if (cleared) {
    summaryText = t('trainer.check.cleared', {
      defaultValue: 'You changed an answer, so the last check no longer counts.',
    });
  } else if (shownAttempt) {
    if (shownAttempt.verdict === 'pass') {
      summaryText = t('trainer.done.title', { defaultValue: 'Task {{n}} verified', n: task.n });
    } else if (numbersOk) {
      summaryText =
        unansweredChoices.length > 0 && choiceChecks.length > 0
          ? t('trainer.check.now_questions', { defaultValue: 'Numbers verified. Now answer the questions below.' })
          : t('trainer.check.all_ok', { defaultValue: 'Numbers verified' });
    } else {
      summaryText = t('trainer.check.summary_fail', {
        defaultValue: '{{passed}} of {{total}} figures match. The notes below say what to look at.',
        passed: numberItems.filter((f) => f.verdict === 'ok').length,
        total: numberItems.length,
      });
    }
  }

  const ringRows: Array<{ id: RingId; label: string }> = [];
  if (numbersChecks.length > 0 || task.readback.length > 0) {
    ringRows.push({ id: 'numbers', label: t('trainer.rings.numbers', { defaultValue: 'Numbers' }) });
  }
  if (choiceChecks.some((c) => c.kind === 'trace')) {
    ringRows.push({ id: 'trace', label: t('trainer.rings.trace', { defaultValue: 'Trace' }) });
  }
  if (choiceChecks.some((c) => c.kind === 'explain')) {
    ringRows.push({ id: 'explain', label: t('trainer.rings.explain', { defaultValue: 'Explain' }) });
  }
  const ringState = attempt?.rings ?? summary?.rings ?? null;

  const target = summary?.target ?? null;
  const targetPath = target ? target.route.split(/[?#]/, 1)[0] ?? target.route : null;
  const wrongPlace = targetPath !== null && !matchesRoutePattern(location.pathname, targetPath);
  const moduleName = trainerModuleLabel(t, task.module);

  const nextTask = me.tasks.find((s) => s.n === task.n + 1) ?? null;
  const opens = summary?.opens ?? null;
  const opensRoute =
    opens && !isBadgeLockId(opens) ? (nextTask?.target?.route ?? getLock(opens)?.catalogueRow ?? null) : null;

  const submitLabel =
    numbersChecks.length > 0
      ? t('trainer.check.submit', { defaultValue: 'Check my numbers' })
      : t('trainer.check.submit_work', { defaultValue: 'Check my work' });

  return (
    <div className="oe-trainer-dock-root flex flex-col gap-3.5 p-4" data-testid="trainer-panel" data-task-id={task.id}>
      {wrongPlace && target && (
        <div
          className="flex flex-col gap-2 rounded-2xl border border-oe-blue/30 bg-oe-blue-subtle px-4 py-3"
          data-testid="trainer-wrong-place"
        >
          <p className="m-0 flex items-center gap-2 text-sm text-content-primary">
            <MapPin size={16} className="shrink-0 text-oe-blue" aria-hidden="true" />
            {t('trainer.panel.wrong_place', { defaultValue: 'This task happens in {{module}}.', module: moduleName })}
          </p>
          <Link
            to={target.anchor ? `${target.route}#${target.anchor}` : target.route}
            className="inline-flex min-h-[44px] items-center self-start rounded-full bg-oe-blue px-5 text-sm font-semibold text-white hover:bg-oe-blue-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-oe-blue"
          >
            {t('trainer.panel.go_to_target', { defaultValue: 'Open {{module}}', module: moduleName })}
          </Link>
        </div>
      )}

      {/* The brief: dark card, as in the mockup. Course content in the course language. */}
      <section className="oe-trainer-brief flex flex-col gap-3 rounded-[18px] p-5" aria-labelledby="oe-trainer-task-heading">
        <h2
          id="oe-trainer-task-heading"
          tabIndex={-1}
          className="oe-trainer-brief-kicker m-0 text-xs font-bold uppercase tracking-wider focus:outline-none"
        >
          {t('trainer.panel.kicker', { defaultValue: 'Task {{n}} · {{title}}', n: task.n, title: task.title })}
        </h2>
        <p className="oe-trainer-brief-text m-0 text-[15px] leading-relaxed" lang={courseLocale} dir={dir}>
          {renderCourseText(task.brief, courseLocale)}
        </p>
        {task.steps.length > 0 && (
          <div className="flex flex-col gap-2">
            <h3 className="sr-only">{t('trainer.panel.steps', { defaultValue: 'Steps' })}</h3>
            <ol className="m-0 flex list-none flex-col gap-2 p-0 text-sm" lang={courseLocale} dir={dir}>
              {task.steps.map((step, i) => (
                <li key={i} className="flex items-start gap-2.5">
                  <span
                    className={`oe-trainer-step-mark ${passed ? 'is-done' : ''} mt-px inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold`}
                    aria-hidden="true"
                  >
                    {passed ? <Check size={12} strokeWidth={3} /> : i + 1}
                  </span>
                  <span className="oe-trainer-brief-step">{renderCourseText(step, courseLocale)}</span>
                </li>
              ))}
            </ol>
          </div>
        )}
      </section>

      {!sameLanguage(courseLocale, uiLocale) && (
        <p className="m-0 flex items-start gap-2 text-xs leading-relaxed text-content-secondary">
          <Info size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
          {t('trainer.panel.course_language_note', {
            defaultValue: 'This course is written in {{language}}. Buttons and labels follow your app language.',
            language: courseLanguageName(courseLocale, uiLocale),
          })}
        </p>
      )}
      {task.has_date_steps && (
        <p className="m-0 flex items-start gap-2 text-xs leading-relaxed text-content-secondary">
          <Info size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
          {t('trainer.panel.date_input_note', {
            defaultValue: "Date fields follow your browser's format. The dates in this task are written out in words.",
          })}
        </p>
      )}

      {task.given.length > 0 && (
        <section className="rounded-2xl bg-surface-elevated px-5 py-4" aria-labelledby="oe-trainer-given">
          <h3 id="oe-trainer-given" className="m-0 mb-2 text-sm font-bold text-content-primary">
            {t('trainer.panel.given', { defaultValue: 'Given' })}
          </h3>
          <dl className="m-0 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5 text-sm" lang={courseLocale} dir={dir}>
            {task.given.map((g) => (
              <div key={g.name} className="contents">
                <dt className="text-content-secondary">{renderCourseText(g.name, courseLocale)}</dt>
                <dd className="m-0 text-end font-mono tabular-nums text-content-primary">
                  {formatCourseValue(g.value, g.kind, { locale: courseLocale, currency })}
                </dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {task.panel_notes.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-1.5 p-0 text-sm text-content-secondary" lang={courseLocale} dir={dir}>
          {task.panel_notes.map((note, i) => (
            <li key={i} className="flex items-start gap-2">
              <Info size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
              {renderCourseText(note, courseLocale)}
            </li>
          ))}
        </ul>
      )}

      <HintStepper taskId={task.id} hints={task.hints} total={task.hints_total} courseLocale={courseLocale} />

      {!passed && (
        <form
          className="flex flex-col gap-4 rounded-2xl bg-surface-elevated px-5 py-4"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            void runCheck(null);
          }}
          data-testid="trainer-check-form"
        >
          {numbersChecks.map((c) => (
            <NumbersCheck
              key={c.id}
              check={c}
              courseLocale={courseLocale}
              currency={currency}
              values={fieldValues}
              verdicts={panelVerdicts}
              showAllProblems={showAllProblems}
              onChange={onFieldChange}
            />
          ))}
          <button
            type="submit"
            aria-busy={busy || undefined}
            className="inline-flex min-h-[44px] items-center justify-center gap-2 self-start rounded-full bg-oe-blue px-5 text-sm font-semibold text-white hover:bg-oe-blue-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-oe-blue"
            data-testid="trainer-check-submit"
          >
            {busy && <Loader2 size={16} className="animate-spin" aria-hidden="true" />}
            {busy ? t('trainer.check.checking', { defaultValue: 'Checking…' }) : submitLabel}
          </button>
        </form>
      )}

      {problem && (
        <div role="alert" className="flex flex-col gap-2 rounded-2xl bg-semantic-error-bg px-4 py-3" data-testid="trainer-check-problem" data-problem={problem}>
          <p className="m-0 text-sm text-content-primary">
            {problem === 'stale'
              ? t('trainer.check.stale', {
                  defaultValue: 'Your task changed since this panel opened. We reloaded it, so please check again.',
                })
              : problem === 'offline'
                ? t('trainer.check.offline', {
                    defaultValue: 'You are offline, so nothing was sent. Your answers are kept here. Check again when you are back online.',
                  })
                : t('trainer.check.error', { defaultValue: 'The check did not run. Your answers are kept.' })}
          </p>
          {problem !== 'stale' && (
            <button
              type="button"
              onClick={() => void runCheck(null)}
              className="inline-flex min-h-[44px] items-center self-start rounded-full border border-border bg-surface-primary px-4 text-sm font-semibold text-content-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-oe-blue"
              data-testid="trainer-check-retry"
            >
              {t('trainer.check.retry', { defaultValue: 'Try again' })}
            </button>
          )}
        </div>
      )}

      {/* The result. Always mounted, so a change is announced. */}
      <div
        id={TRAINER_RESULT_ID}
        tabIndex={-1}
        aria-live="polite"
        className="flex flex-col gap-3 focus:outline-none"
        data-testid="trainer-result"
      >
        {summaryText && (
          <p
            className={[
              'm-0 inline-flex items-center gap-2 text-base font-bold',
              shownAttempt && !cleared && (shownAttempt.verdict === 'pass' || numbersOk)
                ? 'text-semantic-success'
                : 'text-content-primary',
            ].join(' ')}
            data-testid="trainer-result-summary"
          >
            {shownAttempt && !busy && numbersOk && <CircleCheck size={18} aria-hidden="true" />}
            {summaryText}
          </p>
        )}
        {erpItems.length > 0 && !numbersOk && (
          <ul className="m-0 flex list-none flex-col gap-1.5 p-0" data-testid="trainer-erp-verdicts">
            {erpItems.map((item) => {
              const label = subjectOf(item.key);
              const rb = readbackLabels.get(item.key);
              return (
                <li key={`${item.source}-${item.key}`} className="flex items-start justify-between gap-3 text-sm" data-verdict={item.verdict}>
                  <span className="text-content-primary" lang={label ? courseLocale : undefined} dir={label ? dir : undefined}>
                    {label
                      ? renderCourseText(label, courseLocale)
                      : t('trainer.check.erp_item', { defaultValue: 'A figure in your project' })}
                  </span>
                  <span
                    className={`shrink-0 font-semibold ${item.verdict === 'ok' ? 'text-semantic-success' : 'text-semantic-warning'}`}
                  >
                    {item.verdict === 'ok'
                      ? t('trainer.check.field_ok', { defaultValue: 'Matches' })
                      : item.verdict === 'missing'
                        ? t('trainer.check.field_missing', { defaultValue: 'Missing' })
                        : item.verdict === 'error'
                          ? t('trainer.check.field_error', { defaultValue: 'Could not be checked this time. Check again.' })
                          : item.observed !== null && rb
                            ? t('trainer.check.readback_mismatch', {
                                defaultValue: 'Your project shows {{value}}',
                                value: formatCourseValue(item.observed, rb.kind, { locale: courseLocale, currency }),
                              })
                            : t('trainer.check.field_wrong', { defaultValue: 'Does not match yet' })}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        {!numbersOk &&
          diagnosed.map((item) =>
            item.diagnosis ? (
              <Diagnosis
                key={`${item.key}-${item.diagnosis.id}`}
                diagnosis={item.diagnosis}
                courseLocale={courseLocale}
                currency={currency}
                subject={subjectOf(item.key)}
              />
            ) : null,
          )}
      </div>

      {passed && (
        <section
          className="oe-trainer-pop oe-trainer-done flex flex-col gap-3 rounded-[18px] px-5 py-4"
          data-testid="trainer-done"
        >
          <h3 className="oe-trainer-done-title m-0 text-[17px] font-bold">
            {t('trainer.done.title', { defaultValue: 'Task {{n}} verified', n: task.n })}
          </h3>
          <p className="oe-trainer-done-text m-0 text-sm leading-relaxed">
            {t('trainer.done.body', { defaultValue: 'Numbers, Trace and Explain are closed.' })}
          </p>
          <div className="flex flex-wrap gap-2">
            {opensRoute && summary && (
              <Link
                to={opensRoute}
                className="inline-flex min-h-[44px] items-center rounded-full bg-semantic-success px-5 text-sm font-semibold text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-oe-blue"
                data-testid="trainer-done-open"
              >
                {t('trainer.done.open_module', { defaultValue: 'Open {{module}}', module: summary.opens_label })}
              </Link>
            )}
            <Link
              to={COURSE_MAP_ROUTE}
              className="inline-flex min-h-[44px] items-center rounded-full border border-border bg-surface-primary px-5 text-sm font-semibold text-content-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-oe-blue"
            >
              {t('trainer.done.course_map', { defaultValue: 'Course map' })}
            </Link>
          </div>
        </section>
      )}

      {choicesShown &&
        choiceChecks.map((c) => {
          const pending = pendingChoice?.checkId === c.id ? pendingChoice.index : null;
          const savedIndex = savedByName.get(c.id)?.option_index ?? null;
          const chosen = pending ?? savedIndex;
          const raw = attempt?.fields.find((f) => f.key === c.id) ?? null;
          // A verdict counts only for the option it was given on.
          const result = raw && pending === null && raw.observed === String(chosen) ? raw : null;
          return (
            <ChoiceCheck
              key={c.id}
              check={c}
              courseLocale={courseLocale}
              chosen={chosen}
              pendingIndex={pending}
              result={result}
              onPick={(index) => void runCheck({ check: c, index })}
            />
          );
        })}

      <ReadbackList
        items={task.readback}
        values={readbackQ.data?.items}
        courseLocale={courseLocale}
        currency={currency}
        loading={readbackQ.isPending}
      />

      {ringRows.length > 0 && (
        <section className="flex flex-col gap-2.5 rounded-2xl bg-surface-elevated px-5 py-4 text-sm" data-testid="trainer-closes">
          <h3 className="m-0 text-sm font-bold text-content-primary">
            {t('trainer.panel.closes', { defaultValue: 'This task closes' })}
          </h3>
          <ul className="m-0 flex list-none flex-col gap-2 p-0">
            {ringRows.map((row) => {
              const closed = ringState?.[row.id] === true;
              return (
                <li key={row.id} className="flex items-center gap-2.5 text-content-primary" data-ring={row.id} data-closed={closed || undefined}>
                  <span className={`oe-trainer-ring-dot oe-trainer-ring-${row.id} ${closed ? 'is-closed' : ''}`} aria-hidden="true" />
                  <span>{row.label}</span>
                  {closed && (
                    <span className="ms-auto inline-flex items-center gap-1 text-xs font-semibold text-semantic-success">
                      <Check size={12} strokeWidth={3} aria-hidden="true" />
                      {t('trainer.detail.checked', { defaultValue: 'Checked' })}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
          {summary?.video && (
            <Link
              to={summary.video.route}
              className="inline-flex min-h-[44px] items-center gap-2 self-start text-sm font-medium text-oe-blue-text hover:underline"
            >
              <PlayCircle size={16} aria-hidden="true" />
              {t('trainer.panel.watch_title', {
                defaultValue: 'Watch: {{title}}',
                title: renderCourseText(summary.video.title, courseLocale),
              })}
            </Link>
          )}
        </section>
      )}
    </div>
  );
}
