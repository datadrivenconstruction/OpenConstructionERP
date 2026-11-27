// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, Ban } from 'lucide-react';
import { apiGet, apiPost } from '@/shared/lib/api';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { isDecimalString } from '@/shared/lib/exactDecimal';

/** One order or subcontract agreement, net of VAT, in its own currency (CommitmentResponse). */
export interface Commitment {
  kind: 'purchase_order' | 'subcontract';
  id: string;
  ref: string;
  status: string;
  currency_code: string;
  original: string;
  approved_changes: string;
  revised: string;
  invoiced: string;
  remaining: string;
  paid: string;
  retention_percent: string;
  invoices_in_other_currency: number;
  shared_change_orders: number;
}

interface PostingResult {
  rule_id: string;
  severity: string;
  passed: boolean;
  message: string;
  suggestion?: string | null;
}

/** The certificate summary with this invoice added (net of VAT): A, B, A - B, C, A - B - C, balance. */
export interface PaySummary {
  completed_to_date: string;
  retention: string;
  earned_less_retention: string;
  previously_certified: string;
  current_due: string;
  balance_to_finish: string;
}

export interface PostingCheck {
  commitment: Commitment | null;
  summary?: PaySummary | null;
  blocking: boolean;
  report: { results: PostingResult[] };
}

/** The invoice as typed, in the shape `POST /v1/finance/invoices/posting-check/` reads. */
export interface PostingCheckInput {
  project_id: string;
  invoice_id?: string;
  contact_id?: string;
  invoice_number?: string;
  invoice_date?: string;
  due_date?: string;
  scheduled_payment_date?: string;
  currency_code?: string;
  amount_subtotal: string;
  retention_amount?: string;
  purchase_order_id?: string;
  subcontract_agreement_id?: string;
}

/** The first refusal approval would meet, as one sentence, or null when approval would go through. */
export function blockingReason(check: PostingCheck | undefined): string | null {
  const error = check?.report?.results?.find((r) => !r.passed && r.severity === 'error');
  return error ? error.message : null;
}

export function usePostingCheck(input: PostingCheckInput, enabled: boolean) {
  return useQuery({
    queryKey: ['finance-posting-check', input],
    queryFn: () => apiPost<PostingCheck>('/v1/finance/invoices/posting-check/', input),
    enabled: enabled && !!input.project_id,
  });
}

/** The project's subcontract agreements with this supplier; empty where the subcontractors module is absent. */
export function useSubcontractCommitments(projectId: string, contactId: string) {
  return useQuery({
    queryKey: ['finance-commitments', projectId, contactId],
    queryFn: () =>
      apiGet<Commitment[]>(
        `/v1/finance/commitments/?project_id=${encodeURIComponent(projectId)}&contact_id=${encodeURIComponent(contactId)}`,
      ),
    enabled: !!projectId && !!contactId,
    select: (rows) => rows.filter((c) => c.kind === 'subcontract'),
  });
}

function Figure({ label, amount, currency, testId }: { label: string; amount: string; currency: string; testId: string }) {
  return (
    <div data-testid={testId}>
      <dt className="text-content-tertiary">{label}</dt>
      <dd className="tabular-nums font-medium text-content-primary">
        <MoneyDisplay amount={isDecimalString(amount) ? amount : null} currency={currency} />
      </dd>
    </div>
  );
}

/**
 * What approving this invoice would meet: the commitment it bills (original,
 * approved changes, invoiced before, still open) and every posting rule that
 * fails. An error means approval will be refused; `onBlockingChange` hands
 * the reason to the caller so it can disable its submit and say why.
 */
export function InvoiceCommitmentCheck({
  input,
  onBlockingChange,
}: {
  input: PostingCheckInput;
  onBlockingChange?: (reason: string | null) => void;
}) {
  const { t } = useTranslation();
  // Weigh the figures once typing settles, not on every keystroke.
  const [settled, setSettled] = useState(input);
  const key = JSON.stringify(input);
  useEffect(() => {
    const handle = window.setTimeout(() => setSettled(JSON.parse(key) as PostingCheckInput), 400);
    return () => window.clearTimeout(handle);
  }, [key]);

  const { data } = usePostingCheck(settled, true);
  const reason = blockingReason(data);
  useEffect(() => {
    onBlockingChange?.(reason);
  }, [reason, onBlockingChange]);

  const failed = (data?.report?.results ?? []).filter((r) => !r.passed);
  const commitment = data?.commitment ?? null;
  const summary = data?.summary ?? null;
  if (!commitment && failed.length === 0) return null;

  const errors = failed.filter((r) => r.severity === 'error');
  const warnings = failed.filter((r) => r.severity !== 'error');
  let notes: ReactNode = null;
  if (commitment && (commitment.invoices_in_other_currency > 0 || commitment.shared_change_orders > 0)) {
    notes = (
      <p className="col-span-4 text-2xs text-content-tertiary" data-testid="invoice-commitment-notes">
        {commitment.invoices_in_other_currency > 0 &&
          t('finance.commitment_other_currency', {
            defaultValue: 'Invoices in another currency are not counted: {{n}}.',
            n: commitment.invoices_in_other_currency,
          })}{' '}
        {commitment.shared_change_orders > 0 &&
          t('finance.commitment_shared_changes', {
            defaultValue: 'Change orders linked to several orders are not counted: {{n}}.',
            n: commitment.shared_change_orders,
          })}
      </p>
    );
  }

  return (
    <div className="space-y-2" data-testid="invoice-commitment-check">
      {commitment && (
        <dl
          className="grid grid-cols-4 gap-2 rounded-lg border border-border-light bg-surface-secondary/50 px-3 py-2 text-xs"
          data-testid="invoice-commitment-figures"
        >
          <Figure
            testId="commitment-original"
            label={t('finance.commitment_original', { defaultValue: 'Original commitment' })}
            amount={commitment.original}
            currency={commitment.currency_code}
          />
          <Figure
            testId="commitment-changes"
            label={t('finance.commitment_approved_changes', { defaultValue: 'Approved changes' })}
            amount={commitment.approved_changes}
            currency={commitment.currency_code}
          />
          <Figure
            testId="commitment-invoiced"
            label={t('finance.po_link_invoiced', { defaultValue: 'Invoiced to date' })}
            amount={commitment.invoiced}
            currency={commitment.currency_code}
          />
          <Figure
            testId="commitment-remaining"
            label={t('finance.commitment_remaining', { defaultValue: 'Remaining commitment' })}
            amount={commitment.remaining}
            currency={commitment.currency_code}
          />
          <p className="col-span-4 text-2xs text-content-tertiary">
            {t('finance.basis_net', { defaultValue: 'Net of VAT' })}
          </p>
          {notes}
        </dl>
      )}

      {commitment && summary && (
        <table className="w-full text-xs" data-testid="invoice-pay-summary">
          <tbody>
            {(
              [
                ['completed_to_date', t('finance.pay_summary_completed', { defaultValue: 'A. Completed and stored to date' })],
                ['retention', t('finance.pay_summary_retention', { defaultValue: 'B. Retention' })],
                ['earned_less_retention', t('finance.pay_summary_earned', { defaultValue: 'Earned less retention (A - B)' })],
                ['previously_certified', t('finance.pay_summary_previous', { defaultValue: 'C. Previously certified' })],
                ['current_due', t('finance.pay_summary_current_due', { defaultValue: 'Current payment due (A - B - C)' })],
                ['balance_to_finish', t('finance.pay_summary_balance', { defaultValue: 'Balance to finish' })],
              ] as const
            ).map(([field, label]) => (
              <tr key={field} className={field === 'current_due' ? 'font-semibold' : undefined}>
                <td className="py-0.5 text-content-secondary">{label}</td>
                <td className="py-0.5 text-right tabular-nums" data-testid={`pay-summary-${field}`}>
                  <MoneyDisplay
                    amount={isDecimalString(summary[field]) ? summary[field] : null}
                    currency={commitment.currency_code}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {errors.length > 0 && (
        <div
          role="alert"
          className="rounded-lg border border-semantic-error/30 bg-semantic-error-bg px-3 py-2 text-xs text-semantic-error"
          data-testid="invoice-commitment-errors"
        >
          <p className="mb-1 font-medium">
            {t('finance.posting_blocked_title', { defaultValue: 'This invoice cannot be approved yet' })}
          </p>
          <ul className="space-y-1">
            {errors.map((r) => (
              <li key={r.rule_id} className="flex items-start gap-1.5">
                <Ban size={12} className="mt-0.5 shrink-0" />
                <span>
                  <span className="block">{r.message}</span>
                  {r.suggestion && <span className="block opacity-80">{r.suggestion}</span>}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {warnings.length > 0 && (
        <div
          className="rounded-lg border border-semantic-warning/30 bg-semantic-warning-bg px-3 py-2 text-xs text-semantic-warning"
          data-testid="invoice-commitment-warnings"
        >
          <ul className="space-y-1">
            {warnings.map((r) => (
              <li key={r.rule_id} className="flex items-start gap-1.5">
                <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                <span>{r.message}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/**
 * The subcontract agreement a payable bills, offered only when this supplier
 * has agreements on the project. A market without the subcontractors module
 * gets none and sees nothing.
 */
export function InvoiceSubcontractField({
  projectId,
  contactId,
  value,
  onChange,
  disabled,
}: {
  projectId: string;
  contactId: string;
  value: string;
  onChange: (agreementId: string) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const { data: agreements = [] } = useSubcontractCommitments(projectId, contactId);
  if (agreements.length === 0 && !value) return null;
  return (
    <select
      className="oe-select oe-input-lg w-full"
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      aria-label={t('finance.subcontract_link_label', { defaultValue: 'Subcontract agreement' })}
      data-testid="invoice-subcontract-select"
    >
      <option value="">{t('finance.subcontract_link_none', { defaultValue: 'Not linked to a subcontract' })}</option>
      {agreements.map((a) => (
        <option key={a.id} value={a.id}>
          {a.ref}
        </option>
      ))}
    </select>
  );
}

/** Whether a saved pending invoice would be refused on approval, and why. Only asks for invoices that bill a commitment or carry a planned payment date. */
export function useApprovalBlock(invoice: {
  id: string;
  project_id: string;
  status: string;
  contact_id?: string | null;
  invoice_number?: string;
  invoice_date?: string | null;
  scheduled_payment_date?: string | null;
  currency_code?: string | null;
  amount_subtotal?: string | null;
  retention_amount?: string | null;
  purchase_order_id?: string | null;
  subcontract_agreement_id?: string | null;
}): string | null {
  const relevant =
    invoice.status === 'pending' &&
    !!(invoice.purchase_order_id || invoice.subcontract_agreement_id || invoice.contact_id);
  const { data } = usePostingCheck(
    {
      project_id: invoice.project_id,
      invoice_id: invoice.id,
      contact_id: invoice.contact_id || undefined,
      invoice_number: invoice.invoice_number,
      invoice_date: invoice.invoice_date || undefined,
      scheduled_payment_date: invoice.scheduled_payment_date || undefined,
      currency_code: invoice.currency_code || '',
      amount_subtotal: invoice.amount_subtotal || '0',
      retention_amount: invoice.retention_amount || '0',
      purchase_order_id: invoice.purchase_order_id || undefined,
      subcontract_agreement_id: invoice.subcontract_agreement_id || undefined,
    },
    relevant,
  );
  return relevant ? blockingReason(data) : null;
}

/** Render-prop wrapper so a list row can ask {@link useApprovalBlock} without breaking the rules of hooks. */
export function InvoiceApprovalGate({
  invoice,
  children,
}: {
  invoice: Parameters<typeof useApprovalBlock>[0];
  children: (reason: string | null) => ReactNode;
}) {
  return <>{children(useApprovalBlock(invoice))}</>;
}
