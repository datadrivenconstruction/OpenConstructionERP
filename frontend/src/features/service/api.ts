// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Service & Maintenance module.
 *
 * Backed by /api/v1/service/ — see backend/app/modules/service/router.py
 */

import { apiGet, apiPost, apiPatch, apiDelete, type Page } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type ContractStatus = 'draft' | 'active' | 'expired' | 'terminated';
export type AssetStatus = 'active' | 'decommissioned' | 'maintenance';
export type TicketStatus = 'new' | 'assigned' | 'in_progress' | 'resolved' | 'closed' | 'cancelled';
export type TicketPriority = 'low' | 'med' | 'high' | 'critical';
export type WorkOrderStatus =
  | 'scheduled'
  | 'dispatched'
  | 'in_progress'
  | 'completed'
  | 'billed'
  | 'cancelled';

export interface ServiceContract {
  id: string;
  customer_id: string;
  project_id?: string | null;
  contract_number: string;
  title: string;
  description: string;
  period_start: string;
  period_end: string;
  sla_definition_id?: string | null;
  sla_tier: string;
  status: ContractStatus;
  value: number | string;
  currency: string;
  auto_renew: boolean;
  created_by?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ServiceAsset {
  id: string;
  contract_id: string;
  asset_tag?: string | null;
  asset_type: string;
  name: string;
  location?: string | null;
  manufacturer?: string | null;
  model?: string | null;
  serial?: string | null;
  install_date?: string | null;
  warranty_until?: string | null;
  status: AssetStatus;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ServiceTicket {
  id: string;
  contract_id: string;
  asset_id?: string | null;
  ticket_number: string;
  title: string;
  description: string;
  priority: TicketPriority;
  reported_at: string;
  sla_due_at?: string | null;
  status: TicketStatus;
  reported_by?: string | null;
  assigned_to?: string | null;
  resolved_at?: string | null;
  closed_at?: string | null;
  // T10: SLA breach + recurring-schedule fields.
  sla_breach_notified_at?: string | null;
  sla_breached_at?: string | null;
  recurring_schedule_id?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface WorkOrderItem {
  id: string;
  work_order_id: string;
  item_type: 'labor' | 'material' | 'travel' | 'fee';
  description: string;
  quantity: number | string;
  unit: string;
  unit_rate: number | string;
  total: number | string;
}

export interface WorkOrder {
  id: string;
  ticket_id: string;
  work_order_number: string;
  scheduled_for?: string | null;
  technician_id?: string | null;
  status: WorkOrderStatus;
  debrief_summary: string;
  customer_signature?: string | null;
  billed_amount: number | string;
  currency: string;
  completed_at?: string | null;
  billed_at?: string | null;
  items: WorkOrderItem[];
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CreateContractPayload {
  customer_id: string;
  project_id?: string | null;
  title?: string;
  description?: string;
  period_start: string;
  period_end: string;
  sla_tier?: string;
  status?: ContractStatus;
  value?: number | string;
  currency?: string;
  auto_renew?: boolean;
}

export interface CreateAssetPayload {
  contract_id: string;
  asset_tag?: string;
  asset_type: string;
  name?: string;
  location?: string;
  manufacturer?: string;
  model?: string;
  serial?: string;
  install_date?: string;
  warranty_until?: string;
  status?: AssetStatus;
}

export interface CreateTicketPayload {
  contract_id: string;
  asset_id?: string;
  title?: string;
  description?: string;
  priority?: TicketPriority;
  reported_at?: string;
  reported_by?: string;
  assigned_to?: string;
}

export interface CreateWorkOrderPayload {
  ticket_id: string;
  scheduled_for?: string;
  technician_id?: string;
  status?: WorkOrderStatus;
  currency?: string;
}

export interface DispatchTicketPayload {
  technician_id: string;
  scheduled_for?: string;
  notes?: string;
}

/* ── Contracts ─────────────────────────────────────────────────────────── */

export function listContracts(params?: {
  customer_id?: string;
  project_id?: string;
  status?: string;
  offset?: number;
  limit?: number;
}): Promise<ServiceContract[]> {
  const qs = new URLSearchParams();
  if (params?.customer_id) qs.set('customer_id', params.customer_id);
  if (params?.project_id) qs.set('project_id', params.project_id);
  if (params?.status) qs.set('status', params.status);
  if (params?.offset !== undefined) qs.set('offset', String(params.offset));
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  const q = qs.toString();
  return apiGet<ServiceContract[]>(`/v1/service/contracts/${q ? `?${q}` : ''}`);
}

export function createContract(data: CreateContractPayload): Promise<ServiceContract> {
  return apiPost<ServiceContract>('/v1/service/contracts/', data);
}

export function updateContract(
  id: string,
  data: Partial<CreateContractPayload>,
): Promise<ServiceContract> {
  return apiPatch<ServiceContract>(`/v1/service/contracts/${id}`, data);
}

export function deleteContract(id: string): Promise<void> {
  return apiDelete(`/v1/service/contracts/${id}`);
}

export function closeContract(id: string): Promise<ServiceContract> {
  return apiPost<ServiceContract>(`/v1/service/contracts/${id}/close`, {});
}

/* ── Assets ────────────────────────────────────────────────────────────── */

export function listAssets(params: {
  contract_id: string;
  status?: string;
  offset?: number;
  limit?: number;
}): Promise<ServiceAsset[]> {
  const qs = new URLSearchParams();
  qs.set('contract_id', params.contract_id);
  if (params.status) qs.set('status', params.status);
  if (params.offset !== undefined) qs.set('offset', String(params.offset));
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  return apiGet<ServiceAsset[]>(`/v1/service/assets/?${qs.toString()}`);
}

export function createAsset(data: CreateAssetPayload): Promise<ServiceAsset> {
  return apiPost<ServiceAsset>('/v1/service/assets/', data);
}

export function updateAsset(
  id: string,
  data: Partial<CreateAssetPayload>,
): Promise<ServiceAsset> {
  return apiPatch<ServiceAsset>(`/v1/service/assets/${id}`, data);
}

export function deleteAsset(id: string): Promise<void> {
  return apiDelete(`/v1/service/assets/${id}`);
}

/* ── Tickets ───────────────────────────────────────────────────────────── */

export function listTickets(params?: {
  contract_id?: string;
  project_id?: string;
  status?: string;
  priority?: string;
  offset?: number;
  limit?: number;
}): Promise<Page<ServiceTicket>> {
  const qs = new URLSearchParams();
  if (params?.contract_id) qs.set('contract_id', params.contract_id);
  if (params?.project_id) qs.set('project_id', params.project_id);
  if (params?.status) qs.set('status', params.status);
  if (params?.priority) qs.set('priority', params.priority);
  if (params?.offset !== undefined) qs.set('offset', String(params.offset));
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  const q = qs.toString();
  /* The `?` is unconditional. check_page_envelope_consumers.py binds a URL
     literal to the call it stands next to and its pattern stops at the first
     whitespace, so the `${q ? `?${q}` : ''}` suffix this used to carry made
     the route invisible to it. A trailing `?` with an empty query is a valid
     URL and parses as no query at all. */
  return apiGet<Page<ServiceTicket>>(`/v1/service/tickets/?${q}`);
}

export function createTicket(data: CreateTicketPayload): Promise<ServiceTicket> {
  return apiPost<ServiceTicket>('/v1/service/tickets/', data);
}

export function updateTicket(
  id: string,
  data: Partial<CreateTicketPayload> & { status?: TicketStatus },
): Promise<ServiceTicket> {
  return apiPatch<ServiceTicket>(`/v1/service/tickets/${id}`, data);
}

export function deleteTicket(id: string): Promise<void> {
  return apiDelete(`/v1/service/tickets/${id}`);
}

export function dispatchTicket(
  id: string,
  payload: DispatchTicketPayload,
): Promise<ServiceTicket> {
  return apiPost<ServiceTicket>(`/v1/service/tickets/${id}/dispatch`, payload);
}

export function resolveTicket(id: string): Promise<ServiceTicket> {
  return apiPost<ServiceTicket>(`/v1/service/tickets/${id}/resolve`, {});
}

export function closeTicket(id: string): Promise<ServiceTicket> {
  return apiPost<ServiceTicket>(`/v1/service/tickets/${id}/close`, {});
}

/* ── Work Orders ───────────────────────────────────────────────────────── */

export function listWorkOrders(params?: {
  project_id?: string;
  status?: string;
  technician_id?: string;
  offset?: number;
  limit?: number;
}): Promise<Page<WorkOrder>> {
  const qs = new URLSearchParams();
  if (params?.project_id) qs.set('project_id', params.project_id);
  if (params?.status) qs.set('status', params.status);
  if (params?.technician_id) qs.set('technician_id', params.technician_id);
  if (params?.offset !== undefined) qs.set('offset', String(params.offset));
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  const q = qs.toString();
  return apiGet<Page<WorkOrder>>(`/v1/service/work-orders/?${q}`);
}

export function createWorkOrder(data: CreateWorkOrderPayload): Promise<WorkOrder> {
  return apiPost<WorkOrder>('/v1/service/work-orders/', data);
}

export function updateWorkOrder(
  id: string,
  data: { status?: WorkOrderStatus; technician_id?: string; scheduled_for?: string },
): Promise<WorkOrder> {
  return apiPatch<WorkOrder>(`/v1/service/work-orders/${id}`, data);
}

export function billWorkOrder(id: string): Promise<WorkOrder> {
  return apiPost<WorkOrder>(`/v1/service/work-orders/${id}/bill`, {});
}

export function completeWorkOrder(
  id: string,
  debrief: { problem: string; cause: string; solution: string; follow_up_required?: boolean },
): Promise<WorkOrder> {
  return apiPost<WorkOrder>(`/v1/service/work-orders/${id}/complete`, {
    debrief,
  });
}

/* ── T10: SLA breach check + recurring schedules ─────────────────────── */

export interface SLABreachCheckResponse {
  checked_at: string;
  newly_breached: number;
  total_breached: number;
  breached_ticket_ids: string[];
}

export interface RecurringSchedule {
  id: string;
  project_id?: string | null;
  contract_id?: string | null;
  name: string;
  rrule: string;
  template_ticket_data: Record<string, unknown>;
  next_run_at?: string | null;
  last_run_at?: string | null;
  enabled: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CreateRecurringSchedulePayload {
  name: string;
  rrule: string;
  project_id?: string | null;
  contract_id?: string | null;
  template_ticket_data?: Record<string, unknown>;
  next_run_at?: string | null;
  enabled?: boolean;
}

export interface UpdateRecurringSchedulePayload {
  name?: string;
  rrule?: string;
  project_id?: string | null;
  contract_id?: string | null;
  template_ticket_data?: Record<string, unknown>;
  next_run_at?: string | null;
  enabled?: boolean;
}

export interface MaterializeResponse {
  schedule_id: string;
  ticket_id?: string | null;
  ticket_number?: string | null;
  next_run_at?: string | null;
  materialized: boolean;
  reason?: string | null;
}

export function checkTicketBreaches(params?: {
  contract_id?: string;
}): Promise<SLABreachCheckResponse> {
  const qs = new URLSearchParams();
  if (params?.contract_id) qs.set('contract_id', params.contract_id);
  const q = qs.toString();
  return apiPost<SLABreachCheckResponse>(
    `/v1/service/tickets/check-breaches${q ? `?${q}` : ''}`,
    {},
  );
}

export function listRecurringSchedules(params?: {
  project_id?: string;
  enabled?: boolean;
  offset?: number;
  limit?: number;
}): Promise<RecurringSchedule[]> {
  const qs = new URLSearchParams();
  if (params?.project_id) qs.set('project_id', params.project_id);
  if (params?.enabled !== undefined) qs.set('enabled', String(params.enabled));
  if (params?.offset !== undefined) qs.set('offset', String(params.offset));
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  const q = qs.toString();
  return apiGet<RecurringSchedule[]>(
    `/v1/service/recurring-schedules/${q ? `?${q}` : ''}`,
  );
}

export function createRecurringSchedule(
  data: CreateRecurringSchedulePayload,
): Promise<RecurringSchedule> {
  return apiPost<RecurringSchedule>('/v1/service/recurring-schedules/', data);
}

export function updateRecurringSchedule(
  id: string,
  data: UpdateRecurringSchedulePayload,
): Promise<RecurringSchedule> {
  return apiPatch<RecurringSchedule>(`/v1/service/recurring-schedules/${id}`, data);
}

export function deleteRecurringSchedule(id: string): Promise<void> {
  return apiDelete(`/v1/service/recurring-schedules/${id}`);
}

export function materializeRecurringSchedule(
  id: string,
  options?: { force?: boolean },
): Promise<MaterializeResponse> {
  const qs = new URLSearchParams();
  if (options?.force) qs.set('force', 'true');
  const q = qs.toString();
  return apiPost<MaterializeResponse>(
    `/v1/service/recurring-schedules/${id}/materialize${q ? `?${q}` : ''}`,
    {},
  );
}
