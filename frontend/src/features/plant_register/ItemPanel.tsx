// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// One plant item, opened from the register. The top answers the question a
// project lead asks first: when is it needed, when must it be ordered, and
// how much room is left. Below sit the things that answer comes from: the
// lead times with their dates, the route and its decision paper, the
// production slot, who does what on delivery, and the spares.
//
// Every write goes straight to the server and a refusal is shown beside the
// control that caused it, in the server's own words.

import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation } from '@tanstack/react-query';
import { ArrowLeft, Download, Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react';
import clsx from 'clsx';

import { Badge } from '@/shared/ui/Badge';
import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { SkeletonTable } from '@/shared/ui/SkeletonLoader';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { fmtDate, fmtList, fmtNumber } from '@/shared/lib/formatters';
import { formatCurrency } from '@/shared/lib/money';

import {
  deleteSpare,
  downloadExport,
  setBasisQuote,
  submitPaper,
  withdrawPaper,
  syncItem,
  transitionItem,
  transitionSlot,
  transitionSpare,
  type Paper,
  type PlantCatalogue,
  type PlantItem,
  type Slot,
  type Spare,
} from './api';
import { useLimits, usePapers, useQuotes, useSlots, useSpares } from './hooks';
import { ItemDialog } from './ItemDialog';
import { HandoverDialog, LimitsDialog, QuoteDialog, RouteDialog, SlotDialog, SpareDialog } from './ItemDialogs';
import {
  DATE_BASIS,
  FEE_REFUNDABLE,
  ITEM_CLASS,
  ITEM_STATE,
  ITEM_STEP_ACTION,
  LEAD_BASIS,
  ORDER_STATUS,
  PAPER_STATE,
  SLOT_STATE,
  SPARE_STATE,
  SPARE_STEP_ACTION,
  VENDOR_FINDING,
  VENDOR_POLICY,
  VENDOR_REASON,
  catalogueName,
  errorText,
  humanizeCode,
  vocab,
  type LabelContext,
} from './labels';
import { PaperDialog } from './PaperDialog';
import {
  Fact,
  ITEM_STATE_TONE,
  LeadChip,
  PAPER_TONE,
  Refusal,
  SLOT_TONE,
  SPARE_TONE,
  Section,
  ToneBadge,
  WriteButton,
  fieldClass,
  fmtQuantity,
} from './PlantBits';
import { ORDER_TONE, isClosed, isReadFromSource, nextManualStep, nextSpareStep, orderDateOpen, slotIsOpen, spareIsOpen } from './rules';

type Dialog =
  | { kind: 'edit' | 'quote' | 'route' | 'limits' | 'handover' }
  | { kind: 'slot'; slot: Slot | null }
  | { kind: 'paper'; paper: Paper | null }
  | { kind: 'spare'; spare: Spare | null }
  | null;

export interface ItemPanelProps {
  projectId: string;
  item: PlantItem;
  catalogue: PlantCatalogue;
  labels: LabelContext;
  personName: (userId: string | null | undefined) => string | null;
  onBack: () => void;
  onChanged: () => void;
}

export function ItemPanel({ projectId, item, catalogue, labels, personName, onBack, onChanged }: ItemPanelProps) {
  const { t } = useTranslation();
  const [dialog, setDialog] = useState<Dialog>(null);
  const [failed, setFailed] = useState<{ where: string; error: unknown } | null>(null);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const confirmState = useConfirm();
  const { confirm } = confirmState;
  const [waiving, setWaiving] = useState<string | null>(null);
  const [waiverReason, setWaiverReason] = useState('');

  const quotesQ = useQuotes(projectId, item.id);
  const slotsQ = useSlots(projectId, item.id);
  const papersQ = usePapers(projectId, item.id);
  const limitsQ = useLimits(projectId, item.id);
  const sparesQ = useSpares(projectId, item.id);

  // One runner for every button that is a single request, so each failure
  // lands beside the section that asked for it.
  const run = useMutation({
    mutationFn: (job: { where: string; call: () => Promise<unknown> }) => job.call(),
    onMutate: () => setFailed(null),
    onSuccess: () => {
      setWaiving(null);
      setWaiverReason('');
      onChanged();
    },
    onError: (error, job) => setFailed({ where: job.where, error }),
  });
  const busy = (where: string) => run.isPending && run.variables?.where === where;
  const errorAt = (where: string): ReactNode =>
    failed?.where === where ? <Refusal error={failed.error} className="mb-3" /> : null;
  // A section that is still loading or failed to load says so. It must never
  // read as empty: "no slot reserved" is a statement about the project.
  const waiting = (q: { isLoading: boolean; error: unknown }, name: string): ReactNode =>
    q.error ? (
      <Refusal error={q.error} className="mb-3" />
    ) : q.isLoading ? (
      <div data-testid={`${name}-loading`}>
        <SkeletonTable rows={2} columns={3} />
      </div>
    ) : null;
  const saved = () => {
    setDialog(null);
    setFailed(null);
    onChanged();
  };

  const closed = isClosed(item.status);
  const next = nextManualStep(item.status);
  const slot = (slotsQ.data ?? []).find((s) => slotIsOpen(s.status)) ?? (slotsQ.data ?? []).slice(-1)[0] ?? null;
  const paper = (papersQ.data ?? []).slice(-1)[0] ?? null;
  const limits = limitsQ.data ?? [];
  const steps = [...catalogue.delivery_limit_steps].sort((a, b) => a.order - b.order);
  const className = catalogueName(labels, catalogue, 'component_classes', item.component_class_code);
  const dash = t('plant.common.none', { defaultValue: 'Not set' });
  const stepName = (code: string) => catalogueName(labels, catalogue, 'delivery_limit_steps', code);

  return (
    <div className="space-y-4" data-testid="plant-item-panel">
      <ConfirmDialog {...confirmState} />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1.5">
          <Button variant="ghost" size="sm" icon={<ArrowLeft size={14} />} onClick={onBack}>
            {t('plant.item.back', { defaultValue: 'Back to the register' })}
          </Button>
          <h2 className="text-lg font-semibold text-content-primary">
            <span className="font-mono text-content-secondary">{item.code}</span> {item.title}
          </h2>
          <div className="flex flex-wrap items-center gap-2">
            <ToneBadge tone={ITEM_STATE_TONE[item.status]} testId="item-state">
              {vocab(t, ITEM_STATE, item.status)}
            </ToneBadge>
            <span className="text-xs text-content-secondary">{className}</span>
            {item.critical && (
              <Badge variant="error" size="sm">
                {t('plant.field.critical', { defaultValue: 'Critical' })}
              </Badge>
            )}
            {item.long_lead && (
              <Badge variant="warning" size="sm">
                {t('plant.item.long_lead', { defaultValue: 'Long-lead' })}
              </Badge>
            )}
          </div>
        </div>
        {!closed && (
          <div className="flex flex-wrap items-center gap-2">
            <WriteButton variant="ghost" size="sm" icon={<Pencil size={14} />} onClick={() => setDialog({ kind: 'edit' })}>
              {t('plant.common.edit', { defaultValue: 'Edit' })}
            </WriteButton>
            {isReadFromSource(item.status) && (
              <WriteButton
                variant="secondary"
                size="sm"
                icon={<RefreshCw size={14} />}
                loading={busy('state')}
                title={t('plant.item.sync_hint', {
                  defaultValue: 'Ordered, delivered, installed and commissioned are read from the order, the owner-furnished item and commissioning.',
                })}
                onClick={() => run.mutate({ where: 'state', call: () => syncItem(projectId, item.id) })}
              >
                {t('plant.item.sync', { defaultValue: 'Read state from the order' })}
              </WriteButton>
            )}
            {item.status === 'commissioned' && (
              <WriteButton size="sm" onClick={() => setDialog({ kind: 'handover' })} data-testid="item-handover">
                {t('plant.handover.open', { defaultValue: 'Hand over to operation' })}
              </WriteButton>
            )}
            {next && (
              <WriteButton
                size="sm"
                loading={busy('state')}
                data-testid="item-next-step"
                onClick={() => run.mutate({ where: 'state', call: () => transitionItem(projectId, item.id, next) })}
              >
                {vocab(t, ITEM_STEP_ACTION, next)}
              </WriteButton>
            )}
            <WriteButton variant="ghost" size="sm" onClick={() => setConfirmCancel(true)} data-testid="item-cancel">
              {vocab(t, ITEM_STEP_ACTION, 'cancelled')}
            </WriteButton>
          </div>
        )}
      </div>
      {confirmCancel && !closed && (
        <div
          role="alertdialog"
          aria-label={vocab(t, ITEM_STEP_ACTION, 'cancelled')}
          className="flex flex-wrap items-center gap-3 rounded-md border border-semantic-warning/40 bg-semantic-warning-bg p-3 text-sm text-content-primary"
        >
          <span className="min-w-0 flex-1">
            {t('plant.item.cancel_confirm', {
              defaultValue: 'Cancel this item? It stays on record but leaves the dates, the counts and the readiness check. This cannot be undone.',
            })}
          </span>
          <WriteButton
            size="sm"
            variant="danger"
            loading={busy('state')}
            data-testid="item-cancel-confirm"
            onClick={() => {
              setConfirmCancel(false);
              run.mutate({ where: 'state', call: () => transitionItem(projectId, item.id, 'cancelled') });
            }}
          >
            {t('plant.item.cancel_yes', { defaultValue: 'Yes, cancel the item' })}
          </WriteButton>
          <Button size="sm" variant="ghost" onClick={() => setConfirmCancel(false)}>
            {t('plant.item.cancel_no', { defaultValue: 'Keep it' })}
          </Button>
        </div>
      )}
      {errorAt('state')}

      <Section title={t('plant.item.section_when', { defaultValue: 'When to order' })} testId="item-dates">
        <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Fact label={t('plant.field.need_date', { defaultValue: 'Need date' })}>
            {item.need_date ? fmtDate(item.need_date) : dash}
            <span className="block text-xs text-content-tertiary">{vocab(t, DATE_BASIS, item.date_basis)}</span>
          </Fact>
          <Fact label={t('plant.field.latest_order_date', { defaultValue: 'Latest order date' })}>
            {item.latest_order_date ? fmtDate(item.latest_order_date) : dash}
            {orderDateOpen(item) && item.latest_order_date && (
              <span className="mt-1 block">
                <ToneBadge tone={ORDER_TONE[item.order_status]} testId="item-order-status">
                  {vocab(t, ORDER_STATUS, item.order_status)}
                </ToneBadge>
              </span>
            )}
          </Fact>
          <Fact label={t('plant.field.float_days', { defaultValue: 'Float (days)' })}>
            <span className={clsx(item.float_days !== null && item.float_days < 0 && 'font-semibold text-semantic-error')}>
              {item.float_days === null ? dash : fmtNumber(item.float_days, 0)}
            </span>
          </Fact>
          <Fact label={t('plant.field.lead_weeks', { defaultValue: 'Lead time (weeks)' })}>
            <LeadChip item={item} catalogue={catalogue} labels={labels} />
            {item.lead_basis && (
              <span className="block text-xs text-content-tertiary">{vocab(t, LEAD_BASIS, item.lead_basis)}</span>
            )}
          </Fact>
        </dl>
      </Section>

      <Section title={t('plant.item.section_spec', { defaultValue: 'What it must do' })} testId="item-spec">
        <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Fact label={t('plant.field.class', { defaultValue: 'Class' })}>
            {className}
            <span className="block text-xs text-content-tertiary">{vocab(t, ITEM_CLASS, item.item_class)}</span>
          </Fact>
          <Fact label={t('plant.field.quantity', { defaultValue: 'Quantity' })}>{fmtQuantity(item.quantity, item.unit)}</Fact>
          <Fact label={t('plant.field.redundancy', { defaultValue: 'Redundancy' })}>
            {item.redundancy_scheme ? catalogueName(labels, catalogue, 'redundancy_schemes', item.redundancy_scheme) : dash}
            {!item.redundancy_ok && (
              <span className="block text-xs text-semantic-error">
                {t('plant.item.redundancy_short', { defaultValue: 'The quantity is below what this redundancy needs.' })}
              </span>
            )}
          </Fact>
          <Fact label={t('plant.field.vendor_policy', { defaultValue: 'Vendor policy' })}>
            {vocab(t, VENDOR_POLICY, item.vendor_policy)}
            {item.vendor_bound_reason && (
              <span className="block text-xs text-content-tertiary">{vocab(t, VENDOR_REASON, item.vendor_bound_reason)}</span>
            )}
            {item.vendor_findings.map((code) => (
              <span key={code} className="block text-xs text-semantic-error">
                {VENDOR_FINDING[code] ? vocab(t, VENDOR_FINDING, code) : errorText(t, code)}
              </span>
            ))}
          </Fact>
          <Fact label={t('plant.item.maintenance', { defaultValue: 'Maintenance' })}>
            {item.maintenance_strategy
              ? catalogueName(labels, catalogue, 'maintenance_strategies', item.maintenance_strategy)
              : dash}
          </Fact>
          <Fact label={t('plant.item.space', { defaultValue: 'Location' })}>{item.space_ref || dash}</Fact>
          <Fact label={t('plant.item.tag', { defaultValue: 'Tag' })}>{item.tag || dash}</Fact>
          <Fact label={t('plant.item.owner', { defaultValue: 'Responsible person' })}>
            {personName(item.owner_user_id) ?? dash}
          </Fact>
        </dl>
        {item.description && <p className="mt-3 text-sm text-content-secondary">{item.description}</p>}
        {item.performance.length > 0 && (
          <ul className="mt-3 flex flex-wrap gap-2" aria-label={t('plant.field.performance', { defaultValue: 'Performance requirements' })}>
            {item.performance.map((row) => (
              <li key={row.key} className="rounded-md bg-surface-secondary px-2 py-1 text-xs text-content-secondary">
                <span className="text-content-tertiary">{humanizeCode(row.key)}</span>{' '}
                <span className="font-medium text-content-primary">
                  {row.value}
                  {row.unit ? ` ${row.unit}` : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        title={t('plant.quote.section', { defaultValue: 'Lead times' })}
        hint={t('plant.quote.section_hint', {
          defaultValue: 'Every figure with the date it was asked and who answered. The dates above are planned on the one marked.',
        })}
        testId="item-quotes"
        action={
          !closed && (
            <WriteButton size="sm" variant="secondary" icon={<Plus size={14} />} onClick={() => setDialog({ kind: 'quote' })}>
              {t('plant.quote.add', { defaultValue: 'Add lead time' })}
            </WriteButton>
          )
        }
      >
        {errorAt('quotes')}
        {waiting(quotesQ, 'quotes')}
        {quotesQ.data === undefined ? null : quotesQ.data.length === 0 ? (
          <p className="text-sm text-content-tertiary" data-testid="quotes-empty">
            {t('plant.quote.empty', {
              defaultValue: 'No lead time asked yet. Until one is added, the dates rest on the catalogue default, which is not market evidence.',
            })}
          </p>
        ) : (
          <ul className="divide-y divide-border-light">
            {(quotesQ.data ?? []).map((q) => (
              <li key={q.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2 text-sm" data-testid="quote-row">
                <span className="w-24 font-medium text-content-primary">
                  {q.lead_weeks_min === q.lead_weeks_max
                    ? t('plant.item.weeks', { defaultValue: '{{weeks}} wk', weeks: q.lead_weeks_max })
                    : t('plant.quote.weeks_range', {
                        defaultValue: '{{min}} to {{max}} wk',
                        min: q.lead_weeks_min,
                        max: q.lead_weeks_max,
                      })}
                </span>
                <span className="min-w-0 flex-1 text-content-secondary">
                  {q.source_name || catalogueName(labels, catalogue, 'lead_time_sources', q.source)}
                  <span className="block text-xs text-content-tertiary">
                    {t('plant.quote.asked_on', {
                      defaultValue: '{{source}}, asked on {{date}}',
                      source: catalogueName(labels, catalogue, 'lead_time_sources', q.source),
                      date: fmtDate(q.enquiry_date),
                    })}
                  </span>
                </span>
                <span className="text-xs text-content-tertiary">{vocab(t, LEAD_BASIS, q.lead_basis)}</span>
                {q.is_basis ? (
                  <Badge variant="blue" size="sm">
                    {t('plant.quote.is_basis', { defaultValue: 'Dates planned on this' })}
                  </Badge>
                ) : (
                  !closed && (
                    <WriteButton
                      size="sm"
                      variant="ghost"
                      loading={busy('quotes')}
                      onClick={() => run.mutate({ where: 'quotes', call: () => setBasisQuote(projectId, item.id, q.id) })}
                    >
                      {t('plant.quote.use_as_basis', { defaultValue: 'Plan on this' })}
                    </WriteButton>
                  )
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section
        title={t('plant.route.section', { defaultValue: 'Who buys and who installs' })}
        hint={
          item.critical
            ? t('plant.route.section_hint_critical', {
                defaultValue: 'A critical item needs an approved decision paper before its route is confirmed.',
              })
            : undefined
        }
        testId="item-route"
        action={
          !closed && (
            <WriteButton size="sm" variant="secondary" onClick={() => setDialog({ kind: 'route' })} data-testid="item-set-route">
              {item.procurement_route
                ? t('plant.route.change', { defaultValue: 'Change route' })
                : t('plant.route.submit', { defaultValue: 'Set route' })}
            </WriteButton>
          )
        }
      >
        <p className="text-sm text-content-primary" data-testid="item-route-value">
          {item.procurement_route
            ? catalogueName(labels, catalogue, 'procurement_routes', item.procurement_route)
            : t('plant.route.unset', { defaultValue: 'No route yet. Nobody is named to buy this item.' })}
        </p>

        <div className="mt-4 border-t border-border-light pt-3" data-testid="item-paper">
          {errorAt('paper')}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-sm font-medium text-content-primary">
              {t('plant.paper.section', { defaultValue: 'Decision paper' })}
              {paper && (
                <span className="ml-2 inline-block align-middle">
                  <ToneBadge tone={PAPER_TONE[paper.status]} testId="paper-state">
                    {vocab(t, PAPER_STATE, paper.status)}
                  </ToneBadge>
                </span>
              )}
            </h4>
            <div className="flex flex-wrap gap-2">
              {paper && (
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Download size={14} />}
                  onClick={() =>
                    run.mutate({ where: 'paper', call: () => downloadExport(projectId, 'paper', 'pdf', item.id) })
                  }
                >
                  {t('plant.common.pdf', { defaultValue: 'PDF' })}
                </Button>
              )}
              {paper?.status === 'draft' && !closed && (
                <>
                  <WriteButton size="sm" variant="secondary" onClick={() => setDialog({ kind: 'paper', paper })}>
                    {t('plant.common.edit', { defaultValue: 'Edit' })}
                  </WriteButton>
                  <WriteButton
                    size="sm"
                    loading={busy('paper')}
                    data-testid="paper-submit"
                    onClick={() => run.mutate({ where: 'paper', call: () => submitPaper(projectId, item.id, paper.id) })}
                  >
                    {t('plant.paper.submit', { defaultValue: 'Submit for approval' })}
                  </WriteButton>
                </>
              )}
              {paper?.status === 'submitted' && !closed && (
                <WriteButton
                  size="sm"
                  variant="secondary"
                  loading={busy('paper')}
                  data-testid="paper-withdraw"
                  title={t('plant.paper.withdraw_hint', {
                    defaultValue: 'Stops the approval and makes the paper a draft again, so it can be changed.',
                  })}
                  onClick={() => run.mutate({ where: 'paper', call: () => withdrawPaper(projectId, item.id, paper.id) })}
                >
                  {t('plant.paper.withdraw', { defaultValue: 'Take back to draft' })}
                </WriteButton>
              )}
              {papersQ.data !== undefined && (!paper || paper.status === 'rejected') && !closed && (
                <WriteButton size="sm" variant="secondary" icon={<Plus size={14} />} onClick={() => setDialog({ kind: 'paper', paper: null })}>
                  {t('plant.paper.write', { defaultValue: 'Write decision paper' })}
                </WriteButton>
              )}
            </div>
          </div>
          {waiting(papersQ, 'paper')}
          {papersQ.data === undefined ? null : !paper ? (
            <p className="mt-1 text-sm text-content-tertiary" data-testid="paper-empty">
              {t('plant.paper.empty', {
                defaultValue: 'No decision paper. Write one to compare the options and have the choice approved.',
              })}
            </p>
          ) : (
            <div className="mt-2 space-y-2">
              <p className="text-sm text-content-secondary">{paper.question}</p>
              <ul className="space-y-1">
                {paper.options.map((o) => (
                  <li
                    key={o.code}
                    data-testid="paper-option"
                    className={clsx(
                      'flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md px-2 py-1.5 text-sm',
                      o.code === paper.recommendation ? 'bg-oe-blue-subtle' : 'bg-surface-secondary',
                    )}
                  >
                    <span className="min-w-0 flex-1 text-content-primary">{o.title || o.code}</span>
                    {o.lead_weeks !== null && o.lead_weeks !== undefined && (
                      <span className="text-xs text-content-secondary">
                        {t('plant.item.weeks', { defaultValue: '{{weeks}} wk', weeks: o.lead_weeks })}
                      </span>
                    )}
                    {o.cost && <span className="text-xs text-content-secondary">{formatCurrency(o.cost, o.currency)}</span>}
                    {paper.scores[o.code] && (
                      <span className="text-xs text-content-secondary">
                        {t('plant.paper.score', { defaultValue: 'Score {{score}}', score: fmtNumber(paper.scores[o.code], 2) })}
                      </span>
                    )}
                    {o.code === paper.recommendation && (
                      <Badge variant="blue" size="sm">
                        {t('plant.paper.recommended', { defaultValue: 'Recommended' })}
                      </Badge>
                    )}
                  </li>
                ))}
              </ul>
              {paper.rationale && <p className="text-xs text-content-secondary">{paper.rationale}</p>}
            </div>
          )}
        </div>
      </Section>

      <Section
        title={t('plant.slot.section', { defaultValue: 'Production slot' })}
        hint={
          item.needs_slot && slotsQ.data !== undefined && !slot
            ? t('plant.slot.needed_hint', {
                defaultValue: 'With a lead time this long, reserve factory capacity before the order can be placed.',
              })
            : undefined
        }
        testId="item-slot"
        action={
          !closed &&
          slotsQ.data !== undefined &&
          (!slot || !slotIsOpen(slot.status)) && (
            <WriteButton size="sm" variant="secondary" icon={<Plus size={14} />} onClick={() => setDialog({ kind: 'slot', slot: null })}>
              {t('plant.slot.add_submit', { defaultValue: 'Reserve slot' })}
            </WriteButton>
          )
        }
      >
        {errorAt('slot')}
        {waiting(slotsQ, 'slot')}
        {slotsQ.data === undefined ? null : !slot ? (
          <p className="text-sm text-content-tertiary" data-testid="slot-empty">
            {t('plant.slot.empty', { defaultValue: 'No production slot reserved.' })}
          </p>
        ) : (
          <div className="space-y-3">
            <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Fact label={t('plant.slot.vendor', { defaultValue: 'Supplier' })}>
                {slot.vendor_name || dash}
                <span className="mt-1 block">
                  <ToneBadge tone={SLOT_TONE[slot.status]} testId="slot-state">
                    {vocab(t, SLOT_STATE, slot.status)}
                  </ToneBadge>
                </span>
              </Fact>
              <Fact label={t('plant.slot.window', { defaultValue: 'Production window' })}>
                {slot.slot_from && slot.slot_to
                  ? t('plant.common.date_range', {
                      defaultValue: '{{from}} to {{to}}',
                      from: fmtDate(slot.slot_from),
                      to: fmtDate(slot.slot_to),
                    })
                  : slot.slot_from
                    ? fmtDate(slot.slot_from)
                    : dash}
              </Fact>
              <Fact label={t('plant.field.reservation_fee', { defaultValue: 'Reservation fee' })}>
                <span data-testid="slot-fee">
                  {slot.reservation_fee !== null ? formatCurrency(slot.reservation_fee, slot.currency) : dash}
                </span>
                {slot.fee_refundable && (
                  <span className="block text-xs text-content-tertiary">{vocab(t, FEE_REFUNDABLE, slot.fee_refundable)}</span>
                )}
                {slot.fee_credited_to_order && (
                  <span className="block text-xs text-content-tertiary">
                    {t('plant.field.fee_credited', { defaultValue: 'Credited to the order' })}
                  </span>
                )}
              </Fact>
              <Fact label={t('plant.field.convert_by_date', { defaultValue: 'Convert by' })}>
                {slot.convert_by_date ? fmtDate(slot.convert_by_date) : dash}
                {item.slot_after_order_date && (
                  <span className="block text-xs text-semantic-error">
                    {t('plant.slot.after_order_date', { defaultValue: 'This is later than the latest order date.' })}
                  </span>
                )}
              </Fact>
            </dl>
            {slot.terms && <p className="text-xs text-content-secondary">{slot.terms}</p>}
            {slotIsOpen(slot.status) && !closed && (
              <div className="flex flex-wrap gap-2">
                <WriteButton size="sm" variant="ghost" icon={<Pencil size={14} />} onClick={() => setDialog({ kind: 'slot', slot })}>
                  {t('plant.common.edit', { defaultValue: 'Edit' })}
                </WriteButton>
                {slot.status === 'requested' && (
                  <WriteButton
                    size="sm"
                    loading={busy('slot')}
                    data-testid="slot-hold"
                    onClick={() => run.mutate({ where: 'slot', call: () => transitionSlot(projectId, item.id, slot.id, 'held') })}
                  >
                    {t('plant.slot.hold', { defaultValue: 'Confirm the slot is held' })}
                  </WriteButton>
                )}
                {slot.status === 'held' && (
                  <WriteButton
                    size="sm"
                    loading={busy('slot')}
                    onClick={() =>
                      run.mutate({ where: 'slot', call: () => transitionSlot(projectId, item.id, slot.id, 'converted_to_order') })
                    }
                  >
                    {t('plant.slot.convert', { defaultValue: 'Converted to an order' })}
                  </WriteButton>
                )}
                <WriteButton
                  size="sm"
                  variant="ghost"
                  onClick={() => run.mutate({ where: 'slot', call: () => transitionSlot(projectId, item.id, slot.id, 'released') })}
                >
                  {t('plant.slot.release', { defaultValue: 'Release the slot' })}
                </WriteButton>
              </div>
            )}
          </div>
        )}
      </Section>

      <Section
        title={t('plant.limits.section', { defaultValue: 'Who does what on delivery' })}
        hint={
          item.delivery_limit_gaps.length > 0
            ? t('plant.limits.gaps', {
                defaultValue: 'Nobody is named for: {{steps}}',
                steps: fmtList(item.delivery_limit_gaps.map(stepName)),
              })
            : undefined
        }
        testId="item-limits"
        action={
          !closed &&
          limitsQ.data !== undefined && (
            <WriteButton size="sm" variant="secondary" icon={<Pencil size={14} />} onClick={() => setDialog({ kind: 'limits' })}>
              {t('plant.common.edit', { defaultValue: 'Edit' })}
            </WriteButton>
          )
        }
      >
        {waiting(limitsQ, 'limits')}
        <ul className={clsx('grid gap-2 sm:grid-cols-2 lg:grid-cols-5', limitsQ.data === undefined && 'hidden')}>
          {steps.map((s) => {
            const limit = limits.find((l) => l.step === s.code);
            const gap = item.delivery_limit_gaps.includes(s.code);
            return (
              <li
                key={s.code}
                data-testid="limit-cell"
                data-gap={gap || undefined}
                className={clsx(
                  'rounded-md border px-2 py-1.5 text-xs',
                  gap ? 'border-semantic-error/40 bg-semantic-error-bg' : 'border-border-light',
                )}
              >
                <span className="block text-content-tertiary">{stepName(s.code)}</span>
                <span className="font-medium text-content-primary">
                  {limit?.party
                    ? catalogueName(labels, catalogue, 'parties', limit.party)
                    : limit?.contract_package_id
                      ? t('plant.limits.by_package', { defaultValue: 'Held by a contract package' })
                      : t('plant.limits.nobody', { defaultValue: 'Nobody yet' })}
                </span>
              </li>
            );
          })}
        </ul>
      </Section>

      <Section
        title={t('plant.spare.section', { defaultValue: 'Spares' })}
        hint={
          !item.strategic_spares_ok
            ? t('plant.spare.strategic_missing', {
                defaultValue: 'This kind of plant needs strategic spares, or a reason why none are kept.',
              })
            : undefined
        }
        testId="item-spares"
        action={
          !closed && (
            <WriteButton size="sm" variant="secondary" icon={<Plus size={14} />} onClick={() => setDialog({ kind: 'spare', spare: null })}>
              {t('plant.spare.add_submit', { defaultValue: 'Add spare' })}
            </WriteButton>
          )
        }
      >
        {errorAt('spares')}
        {waiting(sparesQ, 'spares')}
        {sparesQ.data === undefined ? null : sparesQ.data.length === 0 ? (
          <p className="text-sm text-content-tertiary" data-testid="spares-empty">
            {t('plant.spare.empty', { defaultValue: 'No spares listed for this item.' })}
          </p>
        ) : (
          <ul className="divide-y divide-border-light">
            {(sparesQ.data ?? []).map((s) => {
              const step = nextSpareStep(s.status);
              return (
                <li key={s.id} className="py-2" data-testid="spare-row">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                    <ToneBadge tone={SPARE_TONE[s.status]}>{vocab(t, SPARE_STATE, s.status)}</ToneBadge>
                    <span className="min-w-0 flex-1 text-content-primary">
                      {s.description || catalogueName(labels, catalogue, 'spare_categories', s.category)}
                      <span className="block text-xs text-content-tertiary">
                        {catalogueName(labels, catalogue, 'spare_categories', s.category)}
                      </span>
                    </span>
                    <span className="text-xs text-content-secondary">{fmtQuantity(s.quantity, s.unit)}</span>
                    {spareIsOpen(s.status) && !closed && waiving !== s.id && (
                      <span className="flex flex-wrap gap-1">
                        {step && (
                          <WriteButton
                            size="sm"
                            variant="secondary"
                            onClick={() =>
                              run.mutate({ where: 'spares', call: () => transitionSpare(projectId, item.id, s.id, step, '') })
                            }
                          >
                            {vocab(t, SPARE_STEP_ACTION, step)}
                          </WriteButton>
                        )}
                        <WriteButton
                          size="sm"
                          variant="ghost"
                          data-testid="spare-waive"
                          onClick={() => {
                            setWaiving(s.id);
                            setWaiverReason('');
                          }}
                        >
                          {vocab(t, SPARE_STEP_ACTION, 'waived')}
                        </WriteButton>
                        {s.status === 'required' && (
                          <>
                            <WriteButton
                              size="sm"
                              variant="ghost"
                              icon={<Pencil size={14} />}
                              aria-label={t('plant.spare.edit_title', { defaultValue: 'Edit the spare' })}
                              onClick={() => setDialog({ kind: 'spare', spare: s })}
                            />
                            <WriteButton
                              size="sm"
                              variant="ghost"
                              icon={<Trash2 size={14} />}
                              aria-label={t('plant.spare.delete', { defaultValue: 'Delete the spare' })}
                              onClick={async () => {
                                if (
                                  await confirm({
                                    title: t('plant.spare.delete_confirm_title', { defaultValue: 'Delete this spare?' }),
                                    message: t('plant.spare.delete_confirm', {
                                      defaultValue: 'The spare is removed from this item. This cannot be undone.',
                                    }),
                                  })
                                ) {
                                  run.mutate({ where: 'spares', call: () => deleteSpare(projectId, item.id, s.id) });
                                }
                              }}
                            />
                          </>
                        )}
                      </span>
                    )}
                  </div>
                  {s.waiver_reason && (
                    <p className="mt-1 text-xs text-content-secondary">
                      {t('plant.spare.waived_because', { defaultValue: 'Waived because: {{reason}}', reason: s.waiver_reason })}
                    </p>
                  )}
                  {waiving === s.id && (
                    <div className="mt-2 space-y-2 rounded-md bg-surface-secondary p-2">
                      <textarea
                        rows={2}
                        data-testid="spare-waiver-reason"
                        className={fieldClass}
                        aria-label={t('plant.spare.waiver_reason', { defaultValue: 'Why this spare is not needed (required)' })}
                        placeholder={t('plant.spare.waiver_reason', { defaultValue: 'Why this spare is not needed (required)' })}
                        value={waiverReason}
                        onChange={(e) => setWaiverReason(e.target.value)}
                      />
                      <div className="flex gap-2">
                        <WriteButton
                          size="sm"
                          loading={busy('spares')}
                          data-testid="spare-waive-send"
                          onClick={() =>
                            run.mutate({
                              where: 'spares',
                              call: () => transitionSpare(projectId, item.id, s.id, 'waived', waiverReason.trim()),
                            })
                          }
                        >
                          {t('plant.spare.waive_send', { defaultValue: 'Waive spare' })}
                        </WriteButton>
                        <Button size="sm" variant="ghost" onClick={() => setWaiving(null)}>
                          {t('plant.common.cancel', { defaultValue: 'Cancel' })}
                        </Button>
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Section>

      {dialog?.kind === 'edit' && (
        <ItemDialog
          open
          onClose={() => setDialog(null)}
          projectId={projectId}
          item={item}
          catalogue={catalogue}
          labels={labels}
          personName={personName}
          onSaved={saved}
        />
      )}
      {dialog?.kind === 'quote' && (
        <QuoteDialog open onClose={() => setDialog(null)} projectId={projectId} item={item} catalogue={catalogue} labels={labels} onSaved={saved} />
      )}
      {dialog?.kind === 'route' && (
        <RouteDialog open onClose={() => setDialog(null)} projectId={projectId} item={item} catalogue={catalogue} labels={labels} onSaved={saved} />
      )}
      {dialog?.kind === 'limits' && (
        <LimitsDialog
          open
          onClose={() => setDialog(null)}
          projectId={projectId}
          item={item}
          catalogue={catalogue}
          labels={labels}
          limits={limits}
          onSaved={saved}
        />
      )}
      {dialog?.kind === 'slot' && (
        <SlotDialog open onClose={() => setDialog(null)} projectId={projectId} item={item} slot={dialog.slot} onSaved={saved} />
      )}
      {dialog?.kind === 'paper' && (
        <PaperDialog open onClose={() => setDialog(null)} projectId={projectId} item={item} paper={dialog.paper} onSaved={saved} />
      )}
      {dialog?.kind === 'spare' && (
        <SpareDialog
          open
          onClose={() => setDialog(null)}
          projectId={projectId}
          item={item}
          catalogue={catalogue}
          labels={labels}
          spare={dialog.spare}
          onSaved={saved}
        />
      )}
      {dialog?.kind === 'handover' && (
        <HandoverDialog open onClose={() => setDialog(null)} projectId={projectId} item={item} onSaved={saved} />
      )}
    </div>
  );
}
