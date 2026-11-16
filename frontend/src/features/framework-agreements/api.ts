// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Framework agreements API (mounted at /api/v1/framework-agreements/).
 * Money and factors travel as decimal strings; the UI formats, never recomputes.
 */

import { apiDelete, apiGet, apiPost, apiPut, apiPatch } from '@/shared/lib/api';

const BASE = '/v1/framework-agreements';

export type Money = string;

export interface Finding {
  rule_id: string;
  code: string;
  severity: 'error' | 'warning' | 'info' | string;
  message: string;
  suggestion?: string | null;
  element_ref?: string | null;
}

export interface Consumption {
  cap: Money | null;
  min_value: Money | null;
  committed: Money;
  certified: Money;
  invoiced: Money;
  tested: Money;
  headroom: Money | null;
  pct: Money | null;
  threshold_pct: Money;
  cap_basis: 'committed' | 'certified' | 'invoiced';
  term_elapsed_pct: Money | null;
  orders: number;
}

export interface AgreementSummary {
  id: string;
  project_id: string;
  code: string;
  title: string;
  client_name: string;
  status: 'draft' | 'signed' | 'active' | 'exhausted' | 'expired' | 'closed' | string;
  currency: string;
  start_date: string | null;
  end_date: string | null;
  consumption: Consumption;
  orders_this_month: number;
}

export interface PackProfile {
  markets: string[];
  term_variant: 'neutral' | 'de' | 'uk' | 'us' | string;
  term_limit: { years: number; source: string } | null;
  pack_fields: string[];
  condition_tags: string[];
  escalation_templates: { code: string; label: string; method: string; verified?: boolean }[];
  notes: string[];
  measurement_preset?: string | null;
  min_value_required?: string | null;
  currency?: string;
}

export interface RatePeriod {
  id: string;
  label: string;
  effective_from: string;
  effective_to: string | null;
  method: string;
  template_code: string | null;
  base_period: string | null;
  fixed_price_until: string | null;
  fixed_part: Money | null;
  fixed_factor: Money | null;
  series_refs: { series: string; weight?: string }[];
  rate_overrides: Record<string, string>;
  status: string;
  factor_today: Money | null;
  factor_error: string | null;
}

export interface AgreementDetail extends AgreementSummary {
  terms: Record<string, unknown> & {
    cap_overrides?: { order_no: string; reason: string; overrun: string; at: string; user_id?: string }[];
    pack_values?: Record<string, unknown>;
    override_policy?: 'block' | 'warn';
    rounding?: 'per_rate' | 'per_total';
  };
  pack: PackProfile;
  findings: Finding[];
  current_period: RatePeriod | null;
}

export interface RateItem {
  id: string;
  code: string;
  description: string;
  unit: string;
  base_rate: Money;
  effective_rate: Money | null;
  max_qty: Money | null;
  estimated_qty: Money | null;
  ordered_qty: Money;
  surcharge_flags: string[];
  is_active: boolean;
  cited: boolean;
  source: string;
}

export interface Adjustment {
  id: string;
  code: string;
  label: string;
  kind: 'multiplier' | 'add_per_unit' | 'lump_sum' | string;
  value: Money;
  scope: string;
  condition: string;
}

export interface PricedLine {
  item_id: string | null;
  code: string;
  description: string;
  unit: string;
  quantity: Money;
  unit_rate: Money;
  total: Money;
  rate_build: Record<string, unknown>;
}

export interface CapCheck {
  cap?: Money;
  prior?: Money;
  order?: Money;
  total_after?: Money;
  headroom_before?: Money;
  headroom_after?: Money;
  pct_after?: Money;
  exceeded?: boolean;
  threshold_reached?: boolean;
}

export interface OrderQuote {
  lines: PricedLine[];
  net: Money;
  factor: Money | null;
  period_label: string | null;
  rounding: string;
  cap: CapCheck;
  findings: Finding[];
  blocking: boolean;
  over_cap: boolean;
  per_rate_net: Money | null;
  per_total_net: Money | null;
}

export interface OrderLineIn {
  item_id?: string;
  code?: string;
  quantity: string;
}

export interface QuoteRequest {
  ordered_at: string;
  tags: string[];
  lines: OrderLineIn[];
  exclude_order_id?: string;
}

export interface OrderCreate extends QuoteRequest {
  site_label: string;
  own_site_project?: boolean;
  issue?: boolean;
  override_reason?: string;
}

export interface OrderSummary {
  id: string;
  code: string;
  order_no: string;
  site_label: string;
  project_id: string;
  ordered_at: string | null;
  tags: string[];
  order_status: 'draft' | 'issued' | 'in_progress' | 'measured' | 'claimed' | 'closed' | 'cancelled' | string;
  line_count: number;
  net: Money;
  extras: Money;
  measured_pct: Money | null;
  claimed: Money;
  has_extras: boolean;
  measured_over_ordered: boolean;
}

export interface OrderLine {
  id: string;
  code: string;
  description: string;
  unit: string | null;
  quantity: Money;
  unit_rate: Money;
  total_value: Money;
  origin: string;
  measured_qty: Money | null;
  rate_build: Record<string, unknown>;
}

export interface OrderDetail extends OrderSummary {
  lines: OrderLine[];
  terms: Record<string, unknown> & { cap_override?: { reason: string; overrun: string } };
  findings: Finding[];
}

export interface BreakdownRow {
  key: string;
  label: string;
  orders: number;
  committed: Money;
  certified: Money;
  quantity: Money | null;
  max_qty: Money | null;
}

export interface Extra {
  id: string;
  code: string;
  title: string;
  status: string;
  amount: Money;
}

export interface CreateAgreementBody {
  project_id: string;
  title: string;
  client_name: string;
  start_date: string;
  end_date: string;
  currency?: string;
  cap_value?: string | null;
  min_value?: string | null;
  threshold_pct?: string;
  rounding?: 'per_rate' | 'per_total';
  override_policy?: 'block' | 'warn';
  client_kind?: 'classic' | 'sector';
  pack_values?: Record<string, unknown>;
  items: { code: string; description: string; unit: string; base_rate: string; max_qty?: string | null; estimated_qty?: string | null }[];
}

export const fwkApi = {
  list: (projectId?: string) =>
    apiGet<{ items: AgreementSummary[]; total: number }>(`${BASE}/${projectId ? `?project_id=${projectId}` : ''}`),
  packProfile: (projectId: string, clientKind = 'classic') =>
    apiGet<PackProfile>(`${BASE}/pack-profile?project_id=${projectId}&client_kind=${clientKind}`),
  create: (body: CreateAgreementBody) => apiPost<AgreementDetail, CreateAgreementBody>(`${BASE}/`, body),
  get: (id: string) => apiGet<AgreementDetail>(`${BASE}/${id}`),
  setStatus: (id: string, status: 'active' | 'closed') =>
    apiPost<AgreementDetail>(`${BASE}/${id}/status`, { status }),
  items: (id: string) => apiGet<RateItem[]>(`${BASE}/${id}/items`),
  updateItem: (id: string, itemId: string, body: Partial<Pick<RateItem, 'base_rate' | 'is_active' | 'max_qty'>>) =>
    apiPatch<Record<string, string | null>>(`${BASE}/${id}/items/${itemId}`, body),
  periods: (id: string) => apiGet<RatePeriod[]>(`${BASE}/${id}/periods`),
  activatePeriod: (id: string, period: RatePeriod) =>
    apiPut<RatePeriod>(`${BASE}/${id}/periods/${period.id}?activate=true`, {
      label: period.label,
      effective_from: period.effective_from,
      effective_to: period.effective_to,
      method: period.method,
      template_code: period.template_code,
      base_period: period.base_period,
      fixed_price_until: period.fixed_price_until,
      fixed_part: period.fixed_part,
      fixed_factor: period.fixed_factor,
      series_refs: period.series_refs,
      rate_overrides: period.rate_overrides,
    }),
  adjustments: (id: string) => apiGet<Adjustment[]>(`${BASE}/${id}/adjustments`),
  addAdjustment: (id: string, body: Omit<Adjustment, 'id'>) => apiPost<Adjustment>(`${BASE}/${id}/adjustments`, body),
  deleteAdjustment: (id: string, adjId: string) => apiDelete(`${BASE}/${id}/adjustments/${adjId}`),
  quote: (id: string, body: QuoteRequest) => apiPost<OrderQuote, QuoteRequest>(`${BASE}/${id}/quote`, body),
  orders: (id: string) => apiGet<{ items: OrderSummary[]; total: number }>(`${BASE}/${id}/orders`),
  createOrder: (id: string, body: OrderCreate) => apiPost<OrderDetail, OrderCreate>(`${BASE}/${id}/orders`, body),
  order: (orderId: string) => apiGet<OrderDetail>(`${BASE}/orders/${orderId}`),
  issueOrder: (orderId: string, overrideReason?: string) =>
    apiPost<OrderDetail>(`${BASE}/orders/${orderId}/issue`, { override_reason: overrideReason || null }),
  setOrderStatus: (orderId: string, status: 'in_progress' | 'closed' | 'cancelled') =>
    apiPost<OrderDetail>(`${BASE}/orders/${orderId}/status`, { status }),
  measure: (orderId: string, measurements: Record<string, string>) =>
    apiPost<OrderDetail>(`${BASE}/orders/${orderId}/measurements`, { measurements }),
  extras: (orderId: string) => apiGet<Extra[]>(`${BASE}/orders/${orderId}/extras`),
  raiseExtra: (orderId: string, body: { title: string; description?: string; amount: string }) =>
    apiPost<{ id: string; code: string; status: string }>(`${BASE}/orders/${orderId}/extras`, body),
  breakdown: (id: string, by: 'site' | 'item' | 'month') =>
    apiGet<{ by: string; rows: BreakdownRow[] }>(`${BASE}/${id}/breakdown?by=${by}`),
};

export const fwkKeys = {
  all: ['framework-agreements'] as const,
  list: (projectId?: string) => ['framework-agreements', 'list', projectId ?? ''] as const,
  detail: (id: string) => ['framework-agreements', 'detail', id] as const,
  orders: (id: string) => ['framework-agreements', 'orders', id] as const,
  order: (orderId: string) => ['framework-agreements', 'order', orderId] as const,
};
