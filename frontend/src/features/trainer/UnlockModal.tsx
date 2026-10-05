// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The celebration when a checked task opens something new, after
// Unlock.dc.html: the padlock's shackle lifts and swings open, the content
// rises in three beats, the icon tile glows. It names what opened (in the
// course language), says how far the learner has come, and offers the next
// step. A finished course shows the badge variant instead of the padlock.
//
// No dark patterns: no countdown, no streak, nothing framed as a loss.
//
// A focus-trapped dialog in a portal: focus starts on the main button,
// Tab stays inside, Escape and the backdrop close it, and focus goes back to
// where it was. Under `prefers-reduced-motion` the animation classes are left
// off and the shackle is drawn already open.

import { useEffect, useId, useRef, useState, type MouseEvent } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Award } from 'lucide-react';

import { useFocusTrap } from '@/shared/hooks/useFocusTrap';
import { useI18nReady } from '@/shared/lib/useI18nReady';

import { courseDir } from './courseLocale';
import { PILL_PRIMARY, PILL_SECONDARY } from './LockedModulePage';
import { COURSE_MAP_ROUTE } from './routeMatch';
import type { LockKind, TaskRings, UnlockTile } from './types';
import { useTrainerUiStore } from './useTrainerUiStore';
import './trainerUnlock.css';

export interface UnlockModalUnlock {
  lockId: string;
  kind: LockKind;
  /** What opened, in the course language: the task's `opens_label`, or the badge title. */
  label: string;
  openedByTask: number;
  tiles: UnlockTile[];
}

export interface UnlockModalProps {
  unlock: UnlockModalUnlock;
  /** The course locale; `label` and `tiles` are written in it. */
  contentLang: string;
  progress: { done: number; total: number };
  /** The rings of the task that opened this, drawn as three dots. */
  rings?: TaskRings | null;
  week?: { done: number; goal: number } | null;
  /** The task that comes next, when it has somewhere to go. */
  next?: { n: number; taskId: string; to: string } | null;
  /** The opened screen itself, used when there is no next task to start. */
  goThere?: string | null;
  onClose: () => void;
}

export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

function Padlock({ animate }: { animate: boolean }) {
  return (
    <svg
      width="36"
      height="36"
      viewBox="0 0 32 32"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="7" y="15" width="18" height="13" rx="3" />
      <path
        data-testid="unlock-shackle"
        className={clsx('oe-trainer-shackle', animate ? 'oe-trainer-shackle--animate' : 'oe-trainer-shackle--open')}
        d="M11 15v-4a5 5 0 0 1 10 0v4"
      />
    </svg>
  );
}

// Closed ring: filled. Open ring: the outline only. Colours as on the course map.
const RING_DOTS: Array<{ id: keyof TaskRings; on: string; off: string }> = [
  { id: 'numbers', on: 'border-oe-blue bg-oe-blue', off: 'border-oe-blue bg-transparent' },
  { id: 'trace', on: 'border-oe-purple bg-oe-purple', off: 'border-oe-purple bg-transparent' },
  {
    id: 'explain',
    on: 'border-orange-700 bg-orange-700 dark:border-orange-400 dark:bg-orange-400',
    off: 'border-orange-700 bg-transparent dark:border-orange-400',
  },
];

export function UnlockModal({ unlock, contentLang, progress, rings, week, next, goThere, onClose }: UnlockModalProps) {
  // Mounted at shell level, possibly before the locale has loaded
  // (`useSuspense: false`): re-render when it lands.
  useI18nReady();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const openTask = useTrainerUiStore((s) => s.openTask);
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  const primaryRef = useRef<HTMLButtonElement>(null);
  const [animate] = useState(() => !prefersReducedMotion());
  const isBadge = unlock.kind === 'badge';
  const dir = courseDir(contentLang);

  // Order matters: the trap records the element to return to before focus
  // moves to the main button.
  useFocusTrap(dialogRef, true);
  useEffect(() => {
    primaryRef.current?.focus();
  }, []);

  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      e.stopPropagation();
      closeRef.current();
    };
    document.addEventListener('keydown', onKey, true);
    return () => document.removeEventListener('keydown', onKey, true);
  }, []);

  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  const kicker =
    unlock.kind === 'badge'
      ? t('trainer.unlock.kicker_badge', { defaultValue: 'Course complete' })
      : unlock.kind === 'module'
        ? t('trainer.unlock.kicker', { defaultValue: 'New module open' })
        : t('trainer.unlock.kicker_panel', { defaultValue: 'New panel open' });

  const goTo = (to: string, taskId?: string) => {
    onClose();
    navigate(to);
    if (taskId) openTask(taskId);
  };

  let primary: { label: string; run: () => void };
  if (!isBadge && next) {
    primary = {
      label: t('trainer.unlock.start_next', { defaultValue: 'Start task {{n}}', n: next.n }),
      run: () => goTo(next.to, next.taskId),
    };
  } else if (!isBadge && goThere) {
    primary = { label: t('trainer.unlock.go_there', { defaultValue: 'Go there' }), run: () => goTo(goThere) };
  } else {
    primary = { label: t('trainer.unlock.close', { defaultValue: 'Close' }), run: onClose };
  }

  const onBackdrop = (e: MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose();
  };

  const dialog = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-[radial-gradient(ellipse_at_50%_40%,rgba(28,42,61,0.9)_0%,rgba(15,15,18,0.92)_70%)] px-4 py-10"
      onMouseDown={onBackdrop}
      data-testid="unlock-backdrop"
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="flex w-full max-w-[760px] flex-col gap-[26px] rounded-[28px] border border-border-light bg-surface-elevated p-6 shadow-xl sm:p-11"
      >
        <div className={clsx('flex flex-wrap items-center gap-5', animate && 'oe-trainer-rise')}>
          <span
            aria-hidden="true"
            data-testid="unlock-icon"
            className={clsx(
              'inline-flex h-[72px] w-[72px] shrink-0 items-center justify-center rounded-[22px] text-white',
              isBadge ? 'bg-amber-500' : 'bg-semantic-success-vivid',
              animate && (isBadge ? 'oe-trainer-glow-badge' : 'oe-trainer-glow'),
            )}
          >
            {isBadge ? <Award size={36} strokeWidth={2.2} /> : <Padlock animate={animate} />}
          </span>
          <div className="flex min-w-0 flex-col gap-1">
            <div
              className={clsx(
                'text-[13px] font-bold uppercase tracking-[0.04em]',
                isBadge ? 'text-amber-700 dark:text-amber-400' : 'text-semantic-success',
              )}
            >
              {kicker}
            </div>
            <h1
              id={titleId}
              lang={contentLang}
              dir={dir}
              className="m-0 text-3xl font-semibold tracking-tight text-content-primary sm:text-[34px]"
            >
              {unlock.label}
            </h1>
          </div>
        </div>

        {unlock.tiles.length > 0 && (
          <ul
            lang={contentLang}
            dir={dir}
            className={clsx(
              'm-0 grid list-none gap-3 p-0 [grid-template-columns:repeat(auto-fit,minmax(190px,1fr))]',
              animate && 'oe-trainer-rise-2',
            )}
          >
            {unlock.tiles.map((tile, i) => (
              <li key={`${i}-${tile.title}`} className="flex flex-col gap-1.5 rounded-2xl bg-surface-secondary p-4">
                <span
                  aria-hidden="true"
                  className="inline-flex h-[34px] w-[34px] items-center justify-center rounded-[10px] bg-oe-blue text-sm font-bold text-content-inverse"
                >
                  {i + 1}
                </span>
                <strong className="text-[15px] text-content-primary">{tile.title}</strong>
                <span className="text-[13px] leading-snug text-content-secondary">{tile.text}</span>
              </li>
            ))}
          </ul>
        )}

        <div
          className={clsx(
            'flex flex-wrap items-center gap-[18px] border-t border-border-light pt-[22px]',
            animate && 'oe-trainer-rise-3',
          )}
        >
          {rings && (
            <div className="flex items-center gap-2" aria-hidden="true">
              {RING_DOTS.map((dot) => (
                <span
                  key={dot.id}
                  className={clsx('h-[26px] w-[26px] rounded-full border-4', rings[dot.id] ? dot.on : dot.off)}
                />
              ))}
            </div>
          )}
          <p className="m-0 min-w-[200px] flex-1 text-sm leading-normal text-content-secondary">
            <strong className="text-content-primary">
              {t('trainer.unlock.progress', {
                defaultValue: '{{done}} of {{total}} verified.',
                done: progress.done,
                total: progress.total,
              })}
            </strong>
            {week && (
              <>
                {' '}
                {t('trainer.unlock.week', {
                  defaultValue: "This week's goal: {{done}}/{{goal}}.",
                  done: week.done,
                  goal: week.goal,
                })}
              </>
            )}
          </p>
          <div className="flex flex-wrap gap-2.5">
            <button type="button" className={PILL_SECONDARY} onClick={() => goTo(COURSE_MAP_ROUTE)}>
              {t('trainer.unlock.course_map', { defaultValue: 'Course map' })}
            </button>
            <button type="button" ref={primaryRef} className={PILL_PRIMARY} onClick={primary.run}>
              {primary.label}
            </button>
          </div>
        </div>
      </div>
    </div>
  );

  return createPortal(dialog, document.body);
}
