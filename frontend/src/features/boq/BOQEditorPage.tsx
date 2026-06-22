import React, { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
// lucide-react icons used by sub-components (BOQToolbar, BOQGrid, etc.) — none needed directly here
import { Database, Download, ExternalLink, X, Sparkles, AlertTriangle as WarnTriangle, Lock, Copy, Wallet, Keyboard, GitCompare, RefreshCw, ShieldCheck, FlaskConical, Send, Percent } from 'lucide-react';
import { Button, Badge, Breadcrumb, ModuleHelpButton, ModuleGuideButton, ConfirmDialog, DismissibleInfo, IntroRichText } from '@/shared/ui';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useProgressStore } from '@/shared/ui/GlobalProgress';
import { apiGet, apiPost, triggerDownload, extractErrorMessageFromBody } from '@/shared/lib/api';
import { toNum } from '@/shared/lib/money';
import { useToastStore } from '@/stores/useToastStore';
import { useRecentStore } from '@/stores/useRecentStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useBIMLinkSelectionStore } from '@/stores/useBIMLinkSelectionStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  boqApi,
  groupPositionsIntoSections,
  isSection,
  getPositionDepth,
  normalizePositions,
  normalizePosition,
  type Position,
  type CreatePositionData,
  type UpdatePositionData,
  type Markup,
  type ActivityEntry,
  type CostAutocompleteItem,
  type CopilotAction,
  type CopilotResource,
  DEFAULT_MAX_NESTING_DEPTH,
} from './api';
import { resourceSplitMoneyTotals } from './grid/columnDefs';
import { ApiError } from '@/shared/lib/api';
import { projectsApi, type Project, type ProjectFxRate } from '@/features/projects/api';
import { fetchBIMModels } from '@/features/bim/api';
// AutocompleteInput used in sub-components, not directly here
// import { AutocompleteInput } from './AutocompleteInput';
import { AIChatPanel } from './AIChatPanel';
import { AICostFinderPanel } from './AICostFinderPanel';
import { AISmartPanel } from './AISmartPanel';
import { AIPositionCopilot } from './AIPositionCopilot';
// ClassificationPicker used in sub-components
// import { ClassificationPicker } from './ClassificationPicker';
import { VersionHistoryDrawer } from './VersionHistoryDrawer';
import { ModelLinkPanel } from './ModelLinkPanel';
import { ModelLinkReviewPanel } from './ModelLinkReviewPanel';
import { BOQCompareDrawer } from './BOQCompareDrawer';
import { CostBreakdownPanel } from './CostBreakdownPanel';
import { EstimateClassification } from './EstimateClassification';
import { ResourceSummary } from './ResourceSummary';
import { CommentDrawer, type CommentEntry } from './CommentDrawer';
import { SensitivityChart } from './SensitivityChart';
import { CostRiskPanel } from './CostRiskPanel';
import { MarkupPanel } from './MarkupPanel';
import BOQGrid from './BOQGrid';
import { exportBOQToExcel } from './exportExcel';
import { generateBOQPdf } from './pdfReport';
import type { BOQGridHandle } from './BOQGrid';
import { BatchActionBar } from './BatchActionBar';
import { ScenarioDialog } from './ScenarioDialog';
import { SendToTenderDialog } from './SendToTenderDialog';
import { BOQFilterBar, type BoqFilterKind } from './BOQFilterBar';
import { BOQOutline } from './BOQOutline';
import type { TenderPackageRef } from './api';
import { boqGuide } from './boqGuide';
// evaluateFormula used in BOQGrid, not directly here
// import { evaluateFormula } from './grid/cellEditors';

/* ── Extracted modules ──────────────────────────────────────────────── */

import {
  UNDO_STACK_LIMIT,
  type UndoEntry,
  getVatRate,
  getVatRateFromMarkups,
  getLocaleForRegion,
  getCurrencySymbol,
  getCurrencyCode,
  createFormatter,
  fmtWithCurrency,
  resourceAwareTotalInBase,
  convertToBase,
  computeQualityScore,
  type QualityBreakdown,
  type Tip,
} from './boqHelpers';

import { BOQToolbar } from './BOQToolbar';
import { PriceReviewPanel } from './PriceReviewPanel';
import { ExcelPasteModal, type PastedRow } from './ExcelPasteModal';
import { QualityScoreRing, TipsPanel, QuickAddFAB, EmptyBOQOnboarding, ExportWarningDialog } from './BOQSummaryPanel';
import { ActivityPanel } from './ActivityPanel';
import { CostDatabaseSearchModal, AssemblyPickerModal } from './BOQModals';
import { CatalogPickerModal, type CatalogResource } from './CatalogPickerModal';
import { CustomColumnsDialog } from './CustomColumnsDialog';
import { BOQVariablesDialog } from './BOQVariablesDialog';
import { RenumberDialog } from './RenumberDialog';
import { LinkedPositionsModal } from './LinkedPositionsModal';

/* ── Re-exports for tests ────────────────────────────────────────────── */

export { getVatRate, getLocaleForRegion, getCurrencySymbol, computeQualityScore };
export type { QualityBreakdown };

/**
 * Issue #136 — next collision-free ordinal for a sub-section nested under
 * ``parentOrdinal``. The previous logic only looked at *direct children*
 * and stepped +10 from their max numeric suffix, which collided with any
 * pre-existing ordinal sharing the prefix (e.g. a stray ``01.14`` left
 * behind by an older backend that dropped ``parent_id``) → backend 409,
 * and the user's "Add sub-section" silently did nothing. We now scan
 * EVERY ordinal under the prefix, jump to the next clean multiple of 10,
 * and keep stepping until the candidate is globally unique in the BOQ.
 */
function computeNextSubOrdinal(all: Position[], parentOrdinal: string): string {
  const prefix = `${parentOrdinal}.`;
  const used = new Set(all.map((p) => p.ordinal));
  let maxSuffix = 0;
  for (const p of all) {
    if (!p.ordinal?.startsWith(prefix)) continue;
    const m = p.ordinal.slice(prefix.length).match(/^\d+/);
    if (!m) continue;
    const n = parseInt(m[0], 10);
    if (!Number.isNaN(n) && n > maxSuffix) maxSuffix = n;
  }
  let next = (Math.floor(maxSuffix / 10) + 1) * 10;
  let candidate = `${parentOrdinal}.${String(next).padStart(2, '0')}`;
  while (used.has(candidate)) {
    next += 10;
    candidate = `${parentOrdinal}.${String(next).padStart(2, '0')}`;
  }
  return candidate;
}

/* ══════════════════════════════════════════════════════════════════════ */
/*  BOQEditorPage                                                        */
/* ══════════════════════════════════════════════════════════════════════ */

export function BOQEditorPage() {
  const { t } = useTranslation();
  const { boqId } = useParams<{ boqId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const highlightPositionId = searchParams.get('highlight');
  const { confirm, ...confirmProps } = useConfirm();

  /* ── Data fetching ─────────────────────────────────────────────────── */

  const { data: boq, isLoading } = useQuery({
    queryKey: ['boq', boqId],
    queryFn: () => boqApi.get(boqId!),
    enabled: !!boqId,
    // Keep data fresh for 5 minutes — prevents refetch while user is
    // editing cells in AG Grid (refetch destroys the cell editor and
    // makes typed text disappear mid-keystroke).
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    // Don't spin forever when the network drops — offlineStore (shared/lib/api.ts)
    // serves cached responses; bail out fast if we're offline and there's no cache.
    networkMode: 'offlineFirst',
    retry: (count) => navigator.onLine && count < 2,
    select: (data) => ({
      ...data,
      positions: normalizePositions(data.positions),
    }),
  });

  /* ── Load project for region/currency/locale settings ────────────── */

  const { data: project } = useQuery({
    queryKey: ['project', boq?.project_id],
    queryFn: () => projectsApi.get(boq!.project_id),
    enabled: !!boq?.project_id,
  });

  /* ── Fetch BIM models for the project (used for mini 3D preview) ─── */

  const { data: bimModelsData } = useQuery({
    queryKey: ['bim-models', boq?.project_id],
    queryFn: () => fetchBIMModels(boq!.project_id),
    enabled: !!boq?.project_id,
    staleTime: 10 * 60_000,
  });

  /** First ready BIM model ID — passed to BOQGrid for mini geometry previews. */
  const bimModelId = useMemo(() => {
    const models = bimModelsData?.items;
    if (!models || models.length === 0) return null;
    const ready = models.find((m) => m.status === 'ready' && (m.element_count ?? 0) > 0);
    return ready?.id ?? null;
  }, [bimModelsData]);

  const currencySymbol = useMemo(() => getCurrencySymbol(project?.currency), [project?.currency]);
  const currencyCode = useMemo(() => getCurrencyCode(project?.currency), [project?.currency]);
  const locale = useMemo(() => getLocaleForRegion(project?.region), [project?.region]);
  /**
   * Project FX template (RFC 37 / Issue #93) — flatten to the shape BOQGrid
   * expects (`currency` + numeric `rate`). The API returns `code` and a
   * decimal-precise string, so coerce here once.
   */
  const fxRates = useMemo(
    () =>
      (project?.fx_rates ?? [])
        .map((fx) => ({
          currency: fx.code,
          rate: Number(fx.rate),
          label: fx.label ?? undefined,
        }))
        .filter((fx) => fx.currency && Number.isFinite(fx.rate)),
    [project?.fx_rates],
  );

  // Custom columns from BOQ metadata
  const boqCustomColumns = useMemo(() => {
    const raw = boq as unknown as Record<string, unknown> | undefined;
    const meta = raw?.metadata ?? raw?.metadata_;
    if (!meta || typeof meta !== 'object') return [];
    return (meta as Record<string, unknown>).custom_columns as import('./grid/columnDefs').CustomColumnDef[] ?? [];
  }, [boq]);

  // BOQ-scoped named variables ($GFA, $LABOR_RATE, …) — read from the same
  // metadata bag and forwarded to the grid so calculated custom columns
  // can resolve them. v2.7.0/E.
  const boqVariables = useMemo<import('./api').BOQVariable[]>(() => {
    const raw = boq as unknown as Record<string, unknown> | undefined;
    const meta = raw?.metadata ?? raw?.metadata_;
    if (!meta || typeof meta !== 'object') return [];
    const vs = (meta as Record<string, unknown>).variables;
    if (!Array.isArray(vs)) return [];
    return vs as import('./api').BOQVariable[];
  }, [boq]);
  const fmt = useMemo(
    () => createFormatter(locale),
    [locale],
  );

  const { data: markupsData } = useQuery({
    queryKey: ['boq-markups', boqId],
    queryFn: () => boqApi.getMarkups(boqId!),
    enabled: !!boqId,
    staleTime: 5 * 60_000,
    refetchOnWindowFocus: false,
    retry: (failCount, error) => {
      if (error instanceof ApiError && error.status === 404) return false;
      return failCount < 3;
    },
  });

  const markups: Markup[] = markupsData?.markups ?? [];

  /* Issue #136 — server-enforced deep-nesting cap. Static across the
   * session; the editor disables "add child / sub-section" once a row is
   * this deep and shows an i18n tooltip. Falls back to the mirrored
   * constant so the UI never blocks nesting the backend would accept. */
  const { data: boqLimits } = useQuery({
    queryKey: ['boq-limits'],
    queryFn: () => boqApi.getLimits(),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const maxNestingDepth =
    boqLimits?.max_nesting_depth ?? DEFAULT_MAX_NESTING_DEPTH;

  /**
   * VAT rate driven from the `tax`-category markup row — single source of
   * truth shared with the backend PDF/Excel exports. Returns 0 (No VAT)
   * when no tax markup exists. Never falls back to a country default.
   */
  const vatRate = useMemo(() => getVatRateFromMarkups(markups), [markups]);

  const addToast = useToastStore((s) => s.addToast);
  const removeToast = useToastStore((s) => s.removeToast);
  const addRecent = useRecentStore((s) => s.addRecent);

  /**
   * Issue #157 (skolodi) — persist an FX rate typed in the per-resource
   * currency popover straight into the PROJECT ``fx_rates``.
   *
   * Root cause of the long-standing "section total doesn't update when I
   * change a resource's currency" report: the inline rate editor only wrote
   * to the device-local global FX store, but the section subtotal converts
   * exclusively through the PROJECT ``fx_rates`` table (so does the backend
   * rollup and every export). A rate that never reached the project was
   * therefore invisible to the sum — switching EUR↔USD (neither in the
   * project) produced an identical, unconverted total while ARS (which the
   * user HAD added to the project) recomputed. Writing the rate to the
   * project closes the gap everywhere at once.
   *
   * Optimistically patches the cached project so the grid recomputes the
   * instant the rate is entered; rolls back and warns if the save is
   * rejected (e.g. a viewer without project-edit access).
   */
  const handleUpsertProjectFxRate = useCallback(
    async (code: string, rate: number) => {
      const projectId = boq?.project_id;
      const upper = (code || '').trim().toUpperCase();
      if (!projectId || !upper || !Number.isFinite(rate) || rate <= 0) return;
      const base = getCurrencyCode(project?.currency).toUpperCase();
      if (upper === base) return; // base currency never needs a rate
      const rateStr = String(rate);
      const existing = (project?.fx_rates ?? []) as ProjectFxRate[];
      const has = existing.some((r) => (r.code || '').toUpperCase() === upper);
      const next: ProjectFxRate[] = has
        ? existing.map((r) =>
            (r.code || '').toUpperCase() === upper ? { ...r, rate: rateStr } : r,
          )
        : [...existing, { code: upper, rate: rateStr }];

      const key = ['project', projectId];
      const prev = queryClient.getQueryData<Project>(key);
      queryClient.setQueryData<Project>(key, (p) =>
        p ? { ...p, fx_rates: next } : p,
      );
      try {
        await projectsApi.update(projectId, { fx_rates: next });
        queryClient.invalidateQueries({ queryKey: key });
      } catch {
        // Restore the pre-optimistic project; the device-global store still
        // holds the rate so the resource row keeps showing the conversion.
        if (prev) queryClient.setQueryData<Project>(key, prev);
        addToast({
          type: 'warning',
          title: t('boq.fx_rate_save_failed', {
            defaultValue: 'Could not save the FX rate to the project',
          }),
          message: t('boq.fx_rate_save_failed_hint', {
            defaultValue:
              'The rate is applied on this device but was not saved to the shared project - you may not have edit access. Ask the project owner to add it under Settings → FX rates.',
          }),
        });
      }
    },
    [boq?.project_id, project?.currency, project?.fx_rates, queryClient, addToast, t],
  );

  // Track BOQ as recent item
  useEffect(() => {
    if (boq && boqId) {
      addRecent({
        type: 'boq',
        id: boqId,
        title: boq.name || t('boq.untitled', { defaultValue: 'Untitled BOQ' }),
        url: `/boq/${boqId}`,
      });
    }
  }, [boq, boqId, addRecent]);

  /* ── Batch selection state ──────────────────────────────────────────── */

  const [selectedPositionIds, setSelectedPositionIds] = useState<string[]>([]);
  /**
   * Issue #139 — the partida the user last clicked / keyboard-focused
   * (independent of the checkbox selection). The grid disables
   * click-selection, so without this a plain "click a row then Add
   * Position" left ``selectedPosition`` null and the new row landed at
   * the LAST section instead of below the clicked row.
   */
  const [activePositionId, setActivePositionId] = useState<string | null>(null);
  const handleActiveRowChange = useCallback((id: string | null) => {
    setActivePositionId(id);
  }, []);
  const selectedPosition = useMemo(() => {
    // Prefer an explicit single checkbox selection; otherwise fall back
    // to the row the user is actively working in (clicked / focused) so
    // insert-below-selected works for the common click-then-add flow.
    if (selectedPositionIds.length === 1) {
      return boq?.positions.find((p) => p.id === selectedPositionIds[0]) ?? null;
    }
    if (selectedPositionIds.length === 0 && activePositionId) {
      return boq?.positions.find((p) => p.id === activePositionId) ?? null;
    }
    return null;
  }, [selectedPositionIds, activePositionId, boq?.positions]);
  const boqGridRef = useRef<BOQGridHandle>(null);

  /** Tracks the pending deferred delete so it can be cancelled by undo. */
  const pendingDeleteRef = useRef<{
    timeoutId: ReturnType<typeof setTimeout>;
    positionSnapshot: Position;
    toastId: string;
  } | null>(null);

  /* ── Undo / Redo stacks ───────────────────────────────────────────── */

  const undoStackRef = useRef<UndoEntry[]>([]);
  const redoStackRef = useRef<UndoEntry[]>([]);
  const [undoRedoVersion, setUndoRedoVersion] = useState(0);
  /** Flag to suppress undo recording during undo/redo-triggered mutations. */
  const isUndoRedoInProgressRef = useRef(false);
  /** Stable ref for handleAddPosition — allows keyboard shortcut access before declaration. */
  const addPositionRef = useRef<(() => void) | null>(null);
  /** Stable ref for handleDuplicatePosition — allows keyboard shortcut access before declaration. */
  const duplicatePositionRef = useRef<((id: string) => void) | null>(null);
  /** Stable ref for trackedDelete — allows keyboard shortcut access before declaration. */
  const trackedDeleteRef = useRef<((id: string) => void) | null>(null);
  /** Stable ref for handleExport — allows keyboard shortcut access before declaration. */
  const handleExportRef = useRef<((format: 'excel' | 'csv' | 'pdf' | 'gaeb') => void) | null>(null);
  /** Stable ref for the AI-copilot toggle (Alt+I) — set after declaration so
   *  the keyboard handler can reach it without widening its dependency array. */
  const toggleAICopilotRef = useRef<(() => void) | null>(null);

  // Derived booleans that re-evaluate when undoRedoVersion changes
  const canUndo = undoRedoVersion >= 0 && undoStackRef.current.length > 0;
  const canRedo = undoRedoVersion >= 0 && redoStackRef.current.length > 0;

  /* ── Mutations ─────────────────────────────────────────────────────── */

  /** Invalidate all BOQ-related queries after any data change. */
  const invalidateAll = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
    queryClient.invalidateQueries({ queryKey: ['boq-cost-breakdown', boqId] });
    queryClient.invalidateQueries({ queryKey: ['boq-resource-summary', boqId] });
    queryClient.invalidateQueries({ queryKey: ['boq-markups', boqId] });
    queryClient.invalidateQueries({ queryKey: ['boq-activity', boqId] });
  }, [queryClient, boqId]);

  /**
   * Sibling rollups (cost breakdown, resource summary, markups, activity)
   * depend on totals, so they DO need to refetch after position edits — but
   * each refetch is a small query and firing them on every keystroke commit
   * creates a 5-request waterfall per cell edit. Debounce by 400ms so that
   * a burst of edits collapses into one refresh wave.
   *
   * Crucially, the BIG ['boq', boqId] query is NOT invalidated here — the
   * mutation's onSuccess merges the server response straight into the cache
   * via setQueryData, so we never need a full BOQ refetch after a PATCH.
   */
  const siblingDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const invalidateSiblingsDebounced = useCallback(() => {
    if (siblingDebounceRef.current) clearTimeout(siblingDebounceRef.current);
    siblingDebounceRef.current = setTimeout(() => {
      queryClient.invalidateQueries({ queryKey: ['boq-cost-breakdown', boqId] });
      queryClient.invalidateQueries({ queryKey: ['boq-resource-summary', boqId] });
      queryClient.invalidateQueries({ queryKey: ['boq-markups', boqId] });
      queryClient.invalidateQueries({ queryKey: ['boq-activity', boqId] });
      siblingDebounceRef.current = null;
    }, 400);
  }, [queryClient, boqId]);

  // Cleanup the debounce timer on unmount so we don't fire after teardown.
  useEffect(() => {
    return () => {
      if (siblingDebounceRef.current) {
        clearTimeout(siblingDebounceRef.current);
        siblingDebounceRef.current = null;
      }
    };
  }, []);

  const [newPositionId, setNewPositionId] = useState<string | null>(null);

  const addMutation = useMutation({
    mutationFn: (data: CreatePositionData) => boqApi.addPosition(data),
    onSuccess: (addedPosition) => {
      invalidateAll();
      // Highlight new position and scroll to it
      setNewPositionId(addedPosition.id);
      setTimeout(() => setNewPositionId(null), 3000);
      // Scroll grid to new position after data refetches
      setTimeout(() => {
        const gridApi = boqGridRef.current;
        if (gridApi) {
          try {
            (gridApi as unknown as { clearSelection: () => void }).clearSelection();
          } catch { /* ignore */ }
        }
      }, 500);
      // Issue #127 — when the create collided with an existing project code
      // and reuse applied, the backend returns a LINKED INSTANCE (its own
      // ordinal + own editable quantity) instead of a 409. Surface that
      // clearly so the user understands the code was reused, not rejected.
      if (addedPosition.link_role === 'instance') {
        const sharedCount =
          (typeof addedPosition.linked_instance_count === 'number'
            ? addedPosition.linked_instance_count
            : 0) + 1;
        addToast({
          type: 'success',
          title: t('boq.reuse_code_title', {
            defaultValue: 'Reused code {{code}}',
            code: addedPosition.reference_code ?? addedPosition.ordinal,
          }),
          message: t('boq.reuse_code_msg', {
            defaultValue:
              'Linked instance created - {{count}} positions share this code. Its quantity is independently editable.',
            count: sharedCount,
          }),
        });
      } else {
        addToast({ type: 'success', title: t('boq.position_added', { defaultValue: 'Position added' }), message: t('boq.position_added_edit_hint', { defaultValue: 'Type the description, then Tab through unit, quantity & rate' }) });
        // Open the freshly-added leaf row directly in inline edit on its
        // Description cell so the user types straight away instead of
        // hunting for a cell to click. Skipped on undo/redo restore so a
        // recovered position never pops an unexpected editor.
        if (!isUndoRedoInProgressRef.current) {
          setTimeout(() => boqGridRef.current?.beginEditDescription(addedPosition.id), 250);
        }
      }
      // Record undo entry for the newly added position (skip if triggered by undo/redo)
      if (!isUndoRedoInProgressRef.current) {
        undoStackRef.current.push({
          type: 'add',
          positionId: addedPosition.id,
          oldData: null,
          newData: null,
          positionSnapshot: addedPosition,
        });
        if (undoStackRef.current.length > UNDO_STACK_LIMIT) {
          undoStackRef.current.shift();
        }
        redoStackRef.current = [];
        setUndoRedoVersion((v) => v + 1);
      }
      isUndoRedoInProgressRef.current = false;
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('boq.add_failed', { defaultValue: 'Failed to add position' }), message: err.message });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdatePositionData }) =>
      boqApi.updatePosition(id, data),
    // ── Optimistic update, full pattern (Bug: edit jumps back to old then
    // reappears) ─────────────────────────────────────────────────────────
    // 1. Cancel in-flight ['boq', boqId] refetches so a slow GET that was
    //    issued before the user typed cannot land AFTER setQueryData and
    //    overwrite the optimistic value.
    // 2. Snapshot the previous cache so onError can roll back without a
    //    refetch round-trip (which would also briefly show old values).
    // 3. setQueryData paints the user's edit instantly.
    // 4. onSuccess splices the server response (the authoritative
    //    PositionResponse) into the cache directly — no full BOQ refetch.
    //    Sibling rollups (cost-breakdown, resource-summary, markups,
    //    activity) refresh via a 400ms debounce so a burst of cell edits
    //    collapses into ONE refresh wave instead of 4 GETs per keystroke.
    onMutate: async ({ id, data }: { id: string; data: UpdatePositionData }) => {
      await queryClient.cancelQueries({ queryKey: ['boq', boqId] });
      const previous = queryClient.getQueryData(['boq', boqId]);
      queryClient.setQueryData(['boq', boqId], (old: unknown) => {
        if (!old || typeof old !== 'object') return old;
        const cur = old as { positions: Position[]; [k: string]: unknown };
        return {
          ...cur,
          positions: cur.positions.map((p) => {
            if (p.id !== id) return p;
            const next = { ...p, ...data } as Position;
            if (data.quantity !== undefined || data.unit_rate !== undefined) {
              // Mirror backend semantics (boq/service.py::_compute_total):
              // total = quantity × unit_rate, no VAT, no markups. Markups
              // are layered on top in derived selectors, not stored here.
              next.total = (next.quantity ?? 0) * (next.unit_rate ?? 0);
            }
            if (data.quantity !== undefined) {
              // Manual edit clears BIM/PDF/DWG source badges. The picker /
              // takeoff link callers explicitly include the relevant key in
              // `data.metadata` so we preserve it in that case — that's the
              // signal the new value IS authoritative provenance.
              const incomingMeta = (data.metadata ?? {}) as Record<string, unknown>;
              const preservesBim = 'bim_qty_source' in incomingMeta;
              const preservesPdf = 'pdf_measurement_source' in incomingMeta;
              const preservesDwg = 'dwg_annotation_source' in incomingMeta;
              if (!preservesBim || !preservesPdf || !preservesDwg) {
                const meta = { ...(next.metadata ?? {}) } as Record<string, unknown>;
                if (!preservesBim) delete meta.bim_qty_source;
                if (!preservesPdf) delete meta.pdf_measurement_source;
                if (!preservesDwg) delete meta.dwg_annotation_source;
                next.metadata = meta;
              }
              next.validation_status = 'pending';
            }
            return next;
          }),
        };
      });
      return { previous };
    },
    onSuccess: (updated) => {
      // Splice the authoritative server response straight into the cache.
      // Avoids a full ['boq', boqId] refetch, which on large BOQs is the
      // single biggest source of edit-to-paint latency.
      const normalized = normalizePosition(updated);
      queryClient.setQueryData(['boq', boqId], (old: unknown) => {
        if (!old || typeof old !== 'object') return old;
        const cur = old as { positions: Position[]; [k: string]: unknown };
        return {
          ...cur,
          positions: cur.positions.map((p) => (p.id === normalized.id ? normalized : p)),
        };
      });
      // Sibling rollups depend on totals; refresh them with a debounce so
      // bursts of edits coalesce into a single refresh wave.
      invalidateSiblingsDebounced();

      // ── Issue #127: linked-position feedback ─────────────────────────
      const meta = (normalized.metadata ?? {}) as Record<string, unknown>;
      const prop = meta.link_propagation as
        | {
            propagated_to?: number;
            unlinked?: boolean;
            resource_propagated_to?: number;
          }
        | undefined;

      // (a) Master definition edit fanned out to N linked instances. Those
      // rows live elsewhere in the BOQ (possibly another section) so the
      // spliced single-position cache update above is NOT enough — pull a
      // fresh BOQ so every linked instance repaints with the new definition.
      if (prop && typeof prop.propagated_to === 'number' && prop.propagated_to > 0) {
        queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
        addToast({
          type: 'info',
          title: t('boq.link_propagated_title', {
            defaultValue: 'Definition propagated',
          }),
          message: t('boq.link_propagated_msg', {
            defaultValue:
              'Updated {{count}} linked position(s) across this project.',
            count: prop.propagated_to,
          }),
        });
      }

      // (a2) Issue #133 — a master RESOURCE definition edit fanned out to
      // resource instances on OTHER positions sharing that code. Those
      // rows are elsewhere in the BOQ, so refetch and inform the user.
      if (
        prop &&
        typeof prop.resource_propagated_to === 'number' &&
        prop.resource_propagated_to > 0
      ) {
        queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
        addToast({
          type: 'info',
          title: t('boq.resource_link_propagated_title', {
            defaultValue: 'Resource definition propagated',
          }),
          message: t('boq.resource_link_propagated_msg', {
            defaultValue:
              'Updated the shared resource on {{count}} other position(s) across this project.',
            count: prop.resource_propagated_to,
          }),
        });
      }

      // (b) Editing a linked INSTANCE's definition diverged it — the backend
      // auto-unlinked it (link_role now null) and attached a quality
      // warning. Surface that PROMINENTLY so the user knows this position no
      // longer follows the shared code (customer: "alertar al usuario").
      const warnings = Array.isArray(meta.boq_quality_warnings)
        ? (meta.boq_quality_warnings as unknown[]).filter(
            (w): w is string => typeof w === 'string',
          )
        : [];
      const unlinkWarning = warnings.find((w) =>
        w.toLowerCase().includes('unlinked it from code'),
      );
      if (prop?.unlinked || unlinkWarning) {
        addToast(
          {
            type: 'warning',
            title: t('boq.link_unlinked_title', {
              defaultValue: 'Position unlinked from shared code',
            }),
            message:
              unlinkWarning ??
              t('boq.link_unlinked_msg', {
                defaultValue:
                  'Your edit changed this linked copy, so it no longer follows the shared code. If you did not mean to diverge it, change its code back instead.',
              }),
          },
          { duration: 9000 },
        );
      }
    },
    onError: (err: Error, _vars, ctx) => {
      // Restore the snapshot synchronously — no refetch flicker.
      if (ctx?.previous !== undefined) {
        queryClient.setQueryData(['boq', boqId], ctx.previous);
      }
      addToast({ type: 'error', title: t('boq.update_failed', { defaultValue: 'Failed to update position' }), message: err.message });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => {
      // A section may still have children (incl. nested sub-sections)
      // when deleted via keyboard / undo-redo. Without cascade the
      // backend 409s and the delete silently fails. Leaves are
      // unaffected (no children → cascade is a harmless no-op).
      const target = boq?.positions.find((p) => p.id === id);
      return boqApi.deletePosition(
        id,
        target && isSection(target) ? { cascade: true } : undefined,
      );
    },
    // Don't invalidate the main BOQ query on success — we already removed
    // the position from the cache optimistically in `trackedDelete`. A
    // refetch here would race with concurrent pending deletes (batch
    // delete, rapid sequential deletes) and bring back rows that were
    // optimistically removed but whose API call is still in flight.
    // Sidecar queries (rollups / activity feed) are safe to refresh.
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['boq-cost-breakdown', boqId] });
      queryClient.invalidateQueries({ queryKey: ['boq-resource-summary', boqId] });
      queryClient.invalidateQueries({ queryKey: ['boq-markups', boqId] });
      queryClient.invalidateQueries({ queryKey: ['boq-activity', boqId] });
    },
    onError: (err: Error) => {
      // The server rejected the delete — re-sync the BOQ so the row
      // reappears (otherwise the user sees a phantom-deleted position
      // that's still on the server).
      queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
      addToast({ type: 'error', title: t('boq.delete_failed', { defaultValue: 'Failed to delete position' }), message: err.message });
    },
  });

  const [renumberDialogOpen, setRenumberDialogOpen] = useState(false);

  const renumberMutation = useMutation({
    mutationFn: ({ scheme, pad }: { scheme: 'gap10' | 'gap100' | 'sequential' | 'dotted'; pad: boolean }) =>
      boqApi.renumberPositions(boqId!, { scheme, pad }),
    onSuccess: (result) => {
      invalidateAll();
      setRenumberDialogOpen(false);
      addToast({
        type: 'success',
        title: t('boq.renumber_done', {
          defaultValue: '{{count}} positions renumbered',
          count: result.renumbered,
        }),
        message: t('boq.renumber_done_hint', {
          defaultValue: 'Order preserved - only ordinals were rewritten. Undo with Ctrl+Z is not supported for renumber.',
        }),
      });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('boq.renumber_failed', { defaultValue: 'Renumber failed' }),
        message: err instanceof Error ? err.message : '',
      });
    },
  });

  const lockMutation = useMutation({
    mutationFn: () => apiPost(`/v1/boq/boqs/${boqId}/lock/`, {}),
    onSuccess: () => {
      invalidateAll();
      addToast(
        {
          type: 'success',
          title: t('boq.locked_success', { defaultValue: 'Estimate locked' }),
          message: t('boq.locked_next', { defaultValue: 'Estimate locked. Create project budget?' }),
          action: {
            label: t('boq.create_budget', { defaultValue: 'Create Budget' }),
            onClick: () => createBudgetMutation.mutate(),
          },
        },
        { duration: 8000 },
      );
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('boq.lock_failed', { defaultValue: 'Lock failed' }),
        message: err instanceof Error ? err.message : '',
      });
    },
  });

  const handleLock = useCallback(async () => {
    // Lock is irreversible without admin unlock — confirm before mutating (Bug 8).
    const ok = await confirm({
      title: t('boq.lock_title', { defaultValue: 'Lock estimate?' }),
      message: t('boq.lock_confirm', {
        defaultValue:
          'Lock this estimate? Locked estimates cannot be edited. Unlocking requires admin privileges.',
      }),
      confirmLabel: t('boq.lock', { defaultValue: 'Lock' }),
      variant: 'warning',
    });
    if (!ok) return;
    lockMutation.mutate();
  }, [confirm, lockMutation, t]);

  const unlockMutation = useMutation({
    mutationFn: () => apiPost(`/v1/boq/boqs/${boqId}/unlock/`, {}),
    onSuccess: () => {
      invalidateAll();
      addToast({ type: 'success', title: t('boq.unlocked_success', { defaultValue: 'Estimate unlocked' }) });
    },
    onError: (err) => {
      addToast({ type: 'error', title: t('boq.unlock_failed', { defaultValue: 'Unlock failed' }), message: err instanceof Error ? err.message : '' });
    },
  });

  const handleUnlock = useCallback(() => {
    unlockMutation.mutate();
  }, [unlockMutation]);

  const createBudgetMutation = useMutation({
    mutationFn: () =>
      apiPost<{ created: number; budget_lines_created?: number }>(
        `/v1/boq/boqs/${boqId}/create-budget/`,
        {},
      ),
    onSuccess: (data) => {
      addToast({
        type: 'success',
        title: t('boq.budget_created', { defaultValue: 'Budget created' }),
        // Report both layers: finance budget categories AND the 5D cost-spine
        // budget lines (one per position) the backend now creates alongside.
        message: t('boq.budget_created_desc_full', {
          defaultValue: 'Budget created: {{count}} categories, {{lines}} cost lines',
          count: data.created ?? 0,
          lines: data.budget_lines_created ?? 0,
        }),
      });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('boq.budget_create_failed', { defaultValue: 'Budget creation failed' }),
        message: err instanceof Error ? err.message : '',
      });
    },
  });

  const handleCreateBudget = useCallback(() => {
    createBudgetMutation.mutate();
  }, [createBudgetMutation]);

  const createRevisionMutation = useMutation({
    mutationFn: () => apiPost<{ id: string }>(`/v1/boq/boqs/${boqId}/create-revision/`, {}),
    onSuccess: (result) => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('boq.revision_created', { defaultValue: 'Revision created' }),
      });
      if (result?.id) {
        navigate(`/boq/${result.id}`);
      }
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('boq.revision_failed', { defaultValue: 'Create revision failed' }),
        message: err instanceof Error ? err.message : '',
      });
    },
  });

  const handleCreateRevision = useCallback(() => {
    createRevisionMutation.mutate();
  }, [createRevisionMutation]);

  const handleRenumber = useCallback(() => {
    setRenumberDialogOpen(true);
  }, []);

  const handleRenumberApply = useCallback(
    (scheme: 'gap10' | 'gap100' | 'sequential' | 'dotted', pad: boolean) => {
      renumberMutation.mutate({ scheme, pad });
    },
    [renumberMutation],
  );

  /**
   * Wrap deleteMutation with a 5-second deferred delete.
   * Optimistically removes the position from the UI and shows an undo toast.
   * If the user clicks "Undo" within 5 seconds the position is restored;
   * otherwise the real DELETE API call fires.
   */
  const trackedDelete = useCallback(
    (posId: string) => {
      const posToDelete = boq?.positions.find((p) => p.id === posId);
      if (!posToDelete) {
        deleteMutation.mutate(posId);
        return;
      }

      // If there's already a pending delete, flush it immediately
      if (pendingDeleteRef.current) {
        const prev = pendingDeleteRef.current;
        clearTimeout(prev.timeoutId);
        removeToast(prev.toastId);
        deleteMutation.mutate(prev.positionSnapshot.id);
        pendingDeleteRef.current = null;
      }

      const snapshot = { ...posToDelete };

      // Record undo entry
      undoStackRef.current.push({
        type: 'delete',
        positionId: posId,
        oldData: null,
        newData: null,
        positionSnapshot: snapshot,
      });
      if (undoStackRef.current.length > UNDO_STACK_LIMIT) {
        undoStackRef.current.shift();
      }
      redoStackRef.current = [];
      setUndoRedoVersion((v) => v + 1);

      // Optimistically remove the position from the query cache
      queryClient.setQueryData(['boq', boqId], (old: unknown) => {
        if (!old || typeof old !== 'object') return old;
        const data = old as { positions: Position[]; [key: string]: unknown };
        return {
          ...data,
          positions: data.positions.filter((p: Position) => p.id !== posId),
        };
      });

      // Show undo toast with action button
      const toastId = addToast(
        {
          type: 'info',
          title: t('boq.position_deleted', { defaultValue: 'Position deleted' }),
          action: {
            label: t('common.undo', { defaultValue: 'Undo' }),
            onClick: () => {
              const pending = pendingDeleteRef.current;
              if (pending && pending.toastId === toastId) {
                clearTimeout(pending.timeoutId);
                pendingDeleteRef.current = null;

                // Restore the position in the query cache
                queryClient.setQueryData(['boq', boqId], (old: unknown) => {
                  if (!old || typeof old !== 'object') return old;
                  const data = old as { positions: Position[]; [key: string]: unknown };
                  return {
                    ...data,
                    positions: [...data.positions, snapshot],
                  };
                });

                // Remove the undo entry from the undo stack
                const idx = undoStackRef.current.findIndex(
                  (e) => e.type === 'delete' && e.positionId === posId,
                );
                if (idx !== -1) undoStackRef.current.splice(idx, 1);
                setUndoRedoVersion((v) => v + 1);

                addToast({ type: 'info', title: t('boq.position_restored', { defaultValue: 'Position restored' }) });
              }
            },
          },
        },
        { duration: 5000 },
      );

      // Schedule the real API delete after 5 seconds
      const timeoutId = setTimeout(() => {
        if (pendingDeleteRef.current?.toastId === toastId) {
          pendingDeleteRef.current = null;
          deleteMutation.mutate(posId);
        }
      }, 5000);

      pendingDeleteRef.current = { timeoutId, positionSnapshot: snapshot, toastId };
    },
    [deleteMutation, boq?.positions, queryClient, boqId, addToast, removeToast, t],
  );

  // Bind ref so the keyboard handler can call trackedDelete without a
  // stale-closure dance.
  trackedDeleteRef.current = trackedDelete;

  /** Flush any pending deferred delete when the component unmounts. */
  useEffect(() => {
    return () => {
      const pending = pendingDeleteRef.current;
      if (pending) {
        clearTimeout(pending.timeoutId);
        // Fire the API call so the delete isn't silently lost.
        // Log failures — component is unmounting so toasts may not render.
        boqApi.deletePosition(pending.positionSnapshot.id).catch((err) => {
          if (import.meta.env.DEV) console.error('Failed to flush pending delete on unmount:', err);
        });
        pendingDeleteRef.current = null;
      }
    };
  }, []);

  /* ── Collapsed sections state ──────────────────────────────────────── */

  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set());

  const toggleSection = useCallback((sectionId: string) => {
    setCollapsedSections((prev) => {
      const next = new Set(prev);
      if (next.has(sectionId)) {
        next.delete(sectionId);
      } else {
        next.add(sectionId);
      }
      return next;
    });
  }, []);

  // Expand / collapse every section at once (Row 2 toggle). Collapsing adds
  // every section id (including nested sub-sections) to the collapsed set;
  // expanding clears it.
  const allSectionIds = useMemo(
    () => (boq?.positions ?? []).filter((p) => isSection(p)).map((p) => p.id),
    [boq?.positions],
  );
  const allSectionsCollapsed =
    allSectionIds.length > 0 && allSectionIds.every((id) => collapsedSections.has(id));
  const handleToggleAllSections = useCallback(() => {
    setCollapsedSections((prev) => {
      const allIn = allSectionIds.length > 0 && allSectionIds.every((id) => prev.has(id));
      return allIn ? new Set<string>() : new Set(allSectionIds);
    });
  }, [allSectionIds]);

  /* ── Search + quick QA filters (grid view only) ────────────────────── */
  const [boqSearch, setBoqSearch] = useState('');
  const [boqFilter, setBoqFilter] = useState<BoqFilterKind>('all');
  const filterActive = boqSearch.trim() !== '' || boqFilter !== 'all';

  const totalLeafCount = useMemo(
    () => (boq?.positions ?? []).filter((p) => !isSection(p)).length,
    [boq?.positions],
  );

  // Narrow ONLY the grid view. Totals, exports and the grand total keep using
  // boq.positions, so the headline numbers never move when you filter. We keep
  // matching leaves plus their ancestor sections (so the tree stays coherent),
  // and a section whose name matches the text search is shown with its children.
  const { filteredGridPositions, filterKeepIds } = useMemo(() => {
    const all = boq?.positions ?? [];
    if (!filterActive) return { filteredGridPositions: all, filterKeepIds: new Set<string>() };
    const q = boqSearch.trim().toLowerCase();
    const byId = new Map(all.map((p) => [p.id, p]));
    const childrenByParent = new Map<string | null, Position[]>();
    for (const p of all) {
      const k = p.parent_id ?? null;
      const arr = childrenByParent.get(k);
      if (arr) arr.push(p);
      else childrenByParent.set(k, [p]);
    }
    const passesFilter = (p: Position): boolean => {
      switch (boqFilter) {
        case 'errors':
          return p.validation_status === 'errors';
        case 'no_price':
          return !isSection(p) && (!p.unit_rate || p.unit_rate === 0);
        case 'zero_qty':
          return !isSection(p) && (!p.quantity || p.quantity === 0);
        case 'ai':
          return typeof p.source === 'string' && p.source.toLowerCase().includes('ai');
        default:
          return true;
      }
    };
    const matchesSearch = (p: Position): boolean => {
      if (!q) return true;
      return (
        (p.description ?? '').toLowerCase().includes(q) ||
        (p.ordinal ?? '').toLowerCase().includes(q)
      );
    };
    const keep = new Set<string>();
    const addAncestors = (p: Position) => {
      let parentId = p.parent_id;
      const guard = new Set<string>();
      while (parentId && !guard.has(parentId)) {
        guard.add(parentId);
        const parent = byId.get(parentId);
        if (!parent) break;
        keep.add(parent.id);
        parentId = parent.parent_id;
      }
    };
    const addDescendants = (sectionId: string) => {
      const stack = [sectionId];
      while (stack.length) {
        const id = stack.pop() as string;
        for (const child of childrenByParent.get(id) ?? []) {
          if (!keep.has(child.id)) {
            keep.add(child.id);
            stack.push(child.id);
          }
        }
      }
    };
    for (const p of all) {
      const sec = isSection(p);
      const direct = sec
        ? boqFilter === 'all' && q !== '' && matchesSearch(p)
        : passesFilter(p) && matchesSearch(p);
      if (direct) {
        keep.add(p.id);
        addAncestors(p);
        if (sec) addDescendants(p.id);
      }
    }
    return { filteredGridPositions: all.filter((p) => keep.has(p.id)), filterKeepIds: keep };
  }, [boq?.positions, boqFilter, boqSearch, filterActive]);

  const filteredLeafCount = useMemo(
    () => filteredGridPositions.filter((p) => !isSection(p)).length,
    [filteredGridPositions],
  );

  // While a filter is active, force-open exactly the sections that contain a
  // match (every id in filterKeepIds is a kept ancestor/section) so matching
  // rows are actually rendered - otherwise a collapsed section would hide them
  // while the "X of Y" count still claims they are shown. The user's real
  // collapse state (collapsedSections) is left untouched for when the filter
  // clears.
  const effectiveCollapsedSections = useMemo(
    () =>
      filterActive
        ? new Set([...collapsedSections].filter((id) => !filterKeepIds.has(id)))
        : collapsedSections,
    [filterActive, collapsedSections, filterKeepIds],
  );

  /* ── AI Chat panel ────────────────────────────────────────────────── */

  const [aiChatOpen, setAiChatOpen] = useState(false);
  const [costFinderOpen, setCostFinderOpen] = useState(false);
  const [smartPanelOpen, setSmartPanelOpen] = useState(false);
  /**
   * Per-position AI copilot dock. ``aiCopilotOpen`` controls visibility;
   * ``aiCopilotPositionId`` is the position it acts on. While open the dock
   * follows the active row (see the effect below) so clicking another partida
   * retargets the copilot to it and replays that row's persisted history.
   */
  const [aiCopilotOpen, setAiCopilotOpen] = useState(false);
  const [aiCopilotPositionId, setAiCopilotPositionId] = useState<string | null>(null);
  const [costDbModalOpen, setCostDbModalOpen] = useState(false);
  const [assemblyModalOpen, setAssemblyModalOpen] = useState(false);
  const [excelPasteOpen, setExcelPasteOpen] = useState(false);
  const [customColumnsOpen, setCustomColumnsOpen] = useState(false);
  const [variablesOpen, setVariablesOpen] = useState(false);
  const [isExcelPasteImporting, setIsExcelPasteImporting] = useState(false);
  const [showShortcuts, setShowShortcuts] = useState(false);
  /** When set, the cost DB modal adds a resource to this position instead of creating a new position. */
  const [costDbForPositionId, setCostDbForPositionId] = useState<string | null>(null);

  /** Catalog picker modal state. */
  const [catalogPickerOpen, setCatalogPickerOpen] = useState(false);
  const [catalogForPositionId, setCatalogForPositionId] = useState<string | null>(null);

  // Listen for "From Database" button clicks from child SectionBlock components
  useEffect(() => {
    const handler = () => setCostDbModalOpen(true);
    document.addEventListener('openCostDbModal', handler);
    return () => document.removeEventListener('openCostDbModal', handler);
  }, []);

  // Idle-time prefetch for the cost-DB modal aggregates. The modal calls
  // /v1/costs/regions/ and /v1/costs/category-tree/ on open; both are
  // GROUP BY scans that can take 18 s (regions) and 80+ s (tree) on cold
  // SQLite when the active catalog holds 100 k+ items. Pre-warming them
  // while the BOQ editor is idle keeps the user's first "Add from
  // Database" click instant. requestIdleCallback bails out gracefully on
  // browsers that don't expose it (Safari < 16) by falling back to a
  // 1.5 s setTimeout, late enough to not fight first paint.
  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      if (cancelled) return;
      try {
        await queryClient.prefetchQuery({
          queryKey: ['cost-regions-modal'],
          queryFn: () => apiGet<string[]>('/v1/costs/regions/'),
          staleTime: 5 * 60 * 1000,
        });
        if (cancelled) return;
        const regions = queryClient.getQueryData<string[]>(['cost-regions-modal']) ?? [];
        const firstRegion = regions[0];
        if (firstRegion) {
          const { fetchCategoryTree, fetchCostSearch } = await import('./api');
          // Run the tree + first-page-search prefetches in parallel so we
          // amortize round-trip latency. The modal opens both queries
          // simultaneously when it mounts, and warming both here means
          // the user's first click on "From Database" lands on a hot
          // cache for the THREE heaviest calls (regions / tree / search).
          await Promise.all([
            queryClient.prefetchQuery({
              queryKey: ['cost-tree', firstRegion, 2],
              queryFn: () => fetchCategoryTree(firstRegion, 2),
              staleTime: 5 * 60 * 1000,
            }),
            queryClient.prefetchInfiniteQuery({
              queryKey: ['cost-search', firstRegion, '', ''],
              initialPageParam: null as string | null,
              queryFn: () =>
                fetchCostSearch({
                  region: firstRegion,
                  q: undefined,
                  classification_path: undefined,
                  cursor: null,
                  limit: 15,
                }),
              staleTime: 5 * 60 * 1000,
            }),
          ]);
        }
      } catch {
        /* prefetch is best-effort — never block the editor on a 5xx */
      }
    };
    const w = window as Window & {
      requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
      cancelIdleCallback?: (handle: number) => void;
    };
    let idleId: number | undefined;
    let timeoutId: ReturnType<typeof setTimeout> | undefined;
    if (typeof w.requestIdleCallback === 'function') {
      idleId = w.requestIdleCallback(() => void run(), { timeout: 4000 });
    } else {
      timeoutId = setTimeout(() => void run(), 1500);
    }
    return () => {
      cancelled = true;
      if (idleId !== undefined && typeof w.cancelIdleCallback === 'function') {
        w.cancelIdleCallback(idleId);
      }
      if (timeoutId !== undefined) clearTimeout(timeoutId);
    };
  }, [queryClient]);

  // Scroll to and highlight a position when ?highlight=pos_id is in URL
  // Works with both AG Grid rows (div[row-id]) and legacy table rows (tr[data-position-id])
  useEffect(() => {
    if (!highlightPositionId || !boq) return;
    const timer = setTimeout(() => {
      const row = (
        document.querySelector(`div.ag-row[row-id="${highlightPositionId}"]`) ??
        document.querySelector(`tr[data-position-id="${highlightPositionId}"]`)
      ) as HTMLElement | null;
      if (row) {
        row.scrollIntoView({ behavior: 'smooth', block: 'center' });
        row.classList.add('ring-2', 'ring-oe-blue', 'ring-inset', 'bg-oe-blue-subtle');
        setTimeout(() => {
          row.classList.remove('ring-2', 'ring-oe-blue', 'ring-inset', 'bg-oe-blue-subtle');
        }, 3000);
      }
      setSearchParams((prev) => {
        prev.delete('highlight');
        return prev;
      }, { replace: true });
    }, 500);
    return () => clearTimeout(timer);
  }, [highlightPositionId, boq, setSearchParams]);

  const aiChatContext = useMemo(
    () => ({
      project_name: boq?.name ?? 'Unnamed project',
      // Empty currency / standard means "tell the AI the project doesn't
      // carry one yet, so it can decline to make currency-specific
      // recommendations" — preferable to lying with EUR/din276 on a
      // project that's actually USD/MasterFormat.
      currency: project?.currency ?? '',
      standard: (project as unknown as Record<string, unknown>)?.classification_standard as string ?? '',
      existing_positions_count: boq?.positions.length ?? 0,
    }),
    [boq?.name, boq?.positions.length, project?.currency, project],
  );

  const handleAIAddPositions = useCallback(
    (items: CreatePositionData[]) => {
      for (const item of items) {
        addMutation.mutate(item);
      }
    },
    [addMutation],
  );

  /** Wrap updateMutation to record an undo entry before applying. */
  const trackedUpdate = useCallback(
    (posId: string, newData: UpdatePositionData, oldData: UpdatePositionData) => {
      undoStackRef.current.push({
        type: 'update',
        positionId: posId,
        oldData,
        newData,
      });
      if (undoStackRef.current.length > UNDO_STACK_LIMIT) {
        undoStackRef.current.shift();
      }
      // Clear redo stack on new action
      redoStackRef.current = [];
      setUndoRedoVersion((v) => v + 1);
      updateMutation.mutate({ id: posId, data: newData });
    },
    [updateMutation],
  );

  /* ── Per-position AI copilot ──────────────────────────────────────── */

  /** Open the copilot dock targeting a specific position. */
  const handleOpenAICopilot = useCallback((posId: string) => {
    setAiCopilotPositionId(posId);
    setAiCopilotOpen(true);
  }, []);

  // The inline copilot stays anchored to the position it was opened on (it
  // renders as a full-width row directly under that position). It re-targets
  // only on an explicit reopen (context menu / Alt+I), never on passive row
  // selection, so the panel does not jump around as the user clicks the grid.

  // Alt+I toggle: close if open, else open on the active/selected partida.
  // Wired through a ref so the curated keydown effect can call it without
  // listing every dependency (same pattern as addPositionRef et al.).
  toggleAICopilotRef.current = () => {
    if (aiCopilotOpen) {
      setAiCopilotOpen(false);
      return;
    }
    const target =
      activePositionId ??
      (selectedPositionIds.length === 1 ? selectedPositionIds[0]! : null);
    if (!target) {
      addToast({
        type: 'info',
        title: t('boq.copilot.select_a_position', {
          defaultValue: 'Select a position to open the copilot',
        }),
      });
      return;
    }
    handleOpenAICopilot(target);
  };

  /**
   * Mirror a copilot {@link CopilotAction} into the grid cache + undo stack via
   * ``trackedUpdate`` so every copilot change is Ctrl+Z-undoable and the row
   * repaints immediately.
   *
   * IMPORTANT — no double-apply: the backend already persisted ``auto_applied``
   * actions AND confirmed ``needs_review`` applies (the dock POSTs the latter
   * to /copilot/apply itself). This handler therefore only mirrors into the
   * client; it never issues its own write beyond the trackedUpdate PATCH that
   * keeps the optimistic cache in sync. The PATCH is idempotent with the
   * server's stored value, so re-sending the same after-state is safe.
   *
   * For ``add_resources`` we append to the position's CURRENT resources (read
   * from the cache, not the snapshot the dock passed) and recompute unit_rate =
   * Σ(quantity × unit_rate) over every resource — the exact rollup
   * ``handleCostDbAddResource`` uses — so money/qty never drift.
   */
  const handleCopilotApplyAction = useCallback(
    (action: CopilotAction, fallbackPosition: Position) => {
      // Prefer the live cache row; fall back to the snapshot the dock handed us.
      const pos =
        boq?.positions.find((p) => p.id === fallbackPosition.id) ?? fallbackPosition;
      const posId = pos.id;

      const payload = action.payload ?? {};

      const num = (bag: Record<string, unknown>, key: string): number | undefined => {
        const v = bag[key];
        if (typeof v === 'number' && Number.isFinite(v)) return v;
        if (typeof v === 'string' && v.trim() !== '') {
          const n = Number(v);
          if (Number.isFinite(n)) return n;
        }
        return undefined;
      };
      const str = (bag: Record<string, unknown>, key: string): string | undefined => {
        const v = bag[key];
        return typeof v === 'string' ? v : undefined;
      };

      switch (action.action_type) {
        case 'update_description': {
          const description = str(payload, 'description');
          if (description == null) return;
          trackedUpdate(
            posId,
            { description },
            { description: pos.description },
          );
          break;
        }
        case 'set_quantity': {
          const quantity = num(payload, 'quantity');
          if (quantity == null) return;
          const unit = str(payload, 'unit');
          const newData: UpdatePositionData = { quantity };
          const oldData: UpdatePositionData = { quantity: pos.quantity };
          if (unit != null && unit !== pos.unit) {
            newData.unit = unit;
            oldData.unit = pos.unit;
          }
          trackedUpdate(posId, newData, oldData);
          break;
        }
        case 'set_unit_rate': {
          const unitRate = num(payload, 'unit_rate');
          if (unitRate == null) return;
          const currency = str(payload, 'currency');
          const newData: UpdatePositionData = { unit_rate: unitRate };
          const oldData: UpdatePositionData = { unit_rate: pos.unit_rate };
          // A catalog price carries its own currency — stamp it onto metadata
          // so the row prices in the catalog's native currency (same contract
          // as handleCostDbAddResource's currencyStamp).
          if (currency && currency.trim()) {
            newData.metadata = { ...(pos.metadata ?? {}), currency };
            oldData.metadata = pos.metadata ?? {};
          }
          trackedUpdate(posId, newData, oldData);
          break;
        }
        case 'add_resources': {
          const incoming = Array.isArray(payload.resources)
            ? (payload.resources as CopilotResource[])
            : [];
          if (incoming.length === 0) return;
          const existing = [
            ...((pos.metadata?.resources ?? []) as Array<Record<string, unknown>>),
          ];
          const newResources: Array<Record<string, unknown>> = incoming.map((r) => {
            const quantity = Number(r.quantity) || 0;
            const unitRate = Number(r.unit_rate) || 0;
            const entry: Record<string, unknown> = {
              name: r.name,
              type: r.type || 'material',
              unit: r.unit,
              quantity,
              unit_rate: unitRate,
              total: Math.round(quantity * unitRate * 100) / 100,
            };
            if (r.code) entry.code = r.code;
            if (r.currency && r.currency.trim()) entry.currency = r.currency;
            return entry;
          });
          const merged = [...existing, ...newResources];
          // Recompute unit_rate = Σ(quantity × unit_rate) over ALL resources —
          // identical to handleCostDbAddResource so the rollup stays correct.
          let computedRate = 0;
          for (const r of merged) {
            computedRate +=
              ((r.quantity as number) ?? 0) * ((r.unit_rate as number) ?? 0);
          }
          computedRate = Math.round(computedRate * 100) / 100;
          const newMeta: Record<string, unknown> = {
            ...(pos.metadata ?? {}),
            resources: merged,
          };
          trackedUpdate(
            posId,
            { unit_rate: computedRate, metadata: newMeta },
            { unit_rate: pos.unit_rate, metadata: pos.metadata ?? {} },
          );
          break;
        }
        default:
          break;
      }
    },
    [boq?.positions, trackedUpdate],
  );

  /**
   * Render the inline copilot for the BOQ grid's injected full-width row. The
   * grid calls this for the position the copilot is open on; we look the
   * position up fresh from the cache so applies (which mirror into the cache)
   * flow straight back into the panel.
   */
  const renderInlineCopilot = useCallback(
    (posId: string) => {
      if (!boqId) return null;
      const pos = boq?.positions.find((p) => p.id === posId) ?? null;
      return (
        <AIPositionCopilot
          variant="inline"
          boqId={boqId}
          positionId={posId}
          position={pos}
          isOpen
          onClose={() => setAiCopilotOpen(false)}
          onApplyAction={handleCopilotApplyAction}
        />
      );
    },
    [boqId, boq?.positions, handleCopilotApplyAction],
  );

  /* ── Batch action handlers ──────────────────────────────────────── */

  const handleBatchDelete = useCallback(
    (ids: string[]) => {
      let deleted = 0;
      for (const id of ids) {
        trackedDelete(id);
        deleted++;
      }
      setSelectedPositionIds([]);
      boqGridRef.current?.clearSelection();
      if (deleted > 0) {
        addToast({
          type: 'success',
          title: t('boq.batch_deleted', {
            defaultValue: '{{count}} positions deleted',
            count: String(deleted),
          } as Record<string, string>),
        });
      }
    },
    [trackedDelete, addToast, t],
  );

  const handleBatchChangeUnit = useCallback(
    (ids: string[], unit: string) => {
      for (const id of ids) {
        const pos = boq?.positions.find((p) => p.id === id);
        if (pos) {
          const oldData: UpdatePositionData = { unit: pos.unit };
          const newData: UpdatePositionData = { unit };
          trackedUpdate(id, newData, oldData);
        }
      }
      setSelectedPositionIds([]);
      boqGridRef.current?.clearSelection();
      addToast({
        type: 'success',
        title: t('boq.batch_unit_changed', {
          defaultValue: 'Unit changed to {{unit}} for {{count}} positions',
          unit,
          count: String(ids.length),
        } as Record<string, string>),
      });
    },
    [boq?.positions, trackedUpdate, addToast, t],
  );

  /**
   * Excel-style fill: write an exact unit_rate / quantity onto every selected
   * leaf position. Goes through trackedUpdate so each row keeps its own undo
   * entry and recompute. Section rows are skipped (they carry no money).
   */
  const handleBatchSetValue = useCallback(
    (ids: string[], field: 'unit_rate' | 'quantity', value: number) => {
      if (!boq) return;
      let count = 0;
      for (const id of ids) {
        const pos = boq.positions.find((p) => p.id === id);
        if (!pos || isSection(pos)) continue;
        const oldData: UpdatePositionData =
          field === 'unit_rate' ? { unit_rate: pos.unit_rate } : { quantity: pos.quantity };
        const newData: UpdatePositionData =
          field === 'unit_rate' ? { unit_rate: value } : { quantity: value };
        trackedUpdate(id, newData, oldData);
        count++;
      }
      setSelectedPositionIds([]);
      boqGridRef.current?.clearSelection();
      addToast({
        type: 'success',
        title: t('boq.batch_set_value_done', {
          defaultValue: 'Updated {{count}} positions',
          count: String(count),
        } as Record<string, string>),
      });
    },
    [boq, trackedUpdate, addToast, t],
  );

  /**
   * v3.12.0 Stream A — multiply unit_rate / quantity on every selected row
   * via the bulk-update endpoint (one PATCH covers all ids, one umbrella
   * audit row is written). Cache invalidation refreshes the grid so the
   * recomputed totals land immediately.
   */
  const handleBatchFactor = useCallback(
    async (ids: string[], kind: 'rate' | 'quantity', factor: number) => {
      if (!boqId || ids.length === 0) return;
      try {
        const result = await boqApi.bulkUpdatePositions(boqId, {
          ids,
          ...(kind === 'rate' ? { rate_factor: factor } : { quantity_factor: factor }),
        });
        queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
        queryClient.invalidateQueries({ queryKey: ['boq-activity', boqId] });
        setSelectedPositionIds([]);
        boqGridRef.current?.clearSelection();
        addToast({
          type: result.skipped === 0 ? 'success' : 'warning',
          title: t('boq.batch_factor_done', {
            defaultValue: 'Updated {{count}} positions (factor {{factor}})',
            count: String(result.updated),
            factor: String(factor),
          } as Record<string, string>),
          message:
            result.skipped > 0
              ? t('boq.batch_factor_skipped', {
                  defaultValue: '{{count}} positions could not be updated.',
                  count: String(result.skipped),
                } as Record<string, string>)
              : undefined,
        });
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : String(e);
        addToast({
          type: 'error',
          title: t('boq.batch_factor_failed', {
            defaultValue: 'Bulk update failed',
          }),
          message: msg,
        });
      }
    },
    [boqId, queryClient, addToast, t],
  );

  /**
   * Find-and-replace across the descriptions of every selected row via the
   * bulk-update endpoint. The server rewrites each description and skips rows
   * with no match, so the toast reports updated vs. unchanged counts.
   */
  const handleBatchFindReplace = useCallback(
    async (ids: string[], find: string, replace: string, caseSensitive: boolean) => {
      if (!boqId || ids.length === 0 || !find) return;
      try {
        const result = await boqApi.bulkUpdatePositions(boqId, {
          ids,
          find_replace: { field: 'description', find, replace, case_sensitive: caseSensitive },
        });
        queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
        queryClient.invalidateQueries({ queryKey: ['boq-activity', boqId] });
        setSelectedPositionIds([]);
        boqGridRef.current?.clearSelection();
        // `unchanged` = benign no-match rows; `skipped` = genuine failures
        // (locked / validation). Report each with its own wording.
        const noMatch = result.unchanged ?? 0;
        const failed = result.skipped ?? 0;
        addToast({
          type: failed > 0 ? 'warning' : 'success',
          title: t('boq.batch_find_replace_done', {
            defaultValue: 'Updated {{count}} descriptions',
            count: String(result.updated),
          } as Record<string, string>),
          message:
            failed > 0
              ? t('boq.batch_find_replace_failed_some', {
                  defaultValue: '{{count}} rows could not be updated.',
                  count: String(failed),
                } as Record<string, string>)
              : noMatch > 0
                ? t('boq.batch_find_replace_skipped', {
                    defaultValue: '{{count}} rows had no match.',
                    count: String(noMatch),
                  } as Record<string, string>)
                : undefined,
        });
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : String(e);
        addToast({
          type: 'error',
          title: t('boq.batch_find_replace_failed', { defaultValue: 'Find and replace failed' }),
          message: msg,
        });
      }
    },
    [boqId, queryClient, addToast, t],
  );

  /**
   * v3.12.0 Stream A — set classification on every selected row. Writes
   * `{[standard]: code}` over the existing classification object so
   * pre-set codes in OTHER standards survive (a position can carry
   * DIN 276 + MasterFormat simultaneously).
   */
  const handleBatchSetClassification = useCallback(
    async (ids: string[], standard: string, code: string) => {
      if (!boqId || ids.length === 0) return;
      try {
        const classifications: Record<string, Record<string, string>> = {};
        for (const id of ids) {
          const existing = (boq?.positions.find((p) => p.id === id)?.classification ??
            {}) as Record<string, string>;
          classifications[id] = { ...existing, [standard]: code };
        }
        // Fan out via the per-row PATCH so each row keeps its other-standard
        // codes. The bulk endpoint cannot mass-merge a per-row dict; reusing
        // trackedUpdate also feeds the undo stack.
        for (const id of ids) {
          const oldData: UpdatePositionData = {
            classification: (boq?.positions.find((p) => p.id === id)
              ?.classification ?? {}) as Record<string, string>,
          };
          const newData: UpdatePositionData = {
            classification: classifications[id],
          };
          trackedUpdate(id, newData, oldData);
        }
        setSelectedPositionIds([]);
        boqGridRef.current?.clearSelection();
        addToast({
          type: 'success',
          title: t('boq.batch_class_done', {
            defaultValue: 'Classification {{standard}}:{{code}} set on {{count}} positions',
            standard,
            code,
            count: String(ids.length),
          } as Record<string, string>),
        });
      } catch (e) {
        const msg = e instanceof ApiError ? e.message : String(e);
        addToast({
          type: 'error',
          title: t('boq.batch_class_failed', {
            defaultValue: 'Classification update failed',
          }),
          message: msg,
        });
      }
    },
    [boqId, boq?.positions, trackedUpdate, addToast, t],
  );

  const handleClearSelection = useCallback(() => {
    setSelectedPositionIds([]);
    setActivePositionId(null);
    boqGridRef.current?.clearSelection();
  }, []);

  /* ── Cross-highlight bridge to BIM viewer ───────────────────────── */
  const setBOQLinkSelection = useBIMLinkSelectionStore((s) => s.setBOQSelection);
  const clearBIMLinkSelection = useBIMLinkSelectionStore((s) => s.clear);
  const bimSelectedElementIds = useBIMLinkSelectionStore((s) => s.selectedBIMElementIds);
  /** Position ID to scroll-to-and-flash when a BIM mesh click arrives. */
  const [bimScrollTargetId, setBimScrollTargetId] = useState<string | undefined>(undefined);

  const handleSelectionChanged = useCallback(
    (ids: string[]) => {
      setSelectedPositionIds(ids);
      // Publish to the cross-highlight store so the BIM viewer lights up
      // linked elements in orange. Only single-row selection drives it —
      // multi-select clears any existing highlight.
      if (ids.length === 1) {
        const pos = boq?.positions.find((p) => p.id === ids[0]);
        const cadIds = pos?.cad_element_ids ?? [];
        setBOQLinkSelection(pos?.id ?? null, cadIds);
      } else {
        setBOQLinkSelection(null, []);
      }
    },
    [boq?.positions, setBOQLinkSelection],
  );

  // Clear the cross-highlight store on unmount or when switching BOQs so
  // the BIM viewer doesn't keep a stale highlight from a different BOQ.
  useEffect(() => {
    return () => clearBIMLinkSelection();
  }, [boqId, clearBIMLinkSelection]);

  // Viewer → editor: when the user clicks a mesh in the BIM viewer, scroll
  // to the first BOQ position whose `cad_element_ids` contains that ID.
  useEffect(() => {
    if (bimSelectedElementIds.length === 0) {
      setBimScrollTargetId(undefined);
      return;
    }
    const positions = boq?.positions ?? [];
    const bimIdSet = new Set(bimSelectedElementIds);
    const match = positions.find((p) =>
      (p.cad_element_ids ?? []).some((cid) => bimIdSet.has(cid)),
    );
    if (match) setBimScrollTargetId(match.id);
  }, [bimSelectedElementIds, boq?.positions]);

  const handleUndo = useCallback(() => {
    const entry = undoStackRef.current.pop();
    if (!entry) return;
    redoStackRef.current.push(entry);
    setUndoRedoVersion((v) => v + 1);

    if (entry.type === 'update' && entry.oldData) {
      updateMutation.mutate({ id: entry.positionId, data: entry.oldData });
    } else if (entry.type === 'add') {
      // Undo add = delete the position that was added
      isUndoRedoInProgressRef.current = true;
      deleteMutation.mutate(entry.positionId);
    } else if (entry.type === 'delete' && entry.positionSnapshot) {
      // Undo delete = re-create the position from snapshot
      isUndoRedoInProgressRef.current = true;
      const snap = entry.positionSnapshot;
      addMutation.mutate({
        boq_id: boqId!,
        ordinal: snap.ordinal,
        description: snap.description,
        unit: snap.unit,
        quantity: parseFloat(String(snap.quantity)) || 0,
        unit_rate: parseFloat(String(snap.unit_rate)) || 0,
        parent_id: snap.parent_id || undefined,
      });
    }
    addToast({ type: 'info', title: t('boq.undone', { defaultValue: 'Undone' }) });
  }, [updateMutation, deleteMutation, addMutation, boqId, addToast, t]);

  const handleRedo = useCallback(() => {
    const entry = redoStackRef.current.pop();
    if (!entry) return;
    undoStackRef.current.push(entry);
    setUndoRedoVersion((v) => v + 1);

    if (entry.type === 'update' && entry.newData) {
      updateMutation.mutate({ id: entry.positionId, data: entry.newData });
    } else if (entry.type === 'add' && entry.positionSnapshot) {
      // Redo add = re-create the position
      isUndoRedoInProgressRef.current = true;
      const snap = entry.positionSnapshot;
      addMutation.mutate({
        boq_id: boqId!,
        ordinal: snap.ordinal,
        description: snap.description,
        unit: snap.unit,
        quantity: parseFloat(String(snap.quantity)) || 0,
        unit_rate: parseFloat(String(snap.unit_rate)) || 0,
        parent_id: snap.parent_id || undefined,
      });
    } else if (entry.type === 'delete') {
      // Redo delete = delete the position again
      isUndoRedoInProgressRef.current = true;
      deleteMutation.mutate(entry.positionId);
    }
    addToast({ type: 'info', title: t('boq.redone', { defaultValue: 'Redone' }) });
  }, [updateMutation, deleteMutation, addMutation, boqId, addToast, t]);

  /** Container ref for keyboard shortcut listener. */
  const editorContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Skip shortcuts when user is editing a cell / input / textarea
      const tag = (document.activeElement?.tagName ?? '').toLowerCase();
      const isEditing =
        tag === 'input' || tag === 'textarea' || tag === 'select' ||
        (document.activeElement as HTMLElement)?.isContentEditable === true;

      // F1 — show shortcuts overlay (always works, even during editing)
      if (e.key === 'F1') {
        e.preventDefault();
        setShowShortcuts((v) => !v);
        return;
      }

      // Ctrl+Shift+? — show shortcuts overlay (always works)
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === '?') {
        e.preventDefault();
        setShowShortcuts((v) => !v);
        return;
      }

      // Ctrl+Z / Cmd+Z = Undo
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key === 'z') {
        e.preventDefault();
        handleUndo();
        return;
      }
      // Ctrl+Y / Ctrl+Shift+Z / Cmd+Shift+Z = Redo
      if (
        ((e.ctrlKey || e.metaKey) && e.key === 'y') ||
        ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'z') ||
        ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'Z')
      ) {
        e.preventDefault();
        handleRedo();
        return;
      }
      // Ctrl+Shift+V = Paste from Excel modal
      if ((e.ctrlKey || e.metaKey) && e.shiftKey && (e.key === 'V' || e.key === 'v')) {
        e.preventDefault();
        setExcelPasteOpen(true);
        return;
      }
      // Ctrl+Enter / Cmd+Enter = Add new position
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault();
        addPositionRef.current?.();
        return;
      }

      // App-level Ctrl-shortcuts must fire even while editing a cell
      // (same as Ctrl+S in spreadsheets) — guard placed below them.
      // #153 guard — e.key can be undefined for synthetic / IME events.
      const k = (e.key ?? '').toLowerCase();
      const codeLetter = (e.code ?? '').startsWith('Key') ? (e.code ?? '').slice(3).toLowerCase() : '';
      const isCmd = e.ctrlKey || e.metaKey;

      // Ctrl+E = Open export menu (use e.code so non-US keyboard layouts
      // still match — e.g. AZERTY where 'e' is at a different KeyE slot
      // but the physical key is the same).
      if (isCmd && !e.shiftKey && (k === 'e' || codeLetter === 'e')) {
        e.preventDefault();
        e.stopPropagation();
        handleExportRef.current?.('excel');
        return;
      }
      // Ctrl+I = Open import dialog
      if (isCmd && !e.shiftKey && (k === 'i' || codeLetter === 'i')) {
        e.preventDefault();
        e.stopPropagation();
        importInputRef.current?.click();
        return;
      }
      // Ctrl+L = Toggle lock/unlock
      if (isCmd && !e.shiftKey && (k === 'l' || codeLetter === 'l')) {
        e.preventDefault();
        e.stopPropagation();
        if (boq?.is_locked) {
          handleUnlock();
        } else {
          handleLock();
        }
        return;
      }
      // Ctrl+/ = Toggle AI chat panel. e.code can be 'Slash' (US) or
      // 'IntlRo'/'Minus' on other layouts — match e.key as primary and
      // e.code='Slash' as the layout-aware fallback.
      if (isCmd && (e.key === '/' || e.code === 'Slash')) {
        e.preventDefault();
        e.stopPropagation();
        setAiChatOpen((prev) => {
          if (!prev) { setCostFinderOpen(false); setSmartPanelOpen(false); }
          return !prev;
        });
        return;
      }

      // Guard remaining shortcuts — don't fire when editing cells
      if (isEditing) return;

      // Alt+I = Toggle the per-position AI copilot dock on the active row.
      // Alt (not Ctrl/Cmd) keeps it clear of Ctrl+I (import). Match e.code so
      // non-US layouts still hit the physical I key.
      if (e.altKey && !isCmd && !e.shiftKey && (k === 'i' || codeLetter === 'i')) {
        e.preventDefault();
        e.stopPropagation();
        toggleAICopilotRef.current?.();
        return;
      }

      // Delete / Backspace = delete selected position(s). Fires the same
      // tracked-delete pipeline as the context menu / batch-bar, so undo
      // toast + 5s deferred API call still apply.
      if ((e.key === 'Delete' || e.key === 'Backspace') && selectedPositionIds.length > 0) {
        e.preventDefault();
        for (const id of selectedPositionIds) {
          trackedDeleteRef.current?.(id);
        }
        return;
      }

      // Ctrl+D = Duplicate selected position
      if (isCmd && !e.shiftKey && (k === 'd' || codeLetter === 'd')) {
        e.preventDefault();
        if (selectedPositionIds.length === 1) {
          duplicatePositionRef.current?.(selectedPositionIds[0]!);
        }
        return;
      }
    }

    // Use capture phase so AG Grid's cell-editor handlers can't swallow
    // these app-level shortcuts before we see them.
    document.addEventListener('keydown', handleKeyDown, true);
    return () => document.removeEventListener('keydown', handleKeyDown, true);
  }, [handleUndo, handleRedo, selectedPositionIds, handleLock, handleUnlock, boq?.is_locked]);

  /* ── Activity panel ───────────────────────────────────────────────── */

  const [activityOpen, setActivityOpen] = useState(false);

  const { data: activityData } = useQuery({
    queryKey: ['boq-activity', boqId],
    queryFn: () => boqApi.getActivity(boqId!),
    enabled: !!boqId,
    retry: (failCount, error) => {
      if (error instanceof ApiError && error.status === 404) return false;
      return failCount < 3;
    },
    refetchInterval: activityOpen ? 30_000 : false,
  });

  const activities: ActivityEntry[] = activityData?.activities ?? [];

  /* ── Export / Version History state ─────────────────────────────────── */

  const [showVersionHistory, setShowVersionHistory] = useState(false);
  const [exportWarning, setExportWarning] = useState<{ format: 'excel' | 'csv' | 'pdf' | 'gaeb'; score: number } | null>(null);
  const [gaebPreviewOpen, setGaebPreviewOpen] = useState(false);

  /* ── Computed data ─────────────────────────────────────────────────── */

  const positions = boq?.positions ?? [];
  const grouped = useMemo(() => {
    if (!boq) return { sections: [], ungrouped: [] };
    return groupPositionsIntoSections(boq.positions);
  }, [boq]);

  /* ── Position drag-and-drop reordering ─────────────────────────── */

  const reorderMutation = useMutation({
    mutationFn: (positionIds: string[]) => boqApi.reorderPositions(boqId!, positionIds),
    onSuccess: () => {
      invalidateAll();
      addToast({
        type: 'success',
        title: t('boq.positions_reordered', { defaultValue: 'Positions reordered' }),
      });
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('boq.reorder_failed', { defaultValue: 'Failed to reorder positions' }),
        message: e.message,
      });
    },
  });

  const handleReorderPositions = useCallback(
    (reorderedIds: string[]) => {
      if (!boq || reorderedIds.length === 0) return;
      reorderMutation.mutate(reorderedIds);
    },
    [boq, reorderMutation],
  );

  /* ── Section reorder (drag section onto another section) ─────── */
  const handleReorderSections = useCallback(
    (fromId: string, toId: string) => {
      if (!boq) return;
      const sectionIds = grouped.sections.map((g) => g.section.id);
      const fromIdx = sectionIds.indexOf(fromId);
      const toIdx = sectionIds.indexOf(toId);
      if (fromIdx === -1 || toIdx === -1) return;
      const reordered = [...sectionIds];
      reordered.splice(fromIdx, 1);
      reordered.splice(toIdx, 0, fromId);
      // Build full position order: sections interleaved with their children
      const fullOrder: string[] = [];
      for (const secId of reordered) {
        fullOrder.push(secId);
        const group = grouped.sections.find((g) => g.section.id === secId);
        if (group) {
          for (const child of group.children) fullOrder.push(child.id);
        }
      }
      // Include ungrouped at the end
      for (const pos of grouped.ungrouped) fullOrder.push(pos.id);
      reorderMutation.mutate(fullOrder);
    },
    [boq, grouped, reorderMutation],
  );

  /* ── Delete section with all its positions ──────────────────── */
  const handleDeleteSection = useCallback(
    async (sectionId: string) => {
      if (!boq) return;
      // Count descendants for the toast by walking the flat parent_id
      // tree — the `grouped` view is flat and never lists nested
      // sub-sections, so it can't be relied on here.
      const childrenByParent = new Map<string, string[]>();
      for (const p of boq.positions) {
        if (!p.parent_id) continue;
        const arr = childrenByParent.get(p.parent_id);
        if (arr) arr.push(p.id);
        else childrenByParent.set(p.parent_id, [p.id]);
      }
      let descendantCount = 0;
      const stack = [...(childrenByParent.get(sectionId) ?? [])];
      while (stack.length > 0) {
        const id = stack.pop()!;
        descendantCount += 1;
        const kids = childrenByParent.get(id);
        if (kids) stack.push(...kids);
      }
      const ok = await confirm({
        title: t('boq.delete_section_title', {
          defaultValue: 'Delete section?',
        }),
        message: t('boq.confirm_delete_section', {
          defaultValue:
            'Delete this section and all {{count}} positions inside it?',
          count: descendantCount,
        }),
        confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
        variant: 'danger',
      });
      if (!ok) return;
      // One recursive cascade delete — the backend removes the whole
      // subtree (nested sub-sections + their positions) leaves-first.
      // The previous per-child loop relied on the flat `grouped` view,
      // which never lists nested sub-sections, so deleting a sub-section
      // that contained another sub-section 409'd and was silently
      // swallowed ("sub-section delete doesn't work").
      try {
        await boqApi.deletePosition(sectionId, { cascade: true });
      } catch (err) {
        addToast({
          type: 'error',
          title: t('boq.section_delete_failed', {
            defaultValue: 'Failed to delete section',
          }),
          message: err instanceof Error ? err.message : undefined,
        });
        return;
      }
      invalidateAll();
      addToast({
        type: 'success',
        title: t('boq.section_deleted', {
          defaultValue: 'Section deleted with {{count}} positions',
          count: descendantCount,
        }),
      });
    },
    [boq, confirm, invalidateAll, addToast, t],
  );

  /* Build flat position list for keyboard navigation — reserved for future use
  const flatPositionIds = useMemo(() => {
    const ids: string[] = [];
    for (const pos of grouped.ungrouped) ids.push(pos.id);
    for (const group of grouped.sections) {
      if (!collapsedSections.has(group.section.id)) {
        for (const child of group.children) ids.push(child.id);
      }
    }
    return ids;
  }, [grouped, collapsedSections]); */

  const directCost = useMemo(() => {
    if (!boq) return 0;
    // Issue #111 (skolodi follow-up) — rebase per-position currencies into
    // the project base before summing. ``resourceAwareTotalInBase`` covers
    // BOTH a position-level ``metadata.currency`` (verified #131 path) AND
    // the previously-missed case: a position with NO metadata.currency but
    // foreign-currency ``metadata.resources`` (its stored total was built
    // from Σ(r.qty×r.rate) with no FX, so summing it raw added a USD
    // resource into an ARS project as if "1 USD = 1 ARS").
    return boq.positions.reduce((sum, p) => {
      return (
        sum +
        resourceAwareTotalInBase(
          p as unknown as {
            total?: number | string | null;
            quantity?: number | string | null;
            metadata?: Record<string, unknown> | null;
          },
          currencyCode,
          fxRates,
        )
      );
    }, 0);
  }, [boq, currencyCode, fxRates]);

  const markupTotals = useMemo(() => {
    let running = directCost;
    return markups
      .filter((m) => m.is_active !== false && m.category !== 'tax')
      .map((m) => {
        let amount = 0;
        if (m.markup_type === 'fixed') {
          // fixed_amount arrives as a Decimal-as-string ("500.00"); coerce
          // before arithmetic so ``running += amount`` adds rather than
          // string-concatenating (which poisoned the footer + Excel/PDF totals).
          amount = toNum(m.fixed_amount);
        } else if (m.apply_to === 'cumulative' || m.apply_to === 'subtotal') {
          // 'subtotal' shares the cumulative base on the server (direct cost +
          // preceding markups); keep the footer Net Total / VAT / gross in step
          // with the authoritative grand total for GAEB-imported tax markups.
          amount = running * (m.percentage / 100);
        } else {
          amount = directCost * (m.percentage / 100);
        }
        running += amount;
        return { ...m, amount, runningTotal: running };
      });
  }, [directCost, markups]);

  const netTotal = useMemo(() => {
    if (markupTotals.length === 0) return directCost;
    const last = markupTotals[markupTotals.length - 1];
    return last ? last.runningTotal : directCost;
  }, [directCost, markupTotals]);

  const vatAmount = netTotal * vatRate;
  const grossTotal = netTotal + vatAmount;

  /* ── Display currency (Issue #88) ─────────────────────────────────────
   *  Lets the user flip the entire BOQ visualisation between the project's
   *  base currency and any FX-rate'd currency without persisting anything
   *  server-side. Empty string ⇒ render in base. Non-empty ⇒ convert all
   *  monetary aggregates (per-position total, section subtotals, footer
   *  rows, grand total) through the FX rate.
   *
   *  Editing-safety: per-position `unit_rate` is intentionally NOT
   *  reformatted because each position can have its own source currency
   *  (v2.6.1) — overriding it would break the per-position-currency model.
   *  `total` cells are already non-editable in the column definition, so
   *  no edit-while-converted hazards in this view-only mode.
   *
   *  Persistence: the choice is remembered per-BOQ in localStorage so the
   *  user doesn't have to re-pick on every page load. Cleared automatically
   *  when the picked currency disappears from the project's FX rate list. */
  const displayCurrencyKey = boqId ? `boq:displayCurrency:${boqId}` : null;
  const [displayCurrency, setDisplayCurrencyState] = useState<string>(() => {
    if (!displayCurrencyKey) return '';
    try {
      return localStorage.getItem(displayCurrencyKey) ?? '';
    } catch {
      return '';
    }
  });
  const setDisplayCurrency = useCallback((next: string) => {
    setDisplayCurrencyState(next);
    if (!displayCurrencyKey) return;
    try {
      if (next) localStorage.setItem(displayCurrencyKey, next);
      else localStorage.removeItem(displayCurrencyKey);
    } catch { /* localStorage unavailable / quota — silently ignore */ }
  }, [displayCurrencyKey]);
  /* ── Resource cost-driver split columns (Material/Labor/Equipment %) ──
   *  A view preference, remembered globally in localStorage so the user
   *  keeps their chosen layout across BOQs. Off by default - the three
   *  percentage columns only appear once the user enables them from the
   *  toolbar's Grid Settings menu. */
  const RESOURCE_SPLIT_KEY = 'oe_boq_show_resource_split';
  const [showResourceSplit, setShowResourceSplit] = useState<boolean>(() => {
    try {
      return localStorage.getItem(RESOURCE_SPLIT_KEY) === '1';
    } catch {
      return false;
    }
  });
  const toggleResourceSplit = useCallback(() => {
    setShowResourceSplit((prev) => {
      const next = !prev;
      try {
        if (next) localStorage.setItem(RESOURCE_SPLIT_KEY, '1');
        else localStorage.removeItem(RESOURCE_SPLIT_KEY);
      } catch { /* localStorage unavailable / quota — silently ignore */ }
      return next;
    });
  }, []);

  const displayCurrencyMeta = useMemo(() => {
    if (!displayCurrency) return null;
    const fx = fxRates.find((f) => f.currency === displayCurrency);
    if (!fx || !Number.isFinite(fx.rate) || fx.rate <= 0) return null;
    return fx;
  }, [displayCurrency, fxRates]);
  // If the persisted choice no longer exists in the FX-rate list (rate
  // removed at project level), drop it transparently so the BOQ doesn't
  // get stuck rendering in a phantom currency. Wait until the project
  // query has actually loaded — otherwise the empty fxRates array on
  // initial render would wipe the persisted choice every reload.
  useEffect(() => {
    if (!project) return;
    if (displayCurrency && !displayCurrencyMeta) {
      setDisplayCurrency('');
    }
  }, [project, displayCurrency, displayCurrencyMeta, setDisplayCurrency]);
  // FX rates store rate-to-base, so converting from base → display is
  // ``base_amount / rate``. Example: base ARS, rate.USD = 1200 ⇒ 12 000 ARS
  // shown as 10 USD.
  const grossTotalDisplay = displayCurrencyMeta
    ? grossTotal / displayCurrencyMeta.rate
    : grossTotal;
  const displaySymbol = displayCurrencyMeta ? displayCurrencyMeta.currency : currencySymbol;

  /* ── Quality score ───────────────────────────────────────────────── */

  const qualityBreakdown = useMemo(
    () => computeQualityScore(boq?.positions ?? [], markups),
    [boq?.positions, markups],
  );

  /* ── Mini summary bar stats ─────────────────────────────────────── */

  const miniSummaryStats = useMemo(() => {
    const allPositions = boq?.positions ?? [];
    const sectionCount = grouped.sections.length;
    const positionCount = allPositions.filter((p) => !isSection(p)).length;
    const errorCount = allPositions.filter(
      (p) => !isSection(p) && p.validation_status === 'errors',
    ).length;
    const warningCount = allPositions.filter(
      (p) => !isSection(p) && p.validation_status === 'warnings',
    ).length;
    return { sectionCount, positionCount, errorCount, warningCount };
  }, [boq?.positions, grouped.sections.length]);

  /* ── Tips (contextual) ───────────────────────────────────────────── */

  const tips: Tip[] = useMemo(() => {
    const all: Tip[] = [
      {
        id: 'tip_sections',
        text: t('boq.tip_sections', { defaultValue: 'Add sections to organize your estimate (e.g., Foundations, Walls, Roof)' }),
        condition: 'no_sections',
      },
      {
        id: 'tip_keyboard',
        text: t('boq.tip_tab', { defaultValue: 'Use Tab to move between fields, Enter to save changes' }),
        condition: 'always',
      },
      {
        id: 'tip_context_menu',
        text: t('boq.tip_menu', { defaultValue: 'Click the (...) menu on a section to add positions or delete it' }),
        condition: 'always',
      },
      {
        id: 'tip_markups',
        text: t('boq.tip_markups', { defaultValue: 'Add markups for overhead costs and profit using the Markups section below the table' }),
        condition: 'no_markups',
      },
      {
        id: 'tip_descriptions',
        text: t('boq.tip_autocomplete', { defaultValue: 'Fill in descriptions for all positions - start typing to see suggestions from the cost database' }),
        condition: 'has_empty_descriptions',
      },
    ];

    const sectionCount = grouped.sections.length;
    const items = (boq?.positions ?? []).filter((p) => p.unit && p.unit.trim() !== '' && p.unit.trim().toLowerCase() !== 'section');
    const hasEmptyDescs = items.some((p) => !p.description || p.description.trim() === '');

    return all.filter((tip) => {
      if (tip.condition === 'always') return true;
      if (tip.condition === 'no_sections' && sectionCount === 0) return true;
      if (tip.condition === 'no_markups' && markups.length === 0 && items.length > 0) return true;
      if (tip.condition === 'has_empty_descriptions' && hasEmptyDescs) return true;
      return false;
    });
  }, [boq?.positions, markups, grouped.sections.length, t]);

  /* ── Handlers ──────────────────────────────────────────────────────── */

  const sectionMutation = useMutation({
    mutationFn: (data: { ordinal: string; description: string; parent_id?: string | null }) =>
      boqApi.addSection(boqId!, data),
    onSuccess: () => {
      invalidateAll();
      addToast({ type: 'success', title: t('boq.section_added', { defaultValue: 'Section added' }) });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('boq.section_add_failed', { defaultValue: 'Failed to add section' }), message: err.message });
    },
  });

  /**
   * Issue #136 — create a sub-section nested under ``parentSectionId``.
   * Backend enforces the depth cap; the grid already disables the menu
   * item at the cap, so this is a straightforward nested create. The
   * ordinal is derived from the parent + its existing direct sub-sections
   * (gap-of-10, mirroring handleAddPosition).
   */
  const handleAddSubSection = useCallback(
    (parentSectionId: string) => {
      if (!boqId) return;
      const all = boq?.positions ?? [];
      const parent = all.find((p) => p.id === parentSectionId);
      const parentOrdinal = parent?.ordinal ?? '01';
      const ordinal = computeNextSubOrdinal(all, parentOrdinal);
      sectionMutation.mutate({ ordinal, description: '', parent_id: parentSectionId });
    },
    [boqId, boq?.positions, sectionMutation],
  );

  /** Section name modal */
  const [showSectionModal, setShowSectionModal] = useState(false);
  const [sectionNameInput, setSectionNameInput] = useState('');
  /**
   * Issue #136 — chosen parent for the new section ('' = top level).
   * Pre-fillable so the section row's "Add sub-section" action can open
   * this same modal with the parent already selected.
   */
  const [sectionParentInput, setSectionParentInput] = useState<string>('');

  /**
   * Issue #136 — every existing section offered as a parent, indented by
   * its depth so the hierarchy is obvious, and disabled when a child under
   * it would breach ``maxNestingDepth`` (server-enforced too).
   */
  const sectionParentChoices = useMemo(() => {
    const all = boq?.positions ?? [];
    const map = new Map(all.map((p) => [p.id, p]));
    return all
      .filter((p) => isSection(p))
      .sort((a, b) =>
        (a.ordinal || '').localeCompare(b.ordinal || '', undefined, { numeric: true }),
      )
      .map((p) => {
        const depth0 = getPositionDepth(p, map); // 0-based ancestor count
        const childTier = depth0 + 2; // parent tier (depth0+1) + 1 for the child
        const name = (
          p.description ||
          t('boq.untitled_section', { defaultValue: 'Untitled section' })
        ).slice(0, 48);
        return {
          id: p.id,
          disabled: childTier > maxNestingDepth,
          label: `${'  '.repeat(Math.min(depth0, 7))}${p.ordinal || ''}  ${name}`,
        };
      });
  }, [boq?.positions, maxNestingDepth, t]);

  const handleAddSection = useCallback(
    (parentSectionId?: unknown) => {
      if (!boqId) return;
      // Callers wired as onClick={onAddSection} pass a MouseEvent — only a
      // real string id preselects a parent; anything else = top level.
      const pid = typeof parentSectionId === 'string' ? parentSectionId : '';
      setSectionNameInput('');
      setSectionParentInput(pid);
      setShowSectionModal(true);
    },
    [boqId],
  );

  const handleConfirmAddSection = useCallback(() => {
    if (!boqId) return;
    const pid = sectionParentInput || '';
    if (pid) {
      // Nested section — collision-free ordinal under the parent
      // (shared with handleAddSubSection).
      const all = boq?.positions ?? [];
      const parent = all.find((p) => p.id === pid);
      const parentOrdinal = parent?.ordinal ?? '01';
      const ordinal = computeNextSubOrdinal(all, parentOrdinal);
      sectionMutation.mutate({ ordinal, description: sectionNameInput || '', parent_id: pid });
    } else {
      const ordinal = String(grouped.sections.length + 1).padStart(2, '0');
      sectionMutation.mutate({ ordinal, description: sectionNameInput || '' });
    }
    setShowSectionModal(false);
    setSectionNameInput('');
    setSectionParentInput('');
  }, [
    boqId,
    boq?.positions,
    grouped.sections.length,
    sectionMutation,
    sectionNameInput,
    sectionParentInput,
  ]);

  const handleAddPosition = useCallback(
    (parentId?: string) => {
      if (!boqId) return;
      const allPositions = boq?.positions ?? [];

      /* Generate the next ordinal using the standard "gap-of-10" scheme
       * common in German/Austrian AVA software:
       *
       *   01.10, 01.20, 01.30, …            ← child positions
       *   01, 02, 03, …                     ← top-level sections
       *   0010, 0020, …                     ← top-level positions (no section)
       *
       * The +10 gap lets the user later insert 01.15 between 01.10 and 01.20
       * without renumbering everything. We look at the LARGEST existing
       * sibling ordinal (parsed) and add 10 — that way ordinals stay sorted
       * even if previous ones were manually edited. */

      const nextChildOrdinal = (parentOrdinal: string, siblings: Position[]): string => {
        // Pick the largest numeric suffix among siblings (e.g. "01.30" → 30)
        let maxSuffix = 0;
        const prefix = `${parentOrdinal}.`;
        for (const sib of siblings) {
          if (!sib.ordinal?.startsWith(prefix)) continue;
          const suffix = parseInt(sib.ordinal.slice(prefix.length), 10);
          if (!isNaN(suffix) && suffix > maxSuffix) maxSuffix = suffix;
        }
        const nextSuffix = maxSuffix + 10;
        return `${parentOrdinal}.${String(nextSuffix).padStart(2, '0')}`;
      };

      /* Issue #139 — when inserting *between* two siblings, pick an ordinal
       * that sorts strictly between them by halving the gap on the trailing
       * numeric segment (e.g. "01.20" + "01.30" → "01.25"). Returns null
       * when the two share no common prefix or the integer gap is too tight
       * to fit a clean value — the caller then falls back to the gap-of-10
       * append ordinal (placement stays correct via sort_order regardless). */
      const splitOrdinal = (ord: string): [string, string] => {
        const dot = ord.lastIndexOf('.');
        return dot === -1 ? ['', ord] : [ord.slice(0, dot + 1), ord.slice(dot + 1)];
      };
      const interpolateOrdinal = (prev: string, next: string): string | null => {
        const [pPre, pNum] = splitOrdinal(prev);
        const [nPre, nNum] = splitOrdinal(next);
        if (pPre !== nPre) return null;
        const a = parseInt(pNum, 10);
        const b = parseInt(nNum, 10);
        if (isNaN(a) || isNaN(b)) return null;
        const mid = Math.floor((a + b) / 2);
        if (mid <= a || mid >= b) return null;
        const width = Math.max(pNum.length, nNum.length);
        return `${pPre}${String(mid).padStart(width, '0')}`;
      };

      // Issue #134 — when invoked without an explicit parent (the
      // Ctrl+Enter shortcut, or the toolbar "Add Position" button),
      // insert into the SELECTED row's section instead of always the
      // last section. A selected section → add as its child; a selected
      // child → add as a sibling in the same section. Falls through to
      // the last-section default below only when nothing is selected.
      //
      // Issue #139 — a selected *leaf* additionally pins the new partida
      // directly below that row (after_position_id) and gets an ordinal
      // interpolated between it and the next sibling, instead of being
      // appended at the section's end.
      const explicitParentId = parentId;
      let afterPositionId: string | undefined;
      if (!parentId && selectedPosition) {
        if (isSection(selectedPosition)) {
          parentId = selectedPosition.id;
        } else {
          parentId = selectedPosition.parent_id ?? undefined;
          afterPositionId = selectedPosition.id;
        }
      }

      let ordinal: string;

      if (afterPositionId && selectedPosition && !explicitParentId) {
        // Find the sibling rendered immediately after the selected leaf
        // (siblings ordered by sort_order, then ordinal — mirrors the grid).
        const siblings = allPositions
          .filter((p) => (p.parent_id ?? null) === (selectedPosition.parent_id ?? null))
          .sort((a, b) =>
            a.sort_order !== b.sort_order
              ? a.sort_order - b.sort_order
              : (a.ordinal ?? '').localeCompare(b.ordinal ?? '', undefined, { numeric: true }),
          );
        const selIdx = siblings.findIndex((p) => p.id === selectedPosition.id);
        const nextSibling = selIdx >= 0 ? siblings[selIdx + 1] : undefined;
        const interpolated =
          nextSibling && selectedPosition.ordinal && nextSibling.ordinal
            ? interpolateOrdinal(selectedPosition.ordinal, nextSibling.ordinal)
            : null;
        if (interpolated) {
          ordinal = interpolated;
        } else {
          // No clean room (or selected is the last sibling): keep the
          // gap-of-10 append label; sort_order still places it correctly.
          const parentSection = parentId
            ? allPositions.find((p) => p.id === parentId)
            : undefined;
          const parentOrdinal = parentSection?.ordinal ?? '01';
          ordinal = parentId
            ? nextChildOrdinal(
                parentOrdinal,
                allPositions.filter((p) => p.parent_id === parentId),
              )
            : (() => {
                let maxTop = 0;
                for (const p of allPositions) {
                  const num = parseInt(p.ordinal ?? '', 10);
                  if (!isNaN(num) && num > maxTop) maxTop = num;
                }
                return String((Math.floor(maxTop / 10) + 1) * 10).padStart(4, '0');
              })();
        }
      } else if (parentId) {
        const parentSection = allPositions.find((p) => p.id === parentId);
        const parentOrdinal = parentSection?.ordinal ?? '01';
        const siblings = allPositions.filter((p) => p.parent_id === parentId);
        ordinal = nextChildOrdinal(parentOrdinal, siblings);
      } else {
        // Add to last section, or generate top-level ordinal
        const lastSection = grouped.sections[grouped.sections.length - 1];
        if (lastSection) {
          parentId = lastSection.section.id;
          ordinal = nextChildOrdinal(lastSection.section.ordinal, lastSection.children);
        } else {
          // No sections — generate a unique top-level ordinal in 4-digit gap-of-10
          let maxTop = 0;
          for (const p of allPositions) {
            const num = parseInt(p.ordinal ?? '', 10);
            if (!isNaN(num) && num > maxTop) maxTop = num;
          }
          const next = (Math.floor(maxTop / 10) + 1) * 10;
          ordinal = String(next).padStart(4, '0');
        }
      }

      addMutation.mutate({
        boq_id: boqId,
        ordinal,
        description: '',
        unit: 'm2',
        quantity: 0,
        unit_rate: 0,
        parent_id: parentId,
        // Issue #127 — register a reusable code mirroring the ordinal so this
        // position can later be reused elsewhere via "Reuse existing code…".
        reference_code: ordinal,
        // Issue #139 — pin the new row directly below the selected leaf.
        after_position_id: afterPositionId ?? null,
      });
      addToast({
        type: 'info',
        title: t('boq.empty_position_quality_hint', {
          defaultValue: 'Empty position lowers Quality Score until quantity & rate are filled',
        }),
      });
    },
    [boqId, boq, grouped, selectedPosition, addMutation, addToast, t],
  );

  /**
   * Issue #127 — reuse an existing project code. Prompts for a code, then
   * creates a LINKED INSTANCE via the create endpoint (`link_mode: 'link'`).
   * The backend copies the master definition + child subtree, assigns a
   * fresh unique ordinal, and keeps an independently-editable quantity. The
   * addMutation.onSuccess handler surfaces the reuse toast.
   */
  const handleReuseCode = useCallback(
    (parentId?: string) => {
      if (!boqId) return;
      const allPositions = boq?.positions ?? [];
      const known = Array.from(
        new Set(
          allPositions
            .map((p) => p.reference_code || p.ordinal)
            .filter((c): c is string => !!c),
        ),
      ).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
      const code = window
        .prompt(
          t('boq.reuse_code_prompt', {
            defaultValue:
              'Enter an existing code to reuse it here (its definition & sub-items are copied; quantity stays independent):',
          }) +
            (known.length > 0
              ? `\n\n${t('boq.reuse_code_existing', {
                  defaultValue: 'Existing codes: {{codes}}',
                  codes: known.slice(0, 40).join(', '),
                })}`
              : ''),
          '',
        )
        ?.trim();
      if (!code) return;

      // Resolve a placement parent (mirror handleAddPosition's default).
      // Issue #134 — prefer the selected row's section over the last one.
      let targetParent = parentId;
      if (!targetParent && selectedPosition) {
        targetParent = isSection(selectedPosition)
          ? selectedPosition.id
          : (selectedPosition.parent_id ?? undefined);
      }
      if (!targetParent) {
        const lastSection = grouped.sections[grouped.sections.length - 1];
        if (lastSection) targetParent = lastSection.section.id;
      }

      // Provisional ordinal — the backend assigns its own unique ordinal for
      // a reused code; this is just the create payload's required field.
      let maxTop = 0;
      for (const p of allPositions) {
        const num = parseInt(p.ordinal ?? '', 10);
        if (!isNaN(num) && num > maxTop) maxTop = num;
      }
      const provisionalOrdinal = String(
        (Math.floor(maxTop / 10) + 1) * 10,
      ).padStart(4, '0');

      addMutation.mutate({
        boq_id: boqId,
        ordinal: provisionalOrdinal,
        description: '',
        unit: 'm2',
        quantity: 0,
        unit_rate: 0,
        parent_id: targetParent,
        reference_code: code,
        link_mode: 'link',
      });
    },
    [boqId, boq, grouped, selectedPosition, addMutation, t],
  );

  /* ── Issue #127: linked-positions modal + unlink ──────────────────── */
  const [linksModalFor, setLinksModalFor] = useState<{
    id: string;
    ordinal: string;
  } | null>(null);

  const handleShowLinks = useCallback(
    (positionId: string) => {
      const pos = (boq?.positions ?? []).find((p) => p.id === positionId);
      setLinksModalFor({ id: positionId, ordinal: pos?.ordinal ?? '' });
    },
    [boq],
  );

  // ── Feature 1: model→quantity binding + review ─────────────────────────
  const [modelLinkFor, setModelLinkFor] = useState<{
    id: string;
    ordinal: string;
  } | null>(null);
  const [modelReviewOpen, setModelReviewOpen] = useState(false);

  const handleModelLink = useCallback(
    (positionId: string) => {
      const pos = (boq?.positions ?? []).find((p) => p.id === positionId);
      setModelLinkFor({ id: positionId, ordinal: pos?.ordinal ?? '' });
    },
    [boq],
  );

  // ── Feature 2: estimate baseline / line-level compare ──────────────────
  const [compareOpen, setCompareOpen] = useState(false);

  // What-if scenario + send-to-tender dialogs, and the "jump to markups"
  // signal that re-opens the (collapsible) markup panel below the grid.
  const [scenarioOpen, setScenarioOpen] = useState(false);
  const [tenderOpen, setTenderOpen] = useState(false);
  const [markupOpenSignal, setMarkupOpenSignal] = useState(0);

  // Top-level sections inside the current selection. Empty means the tender
  // dialog packages the whole BOQ (the backend treats [] as every section).
  const selectedSectionIds = useMemo(
    () =>
      (boq?.positions ?? [])
        .filter((p) => selectedPositionIds.includes(p.id) && isSection(p) && !p.parent_id)
        .map((p) => p.id),
    [boq?.positions, selectedPositionIds],
  );

  const handleJumpToMarkups = useCallback(() => {
    setMarkupOpenSignal((n) => n + 1);
    // Defer so the panel re-expands before we scroll it into view.
    requestAnimationFrame(() => {
      document
        .getElementById('boq-markups-panel')
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }, []);

  // Outline: jump the grid to a section header and flash it.
  const handleOutlineJump = useCallback((positionId: string) => {
    boqGridRef.current?.scrollToPosition(positionId);
  }, []);

  const handleScenarioCreated = useCallback(
    (newBoqId: string) => {
      setScenarioOpen(false);
      navigate(`/boq/${newBoqId}`);
    },
    [navigate],
  );

  const setActiveProject = useProjectContextStore((s) => s.setActiveProject);
  const handleTenderCreated = useCallback(
    (pkg: TenderPackageRef) => {
      setTenderOpen(false);
      // The package is created under the BOQ's project, which may differ from
      // the globally active project. Point the project context at it so the
      // tendering page's package list (keyed on the active project) includes
      // the new package before we deep-link to it.
      if (boq?.project_id) setActiveProject(boq.project_id, project?.name ?? '');
      navigate(`/tendering?package=${pkg.id}`);
    },
    [navigate, setActiveProject, boq?.project_id, project?.name],
  );

  const unlinkMutation = useMutation({
    mutationFn: (positionId: string) => boqApi.unlinkPosition(positionId),
    onSuccess: (updated) => {
      // Unlink may promote another instance to master and detaches this row
      // value-preserving — repaint the whole BOQ so every member's badge,
      // role and counts are correct.
      invalidateAll();
      setLinksModalFor(null);
      addToast({
        type: 'success',
        title: t('boq.unlink_done_title', {
          defaultValue: 'Position unlinked',
        }),
        message: t('boq.unlink_done_msg', {
          defaultValue:
            'Code {{code}} kept. This position no longer follows the shared code; its values were preserved.',
          code: updated.reference_code ?? updated.ordinal,
        }),
      });
    },
    onError: (err) => {
      addToast({
        type: 'error',
        title: t('boq.unlink_failed', {
          defaultValue: 'Failed to unlink position',
        }),
        message: err instanceof Error ? err.message : '',
      });
    },
  });

  const handleUnlinkPosition = useCallback(
    (positionId: string) => {
      unlinkMutation.mutate(positionId);
    },
    [unlinkMutation],
  );

  // Keep ref in sync for keyboard shortcut access
  addPositionRef.current = handleAddPosition;

  /** Actually perform the export (download file). */
  const doExport = useCallback(
    async (format: 'excel' | 'csv' | 'pdf' | 'gaeb') => {
      // Client-side Excel export via SheetJS
      if (format === 'excel' && positions.length > 0) {
        try {
          const markupTotalsForExport = markupTotals.map((m) => ({
            name: m.name,
            percentage: m.percentage,
            amount: m.amount,
          }));
          await exportBOQToExcel({
            boqTitle: boq?.name ?? 'BOQ',
            projectName: project?.name,
            classificationStandard: project?.classification_standard,
            region: project?.region,
            // Use the project base currency ISO code (was a stray ``boq.currency``
            // that doesn't exist \u2192 always fell back to "\u20ac"). Issue #150: also
            // thread the base currency + FX rates so foreign-currency resources
            // are converted to base in the export exactly as in the grid.
            currency: currencyCode,
            baseCurrency: currencyCode,
            fxRates,
            positions,
            markupTotals: markupTotalsForExport,
            netTotal,
            vatRate,
            vatAmount,
            grossTotal,
          });
          addToast({ type: 'success', title: t('boq.file_downloaded', { defaultValue: 'File downloaded' }) });
          return;
        } catch {
          // Fall through to server-side export
        }
      }

      // Client-side PDF export via jsPDF (skip for very large BOQs to avoid
      // browser memory issues — let the server handle them with a simplified report)
      const LARGE_BOQ_THRESHOLD = 500;
      const nonSectionPositions = positions.filter((p) => !isSection(p));
      if (format === 'pdf' && nonSectionPositions.length > 0 && nonSectionPositions.length <= LARGE_BOQ_THRESHOLD) {
        try {
          const markupTotalsForExport = markupTotals.map((m) => ({
            name: m.name,
            percentage: m.percentage,
            amount: m.amount,
          }));
          generateBOQPdf({
            boqTitle: boq?.name ?? 'BOQ',
            projectName: project?.name,
            date: new Date().toISOString(),
            currency: currencySymbol,
            // Issue #150 — convert foreign-currency resources to the project
            // base in the PDF totals exactly as the grid does. ``directCost``
            // (passed above) is already resource-aware base-converted.
            baseCurrency: currencyCode,
            fxRates,
            positions,
            markupTotals: markupTotalsForExport,
            directCost,
            netTotal,
            vatRate,
            vatAmount,
            grossTotal,
            locale,
          });
          addToast({ type: 'success', title: t('boq.file_downloaded', { defaultValue: 'File downloaded' }) });
          return;
        } catch {
          // Fall through to server-side export
        }
      }

      const token = useAuthStore.getState().accessToken;
      const r = await fetch(`/api/v1/boq/boqs/${boqId}/export/${format}/`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (r.ok) {
        const blob = await r.blob();
        const extensions: Record<string, string> = {
          excel: 'xlsx', csv: 'csv', pdf: 'pdf', gaeb: 'xml',
        };
        triggerDownload(blob, `${boq?.name ?? 'boq'}.${extensions[format] ?? format}`);
        addToast({ type: 'success', title: t('boq.file_downloaded', { defaultValue: 'File downloaded' }) });
      } else {
        let errorMsg = t('boq.export_failed', { defaultValue: 'Export failed' });
        try {
          const errBody = await r.json();
          if (errBody?.detail) {
            errorMsg = errBody.detail;
          }
        } catch {
          // Response was not JSON — use default message
        }
        addToast({ type: 'error', title: errorMsg });
      }
    },
    [boqId, boq, positions, markups, directCost, netTotal, addToast, t],
  );

  /** Pre-export validation check: warn if quality < 60%, GAEB preview before export. */
  const handleExport = useCallback(
    (format: 'excel' | 'csv' | 'pdf' | 'gaeb') => {
      // Show GAEB confirmation dialog before quality check
      if (format === 'gaeb') {
        setGaebPreviewOpen(true);
        return;
      }
      const score = qualityBreakdown.score;
      if (score < 60) {
        setExportWarning({ format, score });
      } else {
        doExport(format);
      }
    },
    [qualityBreakdown.score, doExport],
  );
  // Keep ref in sync for keyboard shortcut access
  handleExportRef.current = handleExport;

  /** Confirm GAEB export after preview dialog. */
  const confirmGaebExport = useCallback(() => {
    setGaebPreviewOpen(false);
    const score = qualityBreakdown.score;
    if (score < 60) {
      setExportWarning({ format: 'gaeb', score });
    } else {
      doExport('gaeb');
    }
  }, [qualityBreakdown.score, doExport]);

  const [isValidating, setIsValidating] = useState(false);
  const [lastValidationScore, setLastValidationScore] = useState<number | null>(null);

  const handleValidate = useCallback(async () => {
    const token = useAuthStore.getState().accessToken;
    setIsValidating(true);
    useProgressStore.getState().start();
    try {
      const r = await fetch(`/api/v1/boq/boqs/${boqId}/validate/`, {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!r.ok) {
        const errBody = await r.json().catch(() => ({}));
        throw new Error(errBody?.detail || `Validation request failed (HTTP ${r.status})`);
      }
      const result = await r.json();
      const scoreNum = typeof result?.score === 'number' ? Math.round(result.score * 100) : null;
      setLastValidationScore(scoreNum);
      const errors: Array<{ rule_id: string; message: string }> = result?.errors ?? [];
      const warnings: Array<{ rule_id: string; message: string }> = result?.warnings ?? [];
      const passed: number = result?.passed?.length ?? 0;

      const toastType = errors.length > 0 ? 'error' : warnings.length > 0 ? 'warning' : 'success';

      // Build human-readable summary
      const parts: string[] = [];
      if (scoreNum != null) {
        parts.push(t('boq.validation_score', { defaultValue: 'Quality score: {{score}}%', score: scoreNum }));
      }
      if (errors.length > 0) {
        parts.push(t('boq.validation_errors', { defaultValue: '{{count}} errors found', count: errors.length }));
        // Show first 2 error messages
        errors.slice(0, 2).forEach(e => parts.push(`  - ${e.message}`));
      }
      if (warnings.length > 0) {
        parts.push(t('boq.validation_warnings', { defaultValue: '{{count}} warnings', count: warnings.length }));
      }
      if (errors.length === 0 && warnings.length === 0) {
        parts.push(t('boq.validation_all_passed', { defaultValue: 'All {{count}} checks passed', count: passed }));
      }

      addToast({
        type: toastType,
        title: toastType === 'success'
          ? t('boq.validation_passed', { defaultValue: 'Validation passed' })
          : toastType === 'warning'
            ? t('boq.validation_warnings_title', { defaultValue: 'Validation warnings' })
            : t('boq.validation_errors_title', { defaultValue: 'Validation errors' }),
        message: parts.join('\n'),
      });
      invalidateAll();
    } catch (err) {
      addToast({
        type: 'error',
        title: t('boq.validation_failed', { defaultValue: 'Validation failed' }),
        message:
          err instanceof Error && err.message
            ? err.message
            : t('boq.validation_failed_hint', { defaultValue: 'Could not connect to validation service.' }),
      });
    } finally {
      setIsValidating(false);
      useProgressStore.getState().done();
    }
  }, [boqId, addToast, t, invalidateAll]);

  const [isRecalculating, setIsRecalculating] = useState(false);
  const [showRecalcConfirm, setShowRecalcConfirm] = useState(false);

  const doRecalculate = useCallback(async () => {
    if (!boqId) return;
    setShowRecalcConfirm(false);
    setIsRecalculating(true);
    useProgressStore.getState().start();
    try {
      // Step 1: Enrich — match positions to cost database items and attach resource breakdowns
      let enrichedCount = 0;
      try {
        const enrichResult = await boqApi.enrichResources(boqId);
        enrichedCount = enrichResult.enriched_count;
        // enrichResult.total_positions available for future progress tracking
      } catch {
        // Enrich endpoint not available — skip
      }

      // Step 2: Recalculate — recompute unit_rate = sum(resource costs) for each position
      const result = await boqApi.recalculateRates(boqId);

      // Build informative summary
      const parts: string[] = [];
      if (enrichedCount > 0) {
        parts.push(t('boq.recalc_enriched', {
          defaultValue: '{{count}} positions matched to cost database',
          count: enrichedCount,
        }));
      }
      if (result.updated > 0) {
        parts.push(t('boq.recalc_updated', {
          defaultValue: '{{count}} unit rates recalculated from resources',
          count: result.updated,
        }));
      }
      if (result.skipped > 0) {
        parts.push(t('boq.recalc_skipped', {
          defaultValue: '{{count}} positions without cost data (manual rates kept)',
          count: result.skipped,
        }));
      }

      const hasChanges = enrichedCount > 0 || result.updated > 0;
      addToast({
        type: hasChanges ? 'success' : 'info',
        title: hasChanges
          ? t('boq.recalculate_complete', { defaultValue: 'Rates updated' })
          : t('boq.recalculate_no_changes', { defaultValue: 'No changes needed' }),
        message: parts.join('. ') || t('boq.recalculate_all_manual', {
          defaultValue: 'All positions use manual rates - add resources from cost database to enable automatic rate calculation.',
        }),
      });
      invalidateAll();
    } catch (err) {
      // Surface the actual error to the console so the user can see why
      // recalculate failed (auth, 404, 500…) instead of a generic toast.
      console.error('[Update Rates] recalculate failed:', err);
      const detail = err instanceof Error ? err.message : String(err);
      addToast({
        type: 'error',
        title: t('boq.recalculate_failed', { defaultValue: 'Recalculation failed' }),
        message: detail || t('boq.recalculate_failed_hint', { defaultValue: 'Check that the backend is running and cost database is loaded.' }),
      });
    } finally {
      setIsRecalculating(false);
      useProgressStore.getState().done();
    }
  }, [boqId, addToast, t, invalidateAll]);

  const handleRecalculate = useCallback(() => {
    setShowRecalcConfirm(true);
  }, []);

  // "s" shortcut → save / recalculate rates (when not typing in an input)
  useEffect(() => {
    const INTERACTIVE = new Set(['INPUT', 'TEXTAREA', 'SELECT']);
    const handler = (e: KeyboardEvent) => {
      const el = document.activeElement;
      if (el && (INTERACTIVE.has(el.tagName) || (el as HTMLElement).isContentEditable)) return;
      if (e.ctrlKey || e.altKey || e.metaKey || e.shiftKey) return;
      if (e.key === 's') {
        e.preventDefault();
        handleRecalculate();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [handleRecalculate]);

  /* ── Excel paste handler ──────────────────────────────────────────── */

  const handleExcelPaste = useCallback(async (rows: PastedRow[]) => {
    if (!boqId || rows.length === 0) return;
    setIsExcelPasteImporting(true);
    try {
      const items = rows.map((r) => ({
        boq_id: boqId,
        ordinal: r.ordinal,
        description: r.description,
        unit: r.unit,
        quantity: r.quantity,
        unit_rate: r.unit_rate,
      }));
      await apiPost(`/v1/boq/boqs/${boqId}/positions/bulk/`, { items });
      addToast({
        type: 'success',
        title: t('boq.paste_import_success', { defaultValue: 'Imported successfully' }),
        message: t('boq.paste_import_count', { defaultValue: '{{count}} positions added to BOQ', count: rows.length }),
      });
      setExcelPasteOpen(false);
      invalidateAll();
    } catch (err) {
      addToast({
        type: 'error',
        title: t('boq.paste_import_failed', { defaultValue: 'Import failed' }),
        message:
          err instanceof Error && err.message
            ? err.message
            : t('boq.paste_import_failed_hint', {
                defaultValue: 'Some rows could not be imported. Check the values and try again.',
              }),
      });
    } finally {
      setIsExcelPasteImporting(false);
    }
  }, [boqId, addToast, t, invalidateAll]);

  /* ── Resource management ────────────────────────────────────────────── */

  /** Derive a position's per-unit rate from its resource list, in the
   *  project BASE currency. Issue #88 / #111 — each resource may carry its
   *  own ``currency`` (per-resource currency picker), so every subtotal is
   *  converted via the project FX table BEFORE summing. Mirrors the grid
   *  render path (``BOQGrid.insertResourceRows`` line ~1288) so the value we
   *  persist matches what the editor displays — never a blended-currency sum.
   *  Resource currency wins; absent ⇒ project base (no conversion). */
  const perUnitRateInBase = useCallback(
    (resources: Array<Record<string, unknown>>): number => {
      let acc = 0;
      for (const r of resources) {
        const sub =
          (r.total as number) ?? (((r.quantity as number) ?? 0) * ((r.unit_rate as number) ?? 0));
        const ccy = ((r.currency as string) || '').trim() || currencyCode;
        acc += convertToBase(sub, ccy, currencyCode, fxRates ?? null);
      }
      return Math.round(acc * 10000) / 10000;
    },
    [currencyCode, fxRates],
  );

  /** Remove a resource from a position's metadata.resources array. */
  const handleRemoveResource = useCallback(
    (positionId: string, resourceIndex: number) => {
      const pos = boq?.positions.find((p) => p.id === positionId);
      if (!pos) return;
      const resources = [...((pos.metadata?.resources ?? []) as Array<Record<string, unknown>>)];
      if (resourceIndex < 0 || resourceIndex >= resources.length) return;
      resources.splice(resourceIndex, 1);
      const newMeta = { ...pos.metadata, resources };
      // Recalculate unit_rate from remaining resources, currency-converted
      // into the project base (never blend currencies).
      const computedRate = perUnitRateInBase(resources);
      updateMutation.mutate({
        id: positionId,
        data: { unit_rate: computedRate, metadata: newMeta },
      });
    },
    [boq?.positions, updateMutation, perUnitRateInBase],
  );

  /** Apply one or more field updates to a resource in a single mutation.
   *
   *  Two sequential `handleUpdateResource(field, value)` calls would race on
   *  the React Query cache — both would read the same pre-change snapshot and
   *  the second would overwrite the first (observed bug: editing a catalogued
   *  resource's name reverted to the original because the immediate `code: ''`
   *  follow-up wrote the stale `name` back). This function takes a field map
   *  and merges everything into one PATCH. */
  const handleUpdateResourceFields = useCallback(
    (positionId: string, resourceIndex: number, fields: Record<string, number | string>) => {
      const pos = boq?.positions.find((p) => p.id === positionId);
      if (!pos) return;
      const resources = [...((pos.metadata?.resources ?? []) as Array<Record<string, unknown>>)];
      if (resourceIndex < 0 || resourceIndex >= resources.length) return;
      resources[resourceIndex] = { ...resources[resourceIndex], ...fields };
      const rQty = (resources[resourceIndex].quantity as number) ?? 0;
      const rRate = (resources[resourceIndex].unit_rate as number) ?? 0;
      resources[resourceIndex].total = Math.round(rQty * rRate * 100) / 100;
      const newMeta = { ...pos.metadata, resources };
      // Convert each resource subtotal into the project base before summing
      // (a resource may be priced in a foreign currency) — never blend.
      const derivedUnitRate = perUnitRateInBase(resources);
      updateMutation.mutate({
        id: positionId,
        data: { unit_rate: derivedUnitRate, metadata: newMeta },
      });
    },
    [boq?.positions, updateMutation, perUnitRateInBase],
  );

  /** Single-field shim — delegates to the batched implementation. */
  const handleUpdateResource = useCallback(
    (positionId: string, resourceIndex: number, field: string, value: number | string) => {
      handleUpdateResourceFields(positionId, resourceIndex, { [field]: value });
    },
    [handleUpdateResourceFields],
  );

  /** Per-resource custom-field write. Stores the value at
   *  ``position.metadata.resources[i].metadata.custom_fields[fieldName]``
   *  with a deep merge so it doesn't clobber the resource's other fields
   *  (qty, rate, type, etc) or its own metadata blob. The position-level
   *  ``unit_rate`` is NOT recomputed — custom fields don't feed into the
   *  derived rate. */
  const handleUpdateResourceCustomField = useCallback(
    (positionId: string, resourceIndex: number, fieldName: string, value: number | string) => {
      const pos = boq?.positions.find((p) => p.id === positionId);
      if (!pos) return;
      const resources = [...((pos.metadata?.resources ?? []) as Array<Record<string, unknown>>)];
      if (resourceIndex < 0 || resourceIndex >= resources.length) return;
      const res = { ...resources[resourceIndex] };
      const resMeta = (res.metadata as Record<string, unknown> | undefined) ?? {};
      const cf = (resMeta.custom_fields as Record<string, unknown> | undefined) ?? {};
      res.metadata = { ...resMeta, custom_fields: { ...cf, [fieldName]: value } };
      resources[resourceIndex] = res;
      const newMeta = { ...pos.metadata, resources };
      updateMutation.mutate({ id: positionId, data: { metadata: newMeta } });
    },
    [boq?.positions, updateMutation],
  );

  /** Save a resource from a position to the user's catalog. */
  const handleSaveResourceToCatalog = useCallback(
    async (positionId: string, resourceIndex: number) => {
      const pos = boq?.positions.find((p) => p.id === positionId);
      if (!pos) return;
      const resources = (pos.metadata?.resources ?? []) as Array<Record<string, unknown>>;
      const res = resources[resourceIndex];
      if (!res) return;
      try {
        const code = `MY-${((res.type as string) ?? 'OTH').toUpperCase().slice(0, 3)}-${Date.now().toString(36).toUpperCase()}`;
        await apiPost('/v1/catalog/', {
          resource_code: code,
          name: res.name,
          resource_type: res.type || 'material',
          category: ((res.type as string) ?? 'other').charAt(0).toUpperCase() + ((res.type as string) ?? 'other').slice(1),
          unit: res.unit,
          base_price: res.unit_rate,
          min_price: res.unit_rate,
          max_price: res.unit_rate,
          currency: currencySymbol === '€' ? 'EUR' : currencySymbol === '£' ? 'GBP' : currencySymbol === '$' ? 'USD' : 'EUR',
          source: 'boq_import',
          region: 'CUSTOM',
          specifications: {
            source_position: pos.description,
            source_boq_id: boqId,
            saved_at: new Date().toISOString(),
          },
          metadata: {},
        });
        addToast({
          type: 'success',
          title: t('boq.saved_to_catalog', { defaultValue: 'Saved to catalog' }),
          message: res.name as string,
        });
      } catch {
        addToast({
          type: 'error',
          title: t('boq.save_to_catalog_failed', { defaultValue: 'Save failed' }),
        });
      }
    },
    [boq?.positions, boqId, currencySymbol, addToast, t],
  );

  /** Save the variant-header row to the user's catalog under a custom name.
   *
   *  The variant header is a SYNTHETIC grid row — it has no entry in
   *  ``position.metadata.resources`` — so ``handleSaveResourceToCatalog``
   *  can't reach it via index. This handler reads the chosen variant
   *  directly off the position (``metadata.cost_item_variants`` +
   *  ``metadata.variant``) and POSTs the user's edited name as a brand-new
   *  catalog article so the user keeps a private copy ("превратится в
   *  обычный артикул"). */
  const handleSaveVariantHeaderToCatalog = useCallback(
    async (positionId: string, customName: string) => {
      const pos = boq?.positions.find((p) => p.id === positionId);
      if (!pos) return;
      const meta = (pos.metadata ?? {}) as Record<string, unknown>;
      const variants = (meta.cost_item_variants as Array<Record<string, unknown>> | undefined) ?? [];
      const chosenCode = (meta.variant as string | undefined) ?? null;
      const chosen =
        (chosenCode ? variants.find((v) => (v.code as string) === chosenCode) : null) ??
        variants[0];
      if (!chosen) return;
      const trimmed = customName.trim();
      if (!trimmed) return;
      // Currency resolution chain: per-variant override (rare) → position
      // metadata.currency (set when the CWICR row was applied to the
      // position) → BOQ symbol fallback. The catalog should keep the
      // article in its native currency, not the project base — that
      // matches the rest of the variant pipeline.
      const posMetaCurrency = (meta.currency as string | undefined) || undefined;
      const catalogCurrency =
        (chosen.currency as string | undefined) ||
        posMetaCurrency ||
        (currencySymbol === '€' ? 'EUR' : currencySymbol === '£' ? 'GBP' : currencySymbol === '$' ? 'USD' : 'EUR');
      const code = `MY-VAR-${Date.now().toString(36).toUpperCase()}`;
      try {
        await apiPost('/v1/catalog/', {
          resource_code: code,
          name: trimmed,
          resource_type: 'material',
          category: 'Variant',
          unit: pos.unit,
          base_price: chosen.price ?? pos.unit_rate,
          min_price: chosen.price ?? pos.unit_rate,
          max_price: chosen.price ?? pos.unit_rate,
          currency: catalogCurrency,
          source: 'boq_variant_promote',
          region: 'CUSTOM',
          specifications: {
            source_position: pos.description,
            source_boq_id: boqId,
            promoted_from_variant: chosen.code ?? null,
            saved_at: new Date().toISOString(),
          },
          metadata: {},
        });
        addToast({
          type: 'success',
          title: t('boq.saved_to_catalog', { defaultValue: 'Saved to catalog' }),
          message: trimmed,
        });
      } catch {
        addToast({
          type: 'error',
          title: t('boq.save_to_catalog_failed', { defaultValue: 'Save failed' }),
        });
      }
    },
    [boq?.positions, boqId, currencySymbol, addToast, t],
  );

  /** Re-pick the variant on an already-added resource entry (v2.6.26+).
   *
   *  Reads ``available_variants`` cached on the resource at apply-time (see
   *  ``handleCostDbAddResource``) and PATCHes the dedicated re-pick endpoint
   *  so the backend's ``_stamp_resource_variant_snapshots`` re-stamps only
   *  the swapped row. Optimistic update + cache invalidation mirror the
   *  pattern used by ``updateMutation`` for plain field edits.
   */
  const handleRepickResourceVariant = useCallback(
    async (positionId: string, resourceIndex: number, variantCode: string) => {
      try {
        const updated = await boqApi.repickResourceVariant(
          positionId,
          resourceIndex,
          variantCode,
        );
        // React Query cache invalidation — the BOQ-with-positions query is
        // the source of truth for the grid, so re-fetching it picks up the
        // server-stamped variant_snapshot + recomputed totals.
        await queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
        addToast({
          type: 'success',
          title: t('boq.variant_resource_repicked', {
            defaultValue: 'Variant updated: {{label}}',
            label: variantCode,
          }),
          message: updated?.description as string | undefined,
        });
      } catch (err) {
        const detail =
          err instanceof ApiError ? err.message : 'Variant re-pick failed';
        addToast({
          type: 'error',
          title: t('boq.variant_resource_repick_failed', {
            defaultValue: 'Variant re-pick failed',
          }),
          message: detail,
        });
      }
    },
    [boqId, queryClient, addToast, t],
  );

  /** Open cost DB modal in "add resource to position" mode. */
  const handleOpenCostDbForPosition = useCallback(
    (positionId: string) => {
      setCostDbForPositionId(positionId);
      setCostDbModalOpen(true);
    },
    [],
  );

  /** When a cost item is selected and we're in "add resource" mode, add it as a resource. */
  const handleCostDbAddResource = useCallback(
    (
      item: CostAutocompleteItem,
      picked?:
        | { kind: 'variant'; variant: { label: string; price: number; index: number } }
        | { kind: 'default'; strategy: 'mean' | 'median' },
    ) => {
      if (!costDbForPositionId) return;
      const pos = boq?.positions.find((p) => p.id === costDbForPositionId);
      if (!pos) return;

      // Variant pick: collapse the cost-item's components into ONE priced
      // resource at the chosen variant rate. CWICR variants represent
      // alternate price points for the same rate-code (e.g. C25/C30/C35),
      // not per-component breakdowns, so a single synthesized resource
      // preserves variant semantics without scaling-vs-not-scaling
      // ambiguity. Variant marker travels on the resource entry so the
      // backend `_stamp_resource_variant_snapshots` freezes the rate.
      const components = item.components || [];
      let newResources: Array<Record<string, unknown>>;

      // Cache the full variant catalog on the resource so the BOQ row's
      // re-pick pill can swap variants without re-fetching the cost item.
      // Only meaningful when the item carries 2+ variants (matches the
      // EditableResourceRow visibility rule).
      const itemVariants = item.metadata_?.variants;
      const itemVariantStats = item.metadata_?.variant_stats;
      const variantCache: Record<string, unknown> = {};
      if (itemVariants && itemVariants.length >= 2 && itemVariantStats) {
        variantCache.available_variants = itemVariants;
        variantCache.available_variant_stats = itemVariantStats;
      }

      // Catalog currency stamp — when the cost item carries an explicit
      // currency, propagate it to every synthesized resource entry so the
      // BOQ row's per-resource currency cell + the variant picker both
      // show the catalog's native currency instead of falling back to the
      // BOQ base. ``itemCurrency`` is omitted (not falsified) when the
      // catalog row didn't supply one — that lets the existing baseCurrency
      // fallback still apply for purely manual rows.
      const itemCurrency = item.currency && item.currency.trim() ? item.currency : undefined;
      const currencyStamp = itemCurrency ? { currency: itemCurrency } : {};

      if (picked?.kind === 'variant') {
        const v = picked.variant;
        // Resource name resolution priority (matches BOQModals + cellRenderers):
        //   1. ``v.full_label`` — backend-composed ``common_start + variable_part``,
        //      truncated to 400 chars.
        //   2. ``${common_start} ${variant.label}`` when full_label is absent
        //      (pre-v2.6.30 imports) but common_start is captured.
        //   3. ``v.label`` alone — for CWICR rows whose abstract resource has
        //      no separate common_start (the label already carries the full
        //      display text). NEVER fall back to ``item.description`` here:
        //      that just duplicates the rate-code text in front of an
        //      already-full variant label and produced the
        //      "Realizzazione di piattaforme... Bandstahl warmgewalzt..." mess
        //      the user reported (dev DB pos 01.045 / 01.046).
        const fullVariant = itemVariants?.find((x) => x.label === v.label);
        const commonBase = (itemVariantStats?.common_start ?? '').trim();
        const labelTrim = (v.label || '').trim();
        const labelStartsWithBase =
          commonBase.length > 0 &&
          labelTrim.length > 0 &&
          labelTrim.toLowerCase().startsWith(commonBase.toLowerCase());
        const resolvedName =
          (fullVariant?.full_label || '').trim() ||
          (commonBase && labelTrim && !labelStartsWithBase
            ? `${commonBase} ${labelTrim}`.trim()
            : labelTrim) ||
          item.description;
        newResources = [{
          name: resolvedName,
          code: item.code,
          type: 'material',
          unit: item.unit,
          quantity: 1,
          unit_rate: v.price,
          total: v.price,
          variant: { label: v.label, price: v.price, index: v.index },
          ...currencyStamp,
          ...variantCache,
        }];
      } else if (picked?.kind === 'default') {
        newResources = [{
          name: item.description,
          code: item.code,
          type: 'material',
          unit: item.unit,
          quantity: 1,
          unit_rate: item.rate,
          total: item.rate,
          variant_default: picked.strategy,
          ...currencyStamp,
          ...variantCache,
        }];
      } else {
        newResources = components.length > 0
          ? components.map((c) => {
              // Per-component variant catalog (v2.6.30+): when a component
              // carries its OWN ``available_variants`` slot, forward it so
              // the BOQ resource row exposes its dedicated re-pick pill.
              // A position can host MANY independent variant components
              // (e.g. concrete grade + rebar type + formwork type) — each
              // gets its own picker without affecting the others.
              const compVariants = c.available_variants;
              const compStats = c.available_variant_stats;
              const hasCompVariants =
                Array.isArray(compVariants) &&
                compVariants.length >= 2 &&
                compStats != null;
              // Auto-default to the median variant so the user has a
              // working price out of the box. The amber provenance bar +
              // the per-resource pill make it discoverable for refinement.
              const defaultStrategy: 'median' | undefined = hasCompVariants
                ? 'median'
                : undefined;
              return {
                name: c.name,
                code: c.code || '',
                type: c.type || 'other',
                unit: c.unit,
                quantity: c.quantity,
                unit_rate: c.unit_rate,
                total: c.cost || c.quantity * c.unit_rate,
                ...(defaultStrategy ? { variant_default: defaultStrategy } : {}),
                ...(hasCompVariants
                  ? {
                      available_variants: compVariants,
                      available_variant_stats: compStats,
                    }
                  : {}),
                ...currencyStamp,
              };
            })
          : [{
              name: item.description, code: item.code, type: 'material',
              unit: item.unit, quantity: 1, unit_rate: item.rate,
              total: item.rate,
              // No variant marker here, but we still cache the variants if
              // the item has them — that lets the user "promote" a plain
              // single-rate resource into an explicit variant pick later
              // via the row's re-pick pill.
              ...currencyStamp,
              ...variantCache,
            }];
      }

      const existingResources = [...((pos.metadata?.resources ?? []) as Array<Record<string, unknown>>)];
      const merged = [...existingResources, ...newResources];
      const newMeta: Record<string, unknown> = { ...pos.metadata, resources: merged };
      // Carry the scope-of-work bullets from the catalog over to the
      // BOQ position so the grid's (i) hint shows what work is included
      // in the freshly applied rate. Only overwrite when the position
      // has no scope yet — preserves a richer manual override.
      const sowFromCatalog = item.metadata_?.scope_of_work;
      if (
        Array.isArray(sowFromCatalog) &&
        sowFromCatalog.length > 0 &&
        !(Array.isArray(pos.metadata?.scope_of_work) && (pos.metadata?.scope_of_work as unknown[]).length > 0)
      ) {
        newMeta.scope_of_work = sowFromCatalog;
      }
      // Recalculate unit_rate
      let computedRate = 0;
      for (const r of merged) {
        computedRate += ((r.quantity as number) ?? 0) * ((r.unit_rate as number) ?? 0);
      }
      computedRate = Math.round(computedRate * 100) / 100;
      updateMutation.mutate({
        id: costDbForPositionId,
        data: { unit_rate: computedRate, metadata: newMeta },
      });
      setCostDbForPositionId(null);
      setCostDbModalOpen(false);
      const successMsg = picked?.kind === 'variant'
        ? t('boq.variant_resource_added', {
            defaultValue: 'Resource added: {{label}}',
            label: picked.variant.label,
          })
        : t('boq.resources_added', { defaultValue: 'Resources added to position' });
      addToast({ type: 'success', title: successMsg });
    },
    [costDbForPositionId, boq?.positions, updateMutation, addToast, t],
  );

  /** Open catalog picker modal in "add resource to position" mode. */
  const handleOpenCatalogForPosition = useCallback(
    (positionId: string) => {
      setCatalogForPositionId(positionId);
      setCatalogPickerOpen(true);
    },
    [],
  );

  /** When a catalog resource is selected, add it as a resource to the target position. */
  const handleCatalogSelect = useCallback(
    (catalogRes: CatalogResource) => {
      if (!catalogForPositionId || !boq) return;
      const pos = boq.positions.find((p) => p.id === catalogForPositionId);
      if (!pos) return;

      const newResource = {
        name: catalogRes.name,
        code: catalogRes.resource_code,
        type: catalogRes.resource_type,
        unit: catalogRes.unit,
        quantity: 1,
        unit_rate: catalogRes.base_price || 0,
        total: catalogRes.base_price || 0,
      };

      const existing = [...((pos.metadata?.resources ?? []) as Array<Record<string, unknown>>)];
      existing.push(newResource);

      // Recalculate unit_rate from all resources
      let newRate = 0;
      for (const r of existing) {
        newRate += ((r.quantity as number) ?? 0) * ((r.unit_rate as number) ?? 0);
      }
      newRate = Math.round(newRate * 100) / 100;

      // Optimistic cache write: reflect the new resource instantly in the grid.
      // Without this, the user sees no feedback until the server round-trip
      // completes, and onMutate in updateMutation skips non-quantity payloads.
      queryClient.setQueryData(['boq', boqId], (old: unknown) => {
        if (!old || typeof old !== 'object') return old;
        const cur = old as { positions: Position[]; [k: string]: unknown };
        return {
          ...cur,
          positions: cur.positions.map((p) =>
            p.id === catalogForPositionId
              ? {
                  ...p,
                  unit_rate: newRate,
                  total: newRate * (p.quantity ?? 1),
                  metadata: { ...p.metadata, resources: existing },
                }
              : p,
          ),
        };
      });

      updateMutation.mutate({
        id: catalogForPositionId,
        data: {
          unit_rate: newRate,
          metadata: { ...pos.metadata, resources: existing },
        },
      });

      setCatalogPickerOpen(false);
      setCatalogForPositionId(null);
      addToast({
        type: 'success',
        title: t('boq.resource_added_from_catalog', { defaultValue: 'Resource added from catalog' }),
      });
    },
    [catalogForPositionId, boq, boqId, queryClient, updateMutation, addToast, t],
  );

  /** Add a manual resource (not from database) to a position. */
  const handleAddManualResource = useCallback(
    (
      positionId: string,
      resource: {
        name: string;
        type: string;
        unit: string;
        quantity: number;
        unit_rate: number;
        currency?: string;
        code?: string;
      },
    ) => {
      const pos = boq?.positions.find((p) => p.id === positionId);
      if (!pos) return;
      const newRes = {
        name: resource.name,
        // Issue #133 — persist the reusable code so it stays
        // referenceable for future reuse / collision detection.
        code: (resource.code ?? '').trim(),
        type: resource.type,
        unit: resource.unit,
        quantity: resource.quantity,
        unit_rate: resource.unit_rate,
        ...(resource.currency ? { currency: resource.currency } : {}),
        total: Math.round(resource.quantity * resource.unit_rate * 100) / 100,
      };
      const existing = [...((pos.metadata?.resources ?? []) as Array<Record<string, unknown>>)];
      const merged = [...existing, newRes];
      // Convert each resource subtotal into the project base before summing
      // (the new resource may carry a foreign currency) — never blend.
      const computedRate = perUnitRateInBase(merged);
      updateMutation.mutate({
        id: positionId,
        data: { unit_rate: computedRate, metadata: { ...pos.metadata, resources: merged } },
      });
      addToast({ type: 'success', title: t('boq.resource_added', { defaultValue: 'Resource added' }) });
    },
    [boq?.positions, updateMutation, addToast, t, perUnitRateInBase],
  );

  /** Issue #133 — project-wide resource-code lookup for the manual
   *  resource form's "this code is already used" prompt. Returns the
   *  existing resource's reusable definition, or null when the code is
   *  free / unresolvable. */
  const handleLookupResourceByCode = useCallback(
    async (code: string) => {
      const projectId = boq?.project_id;
      if (!projectId || !code.trim()) return null;
      try {
        const res = await boqApi.lookupResourceByCode(projectId, code.trim());
        return res.found && res.match ? res.match : null;
      } catch {
        return null;
      }
    },
    [boq?.project_id],
  );

  /** Duplicate a position (copy description, unit, rate, resources). */
  const handleDuplicatePosition = useCallback(
    (positionId: string) => {
      if (!boqId) return;
      const pos = boq?.positions.find((p) => p.id === positionId);
      if (!pos) return;
      const siblings = boq?.positions.filter((p) => p.parent_id === pos.parent_id) ?? [];
      const lastSibOrdinal = siblings.length > 0 ? siblings[siblings.length - 1]!.ordinal : pos.ordinal;
      const parts = lastSibOrdinal.split('.');
      const lastNum = parseInt(parts[parts.length - 1] || '0', 10) + 1;
      parts[parts.length - 1] = String(lastNum).padStart(2, '0');
      const newOrdinal = parts.join('.');
      addMutation.mutate({
        boq_id: boqId,
        ordinal: newOrdinal,
        description: pos.description,
        unit: pos.unit,
        quantity: pos.quantity,
        unit_rate: pos.unit_rate,
        parent_id: pos.parent_id ?? undefined,
        ...(pos.metadata ? { metadata: pos.metadata } as Record<string, unknown> : {}),
      } as CreatePositionData);
      addToast({ type: 'success', title: t('boq.position_duplicated', { defaultValue: 'Position duplicated' }) });
    },
    [boqId, boq?.positions, addMutation, addToast, t],
  );
  // Keep ref in sync for keyboard shortcut access
  duplicatePositionRef.current = handleDuplicatePosition;

  /* ── AI features: Suggest Rate, Classify, Anomaly Detection ─────── */

  const [anomalyMap, setAnomalyMap] = useState<
    Map<string, { severity: string; message: string; suggestion: number }>
  >(new Map());

  // Vector DB status — check if AI features can work
  const [showVectorSetup, setShowVectorSetup] = useState(false);
  const [vectorIndexing, setVectorIndexing] = useState(false);

  // Esc closes the AI Features Setup modal — standard modal behaviour (Bug 10).
  useEffect(() => {
    if (!showVectorSetup) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setShowVectorSetup(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [showVectorSetup]);

  const { data: vectorStatus } = useQuery({
    queryKey: ['vector-status'],
    queryFn: () => apiGet<{
      connected: boolean;
      engine?: string;
      cost_collection?: { vectors_count: number; points_count: number } | null;
    }>('/v1/costs/vector/status/'),
    staleTime: 60_000,
    retry: false,
  });

  const vectorReady = (vectorStatus?.cost_collection?.vectors_count ?? 0) > 100;

  const ensureVectorDB = useCallback((): boolean => {
    if (vectorReady) return true;
    setShowVectorSetup(true);
    return false;
  }, [vectorReady]);

  const handleIndexNow = useCallback(async () => {
    setVectorIndexing(true);
    try {
      await apiPost('/v1/costs/vector/index/');
      queryClient.invalidateQueries({ queryKey: ['vector-status'] });
      addToast({
        type: 'success',
        title: t('boq.vector_indexed', { defaultValue: 'Vector Database Ready' }),
        message: t('boq.vector_indexed_msg', { defaultValue: 'Cost database indexed. AI features are now available.' }),
      });
      setShowVectorSetup(false);
    } catch {
      addToast({
        type: 'error',
        title: t('boq.vector_index_error', { defaultValue: 'Indexing Failed' }),
        message: t('boq.vector_index_error_msg', { defaultValue: 'Failed to index the cost database. Try importing a database first.' }),
      });
    } finally {
      setVectorIndexing(false);
    }
  }, [queryClient, addToast, t]);

  const handleSuggestRate = useCallback(
    async (positionId: string) => {
      if (!ensureVectorDB()) return;
      const pos = boq?.positions.find((p) => p.id === positionId);
      if (!pos) return;
      try {
        const result = await boqApi.suggestRate({
          description: pos.description,
          unit: pos.unit,
          classification: (pos.classification ?? {}) as Record<string, string>,
          region: project?.region ?? undefined,
        });
        if (result.suggested_rate > 0) {
          // AI proposes, human confirms — show toast with Apply action button
          const rateStr = fmtWithCurrency(result.suggested_rate, locale, currencyCode);
          const conf = Math.round(result.confidence * 100);
          addToast(
            {
              type: 'info',
              title: t('boq.ai_rate_suggestion', { defaultValue: 'AI Rate Suggestion' }),
              message: `${rateStr} (${conf}%, ${result.matches.length} matches)`,
              action: {
                label: t('boq.apply_rate', { defaultValue: 'Apply' }),
                onClick: () => {
                  updateMutation.mutate({
                    id: positionId,
                    data: { unit_rate: result.suggested_rate },
                  });
                  addToast({ type: 'success', title: t('boq.rate_applied', { defaultValue: 'Rate Applied' }), message: rateStr });
                },
              },
            },
            { duration: 10000 },
          );
        } else {
          addToast({
            type: 'warning',
            title: t('boq.ai_no_rate', { defaultValue: 'No Rate Found' }),
            message: t('boq.ai_no_rate_msg', { defaultValue: 'No similar items found in the cost database.' }),
          });
        }
      } catch (err) {
        const detail = err instanceof Error ? err.message : String(err);
        addToast({
          type: 'error',
          title: t('boq.ai_rate_error', { defaultValue: 'Rate suggestion failed' }),
          message: detail.includes('API') ? detail : t('boq.ai_error_generic', { defaultValue: 'Could not connect to AI service. Check that the embedding model is available.' }),
        });
      }
    },
    [boq?.positions, project?.region, currencySymbol, fmt, updateMutation, addToast, t, ensureVectorDB],
  );

  const handleClassify = useCallback(
    async (positionId: string) => {
      if (!ensureVectorDB()) return;
      const pos = boq?.positions.find((p) => p.id === positionId);
      if (!pos) return;
      try {
        // Empty when project hasn't set a standard — backend's
        // _resolve_classification_order picks region-native default.
        // Hardcoding 'din276' here forced DACH classification on every
        // unset US/UK/LATAM project.
        const projectStandard = (project as unknown as Record<string, unknown>)?.classification_standard as string ?? '';
        const result = await boqApi.classify({
          description: pos.description,
          unit: pos.unit,
          project_standard: projectStandard,
        });
        if (result.suggestions.length > 0) {
          const top = result.suggestions[0]!;
          const classification: Record<string, string> = {};
          for (const s of result.suggestions) {
            classification[s.standard] = s.code;
          }
          addToast({
            type: 'info',
            title: t('boq.ai_classification', { defaultValue: 'AI Classification' }),
            message: `${top.standard.toUpperCase()}: ${top.code} - ${top.label} (${Math.round(top.confidence * 100)}%)`,
          });
          updateMutation.mutate({
            id: positionId,
            data: { classification },
          });
        } else {
          addToast({
            type: 'warning',
            title: t('boq.ai_no_classification', { defaultValue: 'No Classification Found' }),
            message: t('boq.ai_no_classification_msg', { defaultValue: 'Could not determine classification from cost database.' }),
          });
        }
      } catch (err) {
        const detail = err instanceof Error ? err.message : String(err);
        addToast({
          type: 'error',
          title: t('boq.ai_classify_error', { defaultValue: 'Classification failed' }),
          message: detail.includes('API') ? detail : t('boq.ai_error_generic', { defaultValue: 'Could not connect to AI service. Check that the embedding model is available.' }),
        });
      }
    },
    [boq?.positions, updateMutation, addToast, t, ensureVectorDB],
  );

  const [isCheckingAnomalies, setIsCheckingAnomalies] = useState(false);
  const anomalyAbortRef = useRef<AbortController | null>(null);

  const handleCancelAnomalies = useCallback(() => {
    anomalyAbortRef.current?.abort();
    setIsCheckingAnomalies(false);
    addToast({ type: 'info', title: t('boq.anomaly_cancelled', { defaultValue: 'Price check cancelled' }) });
  }, [addToast, t]);

  const handleCheckAnomalies = useCallback(async () => {
    if (!boqId) return;
    if (!ensureVectorDB()) return;
    anomalyAbortRef.current?.abort();
    const controller = new AbortController();
    anomalyAbortRef.current = controller;

    // Auto-timeout after 30 seconds
    const timeout = setTimeout(() => controller.abort(), 30000);

    setIsCheckingAnomalies(true);
    useProgressStore.getState().start();
    try {
      const result = await boqApi.checkAnomalies(boqId);
      const map = new Map<string, { severity: string; message: string; suggestion: number }>();
      for (const a of result.anomalies) {
        map.set(a.position_id, {
          severity: a.severity,
          message: a.message,
          suggestion: a.suggestion,
        });
      }
      setAnomalyMap(map);
      if (result.anomalies.length > 0) {
        addToast({
          type: 'warning',
          title: t('boq.anomalies_found', { defaultValue: 'Pricing Anomalies Found' }),
          message: t('boq.anomalies_count', {
            defaultValue: '{{count}} anomalies detected in {{total}} positions',
            count: result.anomalies.length,
            total: result.positions_checked,
          }),
        });
      } else {
        addToast({
          type: 'success',
          title: t('boq.no_anomalies', { defaultValue: 'No Anomalies' }),
          message: t('boq.all_rates_normal', { defaultValue: 'All rates are within normal market range.' }),
        });
      }
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      addToast({
        type: 'error',
        title: t('boq.anomaly_check_error', { defaultValue: 'Anomaly check failed' }),
        message: detail.includes('API') ? detail : t('boq.ai_error_generic', { defaultValue: 'Could not connect to AI service. Check that the embedding model is available.' }),
      });
    } finally {
      clearTimeout(timeout);
      setIsCheckingAnomalies(false);
      anomalyAbortRef.current = null;
      useProgressStore.getState().done();
    }
  }, [boqId, addToast, t, ensureVectorDB]);

  /* ── AI Cost Finder handlers ────────────────────────────────────── */

  const handleCostFinderApplyRate = useCallback(
    (positionId: string, rate: number, source: string) => {
      updateMutation.mutate({
        id: positionId,
        data: { unit_rate: rate, source: 'cost_database' },
      });
      addToast({
        type: 'success',
        title: t('boq.cost_finder_applied', { defaultValue: 'Rate Applied' }),
        message: `${fmtWithCurrency(rate, locale, currencyCode)} (${source})`,
      });
    },
    [updateMutation, addToast, t, locale, currencyCode],
  );

  const handleCostFinderAddPosition = useCallback(
    (data: CreatePositionData) => {
      addMutation.mutate(data);
      addToast({
        type: 'success',
        title: t('boq.cost_finder_added', { defaultValue: 'Position Added' }),
        message: data.description?.slice(0, 60) ?? '',
      });
    },
    [addMutation, addToast, t],
  );

  const handleApplyAnomalySuggestion = useCallback(
    (positionId: string, suggestedRate: number) => {
      updateMutation.mutate({
        id: positionId,
        data: { unit_rate: suggestedRate },
      });
      setAnomalyMap((prev) => {
        const next = new Map(prev);
        next.delete(positionId);
        return next;
      });
      addToast({
        type: 'success',
        title: t('boq.anomaly_rate_applied', { defaultValue: 'Suggested Rate Applied' }),
        message: fmtWithCurrency(suggestedRate, locale, currencyCode),
      });
    },
    [updateMutation, addToast, t, locale, currencyCode],
  );

  const handleIgnoreAnomaly = useCallback((positionId: string) => {
    setAnomalyMap((prev) => {
      const next = new Map(prev);
      next.delete(positionId);
      return next;
    });
  }, []);

  const handleDismissAnomalies = useCallback(() => {
    setAnomalyMap(new Map());
  }, []);

  const handleAcceptAllAnomalies = useCallback(() => {
    for (const [positionId, anomaly] of anomalyMap.entries()) {
      updateMutation.mutate({
        id: positionId,
        data: { unit_rate: anomaly.suggestion },
      });
    }
    const count = anomalyMap.size;
    setAnomalyMap(new Map());
    addToast({
      type: 'success',
      title: t('boq.all_anomalies_resolved', {
        defaultValue: 'All {{count}} suggested rates applied',
        count,
      }),
    });
  }, [anomalyMap, updateMutation, addToast, t]);

  /* ── Smart import ───────────────────────────────────────────────────── */

  const importInputRef = useRef<HTMLInputElement>(null);
  const [isImporting, setIsImporting] = useState(false);

  const handleImportFile = useCallback(
    async (file: File) => {
      if (!boqId) return;
      setIsImporting(true);
      const token = useAuthStore.getState().accessToken;
      const form = new FormData();
      form.append('file', file);

      // GAEB DA XML files (.x81/.x83/.x84/.xml) have a dedicated parser on
      // the backend (``/import/gaeb/``) that understands the GAEB-specific
      // structure — namespace-agnostic, X81/X83/X84 schema-aware. Smart
      // import doesn't recognise these, so the file would be silently
      // rejected. Route by extension before posting.
      const ext = (file.name.split('.').pop() ?? '').toLowerCase();
      const isGaeb = ['x81', 'x83', 'x84'].includes(ext) ||
        (ext === 'xml' && /\.(x8[134]|gaeb)\.xml$/i.test(file.name));
      const endpoint = isGaeb
        ? `/api/v1/boq/boqs/${boqId}/import/gaeb/`
        : `/api/v1/boq/boqs/${boqId}/import/smart/`;

      // Tell the user *immediately* that the import is in flight — the server
      // can take 30+ seconds for large XLSX/PDF/CAD files, and without this
      // toast the UI looks frozen (Bug 2).
      addToast({
        type: 'info',
        title: t('boq.import_started', { defaultValue: 'Importing {{name}}…', name: file.name }),
        message: isGaeb
          ? t('boq.import_started_gaeb_hint', {
              defaultValue: 'Parsing GAEB XML - namespace-agnostic, X81/X83/X84 supported.',
            })
          : t('boq.import_started_hint', {
              defaultValue: 'Large files (PDF / CAD / 1000+ rows) may take up to 60 seconds.',
            }),
      });

      // Abort if the server doesn't respond within 90 seconds. Without a timeout
      // the fetch hangs and the user thinks the page froze (Bug 2).
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 90_000);

      try {
        const res = await fetch(endpoint, {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: form,
          signal: controller.signal,
        });
        clearTimeout(timeoutId);

        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(extractErrorMessageFromBody(body) ?? 'Import failed');
        }

        const result: {
          imported: number;
          errors: { item?: string; error: string }[];
          total_items?: number;
          method?: string;
          model_used?: string | null;
          cad_format?: string;
          cad_elements?: number;
          // GAEB-specific
          skipped?: number;
          sections?: unknown[];
          source_format?: string;
          currency?: string;
        } = await res.json();

        let methodLabel: string;
        if (isGaeb || result.source_format === 'gaeb') {
          const sectionCount = Array.isArray(result.sections) ? result.sections.length : 0;
          methodLabel = ` (GAEB XML, ${sectionCount} section${sectionCount === 1 ? '' : 's'}${result.currency ? `, ${result.currency}` : ''})`;
        } else if (result.method === 'cad_ai') {
          methodLabel = ` (CAD + ${result.model_used ?? 'AI'}, ${result.cad_elements ?? 0} elements)`;
        } else if (result.method === 'ai') {
          methodLabel = ` (AI: ${result.model_used ?? 'auto'})`;
        } else {
          methodLabel = ' (direct)';
        }
        // GAEB returns ``skipped`` instead of ``total_items`` — derive a
        // reasonable denominator so the toast reads cleanly for both shapes.
        const denominator = result.total_items ?? (result.imported + (result.skipped ?? 0));
        addToast({
          type: result.imported > 0 ? 'success' : 'warning',
          title: `Imported ${result.imported} of ${denominator} items${methodLabel}`,
          message:
            result.errors.length > 0
              ? `${result.errors.length} error(s) occurred`
              : undefined,
        });

        invalidateAll();
      } catch (err) {
        clearTimeout(timeoutId);
        const isTimeout = err instanceof DOMException && err.name === 'AbortError';
        addToast({
          type: 'error',
          title: t('boq.import_failed', { defaultValue: 'Import failed' }),
          message: isTimeout
            ? t('boq.import_timeout', {
                defaultValue: 'Server did not respond within 90 seconds. The file may be too large - try splitting it.',
              })
            : err instanceof Error ? err.message : 'Unknown error',
        });
      } finally {
        setIsImporting(false);
      }
    },
    [boqId, addToast, queryClient, t],
  );

  const handleImportInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleImportFile(file);
      e.target.value = '';
    },
    [handleImportFile],
  );

  /* ── AG Grid footer rows (must be before early returns — Rules of Hooks) */
  const hasPositions = boq ? boq.positions.length > 0 : false;

  const boqFooterRows = useMemo(() => {
    type FooterRow = { _isFooter: true; _footerType: string; id: string; description: string; total: number; ordinal: string; unit: string; quantity: number; unit_rate: number; _resourceSplitMoney?: Record<string, number> };
    const rows: FooterRow[] = [];
    if (!hasPositions) return rows;
    const base = { _isFooter: true as const, ordinal: '', unit: '', quantity: 0, unit_rate: 0 };
    // Estimate-wide money per resource type (Material / Labor / Equipment):
    // for every leaf position with a split, money(type) = share(type) x
    // unit_rate x quantity, rebased into the project base currency (same
    // convertToBase path as directCost) so mixed-currency positions sum
    // correctly. Rendered on the DIRECT COST footer row of the M/L/E split
    // columns so the estimator sees absolute cost-driver totals, not just
    // per-position percentages.
    const splitMoney = resourceSplitMoneyTotals(
      boq?.positions ?? [],
      undefined,
      currencyCode,
      fxRates,
    );
    rows.push({ ...base, _footerType: 'direct_cost', id: '_direct_cost', description: t('boq.direct_cost', { defaultValue: 'DIRECT COST' }), total: directCost, ...(splitMoney ? { _resourceSplitMoney: splitMoney } : {}) });
    for (const m of markupTotals) {
      rows.push({ ...base, _footerType: `markup_${m.id}`, id: `_markup_${m.id}`, description: `${m.name} ${fmt.format(m.percentage)}%`, total: m.amount });
    }
    rows.push({ ...base, _footerType: 'net_total', id: '_net_total', description: t('boq.net_total', { defaultValue: 'NET TOTAL' }), total: netTotal });
    if (vatRate > 0) {
      rows.push({ ...base, _footerType: 'vat', id: '_vat', description: `${t('boq.vat', { defaultValue: 'VAT' })} ${fmt.format(vatRate * 100)}%`, total: vatAmount });
      rows.push({ ...base, _footerType: 'gross_total', id: '_gross_total', description: t('boq.gross_total', { defaultValue: 'GROSS TOTAL' }), total: grossTotal });
    }
    return rows;
  }, [hasPositions, boq?.positions, directCost, markupTotals, netTotal, vatRate, vatAmount, grossTotal, t, fmt, currencyCode, fxRates]);

  /** Handle cost suggestion selected from AG Grid autocomplete editor */
  const handleGridSelectSuggestion = useCallback(
    (positionId: string, item: CostAutocompleteItem) => {
      const pos = boq?.positions.find((p) => p.id === positionId);
      if (!pos) return;
      const components = item.components || [];
      const resources = components.map((c) => ({
        name: c.name, code: c.code || '', type: c.type || 'other',
        unit: c.unit, quantity: c.quantity, unit_rate: c.unit_rate,
        total: c.cost || c.quantity * c.unit_rate,
      }));
      const newMeta: Record<string, unknown> = { ...pos.metadata, cost_item_code: item.code, source: 'cost_database' };
      if (resources.length > 0) newMeta.resources = resources;
      // Carry through the scope-of-work bullets from the catalog so the
      // BOQ grid can surface them as a readable (i) hint next to the
      // description. Only stamps when the catalog row actually carried
      // the data — empty/missing keeps the position metadata clean.
      const sow = item.metadata_?.scope_of_work;
      if (Array.isArray(sow) && sow.length > 0) {
        newMeta.scope_of_work = sow;
      } else {
        delete newMeta.scope_of_work;
      }
      let computedRate = item.rate;
      if (resources.length > 0) {
        computedRate = resources.reduce((s, r) => s + (r.total || r.quantity * r.unit_rate), 0);
        computedRate = Math.round(computedRate * 100) / 100;
      }
      updateMutation.mutate({
        id: positionId,
        data: { description: item.description, unit: item.unit, unit_rate: computedRate, classification: item.classification || {}, metadata: newMeta },
      });
    },
    [boq?.positions, updateMutation],
  );

  /** Handle save position to database from AG Grid actions */
  const handleGridSaveToDatabase = useCallback(
    async (positionId: string) => {
      const pos = boq?.positions.find((p) => p.id === positionId);
      if (!pos) return;
      try {
        const resources = (pos.metadata?.resources as Array<{ name: string; code?: string; type: string; unit: string; quantity: number; unit_rate: number }>) || [];
        await apiPost('/v1/costs/', {
          code: `MY-${Date.now().toString(36).toUpperCase()}`,
          description: pos.description, unit: pos.unit, rate: pos.unit_rate,
          source: 'custom', region: 'CUSTOM',
          components: resources.map((r) => ({ name: r.name, code: r.code || '', type: r.type, unit: r.unit, quantity: r.quantity, unit_rate: r.unit_rate, cost: r.quantity * r.unit_rate })),
          metadata: { saved_from_boq: true, saved_date: new Date().toISOString() },
        });
        addToast({ type: 'success', title: t('boq.saved_to_database', { defaultValue: 'Saved to My Database' }) });
      } catch {
        addToast({ type: 'error', title: t('boq.save_failed', { defaultValue: 'Failed to save' }) });
      }
    },
    [boq?.positions, t, addToast],
  );

  /** Handle "Save as Assembly" from the BOQ position context menu */
  const handleSaveAsAssembly = useCallback(
    async (positionId: string) => {
      const pos = boq?.positions.find((p) => p.id === positionId);
      if (!pos) return;

      try {
        const resources = (pos.metadata?.resources as Array<{
          name: string; code?: string; type?: string; unit: string;
          quantity: number; unit_rate: number; total?: number;
        }>) || [];

        // Create the assembly via the API
        const assemblyCode = `FROM-BOQ-${(pos.ordinal || '').replace(/[^a-zA-Z0-9]/g, '-') || Date.now().toString(36).toUpperCase()}`;
        const assemblyResp = await apiPost<{ id: string; name: string }>('/v1/assemblies/', {
          code: assemblyCode,
          name: pos.description || 'Assembly from BOQ',
          unit: pos.unit || 'm2',
          category: 'custom',
          bid_factor: 1.0,
        });

        // Add components from resources
        for (let i = 0; i < resources.length; i++) {
          const r = resources[i]!;
          await apiPost(`/v1/assemblies/${assemblyResp.id}/components/`, {
            description: r.name || '',
            factor: 1.0,
            quantity: r.quantity || 1,
            unit: r.unit || pos.unit || 'm2',
            unit_cost: r.unit_rate || 0,
          });
        }

        // If no resources, add a single component from the position itself
        if (resources.length === 0) {
          await apiPost(`/v1/assemblies/${assemblyResp.id}/components/`, {
            description: pos.description || 'Main item',
            factor: 1.0,
            quantity: 1,
            unit: pos.unit || 'm2',
            unit_cost: pos.unit_rate || 0,
          });
        }

        addToast({
          type: 'success',
          title: t('boq.saved_as_assembly', { defaultValue: 'Saved as Assembly' }),
          message: assemblyResp.name,
        });
      } catch {
        addToast({
          type: 'error',
          title: t('boq.save_as_assembly_failed', { defaultValue: 'Failed to create assembly' }),
        });
      }
    },
    [boq?.positions, t, addToast],
  );

  /** Handle formula applied from AG Grid quantity editor.
   *
   * Issue #90: when ``formula`` is non-empty we persist it under
   * ``metadata.formula`` so the ƒx badge + round-trip edit work. When it's
   * empty (the user replaced an existing formula with a plain number) we
   * strip the key so a stale formula doesn't outlive its source. */
  const handleGridFormulaApplied = useCallback(
    (positionId: string, formula: string, _result: number) => {
      const pos = boq?.positions.find((p) => p.id === positionId);
      if (!pos) return;
      const existingMeta = (pos.metadata ?? {}) as Record<string, unknown>;
      const nextMeta = { ...existingMeta };
      if (formula) {
        nextMeta.formula = formula;
      } else {
        delete nextMeta.formula;
      }
      updateMutation.mutate({
        id: positionId,
        data: { metadata: nextMeta },
      });
    },
    [boq?.positions, updateMutation],
  );

  /** Comment drawer state */
  const [commentPositionId, setCommentPositionId] = useState<string | null>(null);
  const userEmail = useAuthStore((s) => s.userEmail) ?? '';
  const userRole = useAuthStore((s) => s.userRole);
  const isManager = userRole === 'admin' || userRole === 'manager';

  const handleAddComment = useCallback(
    (positionId: string) => {
      setCommentPositionId(positionId);
    },
    [],
  );

  const handleSaveComments = useCallback(
    (positionId: string, updatedComments: CommentEntry[]) => {
      const pos = boq?.positions.find((p) => p.id === positionId);
      if (!pos) return;
      // Store new array format; also keep legacy `comment` field for backward compat
      const lastText = updatedComments.length > 0 ? updatedComments[updatedComments.length - 1]!.text : undefined;
      updateMutation.mutate({
        id: positionId,
        data: {
          metadata: {
            ...pos.metadata,
            comments: updatedComments,
            comment: lastText, // backward compat
          },
        },
      });
    },
    [boq?.positions, updateMutation],
  );

  /* ── Loading state ─────────────────────────────────────────────────── */

  if (isLoading) {
    return (
      <div className="w-full py-8 animate-fade-in">
        <div className="space-y-4">
          <div className="h-8 w-48 rounded-lg bg-surface-secondary animate-shimmer bg-gradient-to-r from-surface-secondary via-surface-tertiary to-surface-secondary bg-[length:200%_100%]" />
          <div className="h-4 w-80 rounded-md bg-surface-secondary animate-shimmer bg-gradient-to-r from-surface-secondary via-surface-tertiary to-surface-secondary bg-[length:200%_100%]" />
          <div className="mt-6 rounded-xl border border-border-light bg-surface-elevated overflow-hidden">
            {Array.from({ length: 8 }).map((_, i) => (
              <div
                key={i}
                className="h-12 border-b border-border-light animate-shimmer bg-gradient-to-r from-surface-secondary via-surface-tertiary to-surface-secondary bg-[length:200%_100%]"
                style={{ animationDelay: `${i * 80}ms` }}
              />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (!boq) {
    return (
      <div className="w-full py-16 text-center">
        <p className="text-content-secondary">{t('boq.not_found', { defaultValue: 'BOQ not found' })}</p>
      </div>
    );
  }

  /* ── Render ────────────────────────────────────────────────────────── */

  return (
    <div
      ref={editorContainerRef}
      tabIndex={-1}
      className="w-full animate-fade-in pb-12 outline-none"
    >
      {/* ── Breadcrumb ────────────────────────────────────────────────── */}
      <Breadcrumb
        className="mb-5"
        items={[
          ...(project ? [{ label: project.name, to: `/projects/${project.id}` }] : []),
          { label: t('boq.title', 'Bill of Quantities'), to: '/boq' },
          { label: boq.name },
        ]}
      />

      {/* ── Info card ─────────────────────────────────────────────────────
          Full-bleed grid editor (style guide §1 viewer exception): the
          canonical DismissibleInfo lives in the header zone above the grid,
          never over it. */}
      <DismissibleInfo
        storageKey="boq-editor"
        className="mb-4"
        title={t('boq_editor.intro_title', { defaultValue: 'Edit the estimate without losing the thread' })}
        more={t('boq_editor.intro_more', { defaultValue: '' }) ? <IntroRichText text={t('boq_editor.intro_more')} /> : undefined}
        links={[
          { label: t('nav.assemblies', { defaultValue: 'Assemblies' }), onClick: () => navigate('/assemblies') },
          { label: t('nav.costs', { defaultValue: 'Cost Database' }), onClick: () => navigate('/costs') },
          { label: t('nav.validation', { defaultValue: 'Validation' }), onClick: () => navigate('/validation') },
          // CONN-83 — outbound AI affordances. Draft a fresh set of positions
          // with the AI Quick Estimate, or ask the Cost Advisor about rates
          // while pricing. The Quick Estimate save dialog already defaults to
          // the globally active project, so no project param is emitted here.
          // The advisor consumes a ?q= prefill separately under its own batch.
          {
            label: t('boq.draft_with_ai', { defaultValue: 'Draft positions with AI' }),
            onClick: () => navigate('/ai-estimate'),
          },
          {
            label: t('boq.ask_cost_advisor', { defaultValue: 'Ask the Cost Advisor' }),
            onClick: () => navigate('/advisor'),
          },
        ]}
      >
        {t('boq_editor.intro_body', {
          defaultValue:
            'This is the working grid where you add, renumber and price positions in a hierarchy, paste from Excel, apply assemblies and link rows to cost-database items or BIM elements. Changes recompute the total instantly and stay available to validation and the cost rollup.',
        })}
      </DismissibleInfo>

      {/* ── Header bar ─────────────────────────────────────────────────── */}
      <div className="mb-4 space-y-2">
        <div className="flex items-center gap-3 min-w-0">
          <h1 className="text-xl font-bold text-content-primary truncate">{boq.name}</h1>
          <Badge
            variant={
              boq.status === 'final' ? 'success' : boq.status === 'draft' ? 'blue' : 'neutral'
            }
            size="md"
          >
            {boq.status === 'draft' ? t('boq.draft', { defaultValue: 'draft' }) : boq.status === 'final' ? t('boq.final', { defaultValue: 'final' }) : boq.status}
          </Badge>
          {boq.is_locked && (
            <Badge variant="warning" size="sm" className="ml-2">
              <Lock size={12} className="mr-1" /> {t('boq.locked', { defaultValue: 'LOCKED' })}
            </Badge>
          )}
          {boq.estimate_type && (
            <Badge variant="neutral" size="sm" className="ml-2">
              {t(`boq.estimate_type_${boq.estimate_type}`, { defaultValue: boq.estimate_type })}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          {boq.description && (
            <p className="text-sm text-content-secondary truncate flex-1">{boq.description}</p>
          )}
          <div className="flex items-center gap-2 flex-shrink-0">
            {!boq.is_locked && isManager && (
              <Button variant="secondary" size="sm" onClick={handleLock} disabled={lockMutation.isPending} title={t('boq.lock_tooltip', { defaultValue: 'Lock prevents edits. Create a revision to make changes to a locked estimate.' })}>
                <Lock size={14} className="mr-1" />
                {t('boq.lock', { defaultValue: 'Lock Estimate' })}
              </Button>
            )}
            {boq.is_locked && isManager && (
              <Button variant="ghost" size="sm" onClick={handleUnlock} disabled={unlockMutation.isPending}>
                <Lock size={14} className="mr-1" />
                {t('boq.unlock', { defaultValue: 'Unlock' })}
              </Button>
            )}
            {boq.is_locked && (
              <Button variant="secondary" size="sm" onClick={handleCreateBudget} disabled={createBudgetMutation.isPending}>
                <Wallet size={14} className="mr-1" />
                {t('boq.create_budget', { defaultValue: 'Create Budget' })}
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setModelReviewOpen(true)}
              title={t('boq.model_review_btn_hint', {
                defaultValue: 'Re-pull quantities from linked BIM models',
              })}
            >
              <RefreshCw size={14} className="mr-1" />
              {t('boq.model_review_btn', { defaultValue: 'Model sync' })}
            </Button>
            {/* Deep link OUT to the Validation dashboard, carrying this BOQ and
                its project so the target lands pre-selected (2 clicks to a
                result). The dashboard persists a server-side report; the
                toolbar's inline Validate keeps the quick in-grid check. */}
            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                navigate(`/validation?boq_id=${boq.id}&project=${boq.project_id}`)
              }
              title={t('boq.validate_dashboard_hint', {
                defaultValue: 'Open the Validation dashboard for this BOQ',
              })}
            >
              <ShieldCheck size={14} className="mr-1" />
              {t('boq.validate_dashboard_btn', { defaultValue: 'Validate' })}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setCompareOpen(true)}
              title={t('boq.compare_btn_hint', {
                defaultValue: 'Compare this estimate against another BOQ',
              })}
            >
              <GitCompare size={14} className="mr-1" />
              {t('boq.compare_btn', { defaultValue: 'Compare' })}
            </Button>
            <Button variant="secondary" size="sm" onClick={handleCreateRevision} disabled={createRevisionMutation.isPending}>
              <Copy size={14} className="mr-1" />
              {t('boq.create_revision', { defaultValue: 'Create Revision' })}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setScenarioOpen(true)}
              title={t('boq.scenario_btn_hint', {
                defaultValue: 'Clone this estimate into a what-if scenario and adjust it freely',
              })}
            >
              <FlaskConical size={14} className="mr-1" />
              {t('boq.scenario_btn', { defaultValue: 'What-if' })}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleJumpToMarkups}
              title={t('boq.markups_btn_hint', {
                defaultValue: 'Overhead, profit, tax and contingency (OH&P)',
              })}
            >
              <Percent size={14} className="mr-1" />
              {t('boq.markups_btn', { defaultValue: 'Markups' })}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setTenderOpen(true)}
              title={t('boq.tender_btn_hint', {
                defaultValue: 'Create a tender package from this estimate',
              })}
            >
              <Send size={14} className="mr-1" />
              {t('boq.tender_btn', { defaultValue: 'To tender' })}
            </Button>
            <BOQOutline positions={boq.positions} onJump={handleOutlineJump} />
            {/* Per-module Tour CTA — launches the BOQ-specific guided tour
                via the registered TOUR_REGISTRY entry, independent of any
                global / first-login tour state. The Guide button sits in the
                same cluster: Tour walks the live UI, Guide explains the
                concepts and the data-entry flow. Its closing CTA opens the
                Add position flow. */}
            <ModuleHelpButton tourId="boq" />
            <ModuleGuideButton
              content={boqGuide}
              onCta={() => handleAddPosition()}
            />
          </div>
        </div>

        <BOQToolbar
          t={t}
          canUndo={canUndo}
          canRedo={canRedo}
          onUndo={handleUndo}
          onRedo={handleRedo}
          onShowVersionHistory={() => setShowVersionHistory(true)}
          onAddPosition={() => handleAddPosition()}
          onAddSection={handleAddSection}
          onOpenCostDb={() => setCostDbModalOpen(true)}
          onOpenAssembly={() => setAssemblyModalOpen(true)}
          onImportClick={() => importInputRef.current?.click()}
          isImporting={isImporting}
          importInputRef={importInputRef}
          onImportInputChange={handleImportInputChange}
          onPasteFromExcel={() => setExcelPasteOpen(true)}
          onExport={handleExport}
          onCarbonFootprint={() =>
            navigate(
              `/sustainability?project_id=${boq.project_id}&boq_id=${boq.id}`,
            )
          }
          onValidate={handleValidate}
          isValidating={isValidating}
          lastValidationScore={lastValidationScore}
          onRecalculate={handleRecalculate}
          isRecalculating={isRecalculating}
          isCheckingAnomalies={isCheckingAnomalies}
          aiChatOpen={aiChatOpen}
          onToggleAiChat={() => {
            setAiChatOpen((prev) => !prev);
            if (!aiChatOpen) { setCostFinderOpen(false); setSmartPanelOpen(false); }
          }}
          costFinderOpen={costFinderOpen}
          onToggleCostFinder={() => {
            setCostFinderOpen((prev) => !prev);
            if (!costFinderOpen) { setAiChatOpen(false); setSmartPanelOpen(false); }
          }}
          smartPanelOpen={smartPanelOpen}
          onToggleSmartPanel={() => {
            setSmartPanelOpen((prev) => !prev);
            if (!smartPanelOpen) { setAiChatOpen(false); setCostFinderOpen(false); }
          }}
          onCheckAnomalies={handleCheckAnomalies}
          onCancelAnomalies={isCheckingAnomalies ? handleCancelAnomalies : undefined}
          anomalyCount={anomalyMap.size}
          onAcceptAllAnomalies={anomalyMap.size > 0 ? handleAcceptAllAnomalies : undefined}
          onManageColumns={() => setCustomColumnsOpen(true)}
          customColumnCount={boqCustomColumns.length}
          showResourceSplit={showResourceSplit}
          onToggleResourceSplit={toggleResourceSplit}
          onManageVariables={() => setVariablesOpen(true)}
          onRenumber={handleRenumber}
          isRenumbering={renumberMutation.isPending}
          hasPositions={hasPositions}
          qualityScoreRing={<QualityScoreRing score={qualityBreakdown.score} breakdown={qualityBreakdown} t={t} />}
          onShowShortcuts={() => setShowShortcuts(true)}
          onToggleCollapseAll={handleToggleAllSections}
          allSectionsCollapsed={allSectionsCollapsed}
          summary={hasPositions ? {
            sectionCount: miniSummaryStats.sectionCount,
            positionCount: miniSummaryStats.positionCount,
            errorCount: miniSummaryStats.errorCount,
            warningCount: miniSummaryStats.warningCount,
            currencySymbol,
            currencyCode,
            fxRates,
            displayCurrency,
            onChangeDisplayCurrency: setDisplayCurrency,
            grossTotal,
            grossTotalDisplay,
            displaySymbol,
            displayRate: displayCurrencyMeta?.rate ?? null,
          } : null}
        />
      </div>

      {/* ── Tips panel (collapsed by default, compact) ──────────────── */}
      {tips.length > 0 && !hasPositions && (
        <div className="mb-3">
          <TipsPanel tips={tips} t={t} />
        </div>
      )}

      {/* ── BOQ Table (AG Grid) ───────────────────────────────────────── */}
      {/* Mini-summary bar (sections/positions/errors/warnings + Grand Total +
          Display-in selector) was merged into BOQToolbar above so the toolbar
          reads as a single visual band on wide screens. The toolbar's
          flex-wrap still lets it spill onto a second row on narrow viewports
          gracefully — but the source of truth lives in one place now. */}
      {hasPositions ? (
        // `min-w-0` prevents the BOQ grid from forcing this column wider
        // than the viewport when many custom columns are added — the grid
        // keeps its own internal horizontal scrollbar, which is what the
        // user expects (toolbar and headers stay aligned with the page).
        <div className="mb-2 min-w-0" data-testid="boq-grid">
        <BOQFilterBar
          search={boqSearch}
          onSearch={setBoqSearch}
          filter={boqFilter}
          onFilter={setBoqFilter}
          shown={filteredLeafCount}
          total={totalLeafCount}
          active={filterActive}
          onClear={() => {
            setBoqSearch('');
            setBoqFilter('all');
          }}
        />
        <BOQGrid
          ref={boqGridRef}
          positions={filteredGridPositions}
          onUpdatePosition={trackedUpdate}
          onDeletePosition={trackedDelete}
          onAddPosition={handleAddPosition}
          onSelectSuggestion={handleGridSelectSuggestion}
          onSaveToDatabase={handleGridSaveToDatabase}
          onAddComment={handleAddComment}
          onFormulaApplied={handleGridFormulaApplied}
          onReorderPositions={handleReorderPositions}
          onReorderSections={handleReorderSections}
          onDeleteSection={handleDeleteSection}
          collapsedSections={effectiveCollapsedSections}
          onToggleSection={toggleSection}
          highlightPositionId={newPositionId ?? bimScrollTargetId ?? undefined}
          currencySymbol={currencySymbol}
          currencyCode={currencyCode}
          fxRates={fxRates}
          onUpsertProjectFxRate={handleUpsertProjectFxRate}
          displayCurrency={
            displayCurrencyMeta
              ? { code: displayCurrencyMeta.currency, rate: displayCurrencyMeta.rate }
              : null
          }
          onOpenFxRateSettings={
            boq?.project_id
              ? () => navigate(`/projects/${boq.project_id}/settings#fx-rates`)
              : undefined
          }
          locale={locale}
          footerRows={boqFooterRows}
          onSelectionChanged={handleSelectionChanged}
          onActiveRowChange={handleActiveRowChange}
          onRemoveResource={handleRemoveResource}
          onUpdateResource={handleUpdateResource}
          onUpdateResourceFields={handleUpdateResourceFields}
          onUpdateResourceCustomField={handleUpdateResourceCustomField}
          onSaveResourceToCatalog={handleSaveResourceToCatalog}
          onSaveVariantHeaderToCatalog={handleSaveVariantHeaderToCatalog}
          onRepickResourceVariant={handleRepickResourceVariant}
          onOpenCostDbForPosition={handleOpenCostDbForPosition}
          onOpenCatalogForPosition={handleOpenCatalogForPosition}
          onOpenAICopilot={handleOpenAICopilot}
          aiCopilotPositionId={aiCopilotOpen ? aiCopilotPositionId : null}
          renderInlineCopilot={renderInlineCopilot}
          onAddManualResource={handleAddManualResource}
          onLookupResourceByCode={handleLookupResourceByCode}
          onDuplicatePosition={handleDuplicatePosition}
          onReuseCode={handleReuseCode}
          onAddChildPosition={(parentId) => handleAddPosition(parentId)}
          onAddSubSection={handleAddSubSection}
          maxNestingDepth={maxNestingDepth}
          onShowLinks={handleShowLinks}
          onUnlinkPosition={handleUnlinkPosition}
          onModelLink={handleModelLink}
          onSuggestRate={handleSuggestRate}
          onClassify={handleClassify}
          onCheckAnomalies={handleCheckAnomalies}
          anomalyMap={anomalyMap}
          onApplyAnomalySuggestion={handleApplyAnomalySuggestion}
          onSaveAsAssembly={handleSaveAsAssembly}
          customColumns={boqCustomColumns}
          showResourceSplit={showResourceSplit}
          boqVariables={boqVariables}
          bimModelId={bimModelId}
          onHighlightBIMElements={(elementIds) => {
            setBOQLinkSelection(null, elementIds);
          }}
        /></div>
      ) : (
        <div className="rounded-xl border border-border-light bg-surface-elevated shadow-xs overflow-hidden p-8">
          <EmptyBOQOnboarding
            onAddSection={handleAddSection}
            onAddPosition={() => handleAddPosition()}
            hasMarkups={markups.length > 0}
            sectionCount={grouped.sections.length}
            positionCount={0}
            t={t}
          />
        </div>
      )}

      {/* The per-position AI copilot renders inline as a full-width row
          directly under its position inside the grid (renderInlineCopilot +
          BOQGrid aiCopilotPositionId), not as a dock under the grid. */}

      {/* ── Price Review Panel (shown after Price Check) ────────────── */}
      {anomalyMap.size > 0 && (
        <PriceReviewPanel
          anomalyMap={anomalyMap}
          positions={positions}
          currencyCode={currencyCode}
          locale={locale}
          onApply={handleApplyAnomalySuggestion}
          onIgnore={handleIgnoreAnomaly}
          onApplyAll={handleAcceptAllAnomalies}
          onDismiss={handleDismissAnomalies}
        />
      )}

      {/* ── Markup Management Panel ──────────────────────────────────── */}
      {boqId && (
        <div data-testid="boq-markup-panel">
          <MarkupPanel
            boqId={boqId}
            markups={markups}
            directCost={directCost}
            currencySymbol={currencySymbol}
            currencyCode={currencyCode}
            locale={locale}
            fmt={fmt}
            openSignal={markupOpenSignal}
          />
        </div>
      )}

      {/* ── Resource Summary ──────────────────────────────────────────── */}
      {boqId && hasPositions && <div className="mt-6" data-testid="boq-resource-summary"><ResourceSummary boqId={boqId} locale={locale} /></div>}

      {/* ── Cost Breakdown Panel ─────────────────────────────────────── */}
      {boqId && hasPositions && <div className="mt-6"><CostBreakdownPanel boqId={boqId} locale={locale} /></div>}

      {/* ── AACE Estimate Classification ──────────────────────────────── */}
      {boqId && hasPositions && <div className="mt-6"><EstimateClassification boqId={boqId} /></div>}

      {/* ── Sensitivity Analysis (Tornado Chart) ──────────────────────── */}
      {boqId && hasPositions && <div className="mt-6"><SensitivityChart boqId={boqId} locale={locale} /></div>}

      {/* ── Monte Carlo Cost Risk ─────────────────────────────────────── */}
      {boqId && hasPositions && <div className="mt-6"><CostRiskPanel boqId={boqId} locale={locale} /></div>}

      {/* ── Activity Log Panel ────────────────────────────────────────── */}
      <ActivityPanel
        activities={activities}
        isOpen={activityOpen}
        onToggle={() => setActivityOpen((prev) => !prev)}
        t={t}
      />

      {/* ── AI Chat Panel ──────────────────────────────────────────────── */}
      <AIChatPanel
        boqId={boqId!}
        context={aiChatContext}
        isOpen={aiChatOpen}
        onClose={() => setAiChatOpen(false)}
        onAddPositions={handleAIAddPositions}
      />

      {/* ── AI Cost Finder Panel ───────────────────────────────────── */}
      <AICostFinderPanel
        boqId={boqId!}
        isOpen={costFinderOpen}
        onClose={() => setCostFinderOpen(false)}
        selectedPosition={selectedPosition}
        onAddPosition={handleCostFinderAddPosition}
        onApplyRate={handleCostFinderApplyRate}
        projectRegion={project?.region}
        currencyCode={currencyCode}
        locale={locale}
      />

      {/* ── AI Smart Panel ───────────────────────────────────────── */}
      <AISmartPanel
        boqId={boqId!}
        isOpen={smartPanelOpen}
        onClose={() => setSmartPanelOpen(false)}
        selectedPosition={selectedPosition}
        allPositions={boq?.positions ?? []}
        onUpdatePosition={(posId, data) => {
          updateMutation.mutate({ id: posId, data });
          addToast({
            type: 'success',
            title: t('boq.ai_applied', { defaultValue: 'AI Suggestion Applied' }),
          });
        }}
        onAddPosition={handleCostFinderAddPosition}
        currencyCode={currencyCode}
        locale={locale}
        projectRegion={project?.region}
      />

      {/* ── Cost Database Search Modal ──────────────────────────────── */}
      {costDbModalOpen && boqId && (
        <CostDatabaseSearchModal
          boqId={boqId}
          onClose={() => {
            setCostDbModalOpen(false);
            setCostDbForPositionId(null);
          }}
          onAdded={() => {
            setCostDbModalOpen(false);
            setCostDbForPositionId(null);
            invalidateAll();
            addToast({ type: 'success', title: t('boq.positions_added', { defaultValue: 'Positions added from cost database' }) });
          }}
          onSelectForResources={costDbForPositionId ? (item, picked) => {
            handleCostDbAddResource({
              code: item.code,
              description: item.description,
              unit: item.unit,
              rate: item.rate,
              // Forward the catalog currency so the resource entry keeps
              // its native currency (the picker + repick endpoint then
              // honour it instead of silently coercing to the BOQ base).
              currency: item.currency,
              classification: item.classification || {},
              components: (item.components || []).map((c) => {
                // Forward per-component variant catalog (v2.6.30+).
                // Backend stamps ``available_variants`` /
                // ``available_variant_stats`` on each abstract-resource
                // component slot — see ``costs/router.py`` `_extract_components`.
                const av = c.available_variants;
                const avs = c.available_variant_stats;
                return {
                  name: c.name,
                  code: c.code,
                  unit: c.unit,
                  quantity: c.quantity,
                  unit_rate: c.unit_rate,
                  cost: c.cost,
                  type: c.type,
                  ...(Array.isArray(av) && av.length >= 2
                    ? { available_variants: av }
                    : {}),
                  ...(avs != null ? { available_variant_stats: avs } : {}),
                };
              }),
              // v2.6.26+: forward the variant catalog so the resource entry
              // can cache ``available_variants`` for later re-pick.
              metadata_: item.metadata_,
            }, picked);
          } : undefined}
        />
      )}

      {/* ── Assembly Picker Modal ──────────────────────────────────── */}
      {assemblyModalOpen && boqId && (
        <AssemblyPickerModal
          boqId={boqId}
          onClose={() => setAssemblyModalOpen(false)}
          onApplied={() => {
            setAssemblyModalOpen(false);
            invalidateAll();
            addToast({ type: 'success', title: t('boq.toasts.assembly_applied', { defaultValue: 'Assembly applied to BOQ' }) });
          }}
        />
      )}

      {/* ── Catalog Picker Modal ─────────────────────────────────────── */}
      <CatalogPickerModal
        open={catalogPickerOpen}
        onClose={() => {
          setCatalogPickerOpen(false);
          setCatalogForPositionId(null);
        }}
        onSelect={handleCatalogSelect}
      />

      {/* ── Quick Add FAB ─────────────────────────────────────────────── */}
      <QuickAddFAB
        onAddPosition={() => handleAddPosition()}
        onAddSection={handleAddSection}
        onImportFromCosts={() => setCostDbModalOpen(true)}
        sidePanelOpen={aiChatOpen || costFinderOpen || smartPanelOpen}
        t={t}
      />

      {/* ── Batch Action Bar ──────────────────────────────────────── */}
      <BatchActionBar
        selectedIds={selectedPositionIds}
        onBatchDelete={handleBatchDelete}
        onBatchChangeUnit={handleBatchChangeUnit}
        onClearSelection={handleClearSelection}
        onBatchFactor={handleBatchFactor}
        onBatchSetClassification={handleBatchSetClassification}
        onBatchFindReplace={handleBatchFindReplace}
        onBatchSetValue={handleBatchSetValue}
      />

      {/* ── Export Quality Warning Dialog ──────────────────────────── */}
      {exportWarning && (
        <ExportWarningDialog
          exportWarning={exportWarning}
          onCancel={() => setExportWarning(null)}
          onConfirm={(fmt) => {
            setExportWarning(null);
            doExport(fmt);
          }}
          t={t}
        />
      )}

      {/* ── Update Rates Confirmation Dialog ────────────────────────── */}
      {showRecalcConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in" onClick={() => setShowRecalcConfirm(false)}>
          <div role="dialog" aria-modal="true" aria-labelledby="boq-recalc-confirm-title" className="w-full max-w-md mx-4 rounded-2xl bg-surface-primary shadow-2xl border border-border-light overflow-hidden animate-scale-in" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-5">
              <div className="flex items-center gap-3 mb-3">
                <div className="h-10 w-10 rounded-xl bg-blue-50 dark:bg-blue-950/30 flex items-center justify-center">
                  <Database size={20} className="text-oe-blue" />
                </div>
                <div>
                  <h3 id="boq-recalc-confirm-title" className="text-base font-semibold">{t('boq.recalc_confirm_title', { defaultValue: 'Update Unit Rates' })}</h3>
                  <p className="text-xs text-content-secondary">{t('boq.recalc_confirm_subtitle', { defaultValue: 'Match positions to cost database' })}</p>
                </div>
              </div>
              <div className="space-y-2 text-sm text-content-secondary">
                <p>{t('boq.recalc_confirm_step1', { defaultValue: '1. Search cost database for matching items by description' })}</p>
                <p>{t('boq.recalc_confirm_step2', { defaultValue: '2. Attach resource breakdowns (materials, labor, equipment)' })}</p>
                <p>{t('boq.recalc_confirm_step3', { defaultValue: '3. Recalculate unit rates from resource components' })}</p>
              </div>
              <div className="mt-3 rounded-lg bg-amber-50 dark:bg-amber-950/20 border border-amber-200/50 dark:border-amber-800/30 px-3 py-2">
                <p className="text-xs text-amber-700 dark:text-amber-300">
                  {t('boq.recalc_confirm_warning', { defaultValue: 'Positions with manual rates that have no match in the cost database will not be changed.' })}
                </p>
              </div>
            </div>
            <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-border-light bg-surface-secondary/30">
              <Button variant="ghost" size="sm" onClick={() => setShowRecalcConfirm(false)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button variant="primary" size="sm" onClick={doRecalculate} loading={isRecalculating}>
                {t('boq.recalc_confirm_button', { defaultValue: 'Update Rates' })}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── GAEB Export Preview Dialog ─────────────────────────────── */}
      {gaebPreviewOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
          onClick={() => setGaebPreviewOpen(false)}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="boq-gaeb-export-title"
            className="bg-surface-elevated rounded-xl border border-border-light shadow-lg w-[420px] p-6 animate-scale-in"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 id="boq-gaeb-export-title" className="text-sm font-semibold text-content-primary">
                {t('boq.gaeb_export_title', { defaultValue: 'Export GAEB XML (X83)' })}
              </h3>
              <button
                onClick={() => setGaebPreviewOpen(false)}
                className="p-1 rounded-lg text-content-tertiary hover:bg-surface-secondary transition-colors"
                aria-label={t('common.close', { defaultValue: 'Close' })}
              >
                <X size={16} />
              </button>
            </div>

            <p className="text-xs text-content-secondary leading-relaxed mb-4">
              {t('boq.gaeb_export_desc', {
                defaultValue:
                  'This will export your BOQ as GAEB XML 3.3 format, compatible with standard tender workflows.',
              })}
            </p>

            <div className="rounded-lg bg-surface-secondary p-3 mb-5 space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <span className="text-content-tertiary">
                  {t('boq.gaeb_positions', { defaultValue: 'Positions' })}
                </span>
                <span className="font-medium text-content-primary">
                  {positions.filter((p) => !isSection(p)).length}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-content-tertiary">
                  {t('boq.gaeb_grand_total', { defaultValue: 'Grand Total' })}
                </span>
                <span className="font-medium text-content-primary">
                  {fmt.format(grossTotal)} {currencySymbol}
                </span>
              </div>
            </div>

            <div className="flex justify-end gap-2">
              <Button variant="ghost" size="sm" onClick={() => setGaebPreviewOpen(false)}>
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </Button>
              <Button variant="primary" size="sm" onClick={confirmGaebExport}>
                {t('boq.export', { defaultValue: 'Export' })}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ── Version History Drawer ──────────────────────────────────── */}
      {boqId && (
        <VersionHistoryDrawer
          boqId={boqId}
          isOpen={showVersionHistory}
          onClose={() => setShowVersionHistory(false)}
        />
      )}

      {/* ── Feature 1: Model link panel (per-position binding) ───────── */}
      {modelLinkFor && boq?.project_id && (
        <ModelLinkPanel
          positionId={modelLinkFor.id}
          positionOrdinal={modelLinkFor.ordinal}
          projectId={boq.project_id}
          onClose={() => setModelLinkFor(null)}
        />
      )}

      {/* ── Feature 1: Model quantity review (BOQ-wide refresh/apply) ── */}
      {boqId && (
        <ModelLinkReviewPanel
          boqId={boqId}
          locale={locale}
          isOpen={modelReviewOpen}
          onClose={() => setModelReviewOpen(false)}
          onApplied={() => invalidateAll()}
        />
      )}

      {/* ── Feature 2: Estimate baseline / line-level compare ───────── */}
      {boqId && boq?.project_id && (
        <BOQCompareDrawer
          boqId={boqId}
          projectId={boq.project_id}
          isOpen={compareOpen}
          onClose={() => setCompareOpen(false)}
          parentEstimateId={boq.parent_estimate_id}
        />
      )}

      {/* ── What-if scenario dialog ───────────────────────────────── */}
      {boqId && (
        <ScenarioDialog
          boqId={boqId}
          baseName={boq?.name ?? ''}
          isOpen={scenarioOpen}
          onClose={() => setScenarioOpen(false)}
          onCreated={handleScenarioCreated}
        />
      )}

      {/* ── Send to tender dialog ─────────────────────────────────── */}
      {boqId && boq?.project_id && (
        <SendToTenderDialog
          boqId={boqId}
          projectId={boq.project_id}
          baseName={boq?.name ?? ''}
          sectionIds={selectedSectionIds}
          isOpen={tenderOpen}
          onClose={() => setTenderOpen(false)}
          onCreated={handleTenderCreated}
        />
      )}

      {/* ── Excel Paste Modal ─────────────────────────────────────── */}
      <ExcelPasteModal
        open={excelPasteOpen}
        onClose={() => setExcelPasteOpen(false)}
        onImport={handleExcelPaste}
        loading={isExcelPasteImporting}
      />

      {/* ── Custom Columns Manager ────────────────────────────────── */}
      {boqId && (
        <CustomColumnsDialog
          open={customColumnsOpen}
          onClose={() => setCustomColumnsOpen(false)}
          boqId={boqId}
          positions={boq?.positions}
          variables={boqVariables}
        />
      )}

      {/* ── BOQ Variables Manager ($GFA, $LABOR_RATE, …) ────────────── */}
      {boqId && (
        <BOQVariablesDialog
          open={variablesOpen}
          onClose={() => setVariablesOpen(false)}
          boqId={boqId}
        />
      )}

      {/* ── Renumber Dialog (multi-scheme picker with live preview) ── */}
      <RenumberDialog
        open={renumberDialogOpen}
        onClose={() => setRenumberDialogOpen(false)}
        onApply={handleRenumberApply}
        isApplying={renumberMutation.isPending}
        samplePositions={(boq?.positions ?? []).slice(0, 30).map((p) => ({
          ordinal: p.ordinal ?? '',
          description: p.description ?? '',
          unit: p.unit ?? '',
          parent_id: p.parent_id ?? null,
        }))}
      />

      {/* ── Linked Positions Modal (Issue #127) ───────────────────── */}
      {linksModalFor && (
        <LinkedPositionsModal
          positionId={linksModalFor.id}
          positionOrdinal={linksModalFor.ordinal}
          locale={locale}
          currencyCode={currencyCode}
          onClose={() => setLinksModalFor(null)}
          onUnlink={handleUnlinkPosition}
          unlinking={unlinkMutation.isPending}
        />
      )}

      {/* ── Section Name Modal ────────────────────────────────────── */}
      {showSectionModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setShowSectionModal(false)}>
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="boq-add-section-title"
            className="bg-surface-elevated rounded-xl border border-border-light shadow-lg w-96 p-5 animate-scale-in"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 id="boq-add-section-title" className="text-sm font-semibold text-content-primary mb-3">
              {t('boq.add_section', { defaultValue: 'Add Section' })}
            </h3>
            <input
              type="text"
              value={sectionNameInput}
              onChange={(e) => setSectionNameInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleConfirmAddSection(); }}
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
              placeholder={t('boq.section_name_placeholder', { defaultValue: 'e.g. Structural Works, MEP, Finishes...' })}
              autoFocus
            />
            {/* Issue #136 — explicit parent picker so a sub-section at any
                level (up to the {{max}} cap) can be created right here,
                without hunting for the row right-click menu. */}
            <label className="block text-[11px] font-medium text-content-secondary mt-3 mb-1">
              {t('boq.section_parent', { defaultValue: 'Parent section' })}
              <span className="text-content-tertiary font-normal ml-1">
                ({t('common.optional', { defaultValue: 'optional' })})
              </span>
            </label>
            <select
              value={sectionParentInput}
              onChange={(e) => setSectionParentInput(e.target.value)}
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            >
              <option value="">
                {t('boq.section_parent_top', { defaultValue: '- Top level (no parent) -' })}
              </option>
              {sectionParentChoices.map((c) => (
                <option key={c.id} value={c.id} disabled={c.disabled}>
                  {c.label}
                  {c.disabled
                    ? ` · ${t('boq.section_parent_max', { defaultValue: 'max depth' })}`
                    : ''}
                </option>
              ))}
            </select>
            <p className="text-[11px] text-content-tertiary mt-1">
              {t('boq.section_parent_hint', {
                defaultValue:
                  'Leave empty for a top-level section, or pick a parent to nest it (up to {{max}} levels).',
                max: maxNestingDepth,
              })}
            </p>
            <div className="flex justify-end gap-2 mt-3">
              <button
                onClick={() => setShowSectionModal(false)}
                className="px-3 py-1.5 text-xs font-medium rounded-lg text-content-secondary hover:bg-surface-secondary transition-colors"
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
              <button
                onClick={handleConfirmAddSection}
                className="px-3 py-1.5 text-xs font-medium rounded-lg bg-oe-blue text-white hover:bg-oe-blue-hover transition-colors"
              >
                {t('common.add', { defaultValue: 'Add' })}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Comment Drawer ──────────────────────────────────────────── */}
      {commentPositionId && (() => {
        const pos = boq?.positions.find((p) => p.id === commentPositionId);
        if (!pos) return null;
        return (
          <CommentDrawer
            positionId={commentPositionId}
            positionOrdinal={pos.ordinal ?? ''}
            positionDescription={pos.description ?? ''}
            metadata={(pos.metadata ?? {}) as Record<string, unknown>}
            currentUserEmail={userEmail}
            onSave={handleSaveComments}
            onClose={() => setCommentPositionId(null)}
          />
        );
      })()}

      {/* ── Keyboard Shortcuts Overlay ──────────────────────────────── */}
      {showShortcuts && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-label={t('boq.keyboard_shortcuts', { defaultValue: 'Keyboard Shortcuts' })}>
          <div className="absolute inset-0 bg-black/70 backdrop-blur-lg" onClick={() => setShowShortcuts(false)} />
          <div className="relative z-10 rounded-xl bg-surface-primary shadow-2xl border border-border-light p-6 max-w-md w-full animate-scale-in">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Keyboard size={18} className="text-content-tertiary" />
                <h3 className="text-base font-semibold text-content-primary">
                  {t('boq.keyboard_shortcuts', { defaultValue: 'Keyboard Shortcuts' })}
                </h3>
              </div>
              <button
                onClick={() => setShowShortcuts(false)}
                className="p-1.5 rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
                aria-label={t('common.close', { defaultValue: 'Close' })}
              >
                <X size={16} />
              </button>
            </div>
            <div className="grid grid-cols-[auto_1fr] gap-y-2.5 gap-x-4 text-sm">
              <kbd className="inline-flex items-center rounded border border-border-light bg-surface-secondary px-1.5 py-0.5 text-xs font-mono">{t('boq.shortcut_ctrl_enter', { defaultValue: 'Ctrl+Enter' })}</kbd>
              <span className="text-content-secondary">{t('boq.shortcut_new_position', { defaultValue: 'New Position' })}</span>

              <kbd className="inline-flex items-center rounded border border-border-light bg-surface-secondary px-1.5 py-0.5 text-xs font-mono">{t('boq.shortcut_ctrl_d', { defaultValue: 'Ctrl+D' })}</kbd>
              <span className="text-content-secondary">{t('boq.shortcut_duplicate', { defaultValue: 'Duplicate Position' })}</span>

              <kbd className="inline-flex items-center rounded border border-border-light bg-surface-secondary px-1.5 py-0.5 text-xs font-mono">{t('boq.shortcut_ctrl_e', { defaultValue: 'Ctrl+E' })}</kbd>
              <span className="text-content-secondary">{t('boq.shortcut_export', { defaultValue: 'Export' })}</span>

              <kbd className="inline-flex items-center rounded border border-border-light bg-surface-secondary px-1.5 py-0.5 text-xs font-mono">{t('boq.shortcut_ctrl_i', { defaultValue: 'Ctrl+I' })}</kbd>
              <span className="text-content-secondary">{t('boq.shortcut_import', { defaultValue: 'Import' })}</span>

              <kbd className="inline-flex items-center rounded border border-border-light bg-surface-secondary px-1.5 py-0.5 text-xs font-mono">{t('boq.shortcut_ctrl_l', { defaultValue: 'Ctrl+L' })}</kbd>
              <span className="text-content-secondary">{t('boq.shortcut_lock', { defaultValue: 'Lock / Unlock Estimate' })}</span>

              <kbd className="inline-flex items-center rounded border border-border-light bg-surface-secondary px-1.5 py-0.5 text-xs font-mono">{t('boq.shortcut_ctrl_z', { defaultValue: 'Ctrl+Z' })}</kbd>
              <span className="text-content-secondary">{t('boq.shortcut_undo', { defaultValue: 'Undo' })}</span>

              <kbd className="inline-flex items-center rounded border border-border-light bg-surface-secondary px-1.5 py-0.5 text-xs font-mono">{t('boq.shortcut_ctrl_y', { defaultValue: 'Ctrl+Y' })}</kbd>
              <span className="text-content-secondary">{t('boq.shortcut_redo', { defaultValue: 'Redo' })}</span>

              <kbd className="inline-flex items-center rounded border border-border-light bg-surface-secondary px-1.5 py-0.5 text-xs font-mono">{t('boq.shortcut_ctrl_slash', { defaultValue: 'Ctrl+/' })}</kbd>
              <span className="text-content-secondary">{t('boq.shortcut_ai_chat', { defaultValue: 'Toggle AI Chat' })}</span>

              <kbd className="inline-flex items-center rounded border border-border-light bg-surface-secondary px-1.5 py-0.5 text-xs font-mono">{t('boq.shortcut_ctrl_shift_v', { defaultValue: 'Ctrl+Shift+V' })}</kbd>
              <span className="text-content-secondary">{t('boq.shortcut_paste_excel', { defaultValue: 'Paste from Excel' })}</span>

              <kbd className="inline-flex items-center rounded border border-border-light bg-surface-secondary px-1.5 py-0.5 text-xs font-mono">{t('boq.shortcut_del', { defaultValue: 'Del' })}</kbd>
              <span className="text-content-secondary">{t('boq.shortcut_delete', { defaultValue: 'Delete Selected' })}</span>

              <kbd className="inline-flex items-center rounded border border-border-light bg-surface-secondary px-1.5 py-0.5 text-xs font-mono">{t('boq.shortcut_f1', { defaultValue: 'F1' })}</kbd>
              <span className="text-content-secondary">{t('boq.shortcut_show_shortcuts', { defaultValue: 'Show Shortcuts' })}</span>
            </div>
          </div>
        </div>
      )}

      {/* ── Vector DB Setup Dialog ───────────────────────────────────── */}
      {showVectorSetup && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/70 backdrop-blur-lg" onClick={() => setShowVectorSetup(false)} />
          <div className="relative w-full max-w-md rounded-2xl border border-border-light bg-surface-elevated shadow-2xl animate-form-scale-in">
            <button
              onClick={() => setShowVectorSetup(false)}
              className="absolute top-3 right-3 p-1.5 rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
              aria-label={t('common.close', { defaultValue: 'Close' })}
            >
              <X size={16} />
            </button>

            <div className="px-6 pt-6 pb-2">
              <div className="flex items-center gap-3 mb-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-500/10">
                  <Sparkles size={20} className="text-violet-500" />
                </div>
                <div>
                  <h3 className="text-base font-semibold text-content-primary">
                    {t('boq.vector_setup_title', { defaultValue: 'AI Features Setup' })}
                  </h3>
                  <p className="text-xs text-content-tertiary">
                    {t('boq.vector_setup_subtitle', { defaultValue: 'One-time setup required' })}
                  </p>
                </div>
              </div>
            </div>

            <div className="px-6 pb-4">
              <p className="text-sm text-content-secondary leading-relaxed mb-4">
                {t('boq.vector_setup_desc', {
                  defaultValue: 'AI rate suggestions, classification, and anomaly detection require a vector-indexed cost database. This is a one-time setup that takes about 30 seconds.',
                })}
              </p>

              <div className="space-y-2.5">
                {/* Option 1: Index existing database */}
                <button
                  onClick={handleIndexNow}
                  disabled={vectorIndexing}
                  className="flex w-full items-center gap-3 rounded-xl border border-border-light px-4 py-3 text-left hover:bg-surface-secondary transition-colors group disabled:opacity-60"
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10 group-hover:bg-emerald-500/20 transition-colors">
                    <Database size={16} className="text-emerald-500" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-content-primary">
                      {vectorIndexing
                        ? t('boq.vector_indexing', { defaultValue: 'Indexing...' })
                        : t('boq.vector_index_now', { defaultValue: 'Index existing cost database' })
                      }
                    </div>
                    <div className="text-xs text-content-tertiary">
                      {t('boq.vector_index_desc', { defaultValue: 'Build vector index from your imported cost items (~30s)' })}
                    </div>
                  </div>
                  {vectorIndexing && (
                    <div className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-emerald-500 border-t-transparent" />
                  )}
                </button>

                {/* Option 2: Go to import page */}
                <button
                  onClick={() => { setShowVectorSetup(false); navigate('/costs/import'); }}
                  className="flex w-full items-center gap-3 rounded-xl border border-border-light px-4 py-3 text-left hover:bg-surface-secondary transition-colors group"
                >
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-500/10 group-hover:bg-blue-500/20 transition-colors">
                    <Download size={16} className="text-blue-500" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium text-content-primary">
                      {t('boq.vector_download', { defaultValue: 'Download cost database first' })}
                    </div>
                    <div className="text-xs text-content-tertiary">
                      {t('boq.vector_download_desc', { defaultValue: 'Import CWICR databases (55,000+ items, 9 regions)' })}
                    </div>
                  </div>
                  <ExternalLink size={14} className="shrink-0 text-content-quaternary group-hover:text-content-tertiary" />
                </button>
              </div>

              {/* Status info */}
              <div className="mt-4 flex items-start gap-2 rounded-lg bg-surface-secondary/80 px-3 py-2">
                <WarnTriangle size={13} className="text-amber-500 shrink-0 mt-0.5" />
                <p className="text-xs text-content-tertiary leading-relaxed">
                  {vectorStatus?.cost_collection
                    ? t('boq.vector_status_partial', {
                        defaultValue: 'Vector DB has {{count}} items indexed. Minimum ~100 items needed for AI features.',
                        count: vectorStatus.cost_collection.vectors_count,
                      })
                    : t('boq.vector_status_empty', {
                        defaultValue: 'No vector database found. Import a cost database or index your existing cost items.',
                      })
                  }
                </p>
              </div>
            </div>
          </div>
        </div>
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}
