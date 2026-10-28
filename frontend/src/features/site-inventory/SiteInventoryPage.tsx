// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  AlertTriangle,
  ArrowDownToLine,
  ArrowLeftRight,
  Boxes,
  Link2,
  Package,
  PackageMinus,
  Plus,
  Receipt,
  Trash2,
  Warehouse,
  X,
} from 'lucide-react';
import { Badge, Button, Card, EmptyState, SkeletonTable, TabBar } from '@/shared/ui';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { ApiError, apiGet, getErrorMessage } from '@/shared/lib/api';
import { normalizeListResponse } from '@/shared/lib/apiHelpers';
import { formatCurrency } from '@/shared/lib/money';
import { formatValue } from '@/shared/lib/numberFormat';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import {
  createItem,
  createLocation,
  deleteItem,
  deleteLocation,
  fetchItems,
  fetchLocations,
  fetchMovements,
  fetchPositionCoverage,
  fetchStockOnHand,
  fetchUnfixedValue,
  recordMovement,
  updateItem,
  MOVEMENT_TYPES,
  type LocationCreate,
  type MovementCreate,
  type MovementType,
  type PositionCoverageResponse,
  type PositionCoverageRow,
  type StockItem,
  type StockItemCreate,
  type StockItemUpdate,
  type StockLocation,
  type StockMovement,
  type StockOnHandRow,
  type UnfixedValueResponse,
  type UnitAgreement,
} from './api';
import {
  holderList,
  probeHolders,
  type DeleteTarget,
  type Holder,
} from './deleteGuard';
import { buildSiteInventoryInsights } from './siteInventoryInsights';

/* -- Shared styling + small helpers --------------------------------------- */

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const textareaCls =
  'w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue resize-none';

type TabId = 'stock' | 'bill' | 'movements' | 'items' | 'locations';
type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';
type BalanceStatus = 'ok' | 'low' | 'negative';

const MOVEMENT_TYPE_CONFIG: Record<MovementType, { icon: React.ElementType; variant: BadgeVariant }> = {
  INBOUND: { icon: ArrowDownToLine, variant: 'success' },
  CONSUMPTION: { icon: PackageMinus, variant: 'blue' },
  WASTE: { icon: Trash2, variant: 'error' },
  TRANSFER: { icon: ArrowLeftRight, variant: 'neutral' },
};

/** English fallback labels for the movement-type enum (real text goes through
 *  the site_inventory.movement_type_* i18n keys). */
const MOVEMENT_TYPE_LABEL: Record<MovementType, string> = {
  INBOUND: 'Inbound',
  CONSUMPTION: 'Consumption',
  WASTE: 'Waste',
  TRANSFER: 'Transfer',
};

/** Parse a decimal string to a number, or NaN when absent / unparseable. */
/** Fold a unit label the way the backend ledger does, so the warning shown in
 *  the form and the comparison withheld by the report agree about "m3" vs "m³".
 *  Typography only - it must never make two different units look like one. */
function normaliseUnit(unit: string | null | undefined): string {
  if (!unit) return '';
  return unit
    .replace(/²/g, '2')
    .replace(/³/g, '3')
    .toLowerCase()
    .replace(/\s+/g, '')
    .replace(/\.+$/, '');
}

function toNumber(value: string | null | undefined): number {
  if (value == null || value.trim() === '') return Number.NaN;
  return Number.parseFloat(value);
}

/* -- Reusable modal shell -------------------------------------------------- */

function Modal({
  title,
  onClose,
  children,
  footer,
  maxWidth = 'max-w-lg',
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  footer: React.ReactNode;
  maxWidth?: string;
}) {
  const { t } = useTranslation();
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg p-4 animate-fade-in">
      <div
        className={clsx(
          'w-full bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in max-h-[90vh] overflow-y-auto',
          maxWidth,
        )}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">{title}</h2>
          <button
            onClick={onClose}
            aria-label={t('site_inventory.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>
        <div className="px-6 py-4 space-y-4">{children}</div>
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          {footer}
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  required,
  hint,
  children,
}: {
  label: string;
  required?: boolean;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-content-primary mb-1.5">
        {label}
        {required && <span className="text-semantic-error"> *</span>}
      </label>
      {children}
      {hint && <p className="mt-1 text-xs text-content-tertiary">{hint}</p>}
    </div>
  );
}

function InlineError({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { t } = useTranslation();
  return (
    <Card padding="lg" className="flex flex-col items-center gap-3 text-center">
      <AlertTriangle size={24} className="text-semantic-error" />
      <p className="text-sm text-content-secondary">{getErrorMessage(error)}</p>
      <Button variant="secondary" size="sm" onClick={onRetry}>
        {t('site_inventory.retry', { defaultValue: 'Retry' })}
      </Button>
    </Card>
  );
}

/* -- Create-location modal ------------------------------------------------- */

function CreateLocationModal({
  onClose,
  onSubmit,
  isPending,
}: {
  onClose: () => void;
  onSubmit: (data: LocationCreate) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [address, setAddress] = useState('');
  const [latitude, setLatitude] = useState('');
  const [longitude, setLongitude] = useState('');
  const [touched, setTouched] = useState(false);

  const nameError = touched && name.trim().length === 0;
  const submit = () => {
    setTouched(true);
    if (name.trim().length === 0) return;
    onSubmit({
      name: name.trim(),
      code: code.trim() || undefined,
      address: address.trim() || undefined,
      latitude: latitude.trim() || undefined,
      longitude: longitude.trim() || undefined,
    });
  };

  return (
    <Modal
      title={t('site_inventory.new_location_title', { defaultValue: 'New storage location' })}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('site_inventory.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={isPending}
            icon={!isPending ? <Plus size={16} /> : undefined}
          >
            {t('site_inventory.create_location', { defaultValue: 'Create location' })}
          </Button>
        </>
      }
    >
      <Field label={t('site_inventory.field_name', { defaultValue: 'Name' })} required>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
          placeholder={t('site_inventory.name_placeholder', {
            defaultValue: 'e.g. Main yard, Container B, Level 2 store',
          })}
          className={clsx(inputCls, nameError && 'border-semantic-error focus:ring-red-300')}
        />
        {nameError && (
          <p className="mt-1 text-xs text-semantic-error">
            {t('site_inventory.name_required', { defaultValue: 'Name is required' })}
          </p>
        )}
      </Field>
      <Field label={t('site_inventory.field_code', { defaultValue: 'Code' })}>
        <input value={code} onChange={(e) => setCode(e.target.value)} className={inputCls} />
      </Field>
      <Field label={t('site_inventory.field_address', { defaultValue: 'Address' })}>
        <input value={address} onChange={(e) => setAddress(e.target.value)} className={inputCls} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t('site_inventory.field_latitude', { defaultValue: 'Latitude' })}>
          <input
            value={latitude}
            onChange={(e) => setLatitude(e.target.value)}
            inputMode="decimal"
            className={inputCls}
          />
        </Field>
        <Field label={t('site_inventory.field_longitude', { defaultValue: 'Longitude' })}>
          <input
            value={longitude}
            onChange={(e) => setLongitude(e.target.value)}
            inputMode="decimal"
            className={inputCls}
          />
        </Field>
      </div>
    </Modal>
  );
}

/* -- Create-item modal ----------------------------------------------------- */

/* -- BOQ position picker --------------------------------------------------- */

/** A BoQ position as this page needs it: enough to name it on screen and to
 *  compare its unit against the stock item's. */
export interface BoqPositionPick {
  id: string;
  ordinal: string;
  description: string;
  unit: string;
}

interface BoqListItem {
  id: string;
  name: string;
}

interface BoqPositionRow {
  id: string;
  ordinal: string;
  description: string;
  unit: string;
}

interface BoqWithPositions {
  positions: BoqPositionRow[];
}

/** Render a chosen position as "ordinal - description", falling back to the
 *  id when the bill is still loading, so a linked row never renders blank. */
function positionLabel(pick: BoqPositionPick | null, fallbackId: string | null): string {
  if (pick) {
    const head = pick.ordinal ? `${pick.ordinal} ` : '';
    return `${head}${pick.description}`.trim();
  }
  return fallbackId ? fallbackId.slice(0, 8) : '';
}

/**
 * Two-step picker over the project's own bill: choose a BOQ, then a position
 * inside it. This is the only way a storeman attaches a material record to the
 * line that priced it, so it is reachable from the item form, the movement
 * form and the items table alike.
 */
function BoqPositionPickerDialog({
  projectId,
  onClose,
  onPick,
}: {
  projectId: string;
  onClose: () => void;
  onPick: (pick: BoqPositionPick) => void;
}) {
  const { t } = useTranslation();
  const [boqId, setBoqId] = useState('');
  const [search, setSearch] = useState('');

  const { data: boqs = [], isLoading: boqsLoading } = useQuery({
    queryKey: ['site-inventory', 'boqs', projectId],
    queryFn: () => apiGet<BoqListItem[]>(`/v1/boq/boqs/?project_id=${projectId}`),
    select: (d): BoqListItem[] => normalizeListResponse(d),
    enabled: !!projectId,
  });

  const { data: boqDetail, isLoading: posLoading } = useQuery({
    queryKey: ['site-inventory', 'boq-positions', boqId],
    queryFn: () => apiGet<BoqWithPositions>(`/v1/boq/boqs/${boqId}`),
    enabled: !!boqId,
  });

  const positions = useMemo(() => {
    const rows = boqDetail?.positions ?? [];
    const q = search.trim().toLowerCase();
    const filtered = q
      ? rows.filter(
          (p) =>
            (p.description || '').toLowerCase().includes(q) ||
            (p.ordinal || '').toLowerCase().includes(q),
        )
      : rows;
    return filtered.slice(0, 300);
  }, [boqDetail, search]);

  return (
    <Modal
      title={t('site_inventory.pick_position_title', { defaultValue: 'Link to a bill position' })}
      onClose={onClose}
      maxWidth="max-w-2xl"
      footer={
        <Button variant="ghost" onClick={onClose}>
          {t('site_inventory.cancel', { defaultValue: 'Cancel' })}
        </Button>
      }
    >
      <p className="mb-3 text-xs text-content-tertiary">
        {t('site_inventory.pick_position_hint', {
          defaultValue:
            'Pick the position that priced this material. The link is what lets the page compare what was ordered, what arrived and what the bill allows.',
        })}
      </p>
      <Field label={t('site_inventory.field_boq', { defaultValue: 'Bill of quantities' })}>
        <select
          value={boqId}
          onChange={(e) => setBoqId(e.target.value)}
          disabled={boqsLoading}
          className={inputCls}
        >
          <option value="">
            {boqsLoading
              ? t('common.loading', { defaultValue: 'Loading...' })
              : boqs.length > 0
                ? t('common.select_boq', { defaultValue: 'Select BOQ...' })
                : t('boq.no_boqs_for_project', { defaultValue: 'No BOQs found for this project' })}
          </option>
          {boqs.map((b) => (
            <option key={b.id} value={b.id}>
              {b.name}
            </option>
          ))}
        </select>
      </Field>

      {boqId !== '' && (
        <Field label={t('common.search', { defaultValue: 'Search' })}>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('site_inventory.pick_position_search', {
              defaultValue: 'Filter by description or ordinal',
            })}
            className={inputCls}
            autoComplete="off"
          />
        </Field>
      )}

      {boqId !== '' &&
        (posLoading ? (
          <SkeletonTable rows={5} columns={3} />
        ) : positions.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border px-3 py-6 text-center text-xs text-content-tertiary">
            {t('site_inventory.pick_position_empty', {
              defaultValue: 'No positions match. Pick another bill or clear the filter.',
            })}
          </p>
        ) : (
          <div className="max-h-80 overflow-y-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <tbody>
                {positions.map((p) => (
                  <tr
                    key={p.id}
                    className="cursor-pointer border-b border-border-light last:border-0 hover:bg-surface-secondary/60"
                    onClick={() =>
                      onPick({
                        id: p.id,
                        ordinal: p.ordinal || '',
                        description: p.description || '',
                        unit: p.unit || '',
                      })
                    }
                  >
                    <td className="px-3 py-2 font-mono text-2xs text-content-tertiary">
                      {p.ordinal || '-'}
                    </td>
                    <td className="px-3 py-2">{p.description}</td>
                    <td className="px-3 py-2 text-right text-xs text-content-tertiary">
                      {p.unit || '-'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </Modal>
  );
}

/** The field that shows a chosen position and opens the picker. Shared by the
 *  item form and the movement form so both speak about the link the same way. */
function PositionField({
  label,
  hint,
  pick,
  linkedId,
  unitToCompare,
  onOpen,
  onClear,
}: {
  label: string;
  hint?: string;
  pick: BoqPositionPick | null;
  linkedId: string | null;
  unitToCompare?: string;
  onOpen: () => void;
  onClear: () => void;
}) {
  const { t } = useTranslation();
  const mismatch =
    pick !== null &&
    unitToCompare !== undefined &&
    normaliseUnit(unitToCompare) !== '' &&
    normaliseUnit(pick.unit) !== '' &&
    normaliseUnit(unitToCompare) !== normaliseUnit(pick.unit);

  return (
    <Field label={label} hint={hint}>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onOpen}
          className={clsx(inputCls, 'flex-1 text-left', !pick && !linkedId && 'text-content-tertiary')}
        >
          {pick || linkedId
            ? positionLabel(pick, linkedId)
            : t('site_inventory.no_position_linked', { defaultValue: 'Not linked to the bill' })}
        </button>
        {(pick || linkedId) && (
          <Button variant="ghost" size="sm" onClick={onClear}>
            {t('site_inventory.clear_link', { defaultValue: 'Clear' })}
          </Button>
        )}
      </div>
      {mismatch && (
        <p className="mt-1 text-xs text-semantic-warning">
          {t('site_inventory.unit_mismatch_warning', {
            defaultValue:
              'The bill measures this position in {{billUnit}} and the item is metered in {{itemUnit}}. The link is kept, but quantities will not be compared.',
            billUnit: pick?.unit,
            itemUnit: unitToCompare,
          })}
        </p>
      )}
    </Field>
  );
}

function CreateItemModal({
  locations,
  projectId,
  onClose,
  onSubmit,
  isPending,
}: {
  projectId: string;
  locations: StockLocation[];
  onClose: () => void;
  onSubmit: (data: StockItemCreate) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState('');
  const [sku, setSku] = useState('');
  const [unit, setUnit] = useState('');
  const [unitCost, setUnitCost] = useState('');
  const [currency, setCurrency] = useState('');
  const [reorderPoint, setReorderPoint] = useState('');
  const [defaultLocationId, setDefaultLocationId] = useState('');
  const [position, setPosition] = useState<BoqPositionPick | null>(null);
  const [showPicker, setShowPicker] = useState(false);
  const [touched, setTouched] = useState(false);

  const nameError = touched && name.trim().length === 0;
  const submit = () => {
    setTouched(true);
    if (name.trim().length === 0) return;
    onSubmit({
      name: name.trim(),
      sku: sku.trim() || undefined,
      unit: unit.trim() || undefined,
      boq_position_id: position?.id || undefined,
      standard_unit_cost: unitCost.trim() || undefined,
      currency: currency.trim() || undefined,
      reorder_point: reorderPoint.trim() || undefined,
      default_location_id: defaultLocationId || undefined,
    });
  };

  // Picking the position first is the common case: the storeman knows which
  // line he is buying against, and the bill's own unit is the right default
  // for the item, so it is offered rather than left blank.
  const applyPick = (pick: BoqPositionPick) => {
    setPosition(pick);
    setShowPicker(false);
    if (unit.trim() === '' && pick.unit) setUnit(pick.unit);
  };

  return (
    <Modal
      title={t('site_inventory.new_item_title', { defaultValue: 'New stock item' })}
      onClose={onClose}
      maxWidth="max-w-xl"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('site_inventory.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            loading={isPending}
            icon={!isPending ? <Plus size={16} /> : undefined}
          >
            {t('site_inventory.create_item', { defaultValue: 'Create item' })}
          </Button>
        </>
      }
    >
      <Field label={t('site_inventory.field_name', { defaultValue: 'Name' })} required>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
          placeholder={t('site_inventory.item_name_placeholder', {
            defaultValue: 'e.g. Ready-mix concrete C30/37',
          })}
          className={clsx(inputCls, nameError && 'border-semantic-error focus:ring-red-300')}
        />
        {nameError && (
          <p className="mt-1 text-xs text-semantic-error">
            {t('site_inventory.name_required', { defaultValue: 'Name is required' })}
          </p>
        )}
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label={t('site_inventory.field_sku', { defaultValue: 'SKU' })}>
          <input value={sku} onChange={(e) => setSku(e.target.value)} className={inputCls} />
        </Field>
        <Field label={t('site_inventory.field_unit', { defaultValue: 'Unit of measure' })}>
          <input
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            placeholder={t('site_inventory.unit_placeholder', { defaultValue: 'e.g. m3, kg, pcs' })}
            className={inputCls}
          />
        </Field>
      </div>
      <PositionField
        label={t('site_inventory.field_position', { defaultValue: 'Bill position' })}
        hint={t('site_inventory.field_position_hint', {
          defaultValue:
            'Links this material to the line that priced it, so the page can show what is still to arrive and what is standing on site unfixed.',
        })}
        pick={position}
        linkedId={null}
        unitToCompare={unit}
        onOpen={() => setShowPicker(true)}
        onClear={() => setPosition(null)}
      />
      {showPicker && (
        <BoqPositionPickerDialog
          projectId={projectId}
          onClose={() => setShowPicker(false)}
          onPick={applyPick}
        />
      )}
      <div className="grid grid-cols-2 gap-3">
        <Field label={t('site_inventory.field_unit_cost', { defaultValue: 'Standard unit cost' })}>
          <input
            value={unitCost}
            onChange={(e) => setUnitCost(e.target.value)}
            inputMode="decimal"
            className={inputCls}
          />
        </Field>
        <Field label={t('site_inventory.field_currency', { defaultValue: 'Currency' })}>
          <input
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            placeholder="EUR"
            className={inputCls}
          />
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field
          label={t('site_inventory.field_reorder', { defaultValue: 'Reorder point' })}
          hint={t('site_inventory.reorder_hint', {
            defaultValue: 'Balances at or below this level are flagged as low stock.',
          })}
        >
          <input
            value={reorderPoint}
            onChange={(e) => setReorderPoint(e.target.value)}
            inputMode="decimal"
            className={inputCls}
          />
        </Field>
        <Field label={t('site_inventory.field_default_location', { defaultValue: 'Default location' })}>
          <select
            value={defaultLocationId}
            onChange={(e) => setDefaultLocationId(e.target.value)}
            className={inputCls}
          >
            <option value="">
              {t('site_inventory.no_location_option', { defaultValue: 'No default location' })}
            </option>
            {locations.map((loc) => (
              <option key={loc.id} value={loc.id}>
                {loc.name}
              </option>
            ))}
          </select>
        </Field>
      </div>
    </Modal>
  );
}

/* -- Record-movement modal ------------------------------------------------- */

function RecordMovementModal({
  items,
  locations,
  projectId,
  onClose,
  onSubmit,
  isPending,
}: {
  items: StockItem[];
  locations: StockLocation[];
  projectId: string;
  onClose: () => void;
  onSubmit: (data: MovementCreate) => void;
  isPending: boolean;
}) {
  const { t } = useTranslation();
  const [itemId, setItemId] = useState('');
  const [movementType, setMovementType] = useState<MovementType>('INBOUND');
  const [quantity, setQuantity] = useState('');
  const [unitCost, setUnitCost] = useState('');
  const [currency, setCurrency] = useState('');
  const [locationId, setLocationId] = useState('');
  const [toLocationId, setToLocationId] = useState('');
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [note, setNote] = useState('');
  const [position, setPosition] = useState<BoqPositionPick | null>(null);
  const [showPicker, setShowPicker] = useState(false);
  const [touched, setTouched] = useState(false);

  const isTransfer = movementType === 'TRANSFER';
  const qtyNum = toNumber(quantity);
  const itemError = touched && itemId === '';
  const qtyError = touched && !(qtyNum > 0);
  const transferError =
    touched && isTransfer && (locationId === '' || toLocationId === '' || locationId === toLocationId);
  const canSubmit =
    itemId !== '' &&
    qtyNum > 0 &&
    (!isTransfer || (locationId !== '' && toLocationId !== '' && locationId !== toLocationId));

  const chosenItem = items.find((it) => it.id === itemId);

  const onItemChange = (nextId: string) => {
    setItemId(nextId);
    const chosen = items.find((it) => it.id === nextId);
    if (chosen) {
      if (currency.trim() === '' && chosen.currency) setCurrency(chosen.currency);
      if (unitCost.trim() === '' && chosen.standard_unit_cost) setUnitCost(chosen.standard_unit_cost);
    }
  };

  const submit = () => {
    setTouched(true);
    if (!canSubmit) return;
    onSubmit({
      item_id: itemId,
      movement_type: movementType,
      quantity: quantity.trim(),
      unit_cost: unitCost.trim() || undefined,
      currency: currency.trim() || undefined,
      location_id: locationId || undefined,
      to_location_id: isTransfer ? toLocationId || undefined : undefined,
      // Left blank, the movement inherits the item's position when the report
      // is read, so this only has to be filled in to override it.
      boq_position_id: position?.id || undefined,
      occurred_at: date ? new Date(date).toISOString() : undefined,
      note: note.trim() || undefined,
    });
  };

  return (
    <Modal
      title={t('site_inventory.record_movement_title', { defaultValue: 'Record stock movement' })}
      onClose={onClose}
      maxWidth="max-w-xl"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t('site_inventory.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" onClick={submit} loading={isPending} disabled={!canSubmit}>
            {t('site_inventory.record', { defaultValue: 'Record' })}
          </Button>
        </>
      }
    >
      {/* Movement type selector */}
      <Field label={t('site_inventory.field_movement_type', { defaultValue: 'Movement type' })}>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {MOVEMENT_TYPES.map((mt) => {
            const cfg = MOVEMENT_TYPE_CONFIG[mt];
            const Icon = cfg.icon;
            const selected = movementType === mt;
            return (
              <button
                key={mt}
                type="button"
                onClick={() => setMovementType(mt)}
                className={clsx(
                  'flex items-center gap-2 rounded-lg border-2 px-3 py-2.5 text-left transition-all',
                  selected
                    ? 'border-oe-blue bg-oe-blue-subtle text-content-primary'
                    : 'border-border bg-surface-primary text-content-tertiary hover:border-border-light hover:bg-surface-secondary',
                )}
              >
                <Icon size={16} className="shrink-0" />
                <span className="text-xs font-semibold">
                  {t(`site_inventory.movement_type_${mt.toLowerCase()}`, {
                    defaultValue: MOVEMENT_TYPE_LABEL[mt],
                  })}
                </span>
              </button>
            );
          })}
        </div>
      </Field>

      <Field label={t('site_inventory.field_item', { defaultValue: 'Item' })} required>
        <select
          value={itemId}
          onChange={(e) => onItemChange(e.target.value)}
          className={clsx(inputCls, itemError && 'border-semantic-error focus:ring-red-300')}
        >
          <option value="">{t('site_inventory.select_item', { defaultValue: 'Select an item' })}</option>
          {items.map((it) => (
            <option key={it.id} value={it.id}>
              {it.name}
              {it.unit ? ` (${it.unit})` : ''}
            </option>
          ))}
        </select>
        {itemError && (
          <p className="mt-1 text-xs text-semantic-error">
            {t('site_inventory.item_required', { defaultValue: 'Select an item' })}
          </p>
        )}
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field label={t('site_inventory.field_quantity', { defaultValue: 'Quantity' })} required>
          <input
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            inputMode="decimal"
            placeholder={t('site_inventory.quantity_placeholder', { defaultValue: 'e.g. 12.5' })}
            className={clsx(inputCls, qtyError && 'border-semantic-error focus:ring-red-300')}
          />
          {qtyError && (
            <p className="mt-1 text-xs text-semantic-error">
              {t('site_inventory.quantity_required', {
                defaultValue: 'Enter a quantity greater than zero',
              })}
            </p>
          )}
        </Field>
        <Field label={t('site_inventory.field_date', { defaultValue: 'Date' })}>
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className={inputCls}
          />
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label={t('site_inventory.field_unit_cost_optional', { defaultValue: 'Unit cost' })}>
          <input
            value={unitCost}
            onChange={(e) => setUnitCost(e.target.value)}
            inputMode="decimal"
            className={inputCls}
          />
        </Field>
        <Field label={t('site_inventory.field_currency', { defaultValue: 'Currency' })}>
          <input value={currency} onChange={(e) => setCurrency(e.target.value)} className={inputCls} />
        </Field>
      </div>

      <Field
        label={
          isTransfer
            ? t('site_inventory.field_from_location', { defaultValue: 'From location' })
            : t('site_inventory.field_location', { defaultValue: 'Location' })
        }
        required={isTransfer}
      >
        <select
          value={locationId}
          onChange={(e) => setLocationId(e.target.value)}
          className={clsx(inputCls, transferError && 'border-semantic-error focus:ring-red-300')}
        >
          <option value="">{t('site_inventory.none_option', { defaultValue: 'None' })}</option>
          {locations.map((loc) => (
            <option key={loc.id} value={loc.id}>
              {loc.name}
            </option>
          ))}
        </select>
      </Field>

      {isTransfer && (
        <Field label={t('site_inventory.field_to_location', { defaultValue: 'To location' })} required>
          <select
            value={toLocationId}
            onChange={(e) => setToLocationId(e.target.value)}
            className={clsx(inputCls, transferError && 'border-semantic-error focus:ring-red-300')}
          >
            <option value="">{t('site_inventory.none_option', { defaultValue: 'None' })}</option>
            {locations.map((loc) => (
              <option key={loc.id} value={loc.id}>
                {loc.name}
              </option>
            ))}
          </select>
          {transferError && (
            <p className="mt-1 text-xs text-semantic-error">
              {t('site_inventory.transfer_needs_locations', {
                defaultValue: 'A transfer needs a source and a different destination location',
              })}
            </p>
          )}
        </Field>
      )}

      {!isTransfer && (
        <>
          <PositionField
            label={t('site_inventory.field_position', { defaultValue: 'Bill position' })}
            hint={
              chosenItem?.boq_position_id && !position
                ? t('site_inventory.position_inherited_hint', {
                    defaultValue:
                      'This movement will be counted against the position the item is linked to. Pick one here only to book it against a different position.',
                  })
                : t('site_inventory.position_movement_hint', {
                    defaultValue: 'Which bill position this movement is counted against.',
                  })
            }
            pick={position}
            linkedId={null}
            unitToCompare={chosenItem?.unit}
            onOpen={() => setShowPicker(true)}
            onClear={() => setPosition(null)}
          />
          {showPicker && (
            <BoqPositionPickerDialog
              projectId={projectId}
              onClose={() => setShowPicker(false)}
              onPick={(pick) => {
                setPosition(pick);
                setShowPicker(false);
              }}
            />
          )}
        </>
      )}

      <Field label={t('site_inventory.field_note', { defaultValue: 'Note' })}>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={2}
          placeholder={t('site_inventory.note_placeholder', {
            defaultValue: 'Optional reference, delivery note or reason',
          })}
          className={textareaCls}
        />
      </Field>
    </Modal>
  );
}

/* -- Main page ------------------------------------------------------------- */

export function SiteInventoryPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = routeProjectId || activeProjectId || '';
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [activeTab, setActiveTab] = useState<TabId>('stock');
  const [showMovementModal, setShowMovementModal] = useState(false);
  const [showItemModal, setShowItemModal] = useState(false);
  const [showLocationModal, setShowLocationModal] = useState(false);
  // The item whose bill link is being changed from the items table, if any.
  const [linkTarget, setLinkTarget] = useState<StockItem | null>(null);
  // The row a delete was asked for, and - once the server has refused one -
  // what it said was holding that row. `null` means "not refused"; an empty
  // array means "refused, and we could not name the holder", which is a
  // different sentence from "nothing holds it".
  const [deleteTarget, setDeleteTarget] = useState<DeleteTarget | null>(null);
  const [refusedHolders, setRefusedHolders] = useState<Holder[] | null>(null);

  /* -- Queries ------------------------------------------------------------ */
  const stockQuery = useQuery({
    queryKey: ['site-inventory', 'stock-on-hand', projectId],
    queryFn: () => fetchStockOnHand(projectId),
    enabled: !!projectId,
  });
  const movementsQuery = useQuery({
    queryKey: ['site-inventory', 'movements', projectId],
    queryFn: () => fetchMovements(projectId),
    enabled: !!projectId,
  });
  const itemsQuery = useQuery({
    queryKey: ['site-inventory', 'items', projectId],
    queryFn: () => fetchItems(projectId),
    enabled: !!projectId,
  });
  const locationsQuery = useQuery({
    queryKey: ['site-inventory', 'locations', projectId],
    queryFn: () => fetchLocations(projectId),
    enabled: !!projectId,
  });
  const coverageQuery = useQuery({
    queryKey: ['site-inventory', 'position-coverage', projectId],
    queryFn: () => fetchPositionCoverage(projectId),
    enabled: !!projectId,
  });
  const unfixedValueQuery = useQuery({
    queryKey: ['site-inventory', 'unfixed-value', projectId],
    queryFn: () => fetchUnfixedValue(projectId),
    enabled: !!projectId,
  });

  const items = useMemo(() => itemsQuery.data ?? [], [itemsQuery.data]);
  const locations = useMemo(() => locationsQuery.data ?? [], [locationsQuery.data]);
  const movements = useMemo(() => movementsQuery.data ?? [], [movementsQuery.data]);
  const stockRows = useMemo(() => stockQuery.data?.rows ?? [], [stockQuery.data]);

  const itemsById = useMemo(
    () => new Map(items.map((it) => [it.id, it] as const)),
    [items],
  );
  const locationsById = useMemo(
    () => new Map(locations.map((l) => [l.id, l] as const)),
    [locations],
  );
  const reorderById = useMemo(
    () => new Map(items.map((it) => [it.id, it.reorder_point] as const)),
    [items],
  );

  const balanceStatus = useCallback(
    (row: StockOnHandRow): BalanceStatus => {
      const qty = toNumber(row.on_hand);
      if (Number.isFinite(qty) && qty < 0) return 'negative';
      const rp = toNumber(reorderById.get(row.item_id));
      if (Number.isFinite(rp) && Number.isFinite(qty) && qty <= rp) return 'low';
      return 'ok';
    },
    [reorderById],
  );

  const stockSummary = useMemo(() => {
    let low = 0;
    let negative = 0;
    for (const row of stockRows) {
      const status = balanceStatus(row);
      if (status === 'negative') negative += 1;
      else if (status === 'low') low += 1;
    }
    return { tracked: stockRows.length, low, negative };
  }, [stockRows, balanceStatus]);

  // Module Insights - the toggleable visualization panel for this module. Its
  // charts are built client-side from the stock and movement ledgers already
  // loaded; when the project has none the panel draws nothing rather than
  // inventing rows to fill it. Declared before the first return below so the
  // hook order stays stable.
  const inventoryCurrency =
    items.find((i) => i.currency)?.currency ||
    movements.find((m) => m.currency)?.currency ||
    '';
  const insights = useModuleInsights('site-inventory', { defaultOpen: true });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildSiteInventoryInsights(stockRows, movements, items, inventoryCurrency, t),
    [stockRows, movements, items, inventoryCurrency, t],
  );

  const itemName = useCallback(
    (id: string): string =>
      itemsById.get(id)?.name ?? t('site_inventory.unknown_item', { defaultValue: 'Unknown item' }),
    [itemsById, t],
  );
  const locName = useCallback(
    (id: string | null): string => {
      if (!id) return '';
      const loc = locationsById.get(id);
      return loc?.name ?? loc?.code ?? id.slice(0, 8);
    },
    [locationsById],
  );

  /* -- Mutations ---------------------------------------------------------- */
  const toastError = useCallback(
    (e: unknown) =>
      addToast({
        type: 'error',
        title: t('site_inventory.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      }),
    [addToast, t],
  );

  const locationMut = useMutation({
    mutationFn: (data: LocationCreate) => createLocation(projectId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['site-inventory', 'locations', projectId] });
      setShowLocationModal(false);
      addToast({
        type: 'success',
        title: t('site_inventory.location_created', { defaultValue: 'Location created' }),
      });
    },
    onError: toastError,
  });

  // Both bill reports are derived from the items and the movement ledger, so
  // anything that changes either has to refresh them or the page keeps showing
  // an answer that was true one edit ago.
  const invalidateBillReports = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['site-inventory', 'position-coverage', projectId] });
    qc.invalidateQueries({ queryKey: ['site-inventory', 'unfixed-value', projectId] });
  }, [qc, projectId]);

  const itemMut = useMutation({
    mutationFn: (data: StockItemCreate) => createItem(projectId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['site-inventory', 'items', projectId] });
      invalidateBillReports();
      setShowItemModal(false);
      addToast({
        type: 'success',
        title: t('site_inventory.item_created', { defaultValue: 'Item created' }),
      });
    },
    onError: toastError,
  });

  const linkMut = useMutation({
    mutationFn: ({ itemId, data }: { itemId: string; data: StockItemUpdate }) =>
      updateItem(projectId, itemId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['site-inventory', 'items', projectId] });
      invalidateBillReports();
      setLinkTarget(null);
      addToast({
        type: 'success',
        title: t('site_inventory.link_saved', { defaultValue: 'Bill link updated' }),
      });
    },
    onError: toastError,
  });

  const movementMut = useMutation({
    mutationFn: (data: MovementCreate) => recordMovement(projectId, data),
    onSuccess: () => {
      // Recording a movement changes the balance, so refresh the ledger AND the
      // derived stock-on-hand view together so the "on hand" numbers stay live.
      qc.invalidateQueries({ queryKey: ['site-inventory', 'movements', projectId] });
      qc.invalidateQueries({ queryKey: ['site-inventory', 'stock-on-hand', projectId] });
      invalidateBillReports();
      setShowMovementModal(false);
      addToast({
        type: 'success',
        title: t('site_inventory.movement_recorded', { defaultValue: 'Movement recorded' }),
      });
    },
    onError: toastError,
  });

  /* -- Delete ------------------------------------------------------------- */
  // What holds the row somebody asked to delete. Asked once that row is named
  // rather than per table row, so listing items and locations costs nothing
  // extra. The one answer writes both the sentence before the delete and the
  // sentence after a refused one, so the two cannot tell different stories.
  const holdersQuery = useQuery({
    queryKey: [
      'site-inventory',
      'delete-holders',
      projectId,
      deleteTarget?.kind ?? '',
      deleteTarget?.id ?? '',
    ],
    queryFn: () => probeHolders(projectId, deleteTarget as DeleteTarget, items),
    enabled: !!projectId && !!deleteTarget,
    // The app's defaults hold a query fresh for 30s and cached for 5 minutes,
    // which is right for a table and wrong for this. Reopening the dialog on
    // the same row inside that window would answer from the cache, and the
    // answer decides whether an irreversible action is offered: a movement
    // booked by somebody else in between would not be counted, and the dialog
    // would say nothing depends on the row while something already did. Ask
    // every time, and keep nothing once the dialog closes.
    staleTime: 0,
    gcTime: 0,
  });

  const closeDelete = useCallback(() => {
    setDeleteTarget(null);
    setRefusedHolders(null);
  }, []);

  const deleteMut = useMutation({
    mutationFn: (target: DeleteTarget) =>
      target.kind === 'item'
        ? deleteItem(projectId, target.id)
        : deleteLocation(projectId, target.id),
    onSuccess: (_result, target) => {
      if (target.kind === 'item') {
        qc.invalidateQueries({ queryKey: ['site-inventory', 'items', projectId] });
        qc.invalidateQueries({ queryKey: ['site-inventory', 'stock-on-hand', projectId] });
        invalidateBillReports();
      } else {
        qc.invalidateQueries({ queryKey: ['site-inventory', 'locations', projectId] });
      }
      closeDelete();
      addToast({
        type: 'success',
        title:
          target.kind === 'item'
            ? t('site_inventory.item_deleted', { defaultValue: 'Stock item deleted' })
            : t('site_inventory.location_deleted', { defaultValue: 'Storage location deleted' }),
      });
    },
    onError: async (err) => {
      // A 409 here is the guard doing its job, not a failure: something came to
      // hold the row between the check and the button. Ask again so the reason
      // can be named in the reader's language - the server's own answer is one
      // English sentence it composed, which is the thing this must not show.
      if (err instanceof ApiError && err.status === 409) {
        const fresh = await holdersQuery.refetch();
        setRefusedHolders(fresh.data ?? []);
        return;
      }
      toastError(err);
    },
  });

  // "Not fetching" is not the same as "answered": between the target being
  // named and the request going out there is a render with no data and no
  // fetch in flight, and treating that as an answer would flash the sentence
  // saying nothing holds this row before anything had been checked.
  const holdersKnown = !holdersQuery.isFetching && holdersQuery.data !== undefined;
  const probingHolders = deleteTarget !== null && !holdersKnown && !holdersQuery.isError;
  // Refused either because the server said so, or because the check already
  // named a holder - in which case there is nothing to confirm and no request
  // worth sending. While the check is in flight, or if it failed, neither is
  // claimed: the dialog says so and the server stays the one that decides.
  const deleteRefused =
    refusedHolders !== null || (holdersKnown && (holdersQuery.data?.length ?? 0) > 0);
  const shownHolders = refusedHolders ?? holdersQuery.data ?? [];

  // Four things the confirmation can honestly say, and it has to say the right
  // one. The removable wording is the point of the whole dialog: it names the
  // reason this row may go, so "delete" is a decision rather than a gamble.
  let deleteMessage = '';
  const deleteName = deleteTarget?.name ?? '';
  if (probingHolders) {
    deleteMessage = t('site_inventory.delete_checking', {
      defaultValue: 'Checking what depends on {{name}}...',
      name: deleteName,
    });
  } else if (holdersQuery.isError) {
    deleteMessage = t('site_inventory.delete_check_failed', {
      defaultValue:
        'What depends on {{name}} could not be checked from here. The server checks again before it removes anything, and refuses if something still points at it.',
      name: deleteName,
    });
  } else if (deleteTarget?.kind === 'location') {
    deleteMessage = t('site_inventory.delete_location_free', {
      defaultValue:
        'No movement names {{name}}, no stock is standing there and no item defaults to it, so nothing is lost with it. Deleting it cannot be undone.',
      name: deleteName,
    });
  } else {
    deleteMessage = t('site_inventory.delete_item_free', {
      defaultValue:
        'Nothing has ever been booked against {{name}}, so there is no movement history to lose with it. Deleting it cannot be undone.',
      name: deleteName,
    });
  }

  /* -- Tabs --------------------------------------------------------------- */
  const countBadge = (n: number) =>
    n > 0 ? (
      <span className="rounded-full bg-surface-secondary px-1.5 text-2xs text-content-tertiary">
        {n}
      </span>
    ) : undefined;

  const tabs = [
    {
      id: 'stock' as const,
      label: t('site_inventory.tab_stock', { defaultValue: 'Stock on hand' }),
      icon: <Boxes size={15} />,
    },
    {
      id: 'bill' as const,
      label: t('site_inventory.tab_bill', { defaultValue: 'Against the bill' }),
      icon: <Receipt size={15} />,
      badge: countBadge(coverageQuery.data?.position_count ?? 0),
    },
    {
      id: 'movements' as const,
      label: t('site_inventory.tab_movements', { defaultValue: 'Movements' }),
      icon: <ArrowLeftRight size={15} />,
      badge: countBadge(movements.length),
    },
    {
      id: 'items' as const,
      label: t('site_inventory.tab_items', { defaultValue: 'Items' }),
      icon: <Package size={15} />,
      badge: countBadge(items.length),
    },
    {
      id: 'locations' as const,
      label: t('site_inventory.tab_locations', { defaultValue: 'Locations' }),
      icon: <Warehouse size={15} />,
      badge: countBadge(locations.length),
    },
  ];

  const headerAction =
    activeTab === 'items' ? (
      <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={() => setShowItemModal(true)}>
        {t('site_inventory.new_item', { defaultValue: 'New item' })}
      </Button>
    ) : activeTab === 'locations' ? (
      <Button
        variant="primary"
        size="sm"
        icon={<Plus size={14} />}
        onClick={() => setShowLocationModal(true)}
      >
        {t('site_inventory.new_location', { defaultValue: 'New location' })}
      </Button>
    ) : (
      <Button
        variant="primary"
        size="sm"
        icon={<Plus size={14} />}
        onClick={() => setShowMovementModal(true)}
        disabled={items.length === 0}
        title={
          items.length === 0
            ? t('site_inventory.add_item_first', {
                defaultValue: 'Add a stock item before recording a movement',
              })
            : undefined
        }
      >
        {t('site_inventory.record_movement', { defaultValue: 'Record movement' })}
      </Button>
    );

  return (
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('site_inventory.title', { defaultValue: 'Site Inventory' })}
        subtitle={t('site_inventory.subtitle', {
          defaultValue: 'Track on-site material stock, storage locations and every stock movement',
        })}
        actions={
          <>
            <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
            {headerAction}
          </>
        }
      />

      <InsightsPanel
        open={insights.open}
        title={t('site_inventory.insights.title', { defaultValue: 'Inventory insights' })}
        datasets={insightDatasets}
        builtins={insightBuiltins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
      />

      <RequiresProject
        emptyHint={t('site_inventory.select_project', {
          defaultValue: 'Open a project first to view and manage site inventory.',
        })}
      >
        <TabBar<TabId>
          tabs={tabs}
          activeId={activeTab}
          onChange={(id) => setActiveTab(id)}
          ariaLabel={t('site_inventory.tabs_aria', { defaultValue: 'Site inventory sections' })}
          variant="underline"
        />

        <div role="tabpanel">
          {activeTab === 'stock' && (
            <StockPanel
              query={stockQuery}
              rows={stockRows}
              summary={stockSummary}
              status={balanceStatus}
            />
          )}
          {activeTab === 'movements' && (
            <MovementsPanel
              query={movementsQuery}
              movements={movements}
              itemName={itemName}
              itemsById={itemsById}
              locName={locName}
              onRecord={() => setShowMovementModal(true)}
              canRecord={items.length > 0}
            />
          )}
          {activeTab === 'bill' && (
            <BillPanel
              coverageQuery={coverageQuery}
              valueQuery={unfixedValueQuery}
              coverage={coverageQuery.data}
              value={unfixedValueQuery.data}
            />
          )}
          {activeTab === 'items' && (
            <ItemsPanel
              query={itemsQuery}
              items={items}
              onCreate={() => setShowItemModal(true)}
              onLink={setLinkTarget}
              onDelete={(it) => setDeleteTarget({ kind: 'item', id: it.id, name: it.name })}
            />
          )}
          {activeTab === 'locations' && (
            <LocationsPanel
              query={locationsQuery}
              locations={locations}
              onCreate={() => setShowLocationModal(true)}
              onDelete={(loc) =>
                setDeleteTarget({ kind: 'location', id: loc.id, name: loc.name })
              }
            />
          )}
        </div>
      </RequiresProject>

      {linkTarget !== null && (
        <BoqPositionPickerDialog
          projectId={projectId}
          onClose={() => setLinkTarget(null)}
          onPick={(pick) =>
            linkMut.mutate({ itemId: linkTarget.id, data: { boq_position_id: pick.id } })
          }
        />
      )}
      {showMovementModal && (
        <RecordMovementModal
          items={items}
          locations={locations}
          projectId={projectId}
          onClose={() => setShowMovementModal(false)}
          onSubmit={(data) => movementMut.mutate(data)}
          isPending={movementMut.isPending}
        />
      )}
      {showItemModal && (
        <CreateItemModal
          locations={locations}
          projectId={projectId}
          onClose={() => setShowItemModal(false)}
          onSubmit={(data) => itemMut.mutate(data)}
          isPending={itemMut.isPending}
        />
      )}
      {showLocationModal && (
        <CreateLocationModal
          onClose={() => setShowLocationModal(false)}
          onSubmit={(data) => locationMut.mutate(data)}
          isPending={locationMut.isPending}
        />
      )}
      {deleteTarget !== null && !deleteRefused && (
        <ConfirmDialog
          open
          title={
            deleteTarget.kind === 'location'
              ? t('site_inventory.delete_location_title', {
                  defaultValue: 'Delete this storage location?',
                })
              : t('site_inventory.delete_item_title', { defaultValue: 'Delete this stock item?' })
          }
          message={deleteMessage}
          loading={probingHolders || deleteMut.isPending}
          onConfirm={() => deleteMut.mutate(deleteTarget)}
          onCancel={closeDelete}
        />
      )}
      {deleteTarget !== null && deleteRefused && (
        <Modal
          title={t('site_inventory.delete_blocked_title', {
            defaultValue: 'This cannot be deleted',
          })}
          onClose={closeDelete}
          maxWidth="max-w-md"
          footer={
            <Button variant="secondary" onClick={closeDelete}>
              {t('site_inventory.close', { defaultValue: 'Close' })}
            </Button>
          }
        >
          <div className="flex gap-3">
            <AlertTriangle size={20} className="mt-0.5 shrink-0 text-semantic-warning" />
            <div className="space-y-2">
              <p className="text-sm text-content-primary">
                {shownHolders.length > 0
                  ? t('site_inventory.delete_blocked', {
                      defaultValue:
                        '{{name}} is referenced by {{holders}}. Deleting it would take that record away with it, so it is kept.',
                      name: deleteTarget.name,
                      holders: holderList(shownHolders, t),
                    })
                  : t('site_inventory.delete_blocked_unnamed', {
                      defaultValue:
                        'Something now points at {{name}}. Deleting it would take that record away with it, so it is kept.',
                      name: deleteTarget.name,
                    })}
              </p>
              <p className="text-sm text-content-secondary">
                {deleteTarget.kind === 'location'
                  ? t('site_inventory.delete_blocked_location_advice', {
                      defaultValue:
                        'Transfer the stock out and repoint the items that default to it, or clear the Active flag so this location stops being offered while its movement history stays readable.',
                    })
                  : t('site_inventory.delete_blocked_item_advice', {
                      defaultValue:
                        'The movement ledger is the record of what arrived and what was installed. Clear the Active flag instead, so the item stops being offered on new movements and its history stays readable.',
                    })}
              </p>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

/* -- Panels ---------------------------------------------------------------- */

interface QueryLike {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => void;
}

const thCls = 'px-4 py-2.5 text-left font-medium';
const tdCls = 'px-4 py-3 text-content-primary';

const STATUS_BADGE: Record<BalanceStatus, { variant: BadgeVariant; key: string; def: string }> = {
  negative: { variant: 'error', key: 'site_inventory.status_negative', def: 'Negative' },
  low: { variant: 'warning', key: 'site_inventory.status_low', def: 'Low stock' },
  ok: { variant: 'success', key: 'site_inventory.status_ok', def: 'In stock' },
};

function StockPanel({
  query,
  rows,
  summary,
  status,
}: {
  query: QueryLike;
  rows: StockOnHandRow[];
  summary: { tracked: number; low: number; negative: number };
  status: (row: StockOnHandRow) => BalanceStatus;
}) {
  const { t } = useTranslation();
  if (query.isLoading) return <SkeletonTable rows={5} columns={4} />;
  if (query.isError) return <InlineError error={query.error} onRetry={query.refetch} />;
  if (rows.length === 0) {
    return (
      <EmptyState
        icon={<Boxes size={28} strokeWidth={1.5} />}
        title={t('site_inventory.no_stock', { defaultValue: 'No stock on hand yet' })}
        description={t('site_inventory.no_stock_hint', {
          defaultValue: 'Record an inbound movement to start metering material stock.',
        })}
      />
    );
  }

  const chips: { key: string; def: string; value: number; tone: string }[] = [
    { key: 'site_inventory.stat_tracked', def: 'Items tracked', value: summary.tracked, tone: 'text-content-primary' },
    { key: 'site_inventory.stat_low', def: 'Low stock', value: summary.low, tone: 'text-amber-500' },
    { key: 'site_inventory.stat_negative', def: 'Negative', value: summary.negative, tone: 'text-semantic-error' },
  ];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        {chips.map((c) => (
          <div key={c.key} className="rounded-xl border border-border-light bg-surface-elevated/90 p-4">
            <p className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
              {t(c.key, { defaultValue: c.def })}
            </p>
            <p className={clsx('text-lg font-semibold mt-1 tabular-nums', c.tone)}>{c.value}</p>
          </div>
        ))}
      </div>
      <Card padding="none" className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light bg-surface-secondary/30 text-2xs uppercase tracking-wider text-content-tertiary">
              <th className={thCls}>{t('site_inventory.col_item', { defaultValue: 'Item' })}</th>
              <th className={thCls}>{t('site_inventory.col_unit', { defaultValue: 'Unit' })}</th>
              <th className={clsx(thCls, 'text-right')}>
                {t('site_inventory.col_on_hand', { defaultValue: 'On hand' })}
              </th>
              <th className={clsx(thCls, 'text-center')}>
                {t('site_inventory.col_status', { defaultValue: 'Status' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const st = status(row);
              const badge = STATUS_BADGE[st];
              return (
                <tr
                  key={row.item_id}
                  className="border-b border-border-light last:border-0 hover:bg-surface-secondary/40"
                >
                  <td className={clsx(tdCls, 'font-medium')}>{row.name}</td>
                  <td className={clsx(tdCls, 'text-content-tertiary')}>{row.unit || '-'}</td>
                  <td
                    className={clsx(
                      tdCls,
                      'text-right tabular-nums font-semibold',
                      st === 'negative' && 'text-semantic-error',
                    )}
                  >
                    {row.on_hand}
                  </td>
                  <td className={clsx(tdCls, 'text-center')}>
                    <Badge variant={badge.variant} size="sm" dot>
                      {t(badge.key, { defaultValue: badge.def })}
                    </Badge>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function MovementsPanel({
  query,
  movements,
  itemName,
  itemsById,
  locName,
  onRecord,
  canRecord,
}: {
  query: QueryLike;
  movements: StockMovement[];
  itemName: (id: string) => string;
  itemsById: Map<string, StockItem>;
  locName: (id: string | null) => string;
  onRecord: () => void;
  canRecord: boolean;
}) {
  const { t } = useTranslation();
  if (query.isLoading) return <SkeletonTable rows={5} columns={6} />;
  if (query.isError) return <InlineError error={query.error} onRetry={query.refetch} />;
  if (movements.length === 0) {
    return (
      <EmptyState
        icon={<ArrowLeftRight size={28} strokeWidth={1.5} />}
        title={t('site_inventory.no_movements', { defaultValue: 'No movements yet' })}
        description={t('site_inventory.no_movements_hint', {
          defaultValue: 'Record the first stock movement to build the ledger.',
        })}
        action={
          canRecord
            ? {
                label: t('site_inventory.record_movement', { defaultValue: 'Record movement' }),
                onClick: onRecord,
              }
            : undefined
        }
      />
    );
  }

  return (
    <Card padding="none" className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border-light bg-surface-secondary/30 text-2xs uppercase tracking-wider text-content-tertiary">
            <th className={thCls}>{t('site_inventory.col_date', { defaultValue: 'Date' })}</th>
            <th className={thCls}>{t('site_inventory.col_type', { defaultValue: 'Type' })}</th>
            <th className={thCls}>{t('site_inventory.col_item', { defaultValue: 'Item' })}</th>
            <th className={clsx(thCls, 'text-right')}>
              {t('site_inventory.col_quantity', { defaultValue: 'Quantity' })}
            </th>
            <th className={thCls}>{t('site_inventory.col_location', { defaultValue: 'Location' })}</th>
            <th className={thCls}>{t('site_inventory.col_note', { defaultValue: 'Note' })}</th>
          </tr>
        </thead>
        <tbody>
          {movements.map((m) => {
            const cfg = MOVEMENT_TYPE_CONFIG[m.movement_type];
            const Icon = cfg.icon;
            const unit = itemsById.get(m.item_id)?.unit ?? '';
            const locationCell =
              m.movement_type === 'TRANSFER' && m.to_location_id
                ? t('site_inventory.transfer_route', {
                    defaultValue: '{{from}} to {{to}}',
                    from: locName(m.location_id),
                    to: locName(m.to_location_id),
                  })
                : locName(m.location_id) || '-';
            return (
              <tr
                key={m.id}
                className="border-b border-border-light last:border-0 hover:bg-surface-secondary/40"
              >
                <td className={clsx(tdCls, 'whitespace-nowrap text-content-tertiary')}>
                  <DateDisplay value={m.occurred_at} />
                </td>
                <td className={tdCls}>
                  <Badge variant={cfg.variant} size="sm">
                    <Icon size={12} className="mr-1" />
                    {t(`site_inventory.movement_type_${m.movement_type.toLowerCase()}`, {
                      defaultValue: MOVEMENT_TYPE_LABEL[m.movement_type],
                    })}
                  </Badge>
                </td>
                <td className={clsx(tdCls, 'font-medium')}>{itemName(m.item_id)}</td>
                <td className={clsx(tdCls, 'text-right tabular-nums')}>
                  {m.quantity}
                  {unit ? ` ${unit}` : ''}
                </td>
                <td className={clsx(tdCls, 'text-content-tertiary')}>{locationCell}</td>
                <td className={clsx(tdCls, 'text-content-tertiary max-w-[16rem] truncate')}>
                  {m.note || '-'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Card>
  );
}

function ItemsPanel({
  query,
  items,
  onCreate,
  onLink,
  onDelete,
}: {
  query: QueryLike;
  items: StockItem[];
  onCreate: () => void;
  onLink: (item: StockItem) => void;
  onDelete: (item: StockItem) => void;
}) {
  const { t } = useTranslation();
  if (query.isLoading) return <SkeletonTable rows={5} columns={6} />;
  if (query.isError) return <InlineError error={query.error} onRetry={query.refetch} />;
  if (items.length === 0) {
    return (
      <EmptyState
        icon={<Package size={28} strokeWidth={1.5} />}
        title={t('site_inventory.no_items', { defaultValue: 'No stock items yet' })}
        description={t('site_inventory.no_items_hint', {
          defaultValue: 'Add the materials you want to meter on site.',
        })}
        action={{
          label: t('site_inventory.new_item', { defaultValue: 'New item' }),
          onClick: onCreate,
        }}
      />
    );
  }

  return (
    <Card padding="none" className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border-light bg-surface-secondary/30 text-2xs uppercase tracking-wider text-content-tertiary">
            <th className={thCls}>{t('site_inventory.col_item', { defaultValue: 'Item' })}</th>
            <th className={thCls}>{t('site_inventory.col_sku', { defaultValue: 'SKU' })}</th>
            <th className={thCls}>{t('site_inventory.col_unit', { defaultValue: 'Unit' })}</th>
            <th className={thCls}>
              {t('site_inventory.col_bill_position', { defaultValue: 'Bill position' })}
            </th>
            <th className={clsx(thCls, 'text-right')}>
              {t('site_inventory.col_unit_cost', { defaultValue: 'Unit cost' })}
            </th>
            <th className={clsx(thCls, 'text-right')}>
              {t('site_inventory.col_reorder', { defaultValue: 'Reorder point' })}
            </th>
            <th className={clsx(thCls, 'text-center')}>
              {t('site_inventory.col_active', { defaultValue: 'Active' })}
            </th>
            <th className={clsx(thCls, 'text-right')}>
              {t('site_inventory.col_actions', { defaultValue: 'Actions' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => (
            <tr
              key={it.id}
              className="border-b border-border-light last:border-0 hover:bg-surface-secondary/40"
            >
              <td className={clsx(tdCls, 'font-medium')}>{it.name}</td>
              <td className={clsx(tdCls, 'text-content-tertiary')}>{it.sku || '-'}</td>
              <td className={clsx(tdCls, 'text-content-tertiary')}>{it.unit || '-'}</td>
              <td className={tdCls}>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Link2 size={13} />}
                  onClick={() => onLink(it)}
                  className={clsx(!it.boq_position_id && 'text-content-tertiary')}
                >
                  {it.boq_position_id
                    ? t('site_inventory.position_linked', { defaultValue: 'Linked' })
                    : t('site_inventory.link_position', { defaultValue: 'Link to bill' })}
                </Button>
              </td>
              <td className={clsx(tdCls, 'text-right tabular-nums')}>
                {it.standard_unit_cost
                  ? formatCurrency(it.standard_unit_cost, it.currency || undefined)
                  : '-'}
              </td>
              <td className={clsx(tdCls, 'text-right tabular-nums')}>{it.reorder_point ?? '-'}</td>
              <td className={clsx(tdCls, 'text-center')}>
                <Badge variant={it.is_active ? 'success' : 'neutral'} size="sm">
                  {it.is_active
                    ? t('site_inventory.active_yes', { defaultValue: 'Yes' })
                    : t('site_inventory.active_no', { defaultValue: 'No' })}
                </Badge>
              </td>
              <td className={clsx(tdCls, 'text-right')}>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Trash2 size={13} />}
                  onClick={() => onDelete(it)}
                  aria-label={t('site_inventory.delete_aria', {
                    defaultValue: 'Delete {{name}}',
                    name: it.name,
                  })}
                  title={t('site_inventory.delete', { defaultValue: 'Delete' })}
                  className="text-content-tertiary hover:text-semantic-error"
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

/* -- Against the bill ------------------------------------------------------ */

/** Render a quantity through the platform's number formatting. A dash where
 *  there is no number, never a bare "null" and never a hardcoded locale. */
function qty(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '-';
  return formatValue(toNumber(value), 'number', { maximumFractionDigits: 3 });
}

/** A percentage, or a dash when the comparison behind it was withheld. */
function pct(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '-';
  return formatValue(toNumber(value), 'percent');
}

/** The note that replaces a withheld comparison, so an empty cell is never
 *  read as a zero. A mismatch is a warning; an unknown is a gap to fill in. */
function UnitNote({
  agreement,
  billUnit,
  inventoryUnit,
}: {
  agreement: UnitAgreement;
  billUnit: string;
  inventoryUnit: string;
}) {
  const { t } = useTranslation();
  if (agreement === 'match') return null;
  if (agreement === 'mismatch') {
    return (
      <Badge variant="warning" size="sm">
        {t('site_inventory.unit_mismatch_badge', {
          defaultValue: '{{billUnit}} vs {{inventoryUnit}}',
          billUnit: billUnit || '?',
          inventoryUnit: inventoryUnit || '?',
        })}
      </Badge>
    );
  }
  return (
    <Badge variant="neutral" size="sm">
      {t('site_inventory.unit_unknown_badge', { defaultValue: 'Unit not stated' })}
    </Badge>
  );
}

/**
 * The screen the link buys. Per bill position: how much was ordered, how much
 * has landed, how much is installed and how much is still to arrive - plus the
 * value of everything standing on site unfixed.
 *
 * Every comparison is unit-gated by the backend; a withheld figure arrives as
 * null and is rendered as a dash next to a badge naming the two units, so the
 * reader can see the comparison was refused rather than reading an empty cell
 * as a zero.
 */
function BillPanel({
  coverageQuery,
  valueQuery,
  coverage,
  value,
}: {
  coverageQuery: QueryLike;
  valueQuery: QueryLike;
  coverage: PositionCoverageResponse | undefined;
  value: UnfixedValueResponse | undefined;
}) {
  const { t } = useTranslation();
  if (coverageQuery.isLoading || valueQuery.isLoading) return <SkeletonTable rows={6} columns={7} />;
  if (coverageQuery.isError) {
    return <InlineError error={coverageQuery.error} onRetry={coverageQuery.refetch} />;
  }
  if (valueQuery.isError) {
    return <InlineError error={valueQuery.error} onRetry={valueQuery.refetch} />;
  }

  const lines: PositionCoverageRow[] = coverage?.lines ?? [];
  const totals = value?.totals_by_currency ?? [];
  const unvalued = value?.unvalued_item_count ?? 0;

  if (lines.length === 0) {
    return (
      <EmptyState
        icon={<Receipt size={28} strokeWidth={1.5} />}
        title={t('site_inventory.no_bill_links', { defaultValue: 'No stock is linked to the bill yet' })}
        description={t('site_inventory.no_bill_links_hint', {
          defaultValue:
            'Open a stock item and link it to the position that priced it. This page then shows what is still to arrive and what the material on site is worth.',
        })}
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Card padding="sm">
          <p className="text-2xs uppercase tracking-wider text-content-tertiary">
            {t('site_inventory.kpi_unfixed_value', { defaultValue: 'Value on site, unfixed' })}
          </p>
          {totals.length === 0 ? (
            <p className="mt-1 text-lg font-semibold text-content-tertiary">-</p>
          ) : (
            // Never blended: two currencies have no common sum, so each is
            // printed on its own line rather than added into one figure.
            <div className="mt-1 space-y-0.5">
              {totals.map((tot) => (
                <p key={tot.currency} className="text-lg font-semibold tabular-nums">
                  {formatCurrency(tot.value, tot.currency)}
                </p>
              ))}
            </div>
          )}
          {unvalued > 0 && (
            // Deliberately not an i18next `count` key: that would demand a
            // plural form per language, and the phrasing below reads correctly
            // for one item and for many without one.
            <p className="mt-1 text-xs text-content-tertiary">
              {t('site_inventory.unvalued_items', {
                defaultValue: 'Items with no price, not included: {{itemCount}}',
                itemCount: formatValue(unvalued, 'number', { maximumFractionDigits: 0 }),
              })}
            </p>
          )}
        </Card>
        <Card padding="sm">
          <p className="text-2xs uppercase tracking-wider text-content-tertiary">
            {t('site_inventory.kpi_linked_positions', { defaultValue: 'Positions with stock' })}
          </p>
          <p className="mt-1 text-lg font-semibold tabular-nums">
            {formatValue(coverage?.position_count ?? 0, 'number', { maximumFractionDigits: 0 })}
          </p>
        </Card>
        <Card padding="sm">
          <p className="text-2xs uppercase tracking-wider text-content-tertiary">
            {t('site_inventory.kpi_unit_mismatch', { defaultValue: 'Unit mismatches' })}
          </p>
          <p className="mt-1 text-lg font-semibold tabular-nums">
            {formatValue(coverage?.unmatched_unit_count ?? 0, 'number', { maximumFractionDigits: 0 })}
          </p>
          <p className="mt-1 text-xs text-content-tertiary">
            {t('site_inventory.kpi_unit_mismatch_hint', {
              defaultValue: 'Quantities are not compared where the bill and the store disagree.',
            })}
          </p>
        </Card>
      </div>

      <Card padding="none" className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light bg-surface-secondary/30 text-2xs uppercase tracking-wider text-content-tertiary">
              <th className={thCls}>{t('site_inventory.col_position', { defaultValue: 'Position' })}</th>
              <th className={clsx(thCls, 'text-right')}>
                {t('site_inventory.col_bill_qty', { defaultValue: 'In the bill' })}
              </th>
              <th className={clsx(thCls, 'text-right')}>
                {t('site_inventory.col_ordered', { defaultValue: 'Ordered' })}
              </th>
              <th className={clsx(thCls, 'text-right')}>
                {t('site_inventory.col_delivered', { defaultValue: 'Delivered' })}
              </th>
              <th className={clsx(thCls, 'text-right')}>
                {t('site_inventory.col_outstanding', { defaultValue: 'Still to arrive' })}
              </th>
              <th className={clsx(thCls, 'text-right')}>
                {t('site_inventory.col_on_site', { defaultValue: 'On site, unfixed' })}
              </th>
              <th className={clsx(thCls, 'text-right')}>
                {t('site_inventory.col_installed_pct', { defaultValue: 'Installed' })}
              </th>
            </tr>
          </thead>
          <tbody>
            {lines.map((line) => (
              <tr
                key={line.position_id}
                className="border-b border-border-light last:border-0 hover:bg-surface-secondary/40"
              >
                <td className={tdCls}>
                  <div className="flex flex-col gap-1">
                    <span className="font-medium">
                      {line.ordinal ? `${line.ordinal} ` : ''}
                      {line.description ||
                        t('site_inventory.position_unnamed', { defaultValue: 'Bill position' })}
                    </span>
                    <UnitNote
                      agreement={line.bill_unit_agreement}
                      billUnit={line.bill_unit}
                      inventoryUnit={line.inventory_unit}
                    />
                  </div>
                </td>
                <td className={clsx(tdCls, 'text-right tabular-nums')}>
                  {qty(line.bill_quantity)}
                  {line.bill_unit && (
                    <span className="ml-1 text-2xs text-content-tertiary">{line.bill_unit}</span>
                  )}
                </td>
                <td className={clsx(tdCls, 'text-right tabular-nums')}>{qty(line.ordered_quantity)}</td>
                <td className={clsx(tdCls, 'text-right tabular-nums')}>{qty(line.delivered_quantity)}</td>
                <td
                  className={clsx(
                    tdCls,
                    'text-right tabular-nums',
                    toNumber(line.outstanding_quantity) > 0 && 'text-semantic-warning',
                  )}
                >
                  {qty(line.outstanding_quantity)}
                </td>
                <td className={clsx(tdCls, 'text-right tabular-nums')}>{qty(line.on_hand_quantity)}</td>
                <td className={clsx(tdCls, 'text-right tabular-nums')}>{pct(line.installed_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </div>
  );
}

function LocationsPanel({
  query,
  locations,
  onCreate,
  onDelete,
}: {
  query: QueryLike;
  locations: StockLocation[];
  onCreate: () => void;
  onDelete: (location: StockLocation) => void;
}) {
  const { t } = useTranslation();
  if (query.isLoading) return <SkeletonTable rows={4} columns={4} />;
  if (query.isError) return <InlineError error={query.error} onRetry={query.refetch} />;
  if (locations.length === 0) {
    return (
      <EmptyState
        icon={<Warehouse size={28} strokeWidth={1.5} />}
        title={t('site_inventory.no_locations', { defaultValue: 'No storage locations yet' })}
        description={t('site_inventory.no_locations_hint', {
          defaultValue: 'Add a yard, container or store so stock can be located.',
        })}
        action={{
          label: t('site_inventory.new_location', { defaultValue: 'New location' }),
          onClick: onCreate,
        }}
      />
    );
  }

  return (
    <Card padding="none" className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border-light bg-surface-secondary/30 text-2xs uppercase tracking-wider text-content-tertiary">
            <th className={thCls}>{t('site_inventory.col_name', { defaultValue: 'Name' })}</th>
            <th className={thCls}>{t('site_inventory.col_code', { defaultValue: 'Code' })}</th>
            <th className={thCls}>{t('site_inventory.col_address', { defaultValue: 'Address' })}</th>
            <th className={clsx(thCls, 'text-center')}>
              {t('site_inventory.col_active', { defaultValue: 'Active' })}
            </th>
            <th className={clsx(thCls, 'text-right')}>
              {t('site_inventory.col_actions', { defaultValue: 'Actions' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {locations.map((loc) => (
            <tr
              key={loc.id}
              className="border-b border-border-light last:border-0 hover:bg-surface-secondary/40"
            >
              <td className={clsx(tdCls, 'font-medium')}>{loc.name}</td>
              <td className={clsx(tdCls, 'text-content-tertiary')}>{loc.code || '-'}</td>
              <td className={clsx(tdCls, 'text-content-tertiary')}>{loc.address || '-'}</td>
              <td className={clsx(tdCls, 'text-center')}>
                <Badge variant={loc.is_active ? 'success' : 'neutral'} size="sm">
                  {loc.is_active
                    ? t('site_inventory.active_yes', { defaultValue: 'Yes' })
                    : t('site_inventory.active_no', { defaultValue: 'No' })}
                </Badge>
              </td>
              <td className={clsx(tdCls, 'text-right')}>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Trash2 size={13} />}
                  onClick={() => onDelete(loc)}
                  aria-label={t('site_inventory.delete_aria', {
                    defaultValue: 'Delete {{name}}',
                    name: loc.name,
                  })}
                  title={t('site_inventory.delete', { defaultValue: 'Delete' })}
                  className="text-content-tertiary hover:text-semantic-error"
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
