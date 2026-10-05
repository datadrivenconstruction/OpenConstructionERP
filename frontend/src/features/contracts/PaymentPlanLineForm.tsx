// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// PaymentPlanLineForm - add or change one instalment of a payment plan.
//
// The words are the ones a builder uses on site: what the payment is for, how
// much, when it becomes payable, how many days later it can be claimed and how
// long the client has to pay. The schedule link is the reason the plan exists,
// so it sits right under "becomes payable" and only matters when the answer
// is "when the work is finished" or "when it is approved". Only the first is
// reached by the schedule; an approval waits for a person, and the form says so.
//
// A change sends only the fields the person changed. An emptied date or
// payment-terms box goes as an explicit null, which the API clears, and a
// switch between a fixed amount and a percentage clears the other one, since a
// stored amount would otherwise keep winning over the new percentage.
//
// The schedule link has its own route, so linking and unlinking go through it.
//
// Amounts stay the strings the person typed (normalised to a dot decimal), so
// a Decimal is never rounded through a float on its way to the server.

import { useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { TFunction } from 'i18next';
import { Button } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { formatCurrency } from '@/shared/lib/money';
import {
  parseDecimalInput,
  parseMoneyInput,
  stripCurrencySigns,
  toDecimalPayloadString,
} from '@/shared/lib/parseDecimal';
import {
  MILESTONE_KINDS,
  MILESTONE_TRIGGERS,
  createContractMilestone,
  linkMilestoneActivity,
  paymentPlanKey,
  updateContractMilestone,
  type ContractMilestoneCreate,
  type ContractMilestoneUpdate,
  type MilestoneKind,
  type MilestoneTrigger,
  type PaymentPlanLine,
} from './api';
import { ScheduleMilestonePicker } from './ScheduleMilestonePicker';

type Basis = 'amount' | 'percent';

interface Draft {
  name: string;
  kind: MilestoneKind;
  basis: Basis;
  amount: string;
  percent: string;
  trigger: MilestoneTrigger;
  activity_id: string;
  planned_date: string;
  lag_days: string;
  payment_terms_days: string;
  client_visible: boolean;
}

function asKind(v: string): MilestoneKind {
  return (MILESTONE_KINDS as readonly string[]).includes(v) ? (v as MilestoneKind) : 'progress';
}

function asTrigger(v: string): MilestoneTrigger {
  return (MILESTONE_TRIGGERS as readonly string[]).includes(v) ? (v as MilestoneTrigger) : 'date';
}

function emptyDraft(): Draft {
  return {
    name: '',
    kind: 'progress',
    basis: 'amount',
    amount: '',
    percent: '',
    trigger: 'completion',
    activity_id: '',
    planned_date: '',
    lag_days: '0',
    payment_terms_days: '',
    client_visible: false,
  };
}

function draftFrom(line: PaymentPlanLine): Draft {
  const hasValue = line.value != null && String(line.value) !== '';
  return {
    name: line.name,
    kind: asKind(line.kind),
    basis: hasValue || line.percent_of_contract == null ? 'amount' : 'percent',
    amount: hasValue ? String(line.value) : '',
    percent: line.percent_of_contract != null ? String(line.percent_of_contract) : '',
    trigger: asTrigger(line.trigger),
    activity_id: line.activity_id ?? '',
    planned_date: line.planned_date ? line.planned_date.slice(0, 10) : '',
    lag_days: String(line.lag_days ?? 0),
    payment_terms_days: line.payment_terms_days != null ? String(line.payment_terms_days) : '',
    client_visible: line.client_visible,
  };
}

/** A whole number of days in 0..365, or null. */
function parseDays(raw: string): number | null {
  const n = parseDecimalInput(raw);
  if (n === null || !Number.isInteger(n) || n < 0 || n > 365) return null;
  return n;
}

/** The draft's values as they go on the wire. */
interface ParsedDraft {
  lag: number;
  terms: number | null;
  value: string | null;
  percent: string | null;
}

/** What differs between the saved line and the draft, so an edit sends only that. */
function changedFields(before: Draft, after: Draft, parsed: ParsedDraft): ContractMilestoneUpdate {
  const out: ContractMilestoneUpdate = {};
  if (after.name.trim() !== before.name.trim()) out.name = after.name.trim();
  if (after.kind !== before.kind) out.kind = after.kind;
  if (after.trigger !== before.trigger) out.trigger = after.trigger;
  if (after.client_visible !== before.client_visible) out.client_visible = after.client_visible;
  if (parsed.lag !== parseDays(before.lag_days)) out.lag_days = parsed.lag;
  if (after.planned_date.trim() !== before.planned_date) {
    out.planned_date = after.planned_date.trim() || null;
  }
  const termsBefore =
    before.payment_terms_days.trim() === '' ? null : parseDays(before.payment_terms_days);
  if (parsed.terms !== termsBefore) out.payment_terms_days = parsed.terms;
  if (after.basis !== before.basis) {
    // The other basis is cleared, or a stored amount would keep winning.
    if (after.basis === 'amount') {
      out.value = parsed.value;
      out.percent_of_contract = null;
    } else {
      out.percent_of_contract = parsed.percent;
      out.value = null;
    }
  } else if (after.basis === 'amount' && after.amount.trim() !== before.amount.trim()) {
    out.value = parsed.value;
  } else if (after.basis === 'percent' && after.percent.trim() !== before.percent.trim()) {
    out.percent_of_contract = parsed.percent;
  }
  return out;
}

export function kindLabel(t: TFunction, kind: string): string {
  switch (kind) {
    case 'deposit':
      return t('contracts.plan_kind_deposit', { defaultValue: 'Deposit' });
    case 'final':
      return t('contracts.plan_kind_final', { defaultValue: 'Final payment' });
    case 'progress':
      return t('contracts.plan_kind_progress', { defaultValue: 'Stage payment' });
    default:
      return kind;
  }
}

export function triggerLabel(t: TFunction, trigger: string): string {
  switch (trigger) {
    case 'date':
      return t('contracts.plan_trigger_date', { defaultValue: 'On a fixed date' });
    case 'completion':
      return t('contracts.plan_trigger_completion', { defaultValue: 'When the work is finished' });
    case 'approval':
      return t('contracts.plan_trigger_approval', { defaultValue: 'When the work is approved' });
    default:
      return trigger;
  }
}

export function linkWarningLabel(t: TFunction, code: string): string {
  switch (code) {
    case 'date_trigger_ignores_schedule':
      return t('contracts.plan_warning_date_trigger_ignores_schedule', {
        defaultValue:
          'This instalment is paid on a fixed date, so the schedule does not move it. Choose "When the work is finished" if it should wait for the work.',
      });
    default:
      return code;
  }
}

/** The link route refuses a task: only a milestone is ever reported reached. */
function saveErrorMessage(t: TFunction, err: unknown): string {
  if (err instanceof ApiError) {
    const detail = (err.body as { detail?: unknown } | undefined)?.detail;
    const code =
      detail && typeof detail === 'object' ? (detail as { error?: unknown }).error : undefined;
    if (code === 'activity_not_milestone') {
      return t('contracts.plan_error_activity_not_milestone', {
        defaultValue:
          'This schedule activity is not a milestone, so the schedule will never report it done. Mark it as a milestone in the schedule first.',
      });
    }
  }
  return getErrorMessage(err);
}

export function PaymentPlanLineForm({
  contractId,
  projectId,
  currency,
  contractTotal,
  defaultTermsDays,
  line,
  onDone,
}: {
  contractId: string;
  projectId: string;
  currency: string;
  contractTotal: number | string;
  defaultTermsDays: number | null;
  /** The line being changed, or null for a new one. */
  line: PaymentPlanLine | null;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [draft, setDraft] = useState<Draft>(() => (line ? draftFrom(line) : emptyDraft()));
  const [tried, setTried] = useState(false);

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((prev) => ({ ...prev, [key]: value }));

  const saved = useMemo(() => (line ? draftFrom(line) : null), [line]);
  const createdId = useRef<string | null>(null);

  const amountNum = parseMoneyInput(draft.amount);
  const percentNum = parseDecimalInput(draft.percent);
  const lagNum = parseDays(draft.lag_days);
  const termsNum = draft.payment_terms_days.trim() === '' ? null : parseDays(draft.payment_terms_days);

  const errors = {
    name: draft.name.trim() === '',
    amount:
      draft.basis === 'amount'
        ? amountNum === null || amountNum <= 0
        : percentNum === null || percentNum <= 0 || percentNum > 100,
    lag: lagNum === null,
    terms: draft.payment_terms_days.trim() !== '' && termsNum === null,
  };
  const valid = !errors.name && !errors.amount && !errors.lag && !errors.terms;

  const saveMut = useMutation({
    mutationFn: async (): Promise<string[]> => {
      const parsed: ParsedDraft = {
        lag: lagNum ?? 0,
        terms: termsNum,
        value:
          draft.basis === 'amount' ? toDecimalPayloadString(stripCurrencySigns(draft.amount)) : null,
        percent: draft.basis === 'percent' ? toDecimalPayloadString(draft.percent) : null,
      };

      let milestoneId: string;
      let linkedBefore = '';
      if (line && saved) {
        milestoneId = line.id;
        linkedBefore = line.activity_id ?? '';
        const changes = changedFields(saved, draft, parsed);
        if (Object.keys(changes).length > 0) await updateContractMilestone(line.id, changes);
      } else if (createdId.current) {
        // A create went through and its link failed: Save again only links,
        // or a second instalment with the same amount would be written.
        milestoneId = createdId.current;
      } else {
        const body: ContractMilestoneCreate = {
          contract_id: contractId,
          name: draft.name.trim(),
          kind: draft.kind,
          trigger: draft.trigger,
          lag_days: parsed.lag,
          client_visible: draft.client_visible,
        };
        if (draft.planned_date.trim()) body.planned_date = draft.planned_date.trim();
        if (parsed.terms !== null) body.payment_terms_days = parsed.terms;
        if (draft.basis === 'amount') body.value = parsed.value;
        else body.percent_of_contract = parsed.percent;
        const created = await createContractMilestone(contractId, body);
        createdId.current = created.id;
        milestoneId = created.id;
      }
      if (draft.activity_id === linkedBefore) return [];
      const linked = await linkMilestoneActivity(milestoneId, draft.activity_id || null);
      return linked.warnings ?? [];
    },
    onSuccess: (warnings) => {
      qc.invalidateQueries({ queryKey: paymentPlanKey(contractId) });
      addToast({
        type: 'success',
        title: t('contracts.plan_saved', { defaultValue: 'Instalment saved' }),
      });
      for (const code of warnings) {
        addToast({ type: 'warning', title: linkWarningLabel(t, code) });
      }
      onDone();
    },
    onError: (err) => {
      // A create that went through before the link failed still left a row.
      qc.invalidateQueries({ queryKey: paymentPlanKey(contractId) });
      addToast({ type: 'error', title: saveErrorMessage(t, err) });
    },
  });

  const submit = () => {
    setTried(true);
    if (!valid || saveMut.isPending) return;
    saveMut.mutate();
  };

  const inputCls =
    'rounded-md border border-border-light bg-surface-elevated px-2 py-1.5 text-sm';
  const labelCls = 'text-xs text-content-tertiary';
  const hintCls = 'text-2xs text-content-tertiary';
  const errCls = 'text-2xs text-semantic-error';
  const followsSchedule = draft.trigger !== 'date';
  const idBase = line ? `plan-line-${line.id}` : 'plan-line-new';

  return (
    <form
      className="mt-3 rounded-lg bg-surface-secondary p-3"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-secondary">
        {line
          ? t('contracts.plan_form_title_edit', { defaultValue: 'Change instalment' })
          : t('contracts.plan_form_title_new', { defaultValue: 'New instalment' })}
      </p>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className={labelCls}>
            {t('contracts.plan_field_name', { defaultValue: 'What is it for' })}
          </span>
          <input
            className={inputCls}
            value={draft.name}
            onChange={(e) => set('name', e.target.value)}
            placeholder={t('contracts.plan_field_name_placeholder', {
              defaultValue: 'e.g. Roof finished',
            })}
            maxLength={500}
          />
          {tried && errors.name && (
            <span className={errCls}>
              {t('contracts.plan_name_required', { defaultValue: 'Give the instalment a name.' })}
            </span>
          )}
        </label>

        <label className="flex flex-col gap-1">
          <span className={labelCls}>
            {t('contracts.plan_field_kind', { defaultValue: 'Type of payment' })}
          </span>
          <select
            className={inputCls}
            value={draft.kind}
            onChange={(e) => set('kind', asKind(e.target.value))}
          >
            {MILESTONE_KINDS.map((k) => (
              <option key={k} value={k}>
                {kindLabel(t, k)}
              </option>
            ))}
          </select>
          {draft.kind === 'deposit' && (
            <span className={hintCls}>
              {t('contracts.plan_kind_deposit_hint', {
                defaultValue:
                  'Paid before the work starts. Some states and countries limit how much a deposit may be.',
              })}{' '}
              {t('contracts.plan_kind_deposit_retention', {
                defaultValue: 'No retention is held back from a deposit.',
              })}
            </span>
          )}
        </label>

        <fieldset className="flex flex-col gap-1">
          <legend className={labelCls}>
            {t('contracts.plan_field_basis', { defaultValue: 'Amount as' })}
          </legend>
          <div className="flex gap-3 text-sm">
            <label className="inline-flex items-center gap-1.5">
              <input
                type="radio"
                name={`${idBase}-basis`}
                checked={draft.basis === 'amount'}
                onChange={() => set('basis', 'amount')}
              />
              {t('contracts.plan_basis_amount', { defaultValue: 'Fixed amount' })}
            </label>
            <label className="inline-flex items-center gap-1.5">
              <input
                type="radio"
                name={`${idBase}-basis`}
                checked={draft.basis === 'percent'}
                onChange={() => set('basis', 'percent')}
              />
              {t('contracts.plan_basis_percent', { defaultValue: 'Percent of the contract' })}
            </label>
          </div>
        </fieldset>

        {draft.basis === 'amount' ? (
          <label className="flex flex-col gap-1">
            <span className={labelCls}>
              {t('contracts.plan_field_amount', {
                currency,
                defaultValue: 'Amount ({{currency}})',
              })}
            </span>
            <input
              className={inputCls}
              value={draft.amount}
              onChange={(e) => set('amount', e.target.value)}
              inputMode="decimal"
              autoComplete="off"
            />
            {tried && errors.amount && (
              <span className={errCls}>
                {t('contracts.plan_amount_required', {
                  defaultValue: 'Enter an amount above zero.',
                })}
              </span>
            )}
          </label>
        ) : (
          <label className="flex flex-col gap-1">
            <span className={labelCls}>
              {t('contracts.plan_field_percent', { defaultValue: 'Percent of the contract' })}
            </span>
            <input
              className={inputCls}
              value={draft.percent}
              onChange={(e) => set('percent', e.target.value)}
              inputMode="decimal"
              autoComplete="off"
            />
            {percentNum !== null && percentNum > 0 && percentNum <= 100 && (
              <span className={hintCls}>
                {t('contracts.plan_percent_preview', {
                  amount: formatCurrency((Number(contractTotal) * percentNum) / 100, currency),
                  total: formatCurrency(contractTotal, currency),
                  defaultValue: 'That is {{amount}} of {{total}}.',
                })}
              </span>
            )}
            {tried && errors.amount && (
              <span className={errCls}>
                {t('contracts.plan_percent_required', {
                  defaultValue: 'Enter a percentage between 0 and 100.',
                })}
              </span>
            )}
          </label>
        )}

        <label className="flex flex-col gap-1">
          <span className={labelCls}>
            {t('contracts.plan_field_trigger', { defaultValue: 'Becomes payable' })}
          </span>
          <select
            className={inputCls}
            value={draft.trigger}
            onChange={(e) => set('trigger', asTrigger(e.target.value))}
          >
            {MILESTONE_TRIGGERS.map((tr) => (
              <option key={tr} value={tr}>
                {triggerLabel(t, tr)}
              </option>
            ))}
          </select>
          {draft.trigger === 'completion' && (
            <span className={hintCls}>
              {t('contracts.plan_trigger_completion_hint', {
                defaultValue: 'Ready to claim as soon as the schedule marks the milestone done.',
              })}
            </span>
          )}
          {draft.trigger === 'approval' && (
            <span className={hintCls}>
              {t('contracts.plan_trigger_approval_hint', {
                defaultValue:
                  'Ready to claim only after someone marks it reached here. The schedule moves the expected date but never approves the work.',
              })}
            </span>
          )}
        </label>

        <div className="flex flex-col gap-1">
          <label htmlFor={`${idBase}-activity`} className={labelCls}>
            {t('contracts.plan_field_activity', { defaultValue: 'Waits for this schedule milestone' })}
          </label>
          <ScheduleMilestonePicker
            id={`${idBase}-activity`}
            projectId={projectId}
            value={draft.activity_id}
            onChange={(v) => set('activity_id', v)}
            currentActivityName={line?.activity_name}
            currentActivityMissing={line?.activity_missing}
          />
          <span className={hintCls}>
            {followsSchedule
              ? t('contracts.plan_field_activity_hint', {
                  defaultValue: 'When the schedule moves this milestone, the due date moves with it.',
                })
              : t('contracts.plan_field_activity_hint_date', {
                  defaultValue: 'A fixed-date instalment does not move with the schedule.',
                })}
          </span>
        </div>

        <label className="flex flex-col gap-1">
          <span className={labelCls}>
            {t('contracts.plan_field_planned_date', { defaultValue: 'Date in the contract' })}
          </span>
          <input
            type="date"
            className={inputCls}
            value={draft.planned_date}
            onChange={(e) => set('planned_date', e.target.value)}
          />
          <span className={hintCls}>
            {t('contracts.plan_field_planned_date_hint', {
              defaultValue:
                'Used when the instalment is not linked to the schedule, and to show how far a linked one has moved.',
            })}
          </span>
        </label>

        <label className="flex flex-col gap-1">
          <span className={labelCls}>
            {t('contracts.plan_field_lag', { defaultValue: 'Days after the milestone you can claim' })}
          </span>
          <input
            className={inputCls}
            value={draft.lag_days}
            onChange={(e) => set('lag_days', e.target.value)}
            inputMode="numeric"
            autoComplete="off"
          />
          <span className={hintCls}>
            {t('contracts.plan_field_lag_hint', {
              defaultValue: 'For example, time for an inspection. 0 means the same day.',
            })}
          </span>
          {tried && errors.lag && (
            <span className={errCls}>
              {t('contracts.plan_days_invalid', {
                defaultValue: 'Enter a whole number of days from 0 to 365.',
              })}
            </span>
          )}
        </label>

        <label className="flex flex-col gap-1">
          <span className={labelCls}>
            {t('contracts.plan_field_terms', { defaultValue: 'Days the client has to pay' })}
          </span>
          <input
            className={inputCls}
            value={draft.payment_terms_days}
            onChange={(e) => set('payment_terms_days', e.target.value)}
            placeholder={defaultTermsDays != null ? String(defaultTermsDays) : ''}
            inputMode="numeric"
            autoComplete="off"
          />
          <span className={hintCls}>
            {defaultTermsDays != null
              ? t('contracts.plan_field_terms_hint', {
                  count: defaultTermsDays,
                  defaultValue_one: 'Leave empty to use the contract terms: {{count}} day.',
                  defaultValue_other: 'Leave empty to use the contract terms: {{count}} days.',
                })
              : t('contracts.plan_field_terms_hint_none', {
                  defaultValue: 'Leave empty if the client pays on the day it is claimed.',
                })}
          </span>
          {tried && errors.terms && (
            <span className={errCls}>
              {t('contracts.plan_days_invalid', {
                defaultValue: 'Enter a whole number of days from 0 to 365.',
              })}
            </span>
          )}
        </label>

        <label className="flex items-start gap-2 sm:col-span-2">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={draft.client_visible}
            onChange={(e) => set('client_visible', e.target.checked)}
          />
          <span className="flex flex-col">
            <span className="text-sm text-content-primary">
              {t('contracts.plan_field_client_visible', {
                defaultValue: 'Show this instalment to the client in the portal',
              })}
            </span>
            <span className={hintCls}>
              {t('contracts.plan_field_client_visible_hint', {
                defaultValue: 'The client sees the amount, the expected date and whether it moved.',
              })}
            </span>
          </span>
        </label>
      </div>

      <div className="mt-3 flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onDone}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button type="submit" variant="primary" size="sm" loading={saveMut.isPending}>
          {t('common.save', { defaultValue: 'Save' })}
        </Button>
      </div>
    </form>
  );
}
