// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Owner bid schedule API client, mounted at `/api/v1/owner_schedule`. Money and quantities are decimal strings. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { API_BASE, apiGet, downloadWithAuth, extractErrorMessageFromBody, fetchWithAuth } from '@/shared/lib/api';

export interface ProfileSummary {
  key: string;
  name: string;
  source: string;
  file_type: string;
  handled_by: string;
}
export interface DetectCandidate {
  profile_key: string;
  name: string;
  source: string;
  confidence: number;
  reasons: string[];
  item_count: number;
}
export interface Issue {
  severity: string;
  code: string;
  row: number | null;
  item_no: string | null;
  role: string | null;
}
export interface PreviewLine {
  row: number;
  item_no: string;
  description: string;
  unit: string;
  quantity: string | null;
  is_section: boolean;
  is_alternate: boolean;
  is_lump_sum: boolean;
}
export interface Preview {
  profile_key: string;
  item_count: number;
  lines: PreviewLine[];
  issues: Issue[];
}
export interface ScheduleItem {
  id: string;
  item_no: string;
  description: string;
  unit: string;
  quantity: string | null;
  is_section: boolean;
  is_alternate: boolean;
  removed: boolean;
  position_id: string | null;
  unit_price: string | null;
  amount: string | null;
}
export interface Finding {
  rule_id: string;
  severity: string;
  message: string;
  item_no: string | null;
}
export interface ScheduleStatus {
  id: string;
  boq_id: string;
  profile_name: string;
  file_name: string;
  revision: number;
  item_count: number;
  priced_count: number;
  total: string;
  alternates_total: string;
  items: ScheduleItem[];
  findings: Finding[];
}
export interface ImportResult {
  schedule_id: string;
  created_positions: number;
  linked_positions: number;
  item_count: number;
}
export interface DiffChange {
  kind: 'added' | 'removed' | 'changed' | 'quantity_changed';
  item_no: string;
  fields: string[];
}
export interface AddendumPreview {
  file_name: string;
  changes: DiffChange[];
  issues: Issue[];
}

async function send<T>(path: string, file: File, extra: Record<string, string> = {}): Promise<T> {
  const body = new FormData();
  body.append('file', file);
  for (const [k, v] of Object.entries(extra)) body.append(k, v);
  const response = await fetchWithAuth(`${API_BASE}/v1/owner_schedule${path}`, { method: 'POST', body });
  const payload = await response.json().catch(() => null);
  if (!response.ok) throw new Error(extractErrorMessageFromBody(payload) ?? `HTTP ${response.status}`);
  return payload as T;
}

const key = (boqId: string) => ['owner-schedule', boqId] as const;

export const detectProfiles = (file: File) => send<DetectCandidate[]>('/detect', file);
export const previewSchedule = (file: File, profileKey: string) =>
  send<Preview>('/preview', file, { profile_key: profileKey });
export const previewAddendum = (boqId: string, file: File) =>
  send<AddendumPreview>(`/boqs/${boqId}/addendum/preview`, file);
export const exportSchedule = (boqId: string) => downloadWithAuth(`${API_BASE}/v1/owner_schedule/boqs/${boqId}/export`, 'bid-schedule');

export function useProfiles() {
  return useQuery({
    queryKey: ['owner-schedule', 'profiles'],
    queryFn: async () =>
      (await apiGet<{ items: ProfileSummary[]; total: number }>('/v1/owner_schedule/profiles?limit=500')).items,
  });
}

/** A 404 means no schedule on this BOQ yet; the page then offers the import. */
export function useScheduleStatus(boqId: string) {
  return useQuery({
    queryKey: key(boqId),
    queryFn: async () => {
      try {
        return await apiGet<ScheduleStatus>(`/v1/owner_schedule/boqs/${boqId}`);
      } catch (e) {
        if ((e as { status?: number }).status === 404) return null;
        throw e;
      }
    },
    enabled: !!boqId,
    retry: false,
  });
}

export function useImportSchedule(boqId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { file: File; profileKey: string }) =>
      send<ImportResult>(`/boqs/${boqId}/import`, v.file, { profile_key: v.profileKey }),
    onSuccess: () => qc.invalidateQueries({ queryKey: key(boqId) }),
  });
}

export function useApplyAddendum(boqId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { file: File; itemNos: string[] | null }) =>
      send<{ revision: number; applied: number }>(
        `/boqs/${boqId}/addendum/apply`,
        v.file,
        v.itemNos ? { item_nos: JSON.stringify(v.itemNos) } : {},
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: key(boqId) }),
  });
}
