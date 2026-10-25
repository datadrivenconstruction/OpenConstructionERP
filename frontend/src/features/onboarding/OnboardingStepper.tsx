// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The row of steps at the top of the wizard, and the rule for which of them a
 * reader may open.
 *
 * Every step the reader has already reached is a button, so a choice made
 * earlier can be changed without walking Back through the steps in between.
 * A step that is not reachable yet stays in the row, visibly dimmed, and says
 * why in its tooltip.
 */

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Check } from 'lucide-react';

export const STEP_COUNT = 7;

/** Step indices, so the rules below read as words. */
export const STEP = {
  welcome: 0,
  start: 1,
  profile: 2,
  modules: 3,
  look: 4,
  data: 5,
  finish: 6,
} as const;

export type StepLock = 'ahead' | 'pack_data' | 'pack_pending';

export interface StepReach {
  /** The step on screen. */
  current: number;
  /** The furthest step the reader has been on. */
  maxReached: number;
  /** A ready-made pack install was started (and may still be running). */
  packFlow: boolean;
  /** That install's language is ready, so Finish may save without racing it. */
  packReady: boolean;
}

/**
 * Why a step cannot be opened right now, or null when it can.
 *
 * Outside a pack install a step opens once the reader has been there. Inside
 * one the install runs on its own, so Profile, Modules and Appearance open
 * from the moment it starts; Data stays closed because the pack brings its own
 * cost data, and Finish waits until the pack's language is ready because
 * Finish writes the reader's modules and must not overtake the install.
 */
export function stepLock(index: number, reach: StepReach): StepLock | null {
  if (index === reach.current) return null;
  if (reach.packFlow) {
    if (index <= STEP.start) return null;
    if (index === STEP.data) return 'pack_data';
    if (index === STEP.finish) return reach.packReady ? null : 'pack_pending';
    return null;
  }
  return index <= reach.maxReached ? null : 'ahead';
}

/** The step Next opens from `from`. A pack install skips Data. */
export function nextStep(from: number, packFlow: boolean): number {
  if (packFlow && from === STEP.look) return STEP.finish;
  return Math.min(from + 1, STEP_COUNT - 1);
}

/**
 * The step Back opens from `from`: the nearest earlier step the reader has
 * actually been on. Quick Start jumps from Start to Data, so Back from Data
 * returns to Start rather than to a Profile step it never showed.
 */
export function previousStep(from: number, visited: ReadonlySet<number>, packFlow: boolean): number {
  for (let i = from - 1; i > STEP.start; i -= 1) {
    if (packFlow && i === STEP.data) continue;
    if (visited.has(i)) return i;
  }
  return from <= STEP.start ? Math.max(from - 1, 0) : STEP.start;
}

export function OnboardingStepper({
  reach,
  onGo,
}: {
  reach: StepReach;
  onGo: (index: number) => void;
}) {
  const { t } = useTranslation();
  const labels = [
    t('onboarding.step_welcome', { defaultValue: 'Welcome' }),
    t('onboarding.step_start', { defaultValue: 'Start' }),
    t('onboarding.step_profile', { defaultValue: 'Profile' }),
    t('onboarding.step_modules', { defaultValue: 'Modules' }),
    t('onboarding.step_look', { defaultValue: 'Appearance' }),
    t('onboarding.step_data', { defaultValue: 'Data' }),
    t('onboarding.step_finish', { defaultValue: 'Finish' }),
  ];
  const reasons: Record<StepLock, string> = {
    ahead: t('onboarding.stepper_locked_ahead', { defaultValue: 'Finish the earlier steps first' }),
    pack_data: t('onboarding.stepper_locked_pack_data', {
      defaultValue: 'Your ready-made pack already brings its own data',
    }),
    pack_pending: t('onboarding.stepper_locked_pack_pending', {
      defaultValue: 'Available once your pack has applied its language',
    }),
  };

  const current = reach.current;
  // Percent of the track filled, independent of how the dots are laid out so
  // the line stays continuous on narrow screens where the labels are hidden.
  const pct = STEP_COUNT > 1 ? (current / (STEP_COUNT - 1)) * 100 : 0;

  return (
    <nav
      className="w-full"
      aria-label={t('onboarding.stepper_label', { defaultValue: 'Setup steps' })}
      data-testid="onboarding-stepper"
    >
      <div className="relative">
        {/* Track behind everything: continuous line. */}
        <div className="absolute top-[14px] start-[14px] end-[14px] h-[3px] rounded-full bg-border-light dark:bg-white/10" />
        {/* Filled portion: animates on step change. */}
        <div
          className="absolute top-[14px] start-[14px] h-[3px] rounded-full bg-gradient-to-r from-oe-blue via-blue-500 to-purple-500 transition-[width] duration-500 ease-oe"
          style={{ width: `calc(${pct}% - ${pct === 0 ? 0 : 14}px)` }}
          aria-hidden
        />
        <ol className="relative flex items-start justify-between">
          {labels.map((label, i) => {
            const here = i === current;
            const done = i < current;
            const lock = stepLock(i, reach);
            const enabled = lock === null;
            const reason = lock ? reasons[lock] : undefined;
            return (
              <li key={i} className="flex min-w-0 flex-1 justify-center">
                <button
                  type="button"
                  aria-current={here ? 'step' : undefined}
                  aria-disabled={enabled ? undefined : true}
                  aria-label={reason ? `${label}. ${reason}` : label}
                  title={reason ?? label}
                  data-testid={`onboarding-step-${i}`}
                  onClick={() => {
                    if (enabled && !here) onGo(i);
                  }}
                  className={clsx(
                    'group flex min-w-0 flex-col items-center gap-1.5 rounded-lg px-1 pb-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/50',
                    enabled && !here ? 'cursor-pointer' : here ? 'cursor-default' : 'cursor-not-allowed',
                  )}
                >
                  <span
                    className={clsx(
                      'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-2xs font-bold transition-all duration-500 ease-oe',
                      here
                        ? 'bg-white dark:bg-surface-elevated text-oe-blue ring-2 ring-oe-blue shadow-[0_0_0_4px_rgba(37,99,235,0.18)] scale-110'
                        : enabled
                          ? 'bg-oe-blue text-white shadow-sm group-hover:ring-2 group-hover:ring-oe-blue/40'
                          : 'bg-surface-secondary text-content-tertiary opacity-60',
                    )}
                  >
                    {done && enabled ? <Check size={13} strokeWidth={3} /> : i + 1}
                  </span>
                  <span
                    className={clsx(
                      'hidden whitespace-nowrap text-[10px] font-medium transition-colors sm:block',
                      here
                        ? 'text-oe-blue'
                        : enabled
                          ? 'text-content-secondary group-hover:text-content-primary'
                          : 'text-content-quaternary opacity-70',
                    )}
                  >
                    {label}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </div>
    </nav>
  );
}
