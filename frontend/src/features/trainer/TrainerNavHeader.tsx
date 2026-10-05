// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The "Your course" block at the top of the sidebar while a course is active
// (the left rail of the Main mockup): course name, a progress line, then the
// Course map row, "Open modules", "Opens as you go" and the footnote.
//
// This component draws the frame only. The rows are the sidebar's own row
// component, passed in as slots, so they keep the sidebar's active state,
// gates and keyboard behaviour. A slot with no rows drops its label too.

import { Children, useId, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { GraduationCap } from 'lucide-react';

import type { TrainerNavCourse } from './useTrainerNav';

export interface TrainerNavHeaderProps {
  /** Section label; defaults to "Your course". */
  label?: string;
  /** Course name and progress. Null while `/me` loads or failed: a placeholder line. */
  course: TrainerNavCourse | null;
  /** The Course map row (an `<li>`). */
  children: ReactNode;
  /** The open module rows (`<li>`s), or nothing. */
  openModules?: ReactNode;
  /** The locked module rows (`<li>`s), or nothing. */
  lockedModules?: ReactNode;
  /** "The rest of the platform opens in later courses.", already translated. */
  footnote?: string | null;
  /** The collapsed icon-only sidebar. */
  iconified?: boolean;
}

/**
 * The "New" chip of an Academy row whose lock opened and was not seen yet
 * (`TrainerNavRow.fresh`). Exported for the sidebar row, so the label key
 * lives next to the rest of the section's strings.
 */
export function TrainerNewChip() {
  const { t } = useTranslation();
  return (
    <span className="shrink-0 rounded-full bg-oe-blue px-1.5 py-px text-[10px] font-bold leading-4 text-white">
      {t('trainer.nav.new', { defaultValue: 'New' })}
    </span>
  );
}

function hasRows(node: ReactNode): boolean {
  return Children.toArray(node).length > 0;
}

function percentOf(done: number, total: number): number {
  if (!(total > 0)) return 0;
  return Math.min(100, Math.max(0, Math.round((done / total) * 100)));
}

export function TrainerNavHeader({
  label,
  course,
  children,
  openModules,
  lockedModules,
  footnote,
  iconified = false,
}: TrainerNavHeaderProps) {
  const { t } = useTranslation();
  const baseId = useId();
  const headingId = `${baseId}-label`;
  const titleId = `${baseId}-title`;
  const openId = `${baseId}-open`;
  const lockedId = `${baseId}-locked`;
  const sectionLabel = label ?? t('trainer.nav.section', { defaultValue: 'Your course' });
  const showOpen = hasRows(openModules);
  const showLocked = hasRows(lockedModules);

  const progress = course ? (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={course.total}
      aria-valuenow={Math.min(course.done, course.total)}
      aria-label={t('trainer.unlock.progress', {
        defaultValue: '{{done}} of {{total}} verified.',
        done: course.done,
        total: course.total,
      })}
      className={clsx('h-1 overflow-hidden rounded-full bg-oe-purple/15', iconified ? 'mx-1.5' : 'w-full')}
    >
      <div
        data-testid="trainer-nav-progress-fill"
        className="h-full rounded-full bg-oe-purple transition-[width] duration-500 ease-out motion-reduce:transition-none"
        style={{ width: `${percentOf(course.done, course.total)}%` }}
      />
    </div>
  ) : null;

  if (iconified) {
    return (
      <section
        data-testid="trainer-nav"
        aria-labelledby={course ? `${headingId} ${titleId}` : headingId}
        title={course?.title}
        className="mb-1 rounded-xl bg-oe-purple/[0.06] py-1.5 ring-1 ring-inset ring-oe-purple/15 dark:bg-oe-purple/[0.12]"
      >
        <span id={headingId} className="sr-only">
          {sectionLabel}
        </span>
        {course ? (
          <span id={titleId} lang={course.lang} className="sr-only">
            {course.title}
          </span>
        ) : null}
        <span className="mb-1 flex justify-center text-oe-purple-text" aria-hidden>
          <GraduationCap size={14} strokeWidth={2.25} />
        </span>
        {progress}
        <ul className="mt-1 space-y-0.5">{children}</ul>
        {showOpen && (
          <>
            <div className="my-1.5 mx-auto h-px w-6 bg-oe-purple/20" aria-hidden />
            <ul className="space-y-0.5">{openModules}</ul>
          </>
        )}
        {showLocked && (
          <>
            <div className="my-1.5 mx-auto h-px w-6 bg-oe-purple/20" aria-hidden />
            <ul className="space-y-0.5">{lockedModules}</ul>
          </>
        )}
      </section>
    );
  }

  return (
    <section
      data-testid="trainer-nav"
      aria-labelledby={headingId}
      className={clsx(
        'relative mb-2 rounded-xl p-1.5',
        'border border-oe-purple/15 bg-gradient-to-br from-oe-purple/[0.07] via-oe-purple/[0.03] to-transparent',
        'dark:border-oe-purple/25 dark:from-oe-purple/[0.14] dark:via-oe-purple/[0.06]',
      )}
    >
      <div className="flex flex-col gap-1.5 px-1.5 pb-1.5 pt-0.5">
        <div className="flex items-center gap-1.5">
          <span
            className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-oe-purple/15 text-oe-purple-text"
            aria-hidden
          >
            <GraduationCap size={12} strokeWidth={2.25} />
          </span>
          <span
            id={headingId}
            className="min-w-0 flex-1 truncate text-[10px] font-semibold uppercase tracking-[0.085em] text-oe-purple-text"
          >
            {sectionLabel}
          </span>
        </div>
        {course ? (
          <>
            <p
              lang={course.lang}
              title={course.title}
              className="line-clamp-2 text-[13px] font-semibold leading-snug text-content-primary"
            >
              {course.title}
            </p>
            <div className="flex flex-col gap-1">
              {progress}
              <p className="text-[11px] text-content-secondary" aria-hidden>
                <span className="font-semibold tabular-nums text-content-primary">
                  {t('trainer.rings.count', {
                    defaultValue: '{{done}}/{{total}}',
                    done: course.done,
                    total: course.total,
                  })}
                </span>{' '}
                {t('trainer.map.tasks_verified_label', { defaultValue: 'tasks verified' })}
              </p>
            </div>
          </>
        ) : (
          <div data-testid="trainer-nav-placeholder" className="flex flex-col gap-1.5" aria-hidden>
            <span className="h-3.5 w-3/4 rounded bg-oe-purple/10 motion-safe:animate-pulse" />
            <span className="h-1 w-full rounded-full bg-oe-purple/10" />
          </div>
        )}
      </div>

      <ul className="space-y-0.5">{children}</ul>

      {showOpen && (
        <>
          <p
            id={openId}
            className="px-2.5 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-[0.085em] text-content-tertiary"
          >
            {t('trainer.nav.open_modules', { defaultValue: 'Open modules' })}
          </p>
          <ul aria-labelledby={openId} className="space-y-0.5">
            {openModules}
          </ul>
        </>
      )}

      {showLocked && (
        <>
          <p
            id={lockedId}
            className="px-2.5 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-[0.085em] text-content-tertiary"
          >
            {t('trainer.nav.opens_as_you_go', { defaultValue: 'Opens as you go' })}
          </p>
          <ul aria-labelledby={lockedId} className="space-y-0.5">
            {lockedModules}
          </ul>
        </>
      )}

      {footnote ? (
        <p className="px-2.5 pb-1 pt-3 text-[11px] leading-relaxed text-content-secondary">{footnote}</p>
      ) : null}
    </section>
  );
}
