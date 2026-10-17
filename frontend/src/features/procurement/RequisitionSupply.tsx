// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// RequisitionSupply - who should supply a requisition line and when it is
// needed (issue #516).
//
// A line may carry a suggested supplier from the Vendor directory. It comes
// from the BOQ when its sources agree; when they disagree the line shows every
// suggestion and carries none until the requester picks one. A suggestion is
// only a hint: the requisition's supplier is still chosen by a person.
//
// A line may also carry its own needed-by date. Left empty, the requisition's
// date applies. Linked to a schedule activity, the date is proposed as the
// activity start minus a buffer; if the activity moves later, the line says so
// and keeps its date. The supplier's delivery dates live on the order and are
// shown beside the need date, never in its place.

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { AlertTriangle } from 'lucide-react';
import { Badge, Button } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { listVendors } from '@/features/supplier-catalogs/api';
import { fmtList } from '@/shared/lib/formatters';
import {
  daysBetween,
  listScheduleActivities,
  type Requisition,
  type RequisitionLine,
  type RequisitionLineIn,
  type RequisitionPOItemRef,
  type RequisitionVendorRef,
} from './requisitionsApi';

const fieldCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const smallFieldCls =
  'h-8 w-full rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/** Active vendors of the directory, the only ones a requisition may name. */
export function useActiveVendors() {
  return useQuery({
    queryKey: ['supplier-catalogs-vendors', 'active'],
    queryFn: () => listVendors({ status: 'active', limit: 200 }),
    staleTime: 60_000,
  });
}

interface VendorSelectProps {
  value: string;
  onChange: (id: string) => void;
  disabled?: boolean;
  /** Name to show for a stored vendor that is no longer active. */
  fallbackName?: string | null;
  id?: string;
  /** Label of the empty choice. */
  emptyLabel?: string;
  size?: 'md' | 'sm';
  ariaLabel?: string;
}

export function VendorSelect({
  value,
  onChange,
  disabled,
  fallbackName,
  id,
  emptyLabel,
  size = 'md',
  ariaLabel,
}: VendorSelectProps) {
  const { t } = useTranslation();
  const { data, isLoading } = useActiveVendors();
  const vendors = data?.items ?? [];
  const known = !value || vendors.some((v) => v.id === value);
  return (
    <select
      id={id}
      aria-label={ariaLabel}
      className={size === 'sm' ? smallFieldCls : fieldCls}
      value={value}
      disabled={disabled || isLoading}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">
        {emptyLabel ?? t('procurement.requisitions.vendor_none', { defaultValue: 'No vendor chosen yet' })}
      </option>
      {!known && <option value={value}>{fallbackName || value}</option>}
      {vendors.map((v) => (
        <option key={v.id} value={v.id}>
          {v.code ? `${v.name} (${v.code})` : v.name}
        </option>
      ))}
    </select>
  );
}

function vendorNames(refs: RequisitionVendorRef[]): string {
  return fmtList(refs.map((r) => r.name || r.id.slice(0, 8)));
}

/**
 * What the lines suggest for the requisition's supplier. With one suggestion
 * and no supplier chosen, the requester may adopt it with one click; with
 * several, the hint only names them. Nothing is applied on its own.
 */
export function SuggestedSupplierHint({
  req,
  vendorId,
  editable,
  onUse,
}: {
  req: Requisition;
  vendorId: string;
  editable: boolean;
  onUse: (id: string) => void;
}) {
  const { t } = useTranslation();
  const suggested = req.suggested_vendors ?? [];
  if (suggested.length === 0) return null;
  if (suggested.length > 1) {
    return (
      <p className="mt-1 flex items-start gap-1 text-xs text-semantic-warning">
        <AlertTriangle size={13} className="mt-0.5 shrink-0" />
        {t('procurement.requisitions.suggested_several', {
          defaultValue: 'The lines suggest different suppliers: {{names}}. Choose one, or split the requisition.',
          names: vendorNames(suggested),
        })}
      </p>
    );
  }
  const only = suggested[0]!;
  if (only.id === vendorId) return null;
  return (
    <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-content-secondary">
      {t('procurement.requisitions.suggested_single', {
        defaultValue: 'Suggested by the lines: {{name}}',
        name: only.name || only.id.slice(0, 8),
      })}
      {editable && only.status === 'active' && (
        <Button size="sm" variant="secondary" onClick={() => onUse(only.id)}>
          {t('procurement.requisitions.use_suggested', { defaultValue: 'Use this supplier' })}
        </Button>
      )}
    </p>
  );
}

/** The supplier's dates of the order lines, shown beside the need date. */
export function SupplierDates({ poItems }: { poItems: RequisitionPOItemRef[] }) {
  const { t } = useTranslation();
  const dated = poItems.filter((p) => p.po_delivery_date || p.supplier_confirmed_delivery_date);
  if (dated.length === 0) return null;
  return (
    <>
      {dated.map((p) => (
        <div key={p.po_item_id} className="text-content-secondary">
          {p.po_delivery_date && (
            <span>
              {t('procurement.requisitions.supplier_expected', { defaultValue: 'Order delivery date' })}:{' '}
              <DateDisplay value={p.po_delivery_date} />
            </span>
          )}
          {p.supplier_confirmed_delivery_date && (
            <span className="ml-2">
              {t('procurement.requisitions.supplier_confirmed', { defaultValue: 'Confirmed by supplier' })}:{' '}
              <DateDisplay value={p.supplier_confirmed_delivery_date} />
            </span>
          )}
        </div>
      ))}
    </>
  );
}

interface LineSupplyCellProps {
  projectId: string;
  line: RequisitionLineIn;
  /** The line as stored, for names, conflicts and the schedule state; absent while unsaved. */
  stored?: RequisitionLine;
  /** The requisition's own needed-by date, the default for a line without one. */
  headerDate: string;
  editable: boolean;
  onChange: (patch: Partial<RequisitionLineIn>) => void;
}

/** Suggested supplier, needed-by date and schedule link of one requisition line. */
export function LineSupplyCell({ projectId, line, stored, headerDate, editable, onChange }: LineSupplyCellProps) {
  const { t } = useTranslation();
  const { data: activityPage } = useQuery({
    queryKey: ['procurement-schedule-activities', projectId],
    queryFn: () => listScheduleActivities(projectId),
    enabled: editable && !!projectId,
    staleTime: 60_000,
  });
  const activities = activityPage?.items;
  const offered = stored?.source_suggested_vendors ?? [];
  const conflict = offered.length > 1;
  const activityId = line.schedule_activity_id ?? '';
  const buffer = line.schedule_buffer_days ?? 0;

  if (!editable) {
    return (
      <div className="space-y-1 text-xs">
        <div>
          <span className="text-content-tertiary">
            {t('procurement.requisitions.suggested_supplier', { defaultValue: 'Suggested supplier' })}:{' '}
          </span>
          {stored?.suggested_vendor_name ?? (
            <span className="text-content-tertiary">
              {t('procurement.requisitions.no_suggestion', { defaultValue: 'No suggestion' })}
            </span>
          )}
          {stored?.suggested_vendor_status && stored.suggested_vendor_status !== 'active' && (
            <span className="ml-1 inline-block">
              <Badge variant="error" size="sm">
                {t('procurement.requisitions.vendor_inactive', { defaultValue: 'Not active in the directory' })}
              </Badge>
            </span>
          )}
        </div>
        {conflict && (
          <p className="text-semantic-warning">
            {t('procurement.requisitions.sources_suggest', {
              defaultValue: 'The BOQ suggests: {{names}}',
              names: vendorNames(offered),
            })}
          </p>
        )}
        <NeedDate stored={stored} />
        <SupplierDates poItems={stored?.po_items ?? []} />
      </div>
    );
  }

  return (
    <div className="min-w-[14rem] space-y-1.5 text-xs">
      <VendorSelect
        size="sm"
        value={line.suggested_vendor_id ?? ''}
        fallbackName={stored?.suggested_vendor_name}
        emptyLabel={t('procurement.requisitions.no_suggestion', { defaultValue: 'No suggestion' })}
        ariaLabel={t('procurement.requisitions.suggested_supplier', { defaultValue: 'Suggested supplier' })}
        onChange={(id) => onChange({ suggested_vendor_id: id || null })}
      />
      {conflict && (
        <p className="flex items-start gap-1 text-semantic-warning">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          {t('procurement.requisitions.sources_suggest', {
            defaultValue: 'The BOQ suggests: {{names}}',
            names: vendorNames(offered),
          })}
        </p>
      )}
      <label className="block text-content-tertiary">
        {t('procurement.requisitions.line_needed_by', { defaultValue: 'Needed by' })}
        <input
          type="date"
          className={`${smallFieldCls} mt-0.5`}
          value={line.required_date ?? ''}
          onChange={(e) => onChange({ required_date: e.target.value || null })}
        />
      </label>
      {!line.required_date && !activityId && (
        <p className="text-content-tertiary">
          {headerDate
            ? t('procurement.requisitions.line_date_default', {
                defaultValue: 'Uses the requisition date, {{date}}',
                date: headerDate,
              })
            : t('procurement.requisitions.line_date_none', { defaultValue: 'No date yet' })}
        </p>
      )}
      <div className="flex items-end gap-1.5">
        <label className="block flex-1 text-content-tertiary">
          {t('procurement.requisitions.line_activity', { defaultValue: 'From schedule activity' })}
          <select
            className={`${smallFieldCls} mt-0.5`}
            value={activityId}
            onChange={(e) =>
              // A new activity proposes a new date: clear the old one and its anchor.
              onChange({
                schedule_activity_id: e.target.value || null,
                schedule_buffer_days: e.target.value ? buffer : null,
                required_date: null,
                schedule_anchor_date: null,
              })
            }
          >
            <option value="">{t('procurement.requisitions.line_activity_none', { defaultValue: 'None' })}</option>
            {activityId && !(activities ?? []).some((a) => a.id === activityId) && (
              <option value={activityId}>{stored?.schedule_activity_name ?? activityId.slice(0, 8)}</option>
            )}
            {(activities ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {`${a.start_date} · ${a.name}`}
              </option>
            ))}
          </select>
          {activityPage && activityPage.total > activityPage.items.length && (
            <span className="mt-0.5 block">
              {t('common.showing_range', {
                defaultValue: 'Showing {{from}}-{{to}} of {{total}}',
                from: 1,
                to: activityPage.items.length,
                total: activityPage.total,
              })}
            </span>
          )}
        </label>
        {activityId && (
          <label className="block w-20 text-content-tertiary">
            {t('procurement.requisitions.line_buffer', { defaultValue: 'Days before' })}
            <input
              type="number"
              min={0}
              max={365}
              className={`${smallFieldCls} mt-0.5 text-right`}
              value={buffer}
              onChange={(e) => {
                const days = Math.max(0, Math.min(365, Number.parseInt(e.target.value || '0', 10) || 0));
                onChange({ schedule_buffer_days: days, required_date: null, schedule_anchor_date: null });
              }}
            />
          </label>
        )}
      </div>
      {activityId && !line.required_date && (
        <p className="text-content-tertiary">
          {t('procurement.requisitions.line_date_proposed_on_save', {
            defaultValue: 'The date is proposed from the activity when you save.',
          })}
        </p>
      )}
      <ScheduleMoved stored={stored} />
      <SupplierDates poItems={stored?.po_items ?? []} />
    </div>
  );
}

function NeedDate({ stored }: { stored?: RequisitionLine }) {
  const { t } = useTranslation();
  if (!stored?.effective_required_date) return null;
  return (
    <div>
      <span className="text-content-tertiary">
        {t('procurement.requisitions.line_needed_by', { defaultValue: 'Needed by' })}:{' '}
      </span>
      <DateDisplay value={stored.effective_required_date} />
      {stored.required_date_source === 'schedule' && stored.schedule_activity_name && (
        <span className="text-content-tertiary">
          {' '}
          {t('procurement.requisitions.line_date_from_activity', {
            defaultValue: '({{days}} days before {{activity}})',
            days: stored.schedule_buffer_days ?? 0,
            activity: stored.schedule_activity_name,
          })}
        </span>
      )}
      {stored.required_date_source === 'requisition' && (
        <span className="text-content-tertiary">
          {' '}
          {t('procurement.requisitions.line_date_inherited', { defaultValue: '(requisition date)' })}
        </span>
      )}
      {stored.latest_order_date && (
        <div className="text-content-tertiary">
          {t('procurement.requisitions.latest_order_date', { defaultValue: 'Order by' })}:{' '}
          <DateDisplay value={stored.latest_order_date} />
        </div>
      )}
      <ScheduleMoved stored={stored} />
    </div>
  );
}

function ScheduleMoved({ stored }: { stored?: RequisitionLine }) {
  const { t } = useTranslation();
  if (!stored?.schedule_moved || !stored.schedule_activity_start) return null;
  const shift = daysBetween(stored.schedule_anchor_date, stored.schedule_activity_start);
  return (
    <p className="flex items-start gap-1 text-semantic-warning">
      <AlertTriangle size={12} className="mt-0.5 shrink-0" />
      {t('procurement.requisitions.schedule_moved', {
        defaultValue: 'The activity now starts {{date}} ({{shift}} days). The date above was not changed.',
        date: stored.schedule_activity_start,
        shift: shift === null ? '?' : shift > 0 ? `+${shift}` : String(shift),
      })}
    </p>
  );
}
