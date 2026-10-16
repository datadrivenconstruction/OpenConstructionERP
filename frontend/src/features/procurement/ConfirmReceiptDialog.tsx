// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ConfirmReceiptDialog - the last look before a delivery counts as received.
//
// Confirming is what moves money (committed -> actual), so the dialog shows
// what the server would say first: the certificate checks as a traffic light,
// each delivered line with the certificate its order asks for, and the next
// steps on offer. A required certificate that is missing is an error and the
// confirm button stays disabled until one is added here; a batch that differs
// from the certificate is only a warning. The approval route and the incoming
// inspection start only when the person ticks them.

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Loader2, Plus, Trash2, XCircle } from 'lucide-react';
import { WideModal, Button, Badge } from '@/shared/ui';
import { apiDelete, apiGet, apiPost, getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { invalidateFinanceFigures } from '@/features/finance/financeQueryKeys';

const fieldCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

export interface CertificateType {
  code: string;
  family: string;
  rank: number;
  label: string;
}

export interface ReceiptCertificate {
  id: string;
  gr_item_id: string;
  certificate_type: string;
  certificate_number: string;
  issuer: string | null;
  issue_date: string | null;
  batch_number: string | null;
  source: string;
}

export interface ReadinessLine {
  gr_item_id: string;
  label: string;
  unit: string;
  quantity_received: string;
  batch_lot: string | null;
  required_certificate_type: string | null;
  requires_inspection: boolean;
  certificates: ReceiptCertificate[];
}

export interface ReadinessFinding {
  rule_id: string;
  severity: 'error' | 'warning' | 'info';
  passed: boolean;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

export interface ReceiptReadiness {
  gr_id: string;
  status: string;
  can_confirm: boolean;
  validation: { status: string; results: ReadinessFinding[] };
  approval_routes: { id: string; name: string }[];
  inspection_due: boolean;
  inspection_lines: string[];
  lines: ReadinessLine[];
}

export interface ConfirmableReceipt {
  id: string;
  gr_reference: string | null;
  po_number: string;
  source?: string;
}

/** The body the confirm endpoint takes. Nothing starts unless it was ticked. */
export function buildConfirmBody(choice: {
  startRoute: boolean;
  routeId: string;
  createInspection: boolean;
}): { start_approval_route: boolean; approval_route_id: string | null; create_inspection: boolean } {
  return {
    start_approval_route: choice.startRoute,
    approval_route_id: choice.startRoute && choice.routeId ? choice.routeId : null,
    create_inspection: choice.createInspection,
  };
}

/** The catalogue label of a certificate type, the code itself when the catalogue does not know it. */
export function certificateLabel(code: string | null | undefined, types: CertificateType[] | undefined): string {
  if (!code) return '';
  return (Array.isArray(types) ? types : []).find((tp) => tp.code === code)?.label ?? code;
}

/** Failing findings, errors first: what the traffic light lists under itself. */
export function failingFindings(results: ReadinessFinding[] | undefined): ReadinessFinding[] {
  const order = { error: 0, warning: 1, info: 2 } as const;
  return (results ?? []).filter((r) => !r.passed).sort((a, b) => order[a.severity] - order[b.severity]);
}

interface Props {
  receipt: ConfirmableReceipt | null;
  projectId: string;
  onClose: () => void;
}

interface CertDraft {
  certificate_type: string;
  certificate_number: string;
  issuer: string;
  issue_date: string;
  batch_number: string;
}

const EMPTY_DRAFT: CertDraft = {
  certificate_type: '',
  certificate_number: '',
  issuer: '',
  issue_date: '',
  batch_number: '',
};

export function ConfirmReceiptDialog({ receipt, projectId, onClose }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const grId = receipt?.id ?? '';
  const [startRoute, setStartRoute] = useState(false);
  const [routeId, setRouteId] = useState('');
  const [createInspection, setCreateInspection] = useState(false);
  const [openLine, setOpenLine] = useState<string | null>(null);
  const [draft, setDraft] = useState<CertDraft>(EMPTY_DRAFT);

  const readinessKey = ['procurement-gr-readiness', grId];
  const readiness = useQuery({
    queryKey: readinessKey,
    queryFn: () => apiGet<ReceiptReadiness>(`/v1/procurement/goods-receipts/${grId}/readiness/`),
    enabled: Boolean(grId),
  });
  const types = useQuery({
    queryKey: ['procurement-certificate-types'],
    queryFn: () => apiGet<CertificateType[]>('/v1/procurement/certificate-types/'),
    enabled: Boolean(grId),
    staleTime: 60 * 60 * 1000,
  });

  const data = readiness.data;
  const typeList = Array.isArray(types.data) ? types.data : [];
  const routes = useMemo(() => data?.approval_routes ?? [], [data]);

  useEffect(() => {
    setStartRoute(false);
    setCreateInspection(false);
    setOpenLine(null);
    setDraft(EMPTY_DRAFT);
  }, [grId]);

  useEffect(() => {
    // One route on offer is picked for the person; several wait for a choice.
    setRouteId(routes.length === 1 ? routes[0]!.id : '');
  }, [routes]);

  useEffect(() => {
    // A due inspection is suggested, still a box the person can untick.
    if (data?.inspection_due) setCreateInspection(true);
  }, [data?.inspection_due]);

  const onError = (e: unknown) =>
    addToast({
      type: 'error',
      title: t('common.error', { defaultValue: 'Error' }),
      message: getErrorMessage(e),
    });

  const addCert = useMutation({
    mutationFn: (lineId: string) =>
      apiPost(`/v1/procurement/goods-receipts/${grId}/certificates/`, {
        gr_item_id: lineId,
        certificate_type: draft.certificate_type,
        certificate_number: draft.certificate_number.trim(),
        issuer: draft.issuer.trim() || null,
        issue_date: draft.issue_date || null,
        batch_number: draft.batch_number.trim() || null,
      }),
    onSuccess: () => {
      setOpenLine(null);
      setDraft(EMPTY_DRAFT);
      queryClient.invalidateQueries({ queryKey: readinessKey });
    },
    onError,
  });

  const removeCert = useMutation({
    mutationFn: (certId: string) => apiDelete(`/v1/procurement/goods-receipts/${grId}/certificates/${certId}/`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: readinessKey }),
    onError,
  });

  const confirm = useMutation({
    mutationFn: () =>
      apiPost(
        `/v1/procurement/goods-receipts/${grId}/confirm/`,
        buildConfirmBody({ startRoute, routeId, createInspection }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['procurement-gr', projectId] });
      queryClient.invalidateQueries({ queryKey: ['procurement-po', projectId] });
      void invalidateFinanceFigures(queryClient);
      addToast({
        type: 'success',
        title: t('procurement.gr_confirmed_toast', { defaultValue: 'Goods receipt confirmed' }),
      });
      onClose();
    },
    onError,
  });

  const findings = failingFindings(data?.validation.results);
  const routeChoiceMissing = startRoute && routes.length > 1 && !routeId;
  const busy = confirm.isPending || addCert.isPending || removeCert.isPending;
  const light = data?.validation.status ?? 'passed';

  return (
    <WideModal
      open={receipt !== null}
      onClose={onClose}
      busy={busy}
      size="lg"
      title={t('procurement.gr_confirm_title', {
        defaultValue: 'Confirm delivery {{ref}}',
        ref: receipt?.gr_reference || receipt?.po_number || '',
      })}
      subtitle={t('procurement.gr_confirm_subtitle', {
        defaultValue:
          'Check the certificates against the order, then confirm. Confirming counts the delivery as received.',
      })}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            onClick={() => confirm.mutate()}
            disabled={busy || !data?.can_confirm || routeChoiceMissing}
            data-testid="gr-confirm-submit"
          >
            {confirm.isPending && <Loader2 size={14} className="animate-spin mr-1" />}
            {t('procurement.gr_confirm_short', { defaultValue: 'Confirm' })}
          </Button>
        </>
      }
    >
      {readiness.isLoading ? (
        <div className="flex justify-center py-8">
          <Loader2 size={20} className="animate-spin text-content-tertiary" />
        </div>
      ) : readiness.isError || !data ? (
        <p className="text-sm text-semantic-error">{getErrorMessage(readiness.error)}</p>
      ) : (
        <div className="space-y-5">
          {receipt?.source === 'supplier_portal' && (
            <Badge variant="blue" size="sm">
              {t('procurement.gr_source_supplier', { defaultValue: 'Submitted by the supplier' })}
            </Badge>
          )}

          <div data-testid="gr-readiness-light" data-status={light}>
            <div className="flex items-center gap-2 text-sm font-medium">
              {light === 'errors' ? (
                <XCircle size={16} className="text-semantic-error" />
              ) : light === 'warnings' ? (
                <AlertTriangle size={16} className="text-semantic-warning" />
              ) : (
                <CheckCircle2 size={16} className="text-semantic-success" />
              )}
              <span>
                {light === 'errors'
                  ? t('procurement.gr_check_errors', { defaultValue: 'Cannot be confirmed yet' })
                  : light === 'warnings'
                    ? t('procurement.gr_check_warnings', { defaultValue: 'Can be confirmed, please check the notes' })
                    : t('procurement.gr_check_passed', { defaultValue: 'Certificates are in order' })}
              </span>
            </div>
            {findings.length > 0 && (
              <ul className="mt-2 space-y-1">
                {findings.map((f, i) => (
                  <li
                    key={`${f.rule_id}-${i}`}
                    className={
                      f.severity === 'error' ? 'text-xs text-semantic-error' : 'text-xs text-semantic-warning'
                    }
                  >
                    {f.message}
                    {f.suggestion ? <span className="text-content-tertiary"> {f.suggestion}</span> : null}
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
              {t('procurement.gr_lines_certificates', { defaultValue: 'Delivered lines and certificates' })}
            </h3>
            {data.lines.map((line) => (
              <div key={line.gr_item_id} className="rounded-lg border border-border-light p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="text-sm text-content-primary">
                    {line.label}
                    <span className="ms-2 text-xs text-content-tertiary tabular-nums">
                      {line.quantity_received} {line.unit}
                    </span>
                    {line.batch_lot && (
                      <span className="ms-2 text-xs text-content-tertiary">
                        {t('procurement.gr_batch', { defaultValue: 'Batch {{batch}}', batch: line.batch_lot })}
                      </span>
                    )}
                  </div>
                  {line.required_certificate_type ? (
                    <Badge variant="neutral" size="sm">
                      {t('procurement.gr_requires_certificate', {
                        defaultValue: 'Order asks for {{type}}',
                        type: certificateLabel(line.required_certificate_type, types.data),
                      })}
                    </Badge>
                  ) : null}
                </div>
                {line.certificates.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {line.certificates.map((c) => (
                      <li key={c.id} className="flex items-center justify-between gap-2 text-xs text-content-secondary">
                        <span>
                          {certificateLabel(c.certificate_type, types.data)}
                          {c.certificate_number ? ` ${c.certificate_number}` : ''}
                          {c.batch_number ? ` / ${c.batch_number}` : ''}
                          {c.issuer ? ` / ${c.issuer}` : ''}
                        </span>
                        {data.status === 'draft' && (
                          <button
                            type="button"
                            onClick={() => removeCert.mutate(c.id)}
                            disabled={busy}
                            className="text-content-tertiary hover:text-semantic-error"
                            aria-label={t('procurement.gr_remove_certificate', {
                              defaultValue: 'Remove certificate',
                            })}
                          >
                            <Trash2 size={13} />
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
                {data.status === 'draft' &&
                  (openLine === line.gr_item_id ? (
                    <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                      <select
                        aria-label={t('procurement.gr_certificate_type', { defaultValue: 'Certificate type' })}
                        value={draft.certificate_type}
                        onChange={(e) => setDraft({ ...draft, certificate_type: e.target.value })}
                        className={fieldCls}
                      >
                        <option value="">
                          {t('procurement.gr_certificate_type', { defaultValue: 'Certificate type' })}
                        </option>
                        {typeList.map((tp) => (
                          <option key={tp.code} value={tp.code}>
                            {tp.label}
                          </option>
                        ))}
                      </select>
                      <input
                        aria-label={t('procurement.gr_certificate_number', { defaultValue: 'Certificate number' })}
                        placeholder={t('procurement.gr_certificate_number', { defaultValue: 'Certificate number' })}
                        value={draft.certificate_number}
                        maxLength={100}
                        onChange={(e) => setDraft({ ...draft, certificate_number: e.target.value })}
                        className={fieldCls}
                      />
                      <input
                        aria-label={t('procurement.gr_certificate_issuer', { defaultValue: 'Issued by' })}
                        placeholder={t('procurement.gr_certificate_issuer', { defaultValue: 'Issued by' })}
                        value={draft.issuer}
                        maxLength={255}
                        onChange={(e) => setDraft({ ...draft, issuer: e.target.value })}
                        className={fieldCls}
                      />
                      <input
                        type="date"
                        aria-label={t('procurement.gr_certificate_date', { defaultValue: 'Issue date' })}
                        value={draft.issue_date}
                        onChange={(e) => setDraft({ ...draft, issue_date: e.target.value })}
                        className={fieldCls}
                      />
                      <input
                        aria-label={t('procurement.gr_certificate_batch', { defaultValue: 'Batch or heat number' })}
                        placeholder={t('procurement.gr_certificate_batch', { defaultValue: 'Batch or heat number' })}
                        value={draft.batch_number}
                        maxLength={100}
                        onChange={(e) => setDraft({ ...draft, batch_number: e.target.value })}
                        className={fieldCls}
                      />
                      <div className="flex gap-2">
                        <Button
                          size="sm"
                          onClick={() => addCert.mutate(line.gr_item_id)}
                          disabled={busy || !draft.certificate_type}
                        >
                          {t('procurement.gr_add_certificate_save', { defaultValue: 'Add' })}
                        </Button>
                        <Button size="sm" variant="ghost" onClick={() => setOpenLine(null)} disabled={busy}>
                          {t('common.cancel', { defaultValue: 'Cancel' })}
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="mt-2"
                      icon={<Plus size={13} />}
                      onClick={() => {
                        setOpenLine(line.gr_item_id);
                        setDraft({
                          ...EMPTY_DRAFT,
                          certificate_type: line.required_certificate_type ?? '',
                          batch_number: line.batch_lot ?? '',
                        });
                      }}
                    >
                      {t('procurement.gr_add_certificate', { defaultValue: 'Add certificate' })}
                    </Button>
                  ))}
              </div>
            ))}
          </div>

          <div className="space-y-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
              {t('procurement.gr_next_steps', { defaultValue: 'Next steps after confirming' })}
            </h3>
            {routes.length === 0 ? (
              <p className="text-xs text-content-tertiary">
                {t('procurement.gr_no_route', {
                  defaultValue: 'This project has no approval route for deliveries.',
                })}
              </p>
            ) : (
              <div className="space-y-2">
                <label className="flex items-center gap-2 text-sm text-content-primary">
                  <input
                    type="checkbox"
                    checked={startRoute}
                    onChange={(e) => setStartRoute(e.target.checked)}
                    data-testid="gr-start-route"
                  />
                  {t('procurement.gr_start_route', { defaultValue: 'Send the delivery for site approval' })}
                </label>
                {startRoute && routes.length > 1 && (
                  <select
                    aria-label={t('procurement.gr_route', { defaultValue: 'Approval route' })}
                    value={routeId}
                    onChange={(e) => setRouteId(e.target.value)}
                    className={fieldCls}
                  >
                    <option value="">{t('procurement.gr_route', { defaultValue: 'Approval route' })}</option>
                    {routes.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.name}
                      </option>
                    ))}
                  </select>
                )}
                {startRoute && routes.length === 1 && (
                  <p className="text-xs text-content-tertiary">{routes[0]!.name}</p>
                )}
              </div>
            )}
            {data.inspection_due && (
              <label className="flex items-start gap-2 text-sm text-content-primary">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={createInspection}
                  onChange={(e) => setCreateInspection(e.target.checked)}
                  data-testid="gr-create-inspection"
                />
                <span>
                  {t('procurement.gr_create_inspection', { defaultValue: 'Plan the incoming inspection' })}
                  <span className="block text-xs text-content-tertiary">{data.inspection_lines.join(', ')}</span>
                </span>
              </label>
            )}
          </div>
        </div>
      )}
    </WideModal>
  );
}
