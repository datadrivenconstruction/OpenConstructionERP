// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Buyer self-service portal — public landing page (``/buyer-portal/:token``).
 *
 * Rendered for unauthenticated buyers who follow the magic link emailed
 * by the sales team. No bearer JWT — the token in the URL is the entire
 * auth surface (verified server-side against the revocation registry
 * stored in ``oe_propdev_portal_token``).
 *
 * v4.6.2 mobile-first polish (Wave 7 follow-up):
 *   - Hero "Welcome back, {first_name}" card with quick-link tiles.
 *   - Payment schedule rendered as timeline cards on <sm, table on >=sm.
 *   - KYC upload: drag-and-drop on desktop, tap-to-pick + camera capture
 *     on mobile, multi-file picker per code, inline preview chips before
 *     upload, per-file error display, RecoveryCard for batch failures.
 *   - Documents grouped by category, with last-modified date and
 *     file-type icon for visual scanning.
 *   - Bottom-fixed primary CTA bar on mobile so the buyer never has to
 *     scroll to find "Pay" / "Upload KYC".
 *   - Touch targets >= 44x44 (WCAG 2.5.5) on every interactive element.
 *   - aria-required on every required form field.
 *
 * Layout (top → bottom, ARIA-landmarks throughout):
 *   1. <header> — logo + "Welcome, {buyer_name}" + locale switcher.
 *   2. <main> with sections:
 *        a. Welcome hero with quick links.
 *        b. Reservation card.
 *        c. Sales contract card.
 *        d. Payment schedule (timeline on mobile, table on tablet+).
 *        e. Documents library (grouped) + KYC upload requests.
 *        f. "Contact your agent" form.
 *   3. <footer> — contact email + AGPL-3.0 link.
 *   4. Mobile-only fixed bottom CTA bar (visible <sm).
 *
 * States: loading / invalid-token / error / ready. We never leak a
 * login form when the token is bad — just a friendly "ask your agent
 * for a new link" message.
 */

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type FormEvent,
} from 'react';
import { useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useNumberLocale } from '@/stores/usePreferencesStore';
import { formatCurrency } from '@/shared/lib/money';
import {
  AlertTriangle,
  Building2,
  Camera,
  CheckCircle2,
  Clock,
  CreditCard,
  Eye,
  FileImage,
  FileText,
  Loader2,
  Mail,
  Phone,
  ShieldX,
  Trash2,
  Upload,
  X,
} from 'lucide-react';

import { BetaBanner, ModuleGuideButton } from '@/shared/ui';
import { SUPPORTED_LANGUAGES } from '@/app/i18n';

import { buyerPortalGuide } from './buyerPortalGuide';

import {
  contactPortalAgent,
  fetchPortalOverview,
  uploadPortalKyc,
  type PortalDocumentRow,
  type PortalInstalmentRow,
  type PortalKycCode,
  type PortalOverviewResponse,
} from './api';
import { fmtFixed, formatDateValue } from '@/shared/lib/formatters';

// English fallbacks for the computed `buyer_portal.documents.cat.*` keys. The default used to be
// the raw value, so until the key lands in a locale the screen shows the bare
// enum token to every reader, English included. Unknown values still fall
// through to the previous default.
const DOCUMENTS_CAT_LABELS: Record<string, string> = {
  reservation_receipt: 'Reservation receipt', sales_contract: 'Sales contract',
  payment_receipt: 'Payment receipt', handover_certificate: 'Handover certificate',
  warranty_certificate: 'Warranty certificate', noc: 'No objection certificate',
  tenant_lease_agreement: 'Tenant lease agreement', move_in_checklist: 'Move-in checklist',
  mortgage_clearance_letter: 'Mortgage clearance letter',
  title_deed_transfer_request: 'Title deed transfer request',
  escrow_release_authorization: 'Escrow release authorisation',
  refund_authorization: 'Refund authorisation', snag_report: 'Snag report', invoice: 'Invoice',
  payment_reminder: 'Payment reminder', kyc_checklist: 'KYC checklist',
  brokerage_commission: 'Brokerage commission', custom: 'Custom', other: 'Other'
};


type PageState =
  | { kind: 'loading' }
  | { kind: 'invalid' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; data: PortalOverviewResponse };

// File upload limits — must match backend (FILE_TOO_LARGE → 20 MB).
const MAX_KYC_FILE_BYTES = 20 * 1024 * 1024;
const ACCEPT_KYC_TYPES =
  'application/pdf,image/png,image/jpeg,image/heic,image/heif';

// Per-file upload tracking entry. We hold the File object plus a status so
// the UI can show staged-vs-uploading-vs-success/error chips before the
// real network call lands.
interface PendingFile {
  id: string;
  file: File;
  status: 'pending' | 'uploading' | 'success' | 'error';
  errorMsg?: string;
}

export function BuyerPortalPage() {
  const { token } = useParams<{ token: string }>();
  const { t, i18n } = useTranslation();
  // The buyer is the reader here, so their money and dates go through the
  // same resolver as every other register rather than a second answer built
  // in this file. `i18n.language` stays where it means the language itself:
  // the switcher in the shell below.
  const numberLocale = useNumberLocale();

  const [state, setState] = useState<PageState>({ kind: 'loading' });
  const [contactMessage, setContactMessage] = useState('');
  const [contactPhone, setContactPhone] = useState('');
  const [contactSending, setContactSending] = useState(false);
  const [contactSent, setContactSent] = useState(false);

  // Per-KYC-code multi-file staging map.
  // Why per-code: each KYC requirement (passport, address_proof, …) has
  // its own dropzone, and the buyer can pick several pages (e.g. both
  // sides of a national_id) before any upload happens.
  const [pendingByCode, setPendingByCode] = useState<
    Record<string, PendingFile[]>
  >({});
  const [batchErrorByCode, setBatchErrorByCode] = useState<
    Record<string, string | null>
  >({});

  // Track which dropzone is currently being dragged over so the UI can
  // highlight only the active target (not every dropzone on the page).
  const [dragTarget, setDragTarget] = useState<string | null>(null);

  // Honor the buyer's preferred language exactly once on first load.
  // After that the buyer is free to switch manually via the header
  // switcher without us snapping back. The ref guards against the
  // effect re-applying on later re-renders / data refetches.
  const appliedBuyerLanguageRef = useRef(false);

  // 1. Initial overview fetch (verify happens implicitly).
  useEffect(() => {
    let cancelled = false;
    if (!token) {
      setState({ kind: 'invalid' });
      return;
    }
    (async () => {
      try {
        const data = await fetchPortalOverview(token);
        if (!cancelled) setState({ kind: 'ready', data });
      } catch (err) {
        if (cancelled) return;
        const msg = (err as Error).message;
        // The landing page only calls /overview/ (which never consumes
        // the magic link — single-use is enforced solely by /verify/),
        // so a previously-redeemed link surfaces as the generic
        // invalid/expired bucket here, not ALREADY_USED. We therefore
        // map every auth failure to the "ask your agent for a new link"
        // invalid screen and surface anything else as a soft error.
        if (msg === 'INVALID' || msg === 'ALREADY_USED') {
          setState({ kind: 'invalid' });
        } else {
          setState({ kind: 'error', message: msg });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  // 1b. Apply the buyer's preferred language once, when the overview
  //     payload first arrives. Only switch when the language is one we
  //     actually ship and it differs from the current UI language —
  //     otherwise a buyer whose record says e.g. ``fr`` would stay on
  //     the default English UI despite the backend knowing better.
  useEffect(() => {
    if (state.kind !== 'ready' || appliedBuyerLanguageRef.current) return;
    appliedBuyerLanguageRef.current = true;
    const lang = (state.data.buyer_language || '').trim().toLowerCase();
    if (!lang) return;
    const supported = SUPPORTED_LANGUAGES.some((l) => l.code === lang);
    if (supported && !i18n.language.startsWith(lang)) {
      void i18n.changeLanguage(lang);
    }
  }, [state, i18n]);

  // 2. Stage files into the per-code pending list (does NOT upload yet).
  //    This lets the buyer preview filenames, drop extras, then hit
  //    "Upload all" once. Mirrors the multi-file gmail-attachment UX
  //    most buyers expect after the drag.
  function stageFiles(code: PortalKycCode, files: FileList | File[]) {
    const arr = Array.from(files);
    if (arr.length === 0) return;
    const accepted: PendingFile[] = [];
    const rejections: string[] = [];
    for (const file of arr) {
      if (file.size > MAX_KYC_FILE_BYTES) {
        rejections.push(
          t('buyer_portal.upload.too_large_named', {
            defaultValue: '{{name}} is larger than 20 MB',
            name: file.name,
          }),
        );
        continue;
      }
      // Lightweight client-side magic-byte hint via MIME — backend
      // re-validates with the real magic bytes so this is just early UX.
      if (!ACCEPT_KYC_TYPES.split(',').includes(file.type) && file.type !== '') {
        rejections.push(
          t('buyer_portal.upload.bad_type_named', {
            defaultValue: '{{name}} is not a PDF or image',
            name: file.name,
          }),
        );
        continue;
      }
      accepted.push({
        id: `${Date.now()}-${file.name}-${Math.random().toString(36).slice(2, 8)}`,
        file,
        status: 'pending',
      });
    }
    setPendingByCode((prev) => ({
      ...prev,
      [code]: [...(prev[code] || []), ...accepted],
    }));
    setBatchErrorByCode((prev) => ({
      ...prev,
      [code]: rejections.length > 0 ? rejections.join(' · ') : null,
    }));
  }

  // 3. Upload every staged file for one KYC code, sequentially. We use
  //    sequential (not parallel) uploads because each one is up to 20 MB
  //    and parallel saturates mobile uplinks; the per-file progress also
  //    reads more cleanly when one bar fills at a time.
  async function uploadAllFor(code: PortalKycCode) {
    if (!token) return;
    const queue = pendingByCode[code] || [];
    if (queue.length === 0) return;
    setBatchErrorByCode((prev) => ({ ...prev, [code]: null }));

    for (const entry of queue) {
      if (entry.status === 'success') continue;
      setPendingByCode((prev) => ({
        ...prev,
        [code]: (prev[code] || []).map((p) =>
          p.id === entry.id ? { ...p, status: 'uploading', errorMsg: undefined } : p,
        ),
      }));
      try {
        await uploadPortalKyc(token, code, entry.file);
        setPendingByCode((prev) => ({
          ...prev,
          [code]: (prev[code] || []).map((p) =>
            p.id === entry.id ? { ...p, status: 'success' } : p,
          ),
        }));
      } catch (err) {
        const msg = (err as Error).message;
        const friendly =
          msg === 'UNSUPPORTED_MEDIA_TYPE'
            ? t('buyer_portal.upload.unsupported', {
                defaultValue:
                  'This file format is not accepted. Please upload a PDF or image (PNG/JPEG).',
              })
            : msg === 'FILE_TOO_LARGE'
              ? t('buyer_portal.upload.too_large', {
                  defaultValue: 'File is too large. Maximum size is 20 MB.',
                })
              : msg;
        setPendingByCode((prev) => ({
          ...prev,
          [code]: (prev[code] || []).map((p) =>
            p.id === entry.id ? { ...p, status: 'error', errorMsg: friendly } : p,
          ),
        }));
      }
    }

    // Re-fetch the overview so the "is_uploaded" status flips green for
    // the slots that succeeded. We do this even if some failed — the
    // ones that succeeded should still update.
    try {
      const fresh = await fetchPortalOverview(token);
      setState({ kind: 'ready', data: fresh });
    } catch {
      // Soft-ignore — overview will refresh on next interaction.
    }

    // Drop successful entries from the staging list once the slot
    // appears as uploaded on the server.
    setPendingByCode((prev) => ({
      ...prev,
      [code]: (prev[code] || []).filter((p) => p.status !== 'success'),
    }));
  }

  function removePending(code: string, id: string) {
    setPendingByCode((prev) => ({
      ...prev,
      [code]: (prev[code] || []).filter((p) => p.id !== id),
    }));
  }

  function clearBatchError(code: string) {
    setBatchErrorByCode((prev) => ({ ...prev, [code]: null }));
  }

  // 4. Contact-agent submission.
  async function handleContactSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!token || contactSending) return;
    const trimmed = contactMessage.trim();
    if (!trimmed) return;
    setContactSending(true);
    try {
      await contactPortalAgent(token, trimmed, contactPhone.trim() || undefined);
      setContactSent(true);
      setContactMessage('');
      setContactPhone('');
    } catch {
      setContactSent(false);
    } finally {
      setContactSending(false);
    }
  }

  // ── Render: invalid / error / loading shells ──────

  if (state.kind === 'invalid') {
    return (
      <ShellWrapper>
        <div
          data-testid="buyer-portal-invalid"
          className="rounded-2xl border border-semantic-error/30 bg-semantic-error/5 p-6 text-center space-y-3"
        >
          <ShieldX
            size={32}
            strokeWidth={1.5}
            className="mx-auto text-semantic-error"
          />
          <h2 className="text-base font-semibold text-content-primary">
            {t('buyer_portal.invalid.title', {
              defaultValue: 'Your access link has expired',
            })}
          </h2>
          <p className="text-sm text-content-secondary">
            {t('buyer_portal.invalid.body', {
              defaultValue:
                'Contact your sales agent to receive a new link. We never ask for a password to view your information.',
            })}
          </p>
        </div>
      </ShellWrapper>
    );
  }

  if (state.kind === 'error') {
    return (
      <ShellWrapper>
        <div
          data-testid="buyer-portal-error"
          className="rounded-2xl border border-amber-300/40 bg-amber-50 dark:bg-amber-900/20 p-6 text-center space-y-3"
        >
          <AlertTriangle
            size={28}
            strokeWidth={1.5}
            className="mx-auto text-amber-600 dark:text-amber-400"
          />
          <h2 className="text-base font-semibold text-content-primary">
            {t('buyer_portal.error.title', {
              defaultValue: 'Something went wrong',
            })}
          </h2>
          <p className="text-sm text-content-secondary">{state.message}</p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="mt-2 inline-flex items-center justify-center gap-2 min-h-11 px-4 rounded-lg bg-oe-blue text-white text-sm font-medium hover:bg-oe-blue-hover"
          >
            {t('buyer_portal.error.retry', { defaultValue: 'Try again' })}
          </button>
        </div>
      </ShellWrapper>
    );
  }

  if (state.kind === 'loading') {
    return (
      <ShellWrapper>
        <div
          data-testid="buyer-portal-loading"
          className="rounded-2xl border border-border-light bg-surface-elevated p-8 text-center space-y-3"
        >
          <Loader2
            size={24}
            className="animate-spin mx-auto text-content-tertiary"
            aria-hidden
          />
          <p className="text-sm text-content-tertiary">
            {t('buyer_portal.loading', {
              defaultValue: 'Loading your portal…',
            })}
          </p>
        </div>
      </ShellWrapper>
    );
  }

  // ── Render: ready ────────────────────────────────────────────────

  const { data } = state;

  // Derive a friendly first-name greeting. Backend currently returns
  // ``buyer_full_name`` only, so we take the first whitespace-delimited
  // token. If/when the API adds ``buyer_first_name`` we can drop this.
  const firstName =
    (data.buyer_full_name || '').trim().split(/\s+/)[0] || data.buyer_full_name;

  // Outstanding > 0 controls whether the mobile sticky CTA shows "Pay
  // next instalment". When everything is paid we hide it.
  const hasOutstanding =
    Number(data.payment_schedule_outstanding || '0') > 0;
  const nextDueInstalment = data.instalments.find(
    (i) => i.status === 'overdue' || i.status === 'due' || i.status === 'pending',
  );
  const hasPendingKyc = data.kyc_requests.some((r) => !r.is_uploaded);

  return (
    <ShellWrapper buyerName={data.buyer_full_name} locale={i18n.language}>
      <main
        className="w-full max-w-3xl mx-auto px-4 sm:px-6 py-6 space-y-6 pb-32 sm:pb-6"
      >
        <BetaBanner moduleKey="buyer-portal" className="mt-3" />
        {/* 1. Welcome hero with project banner + quick links */}
        <HeroSection
          firstName={firstName}
          developmentName={data.development_name}
          reservationNumber={data.reservation?.reservation_number}
          plotNumber={data.reservation?.plot_number}
          hasOutstanding={hasOutstanding}
          hasPendingKyc={hasPendingKyc}
        />

        {/* Reservation card */}
        {data.reservation && (
          <section
            aria-labelledby="reservation-heading"
            data-testid="reservation-card"
            className="rounded-2xl border border-border-light bg-surface-elevated p-5"
          >
            <h2
              id="reservation-heading"
              className="text-sm font-semibold text-content-primary flex items-center gap-2"
            >
              <Building2 size={16} aria-hidden />
              {t('buyer_portal.reservation.title', {
                defaultValue: 'Reservation',
              })}
            </h2>
            <dl className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
                  {t('buyer_portal.reservation.number', {
                    defaultValue: 'Reservation #',
                  })}
                </dt>
                <dd className="text-content-primary font-medium">
                  {data.reservation.reservation_number}
                </dd>
              </div>
              <div>
                <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
                  {t('buyer_portal.reservation.plot', { defaultValue: 'Plot' })}
                </dt>
                <dd className="text-content-primary font-medium">
                  {data.reservation.plot_number}
                </dd>
              </div>
              <div>
                <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
                  {t('buyer_portal.reservation.address', {
                    defaultValue: 'Address',
                  })}
                </dt>
                <dd className="text-content-primary">
                  {data.reservation.plot_address ||
                    t('buyer_portal.na', { defaultValue: '—' })}
                </dd>
              </div>
              <div>
                <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
                  {t('buyer_portal.reservation.status', {
                    defaultValue: 'Status',
                  })}
                </dt>
                <dd>
                  <StatusBadge status={data.reservation.status} />
                </dd>
              </div>
              <div>
                <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
                  {t('buyer_portal.reservation.deposit', {
                    defaultValue: 'Deposit',
                  })}
                </dt>
                <dd className="text-content-primary font-medium tabular-nums">
                  {formatMoney(
                    data.reservation.deposit_amount,
                    data.reservation.currency,
                    numberLocale,
                  )}
                </dd>
              </div>
              {data.reservation.signed_on && (
                <div>
                  <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
                    {t('buyer_portal.reservation.signed', {
                      defaultValue: 'Signed',
                    })}
                  </dt>
                  <dd className="text-content-primary">
                    {formatDate(data.reservation.signed_on)}
                  </dd>
                </div>
              )}
            </dl>
          </section>
        )}

        {/* Sales contract card */}
        {data.sales_contract && (
          <section
            aria-labelledby="contract-heading"
            data-testid="contract-card"
            className="rounded-2xl border border-border-light bg-surface-elevated p-5"
          >
            <h2
              id="contract-heading"
              className="text-sm font-semibold text-content-primary flex items-center gap-2"
            >
              <FileText size={16} aria-hidden />
              {t('buyer_portal.contract.title', {
                defaultValue: 'Sale & Purchase Agreement',
              })}
            </h2>
            <dl className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
              <div>
                <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
                  {t('buyer_portal.contract.number', {
                    defaultValue: 'Contract #',
                  })}
                </dt>
                <dd className="text-content-primary font-medium">
                  {data.sales_contract.contract_number}
                </dd>
              </div>
              <div>
                <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
                  {t('buyer_portal.contract.value', { defaultValue: 'Value' })}
                </dt>
                <dd className="text-content-primary font-medium tabular-nums">
                  {formatMoney(
                    data.sales_contract.total_value,
                    data.sales_contract.currency,
                    numberLocale,
                  )}
                </dd>
              </div>
              <div>
                <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
                  {t('buyer_portal.contract.status', {
                    defaultValue: 'Status',
                  })}
                </dt>
                <dd>
                  <StatusBadge status={data.sales_contract.status} />
                </dd>
              </div>
            </dl>
          </section>
        )}

        {/* Payment schedule — timeline on mobile, table on tablet+ */}
        <PaymentScheduleSection
          instalments={data.instalments}
          totalPaid={data.payment_schedule_paid}
          totalOutstanding={data.payment_schedule_outstanding}
          totalValue={data.payment_schedule_total}
          currency={data.payment_schedule_currency}
          locale={numberLocale}
        />

        {/* Documents + KYC */}
        <DocumentsSection documents={data.documents} />

        <KycSection
          kycRequests={data.kyc_requests}
          pendingByCode={pendingByCode}
          batchErrorByCode={batchErrorByCode}
          dragTarget={dragTarget}
          setDragTarget={setDragTarget}
          stageFiles={stageFiles}
          uploadAllFor={uploadAllFor}
          removePending={removePending}
          clearBatchError={clearBatchError}
        />

        {/* Contact agent */}
        <section
          aria-labelledby="contact-heading"
          data-testid="contact-section"
          className="rounded-2xl border border-border-light bg-surface-elevated p-5"
        >
          <h2
            id="contact-heading"
            className="text-sm font-semibold text-content-primary flex items-center gap-2"
          >
            <Mail size={16} aria-hidden />
            {t('buyer_portal.contact.title', {
              defaultValue: 'Contact your agent',
            })}
          </h2>
          {contactSent ? (
            <div
              data-testid="contact-sent"
              className="mt-3 rounded-lg bg-semantic-success/10 text-semantic-success px-3 py-2 text-xs"
              role="status"
            >
              {t('buyer_portal.contact.sent', {
                defaultValue: 'Thank you - your agent will reply shortly.',
              })}
            </div>
          ) : (
            <form
              onSubmit={handleContactSubmit}
              className="mt-3 space-y-3"
              aria-label={t('buyer_portal.contact.form_label', {
                defaultValue: 'Contact agent form',
              })}
            >
              <label className="block">
                <span className="text-2xs uppercase tracking-wide text-content-tertiary">
                  {t('buyer_portal.contact.message', {
                    defaultValue: 'Your message',
                  })}
                </span>
                <textarea
                  required
                  aria-required="true"
                  maxLength={2000}
                  rows={4}
                  value={contactMessage}
                  onChange={(e) => setContactMessage(e.target.value)}
                  className="mt-1 w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-base sm:text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-oe-blue/50"
                  placeholder={t('buyer_portal.contact.message_placeholder', {
                    defaultValue: 'Ask a question, request an update…',
                  })}
                  data-testid="contact-message"
                />
              </label>
              <label className="block">
                <span className="text-2xs uppercase tracking-wide text-content-tertiary">
                  {t('buyer_portal.contact.phone', {
                    defaultValue: 'Callback phone (optional)',
                  })}
                </span>
                <input
                  type="tel"
                  inputMode="tel"
                  maxLength={40}
                  value={contactPhone}
                  onChange={(e) => setContactPhone(e.target.value)}
                  className="mt-1 w-full min-h-11 rounded-lg border border-border-light bg-surface-primary px-3 text-base sm:text-sm text-content-primary placeholder:text-content-quaternary focus:outline-none focus:ring-2 focus:ring-oe-blue/50"
                  placeholder="+49 30 12345678"
                  data-testid="contact-phone"
                />
              </label>
              <button
                type="submit"
                disabled={contactSending || contactMessage.trim().length === 0}
                className="inline-flex w-full sm:w-auto items-center justify-center gap-2 min-h-11 px-4 rounded-lg bg-oe-blue text-white text-sm font-medium hover:bg-oe-blue-hover disabled:opacity-50"
                data-testid="contact-submit"
              >
                {contactSending ? (
                  <Loader2 size={14} className="animate-spin" aria-hidden />
                ) : (
                  <Mail size={14} aria-hidden />
                )}
                {t('buyer_portal.contact.submit', {
                  defaultValue: 'Send message',
                })}
              </button>
            </form>
          )}
        </section>
      </main>

      {/* 4. Sticky bottom CTA bar on mobile only. We surface the highest-
            priority action: "Pay" if there's outstanding money, else
            "Upload KYC" if there's a pending request, else "Contact agent". */}
      <MobileCtaBar
        hasOutstanding={hasOutstanding}
        hasPendingKyc={hasPendingKyc}
        nextDueAmount={nextDueInstalment?.amount}
        nextDueCurrency={nextDueInstalment?.currency}
        locale={numberLocale}
      />
    </ShellWrapper>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Hero section: welcome + project banner + quick-link tiles
// ─────────────────────────────────────────────────────────────────────

function HeroSection({
  firstName,
  developmentName,
  reservationNumber,
  plotNumber,
  hasOutstanding,
  hasPendingKyc,
}: {
  firstName: string;
  developmentName: string;
  reservationNumber?: string;
  plotNumber?: string;
  hasOutstanding: boolean;
  hasPendingKyc: boolean;
}) {
  const { t } = useTranslation();
  return (
    <section
      aria-labelledby="welcome-heading"
      data-testid="welcome-hero"
      className="rounded-2xl border border-border-light bg-gradient-to-br from-oe-blue/10 via-surface-elevated to-surface-elevated p-5 sm:p-6"
    >
      <h1
        id="welcome-heading"
        className="text-xl sm:text-2xl font-semibold text-content-primary"
      >
        {t('buyer_portal.welcome_back', {
          defaultValue: 'Welcome back, {{name}}',
          name: firstName,
        })}
      </h1>
      <p className="mt-1 text-sm sm:text-base text-content-secondary">
        {developmentName ||
          t('buyer_portal.welcome.fallback', {
            defaultValue: 'Your buyer dashboard',
          })}
      </p>
      {(reservationNumber || plotNumber) && (
        <p
          className="mt-2 inline-flex items-center gap-2 rounded-full bg-oe-blue/15 px-3 py-1 text-xs font-medium text-oe-blue"
          data-testid="hero-reservation-pill"
        >
          <Building2 size={12} aria-hidden />
          {plotNumber
            ? t('buyer_portal.hero.your_reservation_plot', {
                defaultValue: 'Your reservation · Plot {{plot}}',
                plot: plotNumber,
              })
            : t('buyer_portal.hero.your_reservation_num', {
                defaultValue: 'Reservation #{{num}}',
                num: reservationNumber,
              })}
        </p>
      )}

      <div className="mt-4 grid grid-cols-2 sm:grid-cols-4 gap-2">
        <QuickLinkTile
          href="#payments-heading"
          icon={<CreditCard size={16} aria-hidden />}
          label={
            hasOutstanding
              ? t('buyer_portal.quick.pay_next', {
                  defaultValue: 'Pay next instalment',
                })
              : t('buyer_portal.quick.view_payments', {
                  defaultValue: 'Payments',
                })
          }
          variant={hasOutstanding ? 'primary' : 'neutral'}
          testId="quick-link-pay"
        />
        <QuickLinkTile
          href="#kyc-heading"
          icon={<Upload size={16} aria-hidden />}
          label={t('buyer_portal.quick.upload_kyc', {
            defaultValue: 'Upload KYC',
          })}
          variant={hasPendingKyc ? 'accent' : 'neutral'}
          testId="quick-link-kyc"
        />
        <QuickLinkTile
          href="#documents-heading"
          icon={<FileText size={16} aria-hidden />}
          label={t('buyer_portal.quick.documents', {
            defaultValue: 'Documents',
          })}
          variant="neutral"
          testId="quick-link-documents"
        />
        <QuickLinkTile
          href="#contact-heading"
          icon={<Mail size={16} aria-hidden />}
          label={t('buyer_portal.quick.contact', {
            defaultValue: 'Contact agent',
          })}
          variant="neutral"
          testId="quick-link-contact"
        />
      </div>
    </section>
  );
}

function QuickLinkTile({
  href,
  icon,
  label,
  variant,
  testId,
}: {
  href: string;
  icon: React.ReactNode;
  label: string;
  variant: 'primary' | 'accent' | 'neutral';
  testId: string;
}) {
  const colorClasses =
    variant === 'primary'
      ? 'bg-oe-blue text-white hover:bg-oe-blue-hover border-oe-blue'
      : variant === 'accent'
        ? 'bg-amber-100 text-amber-900 hover:bg-amber-200 border-amber-200 dark:bg-amber-900/30 dark:text-amber-200 dark:border-amber-900/40'
        : 'bg-surface-primary text-content-primary hover:bg-surface-secondary border-border-light';
  return (
    <a
      href={href}
      data-testid={testId}
      className={`flex flex-col items-center justify-center gap-1.5 min-h-16 rounded-xl border ${colorClasses} px-3 py-2.5 text-xs font-medium text-center transition-colors`}
    >
      <span aria-hidden>{icon}</span>
      <span className="leading-tight">{label}</span>
    </a>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Payment schedule: sum bars + responsive table/timeline + detail drawer
// ─────────────────────────────────────────────────────────────────────

function PaymentScheduleSection({
  instalments,
  totalPaid,
  totalOutstanding,
  totalValue,
  currency,
  locale,
}: {
  instalments: PortalInstalmentRow[];
  totalPaid: string;
  totalOutstanding: string;
  totalValue: string;
  currency: string;
  locale: string;
}) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState<PortalInstalmentRow | null>(null);

  // Numbers for the progress bar. ``total`` can be zero (no schedule
  // issued yet) — we guard against division by zero by hiding the bar.
  const paidNum = Number(totalPaid || '0');
  const totalNum = Number(totalValue || '0');
  const paidPct = totalNum > 0 ? Math.min(100, (paidNum / totalNum) * 100) : 0;
  // Only show the outstanding figure when a real schedule exists. With
  // no schedule, currency is empty and the amount is 0, so formatMoney
  // would fabricate an "EUR 0.00" balance implying a genuine zero owing.
  const hasSchedule = totalNum > 0 && !!currency;

  return (
    <section
      aria-labelledby="payments-heading"
      data-testid="payments-section"
      className="rounded-2xl border border-border-light bg-surface-elevated p-5 scroll-mt-4"
    >
      <div className="flex items-baseline justify-between gap-3 flex-wrap">
        <h2
          id="payments-heading"
          className="text-sm font-semibold text-content-primary"
        >
          {t('buyer_portal.payments.title', {
            defaultValue: 'Payment schedule',
          })}
        </h2>
        {hasSchedule && (
          <div className="text-xs text-content-tertiary">
            {t('buyer_portal.payments.outstanding', {
              defaultValue: 'Outstanding: {{value}}',
              value: formatMoney(totalOutstanding, currency, locale),
            })}
          </div>
        )}
      </div>

      {/* Sum bar — paid vs total */}
      {totalNum > 0 && (
        <div
          className="mt-3 space-y-1.5"
          aria-label={t('buyer_portal.payments.progress_label', {
            defaultValue: 'Payment progress',
          })}
        >
          <div className="flex items-center justify-between text-xs">
            <span className="text-content-secondary tabular-nums">
              {formatMoney(totalPaid, currency, locale)}
              <span className="text-content-tertiary"> / </span>
              {formatMoney(totalValue, currency, locale)}
            </span>
            <span className="text-content-tertiary tabular-nums">
              {Math.round(paidPct)}%
            </span>
          </div>
          <div
            className="h-2 w-full overflow-hidden rounded-full bg-surface-secondary"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(paidPct)}
          >
            <div
              className="h-full bg-semantic-success transition-all"
              style={{ width: `${paidPct}%` }}
              data-testid="payment-progress-fill"
            />
          </div>
        </div>
      )}

      {instalments.length === 0 ? (
        <p className="mt-3 text-xs text-content-tertiary">
          {t('buyer_portal.payments.empty', {
            defaultValue:
              'No payment schedule has been issued yet. Your agent will share it once your contract is finalised.',
          })}
        </p>
      ) : (
        <>
          {/* Mobile (<sm): timeline cards. Each card is tappable to open
              a detail drawer. Touch target is the full card surface,
              far exceeding 44x44. */}
          <ol
            className="mt-4 space-y-2 sm:hidden"
            aria-label={t('buyer_portal.payments.timeline_label', {
              defaultValue: 'Payment milestones',
            })}
          >
            {instalments.map((row) => (
              <li key={row.id} data-testid={`installment-row-${row.sequence}`}>
                <button
                  type="button"
                  onClick={() => setSelected(row)}
                  className={`w-full text-left rounded-xl border p-3 transition-colors ${instalmentTimelineColor(row.status)}`}
                  aria-label={t('buyer_portal.payments.open_detail', {
                    defaultValue: 'Open instalment {{n}} details',
                    n: row.sequence,
                  })}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-2xs uppercase tracking-wide text-content-tertiary">
                      {t('buyer_portal.payments.milestone_n', {
                        defaultValue: 'Milestone {{n}}',
                        n: row.sequence,
                      })}
                    </span>
                    <InstalmentStatusPill status={row.status} />
                  </div>
                  <div className="mt-1 text-sm font-medium text-content-primary">
                    {row.milestone_label ||
                      t('buyer_portal.na', { defaultValue: '—' })}
                  </div>
                  <div className="mt-1 flex items-baseline justify-between gap-2">
                    <span className="text-xs text-content-secondary">
                      {row.due_date
                        ? formatDate(row.due_date)
                        : t('buyer_portal.na', { defaultValue: '—' })}
                    </span>
                    <span className="text-sm font-semibold tabular-nums text-content-primary">
                      {formatMoney(row.amount, row.currency, locale)}
                    </span>
                  </div>
                </button>
              </li>
            ))}
          </ol>

          {/* Tablet+ (>=sm): traditional table */}
          <div className="mt-3 hidden sm:block overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-2xs uppercase tracking-wide text-content-tertiary">
                  <th className="py-2 pr-3">#</th>
                  <th className="py-2 pr-3">
                    {t('buyer_portal.payments.milestone', {
                      defaultValue: 'Milestone',
                    })}
                  </th>
                  <th className="py-2 pr-3">
                    {t('buyer_portal.payments.due', { defaultValue: 'Due' })}
                  </th>
                  <th className="py-2 pr-3 text-right">
                    {t('buyer_portal.payments.amount', {
                      defaultValue: 'Amount',
                    })}
                  </th>
                  <th className="py-2 pr-3 text-right">
                    {t('buyer_portal.payments.paid', {
                      defaultValue: 'Paid',
                    })}
                  </th>
                  <th className="py-2 pr-1">
                    {t('buyer_portal.payments.status', {
                      defaultValue: 'Status',
                    })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {instalments.map((row) => (
                  <tr
                    key={row.id}
                    onClick={() => setSelected(row)}
                    className="border-t border-border-light/50 cursor-pointer hover:bg-surface-secondary/50"
                  >
                    <td className="py-2 pr-3 tabular-nums text-content-tertiary">
                      {row.sequence}
                    </td>
                    <td className="py-2 pr-3 text-content-primary">
                      {row.milestone_label || '—'}
                    </td>
                    <td className="py-2 pr-3 text-content-secondary">
                      {row.due_date
                        ? formatDate(row.due_date)
                        : '—'}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums text-content-primary">
                      {formatMoney(row.amount, row.currency, locale)}
                    </td>
                    <td className="py-2 pr-3 text-right tabular-nums text-content-secondary">
                      {formatMoney(row.amount_paid, row.currency, locale)}
                    </td>
                    <td className="py-2 pr-1">
                      <InstalmentStatusPill status={row.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {selected && (
        <InstalmentDetailDrawer
          row={selected}
          locale={locale}
          onClose={() => setSelected(null)}
        />
      )}
    </section>
  );
}

function instalmentTimelineColor(
  status: PortalInstalmentRow['status'],
): string {
  switch (status) {
    case 'paid':
      return 'border-semantic-success/40 bg-semantic-success/5';
    case 'overdue':
      return 'border-semantic-error/40 bg-semantic-error/5';
    case 'due':
      return 'border-amber-300/60 bg-amber-50 dark:bg-amber-900/10';
    case 'waived':
    case 'cancelled':
      return 'border-border-light/60 bg-surface-secondary/30';
    case 'pending':
    default:
      return 'border-border-light bg-surface-primary';
  }
}

function InstalmentDetailDrawer({
  row,
  locale,
  onClose,
}: {
  row: PortalInstalmentRow;
  locale: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();

  // Escape closes — keep parity with the rest of the app's drawer pattern.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-end sm:items-center sm:justify-center"
      onClick={onClose}
    >
      <div className="absolute inset-0 bg-black/40" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('buyer_portal.payments.detail_label', {
          defaultValue: 'Instalment details',
        })}
        onClick={(e) => e.stopPropagation()}
        className="relative w-full sm:w-[28rem] max-h-[90vh] overflow-y-auto rounded-t-2xl sm:rounded-2xl bg-surface-elevated shadow-2xl p-5 space-y-4"
        data-testid="instalment-detail-drawer"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-2xs uppercase tracking-wide text-content-tertiary">
              {t('buyer_portal.payments.milestone_n', {
                defaultValue: 'Milestone {{n}}',
                n: row.sequence,
              })}
            </p>
            <h3 className="text-base font-semibold text-content-primary">
              {row.milestone_label ||
                t('buyer_portal.na', { defaultValue: '—' })}
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="min-h-11 min-w-11 grid place-items-center rounded-md text-content-tertiary hover:text-content-primary hover:bg-surface-secondary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={18} />
          </button>
        </div>

        <dl className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
              {t('buyer_portal.payments.due', { defaultValue: 'Due' })}
            </dt>
            <dd className="text-content-primary">
              {row.due_date ? formatDate(row.due_date) : '—'}
            </dd>
          </div>
          <div>
            <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
              {t('buyer_portal.payments.status', { defaultValue: 'Status' })}
            </dt>
            <dd>
              <InstalmentStatusPill status={row.status} />
            </dd>
          </div>
          <div>
            <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
              {t('buyer_portal.payments.amount', { defaultValue: 'Amount' })}
            </dt>
            <dd className="text-content-primary font-medium tabular-nums">
              {formatMoney(row.amount, row.currency, locale)}
            </dd>
          </div>
          <div>
            <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
              {t('buyer_portal.payments.paid', { defaultValue: 'Paid' })}
            </dt>
            <dd className="text-content-primary font-medium tabular-nums">
              {formatMoney(row.amount_paid, row.currency, locale)}
            </dd>
          </div>
          <div>
            <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
              {t('buyer_portal.payments.outstanding_label', {
                defaultValue: 'Outstanding',
              })}
            </dt>
            <dd className="text-content-primary font-medium tabular-nums">
              {formatMoney(row.amount_outstanding, row.currency, locale)}
            </dd>
          </div>
          {row.paid_at && (
            <div>
              <dt className="text-2xs uppercase tracking-wide text-content-tertiary">
                {t('buyer_portal.payments.paid_at', {
                  defaultValue: 'Paid on',
                })}
              </dt>
              <dd className="text-content-primary">
                {formatDate(row.paid_at)}
              </dd>
            </div>
          )}
        </dl>

        <p className="text-2xs text-content-tertiary border-t border-border-light/50 pt-3">
          {t('buyer_portal.payments.detail_hint', {
            defaultValue:
              'To pay or download a receipt, contact your sales agent. Online payment is not yet enabled in your jurisdiction.',
          })}
        </p>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Documents library: grouped by category, with icons + metadata
// ─────────────────────────────────────────────────────────────────────

function DocumentsSection({
  documents,
}: {
  documents: PortalDocumentRow[];
}) {
  const { t } = useTranslation();

  // Group by doc_type so the buyer sees "Contracts (2)", "Invoices (4)"
  // rather than a flat alphabetised mess. Stable insertion order keeps
  // the most-recently-delivered groups near the top within each bucket.
  const grouped = useMemo(() => {
    const m = new Map<string, PortalDocumentRow[]>();
    for (const doc of documents) {
      const key = doc.doc_type || 'other';
      const arr = m.get(key) || [];
      arr.push(doc);
      m.set(key, arr);
    }
    return Array.from(m.entries());
  }, [documents]);

  return (
    <section
      aria-labelledby="documents-heading"
      data-testid="documents-section"
      className="rounded-2xl border border-border-light bg-surface-elevated p-5 scroll-mt-4"
    >
      <h2
        id="documents-heading"
        className="text-sm font-semibold text-content-primary"
      >
        {t('buyer_portal.documents.title', {
          defaultValue: 'Documents',
        })}
      </h2>

      {documents.length === 0 ? (
        <p className="mt-3 text-xs text-content-tertiary">
          {t('buyer_portal.documents.empty', {
            defaultValue: 'No signed documents are available yet.',
          })}
        </p>
      ) : (
        <div className="mt-3 space-y-4">
          {grouped.map(([category, docs]) => (
            <div key={category}>
              <h3 className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary mb-1.5">
                {t(`buyer_portal.documents.cat.${category}`, {
                  defaultValue: DOCUMENTS_CAT_LABELS[category] ?? prettifyDocType(category),
                })}{' '}
                <span className="text-content-quaternary">({docs.length})</span>
              </h3>
              <ul className="space-y-2">
                {docs.map((doc) => (
                  <li key={doc.id}>
                    <a
                      href={doc.download_url}
                      target="_blank"
                      rel="noreferrer"
                      data-testid={`download-${doc.id}`}
                      className="flex items-center justify-between gap-3 rounded-lg border border-border-light/50 px-3 py-3 sm:py-2 hover:bg-surface-secondary/50 transition-colors min-h-11"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <DocumentIcon type={doc.doc_type} title={doc.title} />
                        <div className="min-w-0">
                          <p className="text-sm text-content-primary truncate">
                            {doc.title}
                          </p>
                          <p className="text-2xs text-content-tertiary">
                            {doc.delivered_at
                              ? t('buyer_portal.documents.delivered_on', {
                                  defaultValue: 'Delivered {{date}}',
                                  date: formatDate(doc.delivered_at),
                                })
                              : t('buyer_portal.documents.no_date', {
                                  defaultValue: 'Delivery date pending',
                                })}
                          </p>
                        </div>
                      </div>
                      <span className="shrink-0 inline-flex items-center gap-1 text-xs font-medium text-oe-blue">
                        <Eye size={12} aria-hidden />
                        <span className="hidden sm:inline">
                          {t('buyer_portal.documents.open', {
                            defaultValue: 'Open',
                          })}
                        </span>
                      </span>
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function DocumentIcon({ type, title }: { type: string; title: string }) {
  // Filename-suffix sniff for the icon. We do not have MIME on the wire,
  // so we infer from the trailing extension on the title. Falls back
  // to a document icon for anything we can't classify.
  const lower = (title || '').toLowerCase();
  const isImage =
    /\.(png|jpe?g|gif|webp|heic|heif)$/i.test(lower) ||
    type === 'photo' ||
    type === 'image';
  const Icon = isImage ? FileImage : FileText;
  return (
    <span
      aria-hidden
      className="shrink-0 grid place-items-center w-8 h-8 rounded-md bg-surface-secondary text-content-secondary"
    >
      <Icon size={16} />
    </span>
  );
}

function prettifyDocType(s: string): string {
  if (!s) return 'Other';
  return s
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// ─────────────────────────────────────────────────────────────────────
// KYC section: drag-drop dropzone per request, multi-file staging
// ─────────────────────────────────────────────────────────────────────

function KycSection({
  kycRequests,
  pendingByCode,
  batchErrorByCode,
  dragTarget,
  setDragTarget,
  stageFiles,
  uploadAllFor,
  removePending,
  clearBatchError,
}: {
  kycRequests: PortalOverviewResponse['kyc_requests'];
  pendingByCode: Record<string, PendingFile[]>;
  batchErrorByCode: Record<string, string | null>;
  dragTarget: string | null;
  setDragTarget: (s: string | null) => void;
  stageFiles: (code: PortalKycCode, files: FileList | File[]) => void;
  uploadAllFor: (code: PortalKycCode) => Promise<void>;
  removePending: (code: string, id: string) => void;
  clearBatchError: (code: string) => void;
}) {
  const { t } = useTranslation();
  return (
    <section
      aria-labelledby="kyc-heading"
      data-testid="kyc-section"
      className="rounded-2xl border border-border-light bg-surface-elevated p-5 scroll-mt-4"
    >
      <h2
        id="kyc-heading"
        className="text-sm font-semibold text-content-primary"
      >
        {t('buyer_portal.kyc.title', {
          defaultValue: 'Documents we need from you',
        })}
      </h2>
      {kycRequests.length === 0 ? (
        <p className="mt-3 text-xs text-content-tertiary">
          {t('buyer_portal.kyc.empty', {
            defaultValue: 'No documents requested at this time.',
          })}
        </p>
      ) : (
        <ul className="mt-3 space-y-3">
          {kycRequests.map((req) => (
            <KycRequestRow
              key={req.code}
              code={req.code as PortalKycCode}
              label={req.label}
              description={req.description}
              isUploaded={req.is_uploaded}
              pending={pendingByCode[req.code] || []}
              batchError={batchErrorByCode[req.code] || null}
              isDragActive={dragTarget === req.code}
              onDragEnter={() => setDragTarget(req.code)}
              onDragLeave={() => setDragTarget(null)}
              onStage={(files) => stageFiles(req.code as PortalKycCode, files)}
              onUploadAll={() => uploadAllFor(req.code as PortalKycCode)}
              onRemove={(id) => removePending(req.code, id)}
              onDismissBatchError={() => clearBatchError(req.code)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function KycRequestRow({
  code,
  label,
  description,
  isUploaded,
  pending,
  batchError,
  isDragActive,
  onDragEnter,
  onDragLeave,
  onStage,
  onUploadAll,
  onRemove,
  onDismissBatchError,
}: {
  code: PortalKycCode;
  label: string;
  description: string;
  isUploaded: boolean;
  pending: PendingFile[];
  batchError: string | null;
  isDragActive: boolean;
  onDragEnter: () => void;
  onDragLeave: () => void;
  onStage: (files: FileList | File[]) => void;
  onUploadAll: () => Promise<void>;
  onRemove: (id: string) => void;
  onDismissBatchError: () => void;
}) {
  const { t } = useTranslation();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);

  const isUploading = pending.some((p) => p.status === 'uploading');
  const successCount = pending.filter((p) => p.status === 'success').length;
  const errorCount = pending.filter((p) => p.status === 'error').length;

  // Drag-and-drop handlers. We accept dragenter on the dropzone wrapper,
  // and call preventDefault on dragover so the browser does not navigate
  // to the dropped file. Native input still wins on mobile where there
  // is no drag affordance.
  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
    onDragLeave();
    const files = e.dataTransfer?.files;
    if (files && files.length > 0) onStage(files);
  }
  function onDragOver(e: DragEvent<HTMLDivElement>) {
    e.preventDefault();
  }

  return (
    <li
      className="rounded-xl border border-border-light/60 p-3"
      data-testid={`kyc-request-${code}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-content-primary flex items-center gap-2">
            {label}
            {isUploaded && (
              <CheckCircle2
                size={14}
                className="text-semantic-success"
                aria-label={t('buyer_portal.kyc.uploaded', {
                  defaultValue: 'Uploaded',
                })}
              />
            )}
          </p>
          {description && (
            <p className="mt-0.5 text-2xs text-content-tertiary">
              {description}
            </p>
          )}
        </div>
      </div>

      {/* Dropzone — drag-and-drop on desktop, taps below on mobile. */}
      <div
        onDragEnter={onDragEnter}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        className={`mt-3 rounded-lg border-2 border-dashed p-4 text-center transition-colors ${
          isDragActive
            ? 'border-oe-blue bg-oe-blue/5'
            : 'border-border-light/80 bg-surface-secondary/30'
        }`}
        data-testid={`kyc-dropzone-${code}`}
      >
        <p className="hidden sm:block text-2xs text-content-tertiary">
          {t('buyer_portal.kyc.dropzone_hint', {
            defaultValue: 'Drag and drop one or more files here, or',
          })}
        </p>
        <div className="mt-1 flex flex-wrap justify-center gap-2">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="inline-flex items-center justify-center gap-1.5 min-h-11 px-3 rounded-md bg-surface-primary border border-border-light text-xs font-medium text-content-primary hover:bg-surface-secondary"
            data-testid={`kyc-upload-${code}`}
            disabled={isUploading}
          >
            <Upload size={14} aria-hidden />
            {t('buyer_portal.kyc.pick_files', {
              defaultValue: 'Choose files',
            })}
          </button>
          {/* Camera capture button — mobile only. The accept+capture combo
              opens the camera directly on iOS/Android for passport scans.
              Hidden on >=sm because desktops misroute capture to webcams
              which is rarely what the buyer wants. */}
          <button
            type="button"
            onClick={() => cameraInputRef.current?.click()}
            className="sm:hidden inline-flex items-center justify-center gap-1.5 min-h-11 px-3 rounded-md bg-surface-primary border border-border-light text-xs font-medium text-content-primary hover:bg-surface-secondary"
            data-testid={`kyc-camera-${code}`}
            disabled={isUploading}
          >
            <Camera size={14} aria-hidden />
            {t('buyer_portal.kyc.take_photo', {
              defaultValue: 'Take photo',
            })}
          </button>
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPT_KYC_TYPES}
          multiple
          className="sr-only"
          onChange={(e: ChangeEvent<HTMLInputElement>) => {
            if (e.target.files) onStage(e.target.files);
            e.target.value = '';
          }}
          aria-label={t('buyer_portal.kyc.pick_files_aria', {
            defaultValue: 'Pick files for {{label}}',
            label,
          })}
        />
        <input
          ref={cameraInputRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="sr-only"
          onChange={(e: ChangeEvent<HTMLInputElement>) => {
            if (e.target.files) onStage(e.target.files);
            e.target.value = '';
          }}
          aria-label={t('buyer_portal.kyc.camera_aria', {
            defaultValue: 'Take photo for {{label}}',
            label,
          })}
        />
      </div>

      {/* Staged-file preview chips. Each chip shows filename + size and
          a remove button. Status colour changes as the upload runs. */}
      {pending.length > 0 && (
        <ul
          className="mt-3 space-y-1.5"
          aria-label={t('buyer_portal.kyc.staged_label', {
            defaultValue: 'Files staged for upload',
          })}
        >
          {pending.map((p) => (
            <li
              key={p.id}
              className={`flex items-center justify-between gap-2 rounded-md px-2.5 py-2 text-xs ${stagedChipColor(p.status)}`}
              data-testid={`kyc-pending-${code}-${p.status}`}
            >
              <div className="flex items-center gap-2 min-w-0">
                <FileText size={12} aria-hidden className="shrink-0" />
                <span className="truncate font-medium" title={p.file.name}>
                  {p.file.name}
                </span>
                <span className="shrink-0 text-content-tertiary">
                  {humanFileSize(p.file.size)}
                </span>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                {p.status === 'uploading' && (
                  <Loader2 size={12} className="animate-spin" aria-hidden />
                )}
                {p.status === 'success' && (
                  <CheckCircle2
                    size={12}
                    aria-label={t('buyer_portal.kyc.upload_ok', {
                      defaultValue: 'Uploaded',
                    })}
                  />
                )}
                {p.status === 'error' && p.errorMsg && (
                  <span className="text-semantic-error truncate max-w-[10rem]" title={p.errorMsg}>
                    {p.errorMsg}
                  </span>
                )}
                {p.status !== 'uploading' && p.status !== 'success' && (
                  <button
                    type="button"
                    onClick={() => onRemove(p.id)}
                    className="min-h-8 min-w-8 grid place-items-center rounded text-content-tertiary hover:text-content-primary hover:bg-surface-secondary"
                    aria-label={t('buyer_portal.kyc.remove_file', {
                      defaultValue: 'Remove {{name}}',
                      name: p.file.name,
                    })}
                  >
                    <Trash2 size={12} />
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* Upload-all action + summary */}
      {pending.length > 0 && (
        <div className="mt-3 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-2">
          <p className="text-2xs text-content-tertiary" role="status">
            {t('buyer_portal.kyc.summary', {
              defaultValue:
                '{{ready}} ready · {{ok}} uploaded · {{err}} failed',
              ready: pending.filter((p) => p.status === 'pending').length,
              ok: successCount,
              err: errorCount,
            })}
          </p>
          <button
            type="button"
            onClick={onUploadAll}
            disabled={isUploading || pending.every((p) => p.status === 'success')}
            className="inline-flex items-center justify-center gap-2 min-h-11 px-4 rounded-md bg-oe-blue text-white text-xs font-medium hover:bg-oe-blue-hover disabled:opacity-50"
            data-testid={`kyc-submit-${code}`}
          >
            {isUploading ? (
              <Loader2 size={14} className="animate-spin" aria-hidden />
            ) : (
              <Upload size={14} aria-hidden />
            )}
            {t('buyer_portal.kyc.upload_all', {
              defaultValue: 'Upload {{n}} file(s)',
              n: pending.filter((p) => p.status !== 'success').length,
            })}
          </button>
        </div>
      )}

      {/* RecoveryCard-style batch error (rejected files at staging step) */}
      {batchError && (
        <div
          role="alert"
          data-testid={`kyc-batch-error-${code}`}
          className="mt-3 flex items-start justify-between gap-2 rounded-lg border border-semantic-error/30 bg-semantic-error/5 px-3 py-2"
        >
          <div className="flex items-start gap-2">
            <AlertTriangle
              size={14}
              className="text-semantic-error shrink-0 mt-0.5"
              aria-hidden
            />
            <p className="text-xs text-semantic-error">{batchError}</p>
          </div>
          <button
            type="button"
            onClick={onDismissBatchError}
            className="min-h-8 min-w-8 grid place-items-center rounded text-semantic-error hover:bg-semantic-error/10"
            aria-label={t('common.dismiss', { defaultValue: 'Dismiss' })}
          >
            <X size={12} />
          </button>
        </div>
      )}
    </li>
  );
}

function stagedChipColor(status: PendingFile['status']): string {
  switch (status) {
    case 'success':
      return 'bg-semantic-success/10 text-semantic-success';
    case 'error':
      return 'bg-semantic-error/10 text-semantic-error';
    case 'uploading':
      return 'bg-oe-blue/10 text-oe-blue';
    case 'pending':
    default:
      return 'bg-surface-secondary text-content-secondary';
  }
}

function humanFileSize(bytes: number): string {
  if (!isFinite(bytes) || bytes <= 0) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let v = bytes;
  let u = 0;
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024;
    u++;
  }
  return `${fmtFixed(v, v >= 10 || u === 0 ? 0 : 1)} ${units[u]}`;
}

// ─────────────────────────────────────────────────────────────────────
// Mobile sticky CTA bar
// ─────────────────────────────────────────────────────────────────────

function MobileCtaBar({
  hasOutstanding,
  hasPendingKyc,
  nextDueAmount,
  nextDueCurrency,
  locale,
}: {
  hasOutstanding: boolean;
  hasPendingKyc: boolean;
  nextDueAmount?: string;
  nextDueCurrency?: string;
  locale: string;
}) {
  const { t } = useTranslation();
  // Decide priority: pay > kyc > contact. Only one slot, so we never
  // overload the buyer's thumb-reach zone with competing CTAs.
  let label: string;
  let href: string;
  let testId: string;
  if (hasOutstanding) {
    label = nextDueAmount && nextDueCurrency
      ? t('buyer_portal.mobile_cta.pay_amount', {
          defaultValue: 'Pay next · {{value}}',
          value: formatMoney(nextDueAmount, nextDueCurrency, locale),
        })
      : t('buyer_portal.mobile_cta.pay', {
          defaultValue: 'Pay next instalment',
        });
    href = '#payments-heading';
    testId = 'mobile-cta-pay';
  } else if (hasPendingKyc) {
    label = t('buyer_portal.mobile_cta.kyc', {
      defaultValue: 'Upload required documents',
    });
    href = '#kyc-heading';
    testId = 'mobile-cta-kyc';
  } else {
    label = t('buyer_portal.mobile_cta.contact', {
      defaultValue: 'Contact your agent',
    });
    href = '#contact-heading';
    testId = 'mobile-cta-contact';
  }
  return (
    <div
      className="sm:hidden fixed bottom-0 inset-x-0 z-40 border-t border-border-light bg-surface-elevated/95 backdrop-blur supports-[backdrop-filter]:bg-surface-elevated/80 p-3 pb-[max(env(safe-area-inset-bottom),0.75rem)]"
      data-testid="mobile-cta-bar"
    >
      <a
        href={href}
        data-testid={testId}
        className="flex items-center justify-center gap-2 min-h-12 w-full rounded-xl bg-oe-blue text-white text-sm font-semibold hover:bg-oe-blue-hover"
      >
        {hasOutstanding ? (
          <CreditCard size={16} aria-hidden />
        ) : hasPendingKyc ? (
          <Upload size={16} aria-hidden />
        ) : (
          <Phone size={16} aria-hidden />
        )}
        {label}
      </a>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────
// Tiny helper components & utilities (unchanged from v4.6.1)
// ─────────────────────────────────────────────────────────────────────

function ShellWrapper({
  children,
  buyerName,
  locale,
}: {
  children: React.ReactNode;
  buyerName?: string;
  locale?: string;
}) {
  const { t, i18n } = useTranslation();

  // Drive the switcher from the full shipped locale catalogue (not a
  // hard-coded en/de/ru subset) so a buyer in any of the supported
  // languages can pick their own. A native <select> keeps all 27
  // options accessible and compact in the header.
  const currentLang =
    SUPPORTED_LANGUAGES.find((l) => (locale || i18n.language).startsWith(l.code))
      ?.code ?? 'en';

  return (
    <div className="min-h-screen bg-gradient-to-br from-surface-secondary via-surface-primary to-surface-elevated">
      <header className="w-full border-b border-border-light bg-surface-primary/80 backdrop-blur supports-[backdrop-filter]:bg-surface-primary/60">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-3 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <div
              className="w-8 h-8 rounded-md bg-oe-blue text-white grid place-items-center text-sm font-bold"
              aria-hidden
            >
              OE
            </div>
            <span className="text-sm font-medium text-content-primary">
              {t('buyer_portal.brand', {
                defaultValue: 'Buyer portal',
              })}
            </span>
          </div>
          {buyerName && (
            <span className="hidden sm:block text-xs text-content-tertiary truncate max-w-[40ch]">
              {t('buyer_portal.header.greeting', {
                defaultValue: 'Welcome, {{name}}',
                name: buyerName,
              })}
            </span>
          )}
          <ModuleGuideButton content={buyerPortalGuide} className="ml-auto" />
          <nav
            aria-label={t('buyer_portal.locale.label', {
              defaultValue: 'Language',
            })}
            className="flex items-center gap-1"
          >
            <label htmlFor="buyer-portal-locale" className="sr-only">
              {t('buyer_portal.locale.label', { defaultValue: 'Language' })}
            </label>
            <select
              id="buyer-portal-locale"
              value={currentLang}
              onChange={(e) => i18n.changeLanguage(e.target.value)}
              className="min-h-11 text-xs font-medium px-2 py-1 rounded border border-border-light bg-surface-primary text-content-secondary hover:bg-surface-secondary focus:outline-none focus:ring-2 focus:ring-oe-blue"
              data-testid="locale-select"
            >
              {SUPPORTED_LANGUAGES.map((loc) => (
                <option key={loc.code} value={loc.code}>
                  {loc.name}
                </option>
              ))}
            </select>
          </nav>
        </div>
      </header>

      {children}

      <footer className="w-full border-t border-border-light mt-10">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-4 text-2xs text-content-tertiary flex items-center justify-between gap-3 flex-wrap">
          <span>
            {t('buyer_portal.footer.contact', {
              defaultValue: 'Questions? Email',
            })}{' '}
            <a
              href="mailto:info@datadrivenconstruction.io"
              className="text-oe-blue hover:underline"
            >
              info@datadrivenconstruction.io
            </a>
          </span>
          <a
            href="https://www.gnu.org/licenses/agpl-3.0.html"
            target="_blank"
            rel="noreferrer"
            className="hover:underline"
          >
            AGPL-3.0
          </a>
        </div>
      </footer>
    </div>
  );
}

// Humanize a raw backend enum (``countersigned`` → ``Countersigned``) as
// the i18n fallback so a status without an explicit translation still
// reads cleanly instead of leaking the snake_case enum to the buyer.
function humanizeStatus(status: string): string {
  if (!status) return '';
  return status
    .split('_')
    .map((w) => (w ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(' ');
}

function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  const tone =
    status === 'active' || status === 'signed' || status === 'countersigned'
      ? 'bg-semantic-success/10 text-semantic-success'
      : status === 'cancelled' || status === 'expired'
        ? 'bg-semantic-error/10 text-semantic-error'
        : 'bg-surface-secondary text-content-secondary';
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-2xs font-medium ${tone}`}
    >
      {t(`buyer_portal.status.${status}`, {
        defaultValue: humanizeStatus(status),
      })}
    </span>
  );
}

function InstalmentStatusPill({
  status,
}: {
  status: PortalInstalmentRow['status'];
}) {
  const { t } = useTranslation();
  const tone =
    status === 'paid'
      ? 'bg-semantic-success/10 text-semantic-success'
      : status === 'overdue'
        ? 'bg-semantic-error/10 text-semantic-error'
        : status === 'due'
          ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300'
          : status === 'waived' || status === 'cancelled'
            ? 'bg-surface-secondary text-content-tertiary'
            : 'bg-surface-secondary text-content-secondary';
  return (
    <span
      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-2xs font-medium ${tone}`}
    >
      {status === 'overdue' && <Clock size={10} aria-hidden />}
      {t(`buyer_portal.status.${status}`, {
        defaultValue: humanizeStatus(status),
      })}
    </span>
  );
}

function formatMoney(amount: string, currency: string, locale: string): string {
  // Money is on the wire as a plain-decimal string (R7 convention).
  // We parse to Number for display — precision is fine at the
  // ≤12-digit values typical of property pricing. For pure
  // ledger-correctness we'd keep Decimal end-to-end, but the buyer
  // portal is a display surface.
  //
  // The buyer is the one person on this page who cannot ask anybody what the
  // number means, so it is formatted by the module that owns money rather
  // than here. The formatter this replaces capped every currency at two
  // decimals with no floor under it: a yen instalment of 1234.50 read
  // "1.234,5 ¥" for a currency with no subunit, and a dinar instalment lost
  // its third digit - on an engine without the ES2023 digit clamping it threw
  // a `RangeError` and took the portal down with it, since a floor of three
  // cannot sit under a ceiling of two. It also stamped a euro sign on a blank
  // currency; `formatCurrency` prints a bare grouped number instead, and the
  // one caller that can reach a blank currency already hides the figure.
  if (!amount) return '';
  const value = Number(amount);
  if (!isFinite(value)) return amount;
  return formatCurrency(value, currency, locale);
}

/**
 * A date, in the reader's language rather than in their number format.
 *
 * Takes no locale on purpose. Every caller here has the money locale to hand,
 * so a locale parameter is a parameter that gets the wrong argument: this
 * picks a month name, and which month names a reader knows is their language,
 * not the convention they chose for grouping digits. Somebody who reads
 * English and writes numbers the German way wants "Aug", not "Aug.".
 */
function formatDate(iso: string): string {
  if (!iso) return '';
  try {
    // Due dates and the signing date are plain calendar dates: keep their day.
    return formatDateValue(iso, { year: 'numeric', month: 'short', day: 'numeric' });
  } catch {
    return iso;
  }
}
