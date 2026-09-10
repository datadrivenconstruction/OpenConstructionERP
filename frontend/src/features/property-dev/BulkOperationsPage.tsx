// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Property Development — Bulk Operations admin console.
 *
 * Five batch endpoints surfaced as a single page of <details>-collapsible
 * sections, one per backend operation. Each section shares the same
 * three-step flow: configure -> Dry run -> Execute for real, with the
 * result envelope rendered through one shared <BulkResultPanel>.
 *
 * MANAGER+ gated end-to-end: the route mounts inside <P> which already
 * forces auth, and we additionally re-check the role here so non-MANAGER
 * users get a clear "Not authorized" landing page instead of a wall of
 * 403s when they try to click anything.
 *
 * Mobile: every section is a <details> so the page is one tap-to-expand
 * column on phones. Desktop keeps each <details> open by default for the
 * sales-ops workflow (most users will scroll through and trigger 2-3 ops
 * in one session).
 *
 * Empty-state copy mentions the inventory map (sibling agent C's
 * surface) so users know where the plot multi-select lives without us
 * importing that page.
 */

import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileText,
  GitMerge,
  Map as MapIcon,
  RefreshCw,
  ShieldAlert,
  Upload,
  XCircle,
} from 'lucide-react';
import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  DismissibleInfo,
  EmptyState,
  IntroRichText,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { getErrorMessage, triggerDownload, apiPost } from '@/shared/lib/api';

const API_BASE = '/v1/property-dev';
const MANAGER_PLUS = new Set(['admin', 'superuser', 'owner', 'manager']);
const BULK_MAX_ITEMS = 500;
const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const labelCls =
  'block text-xs font-medium text-content-secondary mb-1';

/* ───────────── Shared types ────────────────────────────────────────── */

interface BulkSkipped {
  entity_id: string;
  reason: string;
  code: string;
}

interface BulkFailed {
  entity_id: string;
  error_message: string;
  error_code: string;
}

interface BulkResult {
  requested: number;
  succeeded: number;
  skipped: BulkSkipped[];
  failed: BulkFailed[];
  dry_run: boolean;
}

type BulkPhase = 'idle' | 'dry-run-done' | 'real-done';

/* ───────────── Shared result panel ─────────────────────────────────── */

function BulkResultPanel({
  result,
  sectionLabel,
}: {
  result: BulkResult | null;
  sectionLabel: string;
}) {
  const { t } = useTranslation();
  if (!result) return null;
  const { requested, succeeded, skipped, failed, dry_run } = result;
  const pct = requested === 0 ? 0 : Math.round((succeeded / requested) * 100);

  const handleDownloadCsv = () => {
    const rows: string[][] = [
      ['outcome', 'entity_id', 'code', 'detail'],
      ...failed.map((f) => ['failed', f.entity_id, f.error_code, f.error_message]),
      ...skipped.map((s) => ['skipped', s.entity_id, s.code, s.reason]),
    ];
    const csv = rows
      .map((r) => r.map((cell) => `"${(cell ?? '').replaceAll('"', '""')}"`).join(','))
      .join('\n');
    const fname = `${sectionLabel.replaceAll(' ', '_').toLowerCase()}-${
      dry_run ? 'dryrun' : 'live'
    }-${new Date().toISOString().slice(0, 19).replaceAll(':', '')}.csv`;
    triggerDownload(new Blob([csv], { type: 'text/csv' }), fname);
  };

  return (
    <div className="mt-4 rounded-lg border border-border-light bg-surface-secondary p-4">
      <div className="flex flex-wrap items-center gap-3">
        {dry_run && (
          <Badge variant="blue">{t('property_dev.bulk.dry_run_badge', { defaultValue: 'DRY RUN - no rows were written' })}</Badge>
        )}
        <div className="text-sm font-semibold text-content-primary">
          {t('property_dev.bulk.result_summary', { defaultValue: '{{succeeded}} / {{requested}} succeeded ({{pct}}%)', succeeded, requested, pct })}
        </div>
        {(failed.length > 0 || skipped.length > 0) && (
          <Button
            variant="secondary"
            size="sm"
            icon={<Download size={14} />}
            onClick={handleDownloadCsv}
          >
            {t('property_dev.bulk.download_csv', { defaultValue: 'Download log CSV' })}
          </Button>
        )}
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 text-xs">
        <div className="rounded-md bg-green-50 px-2 py-1.5 text-green-800 dark:bg-green-900/30 dark:text-green-300">
          <CheckCircle2 size={12} className="mr-1 inline" />
          {t('property_dev.bulk.ok_count', { defaultValue: '{{count}} ok', count: succeeded })}
        </div>
        <div className="rounded-md bg-yellow-50 px-2 py-1.5 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300">
          <ShieldAlert size={12} className="mr-1 inline" />
          {t('property_dev.bulk.skipped_count', { defaultValue: '{{count}} skipped', count: skipped.length })}
        </div>
        <div className="rounded-md bg-red-50 px-2 py-1.5 text-red-800 dark:bg-red-900/30 dark:text-red-300">
          <XCircle size={12} className="mr-1 inline" />
          {t('property_dev.bulk.failed_count', { defaultValue: '{{count}} failed', count: failed.length })}
        </div>
      </div>

      {failed.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs font-medium text-content-secondary">
            {t('property_dev.bulk.show_failures', { defaultValue: 'Show {{count}} failure(s)', count: failed.length })}
          </summary>
          <ul className="mt-2 space-y-1 text-xs">
            {failed.slice(0, 100).map((f, i) => (
              <li
                key={`${f.entity_id}-${i}`}
                className="rounded-md border border-red-200 bg-white p-2 dark:border-red-800 dark:bg-surface-primary"
              >
                <div className="font-mono text-[11px] text-content-tertiary">
                  {f.entity_id}
                </div>
                <div className="text-content-primary">
                  <Badge variant="error" className="mr-2">
                    {f.error_code}
                  </Badge>
                  {f.error_message}
                </div>
              </li>
            ))}
            {failed.length > 100 && (
              <li className="text-content-tertiary">
                {t('property_dev.bulk.more_download_csv', { defaultValue: '\u2026 and {{count}} more (download CSV for the full list).', count: failed.length - 100 })}
              </li>
            )}
          </ul>
        </details>
      )}

      {skipped.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs font-medium text-content-secondary">
            {t('property_dev.bulk.show_skipped', { defaultValue: 'Show {{count}} skipped', count: skipped.length })}
          </summary>
          <ul className="mt-2 space-y-1 text-xs">
            {skipped.slice(0, 100).map((s, i) => (
              <li
                key={`${s.entity_id}-${i}`}
                className="rounded-md border border-yellow-200 bg-white p-2 dark:border-yellow-800 dark:bg-surface-primary"
              >
                <div className="font-mono text-[11px] text-content-tertiary">
                  {s.entity_id}
                </div>
                <div className="text-content-primary">
                  <Badge variant="warning" className="mr-2">
                    {s.code}
                  </Badge>
                  {s.reason}
                </div>
              </li>
            ))}
            {skipped.length > 100 && (
              <li className="text-content-tertiary">
                {t('property_dev.bulk.more_skipped', { defaultValue: '\u2026 and {{count}} more.', count: skipped.length - 100 })}
              </li>
            )}
          </ul>
        </details>
      )}
    </div>
  );
}

/* ───────────── Reusable execute-with-typed-confirm helper ──────────── */

function useExecuteConfirm(itemsCount: number): {
  needsTypedConfirm: boolean;
  confirmText: string;
  setConfirmText: (v: string) => void;
  canExecute: boolean;
} {
  const [confirmText, setConfirmText] = useState('');
  const needsTypedConfirm = itemsCount > 50;
  return {
    needsTypedConfirm,
    confirmText,
    setConfirmText,
    canExecute: !needsTypedConfirm || confirmText === 'EXECUTE',
  };
}

/* ───────────── Section: plot status change ─────────────────────────── */

function PlotStatusChangeSection() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [idsText, setIdsText] = useState('');
  const [targetStatus, setTargetStatus] = useState<
    'planned' | 'under_construction' | 'ready' | 'sold' | 'handed_over'
  >('sold');
  const [reason, setReason] = useState('');
  const [phase, setPhase] = useState<BulkPhase>('idle');
  const [result, setResult] = useState<BulkResult | null>(null);

  const plotIds = useMemo(
    () =>
      idsText
        .split(/[\s,]+/)
        .map((s) => s.trim())
        .filter((s) => s.length > 0),
    [idsText],
  );

  const confirm = useExecuteConfirm(plotIds.length);

  const mu = useMutation<BulkResult, unknown, { dry: boolean }>({
    mutationFn: async ({ dry }) => {
      return apiPost<BulkResult>(
        `${API_BASE}/bulk/plots/bulk-status-change/${dry ? '?dry_run=true' : ''}`,
        {
          plot_ids: plotIds,
          target_status: targetStatus,
          reason,
        },
      );
    },
    onSuccess: (data, vars) => {
      setResult(data);
      setPhase(vars.dry ? 'dry-run-done' : 'real-done');
      addToast({
        type: data.failed.length > 0 ? 'warning' : 'success',
        title: `Plot status: ${data.succeeded}/${data.requested} ${
          vars.dry ? '(dry-run)' : 'updated'
        }`,
      });
    },
    onError: (err) => {
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  if (plotIds.length === 0 && phase === 'idle') {
    return (
      <SectionShell
        title={t('property_dev.bulk.plot_status_change', { defaultValue: 'Bulk plot status change' })}
        icon={<RefreshCw size={16} />}
        desc={t('property_dev.bulk.plot_status_desc', { defaultValue: 'Flip a set of plots to a new status (excludes hold/release - use the inventory map).' })}
      >
        <EmptyState
          title={t('property_dev.bulk.no_plots_selected', { defaultValue: 'No plots selected' })}
          description={t('property_dev.bulk.no_plots_desc', { defaultValue: 'Pick from the inventory map first, then paste their UUIDs here.' })}
          action={
            <Link
              to="/property-dev"
              className="inline-flex items-center gap-2 rounded-lg border border-oe-blue/30 bg-oe-blue/10 px-3 py-1.5 text-sm text-oe-blue hover:bg-oe-blue/20"
            >
              <MapIcon size={14} /> {t('property_dev.bulk.open_inventory_map', { defaultValue: 'Open inventory map' })}
            </Link>
          }
        />
        <PlotIdsInput
          value={idsText}
          onChange={setIdsText}
          plotIdsCount={plotIds.length}
        />
      </SectionShell>
    );
  }

  return (
    <SectionShell
      title={t('property_dev.bulk.plot_status_change', { defaultValue: 'Bulk plot status change' })}
      icon={<RefreshCw size={16} />}
      desc={t('property_dev.bulk.plot_status_desc', { defaultValue: 'Flip a set of plots to a new status (excludes hold/release - use the inventory map).' })}
    >
      <PlotIdsInput
        value={idsText}
        onChange={setIdsText}
        plotIdsCount={plotIds.length}
      />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className={labelCls}>{t('property_dev.bulk.target_status', { defaultValue: 'Target status' })}</label>
          <select
            value={targetStatus}
            onChange={(e) => setTargetStatus(e.target.value as typeof targetStatus)}
            className={inputCls}
          >
            <option value="planned">planned</option>
            <option value="under_construction">under_construction</option>
            <option value="ready">ready</option>
            <option value="sold">sold</option>
            <option value="handed_over">handed_over</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>{t('property_dev.bulk.reason_label', { defaultValue: 'Reason (audit-logged)' })}</label>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className={inputCls}
            placeholder="e.g. milestone X cleared deposits"
            maxLength={500}
          />
        </div>
      </div>

      <ActionBar
        plotIdsCount={plotIds.length}
        phase={phase}
        confirm={confirm}
        onDryRun={() => mu.mutate({ dry: true })}
        onExecute={() => mu.mutate({ dry: false })}
        isPending={mu.isPending}
      />
      <BulkResultPanel result={result} sectionLabel="plot status change" />
    </SectionShell>
  );
}

/* ───────────── Section: reservation extend expiry ──────────────────── */

function ReservationExtendExpirySection() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [idsText, setIdsText] = useState('');
  const [newExpiry, setNewExpiry] = useState('');
  const [reason, setReason] = useState('');
  const [phase, setPhase] = useState<BulkPhase>('idle');
  const [result, setResult] = useState<BulkResult | null>(null);

  const reservationIds = useMemo(
    () =>
      idsText
        .split(/[\s,]+/)
        .map((s) => s.trim())
        .filter((s) => s.length > 0),
    [idsText],
  );

  const confirm = useExecuteConfirm(reservationIds.length);

  const mu = useMutation<BulkResult, unknown, { dry: boolean }>({
    mutationFn: async ({ dry }) =>
      apiPost<BulkResult>(
        `${API_BASE}/bulk/reservations/bulk-extend-expiry/${
          dry ? '?dry_run=true' : ''
        }`,
        {
          reservation_ids: reservationIds,
          new_expiry: newExpiry,
          reason,
        },
      ),
    onSuccess: (data, vars) => {
      setResult(data);
      setPhase(vars.dry ? 'dry-run-done' : 'real-done');
      addToast({
        type: data.failed.length > 0 ? 'warning' : 'success',
        title: `Reservation expiry: ${data.succeeded}/${data.requested} ${
          vars.dry ? '(dry-run)' : 'extended'
        }`,
      });
    },
    onError: (err) => {
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  return (
    <SectionShell
      title={t('property_dev.bulk.extend_reservation_expiries', { defaultValue: 'Bulk extend reservation expiries' })}
      icon={<RefreshCw size={16} />}
      desc={t('property_dev.bulk.extend_expiry_desc', { defaultValue: 'Push expires_at to a new ISO date for a set of ACTIVE reservations.' })}
    >
      <PlotIdsInput
        value={idsText}
        onChange={setIdsText}
        plotIdsCount={reservationIds.length}
        label={t('property_dev.bulk.reservation_uuids', { defaultValue: 'Reservation UUIDs' })}
      />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className={labelCls}>{t('property_dev.bulk.new_expiry_label', { defaultValue: 'New expiry (ISO date)' })}</label>
          <input
            type="date"
            value={newExpiry}
            onChange={(e) => setNewExpiry(e.target.value)}
            className={inputCls}
          />
        </div>
        <div>
          <label className={labelCls}>{t('property_dev.bulk.reason_label', { defaultValue: 'Reason (audit-logged)' })}</label>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className={inputCls}
            placeholder="e.g. marketing push extends Q4 deadline"
            maxLength={500}
          />
        </div>
      </div>
      <ActionBar
        plotIdsCount={reservationIds.length}
        phase={phase}
        confirm={confirm}
        onDryRun={() => mu.mutate({ dry: true })}
        onExecute={() => mu.mutate({ dry: false })}
        isPending={mu.isPending}
        disabled={!newExpiry}
      />
      <BulkResultPanel result={result} sectionLabel="reservation extend expiry" />
    </SectionShell>
  );
}

/* ───────────── Section: documents regenerate ───────────────────────── */

function DocumentsRegenerateSection() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [docType, setDocType] = useState<
    'reservation_receipt' | 'sales_contract' | 'handover_certificate' | 'warranty_certificate' | 'noc'
  >('sales_contract');
  const [idsText, setIdsText] = useState('');
  const [locale, setLocale] = useState('en');
  const [phase, setPhase] = useState<BulkPhase>('idle');
  const [result, setResult] = useState<BulkResult | null>(null);

  const ids = useMemo(
    () =>
      idsText
        .split(/[\s,]+/)
        .map((s) => s.trim())
        .filter((s) => s.length > 0),
    [idsText],
  );
  const confirm = useExecuteConfirm(ids.length);
  const idsKey = docType === 'reservation_receipt' ? 'reservation_ids' : 'sales_contract_ids';

  const mu = useMutation<BulkResult, unknown, { dry: boolean }>({
    mutationFn: async ({ dry }) =>
      apiPost<BulkResult>(
        `${API_BASE}/bulk/documents/bulk-regenerate/${dry ? '?dry_run=true' : ''}`,
        {
          document_type: docType,
          [idsKey]: ids,
          locale,
        },
      ),
    onSuccess: (data, vars) => {
      setResult(data);
      setPhase(vars.dry ? 'dry-run-done' : 'real-done');
      addToast({
        type: data.failed.length > 0 ? 'warning' : 'success',
        title: `Docs: ${data.succeeded}/${data.requested} ${
          vars.dry ? '(dry-run)' : 'regenerated'
        }`,
      });
    },
    onError: (err) => {
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  return (
    <SectionShell
      title={t('property_dev.bulk.regenerate_documents', { defaultValue: 'Bulk regenerate documents' })}
      icon={<FileText size={16} />}
      desc={t('property_dev.bulk.regenerate_desc', { defaultValue: 'Re-render PDFs after a template fix - receipts, SPAs, certificates, NOCs.' })}
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className={labelCls}>{t('property_dev.bulk.document_type', { defaultValue: 'Document type' })}</label>
          <select
            value={docType}
            onChange={(e) => setDocType(e.target.value as typeof docType)}
            className={inputCls}
          >
            <option value="reservation_receipt">{t('property_dev.bulk.doc_reservation_receipt', { defaultValue: 'Reservation receipt' })}</option>
            <option value="sales_contract">{t('property_dev.bulk.doc_sales_contract', { defaultValue: 'Sales contract (SPA)' })}</option>
            <option value="handover_certificate">{t('property_dev.bulk.doc_handover_certificate', { defaultValue: 'Handover certificate' })}</option>
            <option value="warranty_certificate">{t('property_dev.bulk.doc_warranty_certificate', { defaultValue: 'Warranty certificate' })}</option>
            <option value="noc">{t('property_dev.bulk.doc_noc', { defaultValue: 'No-Objection Certificate (NOC)' })}</option>
          </select>
        </div>
        <div>
          <label className={labelCls}>{t('property_dev.bulk.locale_label', { defaultValue: 'Locale' })}</label>
          <select
            value={locale}
            onChange={(e) => setLocale(e.target.value)}
            className={inputCls}
          >
            <option value="en">en - English</option>
            <option value="de">de - Deutsch</option>
            <option value="ru">ru - Русский</option>
            <option value="fr">fr - Français</option>
            <option value="es">es - Español</option>
            <option value="ar">ar - العربية</option>
          </select>
        </div>
      </div>
      <PlotIdsInput
        value={idsText}
        onChange={setIdsText}
        plotIdsCount={ids.length}
        label={
          docType === 'reservation_receipt'
            ? t('property_dev.bulk.reservation_uuids', { defaultValue: 'Reservation UUIDs' })
            : t('property_dev.bulk.sales_contract_uuids', { defaultValue: 'Sales-contract UUIDs' })
        }
      />
      <ActionBar
        plotIdsCount={ids.length}
        phase={phase}
        confirm={confirm}
        onDryRun={() => mu.mutate({ dry: true })}
        onExecute={() => mu.mutate({ dry: false })}
        isPending={mu.isPending}
      />
      <BulkResultPanel result={result} sectionLabel="documents regenerate" />
    </SectionShell>
  );
}

/* ───────────── Section: leads bulk import CSV ──────────────────────── */

function LeadsImportCsvSection() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [file, setFile] = useState<File | null>(null);
  const [developmentId, setDevelopmentId] = useState('');
  const [phase, setPhase] = useState<BulkPhase>('idle');
  const [result, setResult] = useState<BulkResult | null>(null);

  const upload = async (dry: boolean): Promise<BulkResult> => {
    if (!file) throw new Error('Pick a CSV file first.');
    const formData = new FormData();
    formData.append('file', file);
    const params = new URLSearchParams();
    if (developmentId) params.set('development_id', developmentId);
    if (dry) params.set('dry_run', 'true');
    const token = localStorage.getItem('oe_access_token') || '';
    const res = await fetch(
      `/api${API_BASE}/bulk/leads/bulk-import-csv/?${params.toString()}`,
      {
        method: 'POST',
        headers: {
          Authorization: token ? `Bearer ${token}` : '',
          'X-DDC-Client': 'OE/1.0',
        },
        body: formData,
      },
    );
    if (!res.ok) {
      let detail = `Upload failed: ${res.statusText}`;
      try {
        const j = await res.json();
        if (j?.detail) detail = String(j.detail);
      } catch {
        /* fallthrough */
      }
      throw new Error(detail);
    }
    return res.json();
  };

  const mu = useMutation<BulkResult, Error, { dry: boolean }>({
    mutationFn: ({ dry }) => upload(dry),
    onSuccess: (data, vars) => {
      setResult(data);
      setPhase(vars.dry ? 'dry-run-done' : 'real-done');
      addToast({
        type: data.failed.length > 0 ? 'warning' : 'success',
        title: `Leads: ${data.succeeded}/${data.requested} ${
          vars.dry ? '(dry-run)' : 'imported'
        }`,
      });
    },
    onError: (err) => {
      addToast({ type: 'error', title: err.message });
    },
  });

  const confirm = useExecuteConfirm(0); // CSV size unknown until parsed server-side

  return (
    <SectionShell
      title={t('property_dev.bulk.import_leads_csv', { defaultValue: 'Bulk import leads from CSV' })}
      icon={<Upload size={16} />}
      desc={t('property_dev.bulk.import_leads_desc', { defaultValue: 'Headers required: full_name, email, phone, source, plot_type_interest, budget_min, budget_max, notes.' })}
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className={labelCls}>{t('property_dev.bulk.csv_file', { defaultValue: 'CSV file' })}</label>
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className={inputCls}
          />
          {file && (
            <div className="mt-1 text-xs text-content-tertiary">
              {file.name} — {Math.round(file.size / 1024)} KB
            </div>
          )}
        </div>
        <div>
          <label className={labelCls}>
            {t('property_dev.bulk.development_uuid_label', { defaultValue: 'Development UUID (optional - scopes dedupe)' })}
          </label>
          <input
            value={developmentId}
            onChange={(e) => setDevelopmentId(e.target.value)}
            className={inputCls}
            placeholder="00000000-0000-0000-0000-000000000000"
          />
        </div>
      </div>
      <ActionBar
        plotIdsCount={file ? 1 : 0}
        phase={phase}
        confirm={confirm}
        onDryRun={() => mu.mutate({ dry: true })}
        onExecute={() => mu.mutate({ dry: false })}
        isPending={mu.isPending}
        disabled={!file}
      />
      <BulkResultPanel result={result} sectionLabel="leads import csv" />
    </SectionShell>
  );
}

/* ───────────── Section: buyer merge ────────────────────────────────── */

function BuyerMergeSection() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [primaryId, setPrimaryId] = useState('');
  const [duplicatesText, setDuplicatesText] = useState('');
  const [reason, setReason] = useState('');
  const [phase, setPhase] = useState<BulkPhase>('idle');
  const [result, setResult] = useState<BulkResult | null>(null);

  const duplicates = useMemo(
    () =>
      duplicatesText
        .split(/[\s,]+/)
        .map((s) => s.trim())
        .filter((s) => s.length > 0),
    [duplicatesText],
  );
  const confirm = useExecuteConfirm(duplicates.length);

  const mu = useMutation<BulkResult, unknown, { dry: boolean }>({
    mutationFn: async ({ dry }) =>
      apiPost<BulkResult>(
        `${API_BASE}/bulk/buyers/bulk-merge/${dry ? '?dry_run=true' : ''}`,
        {
          primary_buyer_id: primaryId,
          duplicate_buyer_ids: duplicates,
          reason,
        },
      ),
    onSuccess: (data, vars) => {
      setResult(data);
      setPhase(vars.dry ? 'dry-run-done' : 'real-done');
      addToast({
        type: data.failed.length > 0 ? 'warning' : 'success',
        title: `Buyer merge: ${data.succeeded}/${data.requested} ${
          vars.dry ? '(dry-run)' : 'merged'
        }`,
      });
    },
    onError: (err) => {
      addToast({ type: 'error', title: getErrorMessage(err) });
    },
  });

  return (
    <SectionShell
      title={t('property_dev.bulk.merge_duplicate_buyers', { defaultValue: 'Bulk merge duplicate buyers' })}
      icon={<GitMerge size={16} />}
      desc={t('property_dev.bulk.merge_desc', { defaultValue: 'Re-point reservations, contracts, warranty claims from duplicates \u2192 primary, then soft-delete the duplicates. Atomic via SAVEPOINT.' })}
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className={labelCls}>{t('property_dev.bulk.primary_buyer_uuid', { defaultValue: 'Primary buyer UUID (keeper)' })}</label>
          <input
            value={primaryId}
            onChange={(e) => setPrimaryId(e.target.value)}
            className={inputCls}
            placeholder="00000000-0000-0000-0000-000000000000"
          />
        </div>
        <div>
          <label className={labelCls}>{t('property_dev.bulk.reason_label', { defaultValue: 'Reason (audit-logged)' })}</label>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className={inputCls}
            placeholder="e.g. duplicate buyer rows from web form double-submission"
            maxLength={500}
          />
        </div>
      </div>
      <PlotIdsInput
        value={duplicatesText}
        onChange={setDuplicatesText}
        plotIdsCount={duplicates.length}
        label={t('property_dev.bulk.duplicate_buyer_uuids', { defaultValue: 'Duplicate buyer UUIDs (one per line / comma-separated)' })}
      />
      <ActionBar
        plotIdsCount={duplicates.length}
        phase={phase}
        confirm={confirm}
        onDryRun={() => mu.mutate({ dry: true })}
        onExecute={() => mu.mutate({ dry: false })}
        isPending={mu.isPending}
        disabled={!primaryId || duplicates.length === 0}
      />
      <BulkResultPanel result={result} sectionLabel="buyer merge" />
    </SectionShell>
  );
}

/* ───────────── Shared subcomponents ─────────────────────────────────── */

function SectionShell({
  title,
  icon,
  desc,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  desc: string;
  children: React.ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <Card className="overflow-hidden">
      <details className="group" open>
        <summary className="cursor-pointer list-none border-b border-border-light bg-surface-secondary px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-oe-blue">{icon}</span>
            <h2 className="flex-1 text-sm font-semibold text-content-primary">
              {title}
            </h2>
            <span className="text-xs text-content-tertiary group-open:hidden">
              {t('property_dev.bulk.tap_to_expand', { defaultValue: 'tap to expand' })}
            </span>
          </div>
          <p className="mt-1 text-xs text-content-tertiary">{desc}</p>
        </summary>
        <div className="space-y-4 p-4">{children}</div>
      </details>
    </Card>
  );
}

function PlotIdsInput({
  value,
  onChange,
  plotIdsCount,
  label,
}: {
  value: string;
  onChange: (v: string) => void;
  plotIdsCount: number;
  label?: string;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <label className={labelCls}>
        {label ?? t('property_dev.bulk.plot_uuids_label', { defaultValue: 'Plot UUIDs (one per line / comma-separated)' })}{' '}
        <span
          className={
            plotIdsCount > BULK_MAX_ITEMS
              ? 'font-mono text-red-600'
              : 'font-mono text-content-tertiary'
          }
        >
          {plotIdsCount}/{BULK_MAX_ITEMS}
        </span>
      </label>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={4}
        className={`${inputCls} h-auto font-mono text-xs`}
        placeholder="e.g.&#10;00000000-0000-0000-0000-000000000001&#10;00000000-0000-0000-0000-000000000002"
      />
      {plotIdsCount > BULK_MAX_ITEMS && (
        <div className="mt-1 text-xs text-red-600">
          <AlertTriangle size={12} className="mr-1 inline" />
          {t('property_dev.bulk.over_cap', { defaultValue: 'Over the {{max}}-item cap - server will return 422.', max: BULK_MAX_ITEMS })}
        </div>
      )}
    </div>
  );
}

function ActionBar({
  plotIdsCount,
  phase,
  confirm,
  onDryRun,
  onExecute,
  isPending,
  disabled = false,
}: {
  plotIdsCount: number;
  phase: BulkPhase;
  confirm: ReturnType<typeof useExecuteConfirm>;
  onDryRun: () => void;
  onExecute: () => void;
  isPending: boolean;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="secondary"
          onClick={onDryRun}
          disabled={isPending || plotIdsCount === 0 || disabled}
        >
          {t('property_dev.bulk.dry_run_button', { defaultValue: '1. Dry run (preview)' })}
        </Button>
        <Button
          variant="danger"
          onClick={onExecute}
          disabled={
            isPending ||
            plotIdsCount === 0 ||
            disabled ||
            phase === 'idle' ||
            !confirm.canExecute
          }
        >
          {t('property_dev.bulk.execute_button', { defaultValue: '2. Execute for real' })}
        </Button>
        {phase !== 'idle' && (
          <span className="text-xs text-content-tertiary">
            {phase === 'dry-run-done'
              ? t('property_dev.bulk.dry_run_complete', { defaultValue: 'Dry run complete - review below before executing' })
              : t('property_dev.bulk.live_run_complete', { defaultValue: 'Live run complete' })}
          </span>
        )}
      </div>
      {confirm.needsTypedConfirm && phase === 'dry-run-done' && (
        <div className="rounded-lg border border-red-300 bg-red-50 p-3 text-xs text-red-900 dark:border-red-700 dark:bg-red-900/30 dark:text-red-200">
          <AlertTriangle size={12} className="mr-1 inline" />
          {t('property_dev.bulk.typed_confirm', { defaultValue: '{{count}} items selected - type', count: plotIdsCount })}{' '}
          <code className="rounded bg-white px-1 font-bold dark:bg-surface-primary">
            EXECUTE
          </code>{' '}
          {t('property_dev.bulk.to_confirm', { defaultValue: 'to confirm:' })}
          <input
            value={confirm.confirmText}
            onChange={(e) => confirm.setConfirmText(e.target.value)}
            className={`${inputCls} mt-2 max-w-xs`}
            placeholder="EXECUTE"
          />
        </div>
      )}
      {isPending && (
        <div className="h-1 w-full overflow-hidden rounded bg-border-light">
          <div className="h-full w-1/3 animate-pulse bg-oe-blue" />
        </div>
      )}
    </div>
  );
}

/* ───────────── Page shell ───────────────────────────────────────────── */

export function BulkOperationsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const userRole = useAuthStore((s) => s.userRole);
  const isManagerPlus = useMemo(
    () => (userRole ? MANAGER_PLUS.has(userRole.toLowerCase()) : false),
    [userRole],
  );

  const breadcrumb = (
    <Breadcrumb
      items={[
        {
          label: t('propdev.title', { defaultValue: 'Property Development' }),
          to: '/property-dev',
        },
        {
          label: t('propdev.bulk_ops.title', {
            defaultValue: 'Bulk operations',
          }),
        },
      ]}
    />
  );

  if (!isManagerPlus) {
    return (
      <div className="space-y-5 animate-fade-in">
        {breadcrumb}
        <Card className="p-6">
          <EmptyState
            title={t('propdev.bulk_ops.not_authorized_title', {
              defaultValue: 'Not authorized',
            })}
            description={t('propdev.bulk_ops.not_authorized_desc', {
              defaultValue:
                'Bulk operations are MANAGER+ only. Contact your workspace admin if you need access.',
            })}
          />
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-5 animate-fade-in">
      {breadcrumb}
      <PageHeader
        srTitle={t('propdev.bulk_ops.heading', {
          defaultValue: 'Bulk operations console',
        })}
        subtitle={t('propdev.bulk_ops.subtitle', {
          defaultValue:
            'Manager-only batch actions across plots, reservations, documents, leads and buyers.',
        })}
      />
      <DismissibleInfo
        storageKey="propdev-bulk-operations"
        title={t('propdev_bulk_ops.intro_title', {
          defaultValue: 'Move many records safely at once',
        })}
        more={t('propdev_bulk_ops.intro_more', { defaultValue: '' }) ? <IntroRichText text={t('propdev_bulk_ops.intro_more')} /> : undefined}
        links={[
          {
            label: t('propdev.title', { defaultValue: 'Property Development' }),
            onClick: () => navigate('/property-dev'),
          },
        ]}
      >
        {t('propdev_bulk_ops.intro_body', {
          defaultValue:
            'Manager-only batch actions across plots, reservations, documents, leads and buyers, where every run is dry-run first, then review, then execute. Each batch is one atomic transaction that rolls back fully on failure, so a large change to the development never leaves it half-applied.',
        })}
      </DismissibleInfo>

      <PlotStatusChangeSection />
      <ReservationExtendExpirySection />
      <DocumentsRegenerateSection />
      <LeadsImportCsvSection />
      <BuyerMergeSection />
    </div>
  );
}
