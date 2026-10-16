// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Request types as data: the register's type catalogue on the client.
 *
 * What kind of request a row is (RFI, Technical Query, Site Query, Concession
 * Request ...) is a row in the project's catalogue, served by
 * `GET /v1/rfi/types/`. Type names come from the catalogue in every language
 * it carries, not from the locale files: a company that adds its own type
 * names it once, in the languages its people read.
 *
 * Everything in this file is pure so the picker, the filter, the stats strip
 * and the create form agree, and so it is testable without a network.
 */

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';

/** The type every request has unless it names another. */
export const DEFAULT_REQUEST_TYPE = 'RFI';

/** Request fields a type may require before the request is issued. Mirrors the backend list. */
export const REQUIRED_FIELD_CHOICES = [
  'assigned_to',
  'response_due_date',
  'discipline',
  'priority',
  'linked_drawing_ids',
  'cost_impact_value',
  'schedule_impact_days',
] as const;

export type RequiredField = (typeof REQUIRED_FIELD_CHOICES)[number];

export interface RequestType {
  /** `null` for the built-in RFI type a project has before it loads a catalogue. */
  id: string | null;
  project_id: string;
  code: string;
  /** English name, the fallback when the reader's language has none. */
  name: string;
  name_i18n: Record<string, string>;
  description_i18n: Record<string, string>;
  number_prefix: string;
  number_digits: number;
  default_response_days: number | null;
  /** The SLA applied, in business days: the type's own, else the platform default. */
  response_days: number;
  required_fields: string[];
  default_route_id: string | null;
  is_active: boolean;
  is_builtin: boolean;
  sort_order: number;
  preset_code: string | null;
  request_count: number;
}

export interface RequestTypeCatalogue {
  items: RequestType[];
  total: number;
  required_field_choices: string[];
}

export interface RequestTypePresetType {
  code: string;
  number_prefix: string;
  number_digits: number;
  name_i18n: Record<string, string>;
  default_response_days: number | null;
  required_fields: string[];
}

export interface RequestTypePreset {
  code: string;
  name_i18n: Record<string, string>;
  description_i18n: Record<string, string>;
  types: RequestTypePresetType[];
}

export interface PresetLoadResult {
  preset_code: string;
  created: string[];
  skipped: string[];
}

export interface CreateRequestTypePayload {
  project_id: string;
  code: string;
  name_i18n: Record<string, string>;
  description_i18n?: Record<string, string>;
  number_prefix: string;
  number_digits?: number;
  default_response_days?: number | null;
  required_fields?: string[];
  default_route_id?: string | null;
  is_active?: boolean;
  sort_order?: number;
}

export type UpdateRequestTypePayload = Partial<
  Omit<CreateRequestTypePayload, 'project_id' | 'code' | 'number_prefix'>
>;

export interface RegisterValidationResult {
  rule_id: string;
  severity: string;
  passed: boolean;
  message: string;
  element_ref: string | null;
  details: Record<string, unknown>;
}

export interface RegisterValidation {
  status: 'passed' | 'warnings' | 'errors' | string;
  score: number | null;
  errors: number;
  warnings: number;
  results: RegisterValidationResult[];
}

/* ── Pure helpers ──────────────────────────────────────────────────────── */

/**
 * The text for `language`: the exact tag, then its base language, then
 * English, then `fallback`. `de-AT` reads the German name when only `de` is
 * in the catalogue.
 */
export function localizedText(
  texts: Record<string, string> | null | undefined,
  language: string | null | undefined,
  fallback: string,
): string {
  if (!texts) return fallback;
  if (language) {
    const tag = language.replace('_', '-');
    const exact = texts[tag];
    if (exact) return exact;
    const base = texts[tag.split('-')[0] ?? ''];
    if (base) return base;
  }
  return texts.en || fallback;
}

/** A type's name in the reader's language, falling back to its English name and then its code. */
export function requestTypeName(type: Pick<RequestType, 'code' | 'name' | 'name_i18n'>, language: string): string {
  return localizedText(type.name_i18n, language, type.name || type.code);
}

/**
 * The label of a request's type code: its catalogue name, or the bare code
 * when the catalogue no longer holds it (a retired-then-deleted type keeps
 * its rows, and the code is still the truth about them).
 */
export function requestTypeLabel(types: RequestType[], code: string | null | undefined, language: string): string {
  const key = code || DEFAULT_REQUEST_TYPE;
  const type = types.find((t) => t.code === key);
  return type ? requestTypeName(type, language) : key;
}

/** Types a new request may use: active ones, in catalogue order. */
export function selectableTypes(types: RequestType[]): RequestType[] {
  return types.filter((t) => t.is_active).sort((a, b) => a.sort_order - b.sort_order || a.code.localeCompare(b.code));
}

/** The values the create form holds, keyed by the request field they fill. */
export interface RequiredFieldValues {
  assigned_to: string;
  response_due_date: string;
  discipline: string;
  priority: string;
  linked_drawing_ids: string[];
  cost_impact_value: string;
  schedule_impact_days: string;
}

function isEmpty(value: unknown): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === 'string') return value.trim().length === 0;
  if (Array.isArray(value)) return value.length === 0;
  return false;
}

/** The fields `type` requires that `values` leaves empty, in the type's order. Mirrors the backend. */
export function missingRequiredFields(
  type: Pick<RequestType, 'required_fields'> | null | undefined,
  values: RequiredFieldValues,
): string[] {
  if (!type) return [];
  return type.required_fields.filter((field) =>
    isEmpty((values as unknown as Record<string, unknown>)[field]),
  );
}

/** What a number of this type looks like, e.g. `TQ-0001`. */
export function sampleNumber(type: Pick<RequestType, 'number_prefix' | 'number_digits'>): string {
  return `${type.number_prefix}-${'1'.padStart(type.number_digits, '0')}`;
}

/* ── API ───────────────────────────────────────────────────────────────── */

// Routes are under /v1/rfi/ with a trailing slash on collections and none on
// /types/{id} (type_routes.py); the app runs with redirect_slashes=False.

export function fetchRequestTypes(projectId: string): Promise<RequestTypeCatalogue> {
  return apiGet<RequestTypeCatalogue>(`/v1/rfi/types/?project_id=${encodeURIComponent(projectId)}`);
}

export async function fetchRequestTypePresets(): Promise<RequestTypePreset[]> {
  const page = await apiGet<{ items: RequestTypePreset[]; total: number }>('/v1/rfi/types/presets/');
  return page.items;
}

export function loadRequestTypePreset(presetCode: string, projectId: string): Promise<PresetLoadResult> {
  return apiPost<PresetLoadResult>(
    `/v1/rfi/types/presets/${encodeURIComponent(presetCode)}/load/?project_id=${encodeURIComponent(projectId)}`,
  );
}

export function createRequestType(data: CreateRequestTypePayload): Promise<RequestType> {
  return apiPost<RequestType, CreateRequestTypePayload>('/v1/rfi/types/', data);
}

export function updateRequestType(id: string, data: UpdateRequestTypePayload): Promise<RequestType> {
  return apiPatch<RequestType, UpdateRequestTypePayload>(`/v1/rfi/types/${encodeURIComponent(id)}`, data);
}

export function deleteRequestType(id: string): Promise<void> {
  return apiDelete(`/v1/rfi/types/${encodeURIComponent(id)}`);
}

export function fetchRegisterValidation(projectId: string): Promise<RegisterValidation> {
  return apiGet<RegisterValidation>(`/v1/rfi/validation/?project_id=${encodeURIComponent(projectId)}`);
}
