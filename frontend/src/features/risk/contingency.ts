// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Risk-based contingency: the register's expected monetary value against the
 * contingency lines of the finance budget.
 *
 * Endpoints (mounted at /api/v1/risk):
 *   GET    /v1/risk/projects/{pid}/contingency
 *   POST   /v1/risk/projects/{pid}/contingency/drawdowns/{risk_id}
 *   DELETE /v1/risk/projects/{pid}/contingency/drawdowns/{risk_id}
 *
 * Every money field is a Decimal serialised as a JSON string. Keep the types
 * honest (`MoneyWire`) and go through `money()` before arithmetic, so a
 * string never gets concatenated where a sum was meant.
 */

import { apiDelete, apiGet, apiPost } from '@/shared/lib/api';
import { normalizeRole, ROLE_RANK } from '@/shared/lib/roles';

/** A Decimal on the wire: a string from the server, a number in fixtures. */
export type MoneyWire = string | number;

export type ContingencyState = 'no_allocation' | 'covered' | 'shortfall' | 'overdrawn';

export interface ContingencyLine {
  budget_id: string;
  wbs_id: string | null;
  currency: string;
  allocated: MoneyWire;
  drawn: MoneyWire;
  remaining: MoneyWire;
  /** False when the line's currency has no rate to the project currency. */
  converted: boolean;
}

export interface ContingencyDrawdown {
  risk_id: string | null;
  risk_code: string;
  risk_title: string;
  budget_id: string;
  amount: MoneyWire;
  currency: string;
  confirmed_by: string | null;
  confirmed_at: string | null;
  note: string;
}

export interface ContingencyPending {
  risk_id: string;
  risk_code: string;
  risk_title: string;
  impact_cost: MoneyWire;
  currency: string;
  proposed_amount: MoneyWire | null;
  proposed_currency: string;
  proposed_budget_id: string | null;
}

export interface ContingencyPosition {
  currency: string;
  emv: MoneyWire;
  p50: MoneyWire;
  p80: MoneyWire;
  percentile_method: 'exact' | 'normal_approximation';
  emv_by_currency: Record<string, MoneyWire>;
  allocated: MoneyWire;
  drawn: MoneyWire;
  remaining: MoneyWire;
  coverage_gap: MoneyWire;
  state: ContingencyState;
  active_risk_count: number;
  excluded_closed_count: number;
  excluded_drawn_count: number;
  unconverted_emv: Record<string, MoneyWire>;
  missing_fx_rates: string[];
  lines: ContingencyLine[];
  drawdowns: ContingencyDrawdown[];
  pending: ContingencyPending[];
}

export interface DrawdownBody {
  amount: string;
  budget_id?: string | null;
  note?: string;
}

/** React Query key of a project's contingency position. */
export function contingencyQueryKey(projectId: string): readonly [string, string] {
  return ['risk-contingency', projectId] as const;
}

export function fetchContingency(projectId: string): Promise<ContingencyPosition> {
  return apiGet<ContingencyPosition>(`/v1/risk/projects/${projectId}/contingency`);
}

export function confirmDrawdown(projectId: string, riskId: string, body: DrawdownBody): Promise<ContingencyPosition> {
  return apiPost<ContingencyPosition, DrawdownBody>(
    `/v1/risk/projects/${projectId}/contingency/drawdowns/${riskId}`,
    body,
  );
}

export function reverseDrawdown(projectId: string, riskId: string): Promise<ContingencyPosition> {
  return apiDelete<ContingencyPosition>(`/v1/risk/projects/${projectId}/contingency/drawdowns/${riskId}`);
}

/** A wire money value as a finite number (0 for anything unparseable). */
export function money(value: MoneyWire | null | undefined): number {
  const n = typeof value === 'number' ? value : Number(value ?? 0);
  return Number.isFinite(n) ? n : 0;
}

/**
 * Parse what a person typed into the amount field.
 *
 * Accepts a dot or a comma as the decimal separator and spaces or
 * apostrophes as grouping ("12 500,50", "12'500.50"). Returns the canonical
 * decimal string the API takes, or null when the input is not a positive
 * amount. With both separators present, the last one is the decimal.
 */
export function parseAmountInput(raw: string): string | null {
  // JS `\s` already covers the no-break and narrow no-break spaces that
  // Intl number formatting puts between thousands.
  let s = raw.trim().replace(/[\s']/g, '');
  if (!s) return null;
  const lastComma = s.lastIndexOf(',');
  const lastDot = s.lastIndexOf('.');
  if (lastComma >= 0 && lastDot >= 0) {
    s = lastComma > lastDot ? s.replace(/\./g, '').replace(',', '.') : s.replace(/,/g, '');
  } else if (lastComma >= 0) {
    s = s.replace(',', '.');
  }
  if (!/^\d+(\.\d+)?$/.test(s)) return null;
  const n = Number(s);
  if (!Number.isFinite(n) || n <= 0) return null;
  return s;
}

/** Only managers confirm or reverse a drawdown (backend `risk.contingency`). */
export function canDrawContingency(role: string | null | undefined): boolean {
  const canonical = normalizeRole(role);
  const rank = (ROLE_RANK as Record<string, number>)[canonical];
  return rank !== undefined && rank >= ROLE_RANK.manager;
}

/** The metadata key prefix finance uses for a confirmed drawdown. */
export const CONTINGENCY_DRAWDOWN_PREFIX = 'contingency_drawdown:';

/** True when a finance budget category is the contingency one (either spelling). */
export function isContingencyCategory(category: string | null | undefined): boolean {
  return (category ?? '').trim().toLowerCase() === 'contingency';
}

/**
 * What a finance budget line has drawn for risks, read from its metadata.
 *
 * Amounts are in the line's currency. A record without a positive amount is
 * skipped rather than counted as zero, mirroring the backend parser.
 */
export function drawnOnBudgetLine(metadata: Record<string, unknown> | null | undefined): {
  total: number;
  count: number;
} {
  let total = 0;
  let count = 0;
  if (!metadata || typeof metadata !== 'object') return { total, count };
  for (const [key, raw] of Object.entries(metadata)) {
    if (!key.startsWith(CONTINGENCY_DRAWDOWN_PREFIX)) continue;
    const amount =
      raw && typeof raw === 'object'
        ? money((raw as Record<string, unknown>).amount as MoneyWire | undefined)
        : money(raw as MoneyWire | undefined);
    if (amount > 0) {
      total += amount;
      count += 1;
    }
  }
  return { total, count };
}

/** Line remaining after drawdowns, in the dialog's terms (null without a line). */
export function lineRemaining(lines: ContingencyLine[], budgetId: string | null | undefined): number | null {
  const line = lines.find((l) => l.budget_id === budgetId);
  return line ? money(line.remaining) : null;
}
