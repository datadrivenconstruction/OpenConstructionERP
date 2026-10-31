// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the dispatch board (/v1/dispatch).
 * Cards point at resources people, equipment units, equipment rentals and dispatch crews.
 */
import { API_BASE, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';

const BASE = '/v1/dispatch';

export type CardKind = 'crew' | 'worker' | 'equipment' | 'rental';
export type LocationKind = 'project' | 'yard' | 'shop' | 'rental_return';
export type CardStatus = '' | 'available' | 'assigned' | 'maintenance' | 'in_transit' | 'absent';
export type ConflictKind =
  | 'double_booked'
  | 'missing_certificate'
  | 'maintenance_overdue'
  | 'maintenance_block'
  | 'worker_absent'
  | 'crew_under_minimum';

export interface DispatchLocation {
  id: string;
  name: string;
  kind: LocationKind;
  project_id: string | null;
  sort_order: number;
  is_active: boolean;
}

export interface CrewMemberView {
  id: string;
  name: string;
  absent: string;
}

export interface Placement {
  id: string;
  day: string;
  card_kind: CardKind;
  card_ref: string;
  location_id: string;
  operator_ref: string | null;
  start_time: string;
  notes: string;
  source: 'manual' | 'scheduled' | 'copied';
  label: string;
  subtitle: string;
  status: CardStatus;
  members: CrewMemberView[];
  conflict_kinds: ConflictKind[];
}

export interface Conflict {
  kind: ConflictKind;
  card_kind: string;
  card_ref: string;
  message: string;
  severity: 'error' | 'warning';
  placement_ids: string[];
  details: Record<string, unknown>;
}

export interface ScheduledMove {
  id: string;
  card_kind: CardKind;
  card_ref: string;
  to_location_id: string;
  effective_date: string;
  start_time: string;
  notes: string;
  status: 'pending' | 'applied' | 'cancelled';
  applied_at: string | null;
}

export interface Board {
  day: string;
  locations: DispatchLocation[];
  placements: Placement[];
  conflicts: Conflict[];
  pending_moves: ScheduledMove[];
  applied_moves: number;
}

export interface WeekBoard {
  start: string;
  locations: DispatchLocation[];
  days: { day: string; placements: Placement[]; conflict_count: number }[];
}

export interface CardItem {
  card_kind: CardKind;
  card_ref: string;
  label: string;
  subtitle: string;
  status: string;
}

export interface CardPage {
  items: CardItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface PlanLine {
  location: string;
  location_id: string;
  card_kind: CardKind;
  who_or_what: string;
  operator: string;
  start_time: string;
  notes: string;
}

export interface DailyPlan {
  day: string;
  plans: { foreman: string; foreman_user_id: string | null; lines: PlanLine[] }[];
}

export interface UtilisationRow {
  unit_ref: string;
  card_kind: CardKind;
  label: string;
  days_assigned: number;
  days_idle: number;
  working_days: number;
  percent: number;
  assigned_days: string[];
}

export interface ViewPref {
  card_density: 'compact' | 'detailed';
  settings: Record<string, unknown>;
}

export const fetchBoard = (day: string) => apiGet<Board>(`${BASE}/board?day=${day}`);
export const fetchWeek = (start: string) => apiGet<WeekBoard>(`${BASE}/week?start=${start}`);
export const fetchCards = (kind: CardKind, q: string, offset = 0) =>
  apiGet<CardPage>(`${BASE}/cards?kind=${kind}&q=${encodeURIComponent(q)}&limit=50&offset=${offset}`);
export const fetchPlan = (day: string) => apiGet<DailyPlan>(`${BASE}/plan?day=${day}`);
export const fetchUtilisation = (start: string, end: string) =>
  apiGet<{ start: string; end: string; items: UtilisationRow[] }>(`${BASE}/utilisation?start=${start}&end=${end}`);
export const fetchPref = () => apiGet<ViewPref>(`${BASE}/preferences`);
export const savePref = (pref: ViewPref) => apiPut<ViewPref, ViewPref>(`${BASE}/preferences`, pref);

export const createLocation = (body: { name: string; kind: LocationKind; project_id?: string | null }) =>
  apiPost<DispatchLocation>(`${BASE}/locations`, body);
export const createCrew = (body: { name: string; member_ids: string[]; min_size: number; trade?: string }) =>
  apiPost<{ id: string }>(`${BASE}/crews`, body);

export const placeCards = (body: {
  day: string;
  location_id: string;
  cards: { card_kind: CardKind; card_ref: string }[];
  start_time?: string;
}) => apiPost<{ created: number }>(`${BASE}/placements`, body);
export const moveCards = (placement_ids: string[], to_location_id: string) =>
  apiPost<{ moved: number }>(`${BASE}/placements/move`, { placement_ids, to_location_id });
export const updatePlacement = (id: string, body: { start_time?: string; notes?: string; operator_ref?: string | null }) =>
  apiPatch<unknown>(`${BASE}/placements/${id}`, body);
export const removeCards = (placement_ids: string[]) =>
  apiPost<{ removed: number }>(`${BASE}/placements/remove`, { placement_ids });
export const copyDay = (from_day: string, to_day: string, replace = false) =>
  apiPost<{ copied: number }>(`${BASE}/copy-day`, { from_day, to_day, replace });
export const scheduleMove = (body: {
  card_kind: CardKind;
  card_ref: string;
  to_location_id: string;
  effective_date: string;
  start_time?: string;
}) => apiPost<ScheduledMove>(`${BASE}/moves`, body);
export const cancelMove = (id: string) => apiPost<ScheduledMove>(`${BASE}/moves/${id}/cancel`, {});
export const sharePlan = (day: string) =>
  apiPost<{ notified: number; without_user: string[] }>(`${BASE}/plan/share?day=${day}`, {});
export const downloadPlanPdf = (day: string) =>
  downloadWithAuth(`${API_BASE}${BASE}/plan/pdf?day=${day}`, `daily-plan-${day}.pdf`);
export const prefillTimesheet = (location_id: string, day: string) =>
  apiPost<{ timesheet_id: string; reference: string; created: boolean; lines_added: number }>(
    `${BASE}/timesheet-prefill`,
    { location_id, day },
  );
