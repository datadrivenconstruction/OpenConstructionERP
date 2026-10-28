// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Cases module (user-authored case scenarios).
 * Endpoints prefixed with /v1/cases/.
 *
 * Wire convention: snake_case, both ways. The backend speaks snake_case and
 * the other feature clients (assemblies, dwg-takeoff) keep it verbatim rather
 * than mapping to camelCase, so the payload types below mirror the Pydantic
 * schemas field for field. The ONE place that converts is `caseToPlaybook`,
 * which produces the camelCase `Playbook` the shipped case components render;
 * that is a shape change, not a naming policy.
 *
 * Two id spaces meet here. A shipped playbook is a source file and its id is
 * the file slug; an authored case is a database row and its id is a UUID. A
 * pin points at either one, which is what `case_source` on a pin distinguishes,
 * so an authored case gets a prefixed playbook id (see `authoredPlaybookId`)
 * that cannot collide with a slug and can be turned back into the UUID.
 */

import { apiGet, apiPost, apiPut, apiDelete } from '@/shared/lib/api';
import type {
  CaseCategory,
  CompanyType,
  LifecycleStage,
  Playbook,
  PlaybookStep,
  ProfessionalRole,
  StepFlowItem,
} from './types';

/* ── Types ─────────────────────────────────────────────────────────────── */

/** Where a pinned case lives: a shipped playbook file, or a stored case. */
export type PinSource = 'builtin' | 'custom';

/**
 * Steps per case, mirroring `MAX_STEPS` in the module's `schemas.py`. The
 * backend rejects a longer list, so the editor caps on the same number rather
 * than letting the author write a 41st step and lose it on save.
 */
export const MAX_CASE_STEPS = 40;

/**
 * One step of an authored case, on the wire.
 *
 * Flat text, no i18n keys: the author writes in their own language and nobody
 * translates it afterwards. `to` is validated server-side as an in-app path
 * (a leading single slash plus an optional query), so an external or script
 * URL never reaches this type.
 */
export interface CaseStepWire {
  id: string;
  title: string;
  what: string;
  why: string;
  module_label: string;
  to: string;
  icon: string;
  inputs: string[];
  outputs: string[];
  inputs_hint: string;
  outputs_hint: string;
}

/**
 * The writable half of a case, shared by create and update.
 *
 * Optional here means the backend defaults it, not that it is left alone on
 * update: `PUT /{case_id}` replaces the whole case, so a field omitted from an
 * update goes back to its default rather than keeping its stored value. Send
 * the full case the editor is holding.
 */
export interface CaseBody {
  title: string;
  description?: string;
  long_description?: string;
  category: CaseCategory;
  company_types?: string[];
  roles?: string[];
  stage?: string;
  est_minutes?: number;
  icon?: string;
  steps?: CaseStepWire[];
  /** Id of the shipped playbook this case was copied from, when it was. */
  source_playbook_id?: string;
  /** Shared cases are readable by everyone and editable only by the author.
   *  Sharing is refused while validation reports an error (HTTP 422). */
  is_shared?: boolean;
}

/**
 * One stored case as the reader receives it.
 *
 * `category`, `company_types`, `roles` and `stage` arrive as plain strings
 * because that is how the column stores them; `caseToPlaybook` is what checks
 * them against the frontend unions.
 */
export interface CaseResponse {
  id: string;
  owner_id: string;
  title: string;
  description: string;
  long_description: string;
  category: string;
  company_types: string[];
  roles: string[];
  stage: string;
  est_minutes: number;
  icon: string;
  steps: CaseStepWire[];
  source_playbook_id: string;
  is_shared: boolean;
  created_at: string;
  updated_at: string;
  /** Whether the CALLER may edit this case, computed per request. A shared
   *  case is readable by the whole team and writable only by its author, so
   *  this is false on someone else's shared case. */
  can_edit: boolean;
}

/**
 * One validation finding shown beside the case in the editor.
 *
 * `key` is what the reader translates; `message` is the English the rule wrote
 * and is only shown when a locale has no string for the key yet.
 */
export interface CaseFinding {
  key: string;
  rule_id: string;
  severity: string;
  message: string;
  suggestion: string;
  details: Record<string, unknown>;
  /** True when the row says a check could not run, rather than saying anything
   *  about the case. Both kinds arrive in the same list and an ordinary remark
   *  is the only thing they read as without this, so the editor separates them
   *  on it: "we did not check this part" and "we checked it and here is what we
   *  think" are different messages to the person writing the case. */
  is_engine_error: boolean;
}

/** A saved case plus what validation made of it. */
export interface CaseSaveResponse {
  case: CaseResponse;
  findings: CaseFinding[];
}

/** Pin a case to a project for the calling user. */
export interface PinRequestBody {
  project_id: string;
  case_source: PinSource;
  case_id: string;
  sort_order?: number;
  note?: string;
}

/** One pinned case. */
export interface PinResponse {
  id: string;
  user_id: string;
  project_id: string;
  case_source: string;
  case_id: string;
  sort_order: number;
  note: string;
  created_at: string;
  updated_at: string;
}

/* ── Cases CRUD ────────────────────────────────────────────────────────── */

export interface ListCasesParams {
  category?: string;
  /** Only the caller's own cases; the default also returns shared ones. */
  mine_only?: boolean;
}

/** Cases the caller may read: their own, plus everyone's shared ones. */
export async function fetchCases(params?: ListCasesParams): Promise<CaseResponse[]> {
  const query = new URLSearchParams();
  if (params?.category) query.set('category', params.category);
  // Only sent when true: the backend already defaults it to false, and an
  // explicit `mine_only=false` would differ from the omitted form only in the
  // cache key, splitting one response into two entries.
  if (params?.mine_only) query.set('mine_only', 'true');
  const qs = query.toString();
  return apiGet<CaseResponse[]>(`/v1/cases/${qs ? `?${qs}` : ''}`);
}

export async function fetchCase(caseId: string): Promise<CaseResponse> {
  return apiGet<CaseResponse>(`/v1/cases/${caseId}`);
}

export async function createCase(body: CaseBody): Promise<CaseSaveResponse> {
  return apiPost<CaseSaveResponse, CaseBody>('/v1/cases/', body);
}

/** Replace a case. Only the author may write to it (403 otherwise). */
export async function updateCase(caseId: string, body: CaseBody): Promise<CaseSaveResponse> {
  return apiPut<CaseSaveResponse, CaseBody>(`/v1/cases/${caseId}`, body);
}

/** Delete a case and every pin pointing at it. Only the author may. */
export async function deleteCase(caseId: string): Promise<void> {
  return apiDelete(`/v1/cases/${caseId}`);
}

/**
 * Fork a STORED case into a new private case owned by the caller.
 *
 * Starting from one of the shipped playbooks is not this call: those live in
 * the frontend bundle and the backend has never seen them, so post their
 * contents to {@link createCase} with `source_playbook_id` set to record where
 * the copy came from.
 */
export async function duplicateCase(caseId: string, title?: string): Promise<CaseResponse> {
  return apiPost<CaseResponse>(`/v1/cases/${caseId}/duplicate`, {
    ...(title ? { title } : {}),
  });
}

/* ── Pins ──────────────────────────────────────────────────────────────── */

/** The caller's pinned cases, in the order they arranged them.
 *  Named for cases specifically: the DWG takeoff client exports its own
 *  `fetchPins` for drawing pins, which are a different thing entirely. */
export async function fetchCasePins(projectId?: string): Promise<PinResponse[]> {
  const qs = projectId ? `?${new URLSearchParams({ project_id: projectId }).toString()}` : '';
  return apiGet<PinResponse[]>(`/v1/cases/pins/${qs}`);
}

/** Pin a case to a project. Idempotent - re-pinning returns the same row. */
export async function pinCase(body: PinRequestBody): Promise<PinResponse> {
  return apiPost<PinResponse, PinRequestBody>('/v1/cases/pins/', body);
}

/** Unpin a case. Idempotent - unpinning what is not pinned still succeeds. */
export async function unpinCase(
  projectId: string,
  caseSource: PinSource,
  caseId: string,
): Promise<void> {
  const params = new URLSearchParams({
    project_id: projectId,
    case_source: caseSource,
    case_id: caseId,
  });
  return apiDelete(`/v1/cases/pins/?${params.toString()}`);
}

/** Set the order of the caller's pins on one project in a single call. */
export async function reorderCasePins(
  projectId: string,
  pinIds: string[],
): Promise<PinResponse[]> {
  return apiPost<PinResponse[]>('/v1/cases/pins/reorder', {
    project_id: projectId,
    pin_ids: pinIds,
  });
}

/* ── Stored case -> Playbook ───────────────────────────────────────────── */

/**
 * Valid values of the frontend unions, as runtime sets.
 *
 * `Record<Union, true>` is exhaustive in both directions: a member added to
 * the union in `types.ts` and missing here is a compile error, and so is a
 * member here that the union does not have. The alternative was to derive the
 * sets from `CATEGORY_META` / `ROLE_META` / `STAGE_META` / `COMPANY_TYPE_META`,
 * which are the documented sources of truth but pull React and the whole
 * lucide-react icon set into an API module that otherwise imports nothing.
 * Drift is impossible either way, so this file stays dependency-free.
 */
const CASE_CATEGORY_SET: Record<CaseCategory, true> = {
  estimating: true,
  tendering: true,
  planning: true,
  bim: true,
  site: true,
  quality: true,
  commercial: true,
  handover: true,
};

const COMPANY_TYPE_SET: Record<CompanyType, true> = {
  'general-contractor': true,
  subcontractor: true,
  'cost-consultant': true,
  designer: true,
  'developer-client': true,
  'project-manager': true,
  'bim-consultant': true,
  'owner-operator': true,
};

const ROLE_SET: Record<ProfessionalRole, true> = {
  estimator: true,
  'quantity-surveyor': true,
  'site-manager': true,
  'project-manager': true,
  'bim-coordinator': true,
  'procurement-buyer': true,
  planner: true,
  'hse-officer': true,
  'design-lead': true,
  'document-controller': true,
  'commercial-manager': true,
  accountant: true,
  'contract-administrator': true,
  'finance-manager': true,
  foreman: true,
};

const STAGE_SET: Record<LifecycleStage, true> = {
  define: true,
  design: true,
  estimate: true,
  procure: true,
  plan: true,
  build: true,
  handover: true,
  operate: true,
};

// `in` would also answer true for inherited keys, so a wire value of
// "constructor" or "toString" would pass every one of these guards.
const has = (set: object, value: string): boolean =>
  Object.prototype.hasOwnProperty.call(set, value);

const isCaseCategory = (value: string): value is CaseCategory => has(CASE_CATEGORY_SET, value);
const isCompanyType = (value: string): value is CompanyType => has(COMPANY_TYPE_SET, value);
const isRole = (value: string): value is ProfessionalRole => has(ROLE_SET, value);
const isStage = (value: string): value is LifecycleStage => has(STAGE_SET, value);

/**
 * The category an authored case falls back to when its stored value is not one
 * the frontend knows. The backend accepts the same eight and nothing else, so
 * this only fires on version skew between a newer server and an older bundle.
 * Passing the unknown value through instead would leave `CATEGORY_BY_ID[...]`
 * undefined and take the card renderer down with it.
 */
const FALLBACK_CATEGORY: CaseCategory = 'estimating';

/** Prefix that marks a playbook id as an authored case rather than a file slug. */
export const AUTHORED_CASE_ID_PREFIX = 'custom-';

/**
 * Where authored cases sort relative to the shipped ones. The shipped set
 * currently runs from `order` 5 to 1046, so this base puts authored cases
 * after all of them without a per-case decision.
 */
export const AUTHORED_CASE_ORDER_BASE = 10_000;

/** The playbook id for a stored case. Stable: it is derived from the UUID. */
export function authoredPlaybookId(caseId: string): string {
  return `${AUTHORED_CASE_ID_PREFIX}${caseId}`;
}

/**
 * The case UUID behind a playbook id, or null when the id is a shipped
 * playbook's file slug. This is the inverse of {@link authoredPlaybookId} and
 * the only supported way to tell the two id spaces apart.
 */
export function caseIdFromPlaybookId(playbookId: string): string | null {
  if (!playbookId.startsWith(AUTHORED_CASE_ID_PREFIX)) return null;
  const caseId = playbookId.slice(AUTHORED_CASE_ID_PREFIX.length);
  return caseId.length > 0 ? caseId : null;
}

const toFlowItems = (labels: string[]): StepFlowItem[] =>
  labels.filter((label) => label.length > 0).map((label) => ({ label }));

function stepToPlaybookStep(step: CaseStepWire): PlaybookStep {
  const inputs = toFlowItems(step.inputs ?? []);
  const outputs = toFlowItems(step.outputs ?? []);
  return {
    id: step.id,
    // See the note on `caseToPlaybook` for why these are empty rather than absent.
    titleKey: '',
    titleDefault: step.title,
    whatKey: '',
    whatDefault: step.what,
    whyKey: '',
    whyDefault: step.why,
    moduleLabel: step.module_label,
    to: step.to,
    ...(step.icon ? { icon: step.icon } : {}),
    ...(inputs.length > 0 ? { inputs } : {}),
    ...(outputs.length > 0 ? { outputs } : {}),
    ...(step.inputs_hint ? { inputsHintDefault: step.inputs_hint } : {}),
    ...(step.outputs_hint ? { outputsHintDefault: step.outputs_hint } : {}),
  };
}

/**
 * Convert a stored case into the `Playbook` shape, so an authored case renders
 * through the same components as the shipped ones. Pure: no fetching, no
 * store, same input gives the same output.
 *
 * The i18n split is the whole point. A shipped playbook carries a key PLUS an
 * English default because its text is translated into every locale at build
 * time; an authored case carries only text, because the author writes in their
 * own language and nobody translates it afterwards. So every `*Default` field
 * gets the typed text and no `*Key` field names a real key.
 *
 * The required key fields are set to EMPTY STRING rather than left undefined,
 * and that is deliberate on two counts. `Playbook.titleKey` and the step's
 * `titleKey` / `whatKey` / `whyKey` are declared as required strings, so
 * undefined does not type-check; and the reader calls them unguarded, as
 * `t(step.titleKey, { defaultValue: step.titleDefault })`. i18next returns ''
 * for a null or undefined key WITHOUT consulting the default, so an undefined
 * key would blank the author's text on screen, while an empty key misses in
 * the bundle and falls through to the default, which is exactly the text we
 * want. The genuinely optional keys (`moduleLabelKey`, `inputsHintKey`,
 * `outputsHintKey`) are omitted, because those readers do test for a key first.
 *
 * `order` is not a stored field. Pass `AUTHORED_CASE_ORDER_BASE + index` when
 * rendering a list to preserve the order the server returned.
 */
export function caseToPlaybook(source: CaseResponse, order = AUTHORED_CASE_ORDER_BASE): Playbook {
  const roles = (source.roles ?? []).filter(isRole);
  const stage = source.stage;
  return {
    id: authoredPlaybookId(source.id),
    order,
    category: isCaseCategory(source.category) ? source.category : FALLBACK_CATEGORY,
    companyTypes: (source.company_types ?? []).filter(isCompanyType),
    // Omitted rather than empty so the derivations in `roles.ts` / `stages.ts`
    // run: an empty array is a case that matches no role, a missing one is a
    // case whose roles are inferred from its discipline.
    ...(roles.length > 0 ? { roles } : {}),
    ...(isStage(stage) ? { stage } : {}),
    titleKey: '',
    titleDefault: source.title,
    descKey: '',
    descDefault: source.description,
    ...(source.long_description ? { longDescDefault: source.long_description } : {}),
    estMinutes: source.est_minutes,
    ...(source.icon ? { icon: source.icon } : {}),
    steps: (source.steps ?? []).map(stepToPlaybookStep),
  };
}
