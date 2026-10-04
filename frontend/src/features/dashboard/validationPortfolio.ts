// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Cross-project validation status - API types, fetch and link helpers for
 * the dashboard's "Validation across projects" card.
 *
 * The backend (`GET /v1/validation/portfolio-status/`) already sorts projects
 * and their estimates worst first and maps every "nothing was checked" case to
 * `not_validated`, so this module never re-ranks or re-derives a state. It only
 * builds the deep links, which must land on the exact report the card shows.
 */

import { apiGet } from '@/shared/lib/api';

export type PortfolioState = 'errors' | 'warnings' | 'not_validated' | 'info' | 'passed';

export interface PortfolioEstimate {
  boq_id: string;
  boq_name: string;
  state: PortfolioState;
  report_id: string | null;
  report_status: string | null;
  rule_sets: string[];
  unsupported_rule_sets: string[];
  error_count: number;
  warning_count: number;
  passed_count: number;
  total_rules: number;
  score: number | null;
  validated_at: string | null;
}

export interface PortfolioProject {
  project_id: string;
  project_name: string;
  state: PortfolioState;
  estimate_count: number;
  validated_count: number;
  not_validated_count: number;
  error_count: number;
  warning_count: number;
  passed_count: number;
  rule_sets: string[];
  last_validated_at: string | null;
  estimates: PortfolioEstimate[];
}

export interface PortfolioSummary {
  errors: number;
  warnings: number;
  not_validated: number;
  info: number;
  passed: number;
}

export interface ValidationPortfolio {
  project_count: number;
  summary: PortfolioSummary;
  projects: PortfolioProject[];
}

/**
 * Query key. It sits under `['validation']` on purpose: a run on the
 * validation page, an estimate audit and the Validate button in the BOQ
 * editor all invalidate that root, so the card refreshes as soon as someone
 * re-validates an estimate.
 */
export const VALIDATION_PORTFOLIO_QUERY_KEY = ['validation', 'portfolio-status'] as const;

export function fetchValidationPortfolio(): Promise<ValidationPortfolio> {
  return apiGet<ValidationPortfolio>('/v1/validation/portfolio-status/');
}

/**
 * Where a click on an estimate row lands.
 *
 * With a report, the link names it (`report=`): without it the validation page
 * looks for the estimate's newest report among the project's 50 most recent,
 * and on a busy project the card could say "errors" while the page opened
 * empty. Without a report the page opens on that estimate, ready to run.
 */
export function estimateValidationHref(projectId: string, estimate: PortfolioEstimate): string {
  const params = new URLSearchParams({ project: projectId, boq_id: estimate.boq_id });
  if (estimate.report_id) params.set('report', estimate.report_id);
  return `/validation?${params.toString()}`;
}

/** A project with no estimates has nothing to validate yet: send the reader to its bill register. */
export function projectEstimatesHref(projectId: string): string {
  return `/projects/${encodeURIComponent(projectId)}/boq`;
}

/**
 * True when the latest report exists but checked nothing (pending, skipped,
 * unsupported rule sets, or zero rules), so the row can say why it reads
 * "not validated" despite having a run on record.
 */
export function ranButCheckedNothing(estimate: PortfolioEstimate): boolean {
  return estimate.state === 'not_validated' && estimate.report_id !== null;
}
