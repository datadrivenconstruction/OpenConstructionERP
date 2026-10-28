// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The short dialogs of one plant item: a lead time quote, the capacity
// reservation, the procurement route, the delivery limits, a spare line and
// the handover. Each one sends a single request and shows the server's reason
// in place when it is refused.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';

import { WideModal, WideModalSection } from '@/shared/ui/WideModal';

import {
  addQuote,
  createSlot,
  createSpare,
  handoverItem,
  localToday,
  putLimits,
  setRoute,
  updateSlot,
  updateSpare,
  type FeeRefundable,
  type LeadBasis,
  type Limit,
  type PlantCatalogue,
  type PlantItem,
  type ProcurementRouteCode,
  type Slot,
  type Spare,
} from './api';
import { FEE_REFUNDABLE, LEAD_BASIS, catalogueName, vocab, type LabelContext } from './labels';
import { DialogFooter, Field, Refusal, fieldClass } from './PlantBits';
import {
  emptyQuoteDraft,
  emptySlotDraft,
  quoteProblems,
  slotChanges,
  slotProblems,
  spareChanges,
  spareProblems,
  toQuoteInput,
  toSlotInput,
  toSpareInput,
  type Problem,
  type QuoteDraft,
  type SlotDraft,
  type SpareDraft,
} from './rules';

interface ItemDialogBase {
  open: boolean;
  onClose: () => void;
  projectId: string;
  item: PlantItem;
  onSaved: () => void;
}

interface WithCatalogue {
  catalogue: PlantCatalogue;
  labels: LabelContext;
}

const LEAD_BASES: LeadBasis[] = ['from_order', 'from_approved_drawings', 'from_down_payment'];
const REFUNDS: FeeRefundable[] = ['none', 'partial', 'full'];

/* ── Lead time quote ──────────────────────────────────────────────────── */

export function QuoteDialog({ open, onClose, projectId, item, catalogue, labels, onSaved }: ItemDialogBase & WithCatalogue) {
  const { t } = useTranslation();
  const [draft, setDraft] = useState<QuoteDraft>(emptyQuoteDraft);
  const [tried, setTried] = useState(false);
  const today = localToday();
  const problems = quoteProblems(draft, today);
  const set = <K extends keyof QuoteDraft>(key: K, value: QuoteDraft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const save = useMutation({
    mutationFn: () => addQuote(projectId, item.id, toQuoteInput(draft)),
    onSuccess: onSaved,
  });
  const submit = () => {
    setTried(true);
    if (problems.length === 0) save.mutate();
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="lg"
      testId="plant-quote-dialog"
      title={t('plant.quote.add_title', { defaultValue: 'Add a lead time' })}
      subtitle={t('plant.quote.add_subtitle', {
        defaultValue: 'A lead time counts only with the date it was asked and who answered. Earlier ones stay on the record.',
      })}
      footer={
        <DialogFooter
          problems={problems}
          showProblems={tried}
          busy={save.isPending}
          submitLabel={t('plant.quote.add_submit', { defaultValue: 'Add lead time' })}
          onCancel={onClose}
          onSubmit={submit}
        />
      }
    >
      <div className="space-y-5">
        <Refusal error={save.error} />
        <WideModalSection columns={2}>
          <Field label={t('plant.field.source', { defaultValue: 'Source' })} required>
            {(id) => (
              <select id={id} className={fieldClass} value={draft.source} onChange={(e) => set('source', e.target.value)}>
                <option value="">{t('plant.common.choose', { defaultValue: 'Choose' })}</option>
                {catalogue.lead_time_sources.map((s) => (
                  <option key={s.code} value={s.code}>
                    {catalogueName(labels, catalogue, 'lead_time_sources', s.code)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field
            label={t('plant.quote.source_name', { defaultValue: 'Who answered' })}
            hint={t('plant.quote.source_name_hint', { defaultValue: 'The supplier, the framework or the expert the figure comes from.' })}
          >
            {(id) => (
              <input id={id} className={fieldClass} value={draft.source_name} onChange={(e) => set('source_name', e.target.value)} />
            )}
          </Field>
          <Field label={t('plant.field.enquiry_date', { defaultValue: 'Enquiry date' })} required>
            {(id) => (
              <input
                id={id}
                type="date"
                max={today}
                className={fieldClass}
                value={draft.enquiry_date}
                onChange={(e) => set('enquiry_date', e.target.value)}
              />
            )}
          </Field>
          <Field label={t('plant.field.response_date', { defaultValue: 'Response date' })}>
            {(id) => (
              <input
                id={id}
                type="date"
                className={fieldClass}
                value={draft.response_date}
                onChange={(e) => set('response_date', e.target.value)}
              />
            )}
          </Field>
          <Field label={t('plant.quote.weeks_min', { defaultValue: 'Shortest lead time (weeks)' })} required>
            {(id) => (
              <input
                id={id}
                inputMode="numeric"
                className={fieldClass}
                value={draft.lead_weeks_min}
                onChange={(e) => set('lead_weeks_min', e.target.value)}
              />
            )}
          </Field>
          <Field
            label={t('plant.quote.weeks_max', { defaultValue: 'Longest lead time (weeks)' })}
            hint={t('plant.quote.weeks_max_hint', { defaultValue: 'Dates are planned on the longest. Leave empty for a single figure.' })}
          >
            {(id) => (
              <input
                id={id}
                inputMode="numeric"
                className={fieldClass}
                value={draft.lead_weeks_max}
                onChange={(e) => set('lead_weeks_max', e.target.value)}
              />
            )}
          </Field>
          <Field label={t('plant.field.lead_basis', { defaultValue: 'Lead time runs from' })}>
            {(id) => (
              <select
                id={id}
                className={fieldClass}
                value={draft.lead_basis}
                onChange={(e) => set('lead_basis', e.target.value as LeadBasis)}
              >
                {LEAD_BASES.map((b) => (
                  <option key={b} value={b}>
                    {vocab(t, LEAD_BASIS, b)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label={t('plant.quote.valid_until', { defaultValue: 'Valid until' })}>
            {(id) => (
              <input
                id={id}
                type="date"
                className={fieldClass}
                value={draft.valid_until}
                onChange={(e) => set('valid_until', e.target.value)}
              />
            )}
          </Field>
          <Field label={t('plant.common.document_ref', { defaultValue: 'Document reference' })}>
            {(id) => (
              <input id={id} className={fieldClass} value={draft.document_ref} onChange={(e) => set('document_ref', e.target.value)} />
            )}
          </Field>
          <Field label={t('plant.common.note', { defaultValue: 'Note' })}>
            {(id) => <input id={id} className={fieldClass} value={draft.note} onChange={(e) => set('note', e.target.value)} />}
          </Field>
        </WideModalSection>
        <label className="flex items-start gap-2 text-sm text-content-primary">
          <input
            type="checkbox"
            className="mt-1"
            checked={draft.set_basis}
            onChange={(e) => set('set_basis', e.target.checked)}
          />
          <span>
            {t('plant.quote.set_basis', { defaultValue: 'Plan the dates on this lead time' })}
            <span className="block text-xs text-content-tertiary">
              {t('plant.quote.set_basis_hint', {
                defaultValue: 'The latest order date and the float are counted from the lead time the dates are planned on.',
              })}
            </span>
          </span>
        </label>
      </div>
    </WideModal>
  );
}

/* ── Capacity reservation ─────────────────────────────────────────────── */

function slotDraftOf(slot: Slot): SlotDraft {
  return {
    vendor_name: slot.vendor_name,
    slot_from: slot.slot_from ?? '',
    slot_to: slot.slot_to ?? '',
    reservation_fee: slot.reservation_fee ?? '',
    currency: slot.currency,
    fee_refundable: slot.fee_refundable,
    fee_credited_to_order: slot.fee_credited_to_order,
    convert_by_date: slot.convert_by_date ?? '',
    terms: slot.terms,
    document_ref: slot.document_ref,
  };
}

export function SlotDialog({ open, onClose, projectId, item, slot, onSaved }: ItemDialogBase & { slot: Slot | null }) {
  const { t } = useTranslation();
  const [original] = useState<SlotDraft>(() => (slot ? slotDraftOf(slot) : emptySlotDraft()));
  const [draft, setDraft] = useState<SlotDraft>(original);
  const [tried, setTried] = useState(false);
  const problems = slotProblems(draft);
  const set = <K extends keyof SlotDraft>(key: K, value: SlotDraft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const save = useMutation({
    mutationFn: () =>
      slot
        ? updateSlot(projectId, item.id, slot.id, slotChanges(original, draft))
        : createSlot(projectId, item.id, toSlotInput(draft)),
    onSuccess: onSaved,
  });
  const submit = () => {
    setTried(true);
    if (problems.length === 0) save.mutate();
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="lg"
      testId="plant-slot-dialog"
      title={
        slot
          ? t('plant.slot.edit_title', { defaultValue: 'Edit the production slot' })
          : t('plant.slot.add_title', { defaultValue: 'Reserve a production slot' })
      }
      subtitle={t('plant.slot.subtitle', {
        defaultValue:
          'A supplier holds factory capacity for this item until the order follows. The slot is held once the fee, the refund terms and the date to order by are agreed.',
      })}
      footer={
        <DialogFooter
          problems={problems}
          showProblems={tried}
          busy={save.isPending}
          submitLabel={
            slot ? t('plant.common.save', { defaultValue: 'Save' }) : t('plant.slot.add_submit', { defaultValue: 'Reserve slot' })
          }
          onCancel={onClose}
          onSubmit={submit}
        />
      }
    >
      <div className="space-y-5">
        <Refusal error={save.error} />
        <WideModalSection columns={2}>
          <Field label={t('plant.slot.vendor', { defaultValue: 'Supplier' })} className="sm:col-span-2">
            {(id) => (
              <input id={id} className={fieldClass} value={draft.vendor_name} onChange={(e) => set('vendor_name', e.target.value)} />
            )}
          </Field>
          <Field label={t('plant.slot.from', { defaultValue: 'Production from' })}>
            {(id) => (
              <input id={id} type="date" className={fieldClass} value={draft.slot_from} onChange={(e) => set('slot_from', e.target.value)} />
            )}
          </Field>
          <Field label={t('plant.slot.to', { defaultValue: 'Production until' })}>
            {(id) => (
              <input id={id} type="date" className={fieldClass} value={draft.slot_to} onChange={(e) => set('slot_to', e.target.value)} />
            )}
          </Field>
          <Field label={t('plant.field.reservation_fee', { defaultValue: 'Reservation fee' })}>
            {(id) => (
              <input
                id={id}
                inputMode="decimal"
                className={fieldClass}
                value={draft.reservation_fee}
                onChange={(e) => set('reservation_fee', e.target.value)}
              />
            )}
          </Field>
          <Field label={t('plant.common.currency', { defaultValue: 'Currency' })}>
            {(id) => (
              <input
                id={id}
                maxLength={3}
                placeholder="EUR"
                className={fieldClass}
                value={draft.currency}
                onChange={(e) => set('currency', e.target.value.toUpperCase())}
              />
            )}
          </Field>
          <Field label={t('plant.field.fee_refundable', { defaultValue: 'Refundable' })}>
            {(id) => (
              <select
                id={id}
                className={fieldClass}
                value={draft.fee_refundable}
                onChange={(e) => set('fee_refundable', e.target.value as FeeRefundable | '')}
              >
                <option value="">{t('plant.common.not_set', { defaultValue: 'Not set' })}</option>
                {REFUNDS.map((r) => (
                  <option key={r} value={r}>
                    {vocab(t, FEE_REFUNDABLE, r)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field
            label={t('plant.field.convert_by_date', { defaultValue: 'Convert by' })}
            hint={t('plant.slot.convert_hint', { defaultValue: 'The last day to place the order before the supplier releases the slot.' })}
          >
            {(id) => (
              <input
                id={id}
                type="date"
                className={fieldClass}
                value={draft.convert_by_date}
                onChange={(e) => set('convert_by_date', e.target.value)}
              />
            )}
          </Field>
          <Field label={t('plant.slot.terms', { defaultValue: 'Terms' })} className="sm:col-span-2">
            {(id) => (
              <textarea id={id} rows={2} className={fieldClass} value={draft.terms} onChange={(e) => set('terms', e.target.value)} />
            )}
          </Field>
          <Field label={t('plant.common.document_ref', { defaultValue: 'Document reference' })} className="sm:col-span-2">
            {(id) => (
              <input id={id} className={fieldClass} value={draft.document_ref} onChange={(e) => set('document_ref', e.target.value)} />
            )}
          </Field>
        </WideModalSection>
        <label className="flex items-center gap-2 text-sm text-content-primary">
          <input
            type="checkbox"
            checked={draft.fee_credited_to_order}
            onChange={(e) => set('fee_credited_to_order', e.target.checked)}
          />
          {t('plant.slot.fee_credited', { defaultValue: 'The fee is credited to the order' })}
        </label>
      </div>
    </WideModal>
  );
}

/* ── Procurement route ────────────────────────────────────────────────── */

export function RouteDialog({ open, onClose, projectId, item, catalogue, labels, onSaved }: ItemDialogBase & WithCatalogue) {
  const { t } = useTranslation();
  const [route, setRouteCode] = useState<string>(item.procurement_route ?? '');
  const save = useMutation({
    mutationFn: () => setRoute(projectId, item.id, route as ProcurementRouteCode),
    onSuccess: onSaved,
  });

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="lg"
      testId="plant-route-dialog"
      title={t('plant.route.title', { defaultValue: 'Choose who buys and who installs' })}
      subtitle={t('plant.route.subtitle', {
        defaultValue: 'The route is checked against the contract packages of the project. It cannot change once the item is ordered.',
      })}
      footer={
        <DialogFooter
          problems={[]}
          showProblems={false}
          busy={save.isPending}
          submitLabel={t('plant.route.submit', { defaultValue: 'Set route' })}
          onCancel={onClose}
          onSubmit={() => route && save.mutate()}
        />
      }
    >
      <div className="space-y-4">
        <Refusal error={save.error} />
        <div className="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label={t('plant.field.route', { defaultValue: 'Procurement route' })}>
          {catalogue.procurement_routes.map((r) => (
            <label
              key={r.code}
              className={
                route === r.code
                  ? 'flex cursor-pointer flex-col gap-1 rounded-lg border border-oe-blue bg-oe-blue-subtle p-3 text-sm'
                  : 'flex cursor-pointer flex-col gap-1 rounded-lg border border-border-light p-3 text-sm hover:border-border'
              }
            >
              <span className="flex items-center gap-2 font-medium text-content-primary">
                <input type="radio" name="plant-route" value={r.code} checked={route === r.code} onChange={() => setRouteCode(r.code)} />
                {catalogueName(labels, catalogue, 'procurement_routes', r.code)}
              </span>
              <span className="text-xs text-content-secondary">
                {r.owner_furnished
                  ? t('plant.route.owner_furnished_hint', {
                      defaultValue: 'The owner buys it. It is tracked as an owner-furnished item from here on.',
                    })
                  : t('plant.route.contractor_hint', { defaultValue: 'It is bought inside a contract package.' })}
              </span>
            </label>
          ))}
        </div>
      </div>
    </WideModal>
  );
}

/* ── Delivery limits ──────────────────────────────────────────────────── */

export function LimitsDialog({
  open,
  onClose,
  projectId,
  item,
  catalogue,
  labels,
  limits,
  onSaved,
}: ItemDialogBase & WithCatalogue & { limits: Limit[] }) {
  const { t } = useTranslation();
  const steps = [...catalogue.delivery_limit_steps].sort((a, b) => a.order - b.order);
  const [rows, setRows] = useState<Record<string, { party: string; note: string }>>(() => {
    const out: Record<string, { party: string; note: string }> = {};
    for (const l of limits) out[l.step] = { party: l.party, note: l.note };
    return out;
  });
  // A step a package holds has no party of its own; it is kept as it is.
  const byPackage = new Map(limits.filter((l) => l.contract_package_id).map((l) => [l.step, l]));
  const save = useMutation({
    mutationFn: () =>
      putLimits(
        projectId,
        item.id,
        steps.flatMap((s) => {
          const kept = byPackage.get(s.code);
          const row = rows[s.code];
          if (kept && !row?.party) {
            return [{ step: s.code, party: '', contract_package_id: kept.contract_package_id, note: row?.note ?? kept.note }];
          }
          return row?.party ? [{ step: s.code, party: row.party, note: row.note.trim() }] : [];
        }),
      ),
    onSuccess: onSaved,
  });
  const patch = (step: string, next: Partial<{ party: string; note: string }>) =>
    setRows((r) => ({ ...r, [step]: { party: r[step]?.party ?? '', note: r[step]?.note ?? '', ...next } }));

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="lg"
      testId="plant-limits-dialog"
      title={t('plant.limits.edit_title', { defaultValue: 'Who does what for {{code}}', code: item.code })}
      subtitle={t('plant.limits.edit_subtitle', {
        defaultValue: 'One party per step, from supply to training. A step without a party is a gap somebody will argue about on site.',
      })}
      footer={
        <DialogFooter
          problems={[]}
          showProblems={false}
          busy={save.isPending}
          submitLabel={t('plant.common.save', { defaultValue: 'Save' })}
          onCancel={onClose}
          onSubmit={() => save.mutate()}
        />
      }
    >
      <div className="space-y-4">
        <Refusal error={save.error} />
        <ul className="space-y-2">
          {steps.map((s) => {
            const name = catalogueName(labels, catalogue, 'delivery_limit_steps', s.code);
            return (
              <li key={s.code} className="grid items-center gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.5fr)]" data-testid="limit-step">
                <span className="text-sm text-content-primary">{name}</span>
                <select
                  aria-label={t('plant.limits.party_for', { defaultValue: 'Party for {{step}}', step: name })}
                  className={fieldClass}
                  value={rows[s.code]?.party ?? ''}
                  onChange={(e) => patch(s.code, { party: e.target.value })}
                >
                  <option value="">
                    {byPackage.has(s.code)
                      ? t('plant.limits.by_package', { defaultValue: 'Held by a contract package' })
                      : t('plant.limits.nobody', { defaultValue: 'Nobody yet' })}
                  </option>
                  {catalogue.parties.map((party) => (
                    <option key={party.code} value={party.code}>
                      {catalogueName(labels, catalogue, 'parties', party.code)}
                    </option>
                  ))}
                </select>
                <input
                  aria-label={t('plant.limits.note_for', { defaultValue: 'Note for {{step}}', step: name })}
                  placeholder={t('plant.common.note', { defaultValue: 'Note' })}
                  className={fieldClass}
                  value={rows[s.code]?.note ?? ''}
                  onChange={(e) => patch(s.code, { note: e.target.value })}
                />
              </li>
            );
          })}
        </ul>
      </div>
    </WideModal>
  );
}

/* ── Spare line ───────────────────────────────────────────────────────── */

export function SpareDialog({
  open,
  onClose,
  projectId,
  item,
  catalogue,
  labels,
  spare,
  onSaved,
}: ItemDialogBase & WithCatalogue & { spare: Spare | null }) {
  const { t } = useTranslation();
  const [original] = useState<SpareDraft>(() => ({
    category: spare?.category ?? '',
    description: spare?.description ?? '',
    quantity: spare?.quantity ?? '1',
    unit: spare?.unit ?? '',
    supply_by: spare?.supply_by ?? '',
    handover_target: spare?.handover_target ?? '',
  }));
  const [draft, setDraft] = useState<SpareDraft>(original);
  const [tried, setTried] = useState(false);
  const problems = spareProblems(draft);
  const set = <K extends keyof SpareDraft>(key: K, value: SpareDraft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const save = useMutation({
    mutationFn: () =>
      spare
        ? updateSpare(projectId, item.id, spare.id, spareChanges(original, draft))
        : createSpare(projectId, item.id, toSpareInput(draft)),
    onSuccess: onSaved,
  });
  const submit = () => {
    setTried(true);
    if (problems.length === 0) save.mutate();
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="lg"
      testId="plant-spare-dialog"
      title={
        spare
          ? t('plant.spare.edit_title', { defaultValue: 'Edit the spare' })
          : t('plant.spare.add_title', { defaultValue: 'Add a spare' })
      }
      subtitle={t('plant.spare.subtitle', {
        defaultValue: 'Spare parts, special tools and consumables that have to arrive with the plant and be handed to the operator.',
      })}
      footer={
        <DialogFooter
          problems={problems}
          showProblems={tried}
          busy={save.isPending}
          submitLabel={
            spare ? t('plant.common.save', { defaultValue: 'Save' }) : t('plant.spare.add_submit', { defaultValue: 'Add spare' })
          }
          onCancel={onClose}
          onSubmit={submit}
        />
      }
    >
      <div className="space-y-5">
        <Refusal error={save.error} />
        <WideModalSection columns={2}>
          <Field label={t('plant.spare.category', { defaultValue: 'Kind of spare' })} required>
            {(id) => (
              <select id={id} className={fieldClass} value={draft.category} onChange={(e) => set('category', e.target.value)}>
                <option value="">{t('plant.common.choose', { defaultValue: 'Choose' })}</option>
                {catalogue.spare_categories.map((c) => (
                  <option key={c.code} value={c.code}>
                    {catalogueName(labels, catalogue, 'spare_categories', c.code)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label={t('plant.spare.supply_by', { defaultValue: 'Supplied by' })}>
            {(id) => (
              <select id={id} className={fieldClass} value={draft.supply_by} onChange={(e) => set('supply_by', e.target.value)}>
                <option value="">{t('plant.common.not_set', { defaultValue: 'Not set' })}</option>
                {catalogue.parties.map((party) => (
                  <option key={party.code} value={party.code}>
                    {catalogueName(labels, catalogue, 'parties', party.code)}
                  </option>
                ))}
              </select>
            )}
          </Field>
          <Field label={t('plant.item.description', { defaultValue: 'Description' })} className="sm:col-span-2">
            {(id) => (
              <input id={id} className={fieldClass} value={draft.description} onChange={(e) => set('description', e.target.value)} />
            )}
          </Field>
          <Field label={t('plant.field.quantity', { defaultValue: 'Quantity' })} required>
            {(id) => (
              <input
                id={id}
                inputMode="decimal"
                className={fieldClass}
                value={draft.quantity}
                onChange={(e) => set('quantity', e.target.value)}
              />
            )}
          </Field>
          <Field label={t('plant.item.unit', { defaultValue: 'Unit' })}>
            {(id) => <input id={id} className={fieldClass} value={draft.unit} onChange={(e) => set('unit', e.target.value)} />}
          </Field>
          <Field
            label={t('plant.spare.handover_target', { defaultValue: 'Handed over to' })}
            hint={t('plant.spare.handover_target_hint', { defaultValue: 'The store or the team that receives it.' })}
            className="sm:col-span-2"
          >
            {(id) => (
              <input
                id={id}
                className={fieldClass}
                value={draft.handover_target}
                onChange={(e) => set('handover_target', e.target.value)}
              />
            )}
          </Field>
        </WideModalSection>
      </div>
    </WideModal>
  );
}

/* ── Handover ─────────────────────────────────────────────────────────── */

export function HandoverDialog({ open, onClose, projectId, item, onSaved }: ItemDialogBase) {
  const { t } = useTranslation();
  const [confirm, setConfirm] = useState(false);
  const [reason, setReason] = useState('');
  const [tried, setTried] = useState(false);
  const problems: Problem[] = reason.trim() ? [] : ['no_asset_reason_required'];
  const save = useMutation({
    mutationFn: () => handoverItem(projectId, item.id, confirm, reason.trim()),
    onSuccess: onSaved,
  });
  const submit = () => {
    setTried(true);
    if (problems.length === 0) save.mutate();
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={save.isPending}
      size="md"
      testId="plant-handover-dialog"
      title={t('plant.handover.title', { defaultValue: 'Hand over {{code}} to operation', code: item.code })}
      subtitle={t('plant.handover.subtitle', {
        defaultValue: 'Handover closes the item. Every spare has to be handed over or waived first.',
      })}
      footer={
        <DialogFooter
          problems={problems}
          showProblems={tried}
          busy={save.isPending}
          submitLabel={t('plant.handover.submit', { defaultValue: 'Hand over' })}
          onCancel={onClose}
          onSubmit={submit}
        />
      }
    >
      <div className="space-y-4">
        <Refusal error={save.error} />
        <label className="flex items-start gap-2 text-sm text-content-primary">
          <input
            type="checkbox"
            className="mt-1"
            data-testid="handover-confirm"
            checked={confirm}
            onChange={(e) => setConfirm(e.target.checked)}
          />
          {t('plant.handover.confirm', {
            defaultValue: 'The operator has taken over the plant, its documents and its spares.',
          })}
        </label>
        <Field
          label={t('plant.handover.no_asset_reason', { defaultValue: 'Why it is handed over without a service contract' })}
          hint={t('plant.handover.no_asset_reason_hint', {
            defaultValue: 'A service contract for the asset cannot be named here yet, so the handover records the reason.',
          })}
          required
        >
          {(id) => (
            <textarea
              id={id}
              rows={2}
              className={fieldClass}
              data-testid="handover-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          )}
        </Field>
      </div>
    </WideModal>
  );
}
