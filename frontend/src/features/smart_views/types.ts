// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Smart Views — shared TypeScript types.
//
// These mirror the backend Pydantic schemas in
// ``backend/app/modules/smart_views/schemas.py``. Keep them in lockstep:
// every key here is a public contract that the backend will validate
// strictly (the SmartViewSelector model uses ``extra='forbid'``).
//
// Counter-intuitive core idea: a Smart View is NOT a snapshot. It is a
// list of ``{selector, action}`` *rules* that re-evaluate every time the
// model is loaded — so views survive geometry revisions.

/** Selector operators understood by the backend evaluator. */
export type SmartViewOperator =
  | 'eq'
  | 'neq'
  | 'contains'
  | 'regex'
  | 'gt'
  | 'lt'
  | 'in'
  | 'exists'
  | 'between';

/** Rule actions understood by the backend evaluator. */
export type SmartViewAction =
  | 'show'
  | 'hide'
  | 'color'
  | 'transparent'
  | 'isolate';

/** Default behaviour for elements not touched by any rule. */
export type SmartViewDefaultAction = 'show_all' | 'hide_all';

/** Scope of a view — who can see / edit it. */
export type SmartViewScopeType = 'user' | 'project' | 'federation';

/** Predicate describing which elements a rule applies to. */
export interface SmartViewSelector {
  ifc_class: string | null;
  property: string | null;
  operator: SmartViewOperator | null;
  /** Whatever the operator compares against. ``null`` is legal for
   *  ``exists`` and for ``ifc_class``-only selectors. */
  value: unknown;
}

/** Optional per-action arguments. */
export interface SmartViewActionArgs {
  /** Used by action='color'. ``#RRGGBB`` or ``#RRGGBBAA`` hex. */
  color?: string | null;
  /** Used by action='transparent'. Clamped to [0.0, 1.0] server-side. */
  opacity?: number | null;
  /** Used by action='color' to bucket-colour every match by a property. */
  color_by_property?: string | null;
}

/** A single ``{selector → action}`` rule. */
export interface SmartViewRule {
  id: string;
  selector: SmartViewSelector;
  action: SmartViewAction;
  action_args: SmartViewActionArgs;
  order: number;
}

/** Response shape for read / list / create / update endpoints. */
export interface SmartViewResponse {
  id: string;
  scope_type: SmartViewScopeType | string;
  scope_id: string;
  name: string;
  description: string | null;
  /** Optional folder label for grouping saved views. ``null`` = ungrouped. */
  folder: string | null;
  rules: SmartViewRule[];
  default_action: SmartViewDefaultAction | string;
  color_legend: Record<string, unknown> | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  /** Signed share token — only populated for the authoring user (the
   *  backend redacts the field for collaborators). ``null`` means
   *  "not shared". */
  share_token?: string | null;
}

/** Body for ``POST /smart-views/``. */
export interface SmartViewCreatePayload {
  name: string;
  description?: string | null;
  /** Optional folder label. Blank / omitted = ungrouped. */
  folder?: string | null;
  rules: SmartViewRule[];
  default_action: SmartViewDefaultAction;
  scope_type: SmartViewScopeType;
  scope_id: string;
}

/** Body for ``PUT /smart-views/{id}``. Every field is optional. */
export interface SmartViewUpdatePayload {
  name?: string;
  description?: string | null;
  /** Pass "" to move the view back to ungrouped. */
  folder?: string | null;
  rules?: SmartViewRule[];
  default_action?: SmartViewDefaultAction;
}

/** Resolved per-element visual state — the evaluator's output for one
 *  element keyed by its ``stable_id`` (the IFC GUID / Revit UniqueId). */
export interface ElementState {
  visible: boolean;
  color: string | null;
  opacity: number;
}

/** Payload returned by ``POST /smart-views/{id}/evaluate``. */
export interface SmartViewEvaluateResponse {
  states: Record<string, ElementState>;
  legend: Record<string, string> | null;
  element_count: number;
}

/** Catalogue summary entry returned by ``GET /smart-views/presets``. */
export interface SmartViewPresetSummary {
  preset_id: string;
  category: string;
  name: string;
  description: string;
  rule_count: number;
}

/** Body for ``POST /smart-views/presets/{preset_id}/install``. */
export interface InstallPresetPayload {
  scope_type: SmartViewScopeType;
  scope_id: string;
}

/** Returned by ``POST /smart-views/{view_id}/share``. */
export interface SmartViewShareInfo {
  view_id: string;
  share_token: string;
  /** Server-side relative path — frontend turns it into an absolute URL. */
  url: string;
}

/** Static autocomplete list for the IfcClass field — covers the common
 *  IFC4 entity types a user actually filters on. The free-form input
 *  still accepts arbitrary values; this is just the dropdown hint. */
export const COMMON_IFC_CLASSES: readonly string[] = [
  'IfcWall',
  'IfcSlab',
  'IfcBeam',
  'IfcColumn',
  'IfcDoor',
  'IfcWindow',
  'IfcSpace',
  'IfcPipeSegment',
  'IfcDuctSegment',
  'IfcCableSegment',
  'IfcStair',
  'IfcRailing',
] as const;
