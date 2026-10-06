// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Typed client for the module builder
 * (``backend/app/modules/module_builder``, mounted at ``/api/v1/module-builder``)
 * and for the modules it produces.
 *
 * Two clients live here because they are two halves of one feature. The first
 * half describes and installs a module; the second half is how anyone then uses
 * it, and a module installed at runtime cannot ship a compiled screen, so the
 * platform renders one from the specification the module serves at
 * ``{base_path}/ui-spec``.
 *
 * Three rules this file exists to keep:
 *
 * 1. **``base_path`` always comes from the server.** The loader mounts a module
 *    at the hyphenated form of its key, and that rule lives in ``url_prefix_for``
 *    in ``spec.py``. Rebuilding it here as ``key.replace('_', '-')`` would be a
 *    second copy of a rule that belongs to the loader, and the two would drift
 *    the first time the mount changes. Every path below is derived from the
 *    ``base_path`` the API handed us.
 * 2. **Money and quantities are strings, end to end.** The generated schemas
 *    type them as ``Decimal``, which Pydantic serialises as a JSON string, and
 *    that is the point: a float cannot hold 0.1 and a contract sum is not
 *    allowed to be approximately right. They are never parsed into a JS number
 *    on the way through - see ``fields.ts``.
 * 3. **Shapes mirror ``schemas.py`` and ``spec.py`` field for field**, including
 *    the fields with defaults, because ``/ui-spec`` returns a full
 *    ``model_dump`` and the renderer reads every one of them.
 *
 * Paths carry no trailing slash: every route in ``module_builder/router.py`` and
 * in a generated ``router.py`` is declared without one, and the other spelling
 * only works by way of a 307 redirect that a POST body should not depend on.
 */
import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

// ---------------------------------------------------------------------------
// The specification (mirrors backend/app/modules/module_builder/spec.py)
// ---------------------------------------------------------------------------

/** ``FieldType`` in spec.py. */
export type ModuleFieldType =
  | 'text'
  | 'long_text'
  | 'integer'
  | 'number'
  | 'money'
  | 'date'
  | 'datetime'
  | 'boolean'
  | 'select'
  | 'link';

/**
 * What a `link` field may point at (``LinkTarget`` in spec.py). A link is a
 * reference to a record another module owns, stored as its id.
 */
export type LinkTarget = 'contract' | 'contact' | 'schedule_activity' | 'document' | 'user';

/** Every link target, in the order the wizard offers them. */
export const LINK_TARGETS: readonly LinkTarget[] = [
  'contract',
  'contact',
  'schedule_activity',
  'document',
  'user',
];

/** The optional functions a generated module can carry (``FeatureSpec``). */
export type ModuleFeatureName = 'status' | 'due' | 'export' | 'comments';

/** ``RuleKind`` in spec.py. */
export type ModuleRuleKind = 'required' | 'positive' | 'not_future' | 'range' | 'one_of' | 'order';

export type ModuleRuleSeverity = 'error' | 'warning';

export type ModuleCategory = 'community' | 'integration' | 'regional';

/** One column, one form input, one table cell (``FieldSpec``). */
export interface ModuleFieldSpec {
  name: string;
  label: string;
  type: ModuleFieldType;
  required: boolean;
  help_text: string;
  unit: string;
  /** `select` only, and then at least two. */
  options: string[];
  /** Whether the list view shows this column. */
  in_list: boolean;
  /**
   * `link` only: what the field points at. Optional because a spec written
   * before links existed has no such key, and a non-link field must not send
   * one (the server's FieldSpec forbids it there).
   */
  target?: LinkTarget | null;
  /**
   * Wizard only, never sent: the field as it was before a link suggestion
   * took it over, so unticking the suggestion gives the person their column
   * back exactly. `toWireSpec` drops it.
   */
  replaced?: Omit<ModuleFieldSpec, 'replaced'>;
}

/** One stage a record moves through (``StateSpec``). */
export interface ModuleStateSpec {
  code: string;
  /** The author's wording, in their language. Data, never translated. */
  label: string;
  /** A record in a done state is finished: no reminders, shown as complete. */
  done: boolean;
}

/** ``StatusFeature``: 2 to 8 states, the first one is where a record starts. */
export interface ModuleStatusFeature {
  states: ModuleStateSpec[];
}

/** ``DueFeature``: which date is the deadline, and how early to remind. */
export interface ModuleDueFeature {
  field: string;
  remind_days_before: number;
}

/** ``FeatureSpec``. Every part optional: a spec from before features has none. */
export interface ModuleFeatures {
  status?: ModuleStatusFeature | null;
  due?: ModuleDueFeature | null;
  export?: boolean;
  comments?: boolean;
}

/** A validation rule (``RuleSpec``). */
export interface ModuleRuleSpec {
  code: string;
  message: string;
  kind: ModuleRuleKind;
  field: string;
  /** `range` only. */
  min_value: number | null;
  /** `range` only. */
  max_value: number | null;
  /** `order` only: `field` must not be later than this one. */
  other_field: string;
  severity: ModuleRuleSeverity;
}

/** The one record type a generated module manages (``EntitySpec``). */
export interface ModuleEntitySpec {
  name: string;
  display_name: string;
  plural_name: string;
  fields: ModuleFieldSpec[];
  /** When true the rows belong to a project and the list can be filtered by one. */
  project_scoped: boolean;
}

/** Everything the generator needs (``ModuleSpec``). */
export interface ModuleSpec {
  key: string;
  display_name: string;
  description: string;
  category: ModuleCategory;
  icon: string;
  version: string;
  author: string;
  entity: ModuleEntitySpec;
  rules: ModuleRuleSpec[];
  /**
   * Who wrote the specification: `assistant` when a model drafted it from a
   * sentence, `wizard` when a person filled the form in. Set by the server,
   * which is what called the model, and kept through editing, since a draft a
   * person then corrected was still drafted by a model.
   */
  drafted_by: 'assistant' | 'wizard';
  /** 1 for specs written before links and features, 2 for the current wizard. */
  schema_version?: number;
  features?: ModuleFeatures;
}

/**
 * What ``{base_path}/ui-spec`` returns: the spec as written, plus the two
 * stamps ``_spec_json`` adds when the module is generated.
 */
export interface ModuleUiSpec extends ModuleSpec {
  generated_at?: string;
  generator?: string;
}

// ---------------------------------------------------------------------------
// Builder request and response shapes (mirrors module_builder/schemas.py)
// ---------------------------------------------------------------------------

/** One choice in the wizard's field-type list. */
export interface FieldTypeInfo {
  type: ModuleFieldType;
  label: string;
  hint: string;
}

export interface RuleKindInfo {
  kind: ModuleRuleKind;
  label: string;
  hint: string;
  applies_to: ModuleFieldType[];
  needs_other_field: boolean;
  needs_bounds: boolean;
}

/**
 * What the wizard is allowed to offer.
 *
 * Fetched rather than hardcoded: the field types and rule kinds are read out of
 * the spec on the server, so adding one there adds it to the wizard without a
 * frontend change and the two lists cannot disagree.
 */
export interface Vocabulary {
  field_types: FieldTypeInfo[];
  rule_kinds: RuleKindInfo[];
  reserved_field_names: string[];
  reserved_keys: string[];
  max_fields: number;
  /** False when no AI provider is configured; the wizard then offers only the by-hand path. */
  assistant_available: boolean;
  /**
   * Which link targets exist on this instance. Absent on a server from before
   * links, and that absence is what tells the wizard to send the old shape.
   */
  link_targets?: LinkTargetInfo[];
  /** The functions a module may carry. Absent on a server from before features. */
  features?: ModuleFeatureName[];
  /** True when an installed module can take new fields and functions in place. */
  upgrade?: boolean;
}

export interface LinkTargetInfo {
  target: LinkTarget;
  /** The module that owns the target table, added to the manifest's `depends`. */
  module: string;
  /** False when that module is switched off here; a link to it cannot be built. */
  available: boolean;
}

/**
 * True when the server understands links and features.
 *
 * Every request model on the server is `extra="forbid"`, so sending `locale`,
 * `schema_version`, `features` or a field `target` to a server from before them
 * is a 422, not a harmless extra key. One probe decides the shape of everything
 * the wizard sends.
 */
export function supportsFeatures(vocabulary: Vocabulary | undefined): boolean {
  return Array.isArray(vocabulary?.features) || Array.isArray(vocabulary?.link_targets);
}

/** True when the server can add fields and functions to an installed module. */
export function supportsUpgrade(vocabulary: Vocabulary | undefined): boolean {
  return vocabulary?.upgrade === true && supportsFeatures(vocabulary);
}

/** What applying a suggestion changes. Exactly one part is set. */
export interface SuggestionPatch {
  field?: ModuleFieldSpec;
  status?: ModuleStatusFeature;
  due?: ModuleDueFeature;
  export?: true;
  comments?: true;
}

/**
 * Something the module could also do, proposed by the assistant or by the
 * server's rules. Never applied until a person ticks it.
 */
export interface Suggestion {
  /** Stable, e.g. `link:contract` or `feature:status`; suggestions are merged by it. */
  id: string;
  kind: 'link' | 'feature';
  target?: LinkTarget;
  feature?: ModuleFeatureName;
  confidence: 'high' | 'medium' | 'low';
  /** Resolved as `module_builder.reason.<reason_code>` with `reason_params`. */
  reason_code?: string;
  reason_params?: Record<string, string | number>;
  /** Already in the user's language; shown when there is no reason_code. */
  reason?: string;
  patch: SuggestionPatch;
}

export interface DraftResponse {
  spec: ModuleSpec;
  /** `assistant` when drafted from a sentence, `wizard` when filled in by hand. */
  source?: string;
  /** Absent on a server from before suggestions; read as none. */
  suggestions?: Suggestion[];
}

export interface SuggestResponse {
  suggestions: Suggestion[];
}

export interface LookupItem {
  id: string;
  label: string;
  sublabel?: string | null;
}

export interface LookupResponse {
  items: LookupItem[];
}

export interface LookupLabelsResponse {
  labels: Record<string, string>;
}

export interface PreviewFile {
  path: string;
  lines: number;
  content: string;
}

/** Everything that would land on disk, before any of it does. */
export interface PreviewResponse {
  spec: ModuleSpec;
  files: PreviewFile[];
  total_lines: number;
  /** Known before the install rather than discovered after it. */
  base_path: string;
  /**
   * Proof that these files were rendered for this person to read. Install
   * refuses a spec that arrives without it, which is what makes the review step
   * a rule the server enforces rather than a screen the wizard happens to show.
   */
  review_token: string;
}

export interface InstalledModule {
  key: string;
  module_name: string;
  display_name: string;
  version: string;
  generated_at: string;
  entity: string;
  field_count: number;
  rule_count: number;
  /** Where this module answers. The screen fetches everything under it. */
  base_path: string;
  /**
   * `quarantined` when the server found code in its files it could not vouch
   * for and left the module unloaded. Its records are kept, its routes are
   * not mounted, and `base_path` then answers nothing. Absent on older servers.
   */
  status?: 'installed' | 'quarantined';
  problem?: ModuleProblem | null;
}

/** Why a module was switched off: `unsafe_code` (params.files) or `unverifiable`. */
export interface ModuleProblem {
  code: string;
  params?: Record<string, unknown>;
}

export function isQuarantined(module: Pick<InstalledModule, 'status'> | undefined): boolean {
  return module?.status === 'quarantined';
}

export interface InstalledList {
  items: InstalledModule[];
  total: number;
  /** The directory on the server these modules live in. */
  runtime_root: string;
}

export interface UninstallResponse {
  key: string;
  module_name: string;
  removed: boolean;
  data_dropped: boolean;
}

const BASE = '/v1/module-builder';

/**
 * Shared by every query on a generated module's page, so an install, an
 * upgrade or a save invalidates them together.
 */
export const RUNTIME_MODULE_QUERY_KEY = 'runtime-module';

/** The field types and rule kinds the wizard may offer, read from the server's spec. */
export async function fetchVocabulary(): Promise<Vocabulary> {
  return apiGet<Vocabulary>(`${BASE}/vocabulary`);
}

/**
 * Turn a description into a specification. Writes nothing.
 *
 * `longRunning` because this one call goes out to an AI provider, and the
 * default 90s budget is a client timeout on a request that is still working.
 */
export async function draftSpec(description: string, locale?: string): Promise<DraftResponse> {
  // `locale` only when the caller has one to give: the old request model is
  // extra="forbid", and the wizard passes it only to a server that knows it.
  const body = locale ? { description, locale } : { description };
  return apiPost<DraftResponse, { description: string; locale?: string }>('/v1/module-builder/draft', body, {
    longRunning: true,
  });
}

/**
 * Rule-based suggestions for a spec: which records it could point at and which
 * functions it could carry. Deterministic and AI-free, so templates and the
 * by-hand path get the same proposals an assistant draft does.
 */
export async function suggestForSpec(spec: ModuleSpec, locale?: string): Promise<SuggestResponse> {
  const body = locale ? { spec, locale } : { spec };
  return apiPost<SuggestResponse, { spec: ModuleSpec; locale?: string }>('/v1/module-builder/suggest', body);
}

export interface LookupQuery {
  projectId?: string | null;
  q?: string;
  limit?: number;
}

/** Records of `target` a link field may point at, for the picker. */
export async function lookupRecords(target: LinkTarget, query: LookupQuery = {}): Promise<LookupResponse> {
  const qs = new URLSearchParams();
  if (query.projectId) qs.set('project_id', query.projectId);
  if (query.q) qs.set('q', query.q);
  qs.set('limit', String(query.limit ?? 20));
  return apiGet<LookupResponse>(`/v1/module-builder/lookup/${encodeURIComponent(target)}?${qs.toString()}`);
}

/** The most ids the labels endpoint takes in one request; it refuses more with a 422. */
export const MAX_LABEL_IDS = 500;

/**
 * Readable labels for stored link ids, in one request per target.
 *
 * Ids the caller may not see are simply absent from the answer, so a missing
 * label means "not visible to you", not "still loading". A long register can
 * hold more ids than one request may carry, so those go in batches.
 */
export async function lookupLabels(target: LinkTarget, ids: string[]): Promise<LookupLabelsResponse> {
  const batches: string[][] = [];
  for (let i = 0; i < ids.length; i += MAX_LABEL_IDS) batches.push(ids.slice(i, i + MAX_LABEL_IDS));
  const answers = await Promise.all(
    batches.map((batch) => {
      const qs = new URLSearchParams({ ids: batch.join(',') });
      return apiGet<LookupLabelsResponse>(
        `/v1/module-builder/lookup/${encodeURIComponent(target)}/labels?${qs.toString()}`,
      );
    }),
  );
  return { labels: Object.assign({}, ...answers.map((a) => a?.labels ?? {})) };
}

/** Render every file the module would consist of, without writing any. */
export async function previewModule(spec: ModuleSpec): Promise<PreviewResponse> {
  return apiPost<PreviewResponse, { spec: ModuleSpec }>(`${BASE}/preview`, { spec });
}

/**
 * Write the module and load it into the running server.
 *
 * Either it is installed and serving when this resolves, or nothing was left
 * behind: there is no half-installed state for the caller to clean up.
 */
export async function installModule(
  spec: ModuleSpec,
  reviewToken: string,
): Promise<InstalledModule> {
  return apiPost<InstalledModule, { spec: ModuleSpec; review_token: string }>(
    BASE,
    { spec, review_token: reviewToken },
    { longRunning: true },
  );
}

/** Every module built on this instance. Readable by any signed-in user. */
/** One thing an upgrade adds or rewords. */
export interface UpgradeChange {
  kind: string;
  field?: string;
  feature?: string;
  state?: string;
  rule?: string;
}

export interface UpgradePreviewResponse extends PreviewResponse {
  changes?: UpgradeChange[];
  record_count?: number;
}

export interface UpgradeResult {
  key: string;
  module_name: string;
  base_path: string;
  record_count: number;
  changes: UpgradeChange[];
}

/**
 * Render the files an installed module would have after adding to it.
 *
 * The token that comes back binds this key and this spec, and only the upgrade
 * call below accepts it.
 */
export async function previewUpgrade(key: string, spec: ModuleSpec): Promise<UpgradePreviewResponse> {
  return apiPost<UpgradePreviewResponse, { spec: ModuleSpec }>(
    `/v1/module-builder/${encodeURIComponent(key)}/upgrade/preview`,
    { spec },
  );
}

/**
 * Add the reviewed fields and functions to an installed module, in one go.
 *
 * Records already kept stay as they are: a new field starts empty, a new link
 * unset, and a new status at its first stage.
 */
export async function upgradeModule(key: string, spec: ModuleSpec, reviewToken: string): Promise<UpgradeResult> {
  return apiPost<UpgradeResult, { spec: ModuleSpec; review_token: string }>(
    `/v1/module-builder/${encodeURIComponent(key)}/upgrade`,
    { spec, review_token: reviewToken },
    { longRunning: true },
  );
}

export async function fetchInstalledModules(): Promise<InstalledList> {
  return apiGet<InstalledList>(BASE);
}

/**
 * Take a module away again.
 *
 * The records stay unless `dropData` is asked for, so removing a module you
 * regret installing does not also lose what you recorded with it.
 */
export async function uninstallModule(key: string, dropData = false): Promise<UninstallResponse> {
  const qs = dropData ? '?drop_data=true' : '';
  return apiDelete<UninstallResponse>(`${BASE}/${encodeURIComponent(key)}${qs}`);
}

// ---------------------------------------------------------------------------
// The generated module's own API (mirrors generator.py's _router)
// ---------------------------------------------------------------------------

/**
 * One row as a generated module returns it.
 *
 * The user's own fields are open by construction - their names come from the
 * spec, not from anything compiled in - so they are typed as unknown and read
 * through the spec that describes them. `id`, `created_at` and `updated_at` are
 * on every generated row; `project_id` is there when the entity is
 * project-scoped.
 */
export interface GeneratedRecord {
  id: string;
  project_id?: string;
  created_at: string;
  updated_at: string;
  [field: string]: unknown;
}

export interface GeneratedRecordPage {
  items: GeneratedRecord[];
  total: number;
}

/**
 * A field-level finding from the generated validator, as it arrives on a 422.
 *
 * The generated router sends `detail` as a list of these rather than FastAPI's
 * own validation shape, so a refused write names the rule that refused it.
 */
export interface GeneratedFinding {
  code: string;
  message: string;
  field: string;
}

/**
 * One part of a module that already holds records which a change would have
 * rewritten rather than added to. `field` is the column name, `label` what
 * people read; `empty` counts the records that leave a newly required field
 * blank.
 */
export interface UpgradeProblem {
  code: string;
  field?: string;
  label?: string;
  feature?: string;
  state?: string;
  rule?: string;
  empty?: number;
}

/**
 * A refused change to a module that holds records, by the server's code.
 *
 * `upgrade_not_additive` and `layout_conflict` (an install over a table kept
 * from an earlier build) carry the record count and the problems;
 * `module_quarantined`, `links_switched_off` (params.targets), `upgrade_failed`
 * and `not_installed` carry only what happened.
 */
export interface UpgradeRefusal {
  code: string;
  records: number | null;
  problems: UpgradeProblem[];
  params: Record<string, unknown>;
}

/** The install refusal's per-column words, as the upgrade's problem codes. */
const LAYOUT_PROBLEMS: Record<string, string> = {
  removed: 'field_removed',
  changed: 'field_retyped',
  new_required: 'field_new_required',
  now_required: 'field_now_required',
  now_optional: 'field_now_optional',
};

function asProblem(entry: unknown, layout: boolean): UpgradeProblem | null {
  if (!entry || typeof entry !== 'object') return null;
  const p = entry as Record<string, unknown>;
  const raw = layout ? p.problem : p.code;
  if (typeof raw !== 'string') return null;
  const field = layout ? p.name : p.field;
  const problem: UpgradeProblem = { code: layout ? LAYOUT_PROBLEMS[raw] ?? raw : raw };
  if (typeof field === 'string') problem.field = field;
  for (const key of ['label', 'feature', 'state', 'rule'] as const) {
    if (typeof p[key] === 'string') problem[key] = p[key] as string;
  }
  if (typeof p.empty === 'number') problem.empty = p.empty;
  return problem;
}

/**
 * The structured refusal an upgrade or an install can come back with, or null
 * for any other error (a plain string detail stays a plain message).
 *
 * Read off the body rather than trusted: a refusal that is missing a part still
 * gets shown, with whatever it does say.
 */
export function upgradeRefusalFrom(error: unknown): UpgradeRefusal | null {
  if (!error || typeof error !== 'object') return null;
  const status = (error as { status?: unknown }).status;
  if (status !== 409 && status !== 404) return null;
  const body = (error as { body?: unknown }).body;
  const detail = body && typeof body === 'object' ? (body as { detail?: unknown }).detail : undefined;
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return null;
  const d = detail as Record<string, unknown>;
  if (typeof d.code !== 'string') return null;
  const params = d.params && typeof d.params === 'object' ? (d.params as Record<string, unknown>) : {};
  const layout = d.code === 'layout_conflict';
  const entries = layout ? params.fields : params.problems;
  const problems = (Array.isArray(entries) ? entries : [])
    .map((entry) => asProblem(entry, layout))
    .filter((p): p is UpgradeProblem => p !== null);
  return {
    code: d.code,
    records: typeof params.records === 'number' ? params.records : null,
    problems,
    params,
  };
}

/**
 * Pull the module's own findings out of an `ApiError` body, if that is what it is.
 *
 * Returns an empty list for every other kind of 422 (FastAPI's own body shape,
 * a string detail), so a caller can fall back to the generic message.
 */
export function findingsFromError(body: unknown): GeneratedFinding[] {
  if (!body || typeof body !== 'object') return [];
  const detail = (body as { detail?: unknown }).detail;
  if (!Array.isArray(detail)) return [];
  const findings: GeneratedFinding[] = [];
  for (const entry of detail) {
    if (!entry || typeof entry !== 'object') continue;
    const e = entry as Record<string, unknown>;
    // A generated finding always carries all three. FastAPI's own 422 entries
    // carry `loc`/`msg`/`type` instead, and fall out here.
    if (typeof e.code === 'string' && typeof e.message === 'string' && typeof e.field === 'string') {
      findings.push({ code: e.code, message: e.message, field: e.field });
    }
  }
  return findings;
}

/**
 * The screen description a generated module serves.
 *
 * `basePath` is passed through untouched - it arrives as `/api/v1/<key>` and
 * the API helper strips its own `/api` prefix rather than doubling it, which is
 * exactly the guard in ``shared/lib/api.ts``.
 */
export async function fetchModuleUiSpec(basePath: string): Promise<ModuleUiSpec> {
  return apiGet<ModuleUiSpec>(`${basePath}/ui-spec`);
}

export interface ModuleRecordQuery {
  /** Only meaningful when the entity is project-scoped; the API ignores it otherwise. */
  projectId?: string | null;
  limit?: number;
  offset?: number;
}

export async function fetchModuleRecords(
  basePath: string,
  query: ModuleRecordQuery = {},
): Promise<GeneratedRecordPage> {
  const qs = new URLSearchParams();
  if (query.projectId) qs.set('project_id', query.projectId);
  if (query.limit !== undefined) qs.set('limit', String(query.limit));
  if (query.offset !== undefined) qs.set('offset', String(query.offset));
  const suffix = qs.toString();
  return apiGet<GeneratedRecordPage>(suffix ? `${basePath}?${suffix}` : basePath);
}

/**
 * Where a module with `export` on hands out its register as a file.
 *
 * A URL rather than a call: the file goes to the browser through
 * `downloadWithAuth`, which wants the full `/api/...` path that `basePath`
 * already is.
 */
export function moduleExportUrl(
  basePath: string,
  format: 'csv' | 'xlsx',
  projectId?: string | null,
): string {
  const qs = new URLSearchParams({ format });
  if (projectId) qs.set('project_id', projectId);
  return `${basePath}/export?${qs.toString()}`;
}

export async function fetchModuleRecord(basePath: string, id: string): Promise<GeneratedRecord> {
  return apiGet<GeneratedRecord>(`${basePath}/${encodeURIComponent(id)}`);
}

/**
 * Values are sent as the API types them: strings for money and quantities,
 * numbers for counts, booleans for checkboxes. See ``toPayload`` in fields.ts,
 * which is what builds this body.
 */
export async function createModuleRecord(
  basePath: string,
  payload: Record<string, unknown>,
): Promise<GeneratedRecord> {
  return apiPost<GeneratedRecord, Record<string, unknown>>(basePath, payload);
}

export async function updateModuleRecord(
  basePath: string,
  id: string,
  payload: Record<string, unknown>,
): Promise<GeneratedRecord> {
  return apiPatch<GeneratedRecord, Record<string, unknown>>(
    `${basePath}/${encodeURIComponent(id)}`,
    payload,
  );
}

export async function deleteModuleRecord(basePath: string, id: string): Promise<void> {
  await apiDelete(`${basePath}/${encodeURIComponent(id)}`);
}
