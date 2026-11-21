// Design module (ERP side of the design editor link).
import { ApiError, apiGet, apiPost, apiPut } from '@/shared/lib/api';
import type { BriefDoc } from './data/briefModel';
import type { RevisionView } from './data/revisions';
import type { Impact } from './data/acceptance';
import type { EstimateRule, EstimateView } from './data/estimate';
import type { LinkFile } from './data/offer';
import type { ChangeOrderMode, ChangeOrderSettings, RevisionChangeOrder } from './data/changeOrders';

/** Major version of the design link contract this form speaks; the server answers 426 when it does not. */
export const LINK_VERSION = '1';
const LINK_HEADERS = { 'X-DDC-Link': LINK_VERSION };

const base = (projectId: string) => `/v1/design/projects/${projectId}/brief`;

/** The current brief, or null when the project has none yet. */
export async function fetchBrief(projectId: string): Promise<BriefDoc | null> {
  try {
    return await apiGet<BriefDoc>(base(projectId), { headers: LINK_HEADERS });
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

/**
 * Save as a new version. `basedOn` is the version the edit started from (0 for the first save).
 * `draft` stores a brief that still lacks required values; the server accepts only that gap.
 */
export function saveBrief(projectId: string, doc: BriefDoc, basedOn: number, draft = false): Promise<BriefDoc> {
  return apiPut<BriefDoc, BriefDoc>(`${base(projectId)}${draft ? '?draft=true' : ''}`, doc, {
    headers: { ...LINK_HEADERS, ...(basedOn > 0 ? { 'If-Match': `"${basedOn}"` } : {}) },
  });
}

/** Confirm the values at `pointers` in the stored version `basedOn`. */
export function confirmBrief(projectId: string, pointers: string[], basedOn: number): Promise<BriefDoc> {
  return apiPost<BriefDoc, { pointers: string[] }>(`${base(projectId)}/confirm`, { pointers }, {
    headers: { ...LINK_HEADERS, 'If-Match': `"${basedOn}"` },
  });
}

export interface ImportedModel {
  bim_model_id: string;
  name: string;
  model_format: string;
  element_count: number;
  created_at: string | null;
}

/** Converter-imported models of the project that are not revisions yet, oldest first. */
export function fetchImportedModels(projectId: string): Promise<ImportedModel[]> {
  return apiGet<{ items: ImportedModel[] }>(`/v1/design/projects/${projectId}/imported-models?limit=500`).then((r) => r.items);
}

/** Wraps an imported model as a revision awaiting acceptance; 409 while the project is being edited. */
export function importModel(projectId: string, bimModelId: string): Promise<RevisionView> {
  return apiPost<RevisionView, { bim_model_id: string }>(
    `/v1/design/projects/${projectId}/revisions/import`, { bim_model_id: bimModelId },
  );
}

/** Revisions of a project, newest first. */
export function fetchRevisions(projectId: string): Promise<RevisionView[]> {
  return apiGet<{ items: RevisionView[] }>(`/v1/design/projects/${projectId}/revisions?limit=500`).then((r) => r.items);
}

export interface ProjectAccess {
  can_accept: boolean;
  currency: string | null;
  lock: { held_by: string; mine: boolean; expires_at: string } | null;
}

export function fetchAccess(projectId: string): Promise<ProjectAccess> {
  return apiGet<ProjectAccess>(`/v1/design/projects/${projectId}/access`);
}

/** Position-level change if the revision were accepted now; nothing is written. */
export function fetchImpact(revisionId: string): Promise<Impact> {
  return apiGet<Impact>(`/v1/design/revisions/${revisionId}/impact`);
}

/**
 * Accepting recomputes the estimate in the same transaction: both change or neither. `changeOrder` answers the
 * project setting "ask"; with "always" the server drafts the change order regardless.
 */
export function acceptRevision(revisionId: string, comment: string, changeOrder?: boolean): Promise<RevisionView> {
  return apiPost<RevisionView, { comment: string | null; change_order?: boolean }>(
    `/v1/design/revisions/${revisionId}/accept`,
    { comment: comment.trim() || null, ...(changeOrder === undefined ? {} : { change_order: changeOrder }) },
  );
}

export function fetchChangeOrderSettings(projectId: string): Promise<ChangeOrderSettings> {
  return apiGet<ChangeOrderSettings>(`/v1/design/projects/${projectId}/change-orders/settings`);
}

export function saveChangeOrderMode(projectId: string, mode: ChangeOrderMode): Promise<{ mode: ChangeOrderMode }> {
  return apiPut<{ mode: ChangeOrderMode }, { mode: ChangeOrderMode }>(
    `/v1/design/projects/${projectId}/change-orders/settings`, { mode },
  );
}

/** The draft change order of an accepted revision, if one was made. */
export function fetchRevisionChangeOrder(revisionId: string): Promise<RevisionChangeOrder> {
  return apiGet<RevisionChangeOrder>(`/v1/design/revisions/${revisionId}/change-order`);
}

/** Draft it now from the cost snapshot taken at acceptance; returns the existing one instead of a second. */
export function createRevisionChangeOrder(revisionId: string): Promise<RevisionChangeOrder> {
  return apiPost<RevisionChangeOrder, Record<string, never>>(`/v1/design/revisions/${revisionId}/change-order`, {});
}

export function rejectRevision(revisionId: string, comment: string): Promise<RevisionView> {
  return apiPost<RevisionView, { comment: string }>(`/v1/design/revisions/${revisionId}/reject`, { comment: comment.trim() });
}

/** A one-use code the editor exchanges for a session; the UI saves it as a .ddclink file. */
export function createLink(projectId: string, action: 'new' | 'open', revisionId?: string): Promise<LinkFile> {
  return apiPost<LinkFile, { project_id: string; action: string; revision_id?: string }>('/v1/design/link/code', {
    project_id: projectId,
    action,
    ...(revisionId ? { revision_id: revisionId } : {}),
  });
}

/** The project estimate: positions by rule, the range, and the check against it. `{estimate: false}` before rules ran. */
export function fetchEstimate(projectId: string): Promise<EstimateView> {
  return apiGet<EstimateView>(`/v1/design/projects/${projectId}/estimate`);
}

export function fetchEstimateRules(projectId: string): Promise<EstimateRule[]> {
  return apiGet<{ items: EstimateRule[] }>(`/v1/design/projects/${projectId}/estimate/rules?limit=500`).then((r) => r.items);
}

export function installStarterRules(projectId: string, country: string): Promise<{ rules: number; country: string }> {
  return apiPost<{ rules: number; country: string }, { country: string }>(
    `/v1/design/projects/${projectId}/estimate/rules/starter`, { country: country.trim().toUpperCase() },
  );
}

/** Apply the rules to the latest accepted revision. */
export function runEstimate(projectId: string): Promise<{ revision_id: string; positions: number }> {
  return apiPost<{ revision_id: string; positions: number }, Record<string, never>>(
    `/v1/design/projects/${projectId}/estimate/run`, {},
  );
}

/** Price a position from an ERP cost item (the picker); the server checks unit and currency. */
export function priceFromCostItem(projectId: string, positionId: string, costItemId: string): Promise<void> {
  return apiPost<void, { cost_item_id: string }>(
    `/v1/design/projects/${projectId}/estimate/positions/${positionId}/price`, { cost_item_id: costItemId },
  );
}

export function saveOverrideReason(projectId: string, positionId: string, reason: string): Promise<void> {
  return apiPut<void, { reason: string }>(
    `/v1/design/projects/${projectId}/estimate/positions/${positionId}/override-reason`, { reason: reason.trim() },
  );
}

/** Server generation (R13): the job as ddc-job/1 says it. */
export interface GenerationJob {
  job_id: string;
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled';
  progress: number;
  log_tail: string[];
  revision_id?: string;
  error?: string | null;
}

export interface GenerationState {
  enabled: boolean;
  reason: string | null;
  job: GenerationJob | null;
}

export function fetchGeneration(projectId: string): Promise<GenerationState> {
  return apiGet<GenerationState>(`/v1/design/projects/${projectId}/generation`);
}

export function startGeneration(projectId: string, briefVersion: number): Promise<{ job_id: string }> {
  return apiPost<{ job_id: string }, { brief_version: number }>(`/v1/design/projects/${projectId}/generate`, {
    brief_version: briefVersion,
  });
}

export function cancelGeneration(jobId: string): Promise<GenerationJob> {
  return apiPost<GenerationJob, Record<string, never>>(`/v1/design/jobs/${jobId}/cancel`, {});
}

/** R5 extraction: a draft brief with every value cited and marked proposed; nothing is written. */
export interface Extraction {
  brief: BriefDoc;
  rejected: { pointer: string; reason: string; detail: string }[];
  notes: string[];
  /** `confirmed`: read again, already confirmed in the brief, kept as they are. */
  summary: { proposed: string[]; defaults: string[]; questions: string[]; rejected: number; confirmed?: string[] };
  used_model: string | null;
  tokens: number;
}

export function extractBrief(projectId: string, text: string, current: BriefDoc | null): Promise<Extraction> {
  // editor: the person's editor AI choice applies (ERP settings when there is none)
  return apiPost<Extraction, { text: string; use_ai: boolean; base: BriefDoc | null; editor: boolean }>(
    `${base(projectId)}/extract`, { text, use_ai: true, base: current, editor: true },
  );
}


/** Whether the person has an AI service set up in the ERP (read from their own AI settings; a failed read = no). */
export async function fetchAiSettings(): Promise<unknown> {
  try {
    return await apiGet<unknown>('/v1/ai/settings/');
  } catch {
    return null;
  }
}
