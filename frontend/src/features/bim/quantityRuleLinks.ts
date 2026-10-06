// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Deep links into the Quantity Rules page (/bim/rules) and into the BIM page's
 * "link elements to this BOQ position" mode.
 *
 * Three surfaces open the rules page with context (the 3D viewer's right-click
 * menu, the BIM page header and the BOQ editor toolbar) and one opens the BIM
 * page for a position (the BOQ grid). Each side of a link is a pair of pure
 * functions here, a builder and a reader, so the parameter names live in one
 * place and both ends are tested against each other.
 */

/** Query parameters the rules page reads. `new=1` asks it to open the rule
 *  editor once, pre-filled from the remaining `NEW_RULE_PARAMS`. */
export const RULES_CONTEXT_PARAMS = ['project_id', 'model_id', 'boq_id'] as const;
export const NEW_RULE_PARAMS = ['new', 'element_type', 'prop_key', 'prop_value', 'qty_source', 'unit'] as const;

/** Server column width for `element_type_filter` (String(100)). */
const ELEMENT_TYPE_FILTER_MAX = 100;

export interface NewRulePrefill {
  /** Element type filter pattern, already made safe for fnmatch. */
  elementType: string;
  propKey: string;
  propValue: string;
  /** Raw quantity source (`area_m2`, `count`, a quantities key, `property:x`). */
  quantitySource: string;
  unit: string;
}

export interface QuantityRulesLink {
  projectId?: string | null;
  modelId?: string | null;
  boqId?: string | null;
  newRule?: Partial<NewRulePrefill> | null;
}

/**
 * Turn an element type exactly as the model names it into a filter pattern
 * that selects that type on both the server and the in-browser test.
 *
 * The server matches with Python's `fnmatch`, where `[` `]` start a character
 * class and `*` `?` are wildcards; the browser test treats `[` `]` literally
 * and splits on commas, which the server does not. A type name holding any of
 * those characters would select different elements on the two sides, so each
 * one becomes `?`, which both read as "any one character". Revit type names
 * such as `Basic Wall [300mm]` stay matched; they cannot be written exactly in
 * both dialects at once. Names longer than the column are cut and closed with
 * `*` so they still match by prefix instead of failing to save.
 */
export function elementTypeToPattern(elementType: string): string {
  const safe = elementType.trim().replace(/[[\]*?,]/g, '?');
  if (safe.length <= ELEMENT_TYPE_FILTER_MAX) return safe;
  return `${safe.slice(0, ELEMENT_TYPE_FILTER_MAX - 1)}*`;
}

const QUANTITY_GUESSES: Array<{ keys: string[]; unit: string }> = [
  { keys: ['area_m2', 'area'], unit: 'm²' },
  { keys: ['volume_m3', 'volume'], unit: 'm³' },
  { keys: ['length_m', 'length'], unit: 'm' },
];

/**
 * Pick the quantity a new rule should read for an element, from the keys that
 * element actually carries: area, then volume, then length, else a count.
 * The key is returned as the element spells it (`Area` on converter output,
 * `area_m2` on uploads) because the rule engine reads `quantities[source]`
 * verbatim. This is a starting point for the editor, which the user reviews
 * before saving.
 */
export function suggestQuantitySource(
  quantities: Record<string, unknown> | null | undefined,
): { quantitySource: string; unit: string } {
  const q = quantities ?? {};
  const keys = Object.keys(q);
  for (const guess of QUANTITY_GUESSES) {
    for (const want of guess.keys) {
      const key = keys.find((k) => k.toLowerCase() === want);
      if (!key) continue;
      const value = Number(q[key]);
      if (Number.isFinite(value) && value > 0) return { quantitySource: key, unit: guess.unit };
    }
  }
  return { quantitySource: 'count', unit: 'pcs' };
}

/** Build a same-app URL to the Quantity Rules page carrying project, model
 *  and BOQ context, and optionally a new rule to open pre-filled. */
export function buildQuantityRulesUrl(link: QuantityRulesLink = {}): string {
  const params = new URLSearchParams();
  if (link.projectId) params.set('project_id', link.projectId);
  if (link.modelId) params.set('model_id', link.modelId);
  if (link.boqId) params.set('boq_id', link.boqId);
  const rule = link.newRule;
  if (rule) {
    params.set('new', '1');
    if (rule.elementType) params.set('element_type', rule.elementType);
    if (rule.propKey) {
      params.set('prop_key', rule.propKey);
      if (rule.propValue) params.set('prop_value', rule.propValue);
    }
    if (rule.quantitySource) params.set('qty_source', rule.quantitySource);
    if (rule.unit) params.set('unit', rule.unit);
  }
  const qs = params.toString();
  return qs ? `/bim/rules?${qs}` : '/bim/rules';
}

export interface QuantityRulesContext {
  projectId: string;
  modelId: string;
  boqId: string;
  /** Present only when the URL asked for a new rule (`new=1`). */
  newRule: NewRulePrefill | null;
}

/** Read what `buildQuantityRulesUrl` wrote. Missing values come back empty. */
export function readQuantityRulesContext(params: URLSearchParams): QuantityRulesContext {
  const get = (k: string) => (params.get(k) ?? '').trim();
  const newRule =
    get('new') === '1'
      ? {
          elementType: get('element_type'),
          propKey: get('prop_key'),
          propValue: params.get('prop_value') ?? '',
          quantitySource: get('qty_source'),
          unit: get('unit'),
        }
      : null;
  return { projectId: get('project_id'), modelId: get('model_id'), boqId: get('boq_id'), newRule };
}

/** The rules page's three tabs, each on its own module's data: the quantity
 *  rules are BIM Hub, the requirements oe_requirements, and the Rule Library
 *  installs through oe_bim_requirements. */
export type RulesTab = 'quantity_rules' | 'requirements' | 'rule_library';

/** Which of the two optional tabs have their module switched on. */
export interface RulesTabsAvailable {
  requirements: boolean;
  ruleLibrary: boolean;
}

/**
 * The tab the rules page shows, read from its URL. `mode=requirements` is the
 * compliance link: it hides the quantity tab and starts on the requirements
 * (or on the Rule Library when only that is on). `tab=` is the tab picked on
 * the page, written there so the top bar (which only sees the URL) names the
 * same half as the crumb and the tab bar. A tab whose module is off is never
 * the answer; the quantity rules always exist.
 */
export function rulesTabFromParams(params: URLSearchParams, available: RulesTabsAvailable): RulesTab {
  const tab = params.get('tab');
  if (tab === 'requirements' && available.requirements) return tab;
  if (tab === 'rule_library' && available.ruleLibrary) return tab;
  if (params.get('mode') === 'requirements') {
    if (available.requirements) return 'requirements';
    if (available.ruleLibrary) return 'rule_library';
  }
  return 'quantity_rules';
}

/* ── BOQ position -> BIM page "link elements" mode ───────────────────────── */

export const LINK_TARGET_PARAMS = ['link_position', 'link_boq', 'link_label'] as const;

export interface LinkFromModelTarget {
  positionId: string;
  boqId: string;
  /** Ordinal and description of the position, display only. */
  label: string;
}

/** URL of the BIM page opened to pick elements for one BOQ position. The model
 *  id goes in the path, so the page does not rewrite the URL (and drop the
 *  query) on its way to the model. */
export function buildLinkFromModelUrl(opts: {
  projectId: string;
  modelId: string;
  boqId: string;
  positionId: string;
  label?: string;
}): string {
  const params = new URLSearchParams({ link_position: opts.positionId, link_boq: opts.boqId });
  if (opts.label) params.set('link_label', opts.label.slice(0, 120));
  return `/projects/${encodeURIComponent(opts.projectId)}/bim/${encodeURIComponent(opts.modelId)}?${params.toString()}`;
}

/** Read the link target back, or null when the URL carries none. */
export function readLinkFromModelTarget(params: URLSearchParams): LinkFromModelTarget | null {
  const positionId = (params.get('link_position') ?? '').trim();
  const boqId = (params.get('link_boq') ?? '').trim();
  if (!positionId || !boqId) return null;
  return { positionId, boqId, label: (params.get('link_label') ?? '').trim() };
}
