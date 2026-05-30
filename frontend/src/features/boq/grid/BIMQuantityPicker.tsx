// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { X, Loader2, Cuboid, ArrowRight, SlidersHorizontal } from 'lucide-react';
import { fetchBIMElementsByIds } from '@/features/bim/api';
import type { BIMElementData } from '@/shared/ui/BIMViewer/ElementManager';
import type { DisplayQuantityApi } from '@/shared/hooks/useDisplayQuantity';
import { useToastStore } from '@/stores/useToastStore';
import { boqApi } from '../api';
import { ProjectionEditor, type ProjectionValue } from '../ProjectionEditor';

const DEFAULT_PROJECTION: ProjectionValue = {
  projection_kind: 'simple',
  quantity_field: '',
  aggregation: 'sum',
  formula: '',
};

/* ── Unit inference from property/quantity key ─────────────────────── */

function inferUnit(key: string): string {
  if (key.includes('area') || key.endsWith('_m2')) return 'm\u00B2';
  if (key.includes('volume') || key.endsWith('_m3')) return 'm\u00B3';
  if (key.includes('length') || key.endsWith('_m')) return 'm';
  if (key.includes('weight') || key.endsWith('_kg')) return 'kg';
  if (key.includes('count')) return 'pcs';
  if (key.includes('perimeter')) return 'm';
  if (
    key.includes('height') ||
    key.includes('width') ||
    key.includes('thickness') ||
    key.includes('depth')
  )
    return 'm';
  return '';
}

/* ── Format key name for display ───────────────────────────────────── */

function formatKeyName(key: string): string {
  return key
    .replace(/_m2$|_m3$|_m$|_kg$/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/* ── Types ─────────────────────────────────────────────────────────── */

interface QuantityEntry {
  key: string;
  label: string;
  value: number;
  unit: string;
  source: 'quantities' | 'properties';
}

interface ElementQuantities {
  element: BIMElementData;
  entries: QuantityEntry[];
}

export interface BIMQuantityPickerProps {
  positionId: string;
  cadElementIds: string[];
  bimModelId: string;
  currentQuantity: number;
  currentUnit: string;
  /** Anchor rectangle for portal positioning (from button.getBoundingClientRect()). */
  anchorRect?: DOMRect | null;
  onSelectQuantity: (value: number, source: string) => void;
  onClose: () => void;
  /**
   * Issue #285: measurement-system-aware quantity API. When present each
   * BIM quantity + unit is SHOWN converted into the user's system; the
   * value passed to ``onSelectQuantity`` (which becomes the position's
   * canonical quantity) stays metric. Identity for metric / unmapped
   * units, so values pass straight through when absent.
   */
  displayQuantity?: DisplayQuantityApi;
}

/* ── Extract all numeric values from a BIM element ─────────────────── */

function extractQuantities(element: BIMElementData): QuantityEntry[] {
  const entries: QuantityEntry[] = [];

  // From quantities (primary source)
  if (element.quantities) {
    for (const [key, value] of Object.entries(element.quantities)) {
      const num = typeof value === 'number' ? value : parseFloat(String(value));
      if (!isNaN(num) && num !== 0) {
        entries.push({
          key,
          label: formatKeyName(key),
          value: num,
          unit: inferUnit(key),
          source: 'quantities',
        });
      }
    }
  }

  // From properties (secondary — only numeric values not already in quantities)
  if (element.properties) {
    const qKeys = new Set(Object.keys(element.quantities ?? {}));
    for (const [key, value] of Object.entries(element.properties)) {
      if (qKeys.has(key)) continue;
      const num = typeof value === 'number' ? value : parseFloat(String(value));
      if (!isNaN(num) && num !== 0) {
        entries.push({
          key,
          label: formatKeyName(key),
          value: num,
          unit: inferUnit(key),
          source: 'properties',
        });
      }
    }
  }

  return entries;
}

/* ── Compute sums across all elements ──────────────────────────────── */

interface SumEntry {
  key: string;
  label: string;
  sum: number;
  unit: string;
  count: number;
}

function computeSums(groups: ElementQuantities[]): SumEntry[] {
  const map = new Map<string, SumEntry>();

  for (const group of groups) {
    for (const entry of group.entries) {
      const existing = map.get(entry.key);
      if (existing) {
        existing.sum += entry.value;
        existing.count += 1;
      } else {
        map.set(entry.key, {
          key: entry.key,
          label: entry.label,
          sum: entry.value,
          unit: entry.unit,
          count: 1,
        });
      }
    }
  }

  // Only show sums that appear in more than one element, or always if there is just one element
  return Array.from(map.values()).sort((a, b) => b.sum - a.sum);
}

/* ── Format number for display ─────────────────────────────────────── */

function fmtNum(v: number): string {
  if (Number.isInteger(v)) return v.toLocaleString('en', { maximumFractionDigits: 0 });
  return v.toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
}

/* ── Component ─────────────────────────────────────────────────────── */

export function BIMQuantityPicker({
  positionId,
  cadElementIds,
  bimModelId,
  currentQuantity,
  anchorRect,
  onSelectQuantity,
  onClose,
  displayQuantity,
}: BIMQuantityPickerProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const popoverRef = useRef<HTMLDivElement>(null);

  // Projection rule (option C): persists the *durable* extraction rule so
  // "Refresh from model" honours the chosen parameter / formula instead of
  // re-guessing from the unit. Distinct from the quick "Use" buttons below,
  // which set a one-shot manual value.
  const [showRule, setShowRule] = useState(false);
  const [projection, setProjection] = useState<ProjectionValue>(DEFAULT_PROJECTION);

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [onClose]);

  // Close on Escape
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [onClose]);

  // Fetch ONLY the linked elements by their IDs (DB UUID or stable_id).
  // Uses a dedicated POST endpoint so we don't hit the 2000-element list limit.
  const { data: elementsResp, isLoading, error: fetchError } = useQuery({
    queryKey: ['bim-elements-by-ids', bimModelId, ...cadElementIds],
    queryFn: () => fetchBIMElementsByIds(bimModelId, cadElementIds),
    enabled: !!bimModelId && cadElementIds.length > 0,
    staleTime: 2 * 60 * 1000,
    gcTime: 5 * 60 * 1000,
    retry: 1,
  });

  const { groups, sums, totalFetched, totalMatched } = useMemo(() => {
    if (!elementsResp?.items)
      return { groups: [] as ElementQuantities[], sums: [] as SumEntry[], totalFetched: 0, totalMatched: 0 };

    // All returned items are already the matched elements
    const matched = elementsResp.items;
    const grps = matched
      .map((el) => ({ element: el, entries: extractQuantities(el) }))
      .filter((g) => g.entries.length > 0);

    return {
      groups: grps,
      sums: computeSums(grps),
      totalFetched: elementsResp.items.length,
      totalMatched: matched.length,
    };
  }, [elementsResp]);

  // Collapsible element groups
  const [expandedElements, setExpandedElements] = useState<Set<string>>(
    () => new Set(cadElementIds.length <= 3 ? cadElementIds : []),
  );
  const toggleElement = useCallback((id: string) => {
    setExpandedElements((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // Compute portal position from anchor rect
  const style = useMemo(() => {
    if (!anchorRect) return { position: 'absolute' as const, right: 0, top: '100%', marginTop: 4 };
    const top = anchorRect.bottom + 4;
    const left = Math.min(anchorRect.left, window.innerWidth - 330);
    // Flip up if near bottom of viewport
    if (top + 320 > window.innerHeight) {
      return { position: 'fixed' as const, left, top: anchorRect.top - 320 - 4 };
    }
    return { position: 'fixed' as const, left, top };
  }, [anchorRect]);

  // Canonical params available across the bound elements (chips + field).
  const availableParams = useMemo(() => {
    const keys = new Set<string>();
    for (const g of groups) for (const e of g.entries) keys.add(e.key);
    return Array.from(keys).sort();
  }, [groups]);

  const saveProjection = useMutation({
    mutationFn: () =>
      boqApi.createQuantityLink(positionId, {
        model_id: bimModelId,
        projection_kind: projection.projection_kind,
        quantity_field:
          projection.projection_kind === 'simple' && projection.aggregation !== 'count'
            ? projection.quantity_field
            : '',
        aggregation: projection.aggregation,
        formula: projection.projection_kind === 'formula' ? projection.formula : null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['quantity-links', positionId] });
      addToast({
        type: 'success',
        title: t('boq.projection_saved', { defaultValue: 'Projection saved' }),
        message: t('boq.projection_saved_hint', {
          defaultValue:
            'The quantity is not changed yet — use “Refresh from model” then Apply to pull it in.',
        }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('boq.projection_save_failed', { defaultValue: 'Could not save projection' }),
        message: e.message,
      }),
  });

  const projectionValid =
    projection.projection_kind === 'formula'
      ? projection.formula.trim().length > 0
      : projection.aggregation === 'count' || !!projection.quantity_field;

  const popover = (
    <div
      ref={popoverRef}
      className="w-80 bg-white dark:bg-surface-elevated
                 rounded-xl shadow-xl border border-border-light dark:border-border-dark
                 overflow-hidden"
      style={{ ...style, zIndex: 9999 }}
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border-light dark:border-border-dark bg-surface-secondary/30">
        <div className="flex items-center gap-1.5">
          <Cuboid size={14} className="text-emerald-600" />
          <span className="text-xs font-semibold text-content-primary">BIM Quantities</span>
          <span className="text-[10px] text-content-tertiary tabular-nums">
            ({cadElementIds.length} element{cadElementIds.length !== 1 ? 's' : ''})
          </span>
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="h-5 w-5 flex items-center justify-center rounded text-content-tertiary
                     hover:text-content-primary hover:bg-surface-tertiary transition-colors"
        >
          <X size={12} />
        </button>
      </div>

      {/* Body */}
      <div className="max-h-72 overflow-y-auto">
        {isLoading && (
          <div className="flex items-center justify-center gap-2 py-8">
            <Loader2 size={16} className="animate-spin text-content-tertiary" />
            <span className="text-xs text-content-tertiary">Loading elements...</span>
          </div>
        )}

        {!isLoading && groups.length === 0 && (
          <div className="flex flex-col items-center justify-center py-8 gap-1">
            <Cuboid size={20} className="text-content-quaternary" />
            <span className="text-xs text-content-tertiary">
              {fetchError
                ? 'Failed to load BIM elements'
                : totalFetched === 0
                  ? 'No elements in BIM model'
                  : totalMatched === 0
                    ? 'Linked IDs not found in model'
                    : 'No numeric quantities found'}
            </span>
            <span className="text-[9px] text-content-quaternary tabular-nums">
              {totalFetched} elements loaded, {totalMatched} matched, {cadElementIds.length} linked
            </span>
            {fetchError && (
              <span className="text-[9px] text-red-400 mt-1 px-3 text-center">
                {String(fetchError instanceof Error ? fetchError.message : fetchError)}
              </span>
            )}
          </div>
        )}

        {!isLoading && groups.length > 0 && (
          <>
            {/* Per-element sections */}
            {groups.map(({ element, entries }) => (
              <div key={element.id} className="border-b border-border-light/50 dark:border-border-dark/50 last:border-b-0">
                {/* Element header */}
                <button
                  onClick={() => toggleElement(element.id)}
                  title={`${element.name || element.element_type} (${element.element_type})`}
                  className="w-full flex items-center gap-1.5 px-3 py-1.5 text-left
                             hover:bg-surface-secondary/60 transition-colors"
                >
                  <span className="text-[10px] text-content-quaternary shrink-0">
                    {expandedElements.has(element.id) ? '\u25BC' : '\u25B6'}
                  </span>
                  <span className="text-[11px] font-medium text-content-secondary truncate min-w-0 flex-1">
                    {element.name || element.element_type}
                  </span>
                  <span className="text-[9px] text-content-quaternary font-mono shrink-0">
                    {element.element_type}
                  </span>
                </button>

                {/* Quantity rows */}
                {expandedElements.has(element.id) && (
                  <div className="pb-1">
                    {entries.map((entry) => (
                      <QuantityRow
                        key={`${element.id}-${entry.key}`}
                        label={entry.label}
                        value={entry.value}
                        unit={entry.unit}
                        isCurrent={entry.value === currentQuantity}
                        displayQuantity={displayQuantity}
                        onUse={() =>
                          onSelectQuantity(
                            entry.value,
                            `BIM: ${element.name || element.element_type} / ${entry.label}`,
                          )
                        }
                      />
                    ))}
                  </div>
                )}
              </div>
            ))}

            {/* Sum section */}
            {sums.length > 0 && (
              <div className="border-t border-border-light dark:border-border-dark bg-emerald-50/50 dark:bg-emerald-950/20">
                <div className="px-3 py-1.5">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                    Totals
                  </span>
                </div>
                {sums.map((s) => (
                  <QuantityRow
                    key={`sum-${s.key}`}
                    label={`${s.label} (${s.count}x)`}
                    value={s.sum}
                    unit={s.unit}
                    isCurrent={s.sum === currentQuantity}
                    isSum
                    displayQuantity={displayQuantity}
                    onUse={() => onSelectQuantity(s.sum, `BIM sum: ${s.label}`)}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {/* Durable rule (projection): chosen parameter or formula. */}
      {!isLoading && groups.length > 0 && (
        <div className="border-t border-border-light dark:border-border-dark">
          <button
            onClick={() => setShowRule((v) => !v)}
            className="w-full flex items-center gap-1.5 px-3 py-2 text-left hover:bg-surface-secondary/40 transition-colors"
          >
            <SlidersHorizontal size={13} className="text-content-tertiary shrink-0" />
            <span className="text-[11px] font-medium text-content-secondary flex-1">
              {t('boq.projection_rule_toggle', { defaultValue: 'Quantity rule (parameter / formula)' })}
            </span>
            <span className="text-[10px] text-content-quaternary">
              {showRule ? '▼' : '▶'}
            </span>
          </button>
          {showRule && (
            <div className="px-3 pb-3 space-y-3">
              <ProjectionEditor
                positionId={positionId}
                availableParams={availableParams}
                value={projection}
                onChange={setProjection}
                livePreview
              />
              <button
                onClick={() => saveProjection.mutate()}
                disabled={!projectionValid || saveProjection.isPending}
                className="w-full flex items-center justify-center gap-1.5 h-7 rounded-lg bg-oe-blue text-white text-xs font-medium hover:bg-oe-blue/90 disabled:opacity-50 transition-colors"
              >
                {saveProjection.isPending && <Loader2 size={12} className="animate-spin" />}
                {t('boq.projection_save', { defaultValue: 'Save projection' })}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );

  return anchorRect ? createPortal(popover, document.body) : popover;
}

/* ── Single quantity row ───────────────────────────────────────────── */

function QuantityRow({
  label,
  value,
  unit,
  isCurrent,
  isSum,
  onUse,
  displayQuantity,
}: {
  label: string;
  value: number;
  unit: string;
  isCurrent: boolean;
  isSum?: boolean;
  onUse: () => void;
  displayQuantity?: DisplayQuantityApi;
}) {
  // Issue #285: convert the BIM quantity + unit for DISPLAY only. ``onUse``
  // / ``isCurrent`` are computed in the parent against the raw metric value,
  // so the value applied to the position stays metric-canonical. Identity
  // for metric / unmapped units.
  const shownValue = displayQuantity ? displayQuantity.convert(value, unit).value : value;
  const shownUnit = displayQuantity ? displayQuantity.unitFor(unit) : unit;
  return (
    <div
      className={`flex items-center gap-1 px-3 py-1 group/row hover:bg-emerald-50/80 dark:hover:bg-emerald-950/30 transition-colors ${
        isSum ? 'font-medium' : ''
      }`}
    >
      <span className="text-[11px] text-content-secondary flex-1 truncate pl-3">{label}</span>
      <span className="text-[11px] tabular-nums text-content-primary font-medium shrink-0">
        {fmtNum(shownValue)}
      </span>
      {shownUnit && (
        <span className="text-[9px] text-content-quaternary font-mono shrink-0 w-5">{shownUnit}</span>
      )}
      {isCurrent ? (
        <span className="text-[9px] text-emerald-600 font-medium shrink-0 w-9 text-center">
          current
        </span>
      ) : (
        <button
          onClick={(e) => {
            e.stopPropagation();
            onUse();
          }}
          className="shrink-0 h-4 flex items-center gap-0.5 px-1.5 rounded text-[9px] font-medium
                     text-emerald-600 bg-emerald-100 dark:bg-emerald-900/30
                     hover:bg-emerald-200 dark:hover:bg-emerald-900/50
                     opacity-0 group-hover/row:opacity-100 transition-all"
        >
          Use <ArrowRight size={8} />
        </button>
      )}
    </div>
  );
}
