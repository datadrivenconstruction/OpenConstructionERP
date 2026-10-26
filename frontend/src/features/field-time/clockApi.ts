// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API client and React Query hooks for the geofenced time clock, mounted at​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
 * /api/v1/field-time/ (geofences/ and clock/). Hours are decimal strings.
 * Every path keeps its trailing slash (redirect_slashes is disabled).
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from '@/shared/lib/api';
import type { FieldTimesheet, FieldTimeValidationReport } from './api';
import type { LatLng } from './geometry';

/* -- Types ---------------------------------------------------------------- */

export interface Geofence {
  id: string;
  project_id: string;
  name: string;
  shape: 'circle' | 'polygon';
  center_lat: number | null;
  center_lng: number | null;
  radius_m: number | null;
  polygon: LatLng[];
  tolerance_m: number;
  supervisor_user_ids: string[];
  active: boolean;
  /** Cost code put on timesheet lines built from shifts inside this fence. */
  default_cost_code: string;
  created_at: string;
  updated_at: string;
}

export type GeofencePayload = Omit<Geofence, 'id' | 'created_at' | 'updated_at'>;

export interface ClockSettings {
  project_id: string;
  enabled: boolean;
  retention_days: number;
  consent_text_version: string;
  /** Unpaid break deducted per built shift, 0..240. */
  default_break_minutes: number;
}

export interface ClockConsent {
  resource_id: string;
  project_id: string;
  granted: boolean;
  granted_at: string | null;
  withdrawn_at: string | null;
  text_version: string;
}

export type ClockKind = 'in' | 'out';
export type ApprovalStatus = 'not_required' | 'pending' | 'approved' | 'rejected';

export interface ClockEvent {
  id: string;
  project_id: string;
  resource_id: string;
  resource_name: string;
  kind: ClockKind;
  occurred_at: string;
  latitude: number | null;
  longitude: number | null;
  accuracy_m: number | null;
  geofence_id: string | null;
  geofence_name: string | null;
  inside: boolean;
  distance_m: number | null;
  approval_status: ApprovalStatus;
  approval_reason: string | null;
  approved_by: string | null;
  approved_at: string | null;
  pair_event_id: string | null;
  timesheet_id: string | null;
  position_purged: boolean;
  created_at: string;
}

export interface ClockEventPayload {
  project_id: string;
  resource_id: string;
  kind: ClockKind;
  latitude: number | null;
  longitude: number | null;
  accuracy_m: number | null;
  occurred_at?: string;
  client_op_id?: string;
  note?: string;
}

export interface ClockEventFilters {
  date_from?: string;
  date_to?: string;
  resource_id?: string;
  approval_status?: ApprovalStatus;
}

export interface OnSiteWorker {
  resource_id: string;
  resource_name: string;
  clocked_in_at: string;
  inside: boolean;
  event_id: string;
}

export interface ClockStatus {
  project_id: string;
  on_site: OnSiteWorker[];
  on_site_count: number;
  pending_approvals: number;
  missing_clock_outs: number;
  today_hours: string;
}

/* -- Calls ---------------------------------------------------------------- */

const qs = (o: Record<string, string | undefined>): string => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(o)) if (v) p.set(k, v);
  return p.toString();
};

export function listGeofences(projectId: string): Promise<Geofence[]> {
  return apiGet<Geofence[]>(`/v1/field-time/geofences/?${qs({ project_id: projectId })}`);
}
export function createGeofence(data: GeofencePayload): Promise<Geofence> {
  return apiPost<Geofence, GeofencePayload>('/v1/field-time/geofences/', data);
}
export function updateGeofence(id: string, data: Partial<GeofencePayload>): Promise<Geofence> {
  return apiPatch<Geofence, Partial<GeofencePayload>>(`/v1/field-time/geofences/${id}/`, data);
}
export function deleteGeofence(id: string): Promise<void> {
  return apiDelete(`/v1/field-time/geofences/${id}/`);
}

export function fetchClockSettings(projectId: string): Promise<ClockSettings> {
  return apiGet<ClockSettings>(`/v1/field-time/clock/settings/?${qs({ project_id: projectId })}`);
}
export function saveClockSettings(data: ClockSettings): Promise<ClockSettings> {
  return apiPut<ClockSettings, ClockSettings>('/v1/field-time/clock/settings/', data);
}

export function fetchClockConsent(projectId: string, resourceId: string): Promise<ClockConsent> {
  return apiGet<ClockConsent>(
    `/v1/field-time/clock/consent/?${qs({ project_id: projectId, resource_id: resourceId })}`,
  );
}
export function postClockConsent(data: {
  project_id: string;
  resource_id: string;
  granted: boolean;
  text_version: string;
}): Promise<ClockConsent> {
  return apiPost<ClockConsent, typeof data>('/v1/field-time/clock/consent/', data);
}

export function postClockEvent(data: ClockEventPayload): Promise<ClockEvent> {
  return apiPost<ClockEvent, ClockEventPayload>('/v1/field-time/clock/events/', data);
}
export interface CrewClockResult {
  events: ClockEvent[];
  skipped: { resource_id: string; code: string }[];
}
/** Clock a crew resource and all its members at the same position. */
export function postCrewClockEvent(data: ClockEventPayload): Promise<CrewClockResult> {
  return apiPost<CrewClockResult, ClockEventPayload>('/v1/field-time/clock/events/crew/', data);
}
export async function listClockEvents(
  projectId: string,
  filters: ClockEventFilters = {},
): Promise<{ items: ClockEvent[]; total: number }> {
  const res = await apiGet<{ items: ClockEvent[]; total: number }>(
    `/v1/field-time/clock/events/?${qs({ project_id: projectId, ...filters })}`,
  );
  return Array.isArray(res?.items) ? res : { items: [], total: 0 };
}
export function approveClockEvent(id: string, reason: string): Promise<ClockEvent> {
  return apiPost<ClockEvent, { reason: string }>(`/v1/field-time/clock/events/${id}/approve/`, { reason });
}
export function rejectClockEvent(id: string, reason: string): Promise<ClockEvent> {
  return apiPost<ClockEvent, { reason: string }>(`/v1/field-time/clock/events/${id}/reject/`, { reason });
}

export function fetchClockStatus(projectId: string): Promise<ClockStatus> {
  return apiGet<ClockStatus>(`/v1/field-time/clock/status/?${qs({ project_id: projectId })}`);
}
export function buildClockTimesheet(projectId: string, date: string): Promise<FieldTimesheet> {
  return apiPost<FieldTimesheet, { project_id: string; date: string }>(
    '/v1/field-time/clock/build-timesheet/',
    { project_id: projectId, date },
  );
}
export function fetchClockValidation(projectId: string, date: string): Promise<FieldTimeValidationReport> {
  return apiGet<FieldTimeValidationReport>(
    `/v1/field-time/clock/validation/?${qs({ project_id: projectId, date })}`,
  );
}
export function purgeClockPositions(projectId: string): Promise<{ purged: number }> {
  return apiPost<{ purged: number }>(
    `/v1/field-time/clock/retention/purge/?${qs({ project_id: projectId })}`,
  );
}

/* -- Hooks ---------------------------------------------------------------- */

const KEY = ['field-time', 'clock'] as const;

export function useGeofences(projectId: string) {
  return useQuery({
    queryKey: [...KEY, 'geofences', projectId],
    queryFn: () => listGeofences(projectId),
    enabled: !!projectId,
  });
}

export function useGeofenceMutations(projectId: string) {
  const qc = useQueryClient();
  const done = () => qc.invalidateQueries({ queryKey: [...KEY, 'geofences', projectId] });
  return {
    create: useMutation({ mutationFn: createGeofence, onSuccess: done }),
    update: useMutation({
      mutationFn: ({ id, data }: { id: string; data: Partial<GeofencePayload> }) => updateGeofence(id, data),
      onSuccess: done,
    }),
    remove: useMutation({ mutationFn: deleteGeofence, onSuccess: done }),
  };
}

export function useClockSettings(projectId: string) {
  return useQuery({
    queryKey: [...KEY, 'settings', projectId],
    queryFn: () => fetchClockSettings(projectId),
    enabled: !!projectId,
  });
}

export function useSaveClockSettings(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: saveClockSettings,
    onSuccess: () => qc.invalidateQueries({ queryKey: [...KEY, 'settings', projectId] }),
  });
}

export function useClockConsent(projectId: string, resourceId: string) {
  return useQuery({
    queryKey: [...KEY, 'consent', projectId, resourceId],
    queryFn: () => fetchClockConsent(projectId, resourceId),
    enabled: !!projectId && !!resourceId,
  });
}

export function useSetClockConsent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: postClockConsent,
    onSuccess: () => qc.invalidateQueries({ queryKey: [...KEY, 'consent'] }),
  });
}

export function useClockEvents(projectId: string, filters: ClockEventFilters = {}) {
  return useQuery({
    queryKey: [...KEY, 'events', projectId, filters],
    queryFn: () => listClockEvents(projectId, filters),
    enabled: !!projectId,
  });
}

export function useClockStatus(projectId: string) {
  return useQuery({
    queryKey: [...KEY, 'status', projectId],
    queryFn: () => fetchClockStatus(projectId),
    enabled: !!projectId,
    staleTime: 30 * 1000,
  });
}

export function useDecideClockEvent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, approve, reason }: { id: string; approve: boolean; reason: string }) =>
      approve ? approveClockEvent(id, reason) : rejectClockEvent(id, reason),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...KEY] }),
  });
}

export function useClockEventMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: ClockEventPayload & { crew?: boolean }): Promise<ClockEvent> => {
      const { crew, ...body } = data;
      if (!crew) return postClockEvent(body);
      const res = await postCrewClockEvent(body);
      const first = res.events.find((e) => e.resource_id === body.resource_id) ?? res.events[0];
      if (!first) throw new Error('empty crew result');
      // Skipped members travel on the first event so the panel can list them.
      return Object.assign({}, first, { skipped: res.skipped }) as ClockEvent;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: [...KEY] }),
  });
}
