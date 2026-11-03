// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The budget ledger: money moved between cost lines, and budget changes the
// owner approved. Both go draft, submitted, approved or rejected; only approved
// entries change the revised budget in the table above. The server checks that a
// transfer nets to zero and never takes a line below what is committed on it.
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Badge, Button, Skeleton } from '@/shared/ui';
import type { BadgeVariant } from '@/shared/ui';
import { fmtCurrency } from '@/shared/lib/formatters';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { CostLinePicker } from '@/features/costmodel/CostLinePicker';
import {
  budgetLedgerApi,
  num,
  type BudgetLedger,
  type BudgetModification,
  type BudgetTransfer,
  type LedgerKind,
  type LedgerStatus,
  type LedgerStep,
} from './api';

type View = 'transfers' | 'modifications' | 'history';

const STATUS_VARIANT: Record<LedgerStatus, BadgeVariant> = {
  draft: 'neutral',
  submitted: 'warning',
  approved: 'success',
  rejected: 'error',
};

export function statusLabel(t: TFunction, status: LedgerStatus): string {
  switch (status) {
    case 'draft':
      return t('cost_control.ledger.status_draft', { defaultValue: 'Draft' });
    case 'submitted':
      return t('cost_control.ledger.status_submitted', { defaultValue: 'Waiting for a decision' });
    case 'approved':
      return t('cost_control.ledger.status_approved', { defaultValue: 'Approved' });
    default:
      return t('cost_control.ledger.status_rejected', { defaultValue: 'Rejected' });
  }
}

function actionLabel(t: TFunction, action: string): string {
  switch (action) {
    case 'create':
      return t('cost_control.ledger.action_create', { defaultValue: 'Drafted' });
    case 'edit':
      return t('cost_control.ledger.action_edit', { defaultValue: 'Changed' });
    case 'delete':
      return t('cost_control.ledger.action_delete', { defaultValue: 'Deleted' });
    case 'submit':
      return t('cost_control.ledger.action_submit', { defaultValue: 'Submitted' });
    case 'approve':
      return t('cost_control.ledger.action_approve', { defaultValue: 'Approved' });
    default:
      return t('cost_control.ledger.action_reject', { defaultValue: 'Rejected' });
  }
}

interface Props {
  projectId: string;
  currency: string;
  canEdit: boolean;
  canManage: boolean;
}

export function BudgetLedgerPanel({ projectId, currency, canEdit, canManage }: Props) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [view, setView] = useState<View>('transfers');
  const [form, setForm] = useState<LedgerKind | null>(null);
  const [rejecting, setRejecting] = useState<{ kind: LedgerKind; id: string } | null>(null);
  const [note, setNote] = useState('');
  const [error, setError] = useState('');

  const ledger = useQuery({
    queryKey: ['budget-ledger', projectId],
    queryFn: () => budgetLedgerApi.get(projectId),
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['budget-ledger', projectId] });
    void queryClient.invalidateQueries({ queryKey: ['cost-control'] });
  };
  const fail = (e: unknown) => setError(getErrorMessage(e));

  const step = useMutation({
    mutationFn: (v: { kind: LedgerKind; id: string; step: LedgerStep; note?: string }) =>
      budgetLedgerApi.step(projectId, v.kind, v.id, v.step, v.note ?? ''),
    onSuccess: () => {
      setError('');
      setRejecting(null);
      setNote('');
      refresh();
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (v: { kind: LedgerKind; id: string }) => budgetLedgerApi.remove(projectId, v.kind, v.id),
    onSuccess: () => {
      setError('');
      refresh();
    },
    onError: fail,
  });
  const created = () => {
    setForm(null);
    setError('');
    addToast({ type: 'success', title: t('cost_control.ledger.saved', { defaultValue: 'Saved as a draft' }) });
    refresh();
  };

  const data: BudgetLedger | undefined = ledger.data;
  const pending = (data?.pending_transfers ?? 0) + (data?.pending_modifications ?? 0);
  const busy = step.isPending || remove.isPending;

  const actions = (kind: LedgerKind, id: string, status: LedgerStatus) => (
    <div className="flex shrink-0 flex-wrap items-center gap-2">
      {status === 'draft' && canEdit && (
        <>
          <Button size="sm" disabled={busy} onClick={() => step.mutate({ kind, id, step: 'submit' })}>
            {t('cost_control.ledger.submit', { defaultValue: 'Submit' })}
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => remove.mutate({ kind, id })}>
            {t('cost_control.ledger.delete', { defaultValue: 'Delete' })}
          </Button>
        </>
      )}
      {status === 'submitted' && canManage && (
        <>
          <Button size="sm" disabled={busy} onClick={() => step.mutate({ kind, id, step: 'approve' })}>
            {t('cost_control.ledger.approve', { defaultValue: 'Approve' })}
          </Button>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => setRejecting({ kind, id })}>
            {t('cost_control.ledger.reject', { defaultValue: 'Reject' })}
          </Button>
        </>
      )}
    </div>
  );

  const rejectBox = (kind: LedgerKind, id: string) =>
    rejecting?.kind === kind && rejecting.id === id ? (
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input
          className="min-w-0 flex-1 rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm"
          aria-label={t('cost_control.ledger.reject_reason', { defaultValue: 'Reason for rejecting' })}
          placeholder={t('cost_control.ledger.reject_reason', { defaultValue: 'Reason for rejecting' })}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <Button
          size="sm"
          disabled={busy || !note.trim()}
          onClick={() => step.mutate({ kind, id, step: 'reject', note })}
        >
          {t('cost_control.ledger.reject', { defaultValue: 'Reject' })}
        </Button>
      </div>
    ) : null;

  const transferRow = (tr: BudgetTransfer) => {
    const from = tr.legs.filter((l) => num(l.amount) < 0);
    const to = tr.legs.filter((l) => num(l.amount) > 0);
    return (
      <li key={tr.id} className="px-4 py-3" data-testid={`transfer-${tr.code}`}>
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-mono text-xs text-content-tertiary">{tr.code}</span>
          <Badge variant={STATUS_VARIANT[tr.status]} size="sm">
            {statusLabel(t, tr.status)}
          </Badge>
          <span className="min-w-0 flex-1 text-sm text-content-primary">
            {t('cost_control.ledger.transfer_summary', {
              defaultValue: '{{amount}} from {{from}} to {{to}}',
              amount: fmtCurrency(num(tr.moved), currency),
              from: from.map((l) => l.code).join(', '),
              to: to.map((l) => l.code).join(', '),
            })}
          </span>
          {actions('transfer', tr.id, tr.status)}
        </div>
        <p className="mt-1 text-xs text-content-tertiary">{tr.reason}</p>
        {tr.decision_note && <p className="mt-1 text-xs text-content-secondary">{tr.decision_note}</p>}
        {rejectBox('transfer', tr.id)}
      </li>
    );
  };

  const modRow = (m: BudgetModification) => (
    <li key={m.id} className="px-4 py-3" data-testid={`modification-${m.code}`}>
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-xs text-content-tertiary">{m.code}</span>
        <Badge variant={STATUS_VARIANT[m.status]} size="sm">
          {statusLabel(t, m.status)}
        </Badge>
        <span className="min-w-0 flex-1 text-sm text-content-primary">
          <span className="me-2 font-mono text-xs text-content-tertiary">{m.line_code}</span>
          {fmtCurrency(num(m.amount), currency)}
        </span>
        {actions('modification', m.id, m.status)}
      </div>
      <p className="mt-1 text-xs text-content-tertiary">
        {m.reason}
        {m.approval_ref ? ` (${m.approval_ref})` : ''}
      </p>
      {m.decision_note && <p className="mt-1 text-xs text-content-secondary">{m.decision_note}</p>}
      {rejectBox('modification', m.id)}
    </li>
  );

  const tabs: { id: View; label: string }[] = [
    { id: 'transfers', label: t('cost_control.ledger.tab_transfers', { defaultValue: 'Transfers' }) },
    { id: 'modifications', label: t('cost_control.ledger.tab_modifications', { defaultValue: 'Budget changes' }) },
    { id: 'history', label: t('cost_control.ledger.tab_history', { defaultValue: 'History' }) },
  ];

  return (
    <section aria-label={t('cost_control.ledger.title', { defaultValue: 'Budget moves and changes' })}>
      <div className="flex flex-wrap items-center gap-3 px-4 pt-4">
        <h3 className="text-sm font-semibold text-content-primary">
          {t('cost_control.ledger.title', { defaultValue: 'Budget moves and changes' })}
        </h3>
        {pending > 0 && (
          <Badge variant="warning" size="sm">
            {t('cost_control.ledger.pending', { defaultValue: '{{n}} waiting for a decision', n: pending })}
          </Badge>
        )}
        {canEdit && (
          <div className="ms-auto flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={() => setForm('transfer')}>
              {t('cost_control.ledger.new_transfer', { defaultValue: 'Move budget' })}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setForm('modification')}>
              {t('cost_control.ledger.new_modification', { defaultValue: 'Add a budget change' })}
            </Button>
          </div>
        )}
      </div>
      <p className="px-4 pt-1 text-xs text-content-tertiary">
        {t('cost_control.ledger.hint', {
          defaultValue:
            'Move budget between cost lines, or record a budget change the owner approved. Only approved entries change the revised budget in the table.',
        })}
      </p>

      {error && (
        <p role="alert" className="mx-4 mt-2 rounded-md bg-semantic-error-bg px-3 py-2 text-sm text-semantic-error">
          {error}
        </p>
      )}
      {form === 'transfer' && (
        <TransferForm projectId={projectId} onDone={created} onCancel={() => setForm(null)} onError={fail} />
      )}
      {form === 'modification' && (
        <ModificationForm projectId={projectId} onDone={created} onCancel={() => setForm(null)} onError={fail} />
      )}

      <div role="tablist" className="mt-3 flex gap-1 border-b border-border-light px-4">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={view === tab.id}
            className={`px-3 py-2 text-sm ${
              view === tab.id
                ? 'border-b-2 border-oe-blue font-medium text-content-primary'
                : 'text-content-secondary hover:text-content-primary'
            }`}
            onClick={() => setView(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {ledger.isLoading ? (
        <Skeleton className="m-4 h-16" />
      ) : ledger.isError ? (
        <p className="p-4 text-sm text-semantic-error">{getErrorMessage(ledger.error)}</p>
      ) : view === 'transfers' ? (
        data!.transfers.length === 0 ? (
          <Empty text={t('cost_control.ledger.empty_transfers', { defaultValue: 'No budget has been moved yet.' })} />
        ) : (
          <ul className="divide-y divide-border-light">{data!.transfers.map(transferRow)}</ul>
        )
      ) : view === 'modifications' ? (
        data!.modifications.length === 0 ? (
          <Empty
            text={t('cost_control.ledger.empty_modifications', { defaultValue: 'No owner budget changes yet.' })}
          />
        ) : (
          <ul className="divide-y divide-border-light">{data!.modifications.map(modRow)}</ul>
        )
      ) : (
        <History data={data!} currency={currency} />
      )}
    </section>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="p-4 text-sm text-content-tertiary">{text}</p>;
}

function History({ data, currency }: { data: BudgetLedger; currency: string }) {
  const { t } = useTranslation();
  if (data.audit.length === 0 && data.lines.length === 0) {
    return <Empty text={t('cost_control.ledger.empty_history', { defaultValue: 'Nothing recorded yet.' })} />;
  }
  const codeOf = new Map<string, string>([
    ...data.transfers.map((x) => [x.id, x.code] as [string, string]),
    ...data.modifications.map((x) => [x.id, x.code] as [string, string]),
  ]);
  return (
    <div className="space-y-4 p-4">
      {data.lines.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="pb-1 text-start text-xs font-medium text-content-secondary">
              {t('cost_control.ledger.effect_title', { defaultValue: 'Revised budget of the lines that moved' })}
            </caption>
            <thead>
              <tr className="text-xs text-content-tertiary">
                <th className="py-1 text-start font-medium">
                  {t('cost_control.ledger.col_line', { defaultValue: 'Cost line' })}
                </th>
                {(['original', 'transfers', 'modifications', 'revised', 'committed'] as const).map((k) => (
                  <th key={k} className="py-1 text-end font-medium">
                    {t(`cost_control.ledger.col_${k}`, { defaultValue: k })}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.lines.map((l) => (
                <tr key={l.cost_line_id} className="border-t border-border-light tabular-nums">
                  <td className="py-1 font-mono text-xs">{l.code}</td>
                  {(['original', 'transfers', 'modifications', 'revised', 'committed'] as const).map((k) => (
                    <td key={k} className="py-1 text-end">
                      {fmtCurrency(num(l[k]), currency)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ul className="space-y-1">
        {data.audit.map((a, i) => (
          <li key={`${a.entity_id}-${i}`} className="text-xs text-content-secondary">
            <span className="font-mono text-content-tertiary">{codeOf.get(a.entity_id) ?? ''}</span>{' '}
            {actionLabel(t, a.action)}
            {a.created_at ? `, ${a.created_at.slice(0, 16).replace('T', ' ')}` : ''}
            {a.note ? `: ${a.note}` : ''}
          </li>
        ))}
      </ul>
    </div>
  );
}

interface FormProps {
  projectId: string;
  onDone: () => void;
  onCancel: () => void;
  onError: (e: unknown) => void;
}

const FIELD = 'w-full rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-sm';

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-xs font-medium text-content-secondary">
      {label}
      <div className="mt-1 font-normal">{children}</div>
    </label>
  );
}

function TransferForm({ projectId, onDone, onCancel, onError }: FormProps) {
  const { t } = useTranslation();
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [amount, setAmount] = useState('');
  const [reason, setReason] = useState('');
  const value = num(amount);
  const valid = !!from && !!to && from !== to && value > 0 && !!reason.trim();
  const save = useMutation({
    mutationFn: () =>
      budgetLedgerApi.createTransfer(projectId, {
        reason,
        legs: [
          { cost_line_id: from, amount: (-value).toFixed(2) },
          { cost_line_id: to, amount: value.toFixed(2) },
        ],
      }),
    onSuccess: onDone,
    onError,
  });
  return (
    <div className="m-4 grid gap-3 rounded-lg border border-border-light p-4 sm:grid-cols-2">
      <Field label={t('cost_control.ledger.from_line', { defaultValue: 'From cost line' })}>
        <CostLinePicker projectId={projectId} value={from} onChange={setFrom} data-testid="ledger-from" />
      </Field>
      <Field label={t('cost_control.ledger.to_line', { defaultValue: 'To cost line' })}>
        <CostLinePicker projectId={projectId} value={to} onChange={setTo} data-testid="ledger-to" />
      </Field>
      <Field label={t('cost_control.ledger.amount', { defaultValue: 'Amount' })}>
        <input className={FIELD} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
      </Field>
      <Field label={t('cost_control.ledger.reason', { defaultValue: 'Reason' })}>
        <input className={FIELD} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      {from && from === to && (
        <p className="text-xs text-semantic-error sm:col-span-2">
          {t('cost_control.ledger.same_line', { defaultValue: 'Choose two different cost lines.' })}
        </p>
      )}
      <div className="flex gap-2 sm:col-span-2">
        <Button size="sm" disabled={!valid || save.isPending} onClick={() => save.mutate()}>
          {t('cost_control.ledger.save_draft', { defaultValue: 'Save as draft' })}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          {t('cost_control.ledger.cancel', { defaultValue: 'Cancel' })}
        </Button>
      </div>
    </div>
  );
}

function ModificationForm({ projectId, onDone, onCancel, onError }: FormProps) {
  const { t } = useTranslation();
  const [line, setLine] = useState('');
  const [amount, setAmount] = useState('');
  const [ref, setRef] = useState('');
  const [reason, setReason] = useState('');
  const value = num(amount);
  const valid = !!line && value !== 0 && !!reason.trim();
  const save = useMutation({
    mutationFn: () =>
      budgetLedgerApi.createModification(projectId, {
        cost_line_id: line,
        amount: value.toFixed(2),
        reason,
        approval_ref: ref,
      }),
    onSuccess: onDone,
    onError,
  });
  return (
    <div className="m-4 grid gap-3 rounded-lg border border-border-light p-4 sm:grid-cols-2">
      <Field label={t('cost_control.ledger.line', { defaultValue: 'Cost line' })}>
        <CostLinePicker projectId={projectId} value={line} onChange={setLine} data-testid="ledger-line" />
      </Field>
      <Field label={t('cost_control.ledger.amount_signed', { defaultValue: 'Amount (a minus sign lowers the budget)' })}>
        <input className={FIELD} inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
      </Field>
      <Field label={t('cost_control.ledger.approval_ref', { defaultValue: 'Owner approval (letter or minute no.)' })}>
        <input className={FIELD} value={ref} onChange={(e) => setRef(e.target.value)} />
      </Field>
      <Field label={t('cost_control.ledger.reason', { defaultValue: 'Reason' })}>
        <input className={FIELD} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <div className="flex gap-2 sm:col-span-2">
        <Button size="sm" disabled={!valid || save.isPending} onClick={() => save.mutate()}>
          {t('cost_control.ledger.save_draft', { defaultValue: 'Save as draft' })}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          {t('cost_control.ledger.cancel', { defaultValue: 'Cancel' })}
        </Button>
      </div>
    </div>
  );
}
