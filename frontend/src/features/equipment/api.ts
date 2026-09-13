// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Equipment & Fleet module.
 *
 * Backed by /api/v1/equipment/ — see backend/app/modules/equipment/router.py
 */

import { apiGet, apiPost, apiPatch, apiDelete, type Page } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type EquipmentStatus =
  | 'active'
  | 'under_maintenance'
  | 'decommissioned'
  | 'reserved';
export type Ownership = 'owned' | 'rented' | 'leased';
export type WorkOrderStatus =
  | 'scheduled'
  | 'in_progress'
  | 'completed'
  | 'cancelled';
export type InspectionType =
  | 'annual'
  | 'quarterly'
  | 'pre_use'
  | 'monthly'
  | 'weekly';
export type InspectionResult = 'pass' | 'fail' | 'conditional';
export type DamageSeverity = 'minor' | 'major' | 'critical';
export type DamageStatus = 'reported' | 'under_repair' | 'repaired';

export interface Equipment {
  id: string;
  code: string;
  name: string;
  type_code: string;
  manufacturer?: string | null;
  model?: string | null;
  serial?: string | null;
  year?: number | null;
  ownership: Ownership;
  status: EquipmentStatus;
  location_lat?: number | null;
  location_lng?: number | null;
  hour_meter: number | string;
  odometer_km: number | string;
  last_telemetry_at?: string | null;
  purchase_date?: string | null;
  purchase_value?: number | string | null;
  depreciation_method: string;
  useful_life_years?: number | null;
  residual_value?: number | string | null;
  currency: string;
  notes?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CreateEquipmentPayload {
  code: string;
  name: string;
  type_code?: string;
  manufacturer?: string;
  model?: string;
  serial?: string;
  year?: number;
  ownership?: Ownership;
  status?: EquipmentStatus;
  location_lat?: number;
  location_lng?: number;
  hour_meter?: number;
  odometer_km?: number;
  purchase_date?: string;
  purchase_value?: number;
  useful_life_years?: number;
  residual_value?: number;
  currency?: string;
  notes?: string;
}

export interface TelemetryReading {
  id: string;
  equipment_id: string;
  recorded_at: string;
  fuel_level?: number | string | null;
  hour_meter?: number | string | null;
  odometer_km?: number | string | null;
  lat?: number | null;
  lng?: number | null;
  engine_status?: string | null;
  raw_payload: Record<string, unknown>;
}

export interface MaintenanceWorkOrder {
  id: string;
  equipment_id: string;
  schedule_id?: string | null;
  scheduled_for?: string | null;
  completed_at?: string | null;
  status: WorkOrderStatus;
  technician_id?: string | null;
  work_summary?: string | null;
  cost: number | string;
  currency: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Inspection {
  id: string;
  equipment_id: string;
  inspection_type: InspectionType;
  inspected_at: string;
  valid_until: string;
  inspector_name?: string | null;
  result: InspectionResult;
  notes?: string | null;
  certificate_url?: string | null;
  approved_by?: string | null;
}

export interface DamageReport {
  id: string;
  equipment_id: string;
  reported_at: string;
  reported_by?: string | null;
  severity: DamageSeverity;
  description: string;
  photos: string[];
  repair_cost_estimate?: number | string | null;
  currency: string;
  status: DamageStatus;
  work_order_id?: string | null;
}

export interface EquipmentType {
  id: string;
  code: string;
  name: string;
  category: string;
  default_service_interval_hours?: number | string | null;
  default_service_interval_km?: number | string | null;
  default_inspection_interval_days?: number | null;
  description?: string | null;
}

export interface CreateEquipmentTypePayload {
  code: string;
  name: string;
  category?: string;
  default_service_interval_hours?: number;
  default_service_interval_km?: number;
  default_inspection_interval_days?: number;
  description?: string;
}

export type UpdateEquipmentTypePayload = Partial<Omit<CreateEquipmentTypePayload, 'code'>>;

export interface CreateWorkOrderPayload {
  equipment_id: string;
  schedule_id?: string | null;
  scheduled_for?: string | null;
  status?: WorkOrderStatus;
  technician_id?: string | null;
  work_summary?: string | null;
  cost?: number;
  currency?: string;
}

export interface UpdateWorkOrderPayload {
  scheduled_for?: string | null;
  completed_at?: string | null;
  status?: WorkOrderStatus;
  technician_id?: string | null;
  work_summary?: string | null;
  cost?: number;
  currency?: string;
}

export interface CreateInspectionPayload {
  equipment_id: string;
  inspection_type: InspectionType;
  inspected_at: string;
  valid_until: string;
  inspector_name?: string | null;
  result?: InspectionResult;
  notes?: string | null;
  certificate_url?: string | null;
}

export interface UpdateInspectionPayload {
  inspection_type?: InspectionType;
  inspected_at?: string;
  valid_until?: string;
  inspector_name?: string | null;
  result?: InspectionResult;
  notes?: string | null;
  certificate_url?: string | null;
}

export interface CreateDamageReportPayload {
  equipment_id: string;
  reported_at: string;
  reported_by?: string | null;
  severity?: DamageSeverity;
  description?: string;
  photos?: string[];
  repair_cost_estimate?: number;
  currency?: string;
}

export interface UpdateDamageReportPayload {
  severity?: DamageSeverity;
  description?: string;
  photos?: string[];
  repair_cost_estimate?: number;
  currency?: string;
  status?: DamageStatus;
}

export interface TelemetryReadingPayload {
  recorded_at: string;
  fuel_level?: number;
  hour_meter?: number;
  odometer_km?: number;
  lat?: number;
  lng?: number;
  engine_status?: string;
  raw_payload?: Record<string, unknown>;
}

export interface EquipmentDashboard {
  equipment_id: string;
  code: string;
  name: string;
  status: EquipmentStatus;
  utilization_pct: number;
  fuel_cost_mtd: number | string;
  open_work_orders: number;
  expiring_inspections: number;
  blocked: boolean;
  last_telemetry_at?: string | null;
}

export interface EquipmentCostSummary {
  equipment_id: string;
  project_id: string | null;
  rental_cost: string;
  rental_days: number;
  fuel_cost: string;
  fuel_litres: string;
  maintenance_cost: string;
  maintenance_orders: number;
  parts_cost: string;
  total_cost: string;
  plant_hours: string;
  cost_per_hour: string | null;
}

/* ── Predictive maintenance / fleet analytics ──────────────────────────── */

export type HealthBand = 'green' | 'amber' | 'red';
export type MaintenanceTrend = 'improving' | 'stable' | 'deteriorating';

export interface HealthAnomaly {
  recorded_at: string;
  metric: string;
  value: number;
  z_score: number;
  reason: string;
}

export interface HealthAnalytics {
  equipment_id: string;
  health_score: number;
  band: HealthBand;
  anomaly_detected: boolean;
  maintenance_trend: MaintenanceTrend;
  reasons: string[];
  anomalies: HealthAnomaly[];
  sample_count: number;
}

export interface FailureForecast {
  equipment_id: string;
  predicted_failure_date?: string | null;
  failure_confidence: number;
  days_to_failure?: number | null;
  basis: string;
  daily_usage: number;
}

export interface FleetUnderutilized {
  equipment_id: string;
  code: string;
  name: string;
  utilization_pct: number;
  estimated_idle_days: number;
  estimated_monthly_saving: string;
}

export interface FleetMaintenanceBundle {
  label: string;
  equipment_ids: string[];
  codes: string[];
  unit_count: number;
}

export interface FleetOptimization {
  total_units: number;
  target_utilization_pct: number;
  window_days: number;
  underutilized_count: number;
  estimated_monthly_savings: string;
  underutilized: FleetUnderutilized[];
  maintenance_bundles: FleetMaintenanceBundle[];
}

/* ── Equipment CRUD ────────────────────────────────────────────────────── */

export function listEquipment(params?: {
  offset?: number;
  limit?: number;
  status?: string;
  type?: string;
  ownership?: string;
}): Promise<Page<Equipment>> {
  const qs = new URLSearchParams();
  if (params?.offset !== undefined) qs.set('offset', String(params.offset));
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  if (params?.status) qs.set('status', params.status);
  if (params?.type) qs.set('type', params.type);
  if (params?.ownership) qs.set('ownership', params.ownership);
  const q = qs.toString();
  /* The `?` is inside the template on purpose, rather than the usual
     `${q ? `?${q}` : ''}` suffix. That idiom puts a space inside the string
     literal, and the URL scan in scripts/check_page_envelope_consumers.py
     stops at the first whitespace, so the route becomes invisible to it and
     this endpoint could go half migrated with the gate reporting nothing. A
     trailing `?` with an empty query is a valid URL and parses as no query at
     all, and no caller here omits `limit` anyway. */
  return apiGet<Page<Equipment>>(`/v1/equipment/equipment/?${q}`);
}

export function getEquipment(id: string): Promise<Equipment> {
  return apiGet<Equipment>(`/v1/equipment/equipment/${id}`);
}

export function createEquipment(data: CreateEquipmentPayload): Promise<Equipment> {
  return apiPost<Equipment>('/v1/equipment/equipment/', data);
}

export function updateEquipment(
  id: string,
  data: Partial<CreateEquipmentPayload>,
): Promise<Equipment> {
  return apiPatch<Equipment>(`/v1/equipment/equipment/${id}`, data);
}

export function deleteEquipment(id: string): Promise<void> {
  return apiDelete(`/v1/equipment/equipment/${id}`);
}

export function getEquipmentDashboard(id: string): Promise<EquipmentDashboard> {
  return apiGet<EquipmentDashboard>(`/v1/equipment/equipment/${id}/dashboard`);
}

export function getEquipmentCostSummary(
  id: string,
  projectId?: string,
): Promise<EquipmentCostSummary> {
  const qs = projectId ? `?project_id=${projectId}` : '';
  return apiGet<EquipmentCostSummary>(
    `/v1/equipment/equipment/${id}/cost-summary${qs}`,
  );
}

export function getHealthAnalytics(id: string): Promise<HealthAnalytics> {
  return apiGet<HealthAnalytics>(
    `/v1/equipment/equipment/${id}/health-analytics`,
  );
}

export function getFailureForecast(id: string): Promise<FailureForecast> {
  return apiGet<FailureForecast>(
    `/v1/equipment/equipment/${id}/failure-forecast`,
  );
}

export function getFleetOptimization(params?: {
  target_utilization?: number;
  window_days?: number;
}): Promise<FleetOptimization> {
  const qs = new URLSearchParams();
  if (params?.target_utilization !== undefined)
    qs.set('target_utilization', String(params.target_utilization));
  if (params?.window_days !== undefined)
    qs.set('window_days', String(params.window_days));
  const q = qs.toString();
  return apiGet<FleetOptimization>(
    `/v1/equipment/dashboard/fleet/optimization${q ? `?${q}` : ''}`,
  );
}

/* ── Equipment Types ──────────────────────────────────────────────────── */

/**
 * The whole equipment-type taxonomy.
 *
 * The route takes no offset or limit and never truncates, so `total`
 * always equals `items.length` here. It is a page for shape only, so a
 * caller does not have to remember which list routes are enveloped.
 */
export function listTypes(): Promise<Page<EquipmentType>> {
  return apiGet<Page<EquipmentType>>('/v1/equipment/types/');
}

export function createType(
  data: CreateEquipmentTypePayload,
): Promise<EquipmentType> {
  return apiPost<EquipmentType>('/v1/equipment/types/', data);
}

export function updateType(
  id: string,
  data: UpdateEquipmentTypePayload,
): Promise<EquipmentType> {
  return apiPatch<EquipmentType>(`/v1/equipment/types/${id}`, data);
}

export function deleteType(id: string): Promise<void> {
  return apiDelete(`/v1/equipment/types/${id}`);
}

/* ── Telemetry ────────────────────────────────────────────────────────── */

export function listTelemetry(
  equipmentId: string,
  params?: { limit?: number },
): Promise<TelemetryReading[]> {
  const qs = new URLSearchParams();
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  const q = qs.toString();
  return apiGet<TelemetryReading[]>(
    `/v1/equipment/equipment/${equipmentId}/telemetry${q ? `?${q}` : ''}`,
  );
}

export function recordTelemetry(
  equipmentId: string,
  data: TelemetryReadingPayload,
): Promise<TelemetryReading> {
  return apiPost<TelemetryReading>(
    `/v1/equipment/equipment/${equipmentId}/telemetry`,
    data,
  );
}

/* ── Maintenance ─────────────────────────────────────────────────────── */

export function listMaintenanceWorkOrders(params?: {
  equipment_id?: string;
  status?: string;
  offset?: number;
  limit?: number;
}): Promise<Page<MaintenanceWorkOrder>> {
  const qs = new URLSearchParams();
  if (params?.equipment_id) qs.set('equipment_id', params.equipment_id);
  if (params?.status) qs.set('status', params.status);
  if (params?.offset !== undefined) qs.set('offset', String(params.offset));
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  const q = qs.toString();
  /* Unconditional `?`, for the reason spelled out on listEquipment above. */
  return apiGet<Page<MaintenanceWorkOrder>>(
    `/v1/equipment/maintenance-work-orders/?${q}`,
  );
}

export function createWorkOrder(
  data: CreateWorkOrderPayload,
): Promise<MaintenanceWorkOrder> {
  return apiPost<MaintenanceWorkOrder>(
    '/v1/equipment/maintenance-work-orders/',
    data,
  );
}

export function updateWorkOrder(
  id: string,
  data: UpdateWorkOrderPayload,
): Promise<MaintenanceWorkOrder> {
  return apiPatch<MaintenanceWorkOrder>(
    `/v1/equipment/maintenance-work-orders/${id}`,
    data,
  );
}

export function deleteWorkOrder(id: string): Promise<void> {
  return apiDelete(`/v1/equipment/maintenance-work-orders/${id}`);
}

export function completeWorkOrder(
  id: string,
  completedAt?: string,
): Promise<MaintenanceWorkOrder> {
  const qs = completedAt ? `?completed_at=${encodeURIComponent(completedAt)}` : '';
  return apiPost<MaintenanceWorkOrder>(
    `/v1/equipment/maintenance-work-orders/${id}/complete${qs}`,
    {},
  );
}

/* ── Inspections ─────────────────────────────────────────────────────── */

export function listInspections(equipmentId?: string): Promise<Inspection[]> {
  const qs = new URLSearchParams();
  if (equipmentId) qs.set('equipment_id', equipmentId);
  const q = qs.toString();
  return apiGet<Inspection[]>(`/v1/equipment/inspections/${q ? `?${q}` : ''}`);
}

export function createInspection(
  data: CreateInspectionPayload,
): Promise<Inspection> {
  return apiPost<Inspection>('/v1/equipment/inspections/', data);
}

export function updateInspection(
  id: string,
  data: UpdateInspectionPayload,
): Promise<Inspection> {
  return apiPatch<Inspection>(`/v1/equipment/inspections/${id}`, data);
}

export function deleteInspection(id: string): Promise<void> {
  return apiDelete(`/v1/equipment/inspections/${id}`);
}

/* ── Damage reports ─────────────────────────────────────────────────── */

export function listDamageReports(params?: {
  equipment_id?: string;
  status?: string;
  offset?: number;
  limit?: number;
}): Promise<DamageReport[]> {
  const qs = new URLSearchParams();
  if (params?.equipment_id) qs.set('equipment_id', params.equipment_id);
  if (params?.status) qs.set('status', params.status);
  if (params?.offset !== undefined) qs.set('offset', String(params.offset));
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  const q = qs.toString();
  return apiGet<DamageReport[]>(
    `/v1/equipment/damage-reports/${q ? `?${q}` : ''}`,
  );
}

export function createDamageReport(
  data: CreateDamageReportPayload,
): Promise<DamageReport> {
  return apiPost<DamageReport>('/v1/equipment/damage-reports/', data);
}

export function updateDamageReport(
  id: string,
  data: UpdateDamageReportPayload,
): Promise<DamageReport> {
  return apiPatch<DamageReport>(`/v1/equipment/damage-reports/${id}`, data);
}

export function deleteDamageReport(id: string): Promise<void> {
  return apiDelete(`/v1/equipment/damage-reports/${id}`);
}
