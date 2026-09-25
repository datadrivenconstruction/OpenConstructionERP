// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Lien waivers / tax forms panel — list + upload dialog.
 *
 * Renders inside the DetailDrawer below the existing Certificates
 * summary. Uploads go to
 *   POST /api/v1/subcontractors/subcontractors/{id}/lien-waivers/upload
 * which gates the file against the document magic-byte allow-list
 * (pdf, png, jpeg, gif, webp). The server returns 415 for any other
 * format and we render that as a Toast.
 *
 * Free-standing W-9 / W-8 tax forms are stored alongside per-draw
 * waivers; the difference is purely the ``waiver_type`` enum. They are US IRS
 * forms, so they are offered only for a subcontractor registered in the US; a
 * form already on file is still listed under its name wherever it came from.
 *
 * A payment waiver can be filed against one of the sub's pay applications,
 * with the amount it releases. Only then does the payment release gate, and
 * the GC claim rollup, count it for that pay application.
 */

import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { Upload, FileSignature, Trash2, Loader2 } from 'lucide-react';
import {
  Badge,
  Button,
  EmptyState,
  SkeletonTable,
} from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { apiGet, apiDelete, getErrorMessage, getAuthToken, API_BASE } from '@/shared/lib/api';
import { fmtFixed } from '@/shared/lib/formatters';
import { listAgreements, listPaymentApplications, type PaymentApplication } from './api';

// Six values to match the backend ``_VALID_WAIVER_TYPES`` enum. Each is
// labelled by ``subcontractors.waiver_type.<value>``, kept short so it fits a
// table row.
const WAIVER_TYPES: readonly string[] = [
  'conditional_partial',
  'conditional_final',
  'unconditional_partial',
  'unconditional_final',
  'w9',
  'w8',
];

function isTaxForm(waiverType: string): boolean {
  return waiverType === 'w9' || waiverType === 'w8';
}

/** Whether the US tax forms apply to a subcontractor registered in `country`. */
function offersUsTaxForms(country: string | null | undefined): boolean {
  return (country ?? '').trim().toUpperCase() === 'US';
}

// MIME allow-list shown in the <input accept=…> attribute. The server
// still re-validates by magic bytes — this is a UX nudge only.
const ACCEPT = '.pdf,.png,.jpg,.jpeg,.gif,.webp,application/pdf,image/*';

interface LienWaiver {
  id: string;
  // The pay application whose payment this waiver releases; null for a tax
  // form or a waiver filed on its own.
  payment_application_id: string | null;
  waiver_type: string;
  document_url: string;
  mime_type: string | null;
  file_size: number | null;
  signed_date: string | null;
  // Last day of work the waiver releases. A waiver through the 15th does not
  // cover a pay application whose period ends on the 30th.
  through_date: string | null;
  amount: number | string;
  currency: string;
  notes: string | null;
  created_at: string;
}

interface LienWaiverPanelProps {
  subcontractorId: string;
  /** ISO country of the subcontractor; decides whether the US tax forms apply. */
  country?: string | null;
}

export function LienWaiverPanel({ subcontractorId, country }: LienWaiverPanelProps) {
  const usTaxForms = offersUsTaxForms(country);
  const uploadTypes = WAIVER_TYPES.filter((w) => usTaxForms || !isTaxForm(w));
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [uploadType, setUploadType] = useState<string>('conditional_partial');
  const [throughDate, setThroughDate] = useState<string>('');
  const [payAppId, setPayAppId] = useState<string>('');
  const [amount, setAmount] = useState<string>('');
  const [busy, setBusy] = useState(false);

  const listQ = useQuery({
    queryKey: ['subcontractors', 'lien-waivers', subcontractorId],
    queryFn: () =>
      apiGet<LienWaiver[]>(
        `/v1/subcontractors/subcontractors/${subcontractorId}/lien-waivers`,
      ),
    enabled: !!subcontractorId,
  });

  // The pay applications a payment waiver can release, across all of this
  // sub's agreements. The release gate only counts a waiver filed against the
  // pay application with an amount that reaches its net, so a waiver uploaded
  // without both covers nothing. Same cache keys as the agreement rows above.
  const agreementsQ = useQuery({
    queryKey: ['subcontractors', 'agreements', subcontractorId],
    queryFn: () => listAgreements({ subcontractor_id: subcontractorId }),
    enabled: !!subcontractorId,
  });
  const paymentQs = useQueries({
    queries: (agreementsQ.data ?? []).map((agreement) => ({
      queryKey: ['subcontractors', 'payments', agreement.id],
      queryFn: () => listPaymentApplications({ agreement_id: agreement.id }),
    })),
  });
  const allPayApps = useMemo(() => paymentQs.flatMap((q) => q.data ?? []), [paymentQs]);
  const payApps = useMemo(
    () =>
      allPayApps
        // A rejected pay application is never paid, so there is nothing to release.
        .filter((pa) => pa.status !== 'rejected')
        .sort((a, b) => (b.period_end ?? '').localeCompare(a.period_end ?? '')),
    [allPayApps],
  );
  // Every pay application, rejected ones too, so the list below can still
  // name the one an older waiver was filed against.
  const payAppById = useMemo(() => new Map(allPayApps.map((pa) => [pa.id, pa])), [allPayApps]);
  const pickedPayApp = payAppId ? payAppById.get(payAppId) : undefined;

  const pickPayApp = (id: string) => {
    setPayAppId(id);
    const pa: PaymentApplication | undefined = id ? payAppById.get(id) : undefined;
    // Start from what the pay application asks for: its net, and the end of
    // its period. Both stay editable, the paper may say otherwise.
    setAmount(pa ? String(pa.net_amount) : '');
    if (pa?.period_end && !throughDate) setThroughDate(pa.period_end);
  };

  /**
   * POST a multipart form to /lien-waivers/upload. Native fetch is used
   * (not `apiPost`) because the helper only supports JSON bodies; we
   * still pull the bearer token via getAuthToken so the request lands
   * authenticated and the request ID middleware threads through.
   */
  const handleFile = async (file: File) => {
    setBusy(true);
    try {
      const form = new FormData();
      form.append('waiver_type', uploadType);
      // Tax forms release no lien rights, so they carry no through-date and
      // belong to no pay application.
      if (!isTaxForm(uploadType)) {
        if (throughDate) form.append('through_date', throughDate);
        if (pickedPayApp) {
          form.append('payment_application_id', pickedPayApp.id);
          form.append('amount', amount || '0');
          form.append('currency', pickedPayApp.currency);
        }
      }
      form.append('file', file);
      const token = getAuthToken();
      const resp = await fetch(
        `${API_BASE}/v1/subcontractors/subcontractors/${subcontractorId}/lien-waivers/upload`,
        {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : undefined,
          body: form,
        },
      );
      if (!resp.ok) {
        // 415 → format rejected. 413 → too big. 422 → bad waiver_type
        // / corrupt amount. Surface the server's detail verbatim
        // because it's already user-friendly.
        let detail: string;
        try {
          const j = await resp.json();
          // Refusals about the pay application come as {code, message}.
          detail =
            typeof j.detail === 'string'
              ? j.detail
              : typeof j.detail?.message === 'string'
                ? j.detail.message
                : JSON.stringify(j);
        } catch {
          detail = `HTTP ${resp.status}`;
        }
        addToast({
          type: 'error',
          title: t('subcontractors.upload_failed', {
            defaultValue: 'Upload failed',
          }),
          message: detail,
        });
        return;
      }
      addToast({
        type: 'success',
        title: t('subcontractors.waiver_uploaded', {
          defaultValue: 'Lien waiver uploaded',
        }),
      });
      qc.invalidateQueries({
        queryKey: ['subcontractors', 'lien-waivers', subcontractorId],
      });
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleDelete = async (waiverId: string) => {
    try {
      await apiDelete(
        `/v1/subcontractors/subcontractors/${subcontractorId}/lien-waivers/${waiverId}`,
      );
      addToast({
        type: 'success',
        title: t('subcontractors.waiver_deleted', {
          defaultValue: 'Lien waiver removed',
        }),
      });
      qc.invalidateQueries({
        queryKey: ['subcontractors', 'lien-waivers', subcontractorId],
      });
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    }
  };

  const rows = listQ.data ?? [];

  return (
    <section
      aria-label={t('subcontractors.lien_waivers_aria', {
        defaultValue: 'Lien waivers and tax forms',
      })}
      className="space-y-2"
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-content-secondary">
          {t('subcontractors.lien_waivers_title', {
            defaultValue: 'Lien waivers & tax forms',
          })}
        </h3>
        <div className="flex items-center gap-1.5">
          <select
            value={uploadType}
            onChange={(e) => setUploadType(e.target.value)}
            className="h-8 rounded-md border border-border-light bg-surface-primary px-2 text-xs"
            aria-label={t('subcontractors.lien_waiver_type', {
              defaultValue: 'Waiver type',
            })}
            disabled={busy}
          >
            {uploadTypes.map((w) => (
              <option key={w} value={w}>
                {t(`subcontractors.waiver_type.${w}`)}
              </option>
            ))}
          </select>
          {!isTaxForm(uploadType) && (
            <input
              type="date"
              value={throughDate}
              onChange={(e) => setThroughDate(e.target.value)}
              className="h-8 rounded-md border border-border-light bg-surface-primary px-2 text-xs"
              aria-label={t('subcontractors.waiver_through_date', {
                defaultValue: 'Releases work through',
              })}
              title={t('subcontractors.waiver_through_date_hint', {
                defaultValue:
                  'The last day of work this waiver releases. Leave empty if the waiver does not state one.',
              })}
              disabled={busy}
              data-testid="waiver-through-date"
            />
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void handleFile(f);
            }}
            aria-label={t('subcontractors.lien_waiver_file_input', {
              defaultValue: 'Lien waiver file',
            })}
          />
          <Button
            variant="secondary"
            size="sm"
            icon={busy ? <Loader2 size={12} className="animate-spin" /> : <Upload size={12} />}
            onClick={() => fileInputRef.current?.click()}
            disabled={busy}
          >
            {t('subcontractors.upload_waiver', { defaultValue: 'Upload' })}
          </Button>
        </div>
      </div>

      {!isTaxForm(uploadType) && payApps.length > 0 && (
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          <select
            value={payAppId}
            onChange={(e) => pickPayApp(e.target.value)}
            className="h-8 max-w-[260px] rounded-md border border-border-light bg-surface-primary px-2 text-xs"
            aria-label={t('subcontractors.waiver_pay_app', { defaultValue: 'Pay application' })}
            disabled={busy}
            data-testid="waiver-pay-app"
          >
            <option value="">
              {t('subcontractors.waiver_pay_app_none', { defaultValue: 'Not tied to a pay application' })}
            </option>
            {payApps.map((pa) => (
              <option key={pa.id} value={pa.id}>
                {pa.period_end
                  ? t('subcontractors.waiver_pay_app_option', {
                      number: pa.application_number,
                      date: pa.period_end,
                      defaultValue: '{{number}}, period ending {{date}}',
                    })
                  : pa.application_number}
              </option>
            ))}
          </select>
          {pickedPayApp && (
            <>
              <input
                type="number"
                min="0"
                step="0.01"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                className="h-8 w-28 rounded-md border border-border-light bg-surface-primary px-2 text-right text-xs tabular-nums"
                aria-label={t('subcontractors.waiver_amount', { defaultValue: 'Waiver amount' })}
                title={t('subcontractors.waiver_amount_hint', {
                  defaultValue:
                    'The amount the waiver releases. It covers the payment only when it reaches the net amount of the pay application.',
                })}
                disabled={busy}
                data-testid="waiver-amount"
              />
              <span className="text-xs text-content-tertiary">{pickedPayApp.currency}</span>
            </>
          )}
        </div>
      )}

      {listQ.isLoading && <SkeletonTable rows={2} columns={4} />}

      {!listQ.isLoading && rows.length === 0 && (
        <EmptyState
          icon={<FileSignature size={18} />}
          title={t('subcontractors.no_lien_waivers', {
            defaultValue: 'No lien waivers yet',
          })}
          description={
            usTaxForms
              ? t('subcontractors.no_lien_waivers_desc', {
                  defaultValue:
                    'Upload signed lien waivers (PDF / image) and W-9 / W-8 tax forms here. Server validates file content by magic bytes.',
                })
              : t('subcontractors.no_lien_waivers_desc_neutral')
          }
        />
      )}

      {!listQ.isLoading && rows.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-border-light">
          <table className="w-full text-xs">
            <thead className="bg-surface-secondary text-content-tertiary uppercase tracking-wide">
              <tr>
                <th className="px-3 py-2 text-left">
                  {t('subcontractors.waiver_type_col', { defaultValue: 'Type' })}
                </th>
                <th className="px-3 py-2 text-left">
                  {t('subcontractors.signed_date_col', { defaultValue: 'Signed' })}
                </th>
                <th className="px-3 py-2 text-left">
                  {t('subcontractors.through_date_col', { defaultValue: 'Through' })}
                </th>
                <th className="px-3 py-2 text-left">
                  {t('subcontractors.waiver_pay_app', { defaultValue: 'Pay application' })}
                </th>
                <th className="px-3 py-2 text-right">
                  {t('subcontractors.amount', { defaultValue: 'Amount' })}
                </th>
                <th className="px-3 py-2 text-left">
                  {t('subcontractors.uploaded', { defaultValue: 'Uploaded' })}
                </th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {rows.map((w) => (
                <tr key={w.id} className="border-t border-border-light">
                  <td className="px-3 py-2">
                    <Badge variant="blue" size="sm">
                      {WAIVER_TYPES.includes(w.waiver_type)
                        ? t(`subcontractors.waiver_type.${w.waiver_type}`)
                        : w.waiver_type}
                    </Badge>
                  </td>
                  <td className="px-3 py-2 text-content-secondary">
                    {w.signed_date || '—'}
                  </td>
                  <td className="px-3 py-2 text-content-secondary">
                    {w.through_date || '—'}
                  </td>
                  <td className="px-3 py-2 text-content-secondary">
                    {w.payment_application_id
                      ? (payAppById.get(w.payment_application_id)?.application_number ?? '…')
                      : '—'}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {typeof w.amount === 'string' ? w.amount : fmtFixed(w.amount, 2)}{' '}
                    <span className="text-content-tertiary">{w.currency || ''}</span>
                  </td>
                  <td className="px-3 py-2 text-content-secondary">
                    <DateDisplay value={w.created_at} />
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => handleDelete(w.id)}
                      className={clsx(
                        'inline-flex items-center justify-center rounded p-1 text-content-tertiary',
                        'hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-950/30',
                      )}
                      aria-label={t('subcontractors.delete_waiver', {
                        defaultValue: 'Delete lien waiver',
                      })}
                    >
                      <Trash2 size={12} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
