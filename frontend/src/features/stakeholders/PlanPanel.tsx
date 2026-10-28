// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The communication plan: what is due next, the standing plan behind it, and
// the record of what took place. The reader's question on this screen is
// "whom do I owe a word this week", so the due list comes first.

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CalendarClock, Check, Pencil, Plus, Trash2 } from 'lucide-react';
import clsx from 'clsx';

import { Button } from '@/shared/ui/Button';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { EmptyState } from '@/shared/ui/EmptyState';
import { fmtDate, fmtList } from '@/shared/lib/formatters';

import {
  deleteEvent,
  deletePlanItem,
  type DueOccurrence,
  type EngagementEvent,
  type PlanItem,
  type Stakeholder,
} from './api';
import { EventDialog, type EventTarget } from './EventDialog';
import { PlanItemDialog } from './PlanItemDialog';
import { EVENT_TONE, FOCUS_CLASS, GatedButton, PLAN_TONE, SectionHead, ToneBadge, useFocusRow, useWrite } from './StakeholderBits';
import { EVENT_STATUS, PLAN_STATUS, nameOf, vocab, type TFn } from './labels';
import { useGateOptions } from './links';
import { FREQUENCY, PLAN_START, planStartOf, presetOfFrequency } from './rules';
import { namesOf, type Screen } from './screen';

export interface PlanPanelProps {
  screen: Screen;
  items: PlanItem[];
  due: DueOccurrence[];
  events: EngagementEvent[];
  stakeholders: Stakeholder[];
  /** The plan line a link pointed at: marked and scrolled to. */
  focusItemId?: string | null;
}

type Dialog =
  | { kind: 'item'; item: PlanItem | null }
  | { kind: 'event'; target: EventTarget }
  | { kind: 'delete-item'; item: PlanItem }
  | { kind: 'delete-event'; event: EngagementEvent }
  | null;

/** How often a plan item recurs, in words; a rule no preset matches is shown as stored. */
export function frequencyText(
  t: TFn,
  item: Pick<PlanItem, 'frequency' | 'trigger_kind' | 'trigger_ref'>,
  gateName: (code: string) => string = (code) => code,
): string {
  if (item.trigger_kind === 'gate' && item.trigger_ref) {
    return t('stakeholders.ui.start.gate_named', {
      defaultValue: 'Each time {{gate}} is submitted for review',
      gate: gateName(item.trigger_ref),
    });
  }
  if (item.trigger_kind) {
    const start = planStartOf(item);
    return start
      ? vocab(t, PLAN_START, start)
      : t('stakeholders.ui.plan.trigger_event', { defaultValue: 'When a project event happens' });
  }
  const preset = presetOfFrequency(item.frequency);
  return preset ? vocab(t, FREQUENCY, preset) : item.frequency;
}

export function PlanPanel({ screen, items, due, events, stakeholders, focusItemId = null }: PlanPanelProps) {
  const { t } = useTranslation();
  const { projectId, settings, labels, personName, onChanged } = screen;
  const fw = settings.framework;
  const can = settings.can.edit;
  const [dialog, setDialog] = useState<Dialog>(null);
  const focusRef = useFocusRow<HTMLLIElement>(focusItemId, items.some((i) => i.id === focusItemId));
  // Asked for only when a line waits for one named gate.
  const gates = useGateOptions(projectId, items.some((i) => i.trigger_kind === 'gate' && !!i.trigger_ref)).options;
  const gateName = (code: string) => gates.find((g) => g.id === code)?.label ?? code;
  const done = () => {
    setDialog(null);
    onChanged();
  };
  const remove = useWrite((d: NonNullable<Dialog>) => {
    if (d.kind === 'delete-item') return deletePlanItem(projectId, d.item.id);
    if (d.kind === 'delete-event') return deleteEvent(projectId, d.event.id);
    return Promise.resolve();
  }, done);

  const audienceText = (item: PlanItem) =>
    fmtList([
      ...namesOf(t, stakeholders, item.audience_stakeholder_ids),
      ...item.audience_categories.map((c) => nameOf(labels, fw.stakeholder_categories, c)),
    ]);

  const addItem = (
    <GatedButton
      allowed={can}
      capability="edit"
      icon={<Plus size={14} />}
      onClick={() => setDialog({ kind: 'item', item: null })}
      data-testid="plan-item-add"
    >
      {t('stakeholders.ui.plan.add_title', { defaultValue: 'Plan a communication' })}
    </GatedButton>
  );

  const dialogs = (
    <>
      {dialog?.kind === 'item' && (
        <PlanItemDialog screen={screen} item={dialog.item} stakeholders={stakeholders} onClose={() => setDialog(null)} onSaved={done} />
      )}
      {dialog?.kind === 'event' && (
        <EventDialog screen={screen} target={dialog.target} stakeholders={stakeholders} onClose={() => setDialog(null)} onSaved={done} />
      )}
      <ConfirmDialog
        open={dialog?.kind === 'delete-item' || dialog?.kind === 'delete-event'}
        variant="danger"
        loading={remove.busy}
        title={
          dialog?.kind === 'delete-event'
            ? t('stakeholders.ui.event.delete_title', { defaultValue: 'Remove this event?' })
            : t('stakeholders.ui.plan.delete_title', { defaultValue: 'Remove this planned communication?' })
        }
        message={
          remove.refusal?.message ??
          (dialog?.kind === 'delete-event'
            ? t('stakeholders.ui.event.delete_body', {
                defaultValue: 'The event leaves the record. Commitments made at it keep naming it as their source.',
              })
            : t('stakeholders.ui.plan.delete_body', {
                defaultValue: 'The line leaves the plan. Events already recorded for it stay on record.',
              }))
        }
        confirmLabel={t('stakeholders.ui.remove', { defaultValue: 'Remove' })}
        cancelLabel={t('stakeholders.ui.cancel', { defaultValue: 'Cancel' })}
        onCancel={() => {
          remove.clear();
          setDialog(null);
        }}
        onConfirm={() => dialog && remove.run(dialog)}
      />
    </>
  );

  if (items.length === 0 && events.length === 0) {
    return (
      <>
        <EmptyState
          icon={<CalendarClock size={28} />}
          title={t('stakeholders.ui.plan.empty_title', { defaultValue: 'No communication planned yet' })}
          description={t('stakeholders.ui.plan.empty_body', {
            defaultValue: 'Plan who hears what, how often and from whom: a monthly letter to the neighbours, a meeting with the authority before each gate. What falls due then shows up here.',
          })}
          action={addItem}
        />
        {dialogs}
      </>
    );
  }

  const open = due.filter((d) => !d.done);
  const itemOf = (id: string) => items.find((i) => i.id === id) ?? null;

  return (
    <div className="space-y-6" data-testid="plan-panel">
      <section className="space-y-2">
        <SectionHead
          title={t('stakeholders.ui.plan.due_title', { defaultValue: 'Due now and next' })}
          hint={t('stakeholders.ui.plan.due_hint', {
            defaultValue: 'Record each one once it took place. Anything past its date is marked overdue.',
          })}
          action={addItem}
        />
        {open.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border-light p-4 text-sm text-content-secondary" data-testid="due-empty">
            {t('stakeholders.ui.plan.due_empty', { defaultValue: 'Nothing is due in the coming weeks.' })}
          </p>
        ) : (
          <ul className="divide-y divide-border-light rounded-lg border border-border bg-surface-elevated shadow-sm" data-testid="due-list">
            {open.map((d) => {
              const item = itemOf(d.plan_item_id);
              return (
                <li key={`${d.plan_item_id}-${d.date}`} className="flex flex-wrap items-center gap-3 px-3 py-2" data-testid="due-entry" data-overdue={d.overdue}>
                  <span className={clsx('w-28 shrink-0 text-sm tabular-nums', d.overdue ? 'font-medium text-semantic-error' : 'text-content-secondary')}>
                    {fmtDate(d.date)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-content-primary">{d.title}</span>
                    <span className="block text-xs text-content-tertiary">
                      {fmtList([
                        nameOf(labels, fw.channels, d.channel),
                        nameOf(labels, fw.participation_levels, d.participation_level),
                        personName(d.owner_user_id) ?? '',
                      ])}
                    </span>
                  </span>
                  {d.overdue && (
                    <span className="flex items-center gap-1 text-xs font-medium text-semantic-error" data-testid="due-overdue">
                      <AlertTriangle size={12} aria-hidden />
                      {t('stakeholders.ui.overdue', { defaultValue: 'Overdue' })}
                    </span>
                  )}
                  {can && item && (
                    <Button
                      size="sm"
                      variant="secondary"
                      icon={<Check size={13} />}
                      onClick={() => setDialog({ kind: 'event', target: { kind: 'record', item, date: d.date } })}
                      data-testid="due-record"
                    >
                      {t('stakeholders.ui.plan.record', { defaultValue: 'Record' })}
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="space-y-2">
        <SectionHead
          title={t('stakeholders.ui.plan.plan_title', { defaultValue: 'The plan' })}
          hint={t('stakeholders.ui.plan.plan_hint', { defaultValue: 'Every standing line of communication and its audience.' })}
        />
        {items.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border-light p-4 text-sm text-content-secondary">
            {t('stakeholders.ui.plan.plan_empty', { defaultValue: 'The plan has no lines yet.' })}
          </p>
        ) : (
          <ul className="space-y-2" data-testid="plan-list">
            {items.map((item) => (
              <li
                key={item.id}
                ref={item.id === focusItemId ? focusRef : undefined}
                className={clsx('rounded-lg border border-border-light bg-surface-elevated shadow-sm p-3', item.id === focusItemId && FOCUS_CLASS)}
                data-testid="plan-entry"
                data-focused={item.id === focusItemId || undefined}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-content-primary">{item.title}</span>
                  <ToneBadge tone={PLAN_TONE[item.status]}>{vocab(t, PLAN_STATUS, item.status)}</ToneBadge>
                  {item.overdue && <ToneBadge tone="error">{t('stakeholders.ui.overdue', { defaultValue: 'Overdue' })}</ToneBadge>}
                  {can && (
                    <span className="ml-auto flex gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<Pencil size={13} />}
                        aria-label={t('stakeholders.ui.edit', { defaultValue: 'Edit' })}
                        onClick={() => setDialog({ kind: 'item', item })}
                        data-testid="plan-item-edit"
                      />
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<Trash2 size={13} />}
                        aria-label={t('stakeholders.ui.remove', { defaultValue: 'Remove' })}
                        onClick={() => setDialog({ kind: 'delete-item', item })}
                        data-testid="plan-item-delete"
                      />
                    </span>
                  )}
                </div>
                <p className="mt-1 text-xs text-content-secondary">
                  {fmtList([
                    frequencyText(t as TFn, item, gateName),
                    nameOf(labels, fw.channels, item.channel),
                    nameOf(labels, fw.participation_levels, item.participation_level),
                    item.format_code ? nameOf(labels, fw.participation_formats, item.format_code) : '',
                  ])}
                </p>
                <p className="text-xs text-content-secondary">
                  {t('stakeholders.ui.plan.audience_line', {
                    defaultValue: 'Audience: {{audience}}',
                    audience: audienceText(item) || t('stakeholders.ui.plan.audience_body', { defaultValue: 'a governance body' }),
                  })}
                </p>
                {item.key_message && <p className="mt-1 text-sm text-content-primary">{item.key_message}</p>}
                <p className="mt-1 flex flex-wrap gap-x-4 text-xs text-content-tertiary">
                  {item.next_due && (
                    <span>{t('stakeholders.ui.plan.next_due', { defaultValue: 'Next: {{date}}', date: fmtDate(item.next_due) })}</span>
                  )}
                  {personName(item.owner_user_id) && (
                    <span>
                      {t('stakeholders.ui.plan.owner_line', { defaultValue: 'Responsible: {{name}}', name: personName(item.owner_user_id) })}
                    </span>
                  )}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-2">
        <SectionHead
          title={t('stakeholders.ui.event.list_title', { defaultValue: 'What took place' })}
          hint={t('stakeholders.ui.event.list_hint', {
            defaultValue: 'Meetings, letters and hearings held so far, with their outcome and the feedback given.',
          })}
          action={
            can ? (
              <Button
                variant="secondary"
                size="sm"
                icon={<Plus size={13} />}
                onClick={() => setDialog({ kind: 'event', target: { kind: 'new' } })}
                data-testid="event-add"
              >
                {t('stakeholders.ui.event.add_title', { defaultValue: 'Record an event' })}
              </Button>
            ) : undefined
          }
        />
        {events.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border-light p-4 text-sm text-content-secondary" data-testid="events-empty">
            {t('stakeholders.ui.event.list_empty', { defaultValue: 'Nothing is recorded yet.' })}
          </p>
        ) : (
          <ul className="space-y-2" data-testid="event-list">
            {events.map((e) => (
              <li key={e.id} className="rounded-lg border border-border bg-surface-elevated shadow-sm p-3" data-testid="event-entry">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-content-primary">{e.title}</span>
                  <ToneBadge tone={EVENT_TONE[e.status]}>{vocab(t, EVENT_STATUS, e.status)}</ToneBadge>
                  {(e.held_on || e.occurrence_date) && (
                    <span className="text-xs text-content-secondary">{fmtDate((e.held_on || e.occurrence_date) as string)}</span>
                  )}
                  {can && (
                    <span className="ml-auto flex gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<Pencil size={13} />}
                        aria-label={t('stakeholders.ui.edit', { defaultValue: 'Edit' })}
                        onClick={() => setDialog({ kind: 'event', target: { kind: 'edit', event: e } })}
                        data-testid="event-edit"
                      />
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<Trash2 size={13} />}
                        aria-label={t('stakeholders.ui.remove', { defaultValue: 'Remove' })}
                        onClick={() => setDialog({ kind: 'delete-event', event: e })}
                        data-testid="event-delete"
                      />
                    </span>
                  )}
                </div>
                {e.stakeholder_ids.length > 0 && (
                  <p className="mt-1 text-xs text-content-secondary">
                    {t('stakeholders.ui.event.with', { defaultValue: 'With: {{names}}', names: fmtList(namesOf(t, stakeholders, e.stakeholder_ids)) })}
                  </p>
                )}
                {e.outcome && <p className="mt-1 whitespace-pre-line text-sm text-content-primary">{e.outcome}</p>}
                {e.feedback_summary && (
                  <p className="mt-1 text-xs text-content-secondary">
                    {t('stakeholders.ui.event.feedback_line', { defaultValue: 'Reported back: {{text}}', text: e.feedback_summary })}
                  </p>
                )}
                {e.feedback_not_reported && (
                  <p className="mt-1 flex items-center gap-1 text-xs font-medium text-semantic-error" data-testid="feedback-missing">
                    <AlertTriangle size={12} aria-hidden />
                    {e.feedback_due_on
                      ? t('stakeholders.ui.event.feedback_missing_by', {
                          defaultValue: 'The participants were promised feedback by {{date}}, and none is recorded.',
                          date: fmtDate(e.feedback_due_on),
                        })
                      : t('stakeholders.ui.event.feedback_missing', {
                          defaultValue: 'The participants were promised feedback, and none is recorded.',
                        })}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
      {dialogs}
    </div>
  );
}
