// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How a background onboarding install ended, and what the user is told about it.
//
// The driver in OnboardingWizard used to resolve 'done' once every job had
// stopped, however it stopped, and the wizard read 'done' as ready. These
// helpers keep the three honest endings apart: every job complete, complete
// with items left out, and at least one job failed.

import i18n from 'i18next';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import type { OnboardingJobOutcome, OnboardingJobState } from './onboardingApi';

/** What `startBackgroundOnboardingProvision` resolves with. */
export interface OnboardingProvisionResult {
  /** 'backgrounded' when the grace window ran out with work still running. */
  phase: 'done' | 'backgrounded';
  /** The combined ending of every job, or null while any is still running. */
  outcome: OnboardingJobOutcome | null;
  /** Items the jobs had to leave out, summed. */
  failedItems: number;
}

/** The outcome of one job, falling back on its state for an older server. */
export function jobOutcome(job: OnboardingJobState): OnboardingJobOutcome | null {
  if (job.outcome) return job.outcome;
  if (job.state === 'failed' || job.state === 'cancelled') return 'failed';
  if (job.state === 'success') return 'completed';
  return null;
}

/** Combine the jobs of one install: any failure fails it, any gap makes it partial. */
export function combineOutcomes(jobs: OnboardingJobState[]): OnboardingJobOutcome | null {
  if (jobs.length === 0) return null;
  const outcomes = jobs.map(jobOutcome);
  if (outcomes.some((o) => o === null)) return null;
  if (outcomes.includes('failed')) return 'failed';
  if (outcomes.includes('partial')) return 'partial';
  return 'completed';
}

/** Items left out across the jobs of one install. */
export function failedItemCount(jobs: OnboardingJobState[]): number {
  return jobs.reduce((sum, j) => sum + (j.failed_items ?? 0), 0);
}

export interface CountryProvisionToast {
  type: 'success' | 'warning' | 'error';
  title: string;
}

/** The toast that closes a country install, matching how it really ended. */
export function countryProvisionToast(
  result: OnboardingProvisionResult,
  country: string,
): CountryProvisionToast {
  if (result.outcome === 'failed') {
    return {
      type: 'error',
      title: i18n.t('onboarding.bg_install_done_failed', {
        defaultValue: '{{country}} setup finished with errors',
        country,
      }),
    };
  }
  if (result.outcome === 'partial') {
    return {
      type: 'warning',
      title: i18n.t('onboarding.country_ready_partial', {
        defaultValue: '{{country}} is ready. Cost items left out: {{items}}',
        country,
        // Not `count`: the number sits after a colon, so it needs no plural
        // forms, and `count` would send i18next looking for them.
        items: result.failedItems.toLocaleString(getNumberLocale()),
      }),
    };
  }
  if (result.phase === 'backgrounded') {
    return {
      type: 'success',
      title: i18n.t('onboarding.pp_language_ready', {
        defaultValue: '{{country}} is ready, finishing setup in the background',
        country,
      }),
    };
  }
  return {
    type: 'success',
    title: i18n.t('onboarding.country_ready', { defaultValue: '{{country}} is ready', country }),
  };
}
