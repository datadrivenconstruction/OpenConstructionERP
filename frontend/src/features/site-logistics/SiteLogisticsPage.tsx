// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import React, { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Truck,
  Plus,
  X,
  Check,
  Ban,
  Trash2,
  Clock,
  Package,
  Calendar,
  DoorOpen,
  MapPin,
  CheckCircle2,
  LogIn,
  Pencil,
  Download,
  Printer,
  AlertTriangle,
  CalendarClock,
  ChevronLeft,
  ChevronRight,
  Table2,
  Search,
  Unlink,
  ClipboardList,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  SkeletonTable,
  RecoveryCard,
  MoneyDisplay,
  QuantityDisplay,
} from '@/shared/ui';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DismissibleInfo } from '@/shared/ui/DismissibleInfo';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { getErrorMessage } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  fetchGates,
  fetchLaydownZones,
  fetchDeliveries,
  fetchSiteLogisticsStats,
  createGate,
  updateGate,
  deleteGate,
  createLaydownZone,
  updateLaydownZone,
  deleteLaydownZone,
  createDelivery,
  updateDelivery,
  deleteDelivery,
  approveDelivery,
  rejectDelivery,
  fetchBillCoverage,
  type Gate,
  type LaydownZone,
  type DeliveryBooking,
  type DeliveryStatus,
  type DeliveryLineInput,
  type BillCoverageRow,
  type CreateDeliveryPayload,
  type UpdateDeliveryPayload,
  type UpdateGatePayload,
  type UpdateLaydownZonePayload,
} from './api';
import { getIntlLocale } from '@/shared/lib/formatters';
import { normalizeRole } from '@/shared/lib/roles';

/* ── Constants & helpers ───────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
}

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const STATUS_ORDER: DeliveryStatus[] = [
  'requested',
  'approved',
  'arrived',
  'completed',
  'rejected',
];

const STATUS_CONFIG: Record<DeliveryStatus, { label: string; cls: string }> = {
  requested: {
    label: 'Requested',
    cls: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  },
  approved: {
    label: 'Approved',
    cls: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  },
  arrived: {
    label: 'Arrived',
    cls: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/30 dark:text-indigo-400',
  },
  completed: {
    label: 'Completed',
    cls: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  },
  rejected: {
    label: 'Rejected',
    cls: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  },
};

/**
 * Delivery times are stored as the wall-clock the user booked (see the backend
 * ``_ensure_aware`` note). Format in UTC so the board shows exactly what was
 * entered, on any viewer's machine.
 */
function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(getIntlLocale(), {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'UTC',
  });
}

function fmtDateHeader(iso: string): string {
  return new Date(iso).toLocaleDateString(getIntlLocale(), {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

function dateKey(iso: string): string {
  return iso.slice(0, 10);
}

function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
    d.getHours(),
  )}:${pad(d.getMinutes())}`;
}

/**
 * Turn a stored ISO timestamp back into the value a ``datetime-local`` input
 * expects (``YYYY-MM-DDTHH:mm``). Delivery times are stored as the wall-clock
 * the user booked and shown in UTC (see {@link fmtTime}), so read the UTC parts
 * here as well, otherwise an editor in another timezone would see the window
 * shifted when they open the edit form.
 */
function isoToInput(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(
    d.getUTCDate(),
  )}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`;
}

/** Minutes since midnight (UTC) for a stored ISO timestamp. */
function isoMinutesUTC(iso: string): number {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return 0;
  return d.getUTCHours() * 60 + d.getUTCMinutes();
}

/** Minutes since midnight for a stored ``HH:mm`` gate time, 0 when unparsable. */
function hhmmToMinutes(hhmm: string): number {
  const m = /^(\d{1,2}):(\d{2})/.exec(hhmm ?? '');
  if (!m) return 0;
  return Number(m[1]) * 60 + Number(m[2]);
}

/** Format minutes since midnight as a padded ``HH:mm`` axis label. */
function fmtHourLabel(totalMin: number): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(Math.floor(totalMin / 60))}:${pad(totalMin % 60)}`;
}

/** Today's calendar date as the ``YYYY-MM-DD`` a ``date`` input expects. */
function todayInput(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Shift a ``YYYY-MM-DD`` date string by whole days, staying in that format. */
function shiftDay(day: string, deltaDays: number): string {
  const base = day ? new Date(`${day}T00:00:00Z`) : new Date();
  if (Number.isNaN(base.getTime())) return day;
  base.setUTCDate(base.getUTCDate() + deltaDays);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${base.getUTCFullYear()}-${pad(base.getUTCMonth() + 1)}-${pad(
    base.getUTCDate(),
  )}`;
}

/** Wrap a value as a quote-escaped CSV cell so commas and quotes stay safe. */
function csvCell(value: string): string {
  return `"${String(value ?? '').replace(/"/g, '""')}"`;
}

/** Escape a value for safe interpolation into the print window's HTML. */
function escHtml(value: string): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/* ── Book / edit delivery modal ────────────────────────────────────────── */

/**
 * One bill position on the booking form.
 *
 * `unit` is carried, never edited: it is the position's own unit, and a
 * delivery measured in a different one could not be added to the bill's
 * quantity at all. `position_id` is null only for a detached line - one whose
 * estimate line was deleted after the booking was made.
 */
interface DeliveryFormLine {
  position_id: string | null;
  ordinal: string;
  description: string;
  quantity: string;
  unit: string;
}

interface DeliveryFormState {
  gate_id: string;
  supplier_name: string;
  contact_name: string;
  contact_phone: string;
  vehicle_type: string;
  materials_desc: string;
  window_start: string;
  window_end: string;
  po_ref: string;
  notes: string;
  lines: DeliveryFormLine[];
}

function defaultForm(): DeliveryFormState {
  const start = new Date();
  start.setHours(start.getHours() + 1, 0, 0, 0);
  const end = new Date(start);
  end.setHours(start.getHours() + 1);
  return {
    gate_id: '',
    supplier_name: '',
    contact_name: '',
    contact_phone: '',
    vehicle_type: '',
    materials_desc: '',
    window_start: toLocalInput(start),
    window_end: toLocalInput(end),
    po_ref: '',
    notes: '',
    lines: [],
  };
}

/** Seed the delivery form from an existing booking for the edit flow. */
function formFromDelivery(d: DeliveryBooking): DeliveryFormState {
  return {
    gate_id: d.gate_id ?? '',
    supplier_name: d.supplier_name ?? '',
    contact_name: d.contact_name ?? '',
    contact_phone: d.contact_phone ?? '',
    vehicle_type: d.vehicle_type ?? '',
    materials_desc: d.materials_desc ?? '',
    window_start: isoToInput(d.window_start),
    window_end: isoToInput(d.window_end),
    po_ref: d.po_ref ?? '',
    notes: d.notes ?? '',
    lines: (d.lines ?? []).map((line) => ({
      position_id: line.boq_position_id,
      ordinal: line.position_ordinal ?? '',
      description: line.description,
      quantity: line.quantity,
      unit: line.unit,
    })),
  };
}

/** Turn the form's lines into the payload the API takes. */
function linePayload(lines: DeliveryFormLine[]): DeliveryLineInput[] {
  // Every line goes, including one the user typed a bad quantity into. The
  // form refuses to submit while such a line exists, so filtering here would
  // only hide a line rather than a mistake.
  // The ordinal goes with it. A linked line takes its ordinal from the bill and
  // this is ignored; a line whose position was deleted has nothing to take it
  // from, and losing it here would stop the line reading as detached.
  return lines.map((line) => ({
    boq_position_id: line.position_id,
    position_ordinal: line.ordinal || null,
    description: line.description,
    quantity: line.quantity,
    unit: line.unit,
  }));
}

/**
 * Pick bill positions to book a delivery against.
 *
 * Reads the same coverage endpoint as the coverage table, so each candidate
 * line shows what is still outstanding on it while you are choosing. That is
 * the point of picking from the bill rather than typing a description: the
 * lorry is delivering a line somebody already priced, and the picker can say
 * how much of it is still to come.
 */
function BillPositionPicker({
  projectId,
  chosen,
  onPick,
  onClose,
}: {
  projectId: string;
  /** Position ids already on the booking, shown as picked. */
  chosen: Set<string>;
  onPick: (row: BillCoverageRow) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');

  React.useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(search.trim()), 250);
    return () => window.clearTimeout(handle);
  }, [search]);

  const { data, isLoading, isError } = useQuery({
    queryKey: ['site-logistics-bill-coverage', projectId, debounced],
    queryFn: () => fetchBillCoverage(projectId, { search: debounced || undefined }),
    enabled: !!projectId,
  });

  const rows = data?.rows ?? [];

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in">
      <div
        className="w-full max-w-3xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[85vh] flex flex-col"
        role="dialog"
        aria-label={t('siteLogistics.pick_from_bill', { defaultValue: 'Pick from the bill' })}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div>
            <h2 className="text-lg font-semibold text-content-primary">
              {t('siteLogistics.pick_from_bill', { defaultValue: 'Pick from the bill' })}
            </h2>
            <p className="text-xs text-content-tertiary">
              {t('siteLogistics.pick_from_bill_hint', {
                defaultValue:
                  'Every line shows what is still outstanding against the estimate.',
              })}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        <div className="px-6 py-3 border-b border-border-light">
          <div className="relative">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary pointer-events-none"
            />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={t('siteLogistics.search_bill_placeholder', {
                defaultValue: 'Search by item number or description',
              })}
              aria-label={t('siteLogistics.search_bill', { defaultValue: 'Search the bill' })}
              className={inputCls + ' pl-9'}
              autoFocus
            />
          </div>
        </div>

        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="p-4">
              <SkeletonTable rows={6} />
            </div>
          ) : isError ? (
            <p className="px-6 py-8 text-center text-sm text-semantic-error">
              {t('siteLogistics.bill_load_failed', {
                defaultValue: 'Could not read the bill for this project',
              })}
            </p>
          ) : rows.length === 0 ? (
            <EmptyState
              icon={<Table2 size={40} />}
              title={t('siteLogistics.no_bill_positions', {
                defaultValue: 'No estimate lines to deliver against',
              })}
              description={t('siteLogistics.no_bill_positions_hint', {
                defaultValue:
                  'This project has no priced bill yet, or nothing matches your search.',
              })}
            />
          ) : (
            <ul className="divide-y divide-border-light">
              {rows.map((row) => {
                const picked = row.position_id ? chosen.has(row.position_id) : false;
                return (
                  <li key={row.position_id}>
                    <button
                      type="button"
                      onClick={() => onPick(row)}
                      disabled={picked}
                      className={clsx(
                        'flex w-full items-center gap-3 px-6 py-2.5 text-left transition-colors',
                        picked
                          ? 'cursor-not-allowed opacity-50'
                          : 'hover:bg-surface-secondary/60',
                      )}
                    >
                      <span className="w-24 shrink-0 font-mono text-xs text-content-tertiary tabular-nums">
                        {row.ordinal || '-'}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-sm text-content-primary">
                        {row.description}
                      </span>
                      <span className="shrink-0 text-right text-xs tabular-nums">
                        <span className="block text-content-secondary">
                          {t('siteLogistics.outstanding_short', { defaultValue: 'Outstanding' })}{' '}
                          <QuantityDisplay
                            value={row.outstanding_quantity}
                            unit={row.unit}
                            className="font-medium text-content-primary"
                          />
                        </span>
                        <span className="block text-content-tertiary">
                          {t('siteLogistics.of_bill_quantity', { defaultValue: 'of' })}{' '}
                          <QuantityDisplay value={row.bill_quantity} unit={row.unit} />
                        </span>
                      </span>
                      {picked ? (
                        <Check size={14} className="shrink-0 text-semantic-success" />
                      ) : (
                        <Plus size={14} className="shrink-0 text-content-tertiary" />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {data && (
          <div className="border-t border-border-light px-6 py-2">
            <TruncationNotice page={{ items: data.rows, total: data.total }} />
          </div>
        )}
      </div>
    </div>
  );
}

function BookDeliveryModal({
  projectId,
  gates,
  initial,
  onClose,
  onSubmit,
  isPending,
  errorMessage,
}: {
  projectId: string;
  gates: Gate[];
  /** When present the modal edits this booking instead of creating a new one. */
  initial?: DeliveryBooking | null;
  onClose: () => void;
  onSubmit: (form: DeliveryFormState) => void;
  isPending: boolean;
  errorMessage?: string | null;
}) {
  const { t } = useTranslation();
  const isEdit = !!initial;
  const [form, setForm] = useState<DeliveryFormState>(() =>
    initial ? formFromDelivery(initial) : defaultForm(),
  );
  const [touched, setTouched] = useState(false);
  const [picking, setPicking] = useState(false);

  const chosenPositions = useMemo(
    () =>
      new Set(
        form.lines
          .map((line) => line.position_id)
          .filter((id): id is string => typeof id === 'string'),
      ),
    [form.lines],
  );

  const addLine = (row: BillCoverageRow) => {
    setForm((prev) => ({
      ...prev,
      lines: [
        ...prev.lines,
        {
          position_id: row.position_id,
          ordinal: row.ordinal,
          description: row.description,
          // Default to what the bill still expects, so the common case of
          // "the rest of this line is arriving" is one click.
          quantity: Number(row.outstanding_quantity) > 0 ? row.outstanding_quantity : '1',
          unit: row.unit,
        },
      ],
    }));
    setPicking(false);
  };

  const setLineQuantity = (index: number, quantity: string) =>
    setForm((prev) => ({
      ...prev,
      lines: prev.lines.map((line, i) => (i === index ? { ...line, quantity } : line)),
    }));

  const removeLine = (index: number) =>
    setForm((prev) => ({ ...prev, lines: prev.lines.filter((_, i) => i !== index) }));
  const title = isEdit
    ? t('siteLogistics.edit_delivery', { defaultValue: 'Edit delivery' })
    : t('siteLogistics.book_delivery', { defaultValue: 'Book delivery' });

  const set = <K extends keyof DeliveryFormState>(key: K, value: DeliveryFormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const supplierError = touched && form.supplier_name.trim().length === 0;
  const windowError =
    touched && !!form.window_start && !!form.window_end && form.window_end <= form.window_start;
  // A line whose quantity is blank, zero or not a number cannot be saved: the
  // API refuses it, and dropping it quietly on the way out would lose a line
  // the user can still see listed on the form. Blocked here, beside the field.
  const badLineIndex = form.lines.findIndex((line) => !(Number(line.quantity) > 0));
  const lineError = touched && badLineIndex >= 0;
  const canSubmit =
    form.supplier_name.trim().length > 0 &&
    !!form.window_start &&
    !!form.window_end &&
    form.window_end > form.window_start &&
    badLineIndex < 0;

  const submit = () => {
    setTouched(true);
    if (canSubmit) onSubmit(form);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in">
      <div
        className="w-full max-w-2xl bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto"
        role="dialog"
        aria-label={title}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">{title}</h2>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        <div className="px-6 py-4 space-y-4">
          {errorMessage && (
            <div
              className="rounded-lg border border-semantic-error/30 bg-semantic-error/5 px-3 py-2 text-sm text-semantic-error"
              role="alert"
            >
              {errorMessage}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('siteLogistics.field_supplier', { defaultValue: 'Supplier' })}{' '}
                <span className="text-semantic-error">*</span>
              </label>
              <input
                value={form.supplier_name}
                onChange={(e) => {
                  set('supplier_name', e.target.value);
                  setTouched(true);
                }}
                placeholder={t('siteLogistics.supplier_placeholder', {
                  defaultValue: 'e.g. Ready-Mix Concrete Ltd',
                })}
                className={clsx(
                  inputCls,
                  supplierError && 'border-semantic-error focus:ring-red-300',
                )}
                autoFocus
              />
              {supplierError && (
                <p className="mt-1 text-xs text-semantic-error">
                  {t('siteLogistics.supplier_required', {
                    defaultValue: 'Supplier is required',
                  })}
                </p>
              )}
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('siteLogistics.field_gate', { defaultValue: 'Gate' })}
              </label>
              <select
                value={form.gate_id}
                onChange={(e) => set('gate_id', e.target.value)}
                className={inputCls}
                aria-label={t('siteLogistics.field_gate', { defaultValue: 'Gate' })}
              >
                <option value="">
                  {t('siteLogistics.gate_unassigned', { defaultValue: 'No gate yet' })}
                </option>
                {gates.map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name} ({g.open_time}-{g.close_time})
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('siteLogistics.field_window_start', { defaultValue: 'Window start' })}{' '}
                <span className="text-semantic-error">*</span>
              </label>
              <input
                type="datetime-local"
                value={form.window_start}
                onChange={(e) => {
                  set('window_start', e.target.value);
                  setTouched(true);
                }}
                className={clsx(inputCls, windowError && 'border-semantic-error')}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('siteLogistics.field_window_end', { defaultValue: 'Window end' })}{' '}
                <span className="text-semantic-error">*</span>
              </label>
              <input
                type="datetime-local"
                value={form.window_end}
                onChange={(e) => {
                  set('window_end', e.target.value);
                  setTouched(true);
                }}
                className={clsx(inputCls, windowError && 'border-semantic-error')}
              />
            </div>
          </div>
          {windowError && (
            <p className="text-xs text-semantic-error">
              {t('siteLogistics.window_order_error', {
                defaultValue: 'The end must be after the start',
              })}
            </p>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('siteLogistics.field_vehicle', { defaultValue: 'Vehicle type' })}
              </label>
              <input
                value={form.vehicle_type}
                onChange={(e) => set('vehicle_type', e.target.value)}
                placeholder={t('siteLogistics.vehicle_placeholder', {
                  defaultValue: 'e.g. 32t tipper, flatbed, mixer',
                })}
                className={inputCls}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('siteLogistics.field_po', { defaultValue: 'PO reference' })}
              </label>
              <input
                value={form.po_ref}
                onChange={(e) => set('po_ref', e.target.value)}
                placeholder={t('siteLogistics.po_placeholder', { defaultValue: 'e.g. PO-1042' })}
                className={inputCls}
              />
            </div>
          </div>

          {/* What the lorry is carrying, said in the bill's own words. The
              free-text "Materials" field below stays for the things no
              estimate line prices - a skip, a welfare unit, a tool delivery. */}
          <div>
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <label className="block text-sm font-medium text-content-primary">
                {t('siteLogistics.field_bill_lines', { defaultValue: 'Bill positions delivered' })}
              </label>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setPicking(true)}
                disabled={!projectId}
              >
                <Table2 size={13} className="mr-1 shrink-0" />
                {t('siteLogistics.add_from_bill', { defaultValue: 'Add from bill' })}
              </Button>
            </div>
            {form.lines.length === 0 ? (
              <p className="rounded-lg border border-dashed border-border px-3 py-3 text-xs text-content-tertiary">
                {t('siteLogistics.no_lines_hint', {
                  defaultValue:
                    'Link this delivery to the estimate lines it delivers, and the board can tell you what is still outstanding on each of them.',
                })}
              </p>
            ) : (
              <ul className="divide-y divide-border-light rounded-lg border border-border">
                {form.lines.map((line, index) => (
                  <li
                    key={`${line.position_id ?? 'detached'}-${index}`}
                    className="flex items-center gap-2 px-3 py-2"
                  >
                    <span className="w-20 shrink-0 font-mono text-2xs text-content-tertiary tabular-nums">
                      {line.ordinal || '-'}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-sm text-content-primary">
                      {line.description}
                      {line.position_id === null && (
                        <span
                          className="ml-1.5 inline-flex items-center gap-0.5 text-2xs text-content-tertiary"
                          title={t('siteLogistics.detached_line_hint', {
                            defaultValue:
                              'The estimate line this was booked against has been deleted. The delivery record stands.',
                          })}
                        >
                          <Unlink size={10} className="shrink-0" />
                          {t('siteLogistics.detached_line', { defaultValue: 'Not in the bill' })}
                        </span>
                      )}
                    </span>
                    <input
                      type="number"
                      min="0"
                      step="any"
                      value={line.quantity}
                      onChange={(e) => setLineQuantity(index, e.target.value)}
                      aria-label={t('siteLogistics.line_quantity', {
                        defaultValue: 'Quantity delivered',
                      })}
                      className={`h-8 w-24 shrink-0 rounded-lg border bg-surface-primary px-2 text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-oe-blue/30 ${
                        touched && !(Number(line.quantity) > 0)
                          ? 'border-semantic-error'
                          : 'border-border'
                      }`}
                    />
                    <span className="w-12 shrink-0 text-2xs text-content-tertiary">
                      {line.unit}
                    </span>
                    <button
                      type="button"
                      onClick={() => removeLine(index)}
                      aria-label={t('siteLogistics.remove_line', { defaultValue: 'Remove line' })}
                      className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-content-tertiary hover:bg-semantic-error/10 hover:text-semantic-error transition-colors"
                    >
                      <X size={13} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {lineError && (
              <p className="mt-1.5 text-xs text-semantic-error">
                {t('siteLogistics.line_quantity_required', {
                  defaultValue:
                    'Every linked line needs a quantity greater than zero. Remove the line if none of it is arriving on this delivery.',
                })}
              </p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('siteLogistics.field_materials', { defaultValue: 'Materials' })}
            </label>
            <input
              value={form.materials_desc}
              onChange={(e) => set('materials_desc', e.target.value)}
              placeholder={t('siteLogistics.materials_placeholder', {
                defaultValue: 'e.g. 12 m3 C30/37, rebar cages',
              })}
              className={inputCls}
            />
            <p className="mt-1 text-2xs text-content-tertiary">
              {t('siteLogistics.materials_hint', {
                defaultValue:
                  'Anything the estimate does not price - a skip, a welfare unit, plant on hire.',
              })}
            </p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('siteLogistics.field_contact_name', { defaultValue: 'Contact name' })}
              </label>
              <input
                value={form.contact_name}
                onChange={(e) => set('contact_name', e.target.value)}
                className={inputCls}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-content-primary mb-1.5">
                {t('siteLogistics.field_contact_phone', { defaultValue: 'Contact phone' })}
              </label>
              <input
                value={form.contact_phone}
                onChange={(e) => set('contact_phone', e.target.value)}
                className={inputCls}
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-content-primary mb-1.5">
              {t('siteLogistics.field_notes', { defaultValue: 'Notes' })}
            </label>
            <textarea
              value={form.notes}
              onChange={(e) => set('notes', e.target.value)}
              rows={2}
              className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none"
              placeholder={t('siteLogistics.notes_placeholder', {
                defaultValue: 'Access, offloading, escort...',
              })}
            />
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={submit} disabled={isPending || !canSubmit}>
            {isPending ? (
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent mr-2 shrink-0" />
            ) : isEdit ? (
              <Check size={16} className="mr-1.5 shrink-0" />
            ) : (
              <Truck size={16} className="mr-1.5 shrink-0" />
            )}
            <span>
              {isEdit
                ? t('siteLogistics.save_changes', { defaultValue: 'Save changes' })
                : t('siteLogistics.book_delivery', { defaultValue: 'Book delivery' })}
            </span>
          </Button>
        </div>
      </div>

      {picking && projectId && (
        <BillPositionPicker
          projectId={projectId}
          chosen={chosenPositions}
          onPick={addLine}
          onClose={() => setPicking(false)}
        />
      )}
    </div>
  );
}

/* ── Delivery row ──────────────────────────────────────────────────────── */

function DeliveryRow({
  delivery,
  gate,
  canApprove,
  canEdit,
  canDelete,
  busy,
  onApprove,
  onReject,
  onAdvance,
  onEdit,
  onDelete,
}: {
  delivery: DeliveryBooking;
  gate: Gate | undefined;
  canApprove: boolean;
  canEdit: boolean;
  canDelete: boolean;
  busy: boolean;
  onApprove: (d: DeliveryBooking) => void;
  onReject: (d: DeliveryBooking) => void;
  onAdvance: (d: DeliveryBooking, status: DeliveryStatus) => void;
  onEdit: (d: DeliveryBooking) => void;
  onDelete: (d: DeliveryBooking) => void;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const cfg = STATUS_CONFIG[delivery.status] ?? STATUS_CONFIG.requested;
  const lines = delivery.lines ?? [];

  return (
    <div className="flex flex-wrap items-center gap-3 px-4 py-3 border-b border-border-light last:border-b-0 hover:bg-surface-secondary/40 transition-colors">
      {/* Time window */}
      <div className="flex items-center gap-1.5 w-32 shrink-0 font-mono text-sm text-content-secondary tabular-nums">
        <Clock size={13} className="text-content-tertiary shrink-0" />
        {fmtTime(delivery.window_start)}-{fmtTime(delivery.window_end)}
      </div>

      {/* Supplier, the bill lines it carries, and anything the bill does not price */}
      <div className="flex-1 min-w-[8rem]">
        <p className="text-sm font-medium text-content-primary truncate">
          {delivery.supplier_name}
        </p>
        {lines.length > 0 && (
          <div className="mt-0.5 flex flex-wrap items-center gap-1">
            {lines.map((line) => {
              const label = `${line.position_ordinal || line.description} · ${line.quantity} ${line.unit}`.trim();
              if (!line.boq_position_id) {
                return (
                  <span
                    key={line.id}
                    className="inline-flex items-center gap-0.5 rounded border border-border px-1 py-0.5 text-[9px] font-semibold text-content-tertiary"
                    title={t('siteLogistics.detached_line_hint', {
                      defaultValue:
                        'The estimate line this was booked against has been deleted. The delivery record stands.',
                    })}
                  >
                    <Unlink size={9} className="shrink-0" />
                    {label}
                  </span>
                );
              }
              return (
                <button
                  key={line.id}
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    navigate(`/boq?positionId=${encodeURIComponent(line.boq_position_id!)}`);
                  }}
                  title={t('siteLogistics.view_line_in_boq', {
                    defaultValue: 'Open {{description}} in the bill',
                    description: line.description,
                  })}
                  className="inline-flex items-center gap-0.5 rounded border border-oe-blue/30 bg-oe-blue-subtle px-1 py-0.5 text-[9px] font-semibold text-oe-blue-text hover:bg-oe-blue/10 transition-colors"
                >
                  <Table2 size={9} className="shrink-0" />
                  {label}
                </button>
              );
            })}
          </div>
        )}
        {delivery.materials_desc && (
          <p className="text-2xs text-content-tertiary truncate">{delivery.materials_desc}</p>
        )}
      </div>

      {/* Gate */}
      <div className="hidden md:flex items-center gap-1 w-28 shrink-0 text-xs text-content-tertiary truncate">
        {gate ? (
          <>
            <DoorOpen size={12} className="shrink-0" />
            {gate.name}
          </>
        ) : (
          <span className="italic">{t('siteLogistics.gate_none', { defaultValue: 'No gate' })}</span>
        )}
      </div>

      {/* Vehicle */}
      <div className="hidden lg:block w-28 shrink-0 text-xs text-content-tertiary truncate">
        {delivery.vehicle_type || '-'}
      </div>

      {/* Status chip */}
      <Badge variant="neutral" size="sm" className={cfg.cls}>
        {t(`siteLogistics.status_${delivery.status}`, { defaultValue: cfg.label })}
      </Badge>

      {/* Actions */}
      <div className="flex items-center gap-1.5 shrink-0">
        {canApprove && (delivery.status === 'requested' || delivery.status === 'rejected') && (
          <Button variant="primary" size="sm" disabled={busy} onClick={() => onApprove(delivery)}>
            <Check size={13} className="mr-1" />
            {t('siteLogistics.action_approve', { defaultValue: 'Approve' })}
          </Button>
        )}
        {canApprove && (delivery.status === 'requested' || delivery.status === 'approved') && (
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => onReject(delivery)}>
            <Ban size={13} className="mr-1" />
            {t('siteLogistics.action_reject', { defaultValue: 'Reject' })}
          </Button>
        )}
        {canEdit && delivery.status === 'approved' && (
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => onAdvance(delivery, 'arrived')}
            title={t('siteLogistics.action_mark_arrived', { defaultValue: 'Mark arrived' })}
          >
            <LogIn size={13} className="mr-1" />
            {t('siteLogistics.action_mark_arrived', { defaultValue: 'Mark arrived' })}
          </Button>
        )}
        {canEdit && delivery.status === 'arrived' && (
          <Button
            variant="ghost"
            size="sm"
            disabled={busy}
            onClick={() => onAdvance(delivery, 'completed')}
            title={t('siteLogistics.action_mark_completed', { defaultValue: 'Mark completed' })}
          >
            <CheckCircle2 size={13} className="mr-1" />
            {t('siteLogistics.action_mark_completed', { defaultValue: 'Mark completed' })}
          </Button>
        )}
        {canEdit && (
          <button
            onClick={() => onEdit(delivery)}
            disabled={busy}
            aria-label={t('siteLogistics.action_edit', { defaultValue: 'Edit delivery' })}
            title={t('siteLogistics.action_edit', { defaultValue: 'Edit delivery' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors disabled:opacity-40"
          >
            <Pencil size={14} />
          </button>
        )}
        {canDelete && (
          <button
            onClick={() => onDelete(delivery)}
            disabled={busy}
            aria-label={t('common.delete', { defaultValue: 'Delete' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-semantic-error/10 hover:text-semantic-error transition-colors disabled:opacity-40"
          >
            <Trash2 size={14} />
          </button>
        )}
      </div>
    </div>
  );
}

/* ── Delivery board ────────────────────────────────────────────────────── */

function DeliveryBoard({
  projectId,
  gates,
  onBook,
  onEdit,
}: {
  projectId: string;
  gates: Gate[];
  onBook: () => void;
  onEdit: (d: DeliveryBooking) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const role = normalizeRole(useAuthStore((s) => s.userRole));
  const canApprove = role === 'manager' || role === 'admin';
  const canEdit = role === 'editor' || role === 'manager' || role === 'admin';
  const canDelete = role === 'manager' || role === 'admin';

  const [day, setDay] = useState('');
  const [gateFilter, setGateFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState<DeliveryStatus | ''>('');

  const gateById = useMemo(() => {
    const m = new Map<string, Gate>();
    for (const g of gates) m.set(g.id, g);
    return m;
  }, [gates]);

  const {
    data: deliveries = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ['site-logistics-deliveries', projectId, day, gateFilter, statusFilter],
    queryFn: () =>
      fetchDeliveries(projectId, {
        day: day || undefined,
        gate_id: gateFilter || undefined,
        status: statusFilter || undefined,
      }),
    enabled: !!projectId,
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['site-logistics-deliveries'] });
    qc.invalidateQueries({ queryKey: ['site-logistics-stats'] });
  };

  const decisionMut = useMutation({
    mutationFn: ({ action, id }: { action: 'approve' | 'reject'; id: string }) =>
      action === 'approve' ? approveDelivery(id) : rejectDelivery(id),
    onSuccess: (_data, vars) => {
      invalidate();
      addToast({
        type: 'success',
        title:
          vars.action === 'approve'
            ? t('siteLogistics.approved', { defaultValue: 'Delivery approved' })
            : t('siteLogistics.rejected', { defaultValue: 'Delivery rejected' }),
      });
    },
    onError: (e: unknown) => {
      addToast({
        type: 'error',
        title: t('siteLogistics.decision_failed', { defaultValue: 'Could not update delivery' }),
        message: getErrorMessage(e),
      });
    },
  });

  const advanceMut = useMutation({
    mutationFn: ({ id, status }: { id: string; status: DeliveryStatus }) =>
      updateDelivery(id, { status }),
    onSuccess: () => {
      invalidate();
    },
    onError: (e: unknown) => {
      addToast({
        type: 'error',
        title: t('siteLogistics.decision_failed', { defaultValue: 'Could not update delivery' }),
        message: getErrorMessage(e),
      });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteDelivery(id),
    onSuccess: () => {
      invalidate();
      addToast({ type: 'success', title: t('siteLogistics.deleted', { defaultValue: 'Delivery removed' }) });
    },
    onError: (e: unknown) => {
      addToast({
        type: 'error',
        title: t('siteLogistics.delete_failed', { defaultValue: 'Could not remove delivery' }),
        message: getErrorMessage(e),
      });
    },
  });

  const busy = decisionMut.isPending || advanceMut.isPending || deleteMut.isPending;

  // Group deliveries by calendar day (they arrive chronologically from the API).
  const grouped = useMemo(() => {
    const groups = new Map<string, DeliveryBooking[]>();
    for (const d of deliveries) {
      const key = dateKey(d.window_start);
      const bucket = groups.get(key);
      if (bucket) bucket.push(d);
      else groups.set(key, [d]);
    }
    return Array.from(groups.entries());
  }, [deliveries]);

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <Calendar
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary pointer-events-none"
          />
          <input
            type="date"
            value={day}
            onChange={(e) => setDay(e.target.value)}
            className={inputCls + ' pl-9 w-auto'}
            aria-label={t('siteLogistics.filter_day', { defaultValue: 'Filter by day' })}
          />
        </div>
        {day && (
          <Button variant="ghost" size="sm" onClick={() => setDay('')}>
            {t('siteLogistics.clear_day', { defaultValue: 'All days' })}
          </Button>
        )}
        {gates.length > 0 && (
          <select
            value={gateFilter}
            onChange={(e) => setGateFilter(e.target.value)}
            className={inputCls + ' w-auto'}
            aria-label={t('siteLogistics.filter_gate', { defaultValue: 'Filter by gate' })}
          >
            <option value="">{t('siteLogistics.all_gates', { defaultValue: 'All gates' })}</option>
            {gates.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        )}
        <div className="flex items-center gap-1 overflow-x-auto">
          <button
            onClick={() => setStatusFilter('')}
            className={clsx(
              'rounded-lg px-2.5 py-1.5 text-xs font-medium whitespace-nowrap transition-colors',
              statusFilter === ''
                ? 'bg-oe-blue-subtle text-oe-blue-text'
                : 'text-content-secondary hover:bg-surface-secondary',
            )}
          >
            {t('siteLogistics.status_all', { defaultValue: 'All' })}
          </button>
          {STATUS_ORDER.map((s) => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={clsx(
                'rounded-lg px-2.5 py-1.5 text-xs font-medium whitespace-nowrap transition-colors',
                statusFilter === s
                  ? 'bg-oe-blue-subtle text-oe-blue-text'
                  : 'text-content-secondary hover:bg-surface-secondary',
              )}
            >
              {t(`siteLogistics.status_${s}`, { defaultValue: STATUS_CONFIG[s].label })}
            </button>
          ))}
        </div>
      </div>

      {/* Board */}
      {isLoading ? (
        <SkeletonTable rows={5} columns={4} />
      ) : isError ? (
        <RecoveryCard error={error} onRetry={() => refetch()} />
      ) : deliveries.length === 0 ? (
        <EmptyState
          icon={<Truck size={28} strokeWidth={1.5} />}
          title={
            day || gateFilter || statusFilter
              ? t('siteLogistics.no_matching_deliveries', { defaultValue: 'No matching deliveries' })
              : t('siteLogistics.no_deliveries', { defaultValue: 'No deliveries booked yet' })
          }
          description={
            day || gateFilter || statusFilter
              ? t('siteLogistics.no_matching_hint', {
                  defaultValue: 'Try clearing the day, gate or status filters.',
                })
              : t('siteLogistics.no_deliveries_hint', {
                  defaultValue:
                    'Book your first delivery to start planning what arrives on site and when.',
                })
          }
          action={
            !day && !gateFilter && !statusFilter
              ? {
                  label: t('siteLogistics.book_delivery', { defaultValue: 'Book delivery' }),
                  onClick: onBook,
                }
              : undefined
          }
        />
      ) : (
        <div className="space-y-5">
          {grouped.map(([key, items]) => (
            <div key={key}>
              <div className="flex items-center gap-2 mb-2">
                <Calendar size={14} className="text-content-tertiary" />
                <h3 className="text-sm font-semibold text-content-secondary">
                  {fmtDateHeader(items[0]!.window_start)}
                </h3>
                <span className="text-2xs text-content-tertiary tabular-nums">
                  {t('siteLogistics.delivery_count', {
                    defaultValue: '{{count}} deliveries',
                    count: items.length,
                  })}
                </span>
              </div>
              <Card padding="none" className="overflow-hidden">
                {items.map((d) => (
                  <DeliveryRow
                    key={d.id}
                    delivery={d}
                    gate={d.gate_id ? gateById.get(d.gate_id) : undefined}
                    canApprove={canApprove}
                    canEdit={canEdit}
                    canDelete={canDelete}
                    busy={busy}
                    onApprove={(x) => decisionMut.mutate({ action: 'approve', id: x.id })}
                    onReject={(x) => decisionMut.mutate({ action: 'reject', id: x.id })}
                    onAdvance={(x, status) => advanceMut.mutate({ id: x.id, status })}
                    onEdit={onEdit}
                    onDelete={(x) => deleteMut.mutate(x.id)}
                  />
                ))}
              </Card>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Gates panel ───────────────────────────────────────────────────────── */

function GatesPanel({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const role = normalizeRole(useAuthStore((s) => s.userRole));
  const canEdit = role === 'editor' || role === 'manager' || role === 'admin';
  const canDelete = role === 'manager' || role === 'admin';

  const [name, setName] = useState('');
  const [openTime, setOpenTime] = useState('07:00');
  const [closeTime, setCloseTime] = useState('18:00');
  const [capacity, setCapacity] = useState(1);

  const { data: gates = [], isLoading } = useQuery({
    queryKey: ['site-logistics-gates', projectId],
    queryFn: () => fetchGates(projectId),
    enabled: !!projectId,
  });

  const createMut = useMutation({
    mutationFn: () =>
      createGate({
        project_id: projectId,
        name: name.trim(),
        open_time: openTime,
        close_time: closeTime,
        capacity_per_slot: capacity,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['site-logistics-gates'] });
      qc.invalidateQueries({ queryKey: ['site-logistics-stats'] });
      setName('');
      addToast({ type: 'success', title: t('siteLogistics.gate_added', { defaultValue: 'Gate added' }) });
    },
    onError: (e: unknown) => {
      addToast({
        type: 'error',
        title: t('siteLogistics.gate_add_failed', { defaultValue: 'Could not add gate' }),
        message: getErrorMessage(e),
      });
    },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateGatePayload }) => updateGate(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['site-logistics-gates'] });
      qc.invalidateQueries({ queryKey: ['site-logistics-stats'] });
      addToast({ type: 'success', title: t('siteLogistics.gate_updated', { defaultValue: 'Gate updated' }) });
    },
    onError: (e: unknown) => {
      addToast({
        type: 'error',
        title: t('siteLogistics.gate_update_failed', { defaultValue: 'Could not update gate' }),
        message: getErrorMessage(e),
      });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteGate(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['site-logistics-gates'] });
      qc.invalidateQueries({ queryKey: ['site-logistics-stats'] });
    },
    onError: (e: unknown) => {
      addToast({
        type: 'error',
        title: t('siteLogistics.gate_delete_failed', { defaultValue: 'Could not delete gate' }),
        message: getErrorMessage(e),
      });
    },
  });

  return (
    <div className="space-y-4">
      {canEdit && (
        <Card padding="none" className="p-4">
          <p className="text-sm font-medium text-content-primary mb-3">
            {t('siteLogistics.add_gate', { defaultValue: 'Add a gate' })}
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('siteLogistics.gate_name_placeholder', { defaultValue: 'Gate name' })}
              className={inputCls + ' col-span-2 sm:col-span-1'}
              aria-label={t('siteLogistics.gate_name', { defaultValue: 'Gate name' })}
            />
            <label className="flex items-center gap-1.5 text-xs text-content-tertiary">
              <span className="shrink-0">{t('siteLogistics.open', { defaultValue: 'Open' })}</span>
              <input
                type="time"
                value={openTime}
                onChange={(e) => setOpenTime(e.target.value)}
                className={inputCls}
              />
            </label>
            <label className="flex items-center gap-1.5 text-xs text-content-tertiary">
              <span className="shrink-0">{t('siteLogistics.close', { defaultValue: 'Close' })}</span>
              <input
                type="time"
                value={closeTime}
                onChange={(e) => setCloseTime(e.target.value)}
                className={inputCls}
              />
            </label>
            <label className="flex items-center gap-1.5 text-xs text-content-tertiary">
              <span className="shrink-0">{t('siteLogistics.slots', { defaultValue: 'Slots' })}</span>
              <input
                type="number"
                min={1}
                max={100}
                value={capacity}
                onChange={(e) => setCapacity(Math.max(1, Number(e.target.value) || 1))}
                className={inputCls}
              />
            </label>
          </div>
          <div className="mt-3 flex justify-end">
            <Button
              variant="primary"
              size="sm"
              disabled={name.trim().length === 0 || closeTime <= openTime || createMut.isPending}
              onClick={() => createMut.mutate()}
            >
              <Plus size={14} className="mr-1" />
              {t('siteLogistics.add_gate', { defaultValue: 'Add a gate' })}
            </Button>
          </div>
          {closeTime <= openTime && (
            <p className="mt-2 text-xs text-semantic-error">
              {t('siteLogistics.gate_hours_error', {
                defaultValue: 'Closing time must be after opening time',
              })}
            </p>
          )}
        </Card>
      )}

      {isLoading ? (
        <SkeletonTable rows={3} columns={3} />
      ) : gates.length === 0 ? (
        <EmptyState
          icon={<DoorOpen size={28} strokeWidth={1.5} />}
          title={t('siteLogistics.no_gates', { defaultValue: 'No gates yet' })}
          description={t('siteLogistics.no_gates_hint', {
            defaultValue: 'Add the site access gates so deliveries can be scheduled against them.',
          })}
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {gates.map((g) => (
            <GateCard
              key={g.id}
              gate={g}
              canEdit={canEdit}
              canDelete={canDelete}
              onSave={(data) => updateMut.mutateAsync({ id: g.id, data })}
              onDelete={() => deleteMut.mutate(g.id)}
              busy={deleteMut.isPending}
              savePending={updateMut.isPending}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function GateCard({
  gate,
  canEdit,
  canDelete,
  onSave,
  onDelete,
  busy,
  savePending,
}: {
  gate: Gate;
  canEdit: boolean;
  canDelete: boolean;
  onSave: (data: UpdateGatePayload) => Promise<unknown>;
  onDelete: () => void;
  busy: boolean;
  savePending: boolean;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);

  if (editing) {
    return (
      <GateEditForm
        gate={gate}
        pending={savePending}
        onCancel={() => setEditing(false)}
        onSubmit={async (data) => {
          await onSave(data);
          setEditing(false);
        }}
      />
    );
  }

  return (
    <Card padding="none" className="p-4 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <DoorOpen size={16} className="text-oe-blue shrink-0" />
          <span className="text-sm font-semibold text-content-primary truncate">{gate.name}</span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {canEdit && (
            <button
              onClick={() => setEditing(true)}
              disabled={busy}
              aria-label={t('siteLogistics.edit_gate', { defaultValue: 'Edit gate' })}
              title={t('siteLogistics.edit_gate', { defaultValue: 'Edit gate' })}
              className="flex h-7 w-7 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors disabled:opacity-40"
            >
              <Pencil size={13} />
            </button>
          )}
          {canDelete && (
            <button
              onClick={onDelete}
              disabled={busy}
              aria-label={t('common.delete', { defaultValue: 'Delete' })}
              className="flex h-7 w-7 items-center justify-center rounded-lg text-content-tertiary hover:bg-semantic-error/10 hover:text-semantic-error transition-colors disabled:opacity-40"
            >
              <Trash2 size={13} />
            </button>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1.5 text-xs text-content-secondary">
        <Clock size={12} className="text-content-tertiary" />
        {gate.open_time} - {gate.close_time}
      </div>
      <div className="text-xs text-content-tertiary">
        {t('siteLogistics.capacity_slots', {
          defaultValue: '{{count}} vehicle(s) per slot',
          count: gate.capacity_per_slot,
        })}
      </div>
      {gate.notes && <p className="text-2xs text-content-tertiary">{gate.notes}</p>}
    </Card>
  );
}

function GateEditForm({
  gate,
  pending,
  onCancel,
  onSubmit,
}: {
  gate: Gate;
  pending: boolean;
  onCancel: () => void;
  onSubmit: (data: UpdateGatePayload) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(gate.name);
  const [openTime, setOpenTime] = useState(gate.open_time);
  const [closeTime, setCloseTime] = useState(gate.close_time);
  const [capacity, setCapacity] = useState(gate.capacity_per_slot);
  const [notes, setNotes] = useState(gate.notes ?? '');

  const nameError = name.trim().length === 0;
  const hoursError = !!openTime && !!closeTime && closeTime <= openTime;
  const canSave = !nameError && !hoursError && !pending;

  const submit = async () => {
    if (!canSave) return;
    try {
      await onSubmit({
        name: name.trim(),
        open_time: openTime,
        close_time: closeTime,
        capacity_per_slot: capacity,
        notes: notes.trim(),
      });
    } catch {
      /* the panel surfaces the error toast; stay in edit mode so the user can retry */
    }
  };

  return (
    <Card padding="none" className="p-4 flex flex-col gap-3">
      <div className="flex items-center gap-2 text-sm font-semibold text-content-primary">
        <Pencil size={14} className="text-oe-blue shrink-0" />
        {t('siteLogistics.edit_gate', { defaultValue: 'Edit gate' })}
      </div>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder={t('siteLogistics.gate_name_placeholder', { defaultValue: 'Gate name' })}
        aria-label={t('siteLogistics.gate_name', { defaultValue: 'Gate name' })}
        className={clsx(inputCls, nameError && 'border-semantic-error')}
      />
      <div className="grid grid-cols-2 gap-2">
        <label className="flex items-center gap-1.5 text-xs text-content-tertiary">
          <span className="shrink-0">{t('siteLogistics.open', { defaultValue: 'Open' })}</span>
          <input
            type="time"
            value={openTime}
            onChange={(e) => setOpenTime(e.target.value)}
            className={inputCls}
          />
        </label>
        <label className="flex items-center gap-1.5 text-xs text-content-tertiary">
          <span className="shrink-0">{t('siteLogistics.close', { defaultValue: 'Close' })}</span>
          <input
            type="time"
            value={closeTime}
            onChange={(e) => setCloseTime(e.target.value)}
            className={inputCls}
          />
        </label>
      </div>
      <label className="flex items-center gap-1.5 text-xs text-content-tertiary">
        <span className="shrink-0">{t('siteLogistics.slots', { defaultValue: 'Slots' })}</span>
        <input
          type="number"
          min={1}
          max={100}
          value={capacity}
          onChange={(e) => setCapacity(Math.max(1, Number(e.target.value) || 1))}
          className={inputCls}
        />
      </label>
      <input
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        placeholder={t('siteLogistics.gate_notes_placeholder', { defaultValue: 'Notes (optional)' })}
        aria-label={t('siteLogistics.field_notes', { defaultValue: 'Notes' })}
        className={inputCls}
      />
      {hoursError && (
        <p className="text-xs text-semantic-error">
          {t('siteLogistics.gate_hours_error', {
            defaultValue: 'Closing time must be after opening time',
          })}
        </p>
      )}
      <div className="flex items-center justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={pending}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button variant="primary" size="sm" onClick={submit} disabled={!canSave}>
          <Check size={13} className="mr-1" />
          {t('common.save', { defaultValue: 'Save' })}
        </Button>
      </div>
    </Card>
  );
}

/* ── Laydown zones panel ───────────────────────────────────────────────── */

function LaydownPanel({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const role = normalizeRole(useAuthStore((s) => s.userRole));
  const canEdit = role === 'editor' || role === 'manager' || role === 'admin';
  const canDelete = role === 'manager' || role === 'admin';

  const [name, setName] = useState('');
  const [capacityDesc, setCapacityDesc] = useState('');
  const [usageNote, setUsageNote] = useState('');

  const { data: zones = [], isLoading } = useQuery({
    queryKey: ['site-logistics-zones', projectId],
    queryFn: () => fetchLaydownZones(projectId),
    enabled: !!projectId,
  });

  const createMut = useMutation({
    mutationFn: () =>
      createLaydownZone({
        project_id: projectId,
        name: name.trim(),
        capacity_desc: capacityDesc.trim() || undefined,
        usage_note: usageNote.trim() || undefined,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['site-logistics-zones'] });
      qc.invalidateQueries({ queryKey: ['site-logistics-stats'] });
      setName('');
      setCapacityDesc('');
      setUsageNote('');
      addToast({ type: 'success', title: t('siteLogistics.zone_added', { defaultValue: 'Laydown zone added' }) });
    },
    onError: (e: unknown) => {
      addToast({
        type: 'error',
        title: t('siteLogistics.zone_add_failed', { defaultValue: 'Could not add zone' }),
        message: getErrorMessage(e),
      });
    },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateLaydownZonePayload }) =>
      updateLaydownZone(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['site-logistics-zones'] });
      addToast({
        type: 'success',
        title: t('siteLogistics.zone_updated', { defaultValue: 'Laydown zone updated' }),
      });
    },
    onError: (e: unknown) => {
      addToast({
        type: 'error',
        title: t('siteLogistics.zone_update_failed', { defaultValue: 'Could not update zone' }),
        message: getErrorMessage(e),
      });
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteLaydownZone(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['site-logistics-zones'] });
      qc.invalidateQueries({ queryKey: ['site-logistics-stats'] });
    },
    onError: (e: unknown) => {
      addToast({
        type: 'error',
        title: t('siteLogistics.zone_delete_failed', { defaultValue: 'Could not delete zone' }),
        message: getErrorMessage(e),
      });
    },
  });

  return (
    <div className="space-y-4">
      {canEdit && (
        <Card padding="none" className="p-4">
          <p className="text-sm font-medium text-content-primary mb-3">
            {t('siteLogistics.add_zone', { defaultValue: 'Add a laydown zone' })}
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('siteLogistics.zone_name_placeholder', { defaultValue: 'Zone name' })}
              className={inputCls}
              aria-label={t('siteLogistics.zone_name', { defaultValue: 'Zone name' })}
            />
            <input
              value={capacityDesc}
              onChange={(e) => setCapacityDesc(e.target.value)}
              placeholder={t('siteLogistics.zone_capacity_placeholder', {
                defaultValue: 'Capacity e.g. 200 m2 / 40 t',
              })}
              className={inputCls}
            />
            <input
              value={usageNote}
              onChange={(e) => setUsageNote(e.target.value)}
              placeholder={t('siteLogistics.zone_usage_placeholder', {
                defaultValue: 'Usage note e.g. rebar only',
              })}
              className={inputCls}
            />
          </div>
          <div className="mt-3 flex justify-end">
            <Button
              variant="primary"
              size="sm"
              disabled={name.trim().length === 0 || createMut.isPending}
              onClick={() => createMut.mutate()}
            >
              <Plus size={14} className="mr-1" />
              {t('siteLogistics.add_zone', { defaultValue: 'Add a laydown zone' })}
            </Button>
          </div>
        </Card>
      )}

      {isLoading ? (
        <SkeletonTable rows={3} columns={3} />
      ) : zones.length === 0 ? (
        <EmptyState
          icon={<Package size={28} strokeWidth={1.5} />}
          title={t('siteLogistics.no_zones', { defaultValue: 'No laydown zones yet' })}
          description={t('siteLogistics.no_zones_hint', {
            defaultValue: 'Map out where materials can be stored and staged on site.',
          })}
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {zones.map((z) => (
            <LaydownCard
              key={z.id}
              zone={z}
              canEdit={canEdit}
              canDelete={canDelete}
              onSave={(data) => updateMut.mutateAsync({ id: z.id, data })}
              onDelete={() => deleteMut.mutate(z.id)}
              busy={deleteMut.isPending}
              savePending={updateMut.isPending}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function LaydownCard({
  zone,
  canEdit,
  canDelete,
  onSave,
  onDelete,
  busy,
  savePending,
}: {
  zone: LaydownZone;
  canEdit: boolean;
  canDelete: boolean;
  onSave: (data: UpdateLaydownZonePayload) => Promise<unknown>;
  onDelete: () => void;
  busy: boolean;
  savePending: boolean;
}) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);

  if (editing) {
    return (
      <LaydownEditForm
        zone={zone}
        pending={savePending}
        onCancel={() => setEditing(false)}
        onSubmit={async (data) => {
          await onSave(data);
          setEditing(false);
        }}
      />
    );
  }

  return (
    <Card padding="none" className="p-4 flex flex-col gap-2">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <MapPin size={16} className="text-emerald-600 shrink-0" />
          <span className="text-sm font-semibold text-content-primary truncate">{zone.name}</span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {canEdit && (
            <button
              onClick={() => setEditing(true)}
              disabled={busy}
              aria-label={t('siteLogistics.edit_zone', { defaultValue: 'Edit zone' })}
              title={t('siteLogistics.edit_zone', { defaultValue: 'Edit zone' })}
              className="flex h-7 w-7 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors disabled:opacity-40"
            >
              <Pencil size={13} />
            </button>
          )}
          {canDelete && (
            <button
              onClick={onDelete}
              disabled={busy}
              aria-label={t('common.delete', { defaultValue: 'Delete' })}
              className="flex h-7 w-7 items-center justify-center rounded-lg text-content-tertiary hover:bg-semantic-error/10 hover:text-semantic-error transition-colors disabled:opacity-40"
            >
              <Trash2 size={13} />
            </button>
          )}
        </div>
      </div>
      {zone.capacity_desc && (
        <div className="text-xs text-content-secondary">
          {t('siteLogistics.zone_capacity', { defaultValue: 'Capacity' })}: {zone.capacity_desc}
        </div>
      )}
      {zone.usage_note && <p className="text-2xs text-content-tertiary">{zone.usage_note}</p>}
    </Card>
  );
}

function LaydownEditForm({
  zone,
  pending,
  onCancel,
  onSubmit,
}: {
  zone: LaydownZone;
  pending: boolean;
  onCancel: () => void;
  onSubmit: (data: UpdateLaydownZonePayload) => Promise<void>;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(zone.name);
  const [capacityDesc, setCapacityDesc] = useState(zone.capacity_desc ?? '');
  const [usageNote, setUsageNote] = useState(zone.usage_note ?? '');

  const nameError = name.trim().length === 0;
  const canSave = !nameError && !pending;

  const submit = async () => {
    if (!canSave) return;
    try {
      await onSubmit({
        name: name.trim(),
        capacity_desc: capacityDesc.trim(),
        usage_note: usageNote.trim(),
      });
    } catch {
      /* the panel surfaces the error toast; stay in edit mode so the user can retry */
    }
  };

  return (
    <Card padding="none" className="p-4 flex flex-col gap-3">
      <div className="flex items-center gap-2 text-sm font-semibold text-content-primary">
        <Pencil size={14} className="text-emerald-600 shrink-0" />
        {t('siteLogistics.edit_zone', { defaultValue: 'Edit zone' })}
      </div>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder={t('siteLogistics.zone_name_placeholder', { defaultValue: 'Zone name' })}
        aria-label={t('siteLogistics.zone_name', { defaultValue: 'Zone name' })}
        className={clsx(inputCls, nameError && 'border-semantic-error')}
      />
      <input
        value={capacityDesc}
        onChange={(e) => setCapacityDesc(e.target.value)}
        placeholder={t('siteLogistics.zone_capacity_placeholder', {
          defaultValue: 'Capacity e.g. 200 m2 / 40 t',
        })}
        aria-label={t('siteLogistics.zone_capacity', { defaultValue: 'Capacity' })}
        className={inputCls}
      />
      <input
        value={usageNote}
        onChange={(e) => setUsageNote(e.target.value)}
        placeholder={t('siteLogistics.zone_usage_placeholder', {
          defaultValue: 'Usage note e.g. rebar only',
        })}
        aria-label={t('siteLogistics.zone_usage', { defaultValue: 'Usage note' })}
        className={inputCls}
      />
      <div className="flex items-center justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onCancel} disabled={pending}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
        <Button variant="primary" size="sm" onClick={submit} disabled={!canSave}>
          <Check size={13} className="mr-1" />
          {t('common.save', { defaultValue: 'Save' })}
        </Button>
      </div>
    </Card>
  );
}

/* ── Gate timeline (per-day marshal view) ──────────────────────────────── */

const HOUR_PX = 56; // vertical pixels for one hour on the timeline axis
const TIMELINE_FALLBACK_START = 6 * 60; // sensible working-day window when no
const TIMELINE_FALLBACK_END = 20 * 60; // gate hours or deliveries anchor the axis

interface LaidOutDelivery {
  delivery: DeliveryBooking;
  startMin: number;
  endMin: number;
  lane: number;
  lanes: number;
}

/**
 * Pack a gate's deliveries into lanes so overlapping windows sit side by side
 * instead of hiding one another. ``laneCount`` is the peak concurrency, so a
 * value above the gate's capacity means the gate is over-booked at some moment.
 */
function packLanes(items: DeliveryBooking[]): { laid: LaidOutDelivery[]; laneCount: number } {
  const sorted = [...items].sort(
    (a, b) => isoMinutesUTC(a.window_start) - isoMinutesUTC(b.window_start),
  );
  const laneEnds: number[] = [];
  const laid: LaidOutDelivery[] = [];
  for (const d of sorted) {
    const startMin = isoMinutesUTC(d.window_start);
    let endMin = isoMinutesUTC(d.window_end);
    if (endMin <= startMin) endMin = startMin + 15; // guard zero or malformed windows
    let lane = laneEnds.findIndex((end) => end <= startMin);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(endMin);
    } else {
      laneEnds[lane] = endMin;
    }
    laid.push({ delivery: d, startMin, endMin, lane, lanes: 1 });
  }
  const laneCount = Math.max(1, laneEnds.length);
  for (const item of laid) item.lanes = laneCount;
  return { laid, laneCount };
}

function OccupancyChip({
  count,
  capacity,
  over,
}: {
  count: number;
  capacity: number | null;
  over: boolean;
}) {
  const { t } = useTranslation();
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-2xs font-semibold tabular-nums shrink-0',
        over
          ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400'
          : 'bg-surface-secondary text-content-secondary',
      )}
      title={
        capacity != null
          ? t('siteLogistics.occupancy_hint', {
              defaultValue: '{{count}} booked against {{capacity}} per slot',
              count,
              capacity,
            })
          : t('siteLogistics.occupancy_hint_nogate', {
              defaultValue: '{{count}} booked with no gate assigned',
              count,
            })
      }
    >
      {capacity != null ? `${count}/${capacity}` : count}
      {over && <AlertTriangle size={10} className="shrink-0" />}
    </span>
  );
}

interface TimelineColumn {
  gate: Gate | null;
  items: DeliveryBooking[];
}

function GateTimeline({
  projectId,
  gates,
  onBook,
  onEdit,
}: {
  projectId: string;
  gates: Gate[];
  onBook: () => void;
  onEdit: (d: DeliveryBooking) => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const role = normalizeRole(useAuthStore((s) => s.userRole));
  const canEdit = role === 'editor' || role === 'manager' || role === 'admin';

  const [day, setDay] = useState<string>(() => todayInput());

  const {
    data: deliveries = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    // Same key shape as the board so an invalidation refreshes both surfaces.
    queryKey: ['site-logistics-deliveries', projectId, day, '', ''],
    queryFn: () => fetchDeliveries(projectId, { day: day || undefined }),
    enabled: !!projectId && !!day,
  });

  // Rejected bookings are cancelled, so they never occupy a slot on the board.
  const active = useMemo(() => deliveries.filter((d) => d.status !== 'rejected'), [deliveries]);
  const sortedActive = useMemo(
    () => [...active].sort((a, b) => a.window_start.localeCompare(b.window_start)),
    [active],
  );

  const gateName = (id: string | null): string =>
    id
      ? (gates.find((g) => g.id === id)?.name ?? '')
      : t('siteLogistics.gate_none', { defaultValue: 'No gate' });

  const columns = useMemo<TimelineColumn[]>(() => {
    const cols: TimelineColumn[] = gates.map((g) => ({
      gate: g,
      items: active.filter((d) => d.gate_id === g.id),
    }));
    const unassigned = active.filter((d) => !d.gate_id);
    if (unassigned.length) cols.push({ gate: null, items: unassigned });
    return cols;
  }, [gates, active]);

  const range = useMemo(() => {
    let start = TIMELINE_FALLBACK_START;
    let end = TIMELINE_FALLBACK_END;
    const opens = gates.map((g) => hhmmToMinutes(g.open_time)).filter((n) => n > 0);
    const closes = gates.map((g) => hhmmToMinutes(g.close_time)).filter((n) => n > 0);
    if (opens.length) start = Math.min(...opens);
    if (closes.length) end = Math.max(...closes);
    // Expand so a delivery booked outside gate hours is never clipped away.
    for (const d of active) {
      start = Math.min(start, isoMinutesUTC(d.window_start));
      end = Math.max(end, isoMinutesUTC(d.window_end));
    }
    start = Math.max(0, Math.floor(start / 60) * 60);
    end = Math.min(24 * 60, Math.ceil(end / 60) * 60);
    if (end - start < 60) end = Math.min(24 * 60, start + 60);
    return { start, end };
  }, [gates, active]);

  const hours = useMemo(() => {
    const out: number[] = [];
    for (let m = range.start; m <= range.end; m += 60) out.push(m);
    return out;
  }, [range]);

  const totalHeight = ((range.end - range.start) / 60) * HOUR_PX;

  const exportCsv = () => {
    if (!sortedActive.length) return;
    const headers = [
      t('siteLogistics.col_date', { defaultValue: 'Date' }),
      t('siteLogistics.col_start', { defaultValue: 'Start' }),
      t('siteLogistics.col_end', { defaultValue: 'End' }),
      t('siteLogistics.field_gate', { defaultValue: 'Gate' }),
      t('siteLogistics.field_supplier', { defaultValue: 'Supplier' }),
      t('siteLogistics.field_vehicle', { defaultValue: 'Vehicle type' }),
      t('siteLogistics.field_materials', { defaultValue: 'Materials' }),
      t('siteLogistics.col_status', { defaultValue: 'Status' }),
      t('siteLogistics.field_contact_name', { defaultValue: 'Contact name' }),
      t('siteLogistics.field_contact_phone', { defaultValue: 'Contact phone' }),
      t('siteLogistics.field_po', { defaultValue: 'PO reference' }),
      t('siteLogistics.field_notes', { defaultValue: 'Notes' }),
    ];
    const rows = sortedActive.map((d) =>
      [
        csvCell(day),
        csvCell(fmtTime(d.window_start)),
        csvCell(fmtTime(d.window_end)),
        csvCell(gateName(d.gate_id)),
        csvCell(d.supplier_name),
        csvCell(d.vehicle_type ?? ''),
        csvCell(d.materials_desc ?? ''),
        csvCell(t(`siteLogistics.status_${d.status}`, { defaultValue: d.status })),
        csvCell(d.contact_name ?? ''),
        csvCell(d.contact_phone ?? ''),
        csvCell(d.po_ref ?? ''),
        csvCell(d.notes ?? ''),
      ].join(','),
    );
    const csv = [headers.map(csvCell).join(','), ...rows].join('\r\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `site-logistics_${day}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const printDay = () => {
    if (!sortedActive.length) return;
    const title = t('siteLogistics.print_title', { defaultValue: 'Delivery schedule' });
    const head = [
      t('siteLogistics.col_start', { defaultValue: 'Start' }),
      t('siteLogistics.col_end', { defaultValue: 'End' }),
      t('siteLogistics.field_gate', { defaultValue: 'Gate' }),
      t('siteLogistics.field_supplier', { defaultValue: 'Supplier' }),
      t('siteLogistics.field_vehicle', { defaultValue: 'Vehicle type' }),
      t('siteLogistics.field_materials', { defaultValue: 'Materials' }),
      t('siteLogistics.col_status', { defaultValue: 'Status' }),
      t('siteLogistics.field_contact_name', { defaultValue: 'Contact name' }),
      t('siteLogistics.field_contact_phone', { defaultValue: 'Contact phone' }),
    ];
    const headHtml = head.map((h) => `<th>${escHtml(h)}</th>`).join('');
    const rowsHtml = sortedActive
      .map((d) => {
        const cells = [
          fmtTime(d.window_start),
          fmtTime(d.window_end),
          gateName(d.gate_id),
          d.supplier_name,
          d.vehicle_type ?? '',
          d.materials_desc ?? '',
          t(`siteLogistics.status_${d.status}`, { defaultValue: d.status }),
          d.contact_name ?? '',
          d.contact_phone ?? '',
        ];
        return `<tr>${cells.map((c) => `<td>${escHtml(c)}</td>`).join('')}</tr>`;
      })
      .join('');
    const html = `<!doctype html><html><head><meta charset="utf-8"><title>${escHtml(
      `${title} ${day}`,
    )}</title><style>body{font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;margin:24px;color:#111}h1{font-size:18px;margin:0 0 4px}p{margin:0 0 16px;color:#555;font-size:13px}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid #ccc;padding:6px 8px;text-align:left;vertical-align:top}th{background:#f3f4f6}@media print{@page{margin:14mm}}</style></head><body><h1>${escHtml(
      title,
    )}</h1><p>${escHtml(day)}</p><table><thead><tr>${headHtml}</tr></thead><tbody>${rowsHtml}</tbody></table></body></html>`;
    const w = window.open('', '_blank', 'width=1024,height=720');
    if (!w) {
      addToast({
        type: 'info',
        title: t('siteLogistics.print_blocked', {
          defaultValue: 'Allow pop-ups to print the schedule',
        }),
      });
      return;
    }
    w.document.write(html);
    w.document.close();
    w.focus();
    w.print();
  };

  return (
    <div className="space-y-4">
      {/* Day navigation + export actions */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setDay((d) => shiftDay(d, -1))}
            aria-label={t('siteLogistics.prev_day', { defaultValue: 'Previous day' })}
          >
            <ChevronLeft size={16} />
          </Button>
          <div className="relative">
            <Calendar
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary pointer-events-none"
            />
            <input
              type="date"
              value={day}
              onChange={(e) => setDay(e.target.value || todayInput())}
              className={inputCls + ' pl-9 w-auto'}
              aria-label={t('siteLogistics.filter_day', { defaultValue: 'Filter by day' })}
            />
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setDay((d) => shiftDay(d, 1))}
            aria-label={t('siteLogistics.next_day', { defaultValue: 'Next day' })}
          >
            <ChevronRight size={16} />
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setDay(todayInput())}>
            {t('siteLogistics.today', { defaultValue: 'Today' })}
          </Button>
        </div>
        <div className="flex items-center gap-1.5">
          <Button variant="ghost" size="sm" onClick={exportCsv} disabled={!sortedActive.length}>
            <Download size={14} className="mr-1" />
            {t('siteLogistics.export_csv', { defaultValue: 'Export CSV' })}
          </Button>
          <Button variant="ghost" size="sm" onClick={printDay} disabled={!sortedActive.length}>
            <Printer size={14} className="mr-1" />
            {t('siteLogistics.print', { defaultValue: 'Print' })}
          </Button>
        </div>
      </div>

      {isLoading ? (
        <SkeletonTable rows={6} columns={4} />
      ) : isError ? (
        <RecoveryCard error={error} onRetry={() => refetch()} />
      ) : columns.length === 0 ? (
        <EmptyState
          icon={<CalendarClock size={28} strokeWidth={1.5} />}
          title={t('siteLogistics.timeline_empty_title', {
            defaultValue: 'Nothing to show for this day',
          })}
          description={t('siteLogistics.timeline_empty_hint', {
            defaultValue:
              'Add a gate and book deliveries to see the day laid out gate by gate, hour by hour.',
          })}
          action={{
            label: t('siteLogistics.book_delivery', { defaultValue: 'Book delivery' }),
            onClick: onBook,
          }}
        />
      ) : (
        <>
          <Card padding="none" className="overflow-hidden">
            <div className="overflow-x-auto">
              <div className="flex min-w-max">
                {/* Hour gutter */}
                <div className="shrink-0 w-14 border-r border-border-light">
                  <div className="h-10 border-b border-border-light" />
                  <div className="relative" style={{ height: totalHeight }}>
                    {hours.map((h) => (
                      <div
                        key={h}
                        className="absolute start-0 end-0 flex justify-end pr-1.5 -translate-y-1/2 text-2xs tabular-nums text-content-tertiary"
                        style={{ top: ((h - range.start) / 60) * HOUR_PX }}
                      >
                        {fmtHourLabel(h)}
                      </div>
                    ))}
                  </div>
                </div>

                {/* Gate columns */}
                {columns.map((col) => {
                  const { laid, laneCount } = packLanes(col.items);
                  const capacity = col.gate?.capacity_per_slot ?? null;
                  const overCapacity = !!col.gate && capacity != null && laneCount > capacity;
                  const openMin = col.gate ? hhmmToMinutes(col.gate.open_time) : 0;
                  const closeMin = col.gate ? hhmmToMinutes(col.gate.close_time) : 0;
                  const closedBands: { top: number; height: number }[] = [];
                  if (col.gate) {
                    if (openMin > range.start) {
                      closedBands.push({
                        top: 0,
                        height: ((openMin - range.start) / 60) * HOUR_PX,
                      });
                    }
                    if (closeMin > range.start && closeMin < range.end) {
                      closedBands.push({
                        top: ((closeMin - range.start) / 60) * HOUR_PX,
                        height: ((range.end - closeMin) / 60) * HOUR_PX,
                      });
                    }
                  }
                  return (
                    <div
                      key={col.gate?.id ?? 'unassigned'}
                      className="shrink-0 w-44 border-r border-border-light last:border-r-0"
                    >
                      <div className="h-10 flex items-center justify-between gap-1 px-2 border-b border-border-light bg-surface-secondary/40">
                        <div className="flex items-center gap-1 min-w-0">
                          {col.gate ? (
                            <DoorOpen size={12} className="text-oe-blue shrink-0" />
                          ) : (
                            <Truck size={12} className="text-content-tertiary shrink-0" />
                          )}
                          <span className="text-xs font-semibold text-content-primary truncate">
                            {col.gate
                              ? col.gate.name
                              : t('siteLogistics.gate_none', { defaultValue: 'No gate' })}
                          </span>
                        </div>
                        <OccupancyChip
                          count={col.items.length}
                          capacity={capacity}
                          over={overCapacity}
                        />
                      </div>
                      <div className="relative bg-surface-primary" style={{ height: totalHeight }}>
                        {/* Closed-hours shading (before opening / after closing) */}
                        {closedBands.map((b, i) => (
                          <div
                            key={`band-${i}`}
                            className="absolute start-0 end-0 bg-surface-secondary/50"
                            style={{ top: b.top, height: Math.max(0, b.height) }}
                          />
                        ))}
                        {/* Hour gridlines */}
                        {hours.map((h) => (
                          <div
                            key={h}
                            className="absolute start-0 end-0 border-t border-border-light/60"
                            style={{ top: ((h - range.start) / 60) * HOUR_PX }}
                          />
                        ))}
                        {/* Delivery blocks */}
                        {laid.map(({ delivery, startMin, endMin, lane, lanes }) => {
                          const top = ((startMin - range.start) / 60) * HOUR_PX;
                          const height = Math.max(22, ((endMin - startMin) / 60) * HOUR_PX);
                          const widthPct = 100 / lanes;
                          const cfg = STATUS_CONFIG[delivery.status] ?? STATUS_CONFIG.requested;
                          return (
                            <button
                              key={delivery.id}
                              type="button"
                              onClick={() => {
                                if (canEdit) onEdit(delivery);
                              }}
                              disabled={!canEdit}
                              title={`${fmtTime(delivery.window_start)}-${fmtTime(
                                delivery.window_end,
                              )}  ${delivery.supplier_name}`}
                              className={clsx(
                                'absolute rounded-md border border-black/5 px-1.5 py-1 text-left overflow-hidden',
                                cfg.cls,
                                canEdit
                                  ? 'cursor-pointer hover:shadow-md hover:ring-1 hover:ring-oe-blue/40 transition-shadow'
                                  : 'cursor-default',
                              )}
                              style={{
                                top,
                                height,
                                left: `calc(${lane * widthPct}% + 2px)`,
                                width: `calc(${widthPct}% - 4px)`,
                              }}
                            >
                              <span className="block text-2xs font-mono tabular-nums leading-tight opacity-80">
                                {fmtTime(delivery.window_start)}
                              </span>
                              <span className="block text-2xs font-semibold leading-tight truncate">
                                {delivery.supplier_name}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </Card>

          {/* Legend + empty-day hint */}
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-2xs text-content-tertiary">
            <span className="inline-flex items-center gap-1">
              <AlertTriangle size={11} className="text-amber-600" />
              {t('siteLogistics.timeline_legend_over', {
                defaultValue: 'Amber occupancy means the gate is over capacity at some point',
              })}
            </span>
            {(['requested', 'approved', 'arrived', 'completed'] as DeliveryStatus[]).map((s) => (
              <span key={s} className="inline-flex items-center gap-1">
                <span className={clsx('h-2.5 w-2.5 rounded-sm', STATUS_CONFIG[s].cls)} />
                {t(`siteLogistics.status_${s}`, { defaultValue: STATUS_CONFIG[s].label })}
              </span>
            ))}
          </div>
          {active.length === 0 && (
            <p className="text-xs text-content-tertiary">
              {t('siteLogistics.timeline_no_day', {
                defaultValue: 'No deliveries booked for this day. Use the arrows to check another day.',
              })}
            </p>
          )}
        </>
      )}
    </div>
  );
}

/* ── Main page ─────────────────────────────────────────────────────────── */

/* ── Bill coverage ─────────────────────────────────────────────────────── */

/**
 * The project's estimate, read as a delivery ledger.
 *
 * This is the screen the link buys. Booking a delivery against a bill position
 * is only bookkeeping until somebody can open one table and see, line by line,
 * how much of what was priced has actually turned up - and what it is worth at
 * the bill's own rate.
 */
function BillCoveragePanel({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');

  React.useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(search.trim()), 250);
    return () => window.clearTimeout(handle);
  }, [search]);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['site-logistics-bill-coverage', projectId, debounced],
    queryFn: () => fetchBillCoverage(projectId, { search: debounced || undefined }),
    enabled: !!projectId,
  });

  if (isError) {
    return <RecoveryCard error={error} onRetry={() => refetch()} />;
  }

  const rows = data?.rows ?? [];
  const currency = data?.currency || undefined;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative flex-1 min-w-[14rem]">
          <Search
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary pointer-events-none"
          />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('siteLogistics.search_bill_placeholder', {
              defaultValue: 'Search by item number or description',
            })}
            aria-label={t('siteLogistics.search_bill', { defaultValue: 'Search the bill' })}
            className={inputCls + ' pl-9'}
          />
        </div>
      </div>

      {data && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div className="flex flex-col rounded-xl border border-border-light bg-surface-elevated/90 p-3 shadow-xs">
            <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
              {t('siteLogistics.stat_positions_covered', {
                defaultValue: 'Positions with deliveries',
              })}
            </span>
            <span className="mt-1 text-2xl font-bold tabular-nums text-content-primary">
              {data.linked_position_count}
            </span>
          </div>
          <div className="flex flex-col rounded-xl border border-border-light bg-surface-elevated/90 p-3 shadow-xs">
            <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
              {t('siteLogistics.stat_value_on_site', { defaultValue: 'Value on site' })}
            </span>
            <span className="mt-1 text-2xl font-bold tabular-nums text-content-primary">
              <MoneyDisplay amount={data.delivered_value_total} currency={currency} />
            </span>
          </div>
          {data.detached_line_count > 0 && (
            <div className="flex flex-col rounded-xl border border-border-light bg-surface-elevated/90 p-3 shadow-xs">
              <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                {t('siteLogistics.stat_detached_lines', { defaultValue: 'Lines off the bill' })}
              </span>
              <span className="mt-1 flex items-center gap-1.5 text-2xl font-bold tabular-nums text-content-primary">
                <Unlink size={16} className="shrink-0 text-content-tertiary" />
                {data.detached_line_count}
              </span>
              <span className="mt-0.5 text-2xs text-content-tertiary">
                {t('siteLogistics.detached_lines_hint', {
                  defaultValue: 'Their estimate line was deleted; the delivery record stands.',
                })}
              </span>
            </div>
          )}
        </div>
      )}

      <Card padding="none">
        {isLoading ? (
          <div className="p-4">
            <SkeletonTable rows={8} />
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={<Table2 size={40} />}
            title={t('siteLogistics.no_bill_positions', {
              defaultValue: 'No estimate lines to deliver against',
            })}
            description={t('siteLogistics.no_bill_positions_hint', {
              defaultValue:
                'This project has no priced bill yet, or nothing matches your search.',
            })}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-light text-2xs uppercase tracking-wide text-content-tertiary">
                  <th className="px-4 py-2 text-left font-medium">
                    {t('siteLogistics.col_item', { defaultValue: 'Item' })}
                  </th>
                  <th className="px-4 py-2 text-left font-medium">
                    {t('siteLogistics.col_description', { defaultValue: 'Description' })}
                  </th>
                  <th className="px-4 py-2 text-right font-medium">
                    {t('siteLogistics.col_bill_quantity', { defaultValue: 'In the bill' })}
                  </th>
                  <th className="px-4 py-2 text-right font-medium">
                    {t('siteLogistics.col_booked', { defaultValue: 'Booked in' })}
                  </th>
                  <th className="px-4 py-2 text-right font-medium">
                    {t('siteLogistics.col_delivered', { defaultValue: 'On site' })}
                  </th>
                  <th className="px-4 py-2 text-right font-medium">
                    {t('siteLogistics.col_outstanding', { defaultValue: 'Outstanding' })}
                  </th>
                  <th className="px-4 py-2 text-right font-medium">
                    {t('siteLogistics.col_value_on_site', { defaultValue: 'Value on site' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.position_id}
                    className={clsx(
                      'border-b border-border-light last:border-b-0 hover:bg-surface-secondary/40 transition-colors',
                      row.over_delivered && 'bg-semantic-warning/5',
                    )}
                  >
                    <td className="px-4 py-2 align-top">
                      <button
                        type="button"
                        onClick={() =>
                          navigate(`/boq?positionId=${encodeURIComponent(row.position_id)}`)
                        }
                        title={t('siteLogistics.view_line_in_boq', {
                          defaultValue: 'Open {{description}} in the bill',
                          description: row.description,
                        })}
                        className="font-mono text-xs tabular-nums text-oe-blue hover:underline"
                      >
                        {row.ordinal || '-'}
                      </button>
                    </td>
                    <td className="px-4 py-2 align-top text-content-primary">
                      <span className="line-clamp-2">{row.description}</span>
                      {row.over_delivered && (
                        <span className="mt-0.5 flex items-center gap-1 text-2xs text-semantic-warning">
                          <AlertTriangle size={10} className="shrink-0" />
                          {t('siteLogistics.over_delivered', {
                            defaultValue: 'More delivered than the bill prices',
                          })}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right align-top tabular-nums text-content-secondary">
                      <QuantityDisplay value={row.bill_quantity} unit={row.unit} />
                    </td>
                    <td className="px-4 py-2 text-right align-top tabular-nums text-content-secondary">
                      <QuantityDisplay value={row.booked_quantity} unit={row.unit} />
                    </td>
                    <td className="px-4 py-2 text-right align-top tabular-nums font-medium text-content-primary">
                      <QuantityDisplay value={row.delivered_quantity} unit={row.unit} />
                    </td>
                    <td
                      className={clsx(
                        'px-4 py-2 text-right align-top tabular-nums',
                        Number(row.outstanding_quantity) < 0
                          ? 'text-semantic-warning'
                          : 'text-content-secondary',
                      )}
                    >
                      <QuantityDisplay value={row.outstanding_quantity} unit={row.unit} />
                    </td>
                    <td className="px-4 py-2 text-right align-top tabular-nums text-content-primary">
                      <MoneyDisplay amount={row.delivered_value} currency={currency} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {data && <TruncationNotice page={{ items: data.rows, total: data.total }} />}
    </div>
  );
}

type TabKey = 'deliveries' | 'timeline' | 'coverage' | 'gates' | 'laydown';

export function SiteLogisticsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useActiveProjectId();

  const [tab, setTab] = useState<TabKey>('deliveries');
  const [showBook, setShowBook] = useState(false);
  // The delivery being edited (shared by the board and the gate timeline so a
  // marshal can fix a booking from whichever view they are looking at).
  const [editing, setEditing] = useState<DeliveryBooking | null>(null);

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
    staleTime: 5 * 60_000,
  });

  const projectId = activeProjectId || projects[0]?.id || '';
  const projectName = projects.find((p) => p.id === projectId)?.name || '';

  // Gates power the board's gate lookup, the filters and the booking form.
  const { data: gates = [] } = useQuery({
    queryKey: ['site-logistics-gates', projectId],
    queryFn: () => fetchGates(projectId),
    enabled: !!projectId,
  });

  const { data: stats } = useQuery({
    queryKey: ['site-logistics-stats', projectId],
    queryFn: () => fetchSiteLogisticsStats(projectId),
    enabled: !!projectId,
  });

  const bookMut = useMutation({
    mutationFn: (payload: CreateDeliveryPayload) => createDelivery(payload),
    onSuccess: (created) => {
      setShowBook(false);
      qc.invalidateQueries({ queryKey: ['site-logistics-deliveries'] });
      qc.invalidateQueries({ queryKey: ['site-logistics-stats'] });
      addToast({
        type: 'success',
        title: t('siteLogistics.booked', { defaultValue: 'Delivery booked' }),
        message: created?.supplier_name,
      });
    },
    onError: (e: unknown) => {
      addToast({
        type: 'error',
        title: t('siteLogistics.book_failed', { defaultValue: 'Could not book delivery' }),
        message: getErrorMessage(e),
      });
    },
  });

  const handleBook = (form: DeliveryFormState) => {
    if (!projectId) return;
    bookMut.mutate({
      project_id: projectId,
      gate_id: form.gate_id || null,
      supplier_name: form.supplier_name.trim(),
      contact_name: form.contact_name.trim() || undefined,
      contact_phone: form.contact_phone.trim() || undefined,
      vehicle_type: form.vehicle_type.trim() || undefined,
      materials_desc: form.materials_desc.trim() || undefined,
      window_start: form.window_start,
      window_end: form.window_end,
      po_ref: form.po_ref.trim() || undefined,
      notes: form.notes.trim() || undefined,
      lines: linePayload(form.lines),
    });
  };

  const editMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateDeliveryPayload }) =>
      updateDelivery(id, data),
    onSuccess: (updated) => {
      setEditing(null);
      qc.invalidateQueries({ queryKey: ['site-logistics-deliveries'] });
      qc.invalidateQueries({ queryKey: ['site-logistics-stats'] });
      addToast({
        type: 'success',
        title: t('siteLogistics.delivery_updated', { defaultValue: 'Delivery updated' }),
        message: updated?.supplier_name,
      });
    },
    onError: (e: unknown) => {
      addToast({
        type: 'error',
        title: t('siteLogistics.update_failed', { defaultValue: 'Could not update delivery' }),
        message: getErrorMessage(e),
      });
    },
  });

  // Editing sends every editable field (empty strings clear an optional field),
  // and leaves status untouched so a re-timed booking keeps its approval state.
  const handleEditSubmit = (form: DeliveryFormState) => {
    if (!editing) return;
    editMut.mutate({
      id: editing.id,
      data: {
        gate_id: form.gate_id || null,
        supplier_name: form.supplier_name.trim(),
        contact_name: form.contact_name.trim(),
        contact_phone: form.contact_phone.trim(),
        vehicle_type: form.vehicle_type.trim(),
        materials_desc: form.materials_desc.trim(),
        window_start: form.window_start,
        window_end: form.window_end,
        po_ref: form.po_ref.trim(),
        notes: form.notes.trim(),
        // Sent whole: the dialog always saves the whole booking, so the list
        // it shows is the list the delivery ends up carrying.
        lines: linePayload(form.lines),
      },
    });
  };

  const tabs: { key: TabKey; label: string; icon: React.ReactNode }[] = [
    {
      key: 'deliveries',
      label: t('siteLogistics.tab_deliveries', { defaultValue: 'Deliveries' }),
      icon: <Truck size={14} />,
    },
    {
      key: 'timeline',
      label: t('siteLogistics.tab_timeline', { defaultValue: 'Gate timeline' }),
      icon: <CalendarClock size={14} />,
    },
    {
      key: 'coverage',
      label: t('siteLogistics.tab_coverage', { defaultValue: 'Bill coverage' }),
      icon: <ClipboardList size={14} />,
    },
    {
      key: 'gates',
      label: t('siteLogistics.tab_gates', { defaultValue: 'Gates' }),
      icon: <DoorOpen size={14} />,
    },
    {
      key: 'laydown',
      label: t('siteLogistics.tab_laydown', { defaultValue: 'Laydown zones' }),
      icon: <Package size={14} />,
    },
  ];

  const statCards = stats
    ? [
        { label: t('siteLogistics.stat_total', { defaultValue: 'Deliveries' }), value: stats.total_deliveries },
        {
          label: t('siteLogistics.status_requested', { defaultValue: 'Requested' }),
          value: stats.by_status?.requested ?? 0,
        },
        {
          label: t('siteLogistics.status_approved', { defaultValue: 'Approved' }),
          value: stats.by_status?.approved ?? 0,
        },
        {
          label: t('siteLogistics.stat_upcoming', { defaultValue: 'Upcoming' }),
          value: stats.upcoming_approved,
        },
        { label: t('siteLogistics.tab_gates', { defaultValue: 'Gates' }), value: stats.gate_count },
        {
          label: t('siteLogistics.stat_positions_covered', {
            defaultValue: 'Positions with deliveries',
          }),
          value: stats.positions_covered ?? 0,
        },
      ]
    : [];

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb
        items={[
          ...(projectName ? [{ label: projectName, to: `/projects/${projectId}` }] : []),
          { label: t('siteLogistics.title', { defaultValue: 'Site Logistics & Delivery' }) },
        ]}
      />

      <PageHeader
        srTitle={t('siteLogistics.title', { defaultValue: 'Site Logistics & Delivery' })}
        subtitle={t('siteLogistics.subtitle', {
          defaultValue:
            'Plan what arrives on site: book deliveries into gate time slots, keep laydown zones tidy, and approve or reject each booking so gates never double-book.',
        })}
        actions={
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              if (!projectId) {
                addToast({
                  type: 'info',
                  title: t('siteLogistics.select_project_first_title', {
                    defaultValue: 'Select a project first',
                  }),
                  message: t('siteLogistics.select_project_first', {
                    defaultValue: 'Pick a project from the top bar, then book a delivery.',
                  }),
                });
                return;
              }
              setShowBook(true);
            }}
            className="shrink-0 whitespace-nowrap"
          >
            <Truck size={14} className="mr-1 shrink-0" />
            <span>{t('siteLogistics.book_delivery', { defaultValue: 'Book delivery' })}</span>
          </Button>
        }
      />

      <DismissibleInfo
        storageKey="site-logistics"
        title={t('siteLogistics.intro_title', {
          defaultValue: 'One plan for everything arriving on site',
        })}
      >
        {t('siteLogistics.intro_body_v2', {
          defaultValue:
            'Set up your access gates and their opening hours, map your laydown zones, then book deliveries into gate slots. Book each delivery against the estimate lines it carries and the Bill coverage tab will tell you, line by line, how much has arrived, what is still to come and what is on site at the bill’s own rate. Bookings outside a gate’s hours are refused, and two approved deliveries can never clash on the same gate.',
        })}
      </DismissibleInfo>

      {/* Summary stats */}
      {projectId && stats && stats.total_deliveries + stats.gate_count > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {statCards.map((c) => (
            <div
              key={c.label}
              className="flex flex-col rounded-xl border border-border-light bg-surface-elevated/90 p-3 shadow-xs"
            >
              <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                {c.label}
              </span>
              <span className="mt-1 text-2xl font-bold tabular-nums text-content-primary">
                {c.value}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-border-light">
        {tabs.map((tb) => (
          <button
            key={tb.key}
            onClick={() => setTab(tb.key)}
            className={clsx(
              'flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
              tab === tb.key
                ? 'border-oe-blue text-oe-blue'
                : 'border-transparent text-content-secondary hover:text-content-primary',
            )}
          >
            {tb.icon}
            {tb.label}
          </button>
        ))}
      </div>

      {/* Content */}
      {!projectId ? (
        <RequiresProject>{null}</RequiresProject>
      ) : tab === 'deliveries' ? (
        <DeliveryBoard
          projectId={projectId}
          gates={gates}
          onBook={() => setShowBook(true)}
          onEdit={setEditing}
        />
      ) : tab === 'timeline' ? (
        <GateTimeline
          projectId={projectId}
          gates={gates}
          onBook={() => setShowBook(true)}
          onEdit={setEditing}
        />
      ) : tab === 'coverage' ? (
        <BillCoveragePanel projectId={projectId} />
      ) : tab === 'gates' ? (
        <GatesPanel projectId={projectId} />
      ) : (
        <LaydownPanel projectId={projectId} />
      )}

      {/* Book delivery modal */}
      {showBook && projectId && (
        <BookDeliveryModal
          projectId={projectId}
          gates={gates}
          onClose={() => {
            bookMut.reset();
            setShowBook(false);
          }}
          onSubmit={handleBook}
          isPending={bookMut.isPending}
          errorMessage={bookMut.error ? getErrorMessage(bookMut.error) : null}
        />
      )}

      {/* Edit delivery modal (reuses the booking form, prefilled) */}
      {editing && projectId && (
        <BookDeliveryModal
          projectId={projectId}
          gates={gates}
          initial={editing}
          onClose={() => {
            editMut.reset();
            setEditing(null);
          }}
          onSubmit={handleEditSubmit}
          isPending={editMut.isPending}
          errorMessage={editMut.error ? getErrorMessage(editMut.error) : null}
        />
      )}
    </div>
  );
}
