// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The learning path of one example project as a honeycomb: the goal in the
// centre with a progress rim, its courses spiralling out in the order the work
// happens. Each cell shows the course's subject glyph; a done cell fills green,
// the next one carries a blue rim, the rest stay quiet. Hover or focus shows
// the course in a tooltip. Below `sm` the comb becomes a vertical chain.

import { useMemo, useRef, useState, type CSSProperties, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Check, ExternalLink, Lock, RotateCcw } from 'lucide-react';
import { STAGE_BY_ID } from '@/features/cases/stages';
import { HEX_CELL_CLIP } from '@/shared/lib/honeycomb';
import { CountryFlag } from '@/shared/ui/CountryFlag';
import { academyUrlFor, formatItemDuration } from './academyItems';
import type { AcademyItem } from './academyTypes';
import { CourseGlyph, coverAccentColor } from './CourseCover';
import { coverSubject } from './courseCovers';
import {
  courseStage,
  courseStatuses,
  hiveLayout,
  pathPercent,
  useCoursesDone,
  type CourseStatus,
  type LearningPath,
} from './learningPaths';

const DONE_COLOR = 'var(--oe-brand-academy)';
const NEXT_COLOR = 'var(--oe-brand-erp)';

/** Rim of a cell: brand green when done, brand blue when next, the border tone ahead. */
const RIM: Record<CourseStatus, { className?: string; style?: CSSProperties }> = {
  done: { style: { background: DONE_COLOR } },
  next: { style: { background: NEXT_COLOR } },
  ahead: { className: 'bg-border' },
};

const HEX_W = 200;
const HEX_H = 100 * Math.sqrt(3);

function hexPoints(inset: number): string {
  const r = 100 - inset;
  const h = (Math.sqrt(3) / 2) * r;
  const cx = HEX_W / 2;
  const cy = HEX_H / 2;
  return [
    [cx - r, cy],
    [cx - r / 2, cy - h],
    [cx + r / 2, cy - h],
    [cx + r, cy],
    [cx + r / 2, cy + h],
    [cx - r / 2, cy + h],
  ]
    .map(([x, y]) => `${x!.toFixed(1)},${y!.toFixed(1)}`)
    .join(' ');
}

function useStatusLabel() {
  const { t } = useTranslation();
  return (s: CourseStatus) =>
    s === 'done'
      ? t('learn.hive.status_done', { defaultValue: 'Done' })
      : s === 'next'
        ? t('learn.hive.status_next', { defaultValue: 'Next' })
        : t('learn.hive.status_ahead', { defaultValue: 'Ahead' });
}

/** A hexagon with a status rim and the course's subject glyph inside it. */
function HexFace({ item, status, num, compact }: { item: AcademyItem; status: CourseStatus; num: number; compact?: boolean }) {
  const subject = coverSubject(item);
  const accent = coverAccentColor(subject);
  const rim = RIM[status];
  return (
    <span
      className={clsx('absolute inset-0 block', rim.className)}
      style={{ ...rim.style, clipPath: HEX_CELL_CLIP }}
    >
      <span
        className={clsx(
          'absolute block overflow-hidden',
          status === 'ahead' ? 'inset-[3%] bg-surface-secondary' : 'inset-[6%]',
        )}
        style={{
          clipPath: HEX_CELL_CLIP,
          background: status === 'done' ? DONE_COLOR : status === 'next' ? 'var(--oe-cover-ground)' : undefined,
        }}
      >
        {status === 'next' && <span className="absolute inset-0" style={{ background: accent, opacity: 0.16 }} aria-hidden />}
        <span
          className={clsx(
            'absolute inset-0 flex items-center justify-center',
            status === 'done' ? 'text-white' : status === 'ahead' ? 'opacity-60' : undefined,
          )}
          style={status === 'done' ? undefined : { color: accent }}
        >
          <CourseGlyph subject={subject} className={compact ? 'h-[46%] w-[46%]' : 'h-[40%] w-[40%]'} />
        </span>
        <span className={clsx('absolute inset-x-0 flex justify-center', compact ? 'top-[4%]' : 'top-[9%]')}>
          <span
            className={clsx(
              'inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-2xs font-semibold leading-none tabular-nums',
              status === 'done'
                ? 'bg-white'
                : status === 'next'
                  ? 'text-white'
                  : 'bg-surface-elevated text-content-secondary',
            )}
            style={status === 'done' ? { color: DONE_COLOR } : status === 'next' ? { background: NEXT_COLOR } : undefined}
          >
            {status === 'done' ? <Check size={10} strokeWidth={3} aria-hidden /> : num}
          </span>
        </span>
        {item.access === 'paid' && !compact && (
          <span className="absolute inset-x-0 bottom-[9%] flex justify-center">
            <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-surface-elevated text-content-secondary">
              <Lock size={9} aria-hidden />
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
  const [tipRaw, setTip] = useState<number | null>(null);
  const active = activeRaw !== null && activeRaw < courses.length ? activeRaw : nextIndex;
  const tip = tipRaw !== null && tipRaw < courses.length ? tipRaw : null;
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
  const progressLabel = t('learn.hive.progress', {
    defaultValue: '{{done}} of {{total}} courses done',
    done: doneCount,
    total: courses.length,
  });

  const swatch = (s: CourseStatus) => {
    const rim = RIM[s];
    return (
      <span
        className={clsx('inline-block h-3 w-3.5', rim.className)}
        style={{ ...rim.style, clipPath: HEX_CELL_CLIP }}
        aria-hidden
      />
    );
  };

  const progress = (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2 text-xs text-content-secondary">
        <span>{progressLabel}</span>
        <span className="tabular-nums">{formatItemDuration(minutes, i18n.language)}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-surface-secondary">
        <div
          className="h-full rounded-full transition-[width] duration-300 motion-reduce:transition-none"
          style={{ width: `${percent}%`, background: DONE_COLOR }}
        />
      </div>
    </div>
  );

  const tipBox = tip !== null ? layout.cells[tip]! : null;

  return (
    <section
      className="space-y-3 rounded-xl border border-border-light bg-surface-elevated p-4"
      aria-labelledby="course-hive-title"
      data-testid="course-hive"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="course-hive-title" className="oe-section-title">
            {t('learn.hive.title', { defaultValue: 'Learning paths' })}
          </h2>
          <p className="mt-0.5 text-xs text-content-secondary">
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
                  setTip(null);
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

      <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-content-secondary" data-testid="course-hive-legend">
        {(['done', 'next', 'ahead'] as const).map((s) => (
          <li key={s} className="inline-flex items-center gap-1.5">
            {swatch(s)}
            {statusLabel(s)}
          </li>
        ))}
        <li className="inline-flex items-center gap-1.5">
          <Lock size={12} aria-hidden />
          {t('learn.access.paid', { defaultValue: 'Paid training' })}
        </li>
        <li className="hidden text-content-tertiary lg:inline">
          {t('learn.hive.keys_hint', { defaultValue: 'Follow the numbers. Arrow keys move along the path, Enter opens a course.' })}
        </li>
      </ul>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-center lg:gap-6">
        {/* Comb, sm and up */}
        <div className="relative mx-auto hidden w-full max-w-[36rem] sm:block" data-testid="course-hive-comb">
          <div className="relative w-full" style={{ aspectRatio: `${layout.width} / ${layout.height}` }}>
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
              <span className="absolute inset-[3%] block" style={{ clipPath: HEX_CELL_CLIP, background: 'var(--oe-cover-ground)' }}>
                <svg viewBox={`0 0 ${HEX_W} ${HEX_H}`} className="absolute inset-0 h-full w-full" aria-hidden>
                  <polygon points={hexPoints(9)} fill="none" strokeWidth={9} strokeLinejoin="round" className="stroke-border" />
                  <polygon
                    points={hexPoints(9)}
                    fill="none"
                    strokeWidth={9}
                    strokeLinejoin="round"
                    strokeLinecap="round"
                    pathLength={100}
                    strokeDasharray={`${percent} 100`}
                    style={{ stroke: DONE_COLOR }}
                    className="transition-[stroke-dasharray] duration-500 motion-reduce:transition-none"
                    data-testid="course-hive-ring"
                  />
                </svg>
                <span className="absolute inset-0 flex flex-col items-center justify-center px-[14%] text-center">
                  <span className="text-xl font-semibold leading-none tabular-nums text-content-primary" data-testid="course-hive-percent">
                    {percent}%
                  </span>
                  <span className="mt-1 line-clamp-3 text-2xs font-medium leading-tight text-content-secondary">
                    {t('learn.hive.goal', { defaultValue: '{{project}}: take-off to handover', project: path.name })}
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
                    className="absolute transition-transform duration-150 hover:-translate-y-0.5 focus-within:-translate-y-0.5 motion-reduce:transition-none motion-reduce:hover:translate-y-0 motion-reduce:focus-within:translate-y-0"
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
                      onMouseEnter={() => {
                        setActive(n);
                        setTip(n);
                      }}
                      onMouseLeave={() => setTip(null)}
                      onFocus={() => {
                        setActive(n);
                        setTip(n);
                      }}
                      onBlur={() => setTip(null)}
                      onKeyDown={(e) => onKey(e, n)}
                      className="absolute inset-[3%] block outline-none"
                      style={{ clipPath: HEX_CELL_CLIP }}
                    >
                      <HexFace item={c} status={statuses[n]!} num={n + 1} />
                    </a>
                  </li>
                );
              })}
            </ol>

            {tipBox && tip !== null && (
              <div
                aria-hidden
                data-testid="course-hive-tooltip"
                className="pointer-events-none absolute z-tooltip w-56 -translate-x-1/2 -translate-y-full rounded-lg border border-border-light bg-surface-elevated px-2.5 py-1.5 shadow-lg"
                style={{
                  left: `clamp(7rem, ${tipBox.left + tipBox.width / 2}%, calc(100% - 7rem))`,
                  top: `calc(${tipBox.top}% + 2px)`,
                }}
              >
                <p className="line-clamp-2 text-xs font-semibold leading-snug text-content-primary">{courses[tip]!.title}</p>
                <p className="mt-0.5 flex items-center gap-1.5 text-2xs text-content-tertiary">
                  {swatch(statuses[tip]!)}
                  {[statusLabel(statuses[tip]!), duration(courses[tip]!)].filter(Boolean).join(' · ')}
                  {courses[tip]!.access === 'paid' && <Lock size={10} aria-hidden />}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Chain, below sm */}
        <div className="space-y-3 sm:hidden">
          {progress}
          <ol className="space-y-0 sm:hidden" data-testid="course-hive-chain">
            {courses.map((c, n) => (
              <li key={c.id} className="relative flex items-center gap-3 py-1">
                {n < courses.length - 1 && (
                  <span
                    aria-hidden
                    className={clsx(
                      'absolute start-7 top-1/2 h-full w-0.5 -translate-x-1/2 rtl:translate-x-1/2',
                      statuses[n] !== 'done' && 'bg-border',
                    )}
                    style={statuses[n] === 'done' ? { background: DONE_COLOR } : undefined}
                  />
                )}
                <a
                  href={academyUrlFor(c, i18n.language)}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={cellLabel(c, n)}
                  data-status={statuses[n]}
                  data-testid={`course-hive-chain-${n + 1}`}
                  className="relative block h-12 w-14 shrink-0"
                >
                  <HexFace item={c} status={statuses[n]!} num={n + 1} compact />
                </a>
                <div className="min-w-0 flex-1">
                  <p className="line-clamp-2 text-sm font-medium leading-snug text-content-primary">{c.title}</p>
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
        </div>

        {/* What the pointer or focus is on */}
        <aside className="hidden space-y-3 sm:block" aria-live="polite" data-testid="course-hive-detail">
          {progress}
          <div className="space-y-1 border-t border-border-light pt-3">
            <p className="oe-overline flex items-center gap-1.5">
              <CurrentStage.icon size={12} aria-hidden />
              {active + 1} · {t(CurrentStage.labelKey, { defaultValue: CurrentStage.labelDefault })}
            </p>
            <p className="line-clamp-2 min-h-[2.75rem] text-sm font-semibold leading-snug text-content-primary" data-testid="course-hive-detail-title">
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
