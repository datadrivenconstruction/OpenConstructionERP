// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Invoices and payments of the project's supplier contracts, three tabs:
//
// * Invoices: per contract its value, what is measured, invoiced, released
//   and paid, then each invoice with its release. A click opens the steps
//   from the invoice to the release; "Payment terms" opens the contract's
//   terms. Supplier invoices on no contract are listed below, each can be put
//   on a contract here.
// * Retention: withheld, paid back and still held per contract, and the form
//   that pays held retention back after its event.
// * Checks: rules V11 to V18, already in the reader's language.
import { Fragment, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertOctagon, AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Info, Settings2 } from 'lucide-react';

import { Badge, Button, Skeleton } from '@/shared/ui';
import { TabBar } from '@/shared/ui/TabBar';
import { fmtDate, fmtPercent } from '@/shared/lib/formatters';
// Release figures are amounts to pay: shown to the minor unit, never rounded to whole units.
import { formatCurrency as fmtMoney } from '@/shared/lib/money';
import { getErrorMessage } from '@/shared/lib/api';
import { problemOf } from '@/features/costmodel/structureApi';
import { useToastStore } from '@/stores/useToastStore';
import { num } from './api';
import {
  RELEASE_EVENTS,
  eventLabel,
  kindLabel,
  modeLabel,
  paymentProblem,
  paymentsApi,
  type LedgerContract,
  type LedgerInvoice,
  type LedgerTotals,
  type ReleaseEvent,
  type ReleaseFinding,
  type RetentionContract,
  type RetentionKind,
} from './paymentsApi';
import { ReleaseDrawer, moneyPayload } from './ReleaseDrawer';
import { TermsDrawer } from './TermsDrawer';

type Tab = 'ledger' | 'retention' | 'checks';

const INPUT = 'h-8 w-full rounded-lg border border-border bg-surface-primary px-2.5 text-sm disabled:opacity-60';

function today(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function errorText(t: TFunction, err: unknown, currency: string): string {
  const problem = problemOf(err);
  if (problem) {
    const params = { ...problem.params };
    if (params.held !== undefined) params.held = fmtMoney(String(params.held), currency);
    const text = paymentProblem(t, problem.problem, params);
    if (text) return text;
  }
  return getErrorMessage(err);
}

function Figure({ label, value, sub, testId }: { label: string; value: string; sub?: string; testId?: string }) {
  return (
    <div className="min-w-0" data-testid={testId}>
      <div className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">{label}</div>
      <div className="text-sm font-semibold tabular-nums text-content-primary">{value}</div>
      {sub && <div className="text-2xs text-content-tertiary">{sub}</div>}
    </div>
  );
}

function TotalsStrip({ totals, currency, measured }: { totals: LedgerTotals; currency: string; measured?: string }) {
  const { t } = useTranslation();
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <Figure label={t('cost_control.pay.fig_value', { defaultValue: 'Contract value' })} value={fmtMoney(totals.contract_value, currency)} />
      {measured !== undefined && (
        <Figure label={t('cost_control.pay.fig_measured', { defaultValue: 'Measured' })} value={fmtMoney(measured, currency)} />
      )}
      <Figure
        label={t('cost_control.pay.fig_invoiced', { defaultValue: 'Invoiced (net)' })}
        value={fmtMoney(totals.invoiced, currency)}
        sub={totals.invoiced_pct ? t('cost_control.pay.fig_of_value', { defaultValue: '{{pct}} of the value', pct: fmtPercent(totals.invoiced_pct) }) : undefined}
      />
      <Figure label={t('cost_control.pay.fig_due', { defaultValue: 'Due for payment' })} value={fmtMoney(totals.released, currency)} />
      <Figure label={t('cost_control.pay.fig_paid', { defaultValue: 'Paid' })} value={fmtMoney(totals.paid, currency)} />
      <Figure label={t('cost_control.pay.fig_due_open', { defaultValue: 'Due, not paid' })} value={fmtMoney(totals.open_amount, currency)} />
      <Figure label={t('cost_control.pay.fig_held', { defaultValue: 'Retention held' })} value={fmtMoney(totals.retention_held, currency)} />
    </div>
  );
}

function ContractBlock({
  contract,
  currency,
  findings,
  onOpenInvoice,
  onOpenTerms,
}: {
  contract: LedgerContract;
  currency: string;
  findings: Map<string, ReleaseFinding[]>;
  onOpenInvoice: (invoice: LedgerInvoice) => void;
  onOpenTerms: () => void;
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(contract.invoices.length > 0);
  return (
    <section className="rounded-xl border border-border-light" data-testid={`ledger-contract-${contract.code}`}>
      <div className="flex flex-wrap items-center gap-2 px-4 py-2.5">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-2 text-start"
        >
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
          <span className="truncate text-sm font-medium text-content-primary">
            {contract.code} {contract.title}
          </span>
          <Badge variant="neutral" size="sm">
            {modeLabel(t, contract.invoice_mode)}
          </Badge>
          {!contract.terms_set && (
            <span className="text-xs text-content-tertiary">
              {t('cost_control.pay.terms_default_badge', { defaultValue: 'default terms' })}
            </span>
          )}
        </button>
        <Button variant="ghost" size="sm" icon={<Settings2 size={14} />} onClick={onOpenTerms} data-testid={`terms-open-${contract.code}`}>
          {t('cost_control.pay.terms_title', { defaultValue: 'Payment terms' })}
        </Button>
      </div>
      {open && (
        <div className="space-y-3 border-t border-border-light px-4 py-3">
          <TotalsStrip totals={contract.totals} currency={currency} measured={contract.has_measurement ? contract.measured : undefined} />
          {contract.invoices.length === 0 ? (
            <p className="text-sm text-content-tertiary">
              {t('cost_control.pay.no_invoices', {
                defaultValue: 'No supplier invoice on this contract yet. Invoices recorded in finance appear here by themselves.',
              })}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead>
                  <tr className="border-b border-border-light text-start text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                    <th className="py-2 pe-2">{t('cost_control.pay.col_invoice', { defaultValue: 'Invoice' })}</th>
                    <th className="px-2 py-2">{t('cost_control.pay.kind', { defaultValue: 'Invoice kind' })}</th>
                    <th className="px-2 py-2 text-end">{t('cost_control.pay.col_gross', { defaultValue: 'Gross to assess' })}</th>
                    <th className="px-2 py-2 text-end">{t('cost_control.pay.col_retention', { defaultValue: 'Retention' })}</th>
                    <th className="px-2 py-2 text-end">{t('cost_control.pay.col_release', { defaultValue: 'Release' })}</th>
                    <th className="px-2 py-2 text-end">{t('cost_control.pay.col_paid', { defaultValue: 'Paid' })}</th>
                    <th className="px-2 py-2 text-end">{t('cost_control.pay.col_status', { defaultValue: 'Status' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {contract.invoices.map((inv) => {
                    const found = findings.get(inv.invoice_id) ?? [];
                    const worst = found.some((f) => f.severity === 'error')
                      ? 'error'
                      : found.some((f) => f.severity === 'warning')
                        ? 'warning'
                        : null;
                    return (
                      <tr
                        key={inv.invoice_id}
                        tabIndex={0}
                        role="button"
                        aria-label={t('cost_control.pay.open_invoice', { defaultValue: 'Open invoice {{number}}', number: inv.number })}
                        className="cursor-pointer border-b border-border-light last:border-0 hover:bg-surface-secondary/50 focus-visible:bg-surface-secondary/50 focus-visible:outline-none"
                        onClick={() => onOpenInvoice(inv)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            onOpenInvoice(inv);
                          }
                        }}
                        data-testid={`ledger-invoice-${inv.number}`}
                      >
                        <td className="py-2 pe-2">
                          <span className="flex items-center gap-1.5 font-medium text-content-primary">
                            {worst === 'error' && <AlertOctagon size={14} className="text-semantic-error" />}
                            {worst === 'warning' && <AlertTriangle size={14} className="text-amber-500" />}
                            {inv.number}
                          </span>
                          {inv.invoice_date && <span className="text-2xs text-content-tertiary">{fmtDate(inv.invoice_date)}</span>}
                        </td>
                        <td className="px-2 py-2 text-content-secondary">
                          {kindLabel(t, inv.kind)}
                          {!inv.counted && (
                            <span className="block text-2xs text-content-tertiary">
                              {t('cost_control.pay.superseded', { defaultValue: 'included in a later invoice' })}
                            </span>
                          )}
                        </td>
                        <td className="px-2 py-2 text-end tabular-nums text-content-secondary">{fmtMoney(inv.figures.gross_after, currency)}</td>
                        <td className="px-2 py-2 text-end tabular-nums text-content-secondary">{fmtMoney(inv.figures.retention, currency)}</td>
                        <td className="px-2 py-2 text-end font-semibold tabular-nums text-content-primary">{fmtMoney(inv.figures.release, currency)}</td>
                        <td className="px-2 py-2 text-end tabular-nums text-content-secondary">{fmtMoney(inv.paid, currency)}</td>
                        <td className="px-2 py-2 text-end">
                          <Badge variant={inv.release_status === 'released' ? (inv.differs ? 'warning' : 'success') : 'neutral'} size="sm">
                            {inv.release_status === 'released'
                              ? t('cost_control.pay.status_released', { defaultValue: 'Released' })
                              : t('cost_control.pay.status_open', { defaultValue: 'Not released yet' })}
                          </Badge>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function LedgerTab({
  projectId,
  currency,
  findings,
  canEdit,
  canRelease,
}: {
  projectId: string;
  currency: string;
  findings: ReleaseFinding[];
  canEdit: boolean;
  canRelease: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const ledger = useQuery({ queryKey: ['payment-release', 'ledger', projectId], queryFn: () => paymentsApi.ledger(projectId) });
  const [openInvoice, setOpenInvoice] = useState<string | null>(null);
  const [termsFor, setTermsFor] = useState<LedgerContract | null>(null);

  const byInvoice = useMemo(() => {
    const map = new Map<string, ReleaseFinding[]>();
    for (const f of findings) {
      if (!f.element_ref) continue;
      map.set(f.element_ref, [...(map.get(f.element_ref) ?? []), f]);
    }
    return map;
  }, [findings]);

  const assign = useMutation({
    mutationFn: ({ invoiceId, contractId }: { invoiceId: string; contractId: string }) =>
      paymentsApi.updateInvoice(invoiceId, { contract_id: contractId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['payment-release'] });
      queryClient.invalidateQueries({ queryKey: ['cost-control'] });
    },
    onError: (err: unknown) =>
      addToast({
        type: 'error',
        title: t('cost_control.pay.update_failed', { defaultValue: 'Could not save the invoice' }),
        message: errorText(t, err, currency),
      }),
  });

  if (ledger.isLoading) return <Skeleton className="h-40 w-full" />;
  if (ledger.error) return <p className="text-sm text-semantic-error">{getErrorMessage(ledger.error)}</p>;
  const data = ledger.data!;
  const cur = data.currency || currency;
  const selected = (() => {
    for (const c of data.contracts) {
      const inv = c.invoices.find((i) => i.invoice_id === openInvoice);
      if (inv) return { contract: c, invoice: inv };
    }
    return null;
  })();

  if (data.contracts.length === 0 && data.other_invoices.length === 0) {
    return (
      <p className="text-sm text-content-secondary" data-testid="ledger-empty">
        {t('cost_control.pay.ledger_empty', {
          defaultValue:
            'No supplier contract or supplier invoice on this project yet. Award a subcontract in contracts and record its invoices in finance; they show up here with their release.',
        })}
      </p>
    );
  }

  return (
    <div className="space-y-3" data-testid="payments-ledger">
      <TotalsStrip totals={data.totals} currency={cur} />
      {data.contracts.map((c) => (
        <ContractBlock
          key={c.contract_id}
          contract={c}
          currency={cur}
          findings={byInvoice}
          onOpenInvoice={(inv) => setOpenInvoice(inv.invoice_id)}
          onOpenTerms={() => setTermsFor(c)}
        />
      ))}
      {data.other_invoices.length > 0 && (
        <section className="rounded-xl border border-border-light px-4 py-3" data-testid="ledger-other-invoices">
          <h3 className="text-sm font-medium text-content-primary">
            {t('cost_control.pay.other_title', { defaultValue: 'Supplier invoices on no contract' })}
          </h3>
          <p className="mb-2 text-xs text-content-tertiary">
            {t('cost_control.pay.other_hint', {
              defaultValue: 'They count as invoiced and paid, but no release is computed. Put one on its contract to release it.',
            })}
          </p>
          <ul className="divide-y divide-border-light">
            {data.other_invoices.map((inv) => (
              <li key={inv.invoice_id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
                <span className="min-w-0 flex-1">
                  <span className="font-medium text-content-primary">{inv.number}</span>
                  {inv.invoice_date && <span className="ms-2 text-xs text-content-tertiary">{fmtDate(inv.invoice_date)}</span>}
                </span>
                <span className="tabular-nums text-content-secondary">{fmtMoney(inv.gross, cur)}</span>
                {canEdit && data.contracts.length > 0 && (
                  <select
                    className="h-8 w-48 rounded-lg border border-border bg-surface-primary px-2 text-sm"
                    value=""
                    disabled={assign.isPending}
                    aria-label={t('cost_control.pay.put_on_contract', { defaultValue: 'Put on a contract' })}
                    onChange={(e) => e.target.value && assign.mutate({ invoiceId: inv.invoice_id, contractId: e.target.value })}
                  >
                    <option value="">{t('cost_control.pay.put_on_contract', { defaultValue: 'Put on a contract' })}</option>
                    {data.contracts.map((c) => (
                      <option key={c.contract_id} value={c.contract_id}>
                        {c.code} {c.title}
                      </option>
                    ))}
                  </select>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
      <ReleaseDrawer
        invoice={selected?.invoice ?? null}
        contract={selected?.contract ?? null}
        currency={cur}
        findings={selected ? byInvoice.get(selected.invoice.invoice_id) ?? [] : []}
        canEdit={canEdit}
        canRelease={canRelease}
        onClose={() => setOpenInvoice(null)}
      />
      <TermsDrawer
        contractId={termsFor?.contract_id ?? null}
        contractLabel={termsFor ? `${termsFor.code} ${termsFor.title}` : ''}
        canEdit={canEdit}
        onClose={() => setTermsFor(null)}
      />
    </div>
  );
}

function PostingForm({
  contract,
  currency,
  onDone,
}: {
  contract: RetentionContract;
  currency: string;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [kind, setKind] = useState<RetentionKind>('interim');
  const [event, setEvent] = useState<ReleaseEvent>(
    (RELEASE_EVENTS as readonly string[]).includes(contract.retention_release_event)
      ? (contract.retention_release_event as ReleaseEvent)
      : 'substantial_completion',
  );
  const [eventOn, setEventOn] = useState('');
  const [amount, setAmount] = useState(contract.held);
  const [postedOn, setPostedOn] = useState(today());
  const [ref, setRef] = useState('');

  const post = useMutation({
    mutationFn: () =>
      paymentsApi.postRetention(contract.contract_id, {
        retention_kind: kind,
        event,
        event_on: eventOn || null,
        amount: moneyPayload(amount),
        posted_on: postedOn,
        document_ref: ref || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['payment-release'] });
      queryClient.invalidateQueries({ queryKey: ['cost-control'] });
      addToast({ type: 'success', title: t('cost_control.pay.posted', { defaultValue: 'Retention paid back' }) });
      onDone();
    },
    onError: (err: unknown) =>
      addToast({
        type: 'error',
        title: t('cost_control.pay.post_failed', { defaultValue: 'Could not pay the retention back' }),
        message: errorText(t, err, currency),
      }),
  });

  return (
    <form
      className="grid grid-cols-2 gap-3 rounded-lg bg-surface-secondary/50 p-3 sm:grid-cols-3"
      data-testid={`posting-form-${contract.code}`}
      onSubmit={(e) => {
        e.preventDefault();
        post.mutate();
      }}
    >
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-content-secondary">{t('cost_control.pay.post_kind', { defaultValue: 'Which retention' })}</span>
        <select
          className={INPUT}
          value={kind}
          onChange={(e) => {
            const next = e.target.value as RetentionKind;
            setKind(next);
            const ev = next === 'warranty' ? contract.warranty_release_event : contract.retention_release_event;
            if ((RELEASE_EVENTS as readonly string[]).includes(ev)) setEvent(ev as ReleaseEvent);
          }}
        >
          <option value="interim">{t('cost_control.pay.post_kind_interim', { defaultValue: 'Interim retention' })}</option>
          {contract.warranty_enabled && (
            <option value="warranty">{t('cost_control.pay.post_kind_warranty', { defaultValue: 'Warranty retention' })}</option>
          )}
        </select>
      </label>
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-content-secondary">{t('cost_control.pay.post_event', { defaultValue: 'Event' })}</span>
        <select className={INPUT} value={event} onChange={(e) => setEvent(e.target.value as ReleaseEvent)}>
          {RELEASE_EVENTS.map((ev) => (
            <option key={ev} value={ev}>
              {eventLabel(t, ev)}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-content-secondary">{t('cost_control.pay.post_event_on', { defaultValue: 'Event reached on' })}</span>
        <input type="date" className={INPUT} value={eventOn} onChange={(e) => setEventOn(e.target.value)} />
      </label>
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-content-secondary">
          {t('cost_control.pay.post_amount', { defaultValue: 'Amount ({{currency}})', currency })}
        </span>
        <input className={INPUT} inputMode="decimal" required value={amount} onChange={(e) => setAmount(e.target.value)} data-testid="posting-amount" />
      </label>
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-content-secondary">{t('cost_control.pay.post_on', { defaultValue: 'Paid on' })}</span>
        <input type="date" className={INPUT} required value={postedOn} onChange={(e) => setPostedOn(e.target.value)} />
      </label>
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-content-secondary">{t('cost_control.pay.post_ref', { defaultValue: 'Document' })}</span>
        <input className={INPUT} maxLength={255} value={ref} onChange={(e) => setRef(e.target.value)} />
      </label>
      <div className="col-span-full flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onDone}>
          {t('cost_control.pay.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button type="submit" variant="primary" size="sm" loading={post.isPending} disabled={!amount.trim() || !postedOn} data-testid="posting-save">
          {t('cost_control.pay.post_save', { defaultValue: 'Pay back' })}
        </Button>
      </div>
    </form>
  );
}

function RetentionTab({ projectId, currency, canRelease }: { projectId: string; currency: string; canRelease: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const register = useQuery({ queryKey: ['payment-release', 'retention', projectId], queryFn: () => paymentsApi.retention(projectId) });
  const [posting, setPosting] = useState<string | null>(null);

  const voidIt = useMutation({
    mutationFn: (id: string) => paymentsApi.voidPosting(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['payment-release'] });
      queryClient.invalidateQueries({ queryKey: ['cost-control'] });
    },
    onError: (err: unknown) =>
      addToast({
        type: 'error',
        title: t('cost_control.pay.void_failed', { defaultValue: 'Could not void the posting' }),
        message: errorText(t, err, currency),
      }),
  });

  if (register.isLoading) return <Skeleton className="h-40 w-full" />;
  if (register.error) return <p className="text-sm text-semantic-error">{getErrorMessage(register.error)}</p>;
  const data = register.data!;
  const cur = data.currency || currency;
  if (data.contracts.length === 0) {
    return (
      <p className="text-sm text-content-secondary" data-testid="retention-empty">
        {t('cost_control.pay.retention_empty', {
          defaultValue: 'No retention is held on this project. Set a retention rate in a contract\'s payment terms; each released invoice then holds it back here.',
        })}
      </p>
    );
  }
  return (
    <div className="space-y-3" data-testid="payments-retention">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Figure label={t('cost_control.pay.fig_held', { defaultValue: 'Retention held' })} value={fmtMoney(data.held, cur)} testId="retention-held-total" />
        <Figure label={t('cost_control.pay.fig_posted', { defaultValue: 'Paid back' })} value={fmtMoney(data.posted, cur)} />
      </div>
      <div className="overflow-x-auto rounded-xl border border-border-light">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="border-b border-border-light bg-surface-secondary/60 text-start text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
              <th className="py-2 ps-4 pe-2">{t('cost_control.col_contract', { defaultValue: 'Contract' })}</th>
              <th className="px-2 py-2">{t('cost_control.pay.col_terms', { defaultValue: 'Terms' })}</th>
              <th className="px-2 py-2 text-end">{t('cost_control.pay.col_withheld', { defaultValue: 'Withheld' })}</th>
              <th className="px-2 py-2 text-end">{t('cost_control.pay.fig_posted', { defaultValue: 'Paid back' })}</th>
              <th className="px-2 py-2 text-end">{t('cost_control.pay.col_held', { defaultValue: 'Still held' })}</th>
              <th className="py-2 pe-4 ps-2" />
            </tr>
          </thead>
          <tbody>
            {data.contracts.map((c) => (
              <Fragment key={c.contract_id}>
              <tr className="border-b border-border-light align-top last:border-0" data-testid={`retention-row-${c.code}`}>
                <td className="py-2.5 ps-4 pe-2">
                  <span className="font-medium text-content-primary">{c.code}</span>
                  <span className="block text-xs text-content-tertiary">{c.title}</span>
                  {c.postings.length > 0 && (
                    <ul className="mt-2 space-y-1">
                      {c.postings.map((p) => (
                        <li key={p.id} className={`flex flex-wrap items-center gap-2 text-xs ${p.status === 'void' ? 'text-content-quaternary line-through' : 'text-content-secondary'}`}>
                          <span>{fmtDate(p.posted_on)}</span>
                          <span>{fmtMoney(p.amount, cur)}</span>
                          <span>{eventLabel(t, p.event)}</span>
                          {p.document_ref && <span>{p.document_ref}</span>}
                          {p.status === 'posted' && canRelease && (
                            <button
                              type="button"
                              className="text-oe-blue hover:underline disabled:opacity-50"
                              disabled={voidIt.isPending}
                              onClick={() => voidIt.mutate(p.id)}
                            >
                              {t('cost_control.pay.void', { defaultValue: 'Void' })}
                            </button>
                          )}
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
                <td className="px-2 py-2.5 text-xs text-content-secondary">
                  {num(c.retention_percent) === 0
                    ? t('cost_control.pay.terms_line_none', { defaultValue: 'No retention on interim invoices' })
                    : t('cost_control.pay.terms_line', {
                        defaultValue: '{{percent}} until {{event}}',
                        percent: fmtPercent(c.retention_percent, 2),
                        event: eventLabel(t, c.retention_release_event),
                      })}
                  {c.warranty_enabled && (
                    <span className="block">
                      {t('cost_control.pay.terms_line_warranty', {
                        defaultValue: 'warranty {{percent}} until {{event}}',
                        percent: fmtPercent(c.warranty_percent, 2),
                        event: eventLabel(t, c.warranty_release_event),
                      })}
                    </span>
                  )}
                </td>
                <td className="px-2 py-2.5 text-end tabular-nums text-content-secondary">{fmtMoney(c.withheld, cur)}</td>
                <td className="px-2 py-2.5 text-end tabular-nums text-content-secondary">{fmtMoney(c.posted, cur)}</td>
                <td className="px-2 py-2.5 text-end font-semibold tabular-nums text-content-primary">{fmtMoney(c.held, cur)}</td>
                <td className="py-2.5 pe-4 ps-2 text-end">
                  {canRelease && num(c.held) > 0 && posting !== c.contract_id && (
                    <Button variant="secondary" size="sm" onClick={() => setPosting(c.contract_id)} data-testid={`posting-open-${c.code}`}>
                      {t('cost_control.pay.post_open', { defaultValue: 'Pay back' })}
                    </Button>
                  )}
                </td>
              </tr>
              {posting === c.contract_id && (
                <tr className="border-b border-border-light">
                  <td colSpan={6} className="px-4 py-3">
                    <PostingForm contract={c} currency={cur} onDone={() => setPosting(null)} />
                  </td>
                </tr>
              )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {!canRelease && (
        <p className="text-xs text-content-tertiary">
          {t('cost_control.pay.post_role', { defaultValue: 'A manager pays held retention back.' })}
        </p>
      )}
    </div>
  );
}

function ChecksTab({ findings, loading }: { findings: ReleaseFinding[]; loading: boolean }) {
  const { t } = useTranslation();
  if (loading) return <Skeleton className="h-24 w-full" />;
  if (findings.length === 0) {
    return (
      <p className="flex items-center gap-2 text-sm text-content-secondary" data-testid="payment-checks-none">
        <CheckCircle2 size={16} className="text-semantic-success" />
        {t('cost_control.pay.checks_none', { defaultValue: 'All payment checks pass.' })}
      </p>
    );
  }
  return (
    <ul className="space-y-2" data-testid="payment-checks">
      {findings.map((f, i) => {
        const Icon = f.severity === 'error' ? AlertOctagon : f.severity === 'warning' ? AlertTriangle : Info;
        const tone = f.severity === 'error' ? 'text-semantic-error' : f.severity === 'warning' ? 'text-amber-500' : 'text-sky-500';
        return (
          <li key={`${f.rule_id}-${f.element_ref ?? ''}-${i}`} className="flex items-start gap-3 rounded-lg px-2 py-1.5">
            <Icon size={16} className={`mt-0.5 shrink-0 ${tone}`} />
            <span className="min-w-0 flex-1">
              <span className="block text-sm text-content-primary">{f.message}</span>
              {f.suggestion && <span className="block text-xs text-content-tertiary">{f.suggestion}</span>}
            </span>
            <Badge variant="neutral" size="sm">
              {f.rule_number}
            </Badge>
          </li>
        );
      })}
    </ul>
  );
}

export function PaymentsPanel({
  projectId,
  currency,
  canEdit,
  canRelease,
}: {
  projectId: string;
  currency: string;
  canEdit: boolean;
  canRelease: boolean;
}) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>('ledger');
  const checks = useQuery({ queryKey: ['payment-release', 'findings', projectId], queryFn: () => paymentsApi.findings(projectId) });
  const findings = checks.data?.findings ?? [];
  const errors = checks.data?.errors ?? 0;
  const warnings = checks.data?.warnings ?? 0;

  return (
    <div data-testid="payments-panel">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-content-primary">
            {t('cost_control.pay.title', { defaultValue: 'Invoices and payments' })}
          </h2>
          <p className="text-xs text-content-tertiary">
            {t('cost_control.pay.subtitle', {
              defaultValue:
                'What each supplier invoiced, what is released for payment after retention, earlier payments, rounding and discount, and the retention still held.',
            })}
          </p>
        </div>
        <TabBar
          variant="segmented"
          size="sm"
          ariaLabel={t('cost_control.pay.title', { defaultValue: 'Invoices and payments' })}
          activeId={tab}
          onChange={(next) => setTab(next)}
          testIdPrefix="payments"
          tabs={[
            { id: 'ledger', label: t('cost_control.pay.tab_ledger', { defaultValue: 'Invoices' }) },
            { id: 'retention', label: t('cost_control.pay.tab_retention', { defaultValue: 'Retention' }) },
            {
              id: 'checks',
              label: t('cost_control.pay.tab_checks', { defaultValue: 'Checks' }),
              badge:
                errors + warnings > 0 ? (
                  <Badge variant={errors > 0 ? 'error' : 'warning'} size="sm">
                    {errors + warnings}
                  </Badge>
                ) : undefined,
            },
          ]}
        />
      </div>
      {tab === 'ledger' && (
        <LedgerTab projectId={projectId} currency={currency} findings={findings} canEdit={canEdit} canRelease={canRelease} />
      )}
      {tab === 'retention' && <RetentionTab projectId={projectId} currency={currency} canRelease={canRelease} />}
      {tab === 'checks' && <ChecksTab findings={findings} loading={checks.isLoading} />}
    </div>
  );
}
