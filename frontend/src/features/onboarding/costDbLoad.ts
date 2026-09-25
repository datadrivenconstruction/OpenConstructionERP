// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Data Setup step's "Load Database" button, run as a provisioning job.
//
// The button used to POST /costs/load-cwicr/{region} and wait on the response,
// aborting after five minutes. A large region takes longer than that, so the
// user read "Connection error" while the import carried on and finished on the
// server. The load now goes through the same onboarding job the country install
// uses, and the wizard follows that job to its end, however long it runs.

import i18n from 'i18next';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import {
  fetchOnboardingStatus,
  provisionOnboarding,
  type OnboardingJobState,
} from './onboardingApi';
import { jobOutcome } from './provisionOutcome';

const POLL_MS = 1500;
/** Polls in a row that may fail before the wizard stops following the job. */
const MAX_MISSED_POLLS = 40;

/**
 * How a manual cost base load ended. `unconfirmed` means the wizard lost the
 * server before the job finished: the load may still complete, so it is
 * neither reported as loaded nor as failed.
 */
export type CostDbLoadOutcome = 'completed' | 'partial' | 'failed' | 'unconfirmed';

export interface CostDbLoadResult {
  outcome: CostDbLoadOutcome;
  /** The job's last known state, null when it could not be started. */
  job: OnboardingJobState | null;
}

export interface FollowCostDbLoadOptions {
  pollMs?: number;
  maxMissedPolls?: number;
  /** Called with every state the job reports while it runs. */
  onProgress?: (job: OnboardingJobState) => void;
}

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/** Start the region's load as a background job and resolve once it has ended. */
export async function followCostDbLoad(
  region: string,
  opts: FollowCostDbLoadOptions = {},
): Promise<CostDbLoadResult> {
  const pollMs = opts.pollMs ?? POLL_MS;
  const maxMissed = opts.maxMissedPolls ?? MAX_MISSED_POLLS;

  let job: OnboardingJobState | undefined;
  try {
    const jobs = await provisionOnboarding({ region, demo_ids: [] });
    job = jobs.find((j) => j.kind === 'onboarding.load_cwicr') ?? jobs[0];
  } catch {
    return { outcome: 'failed', job: null };
  }
  if (!job) return { outcome: 'failed', job: null };

  let missed = 0;
  for (;;) {
    const outcome = jobOutcome(job);
    if (outcome) return { outcome, job };
    opts.onProgress?.(job);

    await wait(pollMs);
    let latest: OnboardingJobState | undefined;
    try {
      latest = (await fetchOnboardingStatus([job.id]))[0];
    } catch {
      latest = undefined;
    }
    if (latest) {
      job = latest;
      missed = 0;
    } else if (++missed >= maxMissed) {
      return { outcome: 'unconfirmed', job };
    }
  }
}

/** Cost items the region holds after the load, falling back to what was added. */
export function costDbItemCount(job: OnboardingJobState | null): number {
  return job?.total ?? job?.imported ?? 0;
}

export interface CostDbLoadReport {
  toast: { type: 'success' | 'warning' | 'error'; title: string; message?: string };
  /** The line the upload queue panel shows for the finished task. */
  queueLine: string;
}

const formatCount = (n: number) => n.toLocaleString(getNumberLocale());

/** What the user is told about a finished load. The server's error text is never shown. */
export function costDbLoadReport(result: CostDbLoadResult, dbName: string): CostDbLoadReport {
  if (result.outcome === 'failed') {
    const title = i18n.t('onboarding.db_load_failed', {
      defaultValue: '{{name}} could not be loaded',
      name: dbName,
    });
    return { toast: { type: 'error', title }, queueLine: title };
  }
  if (result.outcome === 'unconfirmed') {
    const title = i18n.t('onboarding.db_load_unconfirmed', {
      defaultValue: 'Lost contact while loading {{name}}. The load may still finish on the server.',
      name: dbName,
    });
    return { toast: { type: 'warning', title }, queueLine: title };
  }
  const title = i18n.t('onboarding.db_loaded', { defaultValue: '{{name}} loaded', name: dbName });
  // Counts sit after a colon, so the strings need no plural forms.
  const available = i18n.t('onboarding.db_loaded_items', {
    defaultValue: 'Cost items available: {{items}}',
    items: formatCount(costDbItemCount(result.job)),
  });
  if (result.outcome === 'partial') {
    const leftOut = i18n.t('onboarding.db_loaded_left_out', {
      defaultValue: 'Cost items left out: {{items}}',
      items: formatCount(result.job?.failed_items ?? 0),
    });
    return { toast: { type: 'warning', title, message: leftOut }, queueLine: leftOut };
  }
  return { toast: { type: 'success', title, message: available }, queueLine: available };
}
