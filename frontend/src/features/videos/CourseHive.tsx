// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The learning path of one example project as a honeycomb: the goal in the
// centre, its courses spiralling out in the order the work happens, each cell
// cut from the course's own photo. Ring colour says done / next / ahead; the
// numbers and the connectors say the order. Below `sm` the comb becomes a
// vertical chain of the same cells.

import { useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Check, ExternalLink, Flag, Lock, RotateCcw } from 'lucide-react';
import { STAGE_BY_ID } from '@/features/cases/stages';
import { HEX_CELL_CLIP } from '@/shared/lib/honeycomb';
import { CountryFlag } from '@/shared/ui/CountryFlag';
import { academyUrlFor, formatItemDuration } from './academyItems';
import type { AcademyItem } from './academyTypes';
import {
  courseStage,
  coursePhoto,
  courseStatuses,
  hiveLayout,
  pathPercent,
  useCoursesDone,
  type CourseStatus,
  type LearningPath,
} from './learningPaths';

const RING: Record<CourseStatus, string> = {
  done: 'bg-semantic-success',
  next: 'bg-oe-blue',
  ahead: 'bg-border',
};

function useStatusLabel() {
  const { t } = useTranslation();
  return (s: CourseStatus) =>
    s === 'done'
      ? t('learn.hive.status_done', { defaultValue: 'Done' })
      : s === 'next'
        ? t('learn.hive.status_next', { defaultValue: 'Next' })
        : t('learn.hive.status_ahead', { defaultValue: 'Ahead' });
}

/** A hexagon with a coloured rim and the course photo cut inside it. */
function HexFace({
  item,
  status,
  num,
  active,
}: {
  item: AcademyItem;
  status: CourseStatus;
  num: number;
  active?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const StageIcon = STAGE_BY_ID[courseStage(item)].icon;
  return (
    <span
      className={clsx(
        'absolute inset-0 block p-[4%] transition-transform duration-200 motion-reduce:transition-none',
        RING[status],
        active && 'scale-[1.06]',
      )}
      style={{ clipPath: HEX_CELL_CLIP }}
    >
      <span className="relative block h-full w-full overflow-hidden bg-surface-secondary" style={{ clipPath: HEX_CELL_CLIP }}>
        {failed ? (
          <span className="flex h-full w-full items-center justify-center text-content-tertiary">
            <StageIcon size={22} aria-hidden />
          </span>
        ) : (
          <img
            src={coursePhoto(item)}
            alt=""
            loading="lazy"
            decoding="async"
            onError={() => setFailed(true)}
            className={clsx(
              'h-full w-full object-cover transition-[filter,opacity] duration-200 motion-reduce:transition-none',
              status === 'ahead' && !active && 'opacity-55 grayscale',
            )}
          />
        )}
        <span className="absolute inset-x-0 top-[12%] flex justify-center">
          <span
            className={clsx(
              'inline-flex h-6 min-w-6 items-center justify-center rounded-full px-1.5 text-xs font-semibold tabular-nums shadow-sm',
              status === 'done'
                ? 'bg-semantic-success text-content-inverse'
                : status === 'next'
                  ? 'bg-oe-blue text-content-inverse'
                  : 'bg-surface-elevated text-content-primary',
            )}
          >
            {status === 'done' ? <Check size={13} aria-hidden /> : num}
          </span>
        </span>
        {item.access === 'paid' && (
          <span className="absolute inset-x-0 bottom-[12%] flex justify-center">
            <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-surface-elevated text-content-secondary shadow-sm">
              <Lock size={11} aria-hidden />
            </span>
          </span>
        )}
      </span>
    </span>
  );
}

export function CourseHive({ paths, initialPath }: { paths: LearningPath[]; initialPath?: string }) {
  const { t, i18n } = useTranslation();
  const statusLabel = useStatusLabel();
  const [pathId, setPathId] = useState(initialPath ?? paths[0]?.id);
  const path = paths.find((p) => p.id === pathId) ?? paths[0];
  const [done, toggleDone] = useCoursesDone();
  const courses = path?.courses ?? [];
  const statuses = useMemo(() => courseStatuses(courses, done), [courses, done]);
  const percent = pathPercent(courses, done);
  const layout = useMemo(() => hiveLayout(courses.length), [courses.length]);
  const nextIndex = Math.max(0, statuses.indexOf('next'));
  const [activeRaw, setActive] = useState<number | null>(null);
  const active = activeRaw !== null && activeRaw < courses.length ? activeRaw : nextIndex;
  const cellRefs = useRef<(HTMLAnchorElement | null)[]>([]);

  if (!path) return null;
  const doneCount = statuses.filter((s) => s === 'done').length;
  const minutes = courses.reduce((a, c) => a + (c.durationMin ?? 0), 0);
  const duration = (c: AcademyItem) => (c.durationMin ? formatItemDuration(c.durationMin, i18n.language) : '');
  const cellLabel = (c: AcademyItem, n: number) =>
    t('learn.hive.cell_label', {
      defaultValue: '{{n}}. {{title}}, {{duration}}, {{status}}',
      n: n + 1,
      title: c.title,
      duration: duration(c),
      status: statusLabel(statuses[n]!),
    });

  const onKey = (e: KeyboardEvent<HTMLElement>, n: number) => {
    let to: number | null = null;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') to = Math.min(courses.length - 1, n + 1);
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') to = Math.max(0, n - 1);
    else if (e.key === 'Home') to = 0;
    else if (e.key === 'End') to = courses.length - 1;
    if (to === null) return;
    e.preventDefault();
    setActive(to);
    cellRefs.current[to]?.focus();
  };

  const current = courses[active]!;
  const currentStatus = statuses[active]!;
  const CurrentStage = STAGE_BY_ID[courseStage(current)];
  const centrePhoto = courses[courses.length - 1]!;

  const legend = (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-content-secondary" data-testid="course-hive-legend">
      {(['done', 'next', 'ahead'] as const).map((s) => (
        <li key={s} className="inline-flex items-center gap-1.5">
          <span className={clsx('inline-block h-3 w-3.5', RING[s])} style={{ clipPath: HEX_CELL_CLIP }} aria-hidden />
          {statusLabel(s)}
        </li>
      ))}
      <li className="inline-flex items-center gap-1.5">
        <Lock size={12} aria-hidden />
        {t('learn.access.paid', { defaultValue: 'Paid training' })}
      </li>
      <li className="hidden text-content-tertiary sm:inline">
        {t('learn.hive.keys_hint', { defaultValue: 'Follow the numbers. Arrow keys move along the path, Enter opens a course.' })}
      </li>
    </ul>
  );

  return (
    <section
      className="space-y-4 rounded-xl border border-border-light bg-surface-elevated p-4"
      aria-labelledby="course-hive-title"
      data-testid="course-hive"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="course-hive-title" className="oe-section-title">
            {t('learn.hive.title', { defaultValue: 'Learning paths' })}
          </h2>
          <p className="mt-0.5 text-sm text-content-secondary">
            {t('learn.hive.subtitle', {
              defaultValue: 'One project from take-off to handover. Each cell is a course, numbered in the order the work happens.',
            })}
          </p>
        </div>
        {paths.length > 1 && (
          <div
            className="inline-flex h-8 items-center rounded-lg border border-border-light p-0.5"
            role="group"
            aria-label={t('learn.hive.choose_path', { defaultValue: 'Project' })}
          >
            {paths.map((p) => (
              <button
                key={p.id}
                type="button"
                data-oe-segment
                aria-pressed={p.id === path.id}
                onClick={() => {
                  setPathId(p.id);
                  setActive(null);
                }}
                data-testid={`course-hive-path-${p.id}`}
                className={clsx(
                  'inline-flex h-full items-center gap-1.5 rounded-md px-2.5 text-xs font-medium transition-colors motion-reduce:transition-none',
                  p.id === path.id ? 'bg-oe-blue/10 text-oe-blue' : 'text-content-secondary hover:bg-surface-secondary',
                )}
              >
                {p.country && <CountryFlag code={p.country} size={14} />}
                {p.name}
                <span className="tabular-nums text-content-tertiary">{p.courses.length}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {legend}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-center">
        {/* Comb, sm and up */}
        <div className="relative mx-auto hidden w-full max-w-[44rem] sm:block" data-testid="course-hive-comb">
          <div className="relative w-full" style={{ aspectRatio: `${layout.width} / ${layout.height}` }}>
            <svg
              className="pointer-events-none absolute inset-0 h-full w-full"
              viewBox={`0 0 ${layout.width} ${layout.height}`}
              aria-hidden
            >
              {[layout.centre, ...layout.cells].slice(0, -1).map((a, n) => {
                const b = layout.cells[n]!;
                const lit = n === 0 || statuses[n - 1] === 'done';
                return (
                  <line
                    key={n}
                    x1={a.cx + (b.cx - a.cx) * 0.3}
                    y1={a.cy + (b.cy - a.cy) * 0.3}
                    x2={a.cx + (b.cx - a.cx) * 0.7}
                    y2={a.cy + (b.cy - a.cy) * 0.7}
                    stroke="currentColor"
                    strokeWidth={lit ? 0.09 : 0.06}
                    strokeDasharray={lit ? undefined : '0.12 0.1'}
                    strokeLinecap="round"
                    className={lit ? 'text-oe-blue' : 'text-content-quaternary'}
                    data-testid="course-hive-link"
                  />
                );
              })}
            </svg>

            <div
              className="absolute"
              style={{
                left: `${layout.centre.left}%`,
                top: `${layout.centre.top}%`,
                width: `${layout.centre.width}%`,
                height: `${layout.centre.height}%`,
              }}
              data-testid="course-hive-goal"
            >
              <span className="absolute inset-0 block bg-oe-blue p-[4%]" style={{ clipPath: HEX_CELL_CLIP }}>
                <span className="relative block h-full w-full overflow-hidden" style={{ clipPath: HEX_CELL_CLIP }}>
                  <img src={coursePhoto(centrePhoto)} alt="" loading="lazy" decoding="async" className="h-full w-full object-cover" />
                  <span className="absolute inset-0 flex flex-col items-center justify-center bg-surface-elevated/85 px-[16%] text-center">
                    <Flag size={14} className="text-oe-blue" aria-hidden />
                    <span className="text-xl font-semibold tabular-nums text-content-primary" data-testid="course-hive-percent">
                      {percent}%
                    </span>
                    <span className="text-2xs font-medium leading-tight text-content-secondary">
                      {t('learn.hive.goal', { defaultValue: '{{project}}: take-off to handover', project: path.name })}
                    </span>
                  </span>
                </span>
              </span>
            </div>

            <ol aria-label={`${t('learn.hive.title', { defaultValue: 'Learning paths' })}: ${path.name}`}>
              {courses.map((c, n) => {
                const box = layout.cells[n]!;
                return (
                  <li
                    key={c.id}
                    className="absolute"
                    style={{ left: `${box.left}%`, top: `${box.top}%`, width: `${box.width}%`, height: `${box.height}%` }}
                  >
                    <a
                      ref={(el) => {
                        cellRefs.current[n] = el;
                      }}
                      href={academyUrlFor(c, i18n.language)}
                      target="_blank"
                      rel="noopener noreferrer"
                      tabIndex={n === active ? 0 : -1}
                      aria-label={cellLabel(c, n)}
                      aria-current={statuses[n] === 'next' ? 'step' : undefined}
                      data-status={statuses[n]}
                      data-testid={`course-hive-cell-${n + 1}`}
                      onMouseEnter={() => setActive(n)}
                      onFocus={() => setActive(n)}
                      onKeyDown={(e) => onKey(e, n)}
                      className="absolute inset-[3%] block outline-none"
                      style={{ clipPath: HEX_CELL_CLIP }}
                    >
                      <HexFace item={c} status={statuses[n]!} num={n + 1} active={n === active} />
                    </a>
                  </li>
                );
              })}
            </ol>
          </div>
        </div>

        {/* Chain, below sm */}
        <ol className="space-y-0 sm:hidden" data-testid="course-hive-chain">
          {courses.map((c, n) => (
            <li key={c.id} className="relative flex items-center gap-3 py-1.5">
              {n < courses.length - 1 && (
                <span
                  aria-hidden
                  className={clsx(
                    'absolute start-8 top-1/2 h-full w-0.5 translate-x-[-50%] rtl:translate-x-[50%]',
                    statuses[n] === 'done' ? 'bg-oe-blue' : 'bg-border',
                  )}
                />
              )}
              <a
                href={academyUrlFor(c, i18n.language)}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={cellLabel(c, n)}
                data-status={statuses[n]}
                data-testid={`course-hive-chain-${n + 1}`}
                className="relative block h-14 w-16 shrink-0"
              >
                <HexFace item={c} status={statuses[n]!} num={n + 1} />
              </a>
              <div className="min-w-0 flex-1">
                <p className="line-clamp-2 text-sm font-medium text-content-primary">{c.title}</p>
                <p className="text-xs text-content-tertiary">
                  {statusLabel(statuses[n]!)} · {duration(c)}
                </p>
              </div>
              <button
                type="button"
                onClick={() => toggleDone(c.id)}
                aria-pressed={statuses[n] === 'done'}
                aria-label={t('learn.hive.mark_done', { defaultValue: 'Mark as done' }) + ': ' + c.title}
                className={clsx(
                  'inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border',
                  statuses[n] === 'done'
                    ? 'border-semantic-success/30 bg-semantic-success-bg text-semantic-success'
                    : 'border-border-light text-content-tertiary',
                )}
              >
                <Check size={16} aria-hidden />
              </button>
            </li>
          ))}
        </ol>

        {/* What the pointer or focus is on */}
        <aside className="hidden space-y-3 sm:block" aria-live="polite" data-testid="course-hive-detail">
          <div className="flex items-baseline justify-between gap-2 text-xs text-content-secondary">
            <span>
              {t('learn.hive.progress', {
                defaultValue: '{{done}} of {{total}} courses done',
                done: doneCount,
                total: courses.length,
              })}
            </span>
            <span className="tabular-nums">{formatItemDuration(minutes, i18n.language)}</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-surface-secondary">
            <div
              className="h-full rounded-full bg-semantic-success transition-[width] duration-300 motion-reduce:transition-none"
              style={{ width: `${percent}%` }}
            />
          </div>
          <div className="space-y-1.5 border-t border-border-light pt-3">
            <p className="oe-overline flex items-center gap-1.5">
              <CurrentStage.icon size={12} aria-hidden />
              {active + 1} · {t(CurrentStage.labelKey, { defaultValue: CurrentStage.labelDefault })}
            </p>
            <p className="text-base font-semibold leading-snug text-content-primary" data-testid="course-hive-detail-title">
              {current.title}
            </p>
            <p className="text-xs text-content-tertiary">
              {statusLabel(currentStatus)} · {duration(current)}
              {current.access === 'paid' && ` · ${t('learn.access.paid', { defaultValue: 'Paid training' })}`}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <a
              href={academyUrlFor(current, i18n.language)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-oe-blue px-3 text-sm font-medium text-content-inverse hover:bg-oe-blue-hover"
              data-testid="course-hive-open"
            >
              <ExternalLink size={16} aria-hidden />
              {t('learn.hive.open', { defaultValue: 'Open course' })}
            </a>
            <button
              type="button"
              onClick={() => toggleDone(current.id)}
              aria-pressed={currentStatus === 'done'}
              data-testid="course-hive-toggle"
              className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-border-light bg-surface-primary px-3 text-sm font-medium text-content-primary hover:bg-surface-secondary"
            >
              {currentStatus === 'done' ? <RotateCcw size={16} aria-hidden /> : <Check size={16} aria-hidden />}
              {currentStatus === 'done'
                ? t('learn.hive.mark_undone', { defaultValue: 'Not done yet' })
                : t('learn.hive.mark_done', { defaultValue: 'Mark as done' })}
            </button>
          </div>
          <p className="text-2xs text-content-tertiary">
            {t('learn.hive.local_note', { defaultValue: 'Progress is kept in this browser only.' })}
          </p>
        </aside>
      </div>
    </section>
  );
}
