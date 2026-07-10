// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Resource prices panel.
//
// A coefficient cost base (Vietnam Dinh Muc = VN_NATIONAL, Indonesia AHSP =
// ID_NATIONAL) lists every work item's resources as quantities but carries no
// prices, so each item's rate is 0 until a user supplies local resource prices.
// This panel lets an estimator do exactly that: see coverage (how many
// resources are priced), edit prices inline, save them, then preview and apply
// a re-price that turns the base into usable rates.
//
// Money: `unit_price` is a decimal STRING end to end. It is shown as-is and
// sent back as a string - never Number()-parsed for storage.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  AlertTriangle,
  Calculator,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Coins,
  Info,
  RefreshCw,
  Save,
  Search,
  Wallet,
} from 'lucide-react';

import { Badge, Button, Card, CountryFlag, EmptyState } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { REGION_MAP } from '@/stores/useCostDatabaseStore';
import {
  useBulkSetResourcePrices,
  useRepriceRegion,
  useResourcePricesQuery,
  useResourcePriceStatsQuery,
  useSeedResourcePrices,
  type ResourcePriceBulkItem,
  type ResourcePriceListParams,
  type ResourcePriceRow,
  type ResourceType,
} from './useResourcePrices';

/* ── Constants ───────────────────────────────────────────────────────────── */

/** Bases that ship as pure coefficients and need local prices to be usable. */
const COEFFICIENT_REGIONS = ['VN_NATIONAL', 'ID_NATIONAL'] as const;
const DEFAULT_REGION: string = COEFFICIENT_REGIONS[0];

const RESOURCE_TYPES: ResourceType[] = [
  'labor',
  'material',
  'equipment',
  'operator',
  'electricity',
  'other',
];

const PAGE_SIZE = 50;

type PillVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

/* ── Money-string helpers (no Number() coercion for storage) ─────────────── */

/** True when the string is a valid non-negative decimal (digits, one dot). */
function isValidPriceString(value: string): boolean {
  const trimmed = value.trim();
  return trimmed.length > 0 && /^\d+(\.\d+)?$/.test(trimmed);
}

/** True when the string represents zero (or is empty) - used only to decide
 *  how to highlight a row, never for storage. */
function isZeroPriceString(value: string): boolean {
  const trimmed = value.trim();
  if (trimmed.length === 0) return true;
  return /^0*(\.0*)?$/.test(trimmed);
}

/* ── Per-region edit buffer ──────────────────────────────────────────────── */

interface PendingEdit {
  value: string;
  original: string;
  currency: string;
  unit: string;
  resource_name: string;
  resource_type: string;
}

/* ── Component ───────────────────────────────────────────────────────────── */

export interface ResourcePriceSheetPanelProps {
  /** When set, the panel prices this region and hides the base selector.
   *  When omitted, the user picks among the coefficient bases. */
  region?: string;
  className?: string;
}

export function ResourcePriceSheetPanel({
  region: controlledRegion,
  className,
}: ResourcePriceSheetPanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [internalRegion, setInternalRegion] = useState<string>(
    controlledRegion ?? DEFAULT_REGION,
  );
  const region = controlledRegion ?? internalRegion;
  const regionInfo = REGION_MAP[region];
  const currency = regionInfo?.currency ?? '';

  // Filters.
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [resourceType, setResourceType] = useState<string>('');
  const [onlyUnpriced, setOnlyUnpriced] = useState(false);
  const [page, setPage] = useState(0);

  // Unsaved price edits, keyed by resource_key so they survive pagination and
  // filtering (an edit on page 1 is still saved after you jump to page 2).
  const [pendingEdits, setPendingEdits] = useState<Map<string, PendingEdit>>(
    () => new Map(),
  );

  // Last dry-run reprice result (a preview - nothing is written yet).
  const [preview, setPreview] = useState<RepriceResponsePreview | null>(null);

  // Debounce the search box so we do not refetch on every keystroke.
  useEffect(() => {
    const id = setTimeout(() => setDebouncedSearch(search.trim()), 300);
    return () => clearTimeout(id);
  }, [search]);

  // Any filter change returns to the first page.
  useEffect(() => {
    setPage(0);
  }, [debouncedSearch, resourceType, onlyUnpriced, region]);

  // Switching base discards edits and any stale preview.
  useEffect(() => {
    setPendingEdits(new Map());
    setPreview(null);
  }, [region]);

  const listParams = useMemo<ResourcePriceListParams>(
    () => ({
      search: debouncedSearch || undefined,
      resourceType: resourceType || undefined,
      onlyUnpriced: onlyUnpriced || undefined,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    }),
    [debouncedSearch, resourceType, onlyUnpriced, page],
  );

  const statsQuery = useResourcePriceStatsQuery(region);
  const listQuery = useResourcePricesQuery(region, listParams);

  const seedMutation = useSeedResourcePrices(region);
  const bulkMutation = useBulkSetResourcePrices(region);
  const repriceMutation = useRepriceRegion(region);

  const stats = statsQuery.data ?? listQuery.data?.stats ?? null;
  const rows = listQuery.data?.rows ?? [];
  const total = listQuery.data?.total ?? 0;

  const coverage = stats?.coverage ?? 0;
  const coveragePct = Math.round(coverage * 100);

  // Derive the save payload straight from the edit buffer so it is independent
  // of which rows are currently on screen.
  const dirtyItems = useMemo<ResourcePriceBulkItem[]>(() => {
    const out: ResourcePriceBulkItem[] = [];
    for (const [key, edit] of Array.from(pendingEdits.entries())) {
      if (!isValidPriceString(edit.value)) continue;
      if (edit.value.trim() === edit.original.trim()) continue;
      out.push({
        resource_key: key,
        unit_price: edit.value.trim(),
        currency: edit.currency || undefined,
        unit: edit.unit || undefined,
        resource_name: edit.resource_name || undefined,
        resource_type: edit.resource_type || undefined,
      });
    }
    return out;
  }, [pendingEdits]);

  const dirtyCount = dirtyItems.length;

  const hasInvalidEdit = useMemo(() => {
    for (const edit of Array.from(pendingEdits.values())) {
      if (edit.value.trim() !== '' && !isValidPriceString(edit.value)) return true;
    }
    return false;
  }, [pendingEdits]);

  /* ── Handlers ──────────────────────────────────────────────────────────── */

  const handlePriceChange = useCallback(
    (row: ResourcePriceRow, value: string) => {
      // Only allow decimal input (digits and a single dot). Rejecting other
      // characters keeps the money string clean, so it never needs coercion.
      if (value !== '' && !/^\d*\.?\d*$/.test(value)) return;
      setPendingEdits((prev) => {
        const next = new Map(prev);
        next.set(row.resource_key, {
          value,
          original: row.unit_price,
          currency: row.currency,
          unit: row.unit,
          resource_name: row.resource_name,
          resource_type:
            typeof row.resource_type === 'string'
              ? row.resource_type
              : String(row.resource_type),
        });
        return next;
      });
      // Editing invalidates a stale reprice preview.
      setPreview(null);
    },
    [],
  );

  const discardEdits = useCallback(() => {
    setPendingEdits(new Map());
  }, []);

  const handleSave = useCallback(() => {
    if (dirtyItems.length === 0) return;
    bulkMutation.mutate(dirtyItems, {
      onSuccess: (res) => {
        setPendingEdits(new Map());
        setPreview(null);
        addToast({
          type: 'success',
          title: t('costs.resource_prices.saved_title', { defaultValue: 'Prices saved' }),
          message: t('costs.resource_prices.saved_msg', {
            defaultValue:
              '{{count}} resource prices updated. Preview and apply the re-price to update rates.',
            count: res.written,
          }),
        });
      },
      onError: (err) => {
        addToast({
          type: 'error',
          title: t('costs.resource_prices.save_failed', {
            defaultValue: 'Could not save prices',
          }),
          message: getErrorMessage(err),
        });
      },
    });
  }, [dirtyItems, bulkMutation, addToast, t]);

  const handleSeed = useCallback(() => {
    seedMutation.mutate(undefined, {
      onSuccess: (res) => {
        addToast({
          type: 'success',
          title: t('costs.resource_prices.sheet_built', { defaultValue: 'Price sheet ready' }),
          message: t('costs.resource_prices.sheet_built_msg', {
            defaultValue: '{{resources}} resources found, {{unpriced}} still need a price.',
            resources: res.resources,
            unpriced: res.unpriced,
          }),
        });
      },
      onError: (err) => {
        addToast({
          type: 'error',
          title: t('costs.resource_prices.seed_failed', {
            defaultValue: 'Could not build the price sheet',
          }),
          message: getErrorMessage(err),
        });
      },
    });
  }, [seedMutation, addToast, t]);

  const handlePreview = useCallback(() => {
    repriceMutation.mutate(true, {
      onSuccess: (res) => setPreview(res),
      onError: (err) => {
        addToast({
          type: 'error',
          title: t('costs.resource_prices.preview_failed', {
            defaultValue: 'Could not preview the re-price',
          }),
          message: getErrorMessage(err),
        });
      },
    });
  }, [repriceMutation, addToast, t]);

  const handleApply = useCallback(() => {
    repriceMutation.mutate(false, {
      onSuccess: (res) => {
        setPreview(null);
        addToast({
          type: 'success',
          title: t('costs.resource_prices.repriced_title', { defaultValue: 'Base re-priced' }),
          message: t('costs.resource_prices.repriced_msg', {
            defaultValue: '{{fully}} of {{total}} items are now fully priced.',
            fully: res.items_fully_priced,
            total: res.items_total,
          }),
        });
      },
      onError: (err) => {
        addToast({
          type: 'error',
          title: t('costs.resource_prices.reprice_failed', {
            defaultValue: 'Could not re-price the base',
          }),
          message: getErrorMessage(err),
        });
      },
    });
  }, [repriceMutation, addToast, t]);

  /* ── Derived render flags ──────────────────────────────────────────────── */

  const isPreviewing = repriceMutation.isPending && repriceMutation.variables === true;
  const isApplying = repriceMutation.isPending && repriceMutation.variables === false;
  const repriceDisabled = dirtyCount > 0 || repriceMutation.isPending;

  const firstLoading = listQuery.isLoading && !listQuery.data;
  const sheetEmpty = stats !== null && stats.resources === 0;

  const barTone: string =
    coverage >= 1
      ? 'bg-semantic-success'
      : coverage >= 0.5
        ? 'bg-oe-blue'
        : 'bg-semantic-warning';

  // i18n label for a resource type. Defined here so it closes over `t`
  // directly, exactly like every other t() call in the component.
  const resourceTypeLabel = (type: string): string => {
    switch (type) {
      case 'labor':
        return t('costs.resource_prices.type_labor', { defaultValue: 'Labour' });
      case 'material':
        return t('costs.resource_prices.type_material', { defaultValue: 'Material' });
      case 'equipment':
        return t('costs.resource_prices.type_equipment', { defaultValue: 'Equipment' });
      case 'operator':
        return t('costs.resource_prices.type_operator', { defaultValue: 'Operator' });
      case 'electricity':
        return t('costs.resource_prices.type_electricity', { defaultValue: 'Electricity' });
      default:
        return t('costs.resource_prices.type_other', { defaultValue: 'Other' });
    }
  };

  /* ── Render ────────────────────────────────────────────────────────────── */

  return (
    <Card padding="none" className={clsx('overflow-hidden', className)}>
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-5 pb-3">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-oe-blue text-white">
            <Wallet size={18} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-content-primary">
              {t('costs.resource_prices.title', { defaultValue: 'Resource prices' })}
            </h3>
            <p className="text-xs text-content-tertiary max-w-xl">
              {t('costs.resource_prices.subtitle', {
                defaultValue:
                  'Price these resources to turn this coefficient base into usable rates.',
              })}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {!controlledRegion && (
            <div className="flex items-center gap-1.5">
              {COEFFICIENT_REGIONS.map((code) => {
                const info = REGION_MAP[code];
                const active = region === code;
                return (
                  <button
                    key={code}
                    type="button"
                    onClick={() => setInternalRegion(code)}
                    className={clsx(
                      'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors',
                      active
                        ? 'border-oe-blue/40 bg-oe-blue-subtle/40 text-oe-blue-text'
                        : 'border-border-light bg-surface-primary text-content-secondary hover:bg-surface-secondary',
                    )}
                    aria-pressed={active}
                  >
                    <CountryFlag code={info?.flag ?? ''} size={16} />
                    <span>{info?.name ?? code}</span>
                  </button>
                );
              })}
            </div>
          )}
          <Button
            variant="ghost"
            size="sm"
            icon={<RefreshCw size={14} className={seedMutation.isPending ? 'animate-spin' : ''} />}
            loading={false}
            disabled={seedMutation.isPending}
            onClick={handleSeed}
            title={t('costs.resource_prices.rebuild_hint', {
              defaultValue: 'Rebuild the sheet from the base. Your edited prices are kept.',
            })}
          >
            {t('costs.resource_prices.rebuild', { defaultValue: 'Rebuild sheet' })}
          </Button>
        </div>
      </div>

      {/* Coverage band */}
      <div className="px-5 pb-4">
        <div className="rounded-xl border border-border-light bg-surface-secondary/40 p-4">
          <div className="mb-2 flex items-center justify-between gap-3">
            <span className="text-xs font-medium text-content-secondary">
              {t('costs.resource_prices.coverage_label', { defaultValue: 'Priced resources' })}
            </span>
            <span className="text-xs font-semibold tabular-nums text-content-primary">
              {stats
                ? t('costs.resource_prices.coverage_count', {
                    defaultValue: '{{priced}} of {{total}} priced ({{pct}}%)',
                    priced: stats.priced.toLocaleString(),
                    total: stats.resources.toLocaleString(),
                    pct: coveragePct,
                  })
                : '…'}
            </span>
          </div>
          <div className="h-2.5 w-full overflow-hidden rounded-full bg-surface-tertiary">
            <div
              className={clsx('h-full rounded-full transition-all duration-500 ease-out', barTone)}
              style={{ width: `${Math.min(100, Math.max(0, coveragePct))}%` }}
            />
          </div>
          {stats && (
            <div className="mt-2 flex items-center gap-1.5 text-2xs text-content-tertiary">
              {stats.unpriced > 0 ? (
                <>
                  <AlertTriangle size={11} className="text-semantic-warning" />
                  <span>
                    {t('costs.resource_prices.still_unpriced', {
                      defaultValue: '{{count}} resources still need a local price.',
                      count: stats.unpriced.toLocaleString(),
                    })}
                  </span>
                </>
              ) : (
                <>
                  <CheckCircle2 size={11} className="text-semantic-success" />
                  <span>
                    {t('costs.resource_prices.all_priced', {
                      defaultValue: 'Every resource has a price. Apply the re-price to refresh rates.',
                    })}
                  </span>
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Body */}
      {firstLoading ? (
        <div className="px-5 pb-6">
          <div className="h-40 animate-pulse rounded-xl bg-surface-secondary/60" />
        </div>
      ) : listQuery.isError ? (
        <div className="px-5 pb-8">
          <EmptyState
            icon={<AlertTriangle size={22} />}
            title={t('costs.resource_prices.load_error', {
              defaultValue: 'Could not load the price sheet',
            })}
            description={getErrorMessage(listQuery.error)}
            action={
              <Button variant="secondary" onClick={() => void listQuery.refetch()}>
                {t('common.retry', { defaultValue: 'Retry' })}
              </Button>
            }
          />
        </div>
      ) : sheetEmpty ? (
        <div className="px-5 pb-4">
          <EmptyState
            icon={<Coins size={22} />}
            title={t('costs.resource_prices.empty_title', { defaultValue: 'No price sheet yet' })}
            description={t('costs.resource_prices.empty_desc', {
              defaultValue:
                'This base lists resources without prices. Build the price sheet to start pricing them. If nothing appears, load the base on this page first.',
            })}
            action={
              <Button
                variant="primary"
                icon={<Coins size={16} />}
                loading={seedMutation.isPending}
                onClick={handleSeed}
              >
                {t('costs.resource_prices.build_sheet', { defaultValue: 'Build price sheet' })}
              </Button>
            }
          />
        </div>
      ) : (
        <>
          {/* Filters */}
          <div className="flex flex-wrap items-center gap-2 px-5 pb-3">
            <div className="relative min-w-[200px] flex-1">
              <Search
                size={14}
                className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-content-tertiary"
              />
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('costs.resource_prices.search_placeholder', {
                  defaultValue: 'Search resources by name…',
                })}
                className="w-full rounded-lg border border-border-light bg-surface-primary py-1.5 pl-8 pr-2.5 text-sm text-content-primary placeholder:text-content-quaternary focus:border-oe-blue/40 focus:outline-none focus:ring-2 focus:ring-oe-blue/20"
              />
            </div>
            <select
              value={resourceType}
              onChange={(e) => setResourceType(e.target.value)}
              className="rounded-lg border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary focus:border-oe-blue/40 focus:outline-none focus:ring-2 focus:ring-oe-blue/20"
              aria-label={t('costs.resource_prices.filter_type', { defaultValue: 'Resource type' })}
            >
              <option value="">
                {t('costs.resource_prices.all_types', { defaultValue: 'All types' })}
              </option>
              {RESOURCE_TYPES.map((rt) => (
                <option key={rt} value={rt}>
                  {resourceTypeLabel(rt)}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={() => setOnlyUnpriced((v) => !v)}
              className={clsx(
                'inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors',
                onlyUnpriced
                  ? 'border-semantic-warning/50 bg-semantic-warning-bg/50 text-[#b45309]'
                  : 'border-border-light bg-surface-primary text-content-secondary hover:bg-surface-secondary',
              )}
              aria-pressed={onlyUnpriced}
            >
              <AlertTriangle size={13} />
              {t('costs.resource_prices.only_unpriced', { defaultValue: 'Only unpriced' })}
            </button>
          </div>

          {/* Table */}
          <div className="overflow-x-auto border-t border-border-light">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-border-light bg-surface-secondary/40 text-left">
                  <th className="px-5 py-2 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                    {t('costs.resource_prices.col_resource', { defaultValue: 'Resource' })}
                  </th>
                  <th className="px-3 py-2 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                    {t('costs.resource_prices.col_type', { defaultValue: 'Type' })}
                  </th>
                  <th className="px-3 py-2 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                    {t('costs.resource_prices.col_unit', { defaultValue: 'Unit' })}
                  </th>
                  <th className="px-3 py-2 text-right text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                    {t('costs.resource_prices.col_price', { defaultValue: 'Unit price' })}
                  </th>
                  <th className="px-5 py-2 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                    {t('costs.resource_prices.col_source', { defaultValue: 'Source' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-5 py-10 text-center text-sm text-content-tertiary">
                      {t('costs.resource_prices.no_rows', {
                        defaultValue: 'No resources match these filters.',
                      })}
                    </td>
                  </tr>
                ) : (
                  rows.map((row) => {
                    const edit = pendingEdits.get(row.resource_key);
                    const value = edit?.value ?? row.unit_price;
                    const dirty =
                      edit !== undefined &&
                      edit.value.trim() !== edit.original.trim() &&
                      isValidPriceString(edit.value);
                    const invalid = edit !== undefined && edit.value.trim() !== '' && !isValidPriceString(edit.value);
                    const unpriced = isZeroPriceString(value);
                    return (
                      <tr
                        key={row.resource_key}
                        className={clsx(
                          'border-b border-border-light/70 transition-colors',
                          dirty
                            ? 'bg-oe-blue-subtle/20'
                            : unpriced
                              ? 'bg-semantic-warning-bg/20'
                              : 'hover:bg-surface-secondary/40',
                        )}
                      >
                        <td className="px-5 py-2 align-top">
                          <div className="font-medium text-content-primary">{row.resource_name}</div>
                          {row.resource_code && (
                            <div className="text-2xs text-content-quaternary tabular-nums">
                              {row.resource_code}
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-2 align-top">
                          <Badge variant={resourceTypeVariant(row.resource_type)} size="sm">
                            {resourceTypeLabel(row.resource_type)}
                          </Badge>
                        </td>
                        <td className="px-3 py-2 align-top text-content-secondary">
                          {row.unit || '-'}
                        </td>
                        <td className="px-3 py-2 align-top">
                          <div className="flex items-center justify-end gap-1.5">
                            <input
                              type="text"
                              inputMode="decimal"
                              value={value}
                              onChange={(e) => handlePriceChange(row, e.target.value)}
                              placeholder="0"
                              aria-label={t('costs.resource_prices.price_for', {
                                defaultValue: 'Unit price for {{name}}',
                                name: row.resource_name,
                              })}
                              className={clsx(
                                'w-28 rounded-md border bg-surface-primary px-2 py-1 text-right text-sm tabular-nums',
                                'focus:outline-none focus:ring-2 focus:ring-oe-blue/30',
                                invalid
                                  ? 'border-semantic-error'
                                  : dirty
                                    ? 'border-oe-blue/60'
                                    : 'border-border-light',
                              )}
                            />
                            <span className="w-10 shrink-0 text-2xs text-content-tertiary">
                              {row.currency || currency}
                            </span>
                          </div>
                        </td>
                        <td className="px-5 py-2 align-top">
                          {row.source === 'user' ? (
                            <Badge variant="blue" size="sm">
                              {t('costs.resource_prices.source_edited', { defaultValue: 'Edited' })}
                            </Badge>
                          ) : (
                            <Badge variant="neutral" size="sm">
                              {t('costs.resource_prices.source_imported', {
                                defaultValue: 'Imported',
                              })}
                            </Badge>
                          )}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between gap-3 px-5 py-3 text-xs text-content-tertiary">
              <span className="tabular-nums">
                {t('costs.resource_prices.page_range', {
                  defaultValue: '{{from}}-{{to}} of {{total}}',
                  from: rows.length === 0 ? 0 : page * PAGE_SIZE + 1,
                  to: page * PAGE_SIZE + rows.length,
                  total: total.toLocaleString(),
                })}
              </span>
              <div className="flex items-center gap-1.5">
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<ChevronLeft size={14} />}
                  disabled={page === 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                >
                  {t('common.previous', { defaultValue: 'Previous' })}
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  icon={<ChevronRight size={14} />}
                  iconPosition="right"
                  disabled={(page + 1) * PAGE_SIZE >= total}
                  onClick={() => setPage((p) => p + 1)}
                >
                  {t('common.next', { defaultValue: 'Next' })}
                </Button>
              </div>
            </div>
          )}

          {/* Reprice preview */}
          {preview && (
            <div className="mx-5 mb-4 rounded-xl border border-oe-blue/30 bg-oe-blue-subtle/20 p-4">
              <div className="mb-1.5 flex items-center gap-2">
                <Info size={14} className="text-oe-blue" />
                <span className="text-sm font-semibold text-content-primary">
                  {t('costs.resource_prices.preview_title', {
                    defaultValue: 'Re-price preview - nothing has changed yet',
                  })}
                </span>
              </div>
              <p className="text-xs text-content-secondary">
                {t('costs.resource_prices.preview_summary', {
                  defaultValue:
                    '{{fully}} of {{total}} items would be fully priced ({{pct}}%). {{partial}} partially priced, {{unpriced}} still unpriced.',
                  fully: preview.items_fully_priced.toLocaleString(),
                  total: preview.items_total.toLocaleString(),
                  pct: Math.round(preview.coverage * 100),
                  partial: preview.items_partially_priced.toLocaleString(),
                  unpriced: preview.items_unpriced.toLocaleString(),
                })}
              </p>
              {preview.missing_resource_count > 0 && (
                <p className="mt-1.5 text-2xs text-content-tertiary">
                  {t('costs.resource_prices.preview_missing', {
                    defaultValue: '{{count}} resources still need a price, for example: {{sample}}',
                    count: preview.missing_resource_count.toLocaleString(),
                    sample: preview.missing_resources_sample.slice(0, 5).join(', '),
                  })}
                </p>
              )}
            </div>
          )}

          {/* Action bar */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border-light bg-surface-secondary/30 px-5 py-3">
            <div className="min-w-0 text-xs">
              {hasInvalidEdit ? (
                <span className="inline-flex items-center gap-1.5 text-semantic-error">
                  <AlertTriangle size={13} />
                  {t('costs.resource_prices.has_invalid', {
                    defaultValue: 'Some prices are not valid numbers.',
                  })}
                </span>
              ) : dirtyCount > 0 ? (
                <span className="inline-flex items-center gap-1.5 text-content-secondary">
                  {t('costs.resource_prices.unsaved', {
                    defaultValue: '{{count}} unsaved change(s). Save before re-pricing.',
                    count: dirtyCount,
                  })}
                </span>
              ) : (
                <span className="text-content-tertiary">
                  {t('costs.resource_prices.flow_hint', {
                    defaultValue: 'Edit prices, save, then preview and apply the re-price.',
                  })}
                </span>
              )}
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {dirtyCount > 0 && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={discardEdits}
                  disabled={bulkMutation.isPending}
                >
                  {t('costs.resource_prices.discard', { defaultValue: 'Discard' })}
                </Button>
              )}
              <Button
                variant="primary"
                size="sm"
                icon={<Save size={14} />}
                loading={bulkMutation.isPending}
                disabled={dirtyCount === 0 || hasInvalidEdit}
                onClick={handleSave}
              >
                {dirtyCount > 0
                  ? t('costs.resource_prices.save_n', {
                      defaultValue: 'Save prices ({{count}})',
                      count: dirtyCount,
                    })
                  : t('costs.resource_prices.save', { defaultValue: 'Save prices' })}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                icon={<Calculator size={14} />}
                loading={isPreviewing}
                disabled={repriceDisabled}
                onClick={handlePreview}
                title={
                  dirtyCount > 0
                    ? t('costs.resource_prices.save_first', {
                        defaultValue: 'Save your price changes first.',
                      })
                    : undefined
                }
              >
                {t('costs.resource_prices.preview_reprice', { defaultValue: 'Preview re-price' })}
              </Button>
              <Button
                variant={preview ? 'primary' : 'secondary'}
                size="sm"
                icon={<CheckCircle2 size={14} />}
                loading={isApplying}
                disabled={repriceDisabled}
                onClick={handleApply}
                title={
                  dirtyCount > 0
                    ? t('costs.resource_prices.save_first', {
                        defaultValue: 'Save your price changes first.',
                      })
                    : undefined
                }
              >
                {t('costs.resource_prices.apply_reprice', { defaultValue: 'Apply re-price' })}
              </Button>
            </div>
          </div>
        </>
      )}
    </Card>
  );
}

/* ── Local helpers ───────────────────────────────────────────────────────── */

/** Narrowed shape of the reprice preview the panel actually renders. */
type RepriceResponsePreview = {
  items_total: number;
  items_fully_priced: number;
  items_partially_priced: number;
  items_unpriced: number;
  coverage: number;
  missing_resource_count: number;
  missing_resources_sample: string[];
};

function resourceTypeVariant(type: string): PillVariant {
  switch (type) {
    case 'labor':
      return 'blue';
    case 'equipment':
      return 'success';
    case 'operator':
    case 'electricity':
      return 'warning';
    default:
      return 'neutral';
  }
}
