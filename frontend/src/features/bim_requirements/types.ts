// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Types mirroring the backend `bim_requirements` Rules-as-Code endpoints
 * (`POST /api/v1/bim_requirements/preview-yaml/` and
 *  `POST /api/v1/bim_requirements/install-from-yaml/`).
 *
 * The backend ships RulePack objects loaded from YAML; the preview endpoint
 * returns the parsed pack plus optional dry-run validation results when a
 * `model_id` is supplied. Install persists the pack to the active project.
 *
 * Keep these types narrow and forgiving: server payloads evolve faster than
 * the UI ships, so unknown trailing fields must NOT break the renderer.
 */

export type RuleSeverity = 'error' | 'warning' | 'info';

export interface RulePackSelector {
  ifc_class?: string;
  properties?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

export interface RulePackAssertion {
  property?: Record<string, unknown>;
  set_vs_set?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface ParsedRule {
  id: string;
  name: string;
  severity: RuleSeverity;
  rationale?: string;
  rule_type?: string;
  selector?: RulePackSelector;
  assertion?: RulePackAssertion;
  failure_message?: string;
}

export interface RulePackAppliesTo {
  classifications?: string[];
  project_regions?: string[];
}

export interface ParsedRulePackMeta {
  id?: string;
  name?: string;
  description?: string;
  source?: string;
  version?: string;
  applies_to?: RulePackAppliesTo;
}

export interface ParsedRulePack {
  schema_version?: string;
  pack?: ParsedRulePackMeta;
  rules?: ParsedRule[];
}

/**
 * One row of the dry-run report — the outcome of a single (rule, element)
 * pair. The backend emits a FLAT list of these (one per evaluated element
 * per rule); per-rule pass/fail aggregates are computed on the client by
 * grouping on `rule_id`. See `bim_requirements/rule_runtime.py:RuleResult`.
 */
export interface DryRunElementResult {
  rule_id: string;
  element_id: string;
  passed: boolean;
  message?: string | null;
  evidence?: Record<string, unknown> | null;
}

export interface DryRunReport {
  pack_id?: string;
  total_elements?: number;
  passed?: number;
  failed?: number;
  not_applicable?: number;
  results?: DryRunElementResult[];
}

export interface PreviewYamlResponse {
  pack: ParsedRulePack;
  dry_run?: DryRunReport | null;
  errors?: string[];
}

export interface InstallYamlResponse {
  requirement_set_id: string;
  pack_id: string | null;
  rules_installed: number;
  rule_ids?: string[];
}
