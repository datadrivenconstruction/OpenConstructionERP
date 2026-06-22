import { apiGet, apiPost, apiPut, apiPatch, apiDelete } from '@/shared/lib/api';
import type { CostVariant, VariantStats } from '@/features/costs/api';
import { resourceAwareTotalInBase } from './boqHelpers';

/* ── Core BOQ types ──────────────────────────────────────────────────── */

export interface BOQ {
  id: string;
  project_id: string;
  name: string;
  description: string;
  status: string;
  estimate_type: string | null;
  is_locked: boolean;
  /** Set when this BOQ was created via "Create revision" — points at the
   *  BOQ it was cloned from. Drives the baseline pick in the compare UI. */
  parent_estimate_id?: string | null;
  created_at: string;
  updated_at: string;
}

/**
 * Linked-position role (Issue #127 — reuse the same code across a project).
 *  - `master`   — the definition-of-record for a shared `reference_code`.
 *  - `instance` — a linked copy that follows the master's definition
 *                 (description/unit/unit_rate/classification/subtree) but
 *                 keeps its OWN ordinal and OWN editable quantity.
 *  - `null`     — a plain standalone position (not part of any link group).
 */
export type LinkRole = 'master' | 'instance' | null;

export interface Position {
  id: string;
  boq_id: string;
  parent_id: string | null;
  ordinal: string;
  description: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  total: number;
  classification: Record<string, string>;
  source: string;
  confidence: number | null;
  sort_order: number;
  validation_status: string;
  /** BIM element IDs linked to this position (cross-highlight source). */
  cad_element_ids?: string[];
  /**
   * Issue #127 — reusable code, distinct from `ordinal`. When two positions
   * in the SAME project share a `reference_code` they form a link group: one
   * `master` plus N `instance`s that inherit its definition.
   */
  reference_code?: string | null;
  /** Role within the link group (see {@link LinkRole}). */
  link_role?: LinkRole;
  /** Stable id shared by every member of the link group. */
  link_group_id?: string | null;
  /** Number of linked instances — populated for masters on single-position
   *  GET/PATCH/create/unlink responses (absent on the bulk BOQ fetch). */
  linked_instance_count?: number | null;
  /** Backend returns `metadata_` (aliased) — normalize to `metadata` in fetch layer */
  metadata: Record<string, unknown>;
  metadata_?: Record<string, unknown>;
}

/**
 * Stamped onto `metadata.link_propagation` by the backend AFTER a master
 * definition edit (Issue #127). `propagated_to` counts the linked instances
 * the change was fanned out to; `unlinked` is true when the edited row was an
 * instance whose definition diverged → the backend auto-detached it.
 */
export interface LinkPropagationMeta {
  propagated_to: number;
  unlinked: boolean;
  /** Issue #133 — count of linked RESOURCE instances a master resource
   *  definition edit was fanned out to (separate from position links). */
  resource_propagated_to?: number;
}

/** One member of a reference-code link group. */
export interface PositionLinkMember {
  id: string;
  boq_id: string;
  ordinal: string;
  description: string;
  quantity: number;
  total: number;
  link_role: LinkRole;
  is_master: boolean;
}

/** Response of `GET /v1/boq/positions/{id}/links/`. */
export interface PositionLinksResponse {
  reference_code: string | null;
  link_group_id: string | null;
  linked: boolean;
  master_id: string | null;
  total_count: number;
  instance_count: number;
  members: PositionLinkMember[];
}

/**
 * Issue #136 — server-enforced BOQ structural limits. The editor reads
 * `max_nesting_depth` so it can disable "add child" / "add sub-section"
 * once the configurable cap is reached and surface an i18n tooltip,
 * keeping the UI in lock-step with the backend validation.
 */
export interface BOQLimits {
  max_nesting_depth: number;
}

/**
 * Conservative client-side fallback for {@link BOQLimits.max_nesting_depth}
 * — mirrors `service.MAX_NESTING_DEPTH`. Used only until the `/limits/`
 * fetch resolves (or if it fails) so the UI never blocks nesting that the
 * backend would actually accept.
 */
export const DEFAULT_MAX_NESTING_DEPTH = 8;

/** Issue #133 — one existing resource that already uses a given code. */
export interface ResourceCodeMatch {
  code: string;
  name: string;
  type: string;
  unit: string;
  unit_rate: number;
  currency: string;
  position_id: string;
  position_ordinal: string;
  position_description: string;
}

/** Response of `GET /v1/boq/projects/{id}/resource-by-code/`. */
export interface ResourceCodeLookupResponse {
  found: boolean;
  code: string;
  match: ResourceCodeMatch | null;
}

export interface BOQWithPositions extends BOQ {
  positions: Position[];
  /**
   * v3 §10 contract: money fields serialise as Decimal-as-string
   * (e.g. ``"634204086.52"``). Keep the type honest so call-sites coerce
   * with ``Number()`` at the boundary instead of string-concatenating
   * ("123" + "456" → "123456") or comparing strings.
   */
  grand_total: number | string;
}

/* ── Markup types ────────────────────────────────────────────────────── */

export interface Markup {
  id: string;
  boq_id: string;
  name: string;
  markup_type: 'percentage' | 'fixed';
  category: 'overhead' | 'profit' | 'tax' | 'contingency' | 'insurance' | 'bond' | 'other';
  percentage: number;
  /**
   * v3 §10 contract: the backend serialises this Decimal money field as a
   * JSON *string* (e.g. ``"500.00"``), so keep the type honest and coerce
   * with ``toNum`` from ``@/shared/lib/money`` before any arithmetic — a bare
   * ``+`` string-concatenates ("1000" + "500.00" → "1000500.00").
   */
  fixed_amount: number | string;
  apply_to: 'direct_cost' | 'subtotal' | 'cumulative';
  sort_order: number;
  is_active: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface MarkupsResponse {
  markups: Markup[];
}

export interface CreateMarkupData {
  name: string;
  markup_type?: string;
  category?: string;
  percentage?: number;
  fixed_amount?: number;
  apply_to?: string;
  sort_order?: number;
  is_active?: boolean;
}

export interface UpdateMarkupData {
  name?: string;
  markup_type?: string;
  category?: string;
  percentage?: number;
  fixed_amount?: number;
  apply_to?: string;
  sort_order?: number;
  is_active?: boolean;
}

/* ── Create / Update payloads ────────────────────────────────────────── */

export interface CreateBOQData {
  project_id: string;
  name: string;
  description?: string;
}

/**
 * What-if scenario request. A scenario is a cloned BOQ linked back to its
 * baseline via `parent_estimate_id`. When `rate_factor` is supplied (and not
 * 1.0) the server multiplies every position's unit_rate by it on the clone,
 * leaving the baseline untouched. `region` and `note` are recorded in the new
 * BOQ's scenario metadata for provenance.
 */
export interface ScenarioCreateData {
  name: string;
  rate_factor?: number | null;
  region?: string | null;
  note?: string | null;
}

/** Minimal tender-package shape returned by the create-from-BOQ endpoint. */
export interface TenderPackageRef {
  id: string;
  name: string;
  status: string;
}

/** Payload for creating a tender package straight from BOQ sections. */
export interface CreateTenderFromBoqData {
  project_id: string;
  boq_id: string;
  section_ids: string[];
  package_name: string;
  package_description?: string;
  deadline?: string | null;
}

/**
 * Issue #127 — how a create/update should resolve when its `reference_code`
 * collides with an existing code in the project:
 *  - `link`       — (default) attach as a linked instance of the master.
 *  - `copy`       — one-time unlinked clone (snapshot, does not follow master).
 *  - `standalone` — force a plain new position, bypass reuse entirely.
 */
export type LinkMode = 'link' | 'copy' | 'standalone';

export interface CreatePositionData {
  boq_id: string;
  ordinal: string;
  description: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  classification?: Record<string, string>;
  parent_id?: string;
  /** Issue #127 — reusable code. When it collides with an existing project
   *  code AND `link_mode` != "standalone", the backend returns 201 with a
   *  linked instance (own ordinal + own quantity) instead of a 409. */
  reference_code?: string | null;
  link_mode?: LinkMode | null;
  /** Issue #139 — UUID of the row the user had selected when they hit
   *  "Add position". The new partida slots in directly *after* that
   *  sibling (sort_order = anchor + 1, later rows shift down) instead of
   *  at the end of the section. Ignored on the reuse/linked-instance path. */
  after_position_id?: string | null;
}

export interface UpdatePositionData {
  ordinal?: string;
  description?: string;
  unit?: string;
  quantity?: number;
  unit_rate?: number;
  classification?: Record<string, string>;
  parent_id?: string | null;
  source?: string;
  metadata?: Record<string, unknown>;
  sort_order?: number;
  /** Issue #127 — set/change the reusable code on an existing position. */
  reference_code?: string | null;
  link_mode?: LinkMode | null;
}

/**
 * Find-and-replace mutation for the bulk endpoint. Currently scoped to the
 * `description` field. The server rewrites each selected row's description,
 * counting only the rows whose text actually changed (no-match rows skip).
 */
export interface FindReplaceSpec {
  field: 'description';
  find: string;
  replace: string;
  case_sensitive: boolean;
}

/**
 * v3.12.0 Stream A — bulk update payload.
 * Exactly one of `updates` / `rate_factor` / `quantity_factor` / `find_replace`
 * must be supplied; the server rejects mixed payloads with 422.
 */
export interface BulkPositionUpdateData {
  ids: string[];
  /** Allow-listed keys only: 'unit' | 'classification' | 'validation_status' | 'source'. */
  updates?: Record<string, unknown>;
  rate_factor?: number;
  quantity_factor?: number;
  /** Rewrite the description text across every selected row. */
  find_replace?: FindReplaceSpec;
}

export interface BulkUpdateResult {
  updated: number;
  /** Rows that could not be updated (errors); same rows as `failed_ids`. */
  skipped: number;
  /** Rows left untouched on purpose, e.g. find-and-replace with no match. */
  unchanged: number;
  failed_ids: string[];
  log_id: string | null;
}

export interface RestoreFieldData {
  field: string;
  value: unknown;
  log_id: string;
}

export interface RestoreFieldResponse {
  position_id: string;
  field: string;
  restored_value: unknown;
  source_log_id: string;
  new_log_id: string | null;
}

/* ── Normalize backend metadata_ → metadata ─────────────────────── */

/**
 * Coerce a backend numeric value into a finite JS number.
 *
 * Money / quantity columns are SQLAlchemy ``Numeric`` and the API
 * serialises them as exact decimal *strings* (e.g. ``"1234.5600"``) so
 * large totals round-trip without float drift. Untouched, those strings
 * poison the grid: ``0 + "1234.56"`` string-concatenates into a section
 * subtotal that renders as ``NaN``, and ``Number.isFinite("1234.56")``
 * is ``false`` so ``convertToBase`` zeroes resource-driven position
 * totals (Issue #131 — "total shows for <1s then drops to 0"). Coercing
 * at the fetch boundary makes the runtime match the ``number`` contract
 * the rest of the editor already assumes.
 */
function toFiniteNumber(v: unknown, fallback = 0): number {
  if (typeof v === 'number') return Number.isFinite(v) ? v : fallback;
  if (typeof v === 'string') {
    const trimmed = v.trim();
    if (trimmed === '') return fallback;
    const n = Number(trimmed);
    return Number.isFinite(n) ? n : fallback;
  }
  return fallback;
}

/**
 * Backend returns `metadata_` (SQLAlchemy alias) and serialises Decimal
 * money/qty fields as strings. Normalize to `metadata` AND coerce every
 * numeric field — position-level and per-resource — to a real number so
 * totals/subtotals never string-concatenate or zero out (Issue #131).
 */
export function normalizePosition(p: Position): Position {
  // Preserve the original metadata-resolution semantics exactly:
  //   metadata missing + metadata_ present → metadata_
  //   metadata missing (no metadata_)      → {}
  //   metadata present                     → metadata
  const resolvedMeta: Record<string, unknown> =
    !p.metadata && p.metadata_ ? p.metadata_ : (p.metadata ?? {});

  // Resource components carry the same string-Decimal money fields and
  // BOQGrid sums them for the per-position unit_rate rollup + resource
  // rows — coerce them too so that rollup stays numeric.
  let normMeta = resolvedMeta;
  const res = (resolvedMeta as { resources?: unknown }).resources;
  if (Array.isArray(res)) {
    normMeta = {
      ...resolvedMeta,
      resources: res.map((r) => {
        if (!r || typeof r !== 'object') return r;
        const rr = r as Record<string, unknown>;
        const quantity = toFiniteNumber(rr.quantity);
        const unit_rate = toFiniteNumber(rr.unit_rate);
        // Issue #131 contract: resources that DO carry a stored `total`
        // (string-Decimal from the API) are coerced to a number. Resources
        // WITHOUT a total key (most seed/import data) must NOT get a literal
        // 0 injected - that fake 0 made the M/L/E split columns read "all
        // totals are zero" and render blank. Derive quantity * unit_rate
        // instead, the same rollup the backend and the grid use.
        const hasStoredTotal = rr.total != null && rr.total !== '';
        return {
          ...rr,
          quantity,
          unit_rate,
          total: hasStoredTotal ? toFiniteNumber(rr.total) : quantity * unit_rate,
        };
      }),
    };
  }

  return {
    ...p,
    quantity: toFiniteNumber(p.quantity),
    unit_rate: toFiniteNumber(p.unit_rate),
    total: toFiniteNumber(p.total),
    sort_order: toFiniteNumber(p.sort_order),
    metadata: normMeta,
  };
}

export function normalizePositions(positions: Position[]): Position[] {
  return positions.map(normalizePosition);
}

/* ── Section helpers (used on the frontend to group positions) ────── */

/** A section is a position with no unit (acts as a group header). */
export function isSection(pos: Position): boolean {
  return !pos.unit || pos.unit.trim() === '' || pos.unit.trim().toLowerCase() === 'section';
}

/**
 * Organizes a flat positions list into sections with children.
 * A section is any position where `unit` is empty.
 * Positions with a `parent_id` pointing to a section go under that section.
 * Positions without a parent that are not sections go into an "Ungrouped" virtual bucket.
 */
export interface SectionGroup {
  section: Position;
  children: Position[];
  subtotal: number;
}

export function groupPositionsIntoSections(
  positions: Position[],
  /**
   * Optional FX context (Issue #111 / #150). When supplied, child positions
   * priced in a non-base currency are converted into ``baseCurrency`` before
   * being added to the section subtotal. This covers BOTH a position-level
   * ``metadata.currency`` AND the harder case the contributor's data hits:
   * a position with NO ``metadata.currency`` but whose ``metadata.resources``
   * are priced in a foreign currency (its stored ``total`` was built from
   * ``Σ(r.qty × r.rate)`` with no FX applied). Without this, mixed-currency
   * BOQs sum foreign-currency totals directly into base subtotals, producing
   * nonsensical figures — and the Excel/PDF exports + version-compare were
   * doing exactly that because they called this helper with no fxOpts.
   */
  fxOpts?: {
    baseCurrency?: string;
    fxRates?: Array<{ currency: string; rate: number }>;
  },
): {
  sections: SectionGroup[];
  ungrouped: Position[];
} {
  const sections: SectionGroup[] = [];
  const ungrouped: Position[] = [];
  const sectionMap = new Map<string, SectionGroup>();
  const baseCurrency = fxOpts?.baseCurrency;
  const fxRates = fxOpts?.fxRates;

  const rebase = (pos: Position): number => {
    // Backward-compatible: with no FX context, return the raw (coerced)
    // position total exactly as before. ``toFiniteNumber`` guards against a
    // decimal string slipping through unnormalized (adding a raw string into
    // ``subtotal`` concatenates → NaN, #131).
    if (!baseCurrency) return toFiniteNumber(pos.total);
    // Resource-currency-aware roll-up — the SAME conversion the editor grid
    // (columnDefs ``totalFormatter`` / ``directCost``) uses, so exported and
    // compared subtotals match what the user sees on screen (#150).
    return resourceAwareTotalInBase(
      pos as unknown as {
        total?: number | string | null;
        quantity?: number | string | null;
        metadata?: Record<string, unknown> | null;
        metadata_?: Record<string, unknown> | null;
      },
      baseCurrency,
      fxRates,
    );
  };

  // First pass: identify sections
  const sortedPositions = [...positions].sort((a, b) => {
    if (a.sort_order !== b.sort_order) return a.sort_order - b.sort_order;
    return a.ordinal.localeCompare(b.ordinal, undefined, { numeric: true });
  });

  for (const pos of sortedPositions) {
    if (isSection(pos)) {
      const group: SectionGroup = { section: pos, children: [], subtotal: 0 };
      sectionMap.set(pos.id, group);
      sections.push(group);
    }
  }

  // Second pass: assign children to sections
  for (const pos of sortedPositions) {
    if (isSection(pos)) continue;

    if (pos.parent_id && sectionMap.has(pos.parent_id)) {
      const group = sectionMap.get(pos.parent_id)!;
      group.children.push(pos);
      group.subtotal += rebase(pos);
    } else {
      ungrouped.push(pos);
    }
  }

  return { sections, ungrouped };
}

/* ── Hierarchical tree builder (multi-level BOQ) ─────────────────────── */

export interface HierarchyNode {
  position: Position;
  level: number;
  children: HierarchyNode[];
  subtotal: number;
}

/**
 * Build a recursive tree from flat positions list.
 * Supports unlimited nesting depth via parent_id references.
 * Sections and positions can appear at any level.
 */
export function buildHierarchy(positions: Position[]): HierarchyNode[] {
  const sorted = [...positions].sort((a, b) => {
    if (a.sort_order !== b.sort_order) return a.sort_order - b.sort_order;
    return a.ordinal.localeCompare(b.ordinal, undefined, { numeric: true });
  });

  const posMap = new Map<string, Position>();
  for (const p of sorted) posMap.set(p.id, p);

  function buildChildren(parentId: string | null, level: number): HierarchyNode[] {
    const children = sorted.filter((p) => p.parent_id === parentId);
    return children.map((pos) => {
      const childNodes = buildChildren(pos.id, level + 1);
      const subtotal = isSection(pos)
        ? childNodes.reduce((sum, c) => sum + (Number(c.subtotal) || 0), 0)
        : Number(pos.total) || 0;
      return { position: pos, level, children: childNodes, subtotal };
    });
  }

  return buildChildren(null, 0);
}

/**
 * Get the depth (level) of a position in the hierarchy.
 * Follows parent_id chain up to root.
 */
export function getPositionDepth(pos: Position, posMap: Map<string, Position>): number {
  let depth = 0;
  let current = pos;
  while (current.parent_id && posMap.has(current.parent_id)) {
    depth++;
    current = posMap.get(current.parent_id)!;
  }
  return depth;
}

/* ── Activity types ──────────────────────────────────────────────────── */

export type ActivityAction =
  | 'position_added'
  | 'position_updated'
  | 'position_deleted'
  | 'quantity_updated'
  | 'rate_updated'
  | 'section_added'
  | 'section_deleted'
  | 'validation_run'
  | 'excel_imported'
  | 'csv_imported'
  | 'boq_created'
  | 'template_applied'
  | 'markup_added'
  | 'markup_updated'
  | 'status_changed';

export interface ActivityEntry {
  id: string;
  boq_id: string;
  action: ActivityAction;
  description: string;
  details: Record<string, unknown>;
  created_at: string;
  user_name?: string;
  /** v3.12.0 — target_type (position / markup / boq) for the restore UI. */
  target_type?: string;
  /** v3.12.0 — target_id (position UUID) for the per-field restore endpoint. */
  target_id?: string | null;
}

export interface ActivityResponse {
  activities: ActivityEntry[];
  total: number;
}

export interface ProjectActivityEntry {
  id: string;
  project_id: string | null;
  boq_id: string | null;
  user_id: string;
  action: string;
  target_type: string;
  target_id: string | null;
  description: string;
  changes: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
}

/* ── Cost autocomplete types ─────────────────────────────────────────── */

export interface CostItemComponent {
  name: string;
  code?: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  cost: number;
  type: string;
  /**
   * Per-component variant catalog (v2.6.30+). Surfaced when the component
   * is one of CWICR's abstract-resource (variant) slots for its rate row
   * — e.g. a single rate that splits into multiple concrete grades or
   * rebar diameters. Backend stamps these via
   * ``costs/router.py::abstract_variants_by_pair`` so each component
   * carries its OWN options list, independent of any other variant
   * component on the same rate. Frontend forwards them to the BOQ
   * resource entry on apply so each variant resource gets its own
   * picker pill.
   */
  available_variants?: CostVariant[];
  available_variant_stats?: VariantStats;
}

/**
 * Slim cost-breakdown payload returned by the autocomplete endpoint.
 *
 * Phase F (v2.7.0): the BOQ description-cell hover tooltip renders these
 * three figures in the catalog's native currency. The keys mirror the
 * CWICR metadata stamps and stay absent when the source row carries no
 * such data — the tooltip hides the section gracefully in that case.
 */
export interface CostAutocompleteBreakdown {
  labor_cost?: number;
  material_cost?: number;
  equipment_cost?: number;
}

export interface CostAutocompleteItem {
  code: string;
  description: string;
  unit: string;
  rate: number;
  /** Catalog currency (ISO 4217). Forwarded to the BOQ resource entry on
   *  apply so each resource keeps its native currency when added from a
   *  catalog whose currency differs from the BOQ base. Optional for the
   *  thin autocomplete endpoint that doesn't carry it. */
  currency?: string;
  /** Region tag (e.g. ``DE_BERLIN``). Surfaced so the tooltip can show
   *  a region badge next to the code without forcing the caller to
   *  re-derive it from currency. */
  region?: string | null;
  classification: Record<string, string>;
  components: CostItemComponent[];
  /**
   * Optional labor / material / equipment split, in the catalog's native
   * currency. Populated by the autocomplete endpoint from CWICR metadata
   * (Phase F, v2.7.0). Absent when the source row carries no breakdown.
   */
  cost_breakdown?: CostAutocompleteBreakdown | null;
  /**
   * Optional CWICR variant payload (v2.6.26+). Surfaced when the cost item
   * carries 2+ abstract-resource variants so callers (e.g. BOQEditorPage's
   * ``handleCostDbAddResource``) can cache the variant catalog on the
   * resource entry for later re-pick. Re-uses the canonical CostVariant /
   * VariantStats shapes from `@/features/costs/api` so newer fields
   * (``full_label``, ``common_start``) propagate automatically.
   *
   * Phase F (v2.7.0): the autocomplete endpoint now also returns a slim
   * ``variant_count`` here (the heavy ``variants`` array is intentionally
   * omitted on the autocomplete path to keep the response small — fetch
   * it lazily via ``GET /v1/costs/{id}/`` on apply). The full optional
   * shape stays compatible.
   */
  metadata_?: {
    variants?: CostVariant[];
    variant_stats?: VariantStats;
    variant_count?: number;
    labor_hours?: number;
    workers_per_unit?: number;
    /**
     * Ordered list of work steps describing what is included in this
     * rate (e.g. "Установка телескопических стоек.", "Bodenbearbeitung
     * nach Maß."). Sourced from CWICR's ``work_composition_text``
     * column (universal scope detector — non-empty work_composition +
     * empty resource_name). Surfaced in the BOQ grid description cell
     * as an inline (i) hint with a bullet-list popover.
     */
    scope_of_work?: string[];
    [key: string]: unknown;
  };
}

/* ── AI Chat types ──────────────────────────────────────────────────── */

export interface AIChatContext {
  project_name: string;
  currency: string;
  standard: string;
  existing_positions_count: number;
}

export interface AIChatRequest {
  message: string;
  context: AIChatContext;
  locale?: string;
}

export interface AIChatItem {
  ordinal: string;
  description: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  total: number;
}

export interface AIChatResponse {
  items: AIChatItem[];
  /** Assistant's natural-language answer — present for any non-empty model
   *  output (knowledge questions get a real answer here, not just items). */
  reply?: string;
  message: string;
}

/* ── Per-position AI copilot types ───────────────────────────────────── */

/**
 * A single concrete change the copilot proposes (or already applied) for one
 * BOQ position. Every action is catalog-sourced — ``source`` carries the cost
 * row's code/description and ``confidence`` (0..1) drives the auto-apply
 * threshold (>= 0.85 lands as ``auto_applied`` server-side, the rest come back
 * as ``needs_review`` confirm cards).
 *
 * ``payload`` carries the after-state and ``before`` the prior values, so the
 * dock can render a clean before -> after diff AND the editor can mirror the
 * change into the local cache + undo stack without re-deriving it.
 */
export type CopilotActionType =
  | 'update_description'
  | 'set_quantity'
  | 'set_unit_rate'
  | 'add_resources';

export type CopilotActionStatus =
  | 'auto_applied'
  | 'needs_review'
  | 'applied'
  | 'dismissed'
  | 'failed';

/** One catalog-sourced resource line proposed by an ``add_resources`` action. */
export interface CopilotResource {
  name: string;
  type: string;
  unit: string;
  quantity: number;
  unit_rate: number;
  code?: string;
  currency?: string;
}

export interface CopilotAction {
  action_type: CopilotActionType;
  /**
   * The after-state. Shape depends on ``action_type``:
   *  - update_description -> { description: string }
   *  - set_quantity       -> { quantity: number; unit?: string }
   *  - set_unit_rate      -> { unit_rate: number; currency?: string }
   *  - add_resources      -> { resources: CopilotResource[] }
   */
  payload: Record<string, unknown>;
  /** Prior values for the touched fields — drives the diff + undo oldData. */
  before: Record<string, unknown>;
  /** Model/catalog confidence (0..1). >= 0.85 auto-applies server-side. */
  confidence: number;
  /** Catalog provenance — code + human label of the source cost row. */
  source: { code?: string; description?: string } | null;
  status: CopilotActionStatus;
  /** Human-readable failure note when ``status === 'failed'`` (empty otherwise). */
  error?: string;
}

export interface CopilotMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  /** Actions attached to an assistant turn — null/absent for plain chat. */
  actions: CopilotAction[] | null;
  created_at: string;
}

/** POST chat response: the assistant turn plus the actions it produced. */
export interface CopilotChatResponse {
  assistant_message: CopilotMessage;
  actions: CopilotAction[];
}

/** POST apply response: the updated position plus the action (status flipped). */
export interface CopilotApplyResponse {
  position: Position;
  action: CopilotAction;
}

/* ── Cost Breakdown types ─────────────────────────────────────────── */

export interface CostBreakdownCategory {
  type: string;
  amount: number;
  percentage: number;
  item_count: number;
}

export interface CostBreakdownMarkup {
  name: string;
  percentage: number;
  amount: number;
}

export interface CostBreakdownResource {
  name: string;
  type: string;
  total_cost: number;
  positions_count: number;
}

export interface CostBreakdownResponse {
  boq_id: string;
  grand_total: number;
  direct_cost: number;
  categories: CostBreakdownCategory[];
  markups: CostBreakdownMarkup[];
  top_resources: CostBreakdownResource[];
}

/* ── Resource Summary types ────────────────────────────────────────── */

export interface ResourcePositionRef {
  position_id: string;
  resource_idx: number;
}

export interface ResourceSummaryItem {
  name: string;
  type: string;
  unit: string;
  total_quantity: number;
  avg_unit_rate: number;
  total_cost: number;
  positions_used: number;

  /**
   * Variant catalog cached on at least one underlying resource slot.  When
   * present (>= 2 entries), the ResourceSummary row surfaces a re-pick pill
   * that opens the same VariantPicker used in the BOQ grid; ``Apply`` fans
   * the new variant out to every entry in ``position_refs``.
   */
  available_variants?: CostVariant[] | null;
  variant_stats?: VariantStats | null;
  /**
   * Variant label currently chosen across positions.  ``"__mixed__"`` when
   * positions disagree (e.g. some picked ``C30/37``, others ``C25/30``);
   * ``null`` when no explicit pick was made on any position.
   */
  current_variant_label?: string | null;
  /** Auto-default strategy when one was applied uniformly. */
  variant_default?: 'mean' | 'median' | null;
  currency?: string | null;
  /** CWICR resource_code — used to dedupe ▾N pickers across summary rows
   *  that resolve to the same abstract-resource catalog. */
  resource_code?: string | null;
  position_refs?: ResourcePositionRef[];
  /** Issue #106 — Pareto / ABC analysis. Share of this resource over the
   *  total summed cost (0–100). Backend computes after sorting items by
   *  descending cost so cumulative ABC class assignment is well-defined. */
  abc_percentage?: number;
  /** "A" | "B" | "C" — ABC bucket using the conventional 80/15/5 cumulative
   *  thresholds. ``null`` when grand_total is 0 (empty BOQ). */
  abc_class?: 'A' | 'B' | 'C' | null;
}

export interface ResourceTypeSummary {
  count: number;
  total_cost: number;
}

export interface ResourceSummaryResponse {
  total_resources: number;
  by_type: Record<string, ResourceTypeSummary>;
  resources: ResourceSummaryItem[];
  /** Issue #106 — sum of every resource.total_cost in this response. */
  grand_total?: number;
}

/* ── Sensitivity Analysis types ───────────────────────────────────────── */

export interface SensitivityItem {
  ordinal: string;
  description: string;
  total: number;
  share_pct: number;
  impact_low: number;
  impact_high: number;
  /* Probabilistic upgrade (present when method === 'monte_carlo'). */
  variance_contribution_pct?: number | null;
  rank_correlation?: number | null;
  swing_low?: number | null;
  swing_high?: number | null;
}

export interface SensitivityResponse {
  base_total: number;
  variation_pct: number;
  method?: string;
  iterations?: number;
  correlation?: number;
  items: SensitivityItem[];
}

/* ── BOQ Snapshot / Version History types ─────────────────────────────── */

export interface BOQSnapshot {
  id: string;
  boq_id: string;
  name: string;
  position_count?: number;
  grand_total?: number;
  created_at: string;
  created_by: string | null;
}

/* ── Feature 1: model→BOQ quantity links ─────────────────────────────── */

/** How multiple bound elements combine into one position quantity. */
export type QuantityAggregation = 'sum' | 'max' | 'min' | 'count' | 'first';

/** A persisted live binding between a position field and BIM elements. */
export interface QuantityLink {
  id: string;
  position_id: string;
  boq_id: string;
  model_id: string;
  element_stable_ids: string[];
  quantity_field: string;
  target_field: string;
  aggregation: string;
  status: string;
  source_model_version: string | null;
  last_applied_quantity: string | null;
  last_pulled_at: string | null;
  last_applied_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateQuantityLinkData {
  model_id: string;
  element_stable_ids: string[];
  quantity_field: string;
  target_field?: 'quantity';
  aggregation?: QuantityAggregation;
}

/** One per-position review row produced by the refresh probe. */
export interface QuantityLinkRefreshRow {
  link_id: string;
  position_id: string;
  ordinal: string;
  description: string;
  quantity_field: string;
  target_field: string;
  aggregation: string;
  unit: string;
  old_quantity: string;
  new_quantity: string;
  delta: string;
  changed: boolean;
  status: string;
  contributing_elements: string[];
  missing_element_ids: string[];
  message: string;
}

export interface QuantityLinkRefreshResponse {
  boq_id: string;
  checked: number;
  stale: number;
  rows: QuantityLinkRefreshRow[];
}

export interface QuantityLinkApplyResultRow {
  link_id: string;
  position_id: string;
  ordinal: string;
  applied: boolean;
  old_quantity: string;
  new_quantity: string;
  message: string;
}

export interface QuantityLinkApplyResponse {
  boq_id: string;
  applied: number;
  skipped: number;
  results: QuantityLinkApplyResultRow[];
}

/* ── Feature 2: estimate baseline / line-level compare ───────────────── */

export type CompareChangeType =
  | 'added'
  | 'removed'
  | 'qty_changed'
  | 'rate_changed'
  | 'changed'
  | 'unchanged';

export interface ComparePositionRow {
  change_type: CompareChangeType;
  match_key: string;
  reference_code: string | null;
  ordinal: string;
  description: string;
  unit: string;
  old_quantity: string | null;
  new_quantity: string | null;
  old_unit_rate: string | null;
  new_unit_rate: string | null;
  old_total: string | null;
  new_total: string | null;
  old_total_base: string | null;
  new_total_base: string | null;
  currency: string;
  total_delta_base: string;
}

export interface CompareSummary {
  base_currency: string;
  added: number;
  removed: number;
  qty_changed: number;
  rate_changed: number;
  changed: number;
  unchanged: number;
  old_direct_cost_base: string;
  new_direct_cost_base: string;
  direct_cost_delta_base: string;
}

export interface BOQCompareResponse {
  base_boq_id: string;
  other_boq_id: string;
  base_boq_name: string;
  other_boq_name: string;
  summary: CompareSummary;
  rows: ComparePositionRow[];
}

/* ── AACE Estimate Classification types ──────────────────────────────── */

export interface EstimateClassificationMetrics {
  total_positions: number;
  positions_with_rates: number;
  positions_with_resources: number;
  positions_with_classification: number;
  rate_completeness_pct: number;
  resource_completeness_pct: number;
  classification_completeness_pct: number;
}

export interface EstimateClassificationResponse {
  estimate_class: number;
  class_label: string;
  accuracy_low: string;
  accuracy_high: string;
  definition_level_low: number;
  definition_level_high: number;
  methodology: string;
  metrics: EstimateClassificationMetrics;
}

/* ── Monte Carlo Cost Risk types ─────────────────────────────────────── */

export interface CostRiskHistogramBin {
  bin_start: number;
  bin_end: number;
  count: number;
}

export interface CostRiskDriver {
  ordinal: string;
  description: string;
  contribution_pct: number;
  rank_correlation?: number;
  swing_low?: number;
  swing_high?: number;
}

export interface CostRiskPercentiles {
  p5?: number;
  p10: number;
  p25: number;
  p50: number;
  p75: number;
  p80: number;
  p90: number;
  p95?: number;
}

export interface CostRiskCdfPoint {
  cost: number;
  cumulative_prob: number;
}

export interface CostRiskResponse {
  iterations: number;
  /* Money fields arrive as Decimal-as-strings on the wire (v3 §10). */
  base_total: number;
  mean?: number;
  std_dev?: number;
  cv_pct?: number;
  percentiles: CostRiskPercentiles;
  contingency_p80: number;
  contingency_pct: number;
  recommended_budget: number;
  target_confidence?: number;
  prob_within_base?: number;
  correlation?: number;
  seed?: number;
  convergence_status?: string;
  convergence_margin_pct?: number;
  histogram: CostRiskHistogramBin[];
  cdf?: CostRiskCdfPoint[];
  risk_drivers: CostRiskDriver[];
}

/* ── AI Classification types ─────────────────────────────────────────── */

export interface ClassificationSuggestion {
  standard: string;
  code: string;
  label: string;
  confidence: number;
}

export interface ClassifyResponse {
  suggestions: ClassificationSuggestion[];
}

/* ── AI Rate Suggestion types ────────────────────────────────────────── */

export interface RateMatch {
  code: string;
  description: string;
  rate: number;
  region: string;
  score: number;
}

export interface SuggestRateResponse {
  suggested_rate: number;
  confidence: number;
  source: string;
  matches: RateMatch[];
}

/* ── Anomaly Detection types ─────────────────────────────────────────── */

export interface PricingAnomaly {
  position_id: string;
  field: string;
  current_value: number;
  market_range: { p25: number; median: number; p75: number };
  severity: 'warning' | 'error';
  message: string;
  suggestion: number;
}

export interface AnomalyCheckResponse {
  anomalies: PricingAnomaly[];
  positions_checked: number;
}

/* ── AI Cost Finder types ─────────────────────────────────────────── */

export interface CostItemSearchResult {
  id: string;
  code: string;
  description: string;
  unit: string;
  rate: number;
  region: string;
  score: number;
  classification: Record<string, string>;
  components: { description: string; unit: string; rate: number }[];
  currency: string;
}

export interface CostItemSearchResponse {
  results: CostItemSearchResult[];
  total_found: number;
  query_embedding_ms: number;
  search_ms: number;
}

/* ── Paginated cost search (used by CostDatabaseSearchModal) ─────────── */

/**
 * One row in the paginated /v1/costs/ search response.  Mirrors the public
 * CostItemResponse on the backend and intentionally re-types only the fields
 * the modal renders — extra metadata (variant_stats, full_label, etc.) flows
 * through ``metadata_`` opaquely.
 */
export interface CostSearchItem {
  id: string;
  code: string;
  description: string;
  unit: string;
  rate: number;
  currency?: string;
  region: string | null;
  classification: Record<string, string>;
  components: CostItemComponent[];
  /** Opaque CWICR metadata (variants, variant_stats, etc.) — type-erased. */
  metadata_?: Record<string, unknown>;
}

/**
 * Search params accepted by ``fetchCostSearch``.  ``classification_path`` is
 * a slash-joined breadcrumb (e.g. ``"Buildings/Concrete"``) the backend
 * resolves against ``classification.collection / department / section /
 * subsection``.  When ``cursor`` is supplied, ``offset`` is ignored.
 */
export interface CostSearchParams {
  region?: string;
  q?: string;
  unit?: string;
  source?: string;
  classification_path?: string;
  cursor?: string | null;
  limit?: number;
}

/**
 * Paginated response shape — matches ``CostSearchPaginatedResponse`` on the
 * backend.  ``total`` is only populated on the first page (no cursor).
 *
 * For backwards compatibility with the legacy offset-paginated endpoint, the
 * fetcher tolerates the older shape (no ``next_cursor`` / ``has_more``) and
 * synthesises sensible defaults.
 */
export interface CostSearchPage {
  items: CostSearchItem[];
  next_cursor: string | null;
  has_more: boolean;
  /** Only set on the first page. */
  total: number | null;
}

/** One node in the cost-database category tree. Recursive but bounded to 4 depths. */
export interface CategoryTreeNode {
  name: string;
  count: number;
  children: CategoryTreeNode[];
}

/**
 * Fetch one page of cost search results.  Tolerant to the legacy non-paginated
 * shape so the modal keeps working while the backend agent rolls out the new
 * keyset endpoint.
 */
export async function fetchCostSearch(
  params: CostSearchParams,
): Promise<CostSearchPage> {
  const qs = new URLSearchParams();
  qs.set('limit', String(params.limit ?? 50));
  if (params.region) qs.set('region', params.region);
  if (params.q && params.q.length >= 2) {
    qs.set('q', params.q);
    qs.set('semantic', 'true');
  }
  if (params.unit) qs.set('unit', params.unit);
  if (params.source) qs.set('source', params.source);
  if (params.classification_path) qs.set('classification_path', params.classification_path);
  if (params.cursor) qs.set('cursor', params.cursor);

  const raw = await apiGet<{
    items: CostSearchItem[];
    next_cursor?: string | null;
    has_more?: boolean;
    total?: number | null;
    limit?: number;
    offset?: number;
  }>(`/v1/costs/?${qs.toString()}`);

  const items = raw.items ?? [];
  const limit = raw.limit ?? params.limit ?? 50;
  const next_cursor = raw.next_cursor ?? null;

  // Tolerate legacy offset-paginated shape.  When the backend hasn't shipped
  // the keyset endpoint yet, derive ``has_more`` from the row count vs limit.
  const has_more =
    typeof raw.has_more === 'boolean' ? raw.has_more : items.length >= limit;

  // ``total`` is only meaningful on the first page (no cursor in the request).
  // Honour ``null`` from the backend; fall back to legacy ``total``.
  const total =
    params.cursor == null
      ? raw.total ?? null
      : null;

  return { items, next_cursor, has_more, total };
}

/** Fetch the category tree for a region.  Pass empty string to fetch globally.
 *
 *  ``depth`` (1..4) limits how many classification levels the backend
 *  aggregates — the BOQ "From Database" modal opens with ``depth=2`` to
 *  paint the sidebar within ~150 ms even on cold catalogs, and the full
 *  4-level tree is fetched lazily on idle to fill in deeper drill-downs.
 *  ``parentPath`` scopes the aggregation to a sub-branch, used when the
 *  user expands a depth=2 leaf and we need its grandchildren.
 */
export function fetchCategoryTree(
  region?: string,
  depth?: number,
  parentPath?: string,
): Promise<CategoryTreeNode[]> {
  const qs = new URLSearchParams();
  if (region) qs.set('region', region);
  if (typeof depth === 'number') qs.set('depth', String(depth));
  if (parentPath) qs.set('parent_path', parentPath);
  const suffix = qs.toString();
  return apiGet<CategoryTreeNode[]>(
    `/v1/costs/category-tree/${suffix ? `?${suffix}` : ''}`,
  );
}

/* ── API client ──────────────────────────────────────────────────────── */

export const boqApi = {
  /* BOQ CRUD */
  list: (projectId: string) => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${projectId}`),
  get: (boqId: string) => apiGet<BOQWithPositions>(`/v1/boq/boqs/${boqId}`),
  create: (data: CreateBOQData) => apiPost<BOQ>('/v1/boq/boqs/', data),
  deleteBoq: (boqId: string) => apiDelete(`/v1/boq/boqs/${boqId}`),

  /* Duplicate */
  duplicateBoq: (boqId: string) => apiPost<BOQ>(`/v1/boq/boqs/${boqId}/duplicate/`, {}),

  /* What-if scenario — clone + optional rate adjustment, linked to baseline. */
  createScenario: (boqId: string, data: ScenarioCreateData) =>
    apiPost<BOQ, ScenarioCreateData>(`/v1/boq/boqs/${boqId}/scenarios/`, data),
  duplicatePosition: (posId: string) =>
    apiPost<Position>(`/v1/boq/positions/${posId}/duplicate/`, {}),

  /* Issue #136 — server-enforced structural limits (max nesting depth). */
  getLimits: () => apiGet<BOQLimits>('/v1/boq/limits/'),

  /* Section — Issue #136: optional parent_id nests a section under another. */
  addSection: (
    boqId: string,
    data: { ordinal: string; description: string; parent_id?: string | null },
  ) => apiPost<Position>(`/v1/boq/boqs/${boqId}/sections/`, { boq_id: boqId, ...data }),

  /* Position CRUD */
  // Resolve which BOQ owns a position id. Reuses the existing GET-by-id
  // endpoint (returns the full PositionResponse incl. boq_id) so a deep
  // link like /boq?positionId=<id> can redirect to the right editor.
  getPosition: (posId: string) => apiGet<Position>(`/v1/boq/positions/${posId}`),
  addPosition: (data: CreatePositionData) =>
    apiPost<Position>(`/v1/boq/boqs/${data.boq_id}/positions/`, data),
  updatePosition: (posId: string, data: UpdatePositionData) =>
    apiPatch<Position>(`/v1/boq/positions/${posId}`, data),

  /**
   * v3.12.0 Stream A — bulk update positions.
   * Sends one PATCH covering every selected position id; the server
   * applies the same direct-set / rate-factor / quantity-factor mutation
   * to every row and writes a single umbrella activity-log entry.
   */
  bulkUpdatePositions: (boqId: string, data: BulkPositionUpdateData) =>
    apiPatch<BulkUpdateResult, BulkPositionUpdateData>(
      `/v1/boq/boqs/${boqId}/positions/bulk-update/`,
      data,
    ),

  /**
   * v3.12.0 Stream A — restore a single field on a position from a prior
   * `BOQActivityLog` entry. The backend writes through the normal update
   * path so totals recompute, validation resets, and the version bumps.
   */
  restorePositionField: (boqId: string, positionId: string, data: RestoreFieldData) =>
    apiPost<RestoreFieldResponse, RestoreFieldData>(
      `/v1/boq/boqs/${boqId}/positions/${positionId}/restore-field/`,
      data,
    ),
  /**
   * Re-pick the variant on an existing resource row.  Backend reads the
   * cached ``available_variants`` array on the resource entry, finds the
   * variant whose label matches ``variantCode``, and patches that
   * resource's unit_rate + variant_snapshot.  Other resources untouched.
   *
   * Added in v2.6.26 alongside the per-resource re-pick UI on
   * ``EditableResourceRow``.
   */
  repickResourceVariant: (posId: string, resourceIdx: number, variantCode: string) =>
    apiPatch<Position>(
      `/v1/boq/positions/${posId}/resources/${resourceIdx}/variant/`,
      { variant_code: variantCode },
    ),
  /**
   * Delete a position. For a section/sub-section, pass
   * ``{ cascade: true }`` so the backend recursively removes every
   * descendant (nested sub-sections + their positions). Without it the
   * backend returns 409 when the section still has children, which the
   * UI used to swallow — making sub-section deletion silently no-op.
   */
  deletePosition: (posId: string, opts?: { cascade?: boolean }) =>
    apiDelete(`/v1/boq/positions/${posId}${opts?.cascade ? '?cascade=true' : ''}`),

  /* ── Linked positions (Issue #127 — reuse the same code) ──────────── */
  /** List every member of this position's reference-code link group. */
  getPositionLinks: (posId: string) =>
    apiGet<PositionLinksResponse>(`/v1/boq/positions/${posId}/links/`),
  /** Value-preserving detach: keeps the code & current values, stops
   *  following the master, may promote another instance to master.
   *  Returns the updated PositionResponse. */
  unlinkPosition: (posId: string) =>
    apiPost<Position>(`/v1/boq/positions/${posId}/unlink/`, {}),

  /* ── Resource code reuse (Issue #133) ─────────────────────────────── */
  /** Project-wide lookup: is this resource code already in use? Returns
   *  the existing resource's reusable definition (no quantity) so the
   *  manual-resource form can offer "insert existing" vs "change code". */
  lookupResourceByCode: (projectId: string, code: string) =>
    apiGet<ResourceCodeLookupResponse>(
      `/v1/boq/projects/${projectId}/resource-by-code/?code=${encodeURIComponent(code)}`,
    ),

  /* Position reorder (drag-and-drop) */
  reorderPositions: (boqId: string, positionIds: string[]) =>
    apiPost<{ ok: boolean }>(`/v1/boq/boqs/${boqId}/positions/reorder/`, {
      position_ids: positionIds,
    }),

  /* Markups */
  getMarkups: (boqId: string) => apiGet<MarkupsResponse>(`/v1/boq/boqs/${boqId}/markups/`),
  addMarkup: (boqId: string, data: CreateMarkupData) =>
    apiPost<Markup>(`/v1/boq/boqs/${boqId}/markups/`, data),
  updateMarkup: (boqId: string, markupId: string, data: UpdateMarkupData) =>
    apiPatch<Markup>(`/v1/boq/boqs/${boqId}/markups/${markupId}`, data),
  deleteMarkup: (boqId: string, markupId: string) =>
    apiDelete(`/v1/boq/boqs/${boqId}/markups/${markupId}`),
  applyDefaults: (boqId: string, region: string) =>
    apiPost<Markup[]>(`/v1/boq/boqs/${boqId}/markups/apply-defaults/?region=${encodeURIComponent(region)}`, {}),

  /* Activity */
  getActivity: async (boqId: string): Promise<ActivityResponse> => {
    const raw = await apiGet<{
      items: Array<{
        id: string;
        boq_id: string;
        user_id: string;
        action: string;
        description: string;
        target_type?: string;
        target_id?: string | null;
        changes?: Record<string, unknown>;
        metadata_?: Record<string, unknown>;
        metadata?: Record<string, unknown>;
        created_at: string;
      }>;
      total: number;
    }>(`/v1/boq/boqs/${boqId}/activity/`);
    return {
      activities: (raw.items ?? []).map((item) => ({
        id: item.id,
        boq_id: item.boq_id ?? boqId,
        action: item.action as ActivityAction,
        description: item.description,
        details: item.changes ?? item.metadata_ ?? item.metadata ?? {},
        created_at: item.created_at,
        user_name: undefined,
        // v3.12.0 — surface target identity so the per-cell restore UI can
        // call the position-scoped endpoint with the right ids.
        target_type: item.target_type,
        target_id: item.target_id ?? null,
      })),
      total: raw.total ?? 0,
    };
  },
  getProjectActivity: (projectId: string, limit = 10) =>
    apiGet<{ items: ProjectActivityEntry[]; total: number }>(
      `/v1/boq/projects/${projectId}/activity/?limit=${limit}`,
    ),

  /* Cost autocomplete — uses vector semantic search when available */
  autocomplete: (q: string, limit = 8, region?: string) => {
    const params = new URLSearchParams({ q, limit: String(limit), semantic: 'true' });
    if (region) params.set('region', region);
    return apiGet<CostAutocompleteItem[]>(`/v1/costs/autocomplete/?${params.toString()}`);
  },

  /* AI Chat */
  aiChat: (boqId: string, data: AIChatRequest) =>
    apiPost<AIChatResponse>(`/v1/boq/boqs/${boqId}/ai-chat/`, data),

  /* ── Per-position AI copilot ──────────────────────────────────────── */
  /**
   * Replay the persisted chat history for a position. The backend returns a
   * bare ``CopilotMessage[]``; we tolerate the ``{ messages: [...] }`` envelope
   * too so the dock keeps working whichever shape the backend settles on.
   */
  positionCopilotHistory: async (positionId: string): Promise<CopilotMessage[]> => {
    const raw = await apiGet<CopilotMessage[] | { messages?: CopilotMessage[] }>(
      `/v1/boq/positions/${positionId}/copilot/`,
    );
    if (Array.isArray(raw)) return raw;
    return raw?.messages ?? [];
  },
  /** Send one user turn — returns the assistant turn plus its actions. */
  positionCopilotChat: (positionId: string, message: string) =>
    apiPost<CopilotChatResponse, { message: string }>(
      `/v1/boq/positions/${positionId}/copilot/`,
      { message },
    ),
  /** Human-confirmed apply of a single ``needs_review`` action (server write). */
  positionCopilotApply: (positionId: string, action: CopilotAction) =>
    apiPost<CopilotApplyResponse, { action: CopilotAction }>(
      `/v1/boq/positions/${positionId}/copilot/apply`,
      { action },
    ),

  /* Recalculate rates from resource breakdowns */
  recalculateRates: (boqId: string) =>
    apiPost<{ updated: number; skipped: number; total: number }>(
      `/v1/boq/boqs/${boqId}/recalculate-rates/`,
      {},
    ),

  /* Resource Summary */
  getResourceSummary: (boqId: string) =>
    apiGet<ResourceSummaryResponse>(`/v1/boq/boqs/${boqId}/resource-summary/`),

  /* Cost Breakdown */
  getCostBreakdown: (boqId: string) =>
    apiGet<CostBreakdownResponse>(`/v1/boq/boqs/${boqId}/cost-breakdown/`),

  /* AACE Estimate Classification */
  getClassification: (boqId: string) =>
    apiGet<EstimateClassificationResponse>(`/v1/boq/boqs/${boqId}/classification/`),

  /* Sensitivity Analysis */
  getSensitivity: (boqId: string, variationPct = 10) =>
    apiGet<SensitivityResponse>(
      `/v1/boq/boqs/${boqId}/sensitivity/?variation_pct=${variationPct}`,
    ),

  /* Monte Carlo Cost Risk */
  getCostRisk: (boqId: string, correlation?: number) => {
    const qs = correlation == null ? '' : `?correlation=${correlation}`;
    return apiGet<CostRiskResponse>(`/v1/boq/boqs/${boqId}/cost-risk/${qs}`);
  },

  /* Statistics — aggregated BOQ metrics.
   * Money fields (direct_cost / grand_total / avg_unit_rate) follow the
   * Decimal-as-string wire contract (v3 §10) - parse with Number()/a money
   * helper at the call site, never assume a JS number. */
  getStatistics: (boqId: string) =>
    apiGet<{
      boq_id: string;
      boq_name: string;
      status: string;
      position_count: number;
      section_count: number;
      direct_cost: string;
      grand_total: string;
      avg_unit_rate: string;
      completion_pct: number;
      unit_breakdown: Record<string, number>;
      source_breakdown: Record<string, number>;
      classification_coverage_pct: number;
      created_at: string;
      updated_at: string;
    }>(`/v1/boq/boqs/${boqId}/statistics/`),

  /* Snapshot / Version History */
  getSnapshots: (boqId: string) =>
    apiGet<BOQSnapshot[]>(`/v1/boq/boqs/${boqId}/snapshots/`),
  createSnapshot: (boqId: string, label?: string) =>
    apiPost<BOQSnapshot>(`/v1/boq/boqs/${boqId}/snapshots/`, { name: label ?? '' }),
  restoreSnapshot: (boqId: string, snapshotId: string) =>
    apiPost<{ ok: boolean }>(`/v1/boq/boqs/${boqId}/restore/${snapshotId}`, {}),

  /* ── Feature 1: model→BOQ quantity links ──────────────────────────── */
  /** List every live model→position binding for one position. */
  getQuantityLinks: (positionId: string) =>
    apiGet<QuantityLink[]>(
      `/v1/boq/positions/${positionId}/quantity-links/`,
    ),
  /** Bind a position quantity to BIM elements. Does NOT mutate the
   *  quantity — that requires an explicit confirm/apply. */
  createQuantityLink: (positionId: string, data: CreateQuantityLinkData) =>
    apiPost<QuantityLink, CreateQuantityLinkData>(
      `/v1/boq/positions/${positionId}/quantity-links/`,
      data,
    ),
  deleteQuantityLink: (positionId: string, linkId: string) =>
    apiDelete<void>(
      `/v1/boq/positions/${positionId}/quantity-links/${linkId}`,
    ),
  /** Re-pull every link against the latest model version (read-only;
   *  flags stale rows and returns old→new→delta review payload). */
  refreshQuantityLinks: (boqId: string) =>
    apiPost<QuantityLinkRefreshResponse>(
      `/v1/boq/boqs/${boqId}/quantity-links/refresh/`,
      {},
    ),
  /** Human-confirmed apply — only the listed link ids are written. */
  applyQuantityLinks: (boqId: string, linkIds: string[]) =>
    apiPost<QuantityLinkApplyResponse, { link_ids: string[] }>(
      `/v1/boq/boqs/${boqId}/quantity-links/apply/`,
      { link_ids: linkIds },
    ),

  /* ── Feature 2: estimate baseline / line-level compare ─────────────── */
  compareBoqs: (boqId: string, otherId: string) =>
    apiGet<BOQCompareResponse>(
      `/v1/boq/boqs/${boqId}/compare/${otherId}`,
    ),

  /* ── Send to tender — create a tender package from BOQ sections ─────── */
  /** Empty `section_ids` means every top-level section of the BOQ. Lands on
   *  the tendering module, returns the new draft package reference. */
  createTenderFromBoq: (data: CreateTenderFromBoqData) =>
    apiPost<TenderPackageRef, CreateTenderFromBoqData>(
      '/v1/tendering/packages/from-boq/',
      data,
    ),

  /* Enrich positions with resources from cost database */
  enrichResources: (boqId: string) =>
    apiPost<{ enriched_count: number; total_positions: number }>(
      `/v1/boq/boqs/${boqId}/enrich-resources/`,
      {},
    ),

  /* AI: Classify position */
  classify: (data: { description: string; unit?: string; project_standard?: string }) =>
    apiPost<ClassifyResponse>('/v1/boq/boqs/classify/', data),

  /* AI: Suggest rate */
  suggestRate: (data: { description: string; unit?: string; classification?: Record<string, string>; region?: string }) =>
    apiPost<SuggestRateResponse>('/v1/boq/boqs/suggest-rate/', data),

  /* AI: Check anomalies */
  checkAnomalies: (boqId: string) =>
    apiPost<AnomalyCheckResponse>(`/v1/boq/boqs/${boqId}/check-anomalies/`, {}),

  /* AI: Search cost items (vector similarity) */
  searchCostItems: (data: {
    query: string;
    unit?: string;
    region?: string;
    limit?: number;
    min_score?: number;
  }) => apiPost<CostItemSearchResponse>('/v1/boq/boqs/search-cost-items/', data),

  /* AI: Enhance description via LLM */
  enhanceDescription: (data: {
    description: string;
    unit?: string;
    classification?: Record<string, string>;
    locale?: string;
  }) => apiPost<EnhanceDescriptionResponse>('/v1/boq/boqs/enhance-description/', data),

  /* AI: Suggest prerequisites via LLM */
  suggestPrerequisites: (data: {
    description: string;
    unit?: string;
    classification?: Record<string, string>;
    existing_descriptions?: string[];
    locale?: string;
  }) => apiPost<SuggestPrerequisitesResponse>('/v1/boq/boqs/suggest-prerequisites/', data),

  /* AI: Check scope completeness via LLM */
  checkScope: (boqId: string, data: {
    project_type?: string;
    region?: string;
    currency?: string;
    locale?: string;
  }) => apiPost<CheckScopeResponse>(`/v1/boq/boqs/${boqId}/check-scope/`, data),

  /* AI: Escalate rate via LLM */
  escalateRate: (data: {
    description: string;
    unit: string;
    rate: number;
    currency?: string;
    base_year?: number;
    target_year?: number;
    region?: string;
    locale?: string;
  }) => apiPost<EscalateRateResponse>('/v1/boq/boqs/escalate-rate/', data),

  /* Custom Columns — manage user-defined fields per BOQ */
  listCustomColumns: (boqId: string) =>
    apiGet<CustomColumnDef[]>(`/v1/boq/boqs/${boqId}/columns/`),
  addCustomColumn: (boqId: string, data: CustomColumnDef) =>
    apiPost<CustomColumnDef, CustomColumnDef>(`/v1/boq/boqs/${boqId}/columns/`, data),
  deleteCustomColumn: (boqId: string, columnName: string) =>
    apiDelete<void>(`/v1/boq/boqs/${boqId}/columns/${columnName}`),

  /* Per-BOQ named variables ($GFA, $LABOR_RATE, …). Used by the formula
     engine; replace-the-whole-list semantics keep the editor simple. */
  listBoqVariables: (boqId: string) =>
    apiGet<BOQVariable[]>(`/v1/boq/boqs/${boqId}/variables/`),
  replaceBoqVariables: (boqId: string, variables: BOQVariable[]) =>
    apiPut<BOQVariable[], BOQVariable[]>(`/v1/boq/boqs/${boqId}/variables/`, variables),

  /* Renumber positions using one of several professional schemes.
     - gap10:      01, 01.10, 01.20  (German tender default — leaves room to insert later)
     - gap100:     01, 01.100, 01.200 (very large BOQs)
     - sequential: 01, 01.01, 01.02  (compact, traditional)
     - dotted:     1, 1.1, 1.2      (NRM-style short form) */
  renumberPositions: (
    boqId: string,
    options?: { scheme?: 'gap10' | 'gap100' | 'sequential' | 'dotted'; pad?: boolean },
  ) =>
    apiPost<{ renumbered: number; scheme: string }>(
      `/v1/boq/boqs/${boqId}/renumber/`,
      options ?? {},
    ),
};

/**
 * Custom column definition stored in BOQ `metadata.custom_columns`.
 *
 * `sort_order` is assigned by the backend on insert (= current count) so the
 * client can omit it; on read it is always populated. The grid keeps columns
 * sorted by this value.
 *
 * v2.7.0/E — `calculated` columns carry a `formula` evaluated by the BOQ
 * formula engine on every render. They are read-only; their value updates
 * automatically when any referenced position, $variable, or row field
 * changes. `decimals` controls display precision (default 2).
 */
export interface CustomColumnDef {
  name: string;
  display_name: string;
  column_type: 'text' | 'number' | 'date' | 'select' | 'calculated';
  options?: string[];
  sort_order?: number;
  /** Formula source for `calculated` columns. e.g. `=quantity * unit_rate * 1.19`. */
  formula?: string;
  /** Display decimals for `calculated` columns when result is numeric. */
  decimals?: number;
  /**
   * Optional semantic hint that turns a `number` column into an auto-derived
   * value. See `grid/columnDefs.ts` for the runtime contract.
   *   - `resource_sum`           — sum of position resources matching `resource_role`
   *   - `percentage_of_unit_rate`— labor/material/etc share of unit_rate as %
   */
  derived?: 'resource_sum' | 'percentage_of_unit_rate';
  /** Single role or a list — array form lets a column sum several resource
   *  types (e.g. GAEB Sonstiges-EP = `other + operator + subcontractor`)
   *  so the EP-split adds up to ``unit_rate``. */
  resource_role?:
    | 'material'
    | 'labor'
    | 'equipment'
    | 'operator'
    | 'subcontractor'
    | 'other'
    | Array<'material' | 'labor' | 'equipment' | 'operator' | 'subcontractor' | 'other'>;
}

/**
 * Per-BOQ named variable. Stored on `boq.metadata.variables`. Names are
 * UPPER_SNAKE_CASE without the leading `$` — the UI prepends the dollar
 * sign for display only. Values are typed: `number` round-trips as a
 * float, `text` and `date` as strings, `null` means unset.
 */
export interface BOQVariable {
  name: string;
  type: 'number' | 'text' | 'date';
  value: number | string | null;
  description?: string | null;
}

/* ── LLM AI feature types ───────────────────────────────────────────── */

export interface EnhanceDescriptionResponse {
  enhanced_description: string;
  specifications: string[];
  standards: string[];
  confidence: number;
  model_used: string;
  tokens_used: number;
}

export interface PrerequisiteItem {
  description: string;
  unit: string;
  typical_rate_eur: number;
  relationship: 'prerequisite' | 'companion' | 'successor';
  reason: string;
}

export interface SuggestPrerequisitesResponse {
  suggestions: PrerequisiteItem[];
  model_used: string;
  tokens_used: number;
}

export interface ScopeMissingItem {
  description: string;
  category: string;
  priority: 'high' | 'medium' | 'low';
  reason: string;
  estimated_rate: number;
  unit: string;
}

export interface CheckScopeResponse {
  completeness_score: number;
  missing_items: ScopeMissingItem[];
  warnings: string[];
  summary: string;
  model_used: string;
  tokens_used: number;
}

export interface EscalationFactors {
  material_inflation: number;
  labor_cost_change: number;
  regional_adjustment: number;
}

export interface EscalateRateResponse {
  original_rate: number;
  escalated_rate: number;
  escalation_percent: number;
  factors: EscalationFactors;
  confidence: 'high' | 'medium' | 'low';
  reasoning: string;
  model_used: string;
  tokens_used: number;
}
