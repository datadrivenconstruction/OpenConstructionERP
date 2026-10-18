// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One supplier invoice, from what it states to what is released for payment,
// one line per step. Every figure comes from the server; nothing is added up
// here. While the release is open a controller sets the invoice kind and the
// agreed deductions and sees the steps move; a manager then confirms it, which
// freezes the figures. Reopening is possible until a later invoice of the same
// contract builds on it.
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertOctagon, AlertTriangle, Info, Lock, Unlock } from 'lucide-react';

import { Badge, Button } from '@/shared/ui';
import { SideDrawer } from '@/shared/ui/SideDrawer';
import { fmtDate, fmtPercent } from '@/shared/lib/formatters';
// Release figures are amounts to pay: shown to the minor unit, never rounded to whole units.
import { formatCurrency as fmtMoney } from '@/shared/lib/money';
import { getErrorMessage } from '@/shared/lib/api';
import { stripCurrencySigns, toDecimalPayloadString } from '@/shared/lib/parseDecimal';
import { problemOf } from '@/features/costmodel/structureApi';
import { useToastStore } from '@/stores/useToastStore';
import { num } from './api';
import {
  INVOICE_KINDS,
  kindLabel,
  modeLabel,
  paymentProblem,
  paymentsApi,
  type InvoiceKind,
  type InvoiceReleaseUpdate,
  type LedgerContract,
  type LedgerInvoice,
  type ReleaseFigures,
  type ReleaseFinding,
} from './paymentsApi';

/** A typed amount in the reader's own spelling (`120,50`, `1.234,56 €`) as the dot-decimal string the API parses. */
export function moneyPayload(raw: string): string {
  return toDecimalPayloadString(stripCurrencySigns(raw), '0');
}

const INPUT = 'h-8 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm disabled:opacity-60';

interface Step {
  key: string;
  label: string;
  amount: string;
  /** '-' takes off, '=' a subtotal, '' a plain figure. */
  sign: '-' | '+' | '=' | '';
  note?: string;
  strong?: boolean;
}

/** The steps in the order the release is computed. Zero steps that change nothing are left out. */
export function releaseSteps(t: TFunction, f: ReleaseFigures, currency: string): Step[] {
  const steps: Step[] = [];
  steps.push({ key: 'net', sign: '', amount: f.net, label: t('cost_control.pay.step_net', { defaultValue: 'Net amount invoiced' }) });
  if (num(f.net_deduction) !== 0) {
    steps.push({ key: 'net_deduction', sign: '-', amount: f.net_deduction, label: t('cost_control.pay.step_net_deduction', { defaultValue: 'Agreed deduction on the net' }) });
    steps.push({ key: 'net_after', sign: '=', amount: f.net_after, label: t('cost_control.pay.step_net_after', { defaultValue: 'Net after deductions' }) });
  }
  steps.push({ key: 'vat', sign: '+', amount: f.vat_after, label: t('cost_control.pay.step_vat', { defaultValue: 'VAT' }),
    note: num(f.vat_deduction) !== 0
      ? t('cost_control.pay.step_vat_note', { defaultValue: 'less {{amount}} VAT on the deduction', amount: fmtMoney(f.vat_deduction, currency) })
      : undefined });
  if (num(f.gross_deduction) !== 0) {
    steps.push({ key: 'gross', sign: '=', amount: f.gross, label: t('cost_control.pay.step_gross', { defaultValue: 'Gross amount' }) });
    steps.push({ key: 'gross_deduction', sign: '-', amount: f.gross_deduction, label: t('cost_control.pay.step_gross_deduction', { defaultValue: 'Agreed deduction on the gross' }) });
  }
  steps.push({ key: 'gross_after', sign: '=', amount: f.gross_after, strong: true, label: t('cost_control.pay.step_gross_after', { defaultValue: 'Gross amount to assess' }) });
  steps.push({
    key: 'retention',
    sign: '-',
    amount: f.retention,
    label: t('cost_control.pay.step_retention', { defaultValue: 'Retention held' }),
    note:
      f.retention_source === 'claim'
        ? t('cost_control.pay.step_retention_claim', { defaultValue: 'as certified on the progress claim' })
        : num(f.retention_percent) !== 0
          ? t('cost_control.pay.step_retention_note', {
              defaultValue: '{{percent}} of {{base}}',
              percent: fmtPercent(f.retention_percent, 2),
              base: fmtMoney(f.retention_base, currency),
            })
          : undefined,
  });
  if (f.previous_counted) {
    steps.push({ key: 'previous', sign: '-', amount: f.previous_releases, label: t('cost_control.pay.step_previous', { defaultValue: 'Released on earlier invoices' }) });
  }
  if (num(f.rounding) !== 0) {
    steps.push({ key: 'before_rounding', sign: '=', amount: f.release_before_rounding, label: t('cost_control.pay.step_before_rounding', { defaultValue: 'Before rounding' }) });
    steps.push({ key: 'rounding', sign: '-', amount: f.rounding, label: t('cost_control.pay.step_rounding', { defaultValue: 'Rounded down, paid with a later invoice' }) });
  }
  steps.push({ key: 'release', sign: '=', amount: f.release, strong: true, label: t('cost_control.pay.step_release', { defaultValue: 'Released for payment' }) });
  if (num(f.discount) !== 0) {
    steps.push({
      key: 'discount',
      sign: '-',
      amount: f.discount,
      label: t('cost_control.pay.step_discount', { defaultValue: 'Early payment discount' }),
      note: f.discount_until
        ? t('cost_control.pay.step_discount_note', {
            defaultValue: '{{percent}} if paid by {{date}}',
            percent: fmtPercent(f.discount_percent, 2),
            date: fmtDate(f.discount_until),
          })
        : undefined,
    });
    steps.push({ key: 'payable', sign: '=', amount: f.payable, strong: true, label: t('cost_control.pay.step_payable', { defaultValue: 'To pay within the discount period' }) });
  }
  return steps;
}

export function StepTable({ steps, currency, testId }: { steps: Step[]; currency: string; testId?: string }) {
  return (
    <table className="w-full text-sm" data-testid={testId}>
      <tbody>
        {steps.map((s) => (
          <tr
            key={s.key}
            className={s.sign === '=' ? 'border-t border-border-light' : undefined}
            data-testid={testId ? `${testId}-${s.key}` : undefined}
          >
            <td className="w-5 py-1.5 text-center text-content-tertiary">{s.sign === '=' ? '' : s.sign}</td>
            <td className={`py-1.5 pe-3 ${s.strong ? 'font-semibold text-content-primary' : 'text-content-secondary'}`}>
              {s.label}
              {s.note && <span className="block text-2xs text-content-tertiary">{s.note}</span>}
            </td>
            <td
              className={`py-1.5 text-end tabular-nums ${s.strong ? 'font-semibold text-content-primary' : 'text-content-secondary'}`}
            >
              {fmtMoney(s.amount, currency)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function FindingLine({ finding }: { finding: ReleaseFinding }) {
  const Icon = finding.severity === 'error' ? AlertOctagon : finding.severity === 'warning' ? AlertTriangle : Info;
  const tone =
    finding.severity === 'error' ? 'text-semantic-error' : finding.severity === 'warning' ? 'text-amber-500' : 'text-sky-500';
  return (
    <li className="flex items-start gap-2 text-sm">
      <Icon size={15} className={`mt-0.5 shrink-0 ${tone}`} />
      <span>
        <span className="text-content-primary">{finding.message}</span>
        {finding.suggestion && <span className="block text-xs text-content-tertiary">{finding.suggestion}</span>}
      </span>
    </li>
  );
}

export function ReleaseDrawer({
  invoice,
  contract,
  currency,
  findings,
  canEdit,
  canRelease,
  onClose,
}: {
  invoice: LedgerInvoice | null;
  contract: LedgerContract | null;
  currency: string;
  findings: ReleaseFinding[];
  canEdit: boolean;
  canRelease: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [kind, setKind] = useState<InvoiceKind>('interim');
  const [netDeduction, setNetDeduction] = useState('0');
  const [netNote, setNetNote] = useState('');
  const [grossDeduction, setGrossDeduction] = useState('0');
  const [grossNote, setGrossNote] = useState('');

  useEffect(() => {
    if (!invoice) return;
    setKind(invoice.kind);
    setNetDeduction(invoice.figures.net_deduction);
    setNetNote(invoice.net_deduction_note);
    setGrossDeduction(invoice.figures.gross_deduction);
    setGrossNote(invoice.gross_deduction_note);
  }, [invoice]);

  const fail = (title: string) => (err: unknown) => {
    const problem = problemOf(err);
    const params = { ...(problem?.params ?? {}) };
    if (params.held !== undefined) params.held = fmtMoney(String(params.held), currency);
    addToast({
      type: 'error',
      title,
      message: (problem && paymentProblem(t, problem.problem, params)) || getErrorMessage(err),
    });
  };
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['payment-release'] });
    queryClient.invalidateQueries({ queryKey: ['cost-control'] });
  };

  const update = useMutation({
    mutationFn: (body: InvoiceReleaseUpdate) => paymentsApi.updateInvoice(invoice!.invoice_id, body),
    onSuccess: refresh,
    onError: fail(t('cost_control.pay.update_failed', { defaultValue: 'Could not save the invoice' })),
  });
  const release = useMutation({
    mutationFn: () => paymentsApi.release(invoice!.invoice_id),
    onSuccess: () => {
      refresh();
      addToast({ type: 'success', title: t('cost_control.pay.released', { defaultValue: 'Release confirmed' }) });
    },
    onError: fail(t('cost_control.pay.release_failed', { defaultValue: 'Could not confirm the release' })),
  });
  const reopen = useMutation({
    mutationFn: () => paymentsApi.reopen(invoice!.invoice_id),
    onSuccess: refresh,
    onError: fail(t('cost_control.pay.reopen_failed', { defaultValue: 'Could not reopen the release' })),
  });

  if (!invoice || !contract) {
    return (
      <SideDrawer open={false} onClose={onClose} title="">
        {null}
      </SideDrawer>
    );
  }

  const released = invoice.release_status === 'released';
  const busy = update.isPending || release.isPending || reopen.isPending;
  const editable = canEdit && !released;
  const steps = releaseSteps(t, invoice.figures, currency);
  const dirty =
    kind !== invoice.kind ||
    netDeduction !== invoice.figures.net_deduction ||
    grossDeduction !== invoice.figures.gross_deduction ||
    netNote !== invoice.net_deduction_note ||
    grossNote !== invoice.gross_deduction_note;

  return (
    <SideDrawer
      open
      onClose={onClose}
      busy={busy}
      title={t('cost_control.pay.release_title', { defaultValue: 'Invoice {{number}}', number: invoice.number })}
      subtitle={`${contract.code} ${contract.title} · ${modeLabel(t, contract.invoice_mode)}`}
      widthClass="w-full max-w-xl"
    >
      <div className="space-y-5 px-5 py-4" data-testid="release-drawer">
        <div className="flex flex-wrap items-center gap-2 text-xs text-content-secondary">
          <Badge variant={released ? 'success' : 'neutral'} size="sm">
            {released
              ? t('cost_control.pay.status_released', { defaultValue: 'Released' })
              : t('cost_control.pay.status_open', { defaultValue: 'Not released yet' })}
          </Badge>
          <span>{kindLabel(t, invoice.kind)}</span>
          {invoice.invoice_date && <span>· {fmtDate(invoice.invoice_date)}</span>}
          {invoice.figures.due_on && (
            <span>
              ·{' '}
              {t('cost_control.pay.due_on', { defaultValue: 'due {{date}}', date: fmtDate(invoice.figures.due_on) })}
            </span>
          )}
        </div>

        <section>
          <h3 className="mb-2 text-sm font-semibold text-content-primary">
            {t('cost_control.pay.steps_title', { defaultValue: 'From the invoice to the release' })}
          </h3>
          <StepTable steps={steps} currency={currency} testId="release-steps" />
          <p className="mt-2 text-xs text-content-tertiary">
            {t('cost_control.pay.held_after', {
              defaultValue: 'Retention held on the contract after this invoice: {{amount}}',
              amount: fmtMoney(invoice.figures.retention_held_after, currency),
            })}
          </p>
        </section>

        {invoice.differs && (
          <section className="rounded-lg border border-amber-300/60 bg-amber-50/60 px-3 py-2 dark:bg-amber-500/10">
            <p className="text-sm text-content-primary">
              {t('cost_control.pay.differs', {
                defaultValue:
                  'The terms today give {{amount}} for this invoice, not the {{released}} confirmed. Reopen it to release it again, or keep the confirmed figure.',
                amount: fmtMoney(invoice.computed.release, currency),
                released: fmtMoney(invoice.figures.release, currency),
              })}
            </p>
          </section>
        )}

        {findings.length > 0 && (
          <section>
            <h3 className="mb-2 text-sm font-semibold text-content-primary">
              {t('cost_control.pay.invoice_checks', { defaultValue: 'Checks on this invoice' })}
            </h3>
            <ul className="space-y-2">
              {findings.map((f, i) => (
                <FindingLine key={`${f.rule_id}-${i}`} finding={f} />
              ))}
            </ul>
          </section>
        )}

        <section className="space-y-3 border-t border-border-light pt-4">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('cost_control.pay.adjust_title', { defaultValue: 'Kind and agreed deductions' })}
          </h3>
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-content-secondary">
              {t('cost_control.pay.kind', { defaultValue: 'Invoice kind' })}
            </span>
            <select
              className={INPUT}
              value={kind}
              disabled={!editable || busy}
              onChange={(e) => setKind(e.target.value as InvoiceKind)}
              data-testid="release-kind"
            >
              {INVOICE_KINDS.map((k) => (
                <option key={k} value={k}>
                  {kindLabel(t, k)}
                </option>
              ))}
            </select>
          </label>
          <div className="grid grid-cols-[8rem_1fr] gap-2">
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-content-secondary">
                {t('cost_control.pay.net_deduction', { defaultValue: 'Deduction on the net' })}
              </span>
              <input
                className={INPUT}
                inputMode="decimal"
                value={netDeduction}
                disabled={!editable || busy}
                onChange={(e) => setNetDeduction(e.target.value)}
                data-testid="release-net-deduction"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-content-secondary">
                {t('cost_control.pay.deduction_reason', { defaultValue: 'Why' })}
              </span>
              <input
                className={INPUT}
                value={netNote}
                maxLength={500}
                disabled={!editable || busy}
                onChange={(e) => setNetNote(e.target.value)}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-content-secondary">
                {t('cost_control.pay.gross_deduction', { defaultValue: 'Deduction on the gross' })}
              </span>
              <input
                className={INPUT}
                inputMode="decimal"
                value={grossDeduction}
                disabled={!editable || busy}
                onChange={(e) => setGrossDeduction(e.target.value)}
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-content-secondary">
                {t('cost_control.pay.deduction_reason', { defaultValue: 'Why' })}
              </span>
              <input
                className={INPUT}
                value={grossNote}
                maxLength={500}
                disabled={!editable || busy}
                onChange={(e) => setGrossNote(e.target.value)}
              />
            </label>
          </div>
          {!canEdit ? null : released ? (
            <p className="text-xs text-content-tertiary">
              {t('cost_control.pay.locked_hint', { defaultValue: 'A confirmed release is locked. Reopen it to change it.' })}
            </p>
          ) : (
            <div className="flex justify-end">
              <Button
                variant="secondary"
                size="sm"
                disabled={!dirty}
                loading={update.isPending}
                data-testid="release-save"
                onClick={() =>
                  update.mutate({
                    kind,
                    net_deduction: moneyPayload(netDeduction),
                    net_deduction_note: netNote,
                    gross_deduction: moneyPayload(grossDeduction),
                    gross_deduction_note: grossNote,
                  })
                }
              >
                {t('cost_control.pay.recompute', { defaultValue: 'Save and recompute' })}
              </Button>
            </div>
          )}
        </section>

        <section className="flex flex-wrap items-center justify-end gap-2 border-t border-border-light pt-4">
          {!canRelease && (
            <p className="me-auto text-xs text-content-tertiary">
              {t('cost_control.pay.release_role', { defaultValue: 'A manager confirms releases.' })}
            </p>
          )}
          {canRelease &&
            (released ? (
              <Button
                variant="secondary"
                size="sm"
                icon={<Unlock size={14} />}
                loading={reopen.isPending}
                onClick={() => reopen.mutate()}
                data-testid="release-reopen"
              >
                {t('cost_control.pay.reopen', { defaultValue: 'Reopen' })}
              </Button>
            ) : (
              <Button
                variant="primary"
                size="sm"
                icon={<Lock size={14} />}
                disabled={dirty}
                loading={release.isPending}
                onClick={() => release.mutate()}
                data-testid="release-confirm"
              >
                {t('cost_control.pay.confirm', { defaultValue: 'Confirm release of {{amount}}', amount: fmtMoney(invoice.figures.release, currency) })}
              </Button>
            ))}
        </section>
      </div>
    </SideDrawer>
  );
}
