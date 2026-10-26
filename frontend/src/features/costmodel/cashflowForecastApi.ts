// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { apiGet, apiPost, downloadWithAuth } from '@/shared/lib/api';
import { documentExportUrl } from '@/shared/lib/documentExport';

/** All money values are Decimal-encoded strings; never sum them as floats. */
export interface CashFlowScenario {
  receipt_delay_days: number;
  cost_overrun_pct: string;
}

export interface CashFlowScenarioParams {
  receiptDelayDays?: number | string;
  costOverrunPct?: number | string;
  threshold?: string;
}

export interface ForecastMonth {
  period: string;
  is_past: boolean;
  planned_in: string;
  planned_out: string;
  actual_in: string;
  actual_out: string;
  expected_in: string;
  expected_out: string;
  net: string;
  cumulative: string;
  variance_in: string;
  variance_out: string;
}

export interface ForecastTotals {
  planned_in: string;
  planned_out: string;
  actual_in: string;
  actual_out: string;
  expected_in: string;
  expected_out: string;
}

export interface ForecastSource {
  source: string;
  direction: 'in' | 'out';
  amount: string;
}

export interface PeakFunding {
  amount: string;
  period: string;
}

export interface CurrencyForecast {
  currency: string;
  months: ForecastMonth[];
  totals: ForecastTotals;
  sources: ForecastSource[];
  closing_position: string;
  peak_funding: PeakFunding | null;
}

export interface ForecastFinding {
  rule_id: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
  suggestion: string;
  element_ref: string | null;
  details: Record<string, string>;
}

export interface ProjectCashFlowForecast {
  project_id: string;
  project_name: string;
  as_of: string;
  scenario: CashFlowScenario;
  threshold: string;
  has_inputs: boolean;
  currencies: CurrencyForecast[];
  findings: ForecastFinding[];
}

export interface PortfolioProjectPosition {
  project_id: string;
  project_name: string;
  closing_position: string;
  peak_funding: PeakFunding | null;
  negative: boolean;
}

export interface PortfolioCurrencyForecast {
  currency: string;
  months: ForecastMonth[];
  closing_position: string;
  peak_funding: PeakFunding | null;
  projects: PortfolioProjectPosition[];
}

export interface PortfolioCashFlowForecast {
  as_of: string;
  scenario: CashFlowScenario;
  currencies: PortfolioCurrencyForecast[];
  projects_without_forecast: { project_id: string; project_name: string }[];
  findings_count: number;
}

function query(p: CashFlowScenarioParams = {}): string {
  const qs = new URLSearchParams();
  if (p.receiptDelayDays !== undefined && p.receiptDelayDays !== '') {
    qs.set('receipt_delay_days', String(p.receiptDelayDays));
  }
  if (p.costOverrunPct !== undefined && p.costOverrunPct !== '') {
    qs.set('cost_overrun_pct', String(p.costOverrunPct));
  }
  if (p.threshold) qs.set('threshold', p.threshold);
  const s = qs.toString();
  return s ? `?${s}` : '';
}

const base = (projectId: string) => `/v1/costmodel/projects/${projectId}/5d/cashflow-forecast`;
const PORTFOLIO = '/v1/costmodel/5d/cashflow-forecast/portfolio';

export const cashflowForecastApi = {
  getProjectForecast: (projectId: string, p?: CashFlowScenarioParams) =>
    apiGet<ProjectCashFlowForecast>(`${base(projectId)}/${query(p)}`),
  getPortfolioForecast: (p?: CashFlowScenarioParams) =>
    apiGet<PortfolioCashFlowForecast>(`${PORTFOLIO}/${query(p)}`),
  evaluate: (projectId: string, p?: CashFlowScenarioParams) =>
    apiPost<{ findings: ForecastFinding[]; published: number }>(
      `${base(projectId)}/evaluate/${query(p)}`,
      {},
    ),
  exportProject: (projectId: string, p: CashFlowScenarioParams | undefined, filename: string) =>
    downloadWithAuth(
      documentExportUrl(`${base(projectId)}/export/`, exportParams(p)),
      filename,
    ),
  exportPortfolio: (p: CashFlowScenarioParams | undefined, filename: string) =>
    downloadWithAuth(documentExportUrl(`${PORTFOLIO}/export/`, exportParams(p)), filename),
};

function exportParams(p: CashFlowScenarioParams = {}): Record<string, string | undefined> {
  return {
    format: 'xlsx',
    receipt_delay_days: p.receiptDelayDays === undefined ? undefined : String(p.receiptDelayDays),
    cost_overrun_pct: p.costOverrunPct === undefined ? undefined : String(p.costOverrunPct),
  };
}
