/**
 * AddToBOQModal — link a BIM element (or a filtered subset) to a BOQ
 * position.  Two tabs:
 *
 *   1. "Link to existing position" — searchable list of BOQ positions
 *      from the active project.  Click a row to create a link via
 *      `createLink`.
 *   2. "Create new position" — a small form pre-filled from the selected
 *      element's quantities, classification and type.  Submitting
 *      creates a new position AND a link in one shot.
 *
 * Also supports "bulk mode" — when `elements.length > 1` the modal shows
 * the aggregated totals (sum of area_m2 / volume_m3 / length_m / count)
 * and on submit creates a single BOQ position + a link per element.
 */

import { useMemo, useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { X, Search, Plus, CheckCircle2, Loader2, Link2, Sparkles, AlertTriangle, Sigma } from 'lucide-react';
import { apiGet, apiPost } from '@/shared/lib/api';
import { boqApi, type BOQ, type BOQWithPositions, type Position } from '@/features/boq/api';
import { createLink, ensureBIMElement } from './api';
import type { BIMElementData } from '@/shared/ui/BIMViewer';
import { useToastStore } from '@/stores/useToastStore';
import {
  suggestQuantityFromBIM,
  formatSuggestionBadge,
  type QuantitySuggestion,
} from '@/features/boq/suggestQuantityFromBIM';

/** Matches a canonical 36-char UUID (8-4-4-4-12, hex + dashes). Anything else
 *  — notably our client-side `_unmatched_N` stubs and Revit numeric ids —
 *  must be resolved to a real BIMElement UUID via `ensureBIMElement` before
 *  it can travel through the UUID-typed link endpoint. */
const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Turn any element into a DB BIMElement UUID. UUIDs pass through; stubs
 *  hit the backend lazy-create endpoint keyed by mesh_ref (or stable_id). */
async function resolveElementUUID(
  modelId: string,
  el: BIMElementData,
): Promise<string> {
  if (UUID_RE.test(el.id)) return el.id;
  const ref = {
    meshRef: el.mesh_ref ?? null,
    stableId: el.stable_id ?? null,
  };
  if (!ref.meshRef && !ref.stableId) {
    throw new Error(
      'This mesh has no Revit ElementId — cannot link it to BOQ. ' +
        'Re-upload the model so the viewer can attach a stable reference.',
    );
  }
  const { id } = await ensureBIMElement(modelId, ref);
  return id;
}

/** Backend response shape for POST /api/v1/costs/suggest-for-element/. */
interface CostSuggestion {
  cost_item_id: string;
  code: string;
  description: string;
  unit: string;
  unit_rate: number | string;
  classification: Record<string, string>;
  score: number;
  match_reasons: string[];
}

interface AddToBOQModalProps {
  projectId: string;
  /** Active BIM model — required so stubs (`_unmatched_N` ids) can be
   *  resolved to real BIMElement UUIDs via the ensure-element endpoint
   *  before the link is created. */
  modelId: string;
  /** Either a single element (click flow) or many (bulk filter flow). */
  elements: BIMElementData[];
  onClose: () => void;
  /** Called after a successful link (or bulk link) so the parent can
   *  refetch the element list and pick up the new boq_links. */
  onLinked?: () => void;
}

type Tab = 'existing' | 'new';

/** Pick the most appropriate quantity/unit pair for a set of elements.
 *  Thin wrapper over `suggestQuantityFromBIM` — used for the *initial*
 *  default before the user picks a unit.  Once the unit changes the
 *  modal re-runs the suggester directly. */
function pickInitialQuantity(elements: BIMElementData[]): {
  quantity: number;
  unit: string;
  suggestion: QuantitySuggestion;
} {
  // Empty unit → suggester falls back to volume → area → length → count
  // and picks an inferredUnit that we use as the form's initial unit.
  const s = suggestQuantityFromBIM(elements, '');
  return { quantity: s.value, unit: s.inferredUnit || 'pcs', suggestion: s };
}

/** Build a default description from the element set. */
function buildDefaultDescription(elements: BIMElementData[]): string {
  if (elements.length === 1) {
    const el = elements[0]!;
    return el.name || el.element_type || 'BIM element';
  }
  // Bulk: group by element_type
  const types = new Set<string>();
  for (const el of elements) {
    if (el.element_type) types.add(el.element_type);
  }
  const typeLabel = Array.from(types).slice(0, 3).join(', ') || 'BIM elements';
  return `${typeLabel} (${elements.length.toLocaleString()} elements from BIM model)`;
}

/** Extract a merged classification from all elements (first non-empty wins). */
function mergeClassification(elements: BIMElementData[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const el of elements) {
    if (!el.classification) continue;
    for (const [key, value] of Object.entries(el.classification)) {
      if (!out[key] && value) out[key] = value;
    }
  }
  return out;
}

export default function AddToBOQModal({
  projectId,
  modelId,
  elements,
  onClose,
  onLinked,
}: AddToBOQModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [tab, setTab] = useState<Tab>(elements.length > 1 ? 'new' : 'existing');
  const [search, setSearch] = useState('');
  // User's explicit BOQ pick.  `null` = "use the default" (first BOQ in the
  // list once it loads).  We derive the effective id via useMemo below so
  // the positions query never fires with a stale/dangling id.
  const [userSelectedBOQId, setUserSelectedBOQId] = useState<string | null>(null);
  // Ref to auto-focus the "Target BOQ" select on modal open — it's the
  // first decision the user has to make before picking link-vs-create.
  const targetBoqRef = useRef<HTMLSelectElement>(null);

  // ── New position form state ─────────────────────────────────────────
  const defaultQty = useMemo(() => pickInitialQuantity(elements), [elements]);
  const [description, setDescription] = useState(() => buildDefaultDescription(elements));
  const [unit, setUnit] = useState(defaultQty.unit);
  const [quantity, setQuantity] = useState(defaultQty.quantity.toFixed(3));
  const [unitRate, setUnitRate] = useState('0');
  const [ordinal, setOrdinal] = useState('');
  // Tracks whether the user has manually edited the quantity field; if so
  // we DON'T overwrite it when the unit changes — they typed it for a reason.
  const [userEditedQty, setUserEditedQty] = useState(false);

  // Re-run the suggester whenever the unit changes so the badge + auto-fill
  // stay in sync with the BOQ position the user is targetting.  The
  // suggestion drives:
  //   1. the value pre-filled into the Quantity input (unless the user
  //      has manually edited it — `userEditedQty` blocks the overwrite),
  //   2. the badge under the Quantity input,
  //   3. the low-confidence warning icon.
  const quantitySuggestion = useMemo<QuantitySuggestion>(
    () => suggestQuantityFromBIM(elements, unit),
    [elements, unit],
  );

  // Auto-update the Quantity input when (elements / unit) change AND the
  // user hasn't typed in it yet.  Use the raw suggestion value, formatted
  // to 3 decimals like the original behaviour.
  useEffect(() => {
    if (userEditedQty) return;
    setQuantity(quantitySuggestion.value.toFixed(3));
  }, [quantitySuggestion, userEditedQty]);

  // Re-seed when the elements list changes (opening the modal from a new
  // element).  This also clears any transient UI state that would
  // otherwise "leak" across reopens if the parent kept the component
  // mounted between sessions — tab, search box, ordinal override, and
  // unit-rate field all reset to the defaults for the new element(s).
  useEffect(() => {
    const d = pickInitialQuantity(elements);
    setDescription(buildDefaultDescription(elements));
    setUnit(d.unit);
    setQuantity(d.quantity.toFixed(3));
    setTab(elements.length > 1 ? 'new' : 'existing');
    setSearch('');
    setOrdinal('');
    setUnitRate('0');
    setUserSelectedBOQId(null);
    setUserEditedQty(false);
  }, [elements]);

  // Focus the Target BOQ select as soon as the modal mounts — it's Step 1
  // of the flow ("which BOQ are we linking into?") and should be the first
  // thing users interact with.
  useEffect(() => {
    const id = requestAnimationFrame(() => targetBoqRef.current?.focus());
    return () => cancelAnimationFrame(id);
  }, []);

  // ── Cost auto-suggestions (CWICR / cost database) ───────────────────
  //
  // Calls POST /api/v1/costs/suggest-for-element/ with the *first* element's
  // attributes (the bulk case shares enough similarity that ranking the
  // first item is a sound approximation).  Results are rendered as chips
  // above the unit-rate field; clicking a chip fills description / unit /
  // unit_rate so the estimator skips manual lookup.
  const firstEl = elements[0];
  const suggestionsQuery = useQuery<CostSuggestion[]>({
    queryKey: [
      'cost-suggestions-for-element',
      firstEl?.id,
      firstEl?.element_type,
      firstEl?.name,
    ],
    enabled: !!firstEl && tab === 'new',
    staleTime: 5 * 60 * 1000,
    queryFn: () =>
      apiPost<CostSuggestion[]>('/api/v1/costs/suggest-for-element/', {
        element_type: firstEl?.element_type ?? null,
        name: firstEl?.name ?? null,
        discipline: firstEl?.discipline ?? null,
        properties: firstEl?.properties ?? null,
        quantities: firstEl?.quantities ?? null,
        classification: firstEl?.classification ?? null,
        limit: 5,
      }),
  });
  const suggestions: CostSuggestion[] = suggestionsQuery.data ?? [];

  /** Apply a clicked suggestion to the form fields.  We keep the user's
   *  current quantity (it's geometric, not from CWICR) and only overwrite
   *  description, unit and unit_rate. */
  const applySuggestion = (s: CostSuggestion) => {
    setDescription(s.description);
    setUnit(s.unit);
    const num =
      typeof s.unit_rate === 'number'
        ? s.unit_rate
        : Number.parseFloat(String(s.unit_rate));
    if (Number.isFinite(num)) setUnitRate(String(num));
  };

  // ── Fetch BOQs for this project ────────────────────────────────────
  const boqsQuery = useQuery({
    queryKey: ['boqs-for-link', projectId],
    queryFn: () => boqApi.list(projectId),
  });
  const boqs = boqsQuery.data ?? [];

  // Effective BOQ id:
  //   - if the user picked one AND it still exists in the current list, use it
  //   - otherwise fall back to the first BOQ in the list (if any)
  // Deriving via useMemo avoids the old race where `selectedBOQId` was
  // initialised lazily via a useEffect AFTER first render — the positions
  // query could fire with a stale/null id during that window.
  const selectedBOQId = useMemo<string | null>(() => {
    if (userSelectedBOQId && boqs.some((b) => b.id === userSelectedBOQId)) {
      return userSelectedBOQId;
    }
    return boqs[0]?.id ?? null;
  }, [boqs, userSelectedBOQId]);

  // ── Fetch positions for the selected BOQ (for the existing tab) ─────
  // Guard is doubled: only fire once the BOQ list has actually loaded AND
  // we have a concrete id, to avoid an enabled=true → queryFn(null) window.
  const positionsQuery = useQuery<BOQWithPositions>({
    queryKey: ['boq-positions-for-link', selectedBOQId],
    queryFn: () => boqApi.get(selectedBOQId!),
    enabled: !!selectedBOQId && !boqsQuery.isLoading,
  });
  const positions: Position[] = positionsQuery.data?.positions ?? [];

  // Filter out sections (pure headers) from the pickable list — you link
  // to real cost-bearing positions, not to their parent headers. A row is
  // a section if EITHER the unit field is blank/dash OR the row is the
  // parent of any other position (sections always have children, leaves
  // never do).
  const pickablePositions = useMemo(() => {
    const q = search.trim().toLowerCase();
    const parentIds = new Set<string>();
    for (const p of positions) {
      if (p.parent_id) parentIds.add(p.parent_id);
    }
    return positions.filter((p) => {
      const unit = (p.unit ?? '').trim();
      if (unit === '' || unit === '—' || unit === '-') return false;
      // Position acts as a section header when other rows are nested under it.
      if (parentIds.has(p.id)) return false;
      if (!q) return true;
      return (
        p.description.toLowerCase().includes(q) ||
        p.ordinal.toLowerCase().includes(q)
      );
    });
  }, [positions, search]);

  // ── Mutation: link to an existing position ──────────────────────────
  const linkExistingMut = useMutation({
    mutationFn: async (positionId: string) => {
      let createdCount = 0;
      for (const el of elements) {
        try {
          const resolvedId = await resolveElementUUID(modelId, el);
          await createLink({
            boq_position_id: positionId,
            bim_element_id: resolvedId,
            link_type: 'manual',
            confidence: 'high',
          });
          createdCount++;
        } catch (e: unknown) {
          // Duplicate links will 409 — swallow so bulk linking is idempotent
          const err = e as { message?: string };
          if (!err?.message?.includes('already')) throw e;
        }
      }
      return createdCount;
    },
    onSuccess: (count) => {
      addToast({
        type: 'success',
        title: t('bim.link_success_title', { defaultValue: 'Linked' }),
        message: t('bim.link_success', {
          defaultValue: 'Linked {{count}} element(s) to BOQ position',
          count,
        }),
      });
      qc.invalidateQueries({ queryKey: ['bim-elements'] });
      onLinked?.();
      onClose();
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: err.message || String(err),
      });
    },
  });

  // ── Mutation: create a new position + link ──────────────────────────
  const createNewMut = useMutation({
    mutationFn: async () => {
      if (!selectedBOQId) throw new Error('No BOQ selected');
      const qty = Number.parseFloat(quantity) || 0;
      const rate = Number.parseFloat(unitRate) || 0;
      // Pick an auto-ordinal: last position ordinal + 1 (simple numeric suffix)
      const computedOrdinal = ordinal.trim() || buildAutoOrdinal(positions);
      const classification = mergeClassification(elements);
      const newPos = await boqApi.addPosition({
        boq_id: selectedBOQId,
        ordinal: computedOrdinal,
        description,
        unit,
        quantity: qty,
        unit_rate: rate,
        classification,
      });
      // Link every element to the new position
      let linkCount = 0;
      for (const el of elements) {
        try {
          const resolvedId = await resolveElementUUID(modelId, el);
          await createLink({
            boq_position_id: newPos.id,
            bim_element_id: resolvedId,
            link_type: 'manual',
            confidence: 'high',
          });
          linkCount++;
        } catch (e: unknown) {
          const err = e as { message?: string };
          if (!err?.message?.includes('already')) throw e;
        }
      }
      return { position: newPos, linkCount };
    },
    onSuccess: ({ linkCount }) => {
      addToast({
        type: 'success',
        title: t('bim.link_created_new_title', { defaultValue: 'Position created' }),
        message: t('bim.link_created_new', {
          defaultValue: 'Created BOQ position and linked {{count}} element(s)',
          count: linkCount,
        }),
      });
      qc.invalidateQueries({ queryKey: ['bim-elements'] });
      qc.invalidateQueries({ queryKey: ['boq-positions-for-link', selectedBOQId] });
      qc.invalidateQueries({ queryKey: ['boq'] });
      onLinked?.();
      onClose();
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: err.message || String(err),
      });
    },
  });

  const busy = linkExistingMut.isPending || createNewMut.isPending;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      <div
        className="bg-surface-primary rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col border border-border-light"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border-light shrink-0">
          <div className="flex items-center gap-2">
            <Link2 size={16} className="text-oe-blue" />
            <h2 className="text-sm font-semibold text-content-primary">
              {t('bim.add_to_boq_title', { defaultValue: 'Add to BOQ' })}
            </h2>
            <span className="text-[11px] text-content-tertiary">
              {elements.length === 1
                ? elements[0]!.name || elements[0]!.element_type
                : t('bim.add_to_boq_bulk', {
                    defaultValue: '{{count}} elements',
                    count: elements.length,
                  })}
            </span>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-content-tertiary hover:text-content-primary hover:bg-surface-secondary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        {/* Step 1 — Target BOQ picker.  Placed above the tabs because the
            flow starts here: pick a BOQ first, THEN choose link-vs-create.
            Highlighted with an oe-blue ring so it reads as the primary
            active field on modal open. */}
        <div className="px-5 py-3 border-b border-border-light shrink-0 bg-oe-blue/[0.04]">
          <label className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-oe-blue mb-1">
            <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-oe-blue text-[9px] font-bold text-white">
              1
            </span>
            {t('bim.target_boq', { defaultValue: 'Target BOQ' })}
          </label>
          <select
            ref={targetBoqRef}
            value={selectedBOQId ?? ''}
            onChange={(e) => setUserSelectedBOQId(e.target.value || null)}
            disabled={boqs.length === 0}
            className="w-full px-2 py-1.5 text-sm rounded border border-oe-blue/50 bg-surface-primary ring-2 ring-oe-blue/20 focus:outline-none focus:ring-2 focus:ring-oe-blue"
          >
            {boqs.length === 0 ? (
              <option value="">
                {t('bim.no_boqs', { defaultValue: 'No BOQs in this project yet' })}
              </option>
            ) : (
              boqs.map((b: BOQ) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))
            )}
          </select>
          {boqs.length === 0 && !boqsQuery.isLoading && (
            <p className="text-[11px] text-rose-600 mt-1">
              {t('bim.no_boqs_help', {
                defaultValue:
                  'Create a BOQ in this project first, then return here to link elements.',
              })}
            </p>
          )}
        </div>

        {/* Step 2 — choose link-vs-create. */}
        <div className="flex px-5 border-b border-border-light shrink-0">
          <TabButton
            active={tab === 'existing'}
            onClick={() => setTab('existing')}
            label={t('bim.tab_link_existing', { defaultValue: 'Link to existing' })}
          />
          <TabButton
            active={tab === 'new'}
            onClick={() => setTab('new')}
            label={t('bim.tab_create_new', { defaultValue: 'Create new position' })}
          />
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {tab === 'existing' ? (
            <div className="p-5">
              {/* Search */}
              <div className="relative mb-3">
                <Search
                  size={13}
                  className="absolute start-2.5 top-1/2 -translate-y-1/2 text-content-quaternary pointer-events-none"
                />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('bim.search_positions', {
                    defaultValue: 'Search positions by ordinal or description…',
                  })}
                  className="w-full ps-8 pe-3 py-1.5 text-sm rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                />
              </div>

              {positionsQuery.isLoading ? (
                <div className="flex items-center justify-center py-8 text-content-tertiary">
                  <Loader2 size={16} className="animate-spin mr-2" />
                  {t('common.loading', { defaultValue: 'Loading…' })}
                </div>
              ) : pickablePositions.length === 0 ? (
                <div className="text-center py-8 text-[11px] text-content-tertiary italic">
                  {positions.length === 0
                    ? t('bim.boq_empty', { defaultValue: 'This BOQ has no positions yet' })
                    : t('bim.no_match', { defaultValue: 'No positions match your search' })}
                </div>
              ) : (
                <ul className="space-y-1 max-h-80 overflow-y-auto">
                  {pickablePositions.map((p) => (
                    <li key={p.id}>
                      <button
                        type="button"
                        onClick={() => linkExistingMut.mutate(p.id)}
                        disabled={busy}
                        className="w-full flex items-center justify-between gap-2 px-2.5 py-1.5 rounded text-start hover:bg-oe-blue/5 border border-transparent hover:border-oe-blue/30 disabled:opacity-50 transition-colors"
                      >
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-[11px] font-mono font-semibold text-content-primary tabular-nums">
                              {p.ordinal}
                            </span>
                            <span className="text-[10px] text-content-tertiary">
                              {p.quantity.toLocaleString()} {p.unit}
                            </span>
                          </div>
                          <div className="text-xs text-content-secondary truncate">
                            {p.description}
                          </div>
                        </div>
                        <Plus size={12} className="text-oe-blue shrink-0" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <div className="p-5 space-y-3">
              <div>
                <Label>{t('bim.form_description', { defaultValue: 'Description' })}</Label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={2}
                  className="w-full px-2 py-1.5 text-sm rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue resize-none"
                />
              </div>

              <div className="grid grid-cols-3 gap-2">
                <div>
                  <Label>{t('bim.form_ordinal', { defaultValue: 'Ordinal' })}</Label>
                  <input
                    type="text"
                    value={ordinal}
                    onChange={(e) => setOrdinal(e.target.value)}
                    placeholder={buildAutoOrdinal(positions)}
                    className="w-full px-2 py-1.5 text-sm rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                  />
                </div>
                <div>
                  <Label>{t('bim.form_quantity', { defaultValue: 'Quantity' })}</Label>
                  <input
                    type="text"
                    value={quantity}
                    onChange={(e) => {
                      setQuantity(e.target.value);
                      setUserEditedQty(true);
                    }}
                    className="w-full px-2 py-1.5 text-sm rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue tabular-nums"
                  />
                </div>
                <div>
                  <Label>{t('bim.form_unit', { defaultValue: 'Unit' })}</Label>
                  <input
                    type="text"
                    value={unit}
                    onChange={(e) => setUnit(e.target.value)}
                    className="w-full px-2 py-1.5 text-sm rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue"
                  />
                </div>
              </div>

              {/* BIM-quantity suggestion badge — shows the source of the
                  pre-filled Quantity value (Σ volume / area / length / count
                  / mass), the inferred unit, and the share of contributing
                  elements.  Low-confidence suggestions (computed mass from
                  density, or no field found) get an amber warning icon. */}
              <BIMQuantitySuggestionBadge
                suggestion={quantitySuggestion}
                userEdited={userEditedQty}
                onResetToSuggestion={() => {
                  setQuantity(quantitySuggestion.value.toFixed(3));
                  setUserEditedQty(false);
                }}
                t={t}
              />

              <div>
                <div className="flex items-center justify-between mb-0.5">
                  <Label>{t('bim.form_unit_rate', { defaultValue: 'Unit rate' })}</Label>
                  {suggestionsQuery.isLoading && (
                    <span className="inline-flex items-center gap-1 text-[10px] text-content-tertiary">
                      <Loader2 size={9} className="animate-spin" />
                      {t('bim.suggesting_costs', {
                        defaultValue: 'Suggesting…',
                      })}
                    </span>
                  )}
                </div>
                <input
                  type="text"
                  value={unitRate}
                  onChange={(e) => setUnitRate(e.target.value)}
                  className="w-full px-2 py-1.5 text-sm rounded border border-border-light bg-surface-primary focus:outline-none focus:ring-1 focus:ring-oe-blue tabular-nums"
                />

                {/* Cost suggestion chips — top-N CWICR matches for this
                    element.  Click any chip to populate description /
                    unit / unit_rate from the matching cost item. */}
                {suggestions.length > 0 && (
                  <div className="mt-2">
                    <div className="flex items-center gap-1 mb-1">
                      <Sparkles size={10} className="text-amber-500" />
                      <span className="text-[10px] font-semibold uppercase tracking-wider text-content-tertiary">
                        {t('bim.cost_suggestions', {
                          defaultValue: 'Suggested rates',
                        })}
                      </span>
                    </div>
                    <ul className="space-y-1">
                      {suggestions.map((s) => {
                        const rateNum =
                          typeof s.unit_rate === 'number'
                            ? s.unit_rate
                            : Number.parseFloat(String(s.unit_rate));
                        const rateLabel = Number.isFinite(rateNum)
                          ? rateNum.toLocaleString(undefined, {
                              minimumFractionDigits: 2,
                              maximumFractionDigits: 2,
                            })
                          : String(s.unit_rate);
                        const confidencePct = Math.round(s.score * 100);
                        const confColor =
                          s.score >= 0.6
                            ? 'bg-emerald-500'
                            : s.score >= 0.35
                              ? 'bg-amber-500'
                              : 'bg-slate-400';
                        return (
                          <li key={s.cost_item_id}>
                            <button
                              type="button"
                              onClick={() => applySuggestion(s)}
                              title={
                                s.match_reasons.length > 0
                                  ? s.match_reasons.join(' • ')
                                  : undefined
                              }
                              className="w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded border border-border-light bg-surface-secondary hover:bg-oe-blue/5 hover:border-oe-blue/40 text-start transition-colors"
                            >
                              <div className="min-w-0 flex-1">
                                <div className="flex items-center gap-1.5">
                                  <span
                                    className={`inline-block h-1.5 w-1.5 rounded-full ${confColor}`}
                                    aria-hidden
                                  />
                                  <span className="text-[10px] font-mono font-semibold text-content-primary">
                                    {s.code}
                                  </span>
                                  <span className="text-[9px] text-content-quaternary tabular-nums">
                                    {confidencePct}%
                                  </span>
                                </div>
                                <div className="text-[11px] text-content-secondary truncate">
                                  {s.description}
                                </div>
                              </div>
                              <div className="text-right shrink-0">
                                <div className="text-xs font-semibold text-content-primary tabular-nums">
                                  {rateLabel}
                                </div>
                                <div className="text-[9px] text-content-tertiary">
                                  / {s.unit}
                                </div>
                              </div>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                )}
              </div>

              <div className="rounded-md border border-oe-blue/20 bg-oe-blue/5 p-2 text-[11px] text-content-secondary">
                <div className="flex items-start gap-1.5">
                  <CheckCircle2 size={11} className="text-oe-blue shrink-0 mt-0.5" />
                  <span>
                    {t('bim.form_note', {
                      defaultValue:
                        'Submitting will create a new BOQ position and link {{count}} BIM element(s) to it in one step.',
                      count: elements.length,
                    })}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between gap-2 px-5 py-3 border-t border-border-light shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="text-xs text-content-tertiary hover:text-content-primary"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </button>
          {tab === 'new' && (
            <button
              type="button"
              onClick={() => createNewMut.mutate()}
              disabled={busy || !selectedBOQId || !description.trim()}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-md bg-oe-blue text-white hover:bg-oe-blue-dark disabled:opacity-50"
            >
              {createNewMut.isPending ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Plus size={12} />
              )}
              {t('bim.form_create_link', { defaultValue: 'Create position and link' })}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

function buildAutoOrdinal(positions: Position[]): string {
  // BIM-sourced positions use a "BIM-NNN" prefix so they can't collide
  // with MasterFormat division ordinals (03, 04, 32.07.1, …) or produce
  // zero-padded ambiguities like "033" (which reads as both "division 33"
  // and "number 33" and then collides on re-submit before the positions
  // list refetches). Scan existing BIM-NNN entries and pick next.
  let maxBim = 0;
  for (const p of positions) {
    const m = /^BIM-(\d+)$/i.exec((p.ordinal || '').trim());
    if (m) {
      const n = Number.parseInt(m[1]!, 10);
      if (n > maxBim) maxBim = n;
    }
  }
  return `BIM-${String(maxBim + 1).padStart(3, '0')}`;
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <label className="block text-[10px] font-semibold uppercase tracking-wider text-content-tertiary mb-0.5">
      {children}
    </label>
  );
}

function TabButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
        active
          ? 'text-oe-blue border-oe-blue'
          : 'text-content-tertiary border-transparent hover:text-content-primary'
      }`}
    >
      {label}
    </button>
  );
}

/* ── BIM-quantity suggestion badge ─────────────────────────────────────── */

/** Renders the auto-suggested quantity provenance ("Σ volume = 17.40 m³ from
 *  3 elements").  Three visual states:
 *
 *   - high confidence    → emerald icon + emerald-tinted border
 *   - medium confidence  → blue icon + blue-tinted border (some elements
 *                          missing the field — partial sum)
 *   - low confidence     → amber AlertTriangle + amber-tinted border + tooltip
 *
 *  When the user has manually edited the Quantity input the badge fades
 *  and exposes a small "use suggestion" button to revert. */
function BIMQuantitySuggestionBadge({
  suggestion,
  userEdited,
  onResetToSuggestion,
  t,
}: {
  suggestion: QuantitySuggestion;
  userEdited: boolean;
  onResetToSuggestion: () => void;
  t: (k: string, opts?: Record<string, unknown>) => string;
}) {
  if (suggestion.source === 'no_elements') return null;

  const isLow = suggestion.confidence === 'low';
  const isMedium = suggestion.confidence === 'medium';
  const tone = isLow
    ? 'bg-amber-50 dark:bg-amber-950/20 border-amber-300/60 dark:border-amber-700/40 text-amber-800 dark:text-amber-300'
    : isMedium
      ? 'bg-oe-blue/5 border-oe-blue/30 text-oe-blue'
      : 'bg-emerald-50 dark:bg-emerald-950/20 border-emerald-300/60 dark:border-emerald-700/40 text-emerald-800 dark:text-emerald-300';

  const icon = isLow ? (
    <AlertTriangle size={11} className="shrink-0" />
  ) : (
    <Sigma size={11} className="shrink-0" />
  );

  const label = formatSuggestionBadge(suggestion);

  // Low-confidence tooltip explains *why* it's low so the estimator
  // knows what to verify before accepting.
  const lowTooltip =
    suggestion.source === 'computed_mass_from_density'
      ? t('bim.qty_low_density', {
          defaultValue:
            'Mass was computed from volume × material density — verify the density value before accepting.',
        })
      : suggestion.source === 'unit_unknown'
      ? t('bim.qty_low_unit', {
          defaultValue:
            'Unit not recognised — falling back to element count. Pick a known unit (m³ / m² / m / kg / pcs / lsum) for a better suggestion.',
        })
      : suggestion.value === 0
      ? t('bim.qty_low_missing', {
          defaultValue:
            'No matching geometric field found on these elements. Check the BIM model has the expected quantity properties.',
        })
      : t('bim.qty_low_generic', {
          defaultValue: 'Low-confidence suggestion — verify before accepting.',
        });

  return (
    <div
      className={`flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-md border text-[11px] ${tone} ${userEdited ? 'opacity-60' : ''}`}
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center gap-1.5 min-w-0 flex-1">
        <span title={isLow ? lowTooltip : undefined} className="inline-flex">
          {icon}
        </span>
        <span className="font-medium truncate" title={label}>
          {label}
        </span>
        {userEdited && (
          <span className="text-[10px] italic text-content-tertiary shrink-0">
            {t('bim.qty_edited_marker', { defaultValue: '(edited)' })}
          </span>
        )}
      </div>
      {userEdited && suggestion.value > 0 && (
        <button
          type="button"
          onClick={onResetToSuggestion}
          className="text-[10px] font-medium underline hover:no-underline shrink-0"
        >
          {t('bim.qty_use_suggestion', { defaultValue: 'Use suggestion' })}
        </button>
      )}
    </div>
  );
}

// unused import marker — keep ESLint happy when apiGet isn't directly used
// (it is indirectly via the boqApi module import above)
void apiGet;
