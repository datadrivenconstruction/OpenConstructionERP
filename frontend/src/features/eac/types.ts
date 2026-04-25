/**
 * EacRuleDefinition v2.0 — TypeScript mirror of the canonical JSON Schema.
 *
 * Source of truth: `backend/app/modules/eac/schema/EacRuleDefinition.schema.json`
 * (lands in EAC-1.2). This file is the frontend-side hand-written mirror used by
 * the visual block editor. Once the backend ships, `packages/oe-schema/eac.ts`
 * will be auto-generated and replace this file — at which point we MUST hold
 * the field names verbatim. Therefore: keep names exactly as RFC 35 §3 / spec
 * §1.5 dictate (snake_case where the JSON uses snake_case).
 *
 * Discriminated unions are keyed on a literal `type` / `kind` field so the
 * editor can switch on the discriminant without runtime type checks.
 *
 * NOTE: This file deliberately uses snake_case for property names because it
 * mirrors the on-the-wire JSON schema. Frontend code that consumes these types
 * should treat them as data transport objects, not domain models.
 */

// ── Output mode ──────────────────────────────────────────────────────────────

/** One engine, four output modes (RFC 35 L11). */
export type OutputMode = 'aggregate' | 'boolean' | 'clash' | 'issue';

// ── Entity selectors (FR-1.4) ────────────────────────────────────────────────

/** Match elements by IFC class. */
export interface IfcClassSelector {
  type: 'ifc_class';
  ifc_class: string;
  /** Include subclasses, e.g. ifcWall + ifcWallStandardCase. */
  include_subtypes?: boolean;
}

/** Match elements by Revit category. */
export interface CategorySelector {
  type: 'category';
  category: string;
}

/** Match elements by classification code mapped via classifier composition. */
export interface ClassificationSelector {
  type: 'classification';
  classifier_id: string;
  /** Single code, e.g. "Uniformat:B2010". */
  code?: string;
  /** Match any of these codes. */
  codes?: string[];
}

/** Match elements by spatial container (level, zone, room). */
export interface SpatialSelector {
  type: 'spatial';
  /** "level" | "zone" | "room" | etc. */
  scope: 'level' | 'zone' | 'room' | 'building' | 'site';
  ref_id: string;
}

/** Match elements by attribute predicate alone. */
export interface AttributeSelector {
  type: 'attribute';
  predicate: Predicate;
}

/** Compose selectors with set logic. */
export interface AndSelector {
  type: 'and';
  children: EntitySelector[];
}
export interface OrSelector {
  type: 'or';
  children: EntitySelector[];
}
export interface NotSelector {
  type: 'not';
  child: EntitySelector;
}

/** Discriminated union of every selector kind. */
export type EntitySelector =
  | IfcClassSelector
  | CategorySelector
  | ClassificationSelector
  | SpatialSelector
  | AttributeSelector
  | AndSelector
  | OrSelector
  | NotSelector;

// ── Attribute references (FR-1.5) ────────────────────────────────────────────

/** Exact property reference: `pset.name`. */
export interface ExactAttributeRef {
  kind: 'exact';
  /** Pset name. Null/empty = instance attribute (e.g. Name, GlobalId). */
  pset_name?: string | null;
  property_name: string;
  /** "instance" | "type" | "auto" — matches spec source_filter enum. */
  source_filter?: 'instance' | 'type' | 'auto';
}

/** Reference an alias (canonical name resolved through synonyms). */
export interface AliasAttributeRef {
  kind: 'alias';
  alias_id: string;
  /** Alias canonical name; informational, not used for resolution. */
  canonical_name?: string;
}

/** Reference all properties matching a regex pattern. */
export interface RegexAttributeRef {
  kind: 'regex';
  /** Regex pattern, ReDoS-safe (compiled with timeout server-side). */
  pattern: string;
  /** Apply to property name, pset name, or both. */
  scope: 'property_name' | 'pset_name' | 'both';
  case_sensitive?: boolean;
}

/** Discriminated union of attribute reference kinds. */
export type AttributeRef = ExactAttributeRef | AliasAttributeRef | RegexAttributeRef;

// ── Constraints (FR-1.6) — 25 operators ──────────────────────────────────────

/** All 25 constraint operators per spec §1.6. */
export type ConstraintOperator =
  // Equality
  | 'eq'
  | 'ne'
  // Comparison
  | 'gt'
  | 'gte'
  | 'lt'
  | 'lte'
  // Range
  | 'between'
  | 'not_between'
  // Set membership
  | 'in'
  | 'not_in'
  // String
  | 'starts_with'
  | 'ends_with'
  | 'contains'
  | 'not_contains'
  | 'matches' // regex
  | 'not_matches'
  // Existence / null
  | 'exists'
  | 'not_exists'
  | 'is_null'
  | 'is_not_null'
  // Type
  | 'is_numeric'
  | 'is_string'
  | 'is_boolean'
  // Unit-aware
  | 'eq_unit_aware'
  | 'gte_unit_aware'
  | 'lte_unit_aware';

/** A constraint applied to an attribute. */
export interface Constraint {
  operator: ConstraintOperator;
  /** Right-hand side value. For binary ops; null for unary (exists/is_null). */
  value?: string | number | boolean | null;
  /** For `between`/`not_between`: [min, max]. */
  values?: Array<string | number>;
  /** Tolerance for unit-aware comparisons. */
  tolerance?: number;
  /** Unit hint, e.g. "mm", "m". Resolved server-side via alias. */
  unit?: string;
  /** When the attribute is missing on an element: "fail" | "pass" | "skip". */
  treat_missing_as?: 'fail' | 'pass' | 'skip';
  case_sensitive?: boolean;
}

// ── Predicates (FR-1.6 logical composition) ──────────────────────────────────

/** A triplet = AttributeRef + Constraint applied to one element. */
export interface TripletPredicate {
  type: 'triplet';
  attribute: AttributeRef;
  constraint: Constraint;
}

/** Logical AND of N children. */
export interface AndPredicate {
  type: 'and';
  children: Predicate[];
}

/** Logical OR of N children. */
export interface OrPredicate {
  type: 'or';
  children: Predicate[];
}

/** Logical NOT of 1 child. */
export interface NotPredicate {
  type: 'not';
  child: Predicate;
}

/** Discriminated union of predicate kinds. */
export type Predicate = TripletPredicate | AndPredicate | OrPredicate | NotPredicate;

// ── Local variables (FR-1.7) ─────────────────────────────────────────────────

/** Aggregate function used inside a local variable definition. */
export type AggregateFunction =
  | 'sum'
  | 'avg'
  | 'min'
  | 'max'
  | 'count'
  | 'count_distinct'
  | 'first'
  | 'last';

/** A local variable defined within the scope of a single rule. */
export interface LocalVariableDefinition {
  name: string;
  /** Optional aggregate function applied across matched elements. */
  aggregate?: AggregateFunction;
  /** Source attribute or formula expression. */
  source?: AttributeRef;
  /** Or a literal expression (simpleeval-evaluated). */
  expression?: string;
  /** Result unit, e.g. "m³". */
  unit?: string;
  description?: string;
}

// ── Clash (FR-1.7) ───────────────────────────────────────────────────────────

/** Clash detection configuration (output_mode = "clash"). */
export interface ClashConfig {
  /** Geometric algorithm. */
  algorithm: 'exact' | 'obb' | 'sphere';
  /** What to detect. */
  metric: 'min_distance' | 'intersection_volume' | 'enclosed';
  /** Threshold, semantics depend on metric (e.g. mm for min_distance). */
  threshold: number;
  /** Set A — elements to clash. */
  set_a: EntitySelector;
  /** Set B — elements to clash against. */
  set_b: EntitySelector;
}

// ── Issue templates (FR-1.7) ─────────────────────────────────────────────────

/** Template used to render an Issue when output_mode = "issue". */
export interface IssueTemplate {
  /** Title with `${var}` placeholders. */
  title: string;
  /** Description with `${var}` placeholders. */
  description?: string;
  /** BCF topic_type. */
  topic_type?: string;
  priority?: 'low' | 'medium' | 'high' | 'critical';
  /** Project stage tag. */
  stage?: string;
  labels?: string[];
}

// ── Top-level rule definition ────────────────────────────────────────────────

/**
 * The canonical EAC rule shape persisted to `eac_rules.definition_json`.
 *
 * Spec §1.5 — version field is the schema version, not the rule version
 * (rule version lives in the parent ORM row).
 */
export interface EacRuleDefinition {
  /** Schema version, currently "2.0". */
  schema_version: '2.0';
  /** Display name. */
  name: string;
  description?: string;
  output_mode: OutputMode;
  /** Top-level entity selector — defines the set this rule applies to. */
  selector: EntitySelector;
  /**
   * Predicate evaluated per element (boolean / issue modes).
   * For `aggregate` mode, this is the filter; the actual aggregation lives in
   * `formula`.
   */
  predicate?: Predicate;
  /** simpleeval expression evaluated per element (aggregate mode). */
  formula?: string;
  /** Result unit, e.g. "m³". */
  result_unit?: string;
  /** Clash configuration (only for output_mode = "clash"). */
  clash?: ClashConfig;
  /** Issue template (only for output_mode = "issue"). */
  issue_template?: IssueTemplate;
  /** Locally scoped variables. */
  local_variables?: LocalVariableDefinition[];
  /** Optional metadata for marketplace / IDS round-trip. */
  metadata?: Record<string, unknown>;
}

// ── UI-only types (not persisted) ────────────────────────────────────────────

/**
 * The five block colors per spec §3.2. Used by `tokens.ts` and every block
 * component to drive consistent styling.
 */
export type BlockColor = 'selector' | 'logic' | 'attribute' | 'constraint' | 'variable';

/**
 * Logical predicate kind shown by `<LogicBlock>`. Subset of `Predicate.type`
 * minus `triplet` (which has its own dedicated block component).
 */
export type LogicKind = 'and' | 'or' | 'not';

/**
 * Palette item categories per spec FR-3.1. Drives the grouped section headers
 * inside `<EacBlockPalette>`.
 */
export type PaletteCategory =
  | 'selectors'
  | 'logic'
  | 'triplet'
  | 'attributes'
  | 'constraints'
  | 'variables'
  | 'templates';
