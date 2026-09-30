// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Upload,
  Plus,
  FileText,
  Loader2,
  ShieldCheck,
  ShieldAlert,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Download,
  History,
  Sparkles,
  Info,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, SkeletonTable } from '@/shared/ui';
import { WideModal } from '@/shared/ui/WideModal';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import {
  apiGet,
  apiPost,
  apiPatch,
  API_BASE,
  getAuthToken,
  extractErrorMessageFromBody,
  downloadWithAuth,
} from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';

/* ── Types ─────────────────────────────────────────────────────────────── */

type CaptureStatus = 'captured' | 'coded' | 'approved' | 'posted' | 'rejected' | 'queried';

interface ValidationFinding {
  severity: string;
  code: string;
  message: string;
  field: string | null;
}

interface BookingProposal {
  expense_account: string | null;
  tax_account: string | null;
  payable_account: string | null;
  cost_code: string | null;
  confidence: number;
  rationale: string[];
}

interface Capture {
  id: string;
  project_id: string;
  status: CaptureStatus;
  doc_kind: string;
  original_filename: string;
  has_document: boolean;
  supplier_name: string;
  supplier_tax_id: string | null;
  invoice_number: string;
  invoice_date: string;
  due_date: string | null;
  currency_code: string;
  amount_net: string;
  amount_tax: string;
  amount_gross: string;
  line_items: Array<Record<string, unknown>>;
  extraction_engine: string;
  field_confidence: Record<string, number>;
  booking_expense_account: string | null;
  booking_tax_account: string | null;
  booking_payable_account: string | null;
  booking_cost_code: string | null;
  approver_id: string | null;
  approved_at: string | null;
  rejected_reason: string | null;
  queried_note: string | null;
  posted_at: string | null;
  posted_transaction_ref: string | null;
  archive_hash: string | null;
  retention_until: string | null;
  created_at: string;
  updated_at: string;
  validation: ValidationFinding[];
  booking_proposal: BookingProposal | null;
}

interface LedgerAccount {
  account_code: string;
  name: string;
  account_type: string;
}

/** The string-valued capture fields the review form can edit inline. */
type EditableField =
  | 'supplier_name'
  | 'supplier_tax_id'
  | 'invoice_number'
  | 'invoice_date'
  | 'due_date'
  | 'currency_code'
  | 'amount_net'
  | 'amount_tax'
  | 'amount_gross';

interface ArchiveVerify {
  sealed: boolean;
  document_present: boolean;
  document_intact: boolean | null;
  booking_intact: boolean;
  overall_intact: boolean;
  message: string;
}

interface AuditEntry {
  action: string;
  from_status: string | null;
  to_status: string | null;
  reason: string | null;
  actor_id: string | null;
  created_at: string;
}

/* ── Constants ─────────────────────────────────────────────────────────── */

const CAPTURE_STATUS_COLORS: Record<CaptureStatus, 'neutral' | 'blue' | 'success' | 'warning' | 'error'> = {
  captured: 'neutral',
  coded: 'blue',
  approved: 'warning',
  posted: 'success',
  rejected: 'error',
  queried: 'warning',
};

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const labelCls = 'block text-xs font-medium text-text-secondary mb-1';

/* ── Confidence pill ───────────────────────────────────────────────────── */

function ConfidencePill({ score }: { score?: number }) {
  if (score == null) return null;
  const pct = Math.round(score * 100);
  const variant = score >= 0.7 ? 'success' : score >= 0.4 ? 'warning' : 'neutral';
  return (
    <Badge variant={variant} size="sm">
      {pct}%
    </Badge>
  );
}

/* ── Tab ───────────────────────────────────────────────────────────────── */

export function InvoiceInboxTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const fileRef = useRef<HTMLInputElement>(null);

  const [statusFilter, setStatusFilter] = useState<string>('');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const listQuery = useQuery({
    queryKey: ['finance-invoice-inbox', projectId, statusFilter],
    queryFn: () =>
      apiGet<{ items: Capture[]; total: number }>(
        `/v1/finance/inbox?project_id=${encodeURIComponent(projectId)}` +
          (statusFilter ? `&status=${encodeURIComponent(statusFilter)}` : ''),
      ),
  });

  const accountsQuery = useQuery({
    queryKey: ['finance-gl-accounts', projectId],
    queryFn: () =>
      apiGet<{ items: LedgerAccount[]; total: number }>(
        `/v1/finance/gaap/accounts?project_id=${encodeURIComponent(projectId)}&active_only=true`,
      ),
  });

  const captures = listQuery.data?.items ?? [];
  const accounts = accountsQuery.data?.items ?? [];

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['finance-invoice-inbox', projectId] });
    if (selectedId) queryClient.invalidateQueries({ queryKey: ['finance-invoice-inbox-item', selectedId] });
    queryClient.invalidateQueries({ queryKey: ['finance-invoices', projectId] });
    queryClient.invalidateQueries({ queryKey: ['finance', 'dashboard', projectId] });
  };

  const uploadMut = useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData();
      fd.append('file', file);
      const res = await fetch(
        `${API_BASE}/v1/finance/inbox/upload?project_id=${encodeURIComponent(projectId)}`,
        {
          method: 'POST',
          headers: { Authorization: `Bearer ${getAuthToken() ?? ''}` },
          body: fd,
        },
      );
      if (!res.ok) {
        let detail = t('finance.inbox.upload_failed', { defaultValue: 'Upload failed' });
        try {
          detail = extractErrorMessageFromBody(await res.json()) ?? detail;
        } catch {
          /* keep default */
        }
        throw new Error(detail);
      }
      return (await res.json()) as Capture;
    },
    onSuccess: (row) => {
      invalidateAll();
      setSelectedId(row.id);
      addToast({
        type: 'success',
        title: t('finance.inbox.captured', { defaultValue: 'Invoice captured for review' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('finance.inbox.upload_failed', { defaultValue: 'Upload failed' }),
        message: e.message,
      }),
  });

  const manualMut = useMutation({
    mutationFn: () =>
      apiPost<Capture>('/v1/finance/inbox/manual', { project_id: projectId, doc_kind: 'invoice' }),
    onSuccess: (row) => {
      invalidateAll();
      setSelectedId(row.id);
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const onPickFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadMut.mutate(file);
    if (fileRef.current) fileRef.current.value = '';
  };

  const statusOptions: Array<{ value: string; label: string }> = [
    { value: '', label: t('finance.inbox.filter_all', { defaultValue: 'All statuses' }) },
    { value: 'captured', label: t('finance.inbox.status_captured', { defaultValue: 'Captured' }) },
    { value: 'coded', label: t('finance.inbox.status_coded', { defaultValue: 'Coded' }) },
    { value: 'approved', label: t('finance.inbox.status_approved', { defaultValue: 'Approved' }) },
    { value: 'posted', label: t('finance.inbox.status_posted', { defaultValue: 'Posted' }) },
    { value: 'queried', label: t('finance.inbox.status_queried', { defaultValue: 'Queried' }) },
    { value: 'rejected', label: t('finance.inbox.status_rejected', { defaultValue: 'Rejected' }) },
  ];

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-base font-semibold text-text-primary">
              {t('finance.inbox.title', { defaultValue: 'Invoice inbox' })}
            </h3>
            <p className="mt-0.5 max-w-2xl text-sm text-text-secondary">
              {t('finance.inbox.subtitle', {
                defaultValue:
                  'Capture a supplier invoice or delivery note, review the read-out fields, confirm the booking, route it for approval, and post it to the ledger. The original is archived unaltered with a tamper-evident seal.',
              })}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,image/*"
              className="hidden"
              onChange={onPickFile}
            />
            <Button variant="secondary" onClick={() => manualMut.mutate()} disabled={manualMut.isPending}>
              <Plus size={15} />
              {t('finance.inbox.add_manual', { defaultValue: 'Add manually' })}
            </Button>
            <Button onClick={() => fileRef.current?.click()} disabled={uploadMut.isPending}>
              {uploadMut.isPending ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />}
              {t('finance.inbox.upload', { defaultValue: 'Upload invoice' })}
            </Button>
          </div>
        </div>
      </Card>

      <div className="flex items-center gap-2">
        <label className="text-sm text-text-secondary">
          {t('finance.inbox.filter_label', { defaultValue: 'Show' })}
        </label>
        <select
          className={`${inputCls} w-56`}
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          {statusOptions.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      {listQuery.isLoading ? (
        <SkeletonTable rows={5} />
      ) : captures.length === 0 ? (
        <EmptyState
          icon={<FileText size={28} />}
          title={t('finance.inbox.empty_title', { defaultValue: 'No captured invoices yet' })}
          description={t('finance.inbox.empty_desc', {
            defaultValue: 'Upload a supplier invoice PDF or image to get started. Manual entry also works.',
          })}
          action={{
            label: t('finance.inbox.upload', { defaultValue: 'Upload invoice' }),
            onClick: () => fileRef.current?.click(),
          }}
        />
      ) : (
        <Card className="overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-secondary">
                  <th className="px-4 py-3 font-medium">
                    {t('finance.inbox.col_supplier', { defaultValue: 'Supplier' })}
                  </th>
                  <th className="px-4 py-3 font-medium">
                    {t('finance.inbox.col_number', { defaultValue: 'Invoice #' })}
                  </th>
                  <th className="px-4 py-3 font-medium">
                    {t('finance.inbox.col_date', { defaultValue: 'Date' })}
                  </th>
                  <th className="px-4 py-3 text-right font-medium">
                    {t('finance.inbox.col_gross', { defaultValue: 'Gross' })}
                  </th>
                  <th className="px-4 py-3 font-medium">
                    {t('finance.inbox.col_status', { defaultValue: 'Status' })}
                  </th>
                  <th className="px-4 py-3 font-medium" />
                </tr>
              </thead>
              <tbody>
                {captures.map((c) => (
                  <tr
                    key={c.id}
                    className="cursor-pointer border-b border-border/60 last:border-0 hover:bg-surface-secondary/50"
                    onClick={() => setSelectedId(c.id)}
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium text-text-primary">
                        {c.supplier_name || t('finance.inbox.unknown_supplier', { defaultValue: 'Unknown supplier' })}
                      </div>
                      {c.has_document && (
                        <div className="text-xs text-text-secondary">{c.original_filename}</div>
                      )}
                    </td>
                    <td className="px-4 py-3 text-text-secondary">
                      {c.invoice_number || <span className="text-text-tertiary">-</span>}
                    </td>
                    <td className="px-4 py-3 text-text-secondary">
                      {c.invoice_date ? <DateDisplay value={c.invoice_date} /> : '-'}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <MoneyDisplay amount={c.amount_gross} currency={c.currency_code || 'EUR'} />
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={CAPTURE_STATUS_COLORS[c.status] ?? 'neutral'} size="sm">
                        {t(`finance.inbox.status_${c.status}`, { defaultValue: c.status })}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Button variant="ghost" size="sm" onClick={() => setSelectedId(c.id)}>
                        {t('finance.inbox.review', { defaultValue: 'Review' })}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {selectedId && (
        <CaptureDetail
          captureId={selectedId}
          projectId={projectId}
          accounts={accounts}
          onClose={() => setSelectedId(null)}
          onChanged={invalidateAll}
        />
      )}
    </div>
  );
}

/* ── Detail modal ──────────────────────────────────────────────────────── */

function CaptureDetail({
  captureId,
  accounts,
  onClose,
  onChanged,
}: {
  captureId: string;
  // projectId is provided by the caller for future project-scoped actions; not needed yet.
  projectId?: string;
  accounts: LedgerAccount[];
  onClose: () => void;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const itemQuery = useQuery({
    queryKey: ['finance-invoice-inbox-item', captureId],
    queryFn: () => apiGet<Capture>(`/v1/finance/inbox/${captureId}`),
  });
  const auditQuery = useQuery({
    queryKey: ['finance-invoice-inbox-audit', captureId],
    queryFn: () => apiGet<{ items: AuditEntry[]; total: number }>(`/v1/finance/inbox/${captureId}/audit`),
  });

  const capture = itemQuery.data;
  const editable = capture ? ['captured', 'coded', 'queried', 'rejected'].includes(capture.status) : false;

  // Local draft for editable fields; seeded from the loaded capture.
  const [draft, setDraft] = useState<Partial<Capture> | null>(null);
  const [booking, setBooking] = useState<{
    expense_account: string;
    payable_account: string;
    tax_account: string;
    cost_code: string;
  } | null>(null);
  const [verify, setVerify] = useState<ArchiveVerify | null>(null);
  const [rejectReason, setRejectReason] = useState('');
  const [queryNote, setQueryNote] = useState('');

  // Seed the local form once the capture loads or changes identity.
  const seededFor = useRef<string | null>(null);
  if (capture && seededFor.current !== capture.id) {
    seededFor.current = capture.id;
    setDraft({
      supplier_name: capture.supplier_name,
      supplier_tax_id: capture.supplier_tax_id,
      invoice_number: capture.invoice_number,
      invoice_date: capture.invoice_date,
      due_date: capture.due_date,
      currency_code: capture.currency_code,
      amount_net: capture.amount_net,
      amount_tax: capture.amount_tax,
      amount_gross: capture.amount_gross,
    });
    const p = capture.booking_proposal;
    setBooking({
      expense_account: capture.booking_expense_account ?? p?.expense_account ?? '',
      payable_account: capture.booking_payable_account ?? p?.payable_account ?? '',
      tax_account: capture.booking_tax_account ?? p?.tax_account ?? '',
      cost_code: capture.booking_cost_code ?? p?.cost_code ?? '',
    });
    setVerify(null);
  }

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['finance-invoice-inbox-item', captureId] });
    queryClient.invalidateQueries({ queryKey: ['finance-invoice-inbox-audit', captureId] });
    onChanged();
  };

  const saveMut = useMutation({
    mutationFn: (body: Record<string, unknown>) => apiPatch<Capture>(`/v1/finance/inbox/${captureId}`, body),
    onSuccess: () => {
      refresh();
      addToast({ type: 'success', title: t('finance.inbox.saved', { defaultValue: 'Draft saved' }) });
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const actionMut = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: Record<string, unknown> }) =>
      apiPost<Capture>(`/v1/finance/inbox/${captureId}/${path}`, body),
    onSuccess: (_row, vars) => {
      refresh();
      addToast({
        type: 'success',
        title: t(`finance.inbox.action_${vars.path}_ok`, {
          defaultValue: t('finance.inbox.action_done', { defaultValue: 'Done' }),
        }),
      });
    },
    onError: (e: Error) =>
      addToast({ type: 'error', title: t('finance.inbox.action_failed', { defaultValue: 'Action failed' }), message: e.message }),
  });

  const enrichMut = useMutation({
    mutationFn: () => apiPost<Capture>(`/v1/finance/inbox/${captureId}/enrich`),
    onSuccess: () => {
      seededFor.current = null; // re-seed the form from enriched values
      refresh();
      addToast({ type: 'success', title: t('finance.inbox.enriched', { defaultValue: 'AI enrichment applied' }) });
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const verifyMut = useMutation({
    mutationFn: () => apiGet<ArchiveVerify>(`/v1/finance/inbox/${captureId}/verify`),
    onSuccess: (res) => setVerify(res),
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const setField = (key: EditableField, value: string) =>
    setDraft((d) => ({ ...(d ?? {}), [key]: value }));

  const saveDraft = () => {
    if (!draft) return;
    saveMut.mutate({
      supplier_name: draft.supplier_name ?? '',
      supplier_tax_id: draft.supplier_tax_id ?? null,
      invoice_number: draft.invoice_number ?? '',
      invoice_date: draft.invoice_date ?? '',
      due_date: draft.due_date || null,
      currency_code: draft.currency_code ?? '',
      amount_net: draft.amount_net ?? '0',
      amount_tax: draft.amount_tax ?? '0',
      amount_gross: draft.amount_gross ?? '0',
    });
  };

  const doCode = () => {
    if (!booking) return;
    if (!booking.expense_account || !booking.payable_account) {
      addToast({
        type: 'warning',
        title: t('finance.inbox.need_accounts', {
          defaultValue: 'Choose an expense account and a payable account first.',
        }),
      });
      return;
    }
    actionMut.mutate({
      path: 'code',
      body: {
        expense_account: booking.expense_account,
        payable_account: booking.payable_account,
        tax_account: booking.tax_account || null,
        cost_code: booking.cost_code || null,
      },
    });
  };

  const expenseAccounts = useMemo(() => accounts.filter((a) => a.account_type === 'expense'), [accounts]);
  const payableAccounts = useMemo(() => accounts.filter((a) => a.account_type === 'liability'), [accounts]);
  const taxAccounts = useMemo(
    () => accounts.filter((a) => a.account_type === 'liability' || a.account_type === 'asset'),
    [accounts],
  );

  const status = capture?.status;
  const errors = (capture?.validation ?? []).filter((f) => f.severity === 'error');
  const warnings = (capture?.validation ?? []).filter((f) => f.severity === 'warning');

  const footer = (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex flex-wrap items-center gap-2">
        {capture?.has_document && (
          <button
            type="button"
            // The document route reads only the bearer header, which a plain link never sends.
            onClick={() =>
              downloadWithAuth(`${API_BASE}/v1/finance/inbox/${captureId}/document`, 'invoice').catch((e: Error) =>
                addToast({ type: 'error', title: t('common.download_failed', { defaultValue: 'Download failed' }), message: e.message }),
              )
            }
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-sm text-text-secondary hover:bg-surface-secondary"
          >
            <Download size={15} />
            {t('finance.inbox.view_original', { defaultValue: 'Original' })}
          </button>
        )}
        {status === 'posted' && (
          <Button variant="secondary" onClick={() => verifyMut.mutate()} disabled={verifyMut.isPending}>
            {verifyMut.isPending ? <Loader2 size={15} className="animate-spin" /> : <ShieldCheck size={15} />}
            {t('finance.inbox.verify', { defaultValue: 'Verify archive' })}
          </Button>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {editable && (
          <Button variant="secondary" onClick={saveDraft} disabled={saveMut.isPending}>
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        )}
        {(status === 'captured' || status === 'coded' || status === 'queried') && (
          <Button onClick={doCode} disabled={actionMut.isPending}>
            {t('finance.inbox.confirm_booking', { defaultValue: 'Confirm booking' })}
          </Button>
        )}
        {status === 'coded' && (
          <Button onClick={() => actionMut.mutate({ path: 'approve' })} disabled={actionMut.isPending}>
            <CheckCircle2 size={15} />
            {t('finance.inbox.approve', { defaultValue: 'Approve' })}
          </Button>
        )}
        {status === 'approved' && (
          <Button onClick={() => actionMut.mutate({ path: 'post' })} disabled={actionMut.isPending}>
            {t('finance.inbox.post', { defaultValue: 'Post to ledger' })}
          </Button>
        )}
        {(status === 'queried' || status === 'rejected' || status === 'coded') && (
          <Button variant="secondary" onClick={() => actionMut.mutate({ path: 'reopen' })} disabled={actionMut.isPending}>
            {t('finance.inbox.reopen', { defaultValue: 'Reopen' })}
          </Button>
        )}
      </div>
    </div>
  );

  return (
    <WideModal
      open
      onClose={onClose}
      size="2xl"
      title={
        capture
          ? capture.supplier_name || t('finance.inbox.review_title', { defaultValue: 'Review invoice' })
          : t('finance.inbox.review_title', { defaultValue: 'Review invoice' })
      }
      subtitle={
        capture ? (
          <span className="inline-flex items-center gap-2">
            <Badge variant={CAPTURE_STATUS_COLORS[capture.status] ?? 'neutral'} size="sm">
              {t(`finance.inbox.status_${capture.status}`, { defaultValue: capture.status })}
            </Badge>
            <span className="text-xs text-text-secondary">
              {t('finance.inbox.read_by', { defaultValue: 'Read by' })}: {capture.extraction_engine}
            </span>
          </span>
        ) : undefined
      }
      footer={footer}
      busy={actionMut.isPending || saveMut.isPending}
    >
      {itemQuery.isLoading || !capture || !draft ? (
        <div className="flex items-center justify-center py-16 text-text-secondary">
          <Loader2 className="animate-spin" />
        </div>
      ) : (
        <div className="space-y-5">
          {/* Validation banner */}
          {(errors.length > 0 || warnings.length > 0) && (
            <div className="space-y-1.5">
              {errors.map((f) => (
                <div key={f.code} className="flex items-start gap-2 rounded-lg bg-error/10 px-3 py-2 text-sm text-error">
                  <XCircle size={15} className="mt-0.5 shrink-0" />
                  <span>{f.message}</span>
                </div>
              ))}
              {warnings.map((f) => (
                <div
                  key={f.code}
                  className="flex items-start gap-2 rounded-lg bg-warning/10 px-3 py-2 text-sm text-warning-strong"
                >
                  <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                  <span>{f.message}</span>
                </div>
              ))}
            </div>
          )}
          {errors.length === 0 && warnings.length === 0 && status !== 'posted' && (
            <div className="flex items-center gap-2 rounded-lg bg-success/10 px-3 py-2 text-sm text-success">
              <CheckCircle2 size={15} />
              {t('finance.inbox.checks_pass', { defaultValue: 'All checks pass.' })}
            </div>
          )}

          {/* Extracted / reviewed fields */}
          <section>
            <div className="mb-2 flex items-center justify-between">
              <h4 className="text-sm font-semibold text-text-primary">
                {t('finance.inbox.fields', { defaultValue: 'Invoice fields' })}
              </h4>
              {editable && (
                <Button variant="ghost" size="sm" onClick={() => enrichMut.mutate()} disabled={enrichMut.isPending}>
                  {enrichMut.isPending ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
                  {t('finance.inbox.ai_fill', { defaultValue: 'AI fill blanks' })}
                </Button>
              )}
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Field
                label={t('finance.inbox.supplier', { defaultValue: 'Supplier' })}
                conf={capture.field_confidence?.['supplier_name']}
              >
                <input
                  className={inputCls}
                  disabled={!editable}
                  value={draft.supplier_name ?? ''}
                  onChange={(e) => setField('supplier_name', e.target.value)}
                />
              </Field>
              <Field
                label={t('finance.inbox.tax_id', { defaultValue: 'Supplier tax ID' })}
                conf={capture.field_confidence?.['supplier_tax_id']}
              >
                <input
                  className={inputCls}
                  disabled={!editable}
                  value={draft.supplier_tax_id ?? ''}
                  onChange={(e) => setField('supplier_tax_id', e.target.value)}
                />
              </Field>
              <Field
                label={t('finance.inbox.number', { defaultValue: 'Invoice number' })}
                conf={capture.field_confidence?.['invoice_number']}
              >
                <input
                  className={inputCls}
                  disabled={!editable}
                  value={draft.invoice_number ?? ''}
                  onChange={(e) => setField('invoice_number', e.target.value)}
                />
              </Field>
              <Field
                label={t('finance.inbox.date', { defaultValue: 'Invoice date' })}
                conf={capture.field_confidence?.['invoice_date']}
              >
                <input
                  type="date"
                  className={inputCls}
                  disabled={!editable}
                  value={draft.invoice_date ?? ''}
                  onChange={(e) => setField('invoice_date', e.target.value)}
                />
              </Field>
              <Field label={t('finance.inbox.due_date', { defaultValue: 'Due date' })}>
                <input
                  type="date"
                  className={inputCls}
                  disabled={!editable}
                  value={draft.due_date ?? ''}
                  onChange={(e) => setField('due_date', e.target.value)}
                />
              </Field>
              <Field label={t('finance.inbox.currency', { defaultValue: 'Currency' })}>
                <input
                  className={inputCls}
                  disabled={!editable}
                  maxLength={10}
                  value={draft.currency_code ?? ''}
                  onChange={(e) => setField('currency_code', e.target.value.toUpperCase())}
                />
              </Field>
              <Field
                label={t('finance.inbox.net', { defaultValue: 'Net' })}
                conf={capture.field_confidence?.['amount_net']}
              >
                <input
                  className={inputCls}
                  disabled={!editable}
                  inputMode="decimal"
                  value={draft.amount_net ?? '0'}
                  onChange={(e) => setField('amount_net', e.target.value)}
                />
              </Field>
              <Field
                label={t('finance.inbox.tax', { defaultValue: 'Tax' })}
                conf={capture.field_confidence?.['amount_tax']}
              >
                <input
                  className={inputCls}
                  disabled={!editable}
                  inputMode="decimal"
                  value={draft.amount_tax ?? '0'}
                  onChange={(e) => setField('amount_tax', e.target.value)}
                />
              </Field>
              <Field
                label={t('finance.inbox.gross', { defaultValue: 'Gross (total)' })}
                conf={capture.field_confidence?.['amount_gross']}
              >
                <input
                  className={inputCls}
                  disabled={!editable}
                  inputMode="decimal"
                  value={draft.amount_gross ?? '0'}
                  onChange={(e) => setField('amount_gross', e.target.value)}
                />
              </Field>
            </div>
          </section>

          {/* Booking */}
          {status !== 'posted' ? (
            <section>
              <div className="mb-2 flex items-center gap-2">
                <h4 className="text-sm font-semibold text-text-primary">
                  {t('finance.inbox.booking', { defaultValue: 'Booking proposal' })}
                </h4>
                {capture.booking_proposal && (
                  <ConfidencePill score={capture.booking_proposal.confidence} />
                )}
              </div>
              {capture.booking_proposal?.rationale?.length ? (
                <ul className="mb-3 space-y-1 text-xs text-text-secondary">
                  {capture.booking_proposal.rationale.map((r, i) => (
                    <li key={i} className="flex items-start gap-1.5">
                      <Info size={13} className="mt-0.5 shrink-0 text-oe-blue" />
                      {r}
                    </li>
                  ))}
                </ul>
              ) : null}
              {booking && (
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <Field label={t('finance.inbox.expense_account', { defaultValue: 'Expense / cost account (Dr)' })}>
                    <AccountSelect
                      value={booking.expense_account}
                      onChange={(v) => setBooking((b) => (b ? { ...b, expense_account: v } : b))}
                      options={expenseAccounts}
                      disabled={!editable}
                    />
                  </Field>
                  <Field label={t('finance.inbox.payable_account', { defaultValue: 'Accounts payable (Cr)' })}>
                    <AccountSelect
                      value={booking.payable_account}
                      onChange={(v) => setBooking((b) => (b ? { ...b, payable_account: v } : b))}
                      options={payableAccounts}
                      disabled={!editable}
                    />
                  </Field>
                  <Field label={t('finance.inbox.tax_account', { defaultValue: 'Tax account (Dr, optional)' })}>
                    <AccountSelect
                      value={booking.tax_account}
                      onChange={(v) => setBooking((b) => (b ? { ...b, tax_account: v } : b))}
                      options={taxAccounts}
                      disabled={!editable}
                      allowEmpty
                    />
                  </Field>
                  <Field label={t('finance.inbox.cost_code', { defaultValue: 'Cost code (optional)' })}>
                    <input
                      className={inputCls}
                      disabled={!editable}
                      value={booking.cost_code}
                      onChange={(e) => setBooking((b) => (b ? { ...b, cost_code: e.target.value } : b))}
                    />
                  </Field>
                </div>
              )}
              {accounts.length === 0 && (
                <p className="mt-2 text-xs text-warning-strong">
                  {t('finance.inbox.seed_chart', {
                    defaultValue:
                      'No chart of accounts is seeded yet. Seed the default chart in the GL settings to enable posting.',
                  })}
                </p>
              )}
            </section>
          ) : (
            <PostedArchivePanel capture={capture} verify={verify} />
          )}

          {/* Send-back actions for reviewers */}
          {status && ['captured', 'coded', 'queried', 'approved'].includes(status) && (
            <section className="rounded-lg border border-border p-3">
              <h4 className="mb-2 text-sm font-semibold text-text-primary">
                {t('finance.inbox.decision', { defaultValue: 'Reject or query' })}
              </h4>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className={labelCls}>{t('finance.inbox.query_note', { defaultValue: 'Query note' })}</label>
                  <div className="flex gap-2">
                    <input
                      className={inputCls}
                      value={queryNote}
                      onChange={(e) => setQueryNote(e.target.value)}
                      placeholder={t('finance.inbox.query_ph', { defaultValue: 'Ask the submitter for more info' })}
                    />
                    <Button
                      variant="secondary"
                      onClick={() => queryNote.trim() && actionMut.mutate({ path: 'query', body: { note: queryNote } })}
                      disabled={!queryNote.trim() || actionMut.isPending}
                    >
                      {t('finance.inbox.send_query', { defaultValue: 'Query' })}
                    </Button>
                  </div>
                </div>
                <div>
                  <label className={labelCls}>{t('finance.inbox.reject_reason', { defaultValue: 'Reject reason' })}</label>
                  <div className="flex gap-2">
                    <input
                      className={inputCls}
                      value={rejectReason}
                      onChange={(e) => setRejectReason(e.target.value)}
                      placeholder={t('finance.inbox.reject_ph', { defaultValue: 'Why is this declined?' })}
                    />
                    <Button
                      variant="danger"
                      onClick={() =>
                        rejectReason.trim() && actionMut.mutate({ path: 'reject', body: { reason: rejectReason } })
                      }
                      disabled={!rejectReason.trim() || actionMut.isPending}
                    >
                      {t('finance.inbox.reject', { defaultValue: 'Reject' })}
                    </Button>
                  </div>
                </div>
              </div>
            </section>
          )}

          {/* Audit trail */}
          <section>
            <h4 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-text-primary">
              <History size={15} />
              {t('finance.inbox.audit', { defaultValue: 'Audit trail' })}
            </h4>
            <div className="space-y-1.5">
              {(auditQuery.data?.items ?? []).map((a, i) => (
                <div key={i} className="flex items-center justify-between rounded-md bg-surface-secondary/50 px-3 py-1.5 text-xs">
                  <span className="text-text-primary">
                    {t(`finance.inbox.event_${a.action}`, { defaultValue: a.action })}
                    {a.to_status ? ` -> ${a.to_status}` : ''}
                    {a.reason ? ` (${a.reason})` : ''}
                  </span>
                  <span className="text-text-secondary">
                    <DateDisplay value={a.created_at} format="datetime" />
                  </span>
                </div>
              ))}
              {(auditQuery.data?.items?.length ?? 0) === 0 && (
                <p className="text-xs text-text-secondary">
                  {t('finance.inbox.no_audit', { defaultValue: 'No actions recorded yet.' })}
                </p>
              )}
            </div>
          </section>
        </div>
      )}
    </WideModal>
  );
}

/* ── Small helpers ─────────────────────────────────────────────────────── */

function Field({
  label,
  conf,
  children,
}: {
  label: string;
  conf?: number;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <label className="text-xs font-medium text-text-secondary">{label}</label>
        <ConfidencePill score={conf} />
      </div>
      {children}
    </div>
  );
}

function AccountSelect({
  value,
  onChange,
  options,
  disabled,
  allowEmpty,
}: {
  value: string;
  onChange: (v: string) => void;
  options: LedgerAccount[];
  disabled?: boolean;
  allowEmpty?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <select className={inputCls} value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
      <option value="">
        {allowEmpty
          ? t('finance.inbox.no_account', { defaultValue: 'None' })
          : t('finance.inbox.select_account', { defaultValue: 'Select an account' })}
      </option>
      {options.map((a) => (
        <option key={a.account_code} value={a.account_code}>
          {a.account_code} - {a.name}
        </option>
      ))}
    </select>
  );
}

function PostedArchivePanel({
  capture,
  verify,
}: {
  capture: Capture;
  verify: ArchiveVerify | null;
}) {
  const { t } = useTranslation();
  return (
    <section className="rounded-lg border border-success/40 bg-success/5 p-4">
      <div className="mb-2 flex items-center gap-2">
        <ShieldCheck size={16} className="text-success" />
        <h4 className="text-sm font-semibold text-text-primary">
          {t('finance.inbox.archived', { defaultValue: 'Posted and archived' })}
        </h4>
      </div>
      <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
        <Row label={t('finance.inbox.gl_ref', { defaultValue: 'Ledger reference' })} value={capture.posted_transaction_ref} />
        <Row label={t('finance.inbox.posted_at', { defaultValue: 'Posted at' })} value={capture.posted_at} />
        <Row
          label={t('finance.inbox.retention', { defaultValue: 'Retain until' })}
          value={capture.retention_until}
        />
        <Row
          label={t('finance.inbox.seal', { defaultValue: 'Archive seal (sha256)' })}
          value={capture.archive_hash ? `${capture.archive_hash.slice(0, 16)}…` : null}
          mono
        />
      </dl>
      {verify && (
        <div
          className={`mt-3 flex items-start gap-2 rounded-md px-3 py-2 text-sm ${
            verify.overall_intact ? 'bg-success/10 text-success' : 'bg-error/10 text-error'
          }`}
        >
          {verify.overall_intact ? (
            <ShieldCheck size={15} className="mt-0.5 shrink-0" />
          ) : (
            <ShieldAlert size={15} className="mt-0.5 shrink-0" />
          )}
          <span>{verify.message}</span>
        </div>
      )}
    </section>
  );
}

function Row({ label, value, mono }: { label: string; value: string | null; mono?: boolean }) {
  return (
    <>
      <dt className="text-text-secondary">{label}</dt>
      <dd className={`text-text-primary ${mono ? 'font-mono' : ''}`}>{value || '-'}</dd>
    </>
  );
}
