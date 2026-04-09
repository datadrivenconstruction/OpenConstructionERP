import React, { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
// lucide-react icons used by sub-components (BOQToolbar, BOQGrid, etc.) — none needed directly here
import { Database, Download, ExternalLink, X, Sparkles, AlertTriangle as WarnTriangle, Lock, Copy, Wallet } from 'lucide-react';
import { Button, Badge, Breadcrumb } from '@/shared/ui';
import { useProgressStore } from '@/shared/ui/GlobalProgress';
import { apiGet, apiPost, triggerDownload } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { useRecentStore } from '@/stores/useRecentStore';
import { useAuthStore } from '@/stores/useAuthStore';
import {
  boqApi,
  groupPositionsIntoSections,
  isSection,
  normalizePositions,
  type Position,
  type CreatePositionData,
  type UpdatePositionData,
  type Markup,
  type ActivityEntry,
  type CostAutocompleteItem,
} from './api';
import { ApiError } from '@/shared/lib/api';
import { projectsApi } from '@/features/projects/api';
// AutocompleteInput used in sub-components, not directly here
// import { AutocompleteInput } from './AutocompleteInput';
import { AIChatPanel } from './AIChatPanel';
import { AICostFinderPanel } from './AICostFinderPanel';
import { AISmartPanel } from './AISmartPanel';
// ClassificationPicker used in sub-components
// import { ClassificationPicker } from './ClassificationPicker';
import { VersionHistoryDrawer } from './VersionHistoryDrawer';
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
// evaluateFormula used in BOQGrid, not directly here
// import { evaluateFormula } from './grid/cellEditors';

/* ── Extracted modules ──────────────────────────────────────────────── */

import {
  UNDO_STACK_LIMIT,
  type UndoEntry,
  getVatRate,
  getLocaleForRegion,
  getCurrencySymbol,
  getCurrencyCode,
  createFormatter,
  fmtWithCurrency,
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
import { RenumberDialog } from './RenumberDialog';

/* ── Re-exports for tests ────────────────────────────────────────────── */

export { getVatRate, getLocaleForRegion, getCurrencySymbol, computeQualityScore };
export type { QualityBreakdown };

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

  /* ── Data fetching ─────────────────────────────────────────────────── */

  const { data: boq, isLoading } = useQuery({
    queryKey: ['boq', boqId],
    queryFn: () => boqApi.get(boqId!),
    enabled: !!boqId,
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

  const vatRate = useMemo(() => getVatRate(project?.region), [project?.region]);
  const currencySymbol = useMemo(() => getCurrencySymbol(project?.currency), [project?.currency]);
  const currencyCode = useMemo(() => getCurrencyCode(project?.currency), [project?.currency]);
  const locale = useMemo(() => getLocaleForRegion(project?.region), [project?.region]);

  // Custom columns from BOQ metadata
  const boqCustomColumns = useMemo(() => {
    const raw = boq as unknown as Record<string, unknown> | undefined;
    const meta = raw?.metadata ?? raw?.metadata_;
    if (!meta || typeof meta !== 'object') return [];
    return (meta as Record<string, unknown>).custom_columns as import('./grid/columnDefs').CustomColumnDef[] ?? [];
  }, [boq]);
  const fmt = useMemo(
    () => createFormatter(locale),
    [locale],
  );

  const { data: markupsData } = useQuery({
    queryKey: ['boq-markups', boqId],
    queryFn: () => boqApi.getMarkups(boqId!),
    enabled: !!boqId,
    retry: (failCount, error) => {
      if (error instanceof ApiError && error.status === 404) return false;
      return failCount < 3;
    },
  });

  const markups: Markup[] = markupsData?.markups ?? [];

  const addToast = useToastStore((s) => s.addToast);
  const removeToast = useToastStore((s) => s.removeToast);
  const addRecent = useRecentStore((s) => s.addRecent);

  // Track BOQ as recent item
  useEffect(() => {
    if (boq && boqId) {
      addRecent({
        type: 'boq',
        id: boqId,
        title: boq.name || 'Untitled BOQ',
        url: `/boq/${boqId}`,
      });
    }
  }, [boq, boqId, addRecent]);

  /* ── Batch selection state ──────────────────────────────────────────── */

  const [selectedPositionIds, setSelectedPositionIds] = useState<string[]>([]);
  const selectedPosition = useMemo(() => {
    if (selectedPositionIds.length !== 1) return null;
    return boq?.positions.find((p) => p.id === selectedPositionIds[0]) ?? null;
  }, [selectedPositionIds, boq?.positions]);
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
      addToast({ type: 'success', title: t('boq.position_added', { defaultValue: 'Position added' }), message: t('boq.click_to_edit', { defaultValue: 'Click any cell to edit' }) });
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
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdatePositionData }) =>
      boqApi.updatePosition(id, data),
    onSuccess: () => invalidateAll(),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => boqApi.deletePosition(id),
    onSuccess: () => invalidateAll(),
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
          defaultValue: 'Order preserved — only ordinals were rewritten. Undo with Ctrl+Z is not supported for renumber.',
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

  const handleLock = useCallback(() => {
    lockMutation.mutate();
  }, [lockMutation]);

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
    mutationFn: () => apiPost<{ created: number }>(`/v1/boq/boqs/${boqId}/create-budget`, {}),
    onSuccess: (data) => {
      addToast({
        type: 'success',
        title: t('boq.budget_created', { defaultValue: 'Budget created' }),
        message: t('boq.budget_created_desc', {
          defaultValue: '{{count}} budget lines created from estimate',
          count: data.created ?? 0,
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
    mutationFn: () => apiPost<{ id: string }>(`/v1/boq/boqs/${boqId}/create-revision`, {}),
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

  /** Flush any pending deferred delete when the component unmounts. */
  useEffect(() => {
    return () => {
      const pending = pendingDeleteRef.current;
      if (pending) {
        clearTimeout(pending.timeoutId);
        // Fire the API call so the delete isn't silently lost
        boqApi.deletePosition(pending.positionSnapshot.id).catch(() => {});
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

  /* ── AI Chat panel ────────────────────────────────────────────────── */

  const [aiChatOpen, setAiChatOpen] = useState(false);
  const [costFinderOpen, setCostFinderOpen] = useState(false);
  const [smartPanelOpen, setSmartPanelOpen] = useState(false);
  const [costDbModalOpen, setCostDbModalOpen] = useState(false);
  const [assemblyModalOpen, setAssemblyModalOpen] = useState(false);
  const [excelPasteOpen, setExcelPasteOpen] = useState(false);
  const [customColumnsOpen, setCustomColumnsOpen] = useState(false);
  const [isExcelPasteImporting, setIsExcelPasteImporting] = useState(false);
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
      currency: project?.currency ?? 'EUR',
      standard: (project as unknown as Record<string, unknown>)?.classification_standard as string ?? 'din276',
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

  const handleClearSelection = useCallback(() => {
    setSelectedPositionIds([]);
    boqGridRef.current?.clearSelection();
  }, []);

  const handleSelectionChanged = useCallback((ids: string[]) => {
    setSelectedPositionIds(ids);
  }, []);

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
    }

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [handleUndo, handleRedo]);

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

  /* ── Section drag-and-drop reordering (future feature) ───────────── */

  /* Section drag state and handlers — wired to section header UI
  const handleSectionDragStart = (sectionId: string) => setDragSectionId(sectionId);
  const handleSectionDrop = (targetSectionId: string) => {
    if (!dragSectionId || dragSectionId === targetSectionId || !grouped.sections.length) {
      setDragSectionId(null); return;
    }
    const sectionIds = grouped.sections.map((g) => g.section.id);
    const fromIdx = sectionIds.indexOf(dragSectionId);
    const toIdx = sectionIds.indexOf(targetSectionId);
    if (fromIdx === -1 || toIdx === -1) { setDragSectionId(null); return; }
    const reordered = [...sectionIds];
    reordered.splice(fromIdx, 1);
    reordered.splice(toIdx, 0, dragSectionId);
    reordered.forEach((secId, idx) => {
      const newOrdinal = String(idx + 1).padStart(2, '0');
      updateMutation.mutate({ id: secId, data: { ordinal: newOrdinal, sort_order: idx * 10 } });
    });
    setDragSectionId(null);
    setDragOverSectionId(null);
  }; */

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
    return boq.positions.reduce((sum, p) => sum + p.total, 0);
  }, [boq]);

  const markupTotals = useMemo(() => {
    let running = directCost;
    return markups
      .filter((m) => m.is_active !== false)
      .map((m) => {
        let amount = 0;
        if (m.markup_type === 'fixed') {
          amount = m.fixed_amount ?? 0;
        } else if (m.apply_to === 'cumulative') {
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

  /* ── Quality score ───────────────────────────────────────────────── */

  const qualityBreakdown = useMemo(
    () => computeQualityScore(boq?.positions ?? [], markups),
    [boq?.positions, markups],
  );

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
        text: t('boq.tip_autocomplete', { defaultValue: 'Fill in descriptions for all positions — start typing to see suggestions from the cost database' }),
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
    mutationFn: (data: { ordinal: string; description: string }) =>
      boqApi.addSection(boqId!, data),
    onSuccess: () => {
      invalidateAll();
      addToast({ type: 'success', title: t('boq.section_added', { defaultValue: 'Section added' }) });
    },
  });

  /** Section name modal */
  const [showSectionModal, setShowSectionModal] = useState(false);
  const [sectionNameInput, setSectionNameInput] = useState('');

  const handleAddSection = useCallback(() => {
    if (!boqId) return;
    setSectionNameInput('');
    setShowSectionModal(true);
  }, [boqId]);

  const handleConfirmAddSection = useCallback(() => {
    if (!boqId) return;
    const ordinal = String(grouped.sections.length + 1).padStart(2, '0');
    sectionMutation.mutate({ ordinal, description: sectionNameInput || '' });
    setShowSectionModal(false);
    setSectionNameInput('');
  }, [boqId, grouped.sections.length, sectionMutation, sectionNameInput]);

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

      let ordinal: string;

      if (parentId) {
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
      });
    },
    [boqId, boq, grouped, addMutation],
  );
  // Keep ref in sync for keyboard shortcut access
  addPositionRef.current = handleAddPosition;

  /* handleDeleteSection — wired via section context menu (future)
  const handleDeleteSection = useCallback(
    (sectionGroup: SectionGroup) => {
      for (const child of sectionGroup.children) trackedDelete(child.id);
      trackedDelete(sectionGroup.section.id);
    },
    [trackedDelete],
  ); */

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
          exportBOQToExcel({
            boqTitle: boq?.name ?? 'BOQ',
            projectName: project?.name,
            classificationStandard: project?.classification_standard,
            region: project?.region,
            currency: (boq as unknown as Record<string, unknown>)?.currency as string ?? '\u20ac',
            positions,
            markupTotals: markupTotalsForExport,
            netTotal,
            vatRate: (boq as Record<string, unknown>)?.vat_rate as number ?? 0.19,
            vatAmount: netTotal * ((boq as Record<string, unknown>)?.vat_rate as number ?? 0.19),
            grossTotal: netTotal * (1 + ((boq as Record<string, unknown>)?.vat_rate as number ?? 0.19)),
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
        errors.slice(0, 2).forEach(e => parts.push(`  — ${e.message}`));
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
    } catch {
      addToast({
        type: 'error',
        title: t('boq.validation_failed', { defaultValue: 'Validation failed' }),
        message: t('boq.validation_failed_hint', { defaultValue: 'Could not connect to validation service.' }),
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
          defaultValue: 'All positions use manual rates — add resources from cost database to enable automatic rate calculation.',
        }),
      });
      invalidateAll();
    } catch {
      addToast({
        type: 'error',
        title: t('boq.recalculate_failed', { defaultValue: 'Recalculation failed' }),
        message: t('boq.recalculate_failed_hint', { defaultValue: 'Check that the backend is running and cost database is loaded.' }),
      });
    } finally {
      setIsRecalculating(false);
      useProgressStore.getState().done();
    }
  }, [boqId, addToast, t, invalidateAll]);

  const handleRecalculate = useCallback(() => {
    setShowRecalcConfirm(true);
  }, []);

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
    } catch {
      addToast({
        type: 'error',
        title: t('boq.paste_import_failed', { defaultValue: 'Import failed' }),
      });
    } finally {
      setIsExcelPasteImporting(false);
    }
  }, [boqId, addToast, t, invalidateAll]);

  /* ── Resource management ────────────────────────────────────────────── */

  /** Remove a resource from a position's metadata.resources array. */
  const handleRemoveResource = useCallback(
    (positionId: string, resourceIndex: number) => {
      const pos = boq?.positions.find((p) => p.id === positionId);
      if (!pos) return;
      const resources = [...((pos.metadata?.resources ?? []) as Array<Record<string, unknown>>)];
      if (resourceIndex < 0 || resourceIndex >= resources.length) return;
      resources.splice(resourceIndex, 1);
      const newMeta = { ...pos.metadata, resources };
      // Recalculate unit_rate from remaining resources
      let computedRate = 0;
      for (const r of resources) {
        computedRate += ((r.quantity as number) ?? 0) * ((r.unit_rate as number) ?? 0);
      }
      computedRate = Math.round(computedRate * 100) / 100;
      updateMutation.mutate({
        id: positionId,
        data: { unit_rate: computedRate, metadata: newMeta },
      });
    },
    [boq?.positions, updateMutation],
  );

  /** Update a single resource field (quantity, unit_rate, or name) and recalculate position rate. */
  const handleUpdateResource = useCallback(
    (positionId: string, resourceIndex: number, field: string, value: number | string) => {
      const pos = boq?.positions.find((p) => p.id === positionId);
      if (!pos) return;
      const resources = [...((pos.metadata?.resources ?? []) as Array<Record<string, unknown>>)];
      if (resourceIndex < 0 || resourceIndex >= resources.length) return;
      resources[resourceIndex] = { ...resources[resourceIndex], [field]: value };
      // Recalculate resource total
      const rQty = (resources[resourceIndex].quantity as number) ?? 0;
      const rRate = (resources[resourceIndex].unit_rate as number) ?? 0;
      resources[resourceIndex].total = Math.round(rQty * rRate * 100) / 100;
      const newMeta = { ...pos.metadata, resources };
      // Recalculate position unit_rate = sum(resource totals) / position quantity
      let resourceTotal = 0;
      for (const r of resources) {
        resourceTotal += (r.total as number) ?? (((r.quantity as number) ?? 0) * ((r.unit_rate as number) ?? 0));
      }
      const posQty = pos.quantity || 1;
      const derivedUnitRate = Math.round((resourceTotal / posQty) * 10000) / 10000;
      updateMutation.mutate({
        id: positionId,
        data: { unit_rate: derivedUnitRate, metadata: newMeta },
      });
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
    (item: CostAutocompleteItem) => {
      if (!costDbForPositionId) return;
      const pos = boq?.positions.find((p) => p.id === costDbForPositionId);
      if (!pos) return;

      const components = item.components || [];
      const newResources = components.length > 0
        ? components.map((c) => ({
            name: c.name, code: c.code || '', type: c.type || 'other',
            unit: c.unit, quantity: c.quantity, unit_rate: c.unit_rate,
            total: c.cost || c.quantity * c.unit_rate,
          }))
        : [{
            name: item.description, code: item.code, type: 'material',
            unit: item.unit, quantity: 1, unit_rate: item.rate,
            total: item.rate,
          }];

      const existingResources = [...((pos.metadata?.resources ?? []) as Array<Record<string, unknown>>)];
      const merged = [...existingResources, ...newResources];
      const newMeta = { ...pos.metadata, resources: merged };
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
      addToast({ type: 'success', title: t('boq.resources_added', { defaultValue: 'Resources added to position' }) });
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
    [catalogForPositionId, boq, updateMutation, addToast, t],
  );

  /** Add a manual resource (not from database) to a position. */
  const handleAddManualResource = useCallback(
    (positionId: string, resource: { name: string; type: string; unit: string; quantity: number; unit_rate: number }) => {
      const pos = boq?.positions.find((p) => p.id === positionId);
      if (!pos) return;
      const newRes = {
        name: resource.name,
        code: '',
        type: resource.type,
        unit: resource.unit,
        quantity: resource.quantity,
        unit_rate: resource.unit_rate,
        total: Math.round(resource.quantity * resource.unit_rate * 100) / 100,
      };
      const existing = [...((pos.metadata?.resources ?? []) as Array<Record<string, unknown>>)];
      const merged = [...existing, newRes];
      let computedRate = 0;
      for (const r of merged) {
        computedRate += ((r.quantity as number) ?? 0) * ((r.unit_rate as number) ?? 0);
      }
      computedRate = Math.round(computedRate * 100) / 100;
      updateMutation.mutate({
        id: positionId,
        data: { unit_rate: computedRate, metadata: { ...pos.metadata, resources: merged } },
      });
      addToast({ type: 'success', title: t('boq.resource_added', { defaultValue: 'Resource added' }) });
    },
    [boq?.positions, updateMutation, addToast, t],
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

  /* ── AI features: Suggest Rate, Classify, Anomaly Detection ─────── */

  const [anomalyMap, setAnomalyMap] = useState<
    Map<string, { severity: string; message: string; suggestion: number }>
  >(new Map());

  // Vector DB status — check if AI features can work
  const [showVectorSetup, setShowVectorSetup] = useState(false);
  const [vectorIndexing, setVectorIndexing] = useState(false);

  const { data: vectorStatus } = useQuery({
    queryKey: ['vector-status'],
    queryFn: () => apiGet<{
      connected: boolean;
      engine?: string;
      cost_collection?: { vectors_count: number; points_count: number } | null;
    }>('/v1/costs/vector/status'),
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
        const projectStandard = (project as unknown as Record<string, unknown>)?.classification_standard as string ?? 'din276';
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
            message: `${top.standard.toUpperCase()}: ${top.code} — ${top.label} (${Math.round(top.confidence * 100)}%)`,
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

      try {
        const res = await fetch(`/api/v1/boq/boqs/${boqId}/import/smart/`, {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: form,
        });

        if (!res.ok) {
          const body = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(body.detail || 'Import failed');
        }

        const result: {
          imported: number;
          errors: { item?: string; error: string }[];
          total_items: number;
          method: string;
          model_used: string | null;
          cad_format?: string;
          cad_elements?: number;
        } = await res.json();

        let methodLabel: string;
        if (result.method === 'cad_ai') {
          methodLabel = ` (CAD + ${result.model_used ?? 'AI'}, ${result.cad_elements ?? 0} elements)`;
        } else if (result.method === 'ai') {
          methodLabel = ` (AI: ${result.model_used ?? 'auto'})`;
        } else {
          methodLabel = ' (direct)';
        }
        addToast({
          type: result.imported > 0 ? 'success' : 'warning',
          title: `Imported ${result.imported} of ${result.total_items} items${methodLabel}`,
          message:
            result.errors.length > 0
              ? `${result.errors.length} error(s) occurred`
              : undefined,
        });

        invalidateAll();
      } catch (err) {
        addToast({
          type: 'error',
          title: t('boq.import_failed', { defaultValue: 'Import failed' }),
          message: err instanceof Error ? err.message : 'Unknown error',
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
    type FooterRow = { _isFooter: true; _footerType: string; id: string; description: string; total: number; ordinal: string; unit: string; quantity: number; unit_rate: number };
    const rows: FooterRow[] = [];
    if (!hasPositions) return rows;
    const base = { _isFooter: true as const, ordinal: '', unit: '', quantity: 0, unit_rate: 0 };
    rows.push({ ...base, _footerType: 'direct_cost', id: '_direct_cost', description: t('boq.direct_cost', { defaultValue: 'DIRECT COST' }), total: directCost });
    for (const m of markupTotals) {
      rows.push({ ...base, _footerType: `markup_${m.id}`, id: `_markup_${m.id}`, description: `${m.name} ${fmt.format(m.percentage)}%`, total: m.amount });
    }
    rows.push({ ...base, _footerType: 'net_total', id: '_net_total', description: t('boq.net_total', { defaultValue: 'NET TOTAL' }), total: netTotal });
    rows.push({ ...base, _footerType: 'vat', id: '_vat', description: vatRate > 0 ? `${t('boq.vat', { defaultValue: 'VAT' })} ${fmt.format(vatRate * 100)}%` : t('boq.no_vat', { defaultValue: 'No VAT' }), total: vatAmount });
    rows.push({ ...base, _footerType: 'gross_total', id: '_gross_total', description: t('boq.gross_total', { defaultValue: 'GROSS TOTAL' }), total: grossTotal });
    return rows;
  }, [hasPositions, directCost, markupTotals, netTotal, vatRate, vatAmount, grossTotal, t, fmt]);

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

  /** Handle formula applied from AG Grid quantity editor */
  const handleGridFormulaApplied = useCallback(
    (positionId: string, formula: string, _result: number) => {
      const pos = boq?.positions.find((p) => p.id === positionId);
      if (!pos) return;
      updateMutation.mutate({
        id: positionId,
        data: { metadata: { ...pos.metadata, formula } },
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
      <div className="max-w-content mx-auto py-8 animate-fade-in">
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
      <div className="max-w-content mx-auto py-16 text-center">
        <p className="text-content-secondary">{t('boq.not_found', { defaultValue: 'BOQ not found' })}</p>
      </div>
    );
  }

  /* ── Render ────────────────────────────────────────────────────────── */

  return (
    <div
      ref={editorContainerRef}
      tabIndex={-1}
      className="max-w-content mx-auto animate-fade-in pb-12 outline-none"
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
              <Button variant="secondary" size="sm" onClick={handleLock} disabled={lockMutation.isPending}>
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
            <Button variant="secondary" size="sm" onClick={handleCreateRevision} disabled={createRevisionMutation.isPending}>
              <Copy size={14} className="mr-1" />
              {t('boq.create_revision', { defaultValue: 'Create Revision' })}
            </Button>
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
          onRenumber={handleRenumber}
          isRenumbering={renumberMutation.isPending}
          hasPositions={hasPositions}
          qualityBreakdown={qualityBreakdown}
          qualityScoreRing={<QualityScoreRing score={qualityBreakdown.score} breakdown={qualityBreakdown} t={t} />}
        />
      </div>

      {/* ── Tips panel (collapsed by default, compact) ──────────────── */}
      {tips.length > 0 && !hasPositions && (
        <div className="mb-3">
          <TipsPanel tips={tips} t={t} />
        </div>
      )}

      {/* ── BOQ Table (AG Grid) ───────────────────────────────────────── */}
      {hasPositions ? (
        <div className="mb-2"><BOQGrid
          ref={boqGridRef}
          positions={boq.positions}
          onUpdatePosition={trackedUpdate}
          onDeletePosition={trackedDelete}
          onAddPosition={handleAddPosition}
          onSelectSuggestion={handleGridSelectSuggestion}
          onSaveToDatabase={handleGridSaveToDatabase}
          onAddComment={handleAddComment}
          onFormulaApplied={handleGridFormulaApplied}
          onReorderPositions={handleReorderPositions}
          collapsedSections={collapsedSections}
          onToggleSection={toggleSection}
          highlightPositionId={newPositionId ?? undefined}
          currencySymbol={currencySymbol}
          currencyCode={currencyCode}
          locale={locale}
          footerRows={boqFooterRows}
          onSelectionChanged={handleSelectionChanged}
          onRemoveResource={handleRemoveResource}
          onUpdateResource={handleUpdateResource}
          onSaveResourceToCatalog={handleSaveResourceToCatalog}
          onOpenCostDbForPosition={handleOpenCostDbForPosition}
          onOpenCatalogForPosition={handleOpenCatalogForPosition}
          onAddManualResource={handleAddManualResource}
          onDuplicatePosition={handleDuplicatePosition}
          onSuggestRate={handleSuggestRate}
          onClassify={handleClassify}
          onCheckAnomalies={handleCheckAnomalies}
          anomalyMap={anomalyMap}
          onApplyAnomalySuggestion={handleApplyAnomalySuggestion}
          onSaveAsAssembly={handleSaveAsAssembly}
          customColumns={boqCustomColumns}
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
        <MarkupPanel
          boqId={boqId}
          markups={markups}
          directCost={directCost}
          currencySymbol={currencySymbol}
          currencyCode={currencyCode}
          locale={locale}
          fmt={fmt}
        />
      )}

      {/* ── Resource Summary ──────────────────────────────────────────── */}
      {boqId && hasPositions && <div className="mt-6"><ResourceSummary boqId={boqId} locale={locale} /></div>}

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
          onSelectForResources={costDbForPositionId ? (item) => {
            handleCostDbAddResource({
              code: item.code,
              description: item.description,
              unit: item.unit,
              rate: item.rate,
              classification: item.classification || {},
              components: (item.components || []).map((c) => ({
                name: c.name,
                code: c.code,
                unit: c.unit,
                quantity: c.quantity,
                unit_rate: c.unit_rate,
                cost: c.cost,
                type: c.type,
              })),
            });
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
            addToast({ type: 'success', title: 'Assembly applied to BOQ' });
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
        onUseTemplate={() => {
          addToast({
            type: 'info',
            title: t('boq.templates_coming_soon', { defaultValue: 'Templates coming soon' }),
            message: t('boq.templates_coming_soon_desc', { defaultValue: 'The template selector will be available in a future update.' }),
          });
        }}
        t={t}
      />

      {/* ── Batch Action Bar ──────────────────────────────────────── */}
      <BatchActionBar
        selectedIds={selectedPositionIds}
        onBatchDelete={handleBatchDelete}
        onBatchChangeUnit={handleBatchChangeUnit}
        onClearSelection={handleClearSelection}
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fade-in" onClick={() => setShowRecalcConfirm(false)}>
          <div className="w-full max-w-md mx-4 rounded-2xl bg-surface-primary shadow-2xl border border-border-light overflow-hidden animate-scale-in" onClick={(e) => e.stopPropagation()}>
            <div className="px-6 py-5">
              <div className="flex items-center gap-3 mb-3">
                <div className="h-10 w-10 rounded-xl bg-blue-50 dark:bg-blue-950/30 flex items-center justify-center">
                  <Database size={20} className="text-oe-blue" />
                </div>
                <div>
                  <h3 className="text-base font-semibold">{t('boq.recalc_confirm_title', { defaultValue: 'Update Unit Rates' })}</h3>
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
            className="bg-surface-elevated rounded-xl border border-border-light shadow-lg w-[420px] p-6 animate-scale-in"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-semibold text-content-primary">
                {t('boq.gaeb_export_title', { defaultValue: 'Export GAEB XML (X83)' })}
              </h3>
              <button
                onClick={() => setGaebPreviewOpen(false)}
                className="p-1 rounded-lg text-content-tertiary hover:bg-surface-secondary transition-colors"
              >
                <X size={16} />
              </button>
            </div>

            <p className="text-xs text-content-secondary leading-relaxed mb-4">
              {t('boq.gaeb_export_desc', {
                defaultValue:
                  'This will export your BOQ as GAEB XML 3.3 format, compatible with German tender workflows (DIN 276).',
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

      {/* ── Section Name Modal ────────────────────────────────────── */}
      {showSectionModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setShowSectionModal(false)}>
          <div
            className="bg-surface-elevated rounded-xl border border-border-light shadow-lg w-96 p-5 animate-scale-in"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-sm font-semibold text-content-primary mb-3">
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

      {/* ── Vector DB Setup Dialog ───────────────────────────────────── */}
      {showVectorSetup && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={() => setShowVectorSetup(false)} />
          <div className="relative w-full max-w-md rounded-2xl border border-border-light bg-surface-elevated shadow-2xl animate-form-scale-in">
            <button
              onClick={() => setShowVectorSetup(false)}
              className="absolute top-3 right-3 p-1.5 rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
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
    </div>
  );
}
