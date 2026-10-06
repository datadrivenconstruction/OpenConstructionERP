// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ruleSandbox — pure, dependency-free logic for the BIM Quantity Rules sandbox.
 *
 * Everything here mirrors the backend rule engine
 * (``BIMHubService._rule_matches_element`` / ``_extract_quantity`` in
 * ``backend/app/modules/bim_hub/service.py``) so the editor can run a *draft*
 * rule against an already-loaded model client-side and show matched elements
 * plus per-element computed quantities BEFORE the rule is ever saved.
 *
 * It also carries the unit-safety check (declared unit vs. the dimension the
 * quantity source produces) and the coverage / missing-scope detector. Keeping
 * this as a side-effect-free module means it can be unit-tested in isolation
 * and reused from any component without dragging in React or the network layer.
 *
 * NB: this is a *preview*. The authoritative apply still runs on the backend;
 * the sandbox is the "AI-augmented, human-confirmed" review surface — it shows
 * what would happen so the estimator can confirm before persisting.
 */

/* ── Minimal element shape the sandbox needs ──────────────────────────────── */

/** The five-ish fields the rule engine reads off a BIM element. Intentionally
 *  a structural subset of ``BIMElementData`` so callers can pass the skeleton
 *  element list straight through. */
export interface SandboxElement {
  id: string;
  stable_id?: string;
  name?: string;
  element_type?: string;
  category?: string;
  properties?: Record<string, unknown> | null;
  quantities?: Record<string, number> | null;
}

/** A draft rule, expressed in the same vocabulary as the editor form. */
export interface SandboxRule {
  element_type_filter: string;
  property_filter: Record<string, string>;
  quantity_source: string;
  multiplier: string;
  waste_factor_pct: string;
  unit: string;
}

/* ── fnmatch-equivalent (matches Python's case-insensitive fnmatch) ───────── */

/** Translate a wildcard pattern (``*`` and ``?`` only) into a RegExp, the same
 *  vocabulary as the server's ``_glob_match``: brackets are literal. Case-insensitive
 *  to mirror the backend's ``.lower()`` on both sides. Any regex-special chars
 *  in the literal portions are escaped so a pattern like ``Wall (Ext)`` is
 *  matched literally rather than throwing. The ``s`` flag lets ``*`` run
 *  across line breaks, as the server's does. */
export function wildcardToRegExp(pattern: string): RegExp {
  let out = '';
  for (const ch of pattern) {
    if (ch === '*') out += '.*';
    else if (ch === '?') out += '.';
    else out += ch.replace(/[.+^${}()|[\]\\]/g, '\\$&');
  }
  return new RegExp(`^${out}$`, 'is');
}

/** Case-insensitive fnmatch for a single value against a single pattern. */
export function fnmatchCI(value: string, pattern: string): boolean {
  return wildcardToRegExp(pattern).test(value);
}

/* ── Property matching (mirror of _property_value_matches) ─────────────────── */

/**
 * Type-aware comparison of an element property value against a filter pattern.
 * Mirrors the backend ``_property_value_matches`` so the sandbox preview and
 * the real apply never disagree about which elements a rule selects.
 */
export function propertyValueMatches(actual: unknown, expected: unknown): boolean {
  // Explicit "must not be set" filter.
  if (expected === null || expected === undefined) {
    return actual === null || actual === undefined;
  }
  if (actual === null || actual === undefined) return false;

  // List actual: membership / intersection semantics.
  if (Array.isArray(actual)) {
    if (Array.isArray(expected)) {
      return actual.some((item) => expected.some((exp) => propertyValueMatches(item, exp)));
    }
    return actual.some((item) => propertyValueMatches(item, expected));
  }

  // Dict actual + dict expected: recursive containment.
  if (
    typeof actual === 'object' &&
    typeof expected === 'object' &&
    !Array.isArray(expected)
  ) {
    const a = actual as Record<string, unknown>;
    const e = expected as Record<string, unknown>;
    return Object.entries(e).every(([k, v]) => propertyValueMatches(a[k], v));
  }

  // Both strings: fnmatch wildcards, case-insensitive.
  if (typeof actual === 'string' && typeof expected === 'string') {
    return fnmatchCI(actual, expected);
  }

  // A whole number also matches its float spelling ("300.0"), which is how
  // the editor's value list writes a width stored as 300.0. Below 1e16, as on
  // the server, where Python stops writing floats that way.
  if (
    typeof actual === 'number' &&
    Number.isInteger(actual) &&
    Math.abs(actual) < 1e16 &&
    String(expected).toLowerCase() === `${actual}.0`
  ) {
    return true;
  }

  // Mixed / numeric / boolean: exact equality after string coercion.
  return String(actual).toLowerCase() === String(expected).toLowerCase();
}

/* ── Rule → element matching (mirror of _rule_matches_element) ─────────────── */

/** Does a draft rule fire on a given element? */
export function ruleMatchesElement(rule: SandboxRule, element: SandboxElement): boolean {
  const typeFilter = (rule.element_type_filter ?? '').trim();
  if (typeFilter && typeFilter !== '*') {
    const et = element.element_type ?? '';
    if (!et) return false;
    // The filter field accepts a comma-separated list of patterns (the editor
    // placeholder shows "Wall*, IfcWall, Curtainwall*"); a single one matching
    // is enough. The backend splits the same way; both engines read the case
    // table in __tests__/fixtures/ruleMatchingParity.json.
    const patterns = typeFilter
      .split(',')
      .map((p) => p.trim())
      .filter(Boolean);
    const list = patterns.length > 0 ? patterns : [typeFilter];
    if (!list.some((p) => fnmatchCI(et, p))) return false;
  }

  const pf = rule.property_filter ?? {};
  const props = element.properties ?? {};
  for (const [key, pattern] of Object.entries(pf)) {
    if (!key.trim()) continue;
    if (!propertyValueMatches(lookupPropertyKey(props, key), pattern)) return false;
  }
  return true;
}

/** Value under a property key the way the server resolves it: exact key first,
 *  then trimmed and case-insensitive, so a rule naming "Phase Created" reads
 *  the "phase created" key the DDC import stored. */
export function lookupPropertyKey(props: Record<string, unknown>, key: string): unknown {
  if (Object.prototype.hasOwnProperty.call(props, key)) return props[key];
  const wanted = key.trim().toLowerCase();
  for (const [k, v] of Object.entries(props)) {
    if (k.trim().toLowerCase() === wanted) return v;
  }
  return undefined;
}

/* ── Quantity extraction (mirror of _extract_quantity) ─────────────────────── */

/** Pull the raw quantity for a source spec off an element, or ``null`` when the
 *  element carries no usable value (missing property / quantity key, or a
 *  non-numeric value). */
export function extractRawQuantity(
  element: SandboxElement,
  source: string,
): number | null {
  const src = (source ?? '').trim();
  if (!src) return null;

  let value: unknown;
  if (src.startsWith('property:')) {
    // Resolved like a property-filter key, as the server does.
    const propName = src.slice('property:'.length);
    value = lookupPropertyKey(element.properties ?? {}, propName);
  } else if (src === 'count') {
    return 1;
  } else {
    value = (element.quantities ?? {})[src];
  }

  if (value === null || value === undefined) return null;
  const num = typeof value === 'number' ? value : Number(String(value));
  if (!Number.isFinite(num)) return null;
  return num;
}

/** Apply multiplier and waste factor to a raw quantity. Returns ``null`` when
 *  the multiplier or waste cannot be parsed (so the row is skipped, exactly
 *  like the backend's invalid_decimal skip path). */
export function applyAdjustment(
  raw: number,
  multiplier: string,
  wastePct: string,
): number | null {
  const mult = Number((multiplier ?? '1').trim() || '1');
  const waste = Number((wastePct ?? '0').trim() || '0');
  if (!Number.isFinite(mult) || !Number.isFinite(waste)) return null;
  const adjusted = raw * mult * (1 + waste / 100);
  if (!Number.isFinite(adjusted)) return null;
  return adjusted;
}

/* ── Sandbox run ──────────────────────────────────────────────────────────── */

export type SkipReason = 'missing_property' | 'invalid_decimal';

export interface SandboxMatchRow {
  element_id: string;
  stable_id: string;
  element_type: string;
  name: string;
  raw_quantity: number;
  adjusted_quantity: number;
}

export interface SandboxSkipRow {
  element_id: string;
  stable_id: string;
  element_type: string;
  reason: SkipReason;
}

export interface SandboxRunResult {
  /** Elements that matched the filter AND yielded a usable quantity. */
  matches: SandboxMatchRow[];
  /** Elements that matched the filter but were dropped (no quantity / bad math). */
  skips: SandboxSkipRow[];
  /** Distinct element_type values that the filter selected at all. */
  matchedTypes: string[];
  /** Σ of adjusted quantities across matches — the number that would land on
   *  the auto-created BOQ position. */
  totalAdjusted: number;
  /** Number of elements scanned. */
  scanned: number;
  /** Every match / skip when the server sends only the first rows of each
   *  list; absent for a local run, where the lists are complete. */
  matchCount?: number;
  skipCount?: number;
  /** Where properties the import's 30-per-element cap left out come from
   *  (server runs only): the converter's sidecar, a sidecar rebuilt from the
   *  database (they are gone until a re-import), or none. */
  sidecar?: 'full' | 'rebuilt' | 'missing';
}

/** How many elements matched and were skipped, whether the lists are complete or not. */
export function resultCounts(result: SandboxRunResult): { matched: number; skipped: number } {
  return {
    matched: result.matchCount ?? result.matches.length,
    skipped: result.skipCount ?? result.skips.length,
  };
}

/**
 * Run a draft rule against a list of loaded elements and return the would-be
 * matches, skips and roll-up. This is the heart of the "test before save"
 * sandbox — same selection + quantity math as the backend apply, executed
 * locally for instant feedback.
 */
export function runSandbox(
  rule: SandboxRule,
  elements: readonly SandboxElement[],
): SandboxRunResult {
  const matches: SandboxMatchRow[] = [];
  const skips: SandboxSkipRow[] = [];
  const matchedTypes = new Set<string>();
  let totalAdjusted = 0;

  for (const el of elements) {
    if (!ruleMatchesElement(rule, el)) continue;
    matchedTypes.add(el.element_type ?? '');

    const raw = extractRawQuantity(el, rule.quantity_source);
    if (raw === null) {
      skips.push({
        element_id: el.id,
        stable_id: el.stable_id ?? '',
        element_type: el.element_type ?? '',
        reason: 'missing_property',
      });
      continue;
    }
    const adjusted = applyAdjustment(raw, rule.multiplier, rule.waste_factor_pct);
    if (adjusted === null) {
      skips.push({
        element_id: el.id,
        stable_id: el.stable_id ?? '',
        element_type: el.element_type ?? '',
        reason: 'invalid_decimal',
      });
      continue;
    }
    matches.push({
      element_id: el.id,
      stable_id: el.stable_id ?? '',
      element_type: el.element_type ?? '',
      name: el.name ?? '',
      raw_quantity: raw,
      adjusted_quantity: adjusted,
    });
    totalAdjusted += adjusted;
  }

  return {
    matches,
    skips,
    matchedTypes: Array.from(matchedTypes).filter(Boolean).sort(),
    totalAdjusted,
    scanned: elements.length,
  };
}

/* ── Unit-safety ──────────────────────────────────────────────────────────── */

/** Physical dimension a quantity source produces, independent of the symbol
 *  the user typed in the unit field. */
export type Dimension = 'area' | 'volume' | 'length' | 'weight' | 'count' | 'unknown';

/** Map a quantity source spec to the dimension it yields. ``property:*`` and
 *  free-form sources are ``unknown`` — we can't infer a dimension from an
 *  arbitrary property name, so unit-safety stays silent rather than nagging. */
export function dimensionForSource(source: string): Dimension {
  const src = (source ?? '').trim().toLowerCase();
  switch (src) {
    case 'area_m2':
      return 'area';
    case 'volume_m3':
      return 'volume';
    case 'length_m':
      return 'length';
    case 'weight_kg':
      return 'weight';
    case 'count':
      return 'count';
    default:
      return 'unknown';
  }
}

/** Infer the dimension implied by a unit symbol (e.g. ``m²`` → area). Returns
 *  ``unknown`` for symbols we don't recognise so we never raise a false alarm
 *  on an exotic unit. Tolerant of common spellings: ``m2``, ``m^2``, ``sqm``. */
export function dimensionForUnit(unit: string): Dimension {
  const u = (unit ?? '').trim().toLowerCase().replace(/\s+/g, '');
  if (!u) return 'unknown';

  // Volume first — "m3" must not be caught by an area test.
  if (['m³', 'm3', 'm^3', 'cbm', 'cum', 'cubicm', 'l', 'liter', 'litre'].includes(u)) {
    return 'volume';
  }
  if (['m²', 'm2', 'm^2', 'sqm', 'sm'].includes(u)) {
    return 'area';
  }
  if (['m', 'lm', 'rm', 'meter', 'metre', 'mm', 'cm', 'km', 'ft', 'lft'].includes(u)) {
    return 'length';
  }
  if (['kg', 't', 'to', 'ton', 'tonne', 'g', 'lb', 'lbs'].includes(u)) {
    return 'weight';
  }
  if (['pcs', 'pc', 'ea', 'each', 'no', 'nr', 'stk', 'item', 'unit', 'units'].includes(u)) {
    return 'count';
  }
  return 'unknown';
}

export interface UnitSafetyResult {
  ok: boolean;
  /** True only when we could compare two known dimensions and they differ. */
  mismatch: boolean;
  sourceDimension: Dimension;
  unitDimension: Dimension;
}

/**
 * Validate that the unit symbol on a rule agrees with the dimension its
 * quantity source produces — an ``area_m2`` rule must not declare a ``m³``
 * unit. When either side is ``unknown`` we report ``ok`` (no false alarms);
 * a hard ``mismatch`` is only raised when both dimensions are known and differ.
 */
export function checkUnitSafety(source: string, unit: string): UnitSafetyResult {
  const sourceDimension = dimensionForSource(source);
  const unitDimension = dimensionForUnit(unit);
  const mismatch =
    sourceDimension !== 'unknown' &&
    unitDimension !== 'unknown' &&
    sourceDimension !== unitDimension;
  return { ok: !mismatch, mismatch, sourceDimension, unitDimension };
}

/* ── Coverage / missing-scope detector ────────────────────────────────────── */

export interface CoverageRow {
  category: string;
  elementCount: number;
  covered: boolean;
  /** Names of the rules whose element_type_filter selects this category. */
  ruleNames: string[];
}

export interface CoverageReport {
  rows: CoverageRow[];
  totalCategories: number;
  coveredCategories: number;
  /** 0..1 — share of categories that at least one active rule covers. */
  coverageRatio: number;
  /** Categories present in the model with NO matching rule (the missing scope). */
  uncovered: CoverageRow[];
}

/** A rule as the coverage detector needs to see it: just its name and the
 *  element-type filter (a comma list of wildcard patterns) plus active flag. */
export interface CoverageRule {
  name: string;
  element_type_filter: string;
  is_active: boolean;
}

/** Does a single element-type filter string select a given category label? */
export function filterCoversCategory(filter: string, category: string): boolean {
  const f = (filter ?? '').trim();
  if (!f || f === '*') return true;
  const cat = (category ?? '').trim();
  if (!cat) return false;
  const patterns = f
    .split(',')
    .map((p) => p.trim())
    .filter(Boolean);
  return patterns.some((p) => fnmatchCI(cat, p));
}

/**
 * Build a coverage report: for every distinct element_type present in the model,
 * which active rules (if any) select it. Categories with zero matching rules are
 * the "missing scope" — the trades the estimator has not yet written a rule for.
 *
 * Only active rules count toward coverage; a disabled rule does not protect a
 * category from showing up as a gap.
 */
export function buildCoverageReport(
  elements: readonly SandboxElement[],
  rules: readonly CoverageRule[],
): CoverageReport {
  const counts = new Map<string, number>();
  for (const el of elements) {
    const t = (el.element_type ?? '').trim();
    if (!t) continue;
    counts.set(t, (counts.get(t) ?? 0) + 1);
  }

  const activeRules = rules.filter((r) => r.is_active);
  const rows: CoverageRow[] = [];
  for (const [category, elementCount] of counts.entries()) {
    const ruleNames = activeRules
      .filter((r) => filterCoversCategory(r.element_type_filter, category))
      .map((r) => r.name);
    rows.push({
      category,
      elementCount,
      covered: ruleNames.length > 0,
      ruleNames,
    });
  }

  // Heaviest gaps first within the uncovered bucket, then alphabetical overall.
  rows.sort((a, b) => {
    if (a.covered !== b.covered) return a.covered ? 1 : -1;
    if (a.elementCount !== b.elementCount) return b.elementCount - a.elementCount;
    return a.category.localeCompare(b.category);
  });

  const coveredCategories = rows.filter((r) => r.covered).length;
  const totalCategories = rows.length;
  return {
    rows,
    totalCategories,
    coveredCategories,
    coverageRatio: totalCategories === 0 ? 1 : coveredCategories / totalCategories,
    uncovered: rows.filter((r) => !r.covered),
  };
}

/* ── Rule versioning (metadata-only, no migration) ────────────────────────── */

/** One captured version of a rule's formula-bearing fields, stored inside the
 *  rule's existing ``metadata.versions`` JSONB array. No new table needed. */
export interface RuleVersionSnapshot {
  /** ISO-8601 timestamp the snapshot was captured. */
  saved_at: string;
  element_type_filter: string;
  property_filter: Record<string, string>;
  quantity_source: string;
  multiplier: string;
  waste_factor_pct: string;
  unit: string;
  /** Optional human label, e.g. the rule name at capture time. */
  label?: string;
}

/** The formula-bearing fields of a rule, used to snapshot and to detect change. */
export interface RuleFormulaFields {
  element_type_filter: string;
  property_filter: Record<string, string>;
  quantity_source: string;
  multiplier: string;
  waste_factor_pct: string;
  unit: string;
}

const MAX_VERSIONS = 20;

/** Stable, order-independent signature of a rule's formula fields so we can
 *  tell whether an edit actually changed anything worth versioning. */
export function formulaSignature(f: RuleFormulaFields): string {
  const props = Object.entries(f.property_filter ?? {})
    .map(([k, v]) => `${k}=${v}`)
    .sort()
    .join('&');
  return [
    (f.element_type_filter ?? '').trim(),
    props,
    (f.quantity_source ?? '').trim(),
    (f.multiplier ?? '').trim(),
    (f.waste_factor_pct ?? '').trim(),
    (f.unit ?? '').trim(),
  ].join('|');
}

/** Read the version history out of a rule's metadata bag, defensively. */
export function readVersions(
  metadata: Record<string, unknown> | null | undefined,
): RuleVersionSnapshot[] {
  const raw = metadata?.versions;
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (v): v is RuleVersionSnapshot =>
      !!v && typeof v === 'object' && typeof (v as RuleVersionSnapshot).saved_at === 'string',
  );
}

/**
 * Append a snapshot of the *previous* formula to the version history, but only
 * when it actually differs from the most recent snapshot (and from the incoming
 * state — no point versioning a no-op save). Caps the list at the newest
 * ``MAX_VERSIONS`` so the JSONB column can't grow without bound.
 *
 * Returns the new versions array; the caller stores it under
 * ``metadata.versions``.
 */
export function pushVersion(
  existing: RuleVersionSnapshot[],
  previous: RuleFormulaFields,
  opts: { savedAt?: string; label?: string } = {},
): RuleVersionSnapshot[] {
  const prevSig = formulaSignature(previous);
  const lastSig = existing.length > 0 ? formulaSignature(existing[existing.length - 1]!) : null;
  if (prevSig === lastSig) return existing.slice(-MAX_VERSIONS);

  const snapshot: RuleVersionSnapshot = {
    saved_at: opts.savedAt ?? new Date().toISOString(),
    element_type_filter: previous.element_type_filter ?? '',
    property_filter: previous.property_filter ?? {},
    quantity_source: previous.quantity_source ?? '',
    multiplier: previous.multiplier ?? '1',
    waste_factor_pct: previous.waste_factor_pct ?? '0',
    unit: previous.unit ?? '',
    ...(opts.label ? { label: opts.label } : {}),
  };
  return [...existing, snapshot].slice(-MAX_VERSIONS);
}

/* ── BOQ draft provenance (cross-module) ──────────────────────────────────── */

/** Confidence buckets we attach to a rule-sourced BOQ position draft. The
 *  estimator confirms before anything is priced — never auto-applied. */
export type DraftConfidence = 'high' | 'medium' | 'low';

/**
 * Derive a confidence score for pushing a sandbox result into a BOQ position
 * draft. The signal is the share of matched elements that yielded a clean
 * quantity (matches vs. matches + skips). A run that selected elements but
 * dropped most of them for missing properties is low-confidence and the UI
 * should make the human look harder before confirming.
 */
export function draftConfidence(result: SandboxRunResult): {
  confidence: DraftConfidence;
  ratio: number;
} {
  const { matched, skipped } = resultCounts(result);
  const considered = matched + skipped;
  if (considered === 0) return { confidence: 'low', ratio: 0 };
  const ratio = matched / considered;
  let confidence: DraftConfidence = 'low';
  if (ratio >= 0.9) confidence = 'high';
  else if (ratio >= 0.6) confidence = 'medium';
  return { confidence, ratio };
}
