// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Wire types for the value-realized API. Money and rates arrive as strings (the
// Decimal rendered losslessly), so they are passed straight to MoneyDisplay and
// never coerced with toFixed. Confidence is one of high / medium / low / none.

export type Confidence = 'high' | 'medium' | 'low' | 'none';

export interface CurrencyValue {
  currency: string;
  overrun_exposure_managed: string;
  chargeable_total: string;
  recovered_total: string;
  absorbed_total: string;
  recovery_rate: string | null;
  schedule_days_managed: string;
  impact_count: number;
  recovery_item_count: number;
}

export interface ValueSummary {
  project_id: string | null;
  by_currency: CurrencyValue[];
  primary_currency: string;
  estimated_hours_saved: string;
  dispute_risk_reduction: string | null;
  exposure_confidence: Confidence;
  recovery_confidence: Confidence;
  hours_confidence: Confidence;
  risk_confidence: Confidence;
  cost_position_percentile: number | null;
  impact_count: number;
  recovery_item_count: number;
  hours_sample: number;
  activity_count: number;
}

export interface HoursSavedBucket {
  key: string;
  event_count: number;
  unit_count: number;
  minutes: string;
  hours: string;
}

export interface HoursSaved {
  project_id: string;
  by: string;
  total_hours: string;
  event_count: number;
  buckets: HoursSavedBucket[];
}

export interface ProjectScore {
  project_id: string;
  adoption: number;
  cohort: 'high' | 'low';
}

export interface CohortComparison {
  metric: string;
  high_mean: number | null;
  low_mean: number | null;
  delta: number | null;
  high_n: number;
  low_n: number;
  higher_is_better: boolean;
  favours_high: boolean | null;
  confidence: Confidence;
}

export interface AdoptionBenchmark {
  project_scores: ProjectScore[];
  comparisons: CohortComparison[];
  confidence: Confidence;
  high_count: number;
  low_count: number;
}

export interface AdoptionStep {
  key: string;
  label: string;
  module: string;
  done: boolean;
}

export interface AdoptionChecklist {
  project_id: string;
  role: string;
  adoption_score: number;
  steps: AdoptionStep[];
  next_actions: AdoptionStep[];
}

// One regional-benchmark metric over the tenant's own projects (POST
// /v1/costs/benchmark/). The five points and the positioned value are decimal
// strings: for cost_per_m2 they are money; for overrun_pct / recovery_rate they
// are dimensionless fractions (e.g. "0.2" = 20 percent) and currency is empty.
export type RegionalMetric = 'cost_per_m2' | 'overrun_pct' | 'recovery_rate';

export interface RegionalPortfolio {
  project_count: number;
  min: string;
  p25: string;
  median: string;
  p75: string;
  max: string;
  confidence: 'high' | 'medium' | 'low';
  note: string;
}

export interface RegionalBenchmark {
  currency: string;
  metric: RegionalMetric;
  own_portfolio: RegionalPortfolio | null;
  percentile_vs_own: number | null;
  explanation: string;
}

// One editable hours-saved minute factor (admin only). `minutes` and
// `default_minutes` are minutes of saved effort carried as strings (lossless
// Decimal), never money. `is_override` is true when the tenant has tuned the
// pair away from the seed default.
export interface TimeFactor {
  module: string;
  action: string;
  minutes: string;
  default_minutes: string | null;
  is_override: boolean;
}

export interface TimeFactors {
  factors: TimeFactor[];
}

export interface TimeFactorUpdate {
  module: string;
  action: string;
  minutes: string;
}
