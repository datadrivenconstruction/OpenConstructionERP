// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The course map at `/academy`: hero, progress rings, this week, "Up next",
// and the path of tasks with the selected task's detail (Main.dc.html).
//
// State comes from `useTrainerMode()` only (decision 33). Every state has a
// real screen:
//
//   checking / loading   skeleton of the hero, the cards and the path
//   error                what failed, that nothing is lost, and Try again
//   none / off           "No course yet" with Check again
//   enrolled             the map; when every task is verified the dark
//                        "Up next" card becomes the course badge card
//
// Course content (titles, summary, prompts, labels) renders in the course
// locale inside `lang`/`dir` containers, with ISO dates written out in words.
// Chrome (headings, buttons, counters) follows the UI language.
//
// Selection: the station picked on the path lives in the UI store and is only
// written on a click (or by the dock's openTask); without one the map shows
// the task to work on now, or the last task when the course is finished.

import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { ArrowRight, Award, GraduationCap, PlayCircle, RefreshCw, AlertTriangle } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { Skeleton } from '@/shared/ui/Skeleton';

import { courseDir, courseLocaleOf } from './courseLocale';
import { renderCourseText } from './courseText';
import {
  CoursePath,
  isCourseFinished,
  nextTaskOf,
  sortTasks,
  taskHref,
  useOpenTask,
  useTaskScreen,
} from './CoursePath';
import { orderRings, ProgressRings, type RingDatum } from './ProgressRings';
import { TaskDetail } from './TaskDetail';
import type { CourseProgress, TaskSummary, TrainerMe } from './types';
import { useTrainerMode } from './useTrainerMode';
import { useTrainerUiStore } from './useTrainerUiStore';
import { WeekStrip } from './WeekStrip';

const DETAIL_ID = 'trainer-task-detail';
const CARD = 'rounded-[18px] bg-surface-elevated p-5 shadow-xs';

/** The API's ring map as a list, known ids first; any extra id the API adds is kept. */
export function ringsFromProgress(rings: CourseProgress['rings']): RingDatum[] {
  const entries = Object.entries(rings as unknown as Record<string, { done: number; total: number }>);
  return orderRings(entries.map(([id, value]) => ({ id, done: value?.done ?? 0, total: value?.total ?? 0 })));
}

/**
 * Today as YYYY-MM-DD in UTC, to mark it on the week strip. UTC, because the
 * week days are dates the server buckets and the strip pins every date to UTC;
 * a local "today" would sit one day off the server's for part of the day.
 */
function utcToday(): string {
  return new Date().toISOString().slice(0, 10);
}

export function CourseMapPage() {
  // Every hook above the first early return.
  const { t } = useTranslation();
  const mode = useTrainerMode();
  const storedSelection = useTrainerUiStore((s) => s.selectedTaskId);
  const selectTask = useTrainerUiStore((s) => s.selectTask);
  const openTask = useOpenTask();
  const screenOf = useTaskScreen();

  if (mode.state === 'checking' || mode.state === 'loading') return <CourseMapSkeleton />;

  if (mode.state === 'error') {
    return (
      <div className="mx-auto flex w-full max-w-xl flex-col items-center gap-4 px-4 py-16 text-center" role="alert">
        <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-semantic-error-bg text-semantic-error">
          <AlertTriangle size={26} aria-hidden="true" />
        </span>
        <h1 className="text-xl font-semibold text-content-primary">
          {t('trainer.state.error_title', { defaultValue: 'Your course did not load' })}
        </h1>
        <p className="max-w-sm text-sm text-content-secondary">
          {t('trainer.state.error_hint', { defaultValue: 'Nothing you entered is lost. Try again in a moment.' })}
        </p>
        <Button variant="primary" icon={<RefreshCw size={15} />} onClick={mode.refetch} className="min-h-[44px]">
          {t('trainer.state.retry', { defaultValue: 'Try again' })}
        </Button>
      </div>
    );
  }

  if (mode.state !== 'enrolled' || !mode.me) {
    return (
      <div className="mx-auto w-full max-w-xl px-4">
        <EmptyState
          icon={<GraduationCap size={26} aria-hidden="true" />}
          title={t('trainer.state.no_enrolment_title', { defaultValue: 'No course yet' })}
          description={t('trainer.state.no_enrolment_body', {
            defaultValue: 'This account is not enrolled in a course. Ask the person who set up your Academy access.',
          })}
          action={{ label: t('trainer.state.refresh', { defaultValue: 'Check again' }), onClick: mode.refetch }}
        />
      </div>
    );
  }

  return (
    <CourseMap
      me={mode.me}
      storedSelection={storedSelection}
      onSelect={selectTask}
      onOpen={openTask}
      screenOf={screenOf}
    />
  );
}

interface CourseMapProps {
  me: TrainerMe;
  storedSelection: string | null;
  onSelect: (taskId: string) => void;
  onOpen: (task: TaskSummary) => boolean;
  screenOf: ReturnType<typeof useTaskScreen>;
}

function CourseMap({ me, storedSelection, onSelect, onOpen, screenOf }: CourseMapProps) {
  const { t } = useTranslation();
  const courseLocale = courseLocaleOf(me.course);
  const dir = courseDir(courseLocale);
  const text = (value: string | null) => (value ? renderCourseText(value, courseLocale) : '');

  const tasks = sortTasks(me.tasks);
  const finished = isCourseFinished(tasks);
  const next = nextTaskOf(tasks);
  const selected =
    tasks.find((task) => task.id === storedSelection) ?? next ?? tasks[tasks.length - 1] ?? null;
  const total = me.progress.total || tasks.length;
  const done = me.progress.done;
  const kicker = [me.level, me.course.contract].filter((v): v is string => !!v).map(text).join(' · ');

  return (
    <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-6 px-4 pb-12 pt-6 sm:px-6 lg:px-10 lg:pt-7">
      {/* Hero */}
      <section className="flex flex-wrap items-end justify-between gap-6">
        <div className="flex max-w-[720px] flex-col gap-1.5" lang={courseLocale} dir={dir}>
          {kicker && <div className="text-[13px] font-semibold text-oe-purple-text">{kicker}</div>}
          <h1 className="text-[26px] font-bold leading-tight tracking-tight text-content-primary sm:text-[34px]">
            {text(me.course.title)}
          </h1>
          {me.course.summary && (
            <p className="text-[15px] leading-relaxed text-content-secondary">{text(me.course.summary)}</p>
          )}
        </div>
        <div className="flex items-center gap-2.5 text-sm text-content-secondary" data-testid="trainer-map-counter">
          <span className="font-mono text-[28px] font-bold tabular-nums text-content-primary">
            {t('trainer.rings.count', { defaultValue: '{{done}}/{{total}}', done, total })}
          </span>
          <span className="max-w-[6rem] leading-tight">
            {t('trainer.map.tasks_verified_label', { defaultValue: 'tasks verified' })}
          </span>
        </div>
      </section>

      {/* Rings, week, up next */}
      <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
        <div className={clsx(CARD, 'flex flex-col gap-3')}>
          <ProgressRings rings={ringsFromProgress(me.progress.rings)} />
          <p className="max-w-[260px] text-xs leading-snug text-content-tertiary">
            {t('trainer.rings.note', {
              defaultValue: 'Rings close only on checked work. Watching and clicking do not count.',
            })}
          </p>
        </div>

        <div className={CARD}>
          <WeekStrip
            goal={me.week?.goal}
            done={me.week?.done ?? 0}
            days={me.week?.days ?? []}
            today={utcToday()}
          />
        </div>

        {finished ? (
          <BadgeCard me={me} done={done} total={total} courseLocale={courseLocale} />
        ) : (
          <UpNextCard task={next} courseLocale={courseLocale} onOpen={onOpen} screenOf={screenOf} />
        )}
      </section>

      {/* The path and the selected task */}
      <CoursePath
        tasks={tasks}
        nextTaskId={next?.id ?? null}
        selectedTaskId={selected?.id ?? null}
        onSelect={onSelect}
        courseLocale={courseLocale}
        detailId={DETAIL_ID}
      >
        {selected && <TaskDetail id={DETAIL_ID} task={selected} nextTask={next} courseLocale={courseLocale} />}
      </CoursePath>
    </div>
  );
}

const DARK_CARD =
  'flex flex-col justify-between gap-2.5 rounded-[18px] bg-[#1d1d1f] p-5 text-white ring-1 ring-inset ring-white/10 dark:bg-surface-tertiary md:col-span-2 xl:col-span-1';

function UpNextCard({
  task,
  courseLocale,
  onOpen,
  screenOf,
}: {
  task: TaskSummary | null;
  courseLocale: string;
  onOpen: (task: TaskSummary) => boolean;
  screenOf: ReturnType<typeof useTaskScreen>;
}) {
  const { t } = useTranslation();
  const dir = courseDir(courseLocale);
  const kicker = (
    <div className="text-xs font-bold uppercase tracking-[0.06em] text-zinc-400">
      {t('trainer.next.kicker', { defaultValue: 'Up next' })}
    </div>
  );

  // Nothing open and not finished: every remaining task is locked. Say so
  // instead of showing an empty card.
  if (!task) {
    return (
      <div className={DARK_CARD} data-testid="trainer-up-next">
        {kicker}
        <p className="text-sm leading-relaxed text-zinc-300">
          {t('trainer.next.nothing_open', {
            defaultValue: 'Nothing is open right now. Pick a station on the path below to see what opens it.',
          })}
        </p>
      </div>
    );
  }

  const screen = screenOf(task);
  const canGo = taskHref(task, screen) !== null;
  const label =
    task.status === 'not_started'
      ? t('trainer.next.start', { defaultValue: 'Start task {{n}}', n: task.n })
      : t('trainer.next.continue', { defaultValue: 'Continue in {{module}}', module: screen.label });

  return (
    <div className={DARK_CARD} data-testid="trainer-up-next">
      {kicker}
      <div lang={courseLocale} dir={dir} className="text-xl font-bold leading-snug">
        {renderCourseText(task.title, courseLocale)}
      </div>
      {task.checked_prompt && (
        <p lang={courseLocale} dir={dir} className="text-sm leading-relaxed text-zinc-300">
          {renderCourseText(task.checked_prompt, courseLocale)}
        </p>
      )}
      <p className="text-xs text-zinc-400">
        {t('trainer.next.where', { defaultValue: 'You work in {{screen}}.', screen: screen.label })}
      </p>
      <div className="mt-1 flex flex-wrap items-center gap-3">
        {canGo && (
          <button
            type="button"
            onClick={() => onOpen(task)}
            data-testid="trainer-up-next-go"
            className="inline-flex min-h-[44px] items-center gap-2 rounded-full bg-oe-blue px-5 text-sm font-semibold text-white transition-colors hover:bg-oe-blue-hover focus:outline-none focus-visible:ring-2 focus-visible:ring-white focus-visible:ring-offset-2 focus-visible:ring-offset-[#1d1d1f]"
          >
            {label}
            <ArrowRight size={16} aria-hidden="true" />
          </button>
        )}
        {task.video && (
          <Link
            to={task.video.route}
            className="inline-flex min-h-[44px] items-center gap-1.5 rounded-full px-2 text-sm font-medium text-zinc-200 hover:text-white hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-white"
          >
            <PlayCircle size={16} aria-hidden="true" />
            {t('trainer.detail.watch', { defaultValue: 'Watch' })}
          </Link>
        )}
      </div>
    </div>
  );
}

function BadgeCard({
  me,
  done,
  total,
  courseLocale,
}: {
  me: TrainerMe;
  done: number;
  total: number;
  courseLocale: string;
}) {
  const { t } = useTranslation();
  const badgeTitle = me.course.badge?.title ?? me.course.title;
  return (
    <div className={DARK_CARD} data-testid="trainer-badge-card">
      <div className="text-xs font-bold uppercase tracking-[0.06em] text-zinc-400">
        {t('trainer.next.all_done', { defaultValue: 'Course complete' })}
      </div>
      <div className="flex items-center gap-3">
        <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-amber-400 text-[#1d1d1f]">
          <Award size={26} aria-hidden="true" />
        </span>
        <div lang={courseLocale} dir={courseDir(courseLocale)} className="text-xl font-bold leading-snug">
          {renderCourseText(badgeTitle, courseLocale)}
        </div>
      </div>
      <p className="text-sm leading-relaxed text-zinc-300">
        {t('trainer.unlock.progress', { defaultValue: '{{done}} of {{total}} verified.', done, total })}
      </p>
    </div>
  );
}

function CourseMapSkeleton() {
  const { t } = useTranslation();
  return (
    <div
      className="mx-auto flex w-full max-w-[1200px] flex-col gap-6 px-4 pb-12 pt-6 sm:px-6 lg:px-10"
      role="status"
      aria-busy="true"
      data-testid="trainer-map-loading"
    >
      <span className="sr-only">{t('trainer.state.loading', { defaultValue: 'Loading your course' })}</span>
      <div className="flex flex-col gap-2" aria-hidden="true">
        <Skeleton width={220} height={14} />
        <Skeleton width="60%" height={34} />
        <Skeleton width="80%" height={16} />
      </div>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" aria-hidden="true">
        <Skeleton height={172} className="rounded-[18px]" />
        <Skeleton height={172} className="rounded-[18px]" />
        <Skeleton height={172} className="rounded-[18px] md:col-span-2 xl:col-span-1" />
      </div>
      <div aria-hidden="true">
        <Skeleton height={260} className="rounded-[18px]" />
      </div>
    </div>
  );
}
