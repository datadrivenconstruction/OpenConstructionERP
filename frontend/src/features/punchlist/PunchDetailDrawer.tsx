// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Punch item detail drawer.
 *
 * A right-side slide-over that surfaces one snag end to end: the full status
 * lifecycle (closure stepper), the photo capture + gallery, the sheet-pin
 * location, and the core fields. Opened from the list rows, the kanban cards,
 * and the pin board.
 *
 * The item is (re)fetched by id so the drawer always reflects the latest state
 * after a transition or a photo change, seeded with whatever the caller already
 * had so the panel paints instantly.
 */

import { useCallback, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Calendar, MapPin, Pencil, RotateCcw, Tag, User } from 'lucide-react';
import clsx from 'clsx';
import { Badge, Button, SideDrawer } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  fetchPunchItem,
  transitionPunchStatus,
  updatePunchItem,
  type PunchItem,
  type PunchPriority,
  type PunchStatus,
} from './api';
import { PunchClosureStepper } from './PunchClosureStepper';
import { PunchPhotoGallery } from './PunchPhotoGallery';
import { AssigneeLabel } from './assignee';
import {
  formatReworkCost,
  parseReworkCostInput,
  projectCurrencyCode,
  reworkCostForInput,
} from './reworkCost';
import { getIntlLocale } from '@/shared/lib/formatters';
import { RaiseBackCharge } from '@/features/cost-recovery/RaiseBackCharge';

const STATUS_VARIANT: Record<PunchStatus, 'error' | 'warning' | 'blue' | 'success' | 'neutral'> = {
  open: 'error',
  assigned: 'blue',
  in_progress: 'warning',
  resolved: 'blue',
  verified: 'success',
  closed: 'neutral',
};

const PRIORITY_VARIANT: Record<PunchPriority, 'neutral' | 'blue' | 'warning' | 'error'> = {
  low: 'neutral',
  medium: 'warning',
  high: 'error',
  critical: 'error',
};

/** Human title-case fallback for an enum-ish token (open_x -> Open X). */
function titleCase(value: string): string {
  return value
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '-';
  try {
    const isDateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
    return new Date(value).toLocaleDateString(getIntlLocale(), {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      ...(isDateOnly ? { timeZone: 'UTC' } : {}),
    });
  } catch {
    return value;
  }
}

function Field({
  icon: Icon,
  label,
  children,
}: {
  icon: React.ElementType;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <div className="mb-0.5 flex items-center gap-1 text-2xs font-semibold uppercase tracking-wider text-content-quaternary">
        <Icon size={12} className="shrink-0" />
        {label}
      </div>
      <div className="truncate text-sm text-content-secondary">{children}</div>
    </div>
  );
}

/**
 * The item's rework cost, and the one place it can be changed after the item
 * exists. Snags raised from a clash, an inspection or an NCR never pass
 * through the add form, so without this they could not be priced at all.
 */
function ReworkCostSection({
  item,
  projectCurrency,
  onSaved,
}: {
  item: PunchItem;
  projectCurrency: string;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [touched, setTouched] = useState(false);

  const shown = formatReworkCost(item);
  // A price recorded in another currency is not carried into the edit box:
  // saving records the amount in the project's currency, and keeping the old
  // number under the new code would restate the money without anyone saying so.
  const currencyChanges =
    item.rework_cost != null && projectCurrencyCode(item.rework_cost_currency) !== projectCurrency;
  const parsed = parseReworkCostInput(draft);
  const invalid = touched && !parsed.ok;

  const saveMut = useMutation({
    mutationFn: (value: string | null) =>
      updatePunchItem(item.id, { rework_cost: value, rework_cost_currency: projectCurrency }),
    onSuccess: () => {
      setEditing(false);
      onSaved();
      addToast({
        type: 'success',
        title: t('punch.rework_cost_saved', { defaultValue: 'Rework cost saved' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  const startEditing = () => {
    setDraft(currencyChanges ? '' : reworkCostForInput(item.rework_cost));
    setTouched(false);
    setEditing(true);
  };

  const save = () => {
    setTouched(true);
    if (parsed.ok) saveMut.mutate(parsed.value);
  };

  return (
    <section data-testid="punch-rework-cost">
      <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
        {t('punch.field_rework_cost', { defaultValue: 'Rework cost' })}
      </h4>
      {editing ? (
        <div className="space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="text"
              inputMode="decimal"
              autoComplete="off"
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              // Enter saves. Escape is the drawer's (a capture listener on
              // document closes it first), so there is no Escape branch here.
              onKeyDown={(e) => {
                if (e.key === 'Enter') save();
              }}
              aria-label={t('punch.field_rework_cost', { defaultValue: 'Rework cost' })}
              aria-invalid={invalid || undefined}
              placeholder="0.00"
              className={clsx(
                'h-9 w-40 rounded-lg border bg-surface-primary px-3 text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-oe-blue/30',
                invalid ? 'border-semantic-error' : 'border-border focus:border-oe-blue',
              )}
            />
            <span className="text-sm text-content-tertiary">{projectCurrency}</span>
            <Button size="sm" variant="primary" onClick={save} loading={saveMut.isPending}>
              {t('common.save', { defaultValue: 'Save' })}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)} disabled={saveMut.isPending}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
          {invalid ? (
            <p className="text-xs text-semantic-error">
              {t('punch.rework_cost_invalid', { defaultValue: 'Enter an amount of zero or more' })}
            </p>
          ) : currencyChanges ? (
            <p className="text-xs text-content-secondary">
              {t('punch.rework_cost_currency_changes', {
                defaultValue:
                  'The current cost is in {{stored}}. Enter the amount in {{currency}}; it replaces the old figure.',
                stored: item.rework_cost_currency,
                currency: projectCurrency,
              })}
            </p>
          ) : (
            <p className="text-xs text-content-secondary">
              {t('punch.rework_cost_hint', {
                defaultValue: 'In {{currency}}. What it will cost to put this right. Leave empty until it is priced.',
                currency: projectCurrency,
              })}
            </p>
          )}
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={clsx(
              'text-sm tabular-nums',
              shown ? 'text-content-secondary' : 'text-content-tertiary',
            )}
          >
            {shown ?? t('punch.rework_cost_unpriced', { defaultValue: 'Not priced' })}
          </span>
          {projectCurrency ? (
            <button
              type="button"
              onClick={startEditing}
              className="inline-flex items-center gap-1 rounded-md text-xs font-medium text-oe-blue hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
            >
              <Pencil size={12} />
              {t('common.edit', { defaultValue: 'Edit' })}
            </button>
          ) : (
            <span className="text-xs text-content-tertiary">
              {t('punch.rework_cost_no_currency', {
                defaultValue: "Set the project's currency before pricing items.",
              })}
            </span>
          )}
        </div>
      )}
    </section>
  );
}

export function PunchDetailDrawer({
  itemId,
  projectId,
  initialItem,
  projectCurrency,
  onClose,
  onOpenPinBoard,
}: {
  itemId: string;
  projectId: string;
  /** Item from the list, used as instant seed data while the fresh copy loads. */
  initialItem?: PunchItem;
  /** The project's ISO currency, '' when the project has none set. */
  projectCurrency: string;
  onClose: () => void;
  /** Jump to the pin board focused on this item's drawing (optional). */
  onOpenPinBoard?: (item: PunchItem) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const { data: item } = useQuery({
    queryKey: ['punchlist', 'item', itemId],
    queryFn: () => fetchPunchItem(itemId),
    initialData: initialItem,
    enabled: Boolean(itemId),
  });

  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['punchlist'] });
    qc.invalidateQueries({ queryKey: ['punchlist', 'item', itemId] });
    qc.invalidateQueries({ queryKey: ['punchlist-summary'] });
  }, [qc, itemId]);

  const transitionMut = useMutation({
    mutationFn: ({ next, notes }: { next: PunchStatus; notes?: string }) =>
      transitionPunchStatus(itemId, next, notes),
    onSuccess: (_data, vars) => {
      refresh();
      addToast({
        type: 'success',
        title: t('punch.status_updated', {
          defaultValue: 'Status updated to {{status}}',
          status: t(`punch.status_${vars.next}`, { defaultValue: titleCase(vars.next) }),
        }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      }),
  });

  if (!item) {
    return (
      <SideDrawer open onClose={onClose} title={t('punch.item_detail', { defaultValue: 'Punch item' })}>
        <div className="p-5 text-sm text-content-tertiary">
          {t('common.loading', { defaultValue: 'Loading...' })}
        </div>
      </SideDrawer>
    );
  }

  const category = item.category;
  const hasPin =
    Boolean(item.document_id) && item.location_x != null && item.location_y != null;
  const history = item.reopen_history ?? [];

  return (
    <SideDrawer
      open
      onClose={onClose}
      busy={transitionMut.isPending}
      widthClass="max-w-2xl"
      title={item.title}
      subtitle={
        <span className="flex items-center gap-1.5">
          <Badge variant={STATUS_VARIANT[item.status]} size="sm">
            {t(`punch.status_${item.status}`, { defaultValue: titleCase(item.status) })}
          </Badge>
          <Badge variant={PRIORITY_VARIANT[item.priority]} size="sm">
            {t(`punch.priority_${item.priority}`, { defaultValue: titleCase(item.priority) })}
          </Badge>
        </span>
      }
    >
      <div className="space-y-6 p-5">
        {/* ── Closure stepper ─────────────────────────────────────────── */}
        <section>
          <PunchClosureStepper
            item={item}
            isPending={transitionMut.isPending}
            onTransition={(next, notes) => transitionMut.mutate({ next, notes })}
          />
        </section>

        {/* ── Core fields ─────────────────────────────────────────────── */}
        <section className="grid grid-cols-2 gap-4">
          <Field icon={Tag} label={t('punch.col_category', { defaultValue: 'Category' })}>
            {category
              ? t(`punch.category_${category}`, { defaultValue: titleCase(category) })
              : '-'}
          </Field>
          <Field icon={User} label={t('punch.field_assigned_to', { defaultValue: 'Assigned To' })}>
            <AssigneeLabel
              raw={item.assigned_to}
              name={item.assigned_to_name}
              variant="plain"
            />
          </Field>
          <Field icon={Calendar} label={t('punch.field_due_date', { defaultValue: 'Due Date' })}>
            {formatDate(item.due_date)}
          </Field>
          <Field icon={Calendar} label={t('punch.created', { defaultValue: 'Created' })}>
            {formatDate(item.created_at)}
          </Field>
        </section>

        {/* ── Rework cost ─────────────────────────────────────────────── */}
        <ReworkCostSection
          key={item.id}
          item={item}
          projectCurrency={projectCurrency}
          onSaved={refresh}
        />
        {item.rework_cost != null && item.rework_cost !== '' && (
          <RaiseBackCharge key={`bc-${item.id}`} projectId={item.project_id} source={{ kind: 'punch_item', id: item.id }} />
        )}

        {/* ── Description ──────────────────────────────────────────────── */}
        {item.description?.trim() && (
          <section>
            <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('punch.field_description', { defaultValue: 'Description' })}
            </h4>
            <p className="whitespace-pre-wrap text-sm text-content-secondary">{item.description}</p>
          </section>
        )}

        {/* ── Resolution notes ────────────────────────────────────────── */}
        {item.resolution_notes?.trim() && (
          <section>
            <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('punch.resolution_notes', { defaultValue: 'Resolution notes' })}
            </h4>
            <p className="whitespace-pre-wrap text-sm text-content-secondary">
              {item.resolution_notes}
            </p>
          </section>
        )}

        {/* ── Sheet pin ───────────────────────────────────────────────── */}
        <section>
          <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
            {t('punch.pin_section', { defaultValue: 'Drawing pin' })}
          </h4>
          {hasPin ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="inline-flex items-center gap-1 text-sm text-content-secondary">
                <MapPin size={14} className="text-oe-blue" />
                {t('punch.pinned_at', {
                  defaultValue: 'Page {{page}}',
                  page: item.page ?? 1,
                })}
              </span>
              {onOpenPinBoard && (
                <button
                  type="button"
                  onClick={() => onOpenPinBoard(item)}
                  className="inline-flex items-center gap-1 rounded-md text-xs font-medium text-oe-blue hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                >
                  <MapPin size={12} />
                  {t('punch.open_pin_board', { defaultValue: 'Open on pin board' })}
                </button>
              )}
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-content-tertiary">
                {t('punch.not_pinned', { defaultValue: 'Not pinned to a drawing yet.' })}
              </span>
              {onOpenPinBoard && (
                <button
                  type="button"
                  onClick={() => onOpenPinBoard(item)}
                  className="inline-flex items-center gap-1 rounded-md text-xs font-medium text-oe-blue hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/40"
                >
                  <MapPin size={12} />
                  {t('punch.pin_on_board', { defaultValue: 'Pin on a drawing' })}
                </button>
              )}
            </div>
          )}
        </section>

        {/* ── Photos ──────────────────────────────────────────────────── */}
        <section>
          <PunchPhotoGallery item={item} projectId={projectId} onChanged={refresh} />
        </section>

        {/* ── Reopen history ──────────────────────────────────────────── */}
        {history.length > 0 && (
          <section>
            <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
              {t('punch.reopen_history', { defaultValue: 'Reopen history' })}
            </h4>
            <ul className="space-y-1.5">
              {history.map((entry, idx) => (
                <li
                  key={`${entry.reopened_at}-${idx}`}
                  className={clsx(
                    'flex items-start gap-2 rounded-md bg-surface-secondary/50 px-2.5 py-1.5 text-xs',
                    'text-content-secondary',
                  )}
                >
                  <RotateCcw size={13} className="mt-0.5 shrink-0 text-content-tertiary" />
                  <span className="min-w-0">
                    {t('punch.reopened_from', {
                      defaultValue: 'Reopened from {{status}} on {{date}}',
                      status: t(`punch.status_${entry.previous_status}`, {
                        defaultValue: titleCase(entry.previous_status),
                      }),
                      date: formatDate(entry.reopened_at),
                    })}
                    {entry.reason ? <span className="text-content-tertiary"> - {entry.reason}</span> : null}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </SideDrawer>
  );
}
