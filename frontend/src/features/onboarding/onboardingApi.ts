// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Thin client for the onboarding provisioning API (backend module
// `oe_onboarding`, mounted at /api/v1/onboarding). The wizard uses this to push
// the heavy first-run work - importing a regional cost base, installing a
// sample project - to the server as background jobs and then poll their live
// state, instead of awaiting the raw imports inline and blocking the user.

import { apiGet, apiPost } from '@/shared/lib/api';

/** One background provisioning job's live state, as returned by the server. */
export interface OnboardingJobState {
  id: string;
  /** e.g. 'onboarding.load_cwicr' | 'onboarding.install_demo'. */
  kind: string;
  /** The item being provisioned (region id or demo id), when known. */
  arg: string | null;
  /** pending | started | success | failed | cancelled. */
  state: string;
  /**
   * How the job ended, null while it runs. `partial` means it finished but left
   * something out (see `failed_items`). Read this, not `state`: a job can reach
   * `success` and still be partial.
   */
  outcome: OnboardingJobOutcome | null;
  /** 0..100 progress reported by the handler. */
  pct: number;
  /** Latest human progress message, when the handler set one. */
  message: string | null;
  /** Server-side reason when the job failed. For logs, not for the user. */
  error: string | null;
  /** Items the job added, when it reports them. */
  imported?: number | null;
  /** Items now present for the job's subject. */
  total?: number | null;
  /** Items the job had to leave out. */
  failed_items?: number;
}

/** The truthful ending of a finished onboarding job. */
export type OnboardingJobOutcome = 'completed' | 'partial' | 'failed';

/** What to provision in the background. Mirrors the backend `ProvisionRequest`. */
export interface ProvisionOnboardingBody {
  region?: string | null;
  demo_ids?: string[];
}

interface JobsEnvelope {
  jobs: OnboardingJobState[];
}

/**
 * Kick off the heavy first-run work as background jobs. Returns the job states
 * (with ids) so the caller can poll {@link fetchOnboardingStatus}. Idempotent
 * on the server per user and item, so a retried call reuses the running job.
 */
export async function provisionOnboarding(
  body: ProvisionOnboardingBody,
): Promise<OnboardingJobState[]> {
  const res = await apiPost<JobsEnvelope, ProvisionOnboardingBody>(
    '/v1/onboarding/provision',
    body,
  );
  return res.jobs ?? [];
}

/** The caller's onboarding jobs, newest first (the server lists only their own). */
export async function listOnboardingJobs(): Promise<OnboardingJobState[]> {
  const res = await apiGet<JobsEnvelope>('/v1/onboarding/jobs/');
  return res.jobs ?? [];
}

/**
 * Poll the live state of previously provisioned jobs by id. Reads the caller's
 * job list, which the server scopes to the caller, and keeps the ids asked for.
 */
export async function fetchOnboardingStatus(ids: string[]): Promise<OnboardingJobState[]> {
  if (ids.length === 0) return [];
  const wanted = new Set(ids);
  return (await listOnboardingJobs()).filter((j) => wanted.has(j.id));
}
