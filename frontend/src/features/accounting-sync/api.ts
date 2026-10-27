// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers and React Query hooks for the accounting sync module: connections
 * to Xero and QuickBooks (live, OAuth) and to file targets (DATEV EXTF, journal
 * CSV or Excel, SAF-T), the account and tax mapping, the sync log and exports.
 *
 * Mounted at `/api/v1/accounting_sync`. Money is a decimal STRING on the wire and
 * stays a string here; the UI formats it with the shared money formatter and
 * never does arithmetic on it.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { API_BASE, apiDelete, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';

/* -- Vocabularies (in lock-step with the backend module) ------------------- */

export type Provider = 'xero' | 'qbo' | 'datev' | 'journal' | 'saft';
export const PROVIDERS: Provider[] = ['xero', 'qbo', 'datev', 'journal', 'saft'];
/** Live providers authorise through OAuth; the others only produce files. */
export const LIVE_PROVIDERS: Provider[] = ['xero', 'qbo'];

export type ExportKind = 'datev_postings' | 'datev_master' | 'journal_csv' | 'journal_xlsx' | 'saft';

export type LogStatus = 'success' | 'failed' | 'skipped';
export type LogAction = 'push' | 'pull' | 'export' | 'connect';
export type DocumentRecordType = 'ar_invoice' | 'ap_bill';
export type DocumentSource = 'invoice' | 'interim_payment' | 'subcontractor' | 'procurement' | 'guarantee_fee';
export type TaxDirection = 'sales' | 'purchase';

export const RULE_IDS = [
  'accounting_sync.unmapped_account',
  'accounting_sync.tax_code_mismatch',
  'accounting_sync.closed_period',
  'accounting_sync.total_mismatch',
  'accounting_sync.contact_missing_tax_id',
] as const;

/** Which export buttons a template's `formats` unlock. */
const FORMAT_EXPORTS: Record<string, ExportKind[]> = {
  datev_extf: ['datev_postings', 'datev_master'],
  journal: ['journal_csv', 'journal_xlsx'],
  journal_csv: ['journal_csv'],
  journal_xlsx: ['journal_xlsx'],
  saft: ['saft'],
};

/* -- Wire types ------------------------------------------------------------- */

export interface StatusConnection {
  id: string;
  name: string;
  provider: Provider;
  status: string;
  last_sync_at: string | null;
  last_sync_status: string | null;
  success: number;
  failed: number;
  open_failures: number;
}

export interface SyncStatus {
  connections: StatusConnection[];
  open_failures: number;
  providers: { api: Provider[]; file: Provider[] };
}

export interface ChartTemplate {
  key: string;
  label: string;
  country_code: string | null;
  formats: string[];
}

export interface TaxCodeInfo {
  tax_code: string;
  name: string;
  rate_pct: string | number | null;
}

export interface TemplateCatalog {
  templates: ChartTemplate[];
  categories: string[];
  tax_codes: TaxCodeInfo[];
  journal_columns: string[];
  export_kinds: ExportKind[];
}

export interface ConnectionSettings {
  auto_push?: boolean;
  consultant_number?: string;
  client_number?: string;
  journal_columns?: string[];
  [key: string]: unknown;
}

export interface Connection {
  id: string;
  name: string;
  provider: Provider;
  country_code: string | null;
  chart_template: string | null;
  base_currency: string;
  status: string;
  is_sandbox: boolean;
  client_id: string | null;
  has_client_secret: boolean;
  is_authorised: boolean;
  external_tenant_id: string | null;
  lock_date: string | null;
  project_ids: string[];
  settings: ConnectionSettings;
  last_sync_at: string | null;
  last_sync_status: string | null;
  created_at: string;
}

export interface ConnectionCreate {
  name: string;
  provider: Provider;
  country_code?: string | null;
  chart_template?: string | null;
  base_currency: string;
  is_sandbox: boolean;
  client_id?: string | null;
  client_secret?: string | null;
  external_tenant_id?: string | null;
  lock_date?: string | null;
  project_ids: string[];
  settings: ConnectionSettings;
}

export type ConnectionUpdate = Partial<ConnectionCreate> & { clear_lock_date?: boolean };

export interface AccountMapping {
  category: string;
  account_code: string;
  account_name: string;
}

export interface TaxMapping {
  tax_code: string;
  direction: TaxDirection;
  external_code: string;
  rate_pct: string | number | null;
}

export interface Mappings {
  chart_template: string | null;
  templates: ChartTemplate[];
  tax_codes: TaxCodeInfo[];
  accounts: AccountMapping[];
  taxes: TaxMapping[];
}

export interface MappingsBody {
  accounts: AccountMapping[];
  taxes: TaxMapping[];
}

export interface SyncDocument {
  record_id: string;
  record_type: DocumentRecordType;
  source: DocumentSource;
  number: string;
  doc_date: string | null;
  counterparty: string | null;
  project_code: string | null;
  currency: string;
  net_total: string;
  tax_total: string;
  gross_total: string;
  external_id: string | null;
}

export interface Finding {
  rule_id: string;
  severity: 'error' | 'warning' | 'info' | string;
  message: string;
  element_ref: string | null;
  record_id: string | null;
}

export interface PushResult {
  success: number;
  failed: number;
  skipped: number;
}

export interface PushBody {
  project_id?: string;
  record_ids?: string[];
}

export interface LogEntry {
  id: string;
  connection_id: string;
  project_id: string | null;
  action: LogAction;
  record_type: string | null;
  record_id: string | null;
  record_label: string | null;
  status: LogStatus;
  attempt: number;
  error_reason: string | null;
  external_id: string | null;
  amount: string | null;
  resolved: boolean;
  created_at: string;
}

export interface LogPage {
  items: LogEntry[];
  total: number;
}

export interface DateRange {
  date_from?: string;
  date_to?: string;
}

/* -- Pure helpers ------------------------------------------------------------ */

/** Export kinds a template unlocks, in a stable order; none known means every kind. */
export function exportKindsFor(formats: string[] | undefined, all: ExportKind[]): ExportKind[] {
  if (!formats || formats.length === 0) return all;
  const allowed = new Set<ExportKind>();
  for (const f of formats) for (const k of FORMAT_EXPORTS[f] ?? []) allowed.add(k);
  return all.filter((k) => allowed.has(k));
}

/** Account rows without an account code: they cannot be posted. */
export function unmappedAccounts(accounts: AccountMapping[]): AccountMapping[] {
  return accounts.filter((a) => a.account_code.trim() === '');
}

/** Tax rows without an external code. */
export function unmappedTaxes(taxes: TaxMapping[]): TaxMapping[] {
  return taxes.filter((x) => x.external_code.trim() === '');
}

/** A failed entry can be retried until it is resolved. */
export function canRetry(entry: Pick<LogEntry, 'status' | 'resolved' | 'action'>): boolean {
  return entry.status === 'failed' && !entry.resolved && entry.action !== 'connect';
}

/** Whether the connection needs the OAuth round trip before it can push. */
export function needsAuthorisation(c: Pick<Connection, 'provider' | 'is_authorised'>): boolean {
  return LIVE_PROVIDERS.includes(c.provider) && !c.is_authorised;
}

/** Drops empty strings and undefined so a PATCH or POST body carries only set values. */
export function compactBody<T extends object>(body: T): Partial<T> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(body)) {
    if (v === '' || v === undefined) continue;
    out[k] = v;
  }
  return out as Partial<T>;
}

/** Where the provider sends the browser back to after the user approves access. */
export function oauthRedirectUri(): string {
  return `${window.location.origin}/accounting-sync/oauth/callback`;
}

/* -- Fetchers ------------------------------------------------------------------ */

const BASE = '/v1/accounting_sync';

function qs(params: Record<string, string | number | undefined | null>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') sp.set(k, String(v));
  const s = sp.toString();
  return s ? `?${s}` : '';
}

export const fetchStatus = () => apiGet<SyncStatus>(`${BASE}/status`);
export const fetchTemplates = (countryCode?: string) =>
  apiGet<TemplateCatalog>(`${BASE}/templates${qs({ country_code: countryCode })}`);
export const fetchConnections = () => apiGet<Connection[]>(`${BASE}/connections`);
export const createConnection = (body: ConnectionCreate) =>
  apiPost<Connection, ConnectionCreate>(`${BASE}/connections`, body);
export const updateConnection = (id: string, body: ConnectionUpdate) =>
  apiPatch<Connection, ConnectionUpdate>(`${BASE}/connections/${id}`, body);
export const deleteConnection = (id: string) => apiDelete<void>(`${BASE}/connections/${id}`);

export const startOAuth = (id: string, redirectUri: string) =>
  apiPost<{ authorization_url: string }>(`${BASE}/connections/${id}/oauth/start${qs({ redirect_uri: redirectUri })}`);
export const completeOAuth = (id: string, body: { code: string; redirect_uri: string; tenant_id?: string }) =>
  apiPost<Connection>(`${BASE}/connections/${id}/oauth/complete`, body);

export const fetchMappings = (id: string) => apiGet<Mappings>(`${BASE}/connections/${id}/mappings`);
export const saveMappings = (id: string, body: MappingsBody) =>
  apiPut<Mappings, MappingsBody>(`${BASE}/connections/${id}/mappings`, body);
export const applyTemplate = (id: string, chartTemplate: string) =>
  apiPost<Mappings>(`${BASE}/connections/${id}/mappings/template`, { chart_template: chartTemplate });

export const fetchDocuments = (id: string, range: DateRange) =>
  apiGet<SyncDocument[]>(`${BASE}/connections/${id}/documents${qs({ ...range })}`);
export const fetchFindings = (id: string) => apiGet<Finding[]>(`${BASE}/connections/${id}/findings`);
export const pushRecords = (id: string, body: PushBody = {}) =>
  apiPost<PushResult, PushBody>(`${BASE}/connections/${id}/push`, body);
export const pullPayments = (id: string) => apiPost<PushResult>(`${BASE}/connections/${id}/pull-payments`);

export const fetchLog = (id: string, opts: { status?: LogStatus; limit?: number; offset?: number }) =>
  apiGet<LogPage>(`${BASE}/connections/${id}/log${qs({ ...opts })}`);
export const retryLogEntry = (id: string, entryId: string) =>
  apiPost<LogEntry>(`${BASE}/connections/${id}/log/${entryId}/retry`);

/** Authenticated file download; the server names the file. */
export function downloadExport(
  id: string,
  kind: ExportKind,
  range: DateRange,
  columns?: string[],
): Promise<void> {
  const url = `${API_BASE}${BASE}/connections/${id}/export${qs({
    kind,
    ...range,
    columns: columns && columns.length > 0 ? columns.join(',') : undefined,
  })}`;
  return downloadWithAuth(url, `${kind}-export`);
}

/* -- Hooks --------------------------------------------------------------------- */

export const syncKeys = {
  all: ['accounting-sync'] as const,
  status: ['accounting-sync', 'status'] as const,
  templates: (cc: string) => ['accounting-sync', 'templates', cc] as const,
  connections: ['accounting-sync', 'connections'] as const,
  mappings: (id: string) => ['accounting-sync', 'mappings', id] as const,
  documents: (id: string, r: DateRange) => ['accounting-sync', 'documents', id, r] as const,
  findings: (id: string) => ['accounting-sync', 'findings', id] as const,
  log: (id: string, status: string, offset: number) => ['accounting-sync', 'log', id, status, offset] as const,
};

export function useSyncStatus() {
  return useQuery({ queryKey: syncKeys.status, queryFn: fetchStatus, staleTime: 60 * 1000 });
}

export function useTemplates(countryCode = '') {
  return useQuery({
    queryKey: syncKeys.templates(countryCode),
    queryFn: () => fetchTemplates(countryCode || undefined),
    staleTime: 10 * 60 * 1000,
  });
}

export function useConnections() {
  return useQuery({ queryKey: syncKeys.connections, queryFn: fetchConnections });
}

export function useMappings(id: string) {
  return useQuery({ queryKey: syncKeys.mappings(id), queryFn: () => fetchMappings(id), enabled: !!id });
}

export function useDocuments(id: string, range: DateRange) {
  return useQuery({ queryKey: syncKeys.documents(id, range), queryFn: () => fetchDocuments(id, range), enabled: !!id });
}

export function useFindings(id: string) {
  return useQuery({ queryKey: syncKeys.findings(id), queryFn: () => fetchFindings(id), enabled: !!id });
}

export const LOG_PAGE_SIZE = 25;

export function useSyncLog(id: string, failedOnly: boolean, offset: number) {
  const status = failedOnly ? 'failed' : '';
  return useQuery({
    queryKey: syncKeys.log(id, status, offset),
    queryFn: () => fetchLog(id, { status: failedOnly ? 'failed' : undefined, limit: LOG_PAGE_SIZE, offset }),
    enabled: !!id,
  });
}

/** Every write refreshes the whole `accounting-sync` cache: list, status tile, findings and log move together. */
export function useSyncMutation<TVars, TResult>(fn: (vars: TVars) => Promise<TResult>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: syncKeys.all }),
  });
}
