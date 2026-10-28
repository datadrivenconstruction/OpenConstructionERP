// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Framework agreements of the company and what has been called off from
// each. An agreement is shared by every project of the company, so its
// remaining value counts the call-offs of all of them. A package calls off
// from an agreement in its award plan; this screen keeps the agreements.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { FileText, Pencil, Plus, Trash2 } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { WideModal } from '@/shared/ui/WideModal';
import { fmtDate, fmtList, fmtPercent } from '@/shared/lib/formatters';

import {
  createFramework,
  localToday,
  patchFramework,
  setFrameworkState,
  type CallOffMode,
  type Capability,
  type Framework,
  type FrameworkLot,
  type FrameworkTarget,
  type PackageKind,
} from './api';
import { CompanyPicker, useCompanyRegister } from './CompanyPicker';
import { refusalText, useLedger } from './hooks';
import {
  CALL_OFF_MODE,
  FRAMEWORK_STATE,
  LEDGER_KIND,
  PACKAGE_KIND,
  PACKAGE_STATE,
  vocab,
  type KeyText,
  type LabelContext,
} from './labels';
import { FIELD_CLASS, FRAMEWORK_TONE, Field, Money, ProblemList, ReasonedButton, RefusalBox, ToneBadge } from './ProcurementBits';
import {
  FRAMEWORK_PROBLEM,
  calledOffShare,
  capVerdict,
  companyLinks,
  companyValue,
  frameworkProblems,
  notApplicable,
  toFrameworkInput,
  typedLots,
  toFrameworkPatch,
  type FrameworkDraft,
} from './rules';

const KINDS: PackageKind[] = ['works', 'supply', 'supply_and_install', 'design', 'services'];
const MODES: CallOffMode[] = ['direct', 'mini_competition'];

export const FRAMEWORK_MOVE: Record<FrameworkTarget, KeyText> = {
  active: ['procurement_concept.ui.framework.move_active', 'Activate'],
  exhausted: ['procurement_concept.ui.framework.move_exhausted', 'Mark as exhausted'],
  expired: ['procurement_concept.ui.framework.move_expired', 'Mark as expired'],
  terminated: ['procurement_concept.ui.framework.move_terminated', 'Terminate'],
};

export interface FrameworksProps {
  frameworks: Framework[];
  /** Whether the reader may add an agreement, from the list. */
  canCreate?: Capability;
  labels: LabelContext;
  onChanged: () => void;
}

export function Frameworks({ frameworks, canCreate, labels, onChanged }: FrameworksProps) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState<Framework | 'new' | null>(null);
  const [ledgerOf, setLedgerOf] = useState<string | null>(null);
  const [closing, setClosing] = useState<{ id: string; target: FrameworkTarget } | null>(null);

  const move = useMutation({
    mutationFn: (m: { id: string; target: FrameworkTarget }) => setFrameworkState(m.id, m.target),
    onSuccess: () => {
      setClosing(null);
      onChanged();
    },
  });
  // Expired and terminated are final, so they ask first.
  const startMove = (id: string, target: FrameworkTarget) => {
    move.reset();
    if (target === 'expired' || target === 'terminated') setClosing({ id, target });
    else move.mutate({ id, target });
  };

  const addButton = notApplicable(canCreate) ? undefined : (
    <ReasonedButton
      verdict={capVerdict(canCreate, 'permission_denied')}
      icon={<Plus size={14} />}
      onClick={() => setEditing('new')}
      data-testid="framework-add"
    >
      {t('procurement_concept.ui.framework.add', { defaultValue: 'Add framework agreement' })}
    </ReasonedButton>
  );

  return (
    <div className="space-y-3" data-testid="frameworks">
      {frameworks.length === 0 ? (
        <EmptyState
          icon={<FileText size={28} />}
          title={t('procurement_concept.ui.framework.empty_title', { defaultValue: 'No framework agreements yet' })}
          description={t('procurement_concept.ui.framework.empty_body', {
            defaultValue:
              'A framework agreement fixes a supplier, a scope and a maximum value once, so packages can call off from it without a new tender. Add the agreements your company holds; every project can then use them.',
          })}
          action={addButton}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-content-secondary">
              {t('procurement_concept.ui.framework.intro', {
                defaultValue: 'Agreements belong to the company. Their remaining value counts the call-offs of every project.',
              })}
            </p>
            {addButton}
          </div>
          {move.error ? <RefusalBox error={move.error} /> : null}
          <ul className="space-y-2">
            {frameworks.map((f) => (
              <li key={f.id} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="framework-entry" data-framework={f.code}>
                <div className="flex flex-wrap items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs text-content-tertiary">{f.code}</span>
                      <span className="font-medium text-content-primary">{f.title}</span>
                      <ToneBadge tone={FRAMEWORK_TONE[f.state]} testId="framework-state">
                        {vocab(labels.t, FRAMEWORK_STATE, f.state)}
                      </ToneBadge>
                    </div>
                    <dl className="mt-1.5 flex flex-wrap gap-x-6 gap-y-1 text-sm">
                      {f.supplier_name && (
                        <div>
                          <dt className="text-xs text-content-tertiary">{t('procurement_concept.ui.framework.supplier', { defaultValue: 'Supplier' })}</dt>
                          <dd className="text-content-primary">{f.supplier_name}</dd>
                        </div>
                      )}
                      <div>
                        <dt className="text-xs text-content-tertiary">{t('procurement_concept.ui.framework.max_value', { defaultValue: 'Maximum value' })}</dt>
                        <dd className="text-content-primary">
                          <Money value={f.max_value} currency={f.currency} />
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs text-content-tertiary">{t('procurement_concept.ui.framework.period', { defaultValue: 'Runs' })}</dt>
                        <dd className="text-content-primary">
                          {t('procurement_concept.ui.framework.period_value', {
                            defaultValue: '{{from}} to {{to}}',
                            from: fmtDate(f.start_date),
                            to: fmtDate(f.end_date),
                          })}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs text-content-tertiary">{t('procurement_concept.ui.framework.call_off_mode', { defaultValue: 'Call-off' })}</dt>
                        <dd className="text-content-primary">{vocab(labels.t, CALL_OFF_MODE, f.call_off_mode)}</dd>
                      </div>
                      {f.package_kinds.length > 0 && (
                        <div>
                          <dt className="text-xs text-content-tertiary">{t('procurement_concept.ui.framework.covers', { defaultValue: 'Covers' })}</dt>
                          <dd className="text-content-primary">{fmtList(f.package_kinds.map((k) => vocab(labels.t, PACKAGE_KIND, k)))}</dd>
                        </div>
                      )}
                    </dl>
                    {f.scope && <p className="mt-1.5 text-sm text-content-secondary">{f.scope}</p>}
                    {typedLots(f.lots).length > 0 && (
                      <div className="mt-1.5 text-sm" data-testid="framework-lots">
                        <span className="text-xs text-content-tertiary">{t('procurement_concept.ui.framework.lots', { defaultValue: 'Lots' })}</span>
                        <ul className="mt-0.5 flex flex-wrap gap-1.5">
                          {typedLots(f.lots).map((l, i) => (
                            <li key={i} className="rounded-full border border-border-light px-2 py-0.5 text-xs text-content-primary">
                              {l.code && <span className="font-mono text-content-tertiary">{l.code}</span>} {l.title}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center justify-end gap-1.5">
                    <Button
                      size="sm"
                      variant="secondary"
                      aria-expanded={ledgerOf === f.id}
                      onClick={() => setLedgerOf(ledgerOf === f.id ? null : f.id)}
                      data-testid="framework-ledger-toggle"
                    >
                      {t('procurement_concept.ui.framework.ledger', { defaultValue: 'Call-offs' })}
                    </Button>
                    {!notApplicable(f.can?.edit) && (
                      <ReasonedButton
                        quiet
                        verdict={capVerdict(f.can?.edit, 'permission_denied')}
                        size="sm"
                        variant="ghost"
                        icon={<Pencil size={14} />}
                        onClick={() => setEditing(f)}
                        data-testid="framework-edit"
                      >
                        {t('procurement_concept.ui.prequal.edit', { defaultValue: 'Change' })}
                      </ReasonedButton>
                    )}
                    {/* The moves the server allows this reader from the state the agreement is in. */}
                    {(f.can?.transitions ?? []).map((target) => (
                      <Button
                        key={target}
                        size="sm"
                        variant="ghost"
                        loading={move.isPending && move.variables?.id === f.id && move.variables.target === target}
                        onClick={() => startMove(f.id, target)}
                        data-testid={`framework-move-${target}`}
                      >
                        {vocab(labels.t, FRAMEWORK_MOVE, target)}
                      </Button>
                    ))}
                  </div>
                </div>
                {closing?.id === f.id && (
                  <div className="mt-2 flex flex-wrap items-center gap-2 rounded-md bg-surface-secondary p-2" data-testid="framework-close-confirm">
                    <span className="text-xs text-content-primary">
                      {t('procurement_concept.ui.framework.close_confirm', {
                        defaultValue: 'This closes the agreement for good. No package can call off from it afterwards.',
                      })}
                    </span>
                    <Button size="sm" variant="danger" loading={move.isPending} onClick={() => move.mutate(closing)} data-testid="framework-close-yes">
                      {vocab(labels.t, FRAMEWORK_MOVE, closing.target)}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setClosing(null)}>
                      {t('procurement_concept.ui.keep', { defaultValue: 'Not now' })}
                    </Button>
                  </div>
                )}
                {ledgerOf === f.id && <Ledger frameworkId={f.id} labels={labels} />}
              </li>
            ))}
          </ul>
        </>
      )}
      {editing && (
        <FrameworkDialog open onClose={() => setEditing(null)} framework={editing === 'new' ? null : editing} labels={labels} onSaved={onChanged} />
      )}
    </div>
  );
}

function Ledger({ frameworkId, labels }: { frameworkId: string; labels: LabelContext }) {
  const { t } = useTranslation();
  const q = useLedger(frameworkId);
  if (q.isLoading) {
    return (
      <p className="mt-3 text-sm text-content-tertiary">
        {t('procurement_concept.ui.ledger.loading', { defaultValue: 'Adding up the call-offs' })}
      </p>
    );
  }
  if (q.isError || !q.data) {
    return (
      <div className="mt-3 flex flex-wrap items-center gap-3" role="alert" data-testid="ledger-error">
        <span className="text-sm text-semantic-error">{refusalText(labels.t, q.error)}</span>
        <Button size="sm" variant="secondary" loading={q.isFetching} onClick={() => q.refetch()} data-testid="ledger-retry">
          {t('procurement_concept.ui.retry', { defaultValue: 'Try again' })}
        </Button>
      </div>
    );
  }
  const ledger = q.data;
  const share = calledOffShare(ledger);
  return (
    <div className="mt-3 rounded-md bg-surface-secondary p-3" data-testid="framework-ledger">
      <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 text-sm">
        <span>
          <span className="text-xs text-content-tertiary">{t('procurement_concept.ui.ledger.called_off', { defaultValue: 'Called off' })}</span>{' '}
          <span className="font-medium text-content-primary" data-testid="ledger-called-off">
            <Money value={ledger.call_off_value} currency={ledger.currency} />
          </span>
        </span>
        <span>
          <span className="text-xs text-content-tertiary">{t('procurement_concept.ui.ledger.remaining', { defaultValue: 'Remaining' })}</span>{' '}
          <span className="font-medium text-content-primary" data-testid="ledger-remaining">
            {ledger.remaining_known && ledger.remaining_value !== null ? (
              <Money value={ledger.remaining_value} currency={ledger.currency} />
            ) : (
              t('procurement_concept.ui.ledger.remaining_unknown', { defaultValue: 'cannot be determined' })
            )}
          </span>
        </span>
        <span className="text-xs text-content-tertiary">{fmtPercent(share * 100, 0)}</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-border-light" aria-hidden>
        <div className="h-full rounded-full bg-oe-blue" style={{ width: `${share * 100}%` }} />
      </div>
      {ledger.unconverted_entries > 0 && (
        <p className="mt-2 text-xs text-semantic-warning" data-testid="ledger-unconverted">
          {t('procurement_concept.ui.ledger.unconverted', {
            defaultValue: 'Entries in another currency are listed but not added up: {{n}}.',
            n: ledger.unconverted_entries,
          })}
        </p>
      )}
      {!ledger.complete && (
        <p className="mt-2 text-xs text-semantic-warning" data-testid="ledger-incomplete">
          {t('procurement_concept.ui.ledger.incomplete', {
            defaultValue: 'Some call-offs could not be read, so this list may miss entries.',
          })}
        </p>
      )}
      {ledger.items.length === 0 ? (
        <p className="mt-2 text-sm text-content-secondary">
          {t('procurement_concept.ui.ledger.empty', {
            defaultValue: 'Nothing called off yet. A package calls off from this agreement in its award plan.',
          })}
        </p>
      ) : (
        <table className="mt-2 w-full text-left text-sm">
          <thead className="text-xs text-content-tertiary">
            <tr>
              <th className="py-1 pr-3 font-medium">{t('procurement_concept.ui.ledger.col_kind', { defaultValue: 'Call-off' })}</th>
              <th className="py-1 pr-3 font-medium">{t('procurement_concept.ui.package.col_state', { defaultValue: 'State' })}</th>
              <th className="py-1 text-right font-medium">{t('procurement_concept.ui.ledger.col_amount', { defaultValue: 'Amount' })}</th>
            </tr>
          </thead>
          <tbody>
            {ledger.items.map((e) => (
              <tr key={`${e.kind}-${e.id}`} className="border-t border-border-light" data-testid="ledger-entry">
                <td className="py-1 pr-3 text-content-primary">{vocab(labels.t, LEDGER_KIND, e.kind)}</td>
                <td className="py-1 pr-3 text-content-secondary">
                  {e.kind === 'award_package' ? vocab(labels.t, PACKAGE_STATE, e.state as keyof typeof PACKAGE_STATE) : e.state}
                </td>
                <td className="py-1 text-right text-content-primary">
                  <Money value={e.amount} currency={e.currency || ledger.currency} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function FrameworkDialog({
  open,
  onClose,
  framework,
  labels,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  framework: Framework | null;
  labels: LabelContext;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<FrameworkDraft>({
    code: framework?.code ?? '',
    title: framework?.title ?? '',
    supplier_name: framework?.supplier_name ?? '',
    scope: framework?.scope ?? '',
    package_kinds: framework?.package_kinds ?? [],
    max_value: framework?.max_value ?? '',
    currency: framework?.currency ?? '',
    start_date: framework?.start_date ?? localToday(),
    end_date: framework?.end_date ?? '',
    call_off_mode: framework?.call_off_mode ?? 'direct',
    source_procedure_ref: framework?.source_procedure_ref ?? '',
    lots: typedLots(framework?.lots),
    subcontractor_id: framework?.subcontractor_id ?? '',
    vendor_id: framework?.subcontractor_id ? '' : (framework?.vendor_id ?? ''),
  });
  const register = useCompanyRegister(open);
  const supplier = companyValue({ subcontractor_id: draft.subcontractor_id ?? '', vendor_id: draft.vendor_id ?? '' });
  // A registered supplier gives the agreement its name; an unregistered one is typed.
  const pickSupplier = (value: string) =>
    setDraft((d) => ({ ...d, ...companyLinks(value), supplier_name: value ? (register.nameOf(value) ?? d.supplier_name) : d.supplier_name }));
  const lots = draft.lots ?? [];
  const setLot = (index: number, patch: FrameworkLot) =>
    set(
      'lots',
      lots.map((l, i) => (i === index ? { ...l, ...patch } : l)),
    );
  const set = <K extends keyof FrameworkDraft>(key: K, value: FrameworkDraft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const toggleKind = (k: PackageKind) =>
    set('package_kinds', draft.package_kinds.includes(k) ? draft.package_kinds.filter((x) => x !== k) : [...draft.package_kinds, k]);
  const problems = frameworkProblems(draft);

  const save = useMutation({
    mutationFn: () => (framework ? patchFramework(framework.id, toFrameworkPatch(draft, framework.lots, framework)) : createFramework(toFrameworkInput(draft))),
    onSuccess: () => {
      onSaved();
      onClose();
    },
  });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="lg"
      testId="framework-dialog"
      title={
        framework
          ? t('procurement_concept.ui.framework.edit_title', { defaultValue: 'Framework agreement {{code}}', code: framework.code })
          : t('procurement_concept.ui.framework.add', { defaultValue: 'Add framework agreement' })
      }
      subtitle={t('procurement_concept.ui.framework.subtitle', {
        defaultValue: 'The supplier, what the agreement covers, its ceiling and how long it runs.',
      })}
      footer={
        <div className="flex w-full flex-wrap items-center justify-end gap-3">
          <ProblemList problems={problems.map((p) => FRAMEWORK_PROBLEM[p])} />
          <Button variant="ghost" onClick={onClose} disabled={save.isPending}>
            {t('procurement_concept.ui.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button loading={save.isPending} disabled={problems.length > 0} onClick={() => save.mutate()} data-testid="framework-save">
            {t('procurement_concept.ui.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        <RefusalBox error={save.error} />
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label={t('procurement_concept.ui.framework.code', { defaultValue: 'Code' })} htmlFor="fw-code">
            <input id="fw-code" className={FIELD_CLASS} disabled={!!framework} value={draft.code} onChange={(e) => set('code', e.target.value)} />
          </Field>
          <Field className="sm:col-span-2" label={t('procurement_concept.ui.framework.title_field', { defaultValue: 'Title' })} htmlFor="fw-title">
            <input id="fw-title" className={FIELD_CLASS} value={draft.title} onChange={(e) => set('title', e.target.value)} />
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <CompanyPicker
            id="fw-company"
            label={t('procurement_concept.ui.framework.supplier', { defaultValue: 'Supplier' })}
            value={supplier}
            keptName={framework?.supplier_name}
            register={register}
            onChange={pickSupplier}
          />
          {!supplier && (
            <Field label={t('procurement_concept.ui.candidate.free_name', { defaultValue: 'Company name' })} htmlFor="fw-supplier">
              <input id="fw-supplier" className={FIELD_CLASS} value={draft.supplier_name} onChange={(e) => set('supplier_name', e.target.value)} />
            </Field>
          )}
        </div>
        <Field label={t('procurement_concept.ui.framework.scope', { defaultValue: 'What it covers' })} htmlFor="fw-scope">
          <textarea id="fw-scope" rows={2} className={FIELD_CLASS} value={draft.scope} onChange={(e) => set('scope', e.target.value)} />
        </Field>
        <fieldset data-testid="framework-lot-editor">
          <legend className="mb-1 text-xs font-medium text-content-secondary">
            {t('procurement_concept.ui.framework.lots', { defaultValue: 'Lots' })}
          </legend>
          <p className="mb-2 text-xs text-content-tertiary">
            {t('procurement_concept.ui.framework.lots_hint', {
              defaultValue: 'Only when the agreement is divided into lots: give each its code and what it covers.',
            })}
          </p>
          <ul className="space-y-2">
            {lots.map((l, i) => (
              <li key={i} className="flex items-center gap-2" data-testid="framework-lot">
                <input
                  className={`${FIELD_CLASS} w-28`}
                  maxLength={64}
                  aria-label={t('procurement_concept.ui.framework.lot_code', { defaultValue: 'Lot code' })}
                  placeholder={t('procurement_concept.ui.framework.lot_code', { defaultValue: 'Lot code' })}
                  value={l.code ?? ''}
                  onChange={(e) => setLot(i, { code: e.target.value })}
                />
                <input
                  className={`${FIELD_CLASS} flex-1`}
                  maxLength={255}
                  aria-label={t('procurement_concept.ui.framework.lot_title', { defaultValue: 'What the lot covers' })}
                  placeholder={t('procurement_concept.ui.framework.lot_title', { defaultValue: 'What the lot covers' })}
                  value={l.title ?? ''}
                  onChange={(e) => setLot(i, { title: e.target.value })}
                />
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Trash2 size={14} />}
                  aria-label={t('procurement_concept.ui.framework.lot_remove', { defaultValue: 'Remove this lot' })}
                  onClick={() => set('lots', lots.filter((_, j) => j !== i))}
                  data-testid="framework-lot-remove"
                >
                  {null}
                </Button>
              </li>
            ))}
          </ul>
          <Button
            className="mt-2"
            size="sm"
            variant="secondary"
            icon={<Plus size={14} />}
            disabled={lots.length >= 50}
            onClick={() => set('lots', [...lots, { code: '', title: '' }])}
            data-testid="framework-lot-add"
          >
            {t('procurement_concept.ui.framework.lot_add', { defaultValue: 'Add a lot' })}
          </Button>
        </fieldset>
        <fieldset>
          <legend className="mb-1 text-xs font-medium text-content-secondary">
            {t('procurement_concept.ui.framework.kinds', { defaultValue: 'Kinds of package that may call off' })}
          </legend>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {KINDS.map((k) => (
              <label key={k} className="inline-flex items-center gap-1.5 text-sm text-content-primary">
                <input type="checkbox" checked={draft.package_kinds.includes(k)} onChange={() => toggleKind(k)} />
                {vocab(labels.t, PACKAGE_KIND, k)}
              </label>
            ))}
          </div>
        </fieldset>
        <div className="grid gap-4 sm:grid-cols-4">
          <Field className="sm:col-span-2" label={t('procurement_concept.ui.framework.max_value', { defaultValue: 'Maximum value' })} htmlFor="fw-max">
            <input id="fw-max" inputMode="decimal" className={FIELD_CLASS} value={draft.max_value} onChange={(e) => set('max_value', e.target.value)} />
          </Field>
          <Field label={t('procurement_concept.ui.package.currency', { defaultValue: 'Currency' })} htmlFor="fw-currency">
            <input
              id="fw-currency"
              maxLength={3}
              disabled={!!framework}
              className={`${FIELD_CLASS} uppercase`}
              value={draft.currency}
              onChange={(e) => set('currency', e.target.value)}
            />
          </Field>
          <Field label={t('procurement_concept.ui.framework.call_off_mode', { defaultValue: 'Call-off' })} htmlFor="fw-mode">
            <select id="fw-mode" className={FIELD_CLASS} value={draft.call_off_mode} onChange={(e) => set('call_off_mode', e.target.value as CallOffMode)}>
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {vocab(labels.t, CALL_OFF_MODE, m)}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t('procurement_concept.ui.framework.start_date', { defaultValue: 'Starts on' })} htmlFor="fw-start">
            <input id="fw-start" type="date" disabled={!!framework} className={FIELD_CLASS} value={draft.start_date} onChange={(e) => set('start_date', e.target.value)} />
          </Field>
          <Field label={t('procurement_concept.ui.framework.end_date', { defaultValue: 'Ends on' })} htmlFor="fw-end">
            <input id="fw-end" type="date" className={FIELD_CLASS} value={draft.end_date} onChange={(e) => set('end_date', e.target.value)} />
          </Field>
        </div>
        <Field
          label={t('procurement_concept.ui.framework.source_ref', { defaultValue: 'How the agreement was awarded' })}
          htmlFor="fw-source"
        >
          <input id="fw-source" className={FIELD_CLASS} value={draft.source_procedure_ref} onChange={(e) => set('source_procedure_ref', e.target.value)} />
        </Field>
      </div>
    </WideModal>
  );
}
