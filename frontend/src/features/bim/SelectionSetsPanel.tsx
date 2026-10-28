// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** 
 * SelectionSetsPanel — right-rail panel for named selection sets.
 *
 * Part of v3.13.0 W6.6 "BIM Viewer Pro UX". Lists per-model selection sets
 * persisted in ``SelectionSetsStore`` (localStorage). Each row supports:
 *   - Restore        (replaces current viewer selection — exclusive)
 *   - Add to current (merges into existing selection)
 *   - Update from current (overwrites the set's elements with what's
 *                          selected in the viewer)
 *   - Rename         (double-click name, Enter to commit, Esc to cancel)
 *   - Colour tag     (6-swatch picker)
 *   - Delete         (inline confirm-then-remove)
 *
 * SelectionManager API consumed (see SelectionManager.ts):
 *   getSelectedIds(): string[]
 *   selectByIds(ids: string[], options?: { exclusive?: boolean }): void
 *
 * The panel never owns the viewer's selection state — it only reads it
 * on demand and pushes new selections back through ``selectByIds``. That
 * keeps the panel ignorant of viewer internals (Three.js, raycasting,
 * material restoration) and lets it work even before the viewer scene
 * fully loads (the manager is null until the model is ready, in which
 * case the actions just no-op rather than crashing).
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Bookmark,
  PlusCircle,
  Crosshair,
  Plus,
  RefreshCw,
  Trash2,
  Check,
  X,
  Folder,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import type { SelectionManager } from '@/shared/ui/BIMViewer';
import {
  selectionSetsStore,
  type SelectionSet,
} from '@/shared/ui/BIMViewer/SelectionSetsStore';

interface SelectionSetsPanelProps {
  /** Active BIM model id. When null, the panel renders a "no model" hint. */
  modelId: string | null;
  /** Selection manager from the active viewer. Null while the viewer is
   *  still bootstrapping (no scene yet) — actions are disabled in that case. */
  selectionManager: SelectionManager | null;
  className?: string;
}

const SWATCH_COLORS: { name: string; hex: string }[] = [
  { name: 'gray', hex: '#9ca3af' },
  { name: 'blue', hex: '#2979ff' },
  { name: 'green', hex: '#10b981' },
  { name: 'yellow', hex: '#f59e0b' },
  { name: 'rose', hex: '#f43f5e' },
  { name: 'violet', hex: '#8b5cf6' },
];

/** One folder bucket of selection sets. ``folder === null`` is the ungrouped
 *  bucket, always rendered first (B4). */
export interface SelectionSetFolderGroup {
  folder: string | null;
  sets: SelectionSet[];
}

/** Group sets into ordered folder buckets: ungrouped first, then folders in
 *  natural-sort order. Blank / missing folders fold into the ungrouped bucket. */
export function groupSetsByFolder(
  sets: SelectionSet[],
): SelectionSetFolderGroup[] {
  const ungrouped: SelectionSet[] = [];
  const byFolder = new Map<string, SelectionSet[]>();
  for (const s of sets) {
    const folder = (s.folder ?? '').trim();
    if (!folder) {
      ungrouped.push(s);
      continue;
    }
    const bucket = byFolder.get(folder) ?? [];
    bucket.push(s);
    byFolder.set(folder, bucket);
  }
  const collator = new Intl.Collator(undefined, {
    numeric: true,
    sensitivity: 'base',
  });
  const groups: SelectionSetFolderGroup[] = [];
  if (ungrouped.length) groups.push({ folder: null, sets: ungrouped });
  for (const folder of Array.from(byFolder.keys()).sort((a, b) =>
    collator.compare(a, b),
  )) {
    groups.push({ folder, sets: byFolder.get(folder) ?? [] });
  }
  return groups;
}

export default function SelectionSetsPanel({
  modelId,
  selectionManager,
  className,
}: SelectionSetsPanelProps) {
  const { t } = useTranslation();

  const [sets, setSets] = useState<SelectionSet[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [draftName, setDraftName] = useState('');
  const [draftFolder, setDraftFolder] = useState('');
  const [createError, setCreateError] = useState<string | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState('');
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<string | null>(null);
  const [colorPickerId, setColorPickerId] = useState<string | null>(null);
  const [currentSelectionCount, setCurrentSelectionCount] = useState(0);
  /** Set whose folder is being edited inline (B4), plus the draft value. */
  const [folderEditId, setFolderEditId] = useState<string | null>(null);
  const [folderEditDraft, setFolderEditDraft] = useState('');
  /** Folders the user has collapsed in the list. */
  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(
    () => new Set(),
  );

  const existingFolders = useMemo<string[]>(() => {
    const labels = new Set<string>();
    for (const s of sets) {
      const f = (s.folder ?? '').trim();
      if (f) labels.add(f);
    }
    return Array.from(labels).sort((a, b) => a.localeCompare(b));
  }, [sets]);

  const groups = useMemo(() => groupSetsByFolder(sets), [sets]);

  const toggleFolder = useCallback((folder: string) => {
    setCollapsedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(folder)) next.delete(folder);
      else next.add(folder);
      return next;
    });
  }, []);

  const refresh = useCallback(() => {
    if (!modelId) {
      setSets([]);
      return;
    }
    setSets(selectionSetsStore.list(modelId));
  }, [modelId]);

  // Subscribe to store mutations (including cross-tab) so the panel stays
  // in sync when another tab edits the same set.
  useEffect(() => {
    refresh();
    const unsub = selectionSetsStore.subscribe(refresh);
    return unsub;
  }, [refresh]);

  // Track current selection count so the header can show the right hint
  // and disable "Save" when nothing is selected. Polled at 500ms — cheaper
  // than wiring a callback through the parent for a UX-only badge.
  useEffect(() => {
    if (!selectionManager) {
      setCurrentSelectionCount(0);
      return undefined;
    }
    const tick = () => setCurrentSelectionCount(selectionManager.getSelectedIds().length);
    tick();
    const handle = window.setInterval(tick, 500);
    return () => window.clearInterval(handle);
  }, [selectionManager]);

  const canCreate = useMemo(() => {
    return !!modelId && !!selectionManager && currentSelectionCount > 0;
  }, [modelId, selectionManager, currentSelectionCount]);

  // ── Row actions ────────────────────────────────────────────────────

  const handleRestore = useCallback(
    (set: SelectionSet) => {
      if (!selectionManager) return;
      selectionManager.selectByIds(set.elementIds, { exclusive: true });
    },
    [selectionManager],
  );

  const handleAddToSelection = useCallback(
    (set: SelectionSet) => {
      if (!selectionManager) return;
      selectionManager.selectByIds(set.elementIds, { exclusive: false });
    },
    [selectionManager],
  );

  const handleUpdateFromCurrent = useCallback(
    (set: SelectionSet) => {
      if (!selectionManager) return;
      const ids = selectionManager.getSelectedIds();
      try {
        selectionSetsStore.update(set.id, { elementIds: ids });
      } catch {
        // No-op — surface via console in dev. In production a toast would
        // be wired through useToastStore, but the panel intentionally has
        // no toast dependency so it can be mounted in lightweight contexts.
      }
    },
    [selectionManager],
  );

  const handleDeleteConfirm = useCallback((id: string) => {
    selectionSetsStore.delete(id);
    setConfirmingDeleteId(null);
  }, []);

  const handleStartRename = useCallback((set: SelectionSet) => {
    setRenamingId(set.id);
    setRenameDraft(set.name);
  }, []);

  const handleCommitRename = useCallback(
    (set: SelectionSet) => {
      const trimmed = renameDraft.trim();
      if (!trimmed || trimmed === set.name) {
        setRenamingId(null);
        return;
      }
      try {
        selectionSetsStore.update(set.id, { name: trimmed });
      } catch {
        // Validation failure — keep the input open so the user can fix it.
        return;
      }
      setRenamingId(null);
    },
    [renameDraft],
  );

  const handleCancelRename = useCallback(() => {
    setRenamingId(null);
    setRenameDraft('');
  }, []);

  const handlePickColor = useCallback((set: SelectionSet, hex: string | undefined) => {
    selectionSetsStore.update(set.id, { color: hex });
    setColorPickerId(null);
  }, []);

  // ── Create flow ────────────────────────────────────────────────────

  const handleOpenCreate = useCallback(() => {
    setShowCreate(true);
    setDraftName('');
    setDraftFolder('');
    setCreateError(null);
  }, []);

  const handleCancelCreate = useCallback(() => {
    setShowCreate(false);
    setDraftName('');
    setDraftFolder('');
    setCreateError(null);
  }, []);

  const handleSubmitCreate = useCallback(() => {
    if (!modelId || !selectionManager) return;
    const ids = selectionManager.getSelectedIds();
    if (ids.length === 0) {
      setCreateError(
        t('bim.selection_sets_no_selection_create', {
          defaultValue: 'Select at least one element in the viewer first.',
        }),
      );
      return;
    }
    try {
      selectionSetsStore.create(modelId, draftName, ids, {
        folder: draftFolder,
      });
      setShowCreate(false);
      setDraftName('');
      setDraftFolder('');
      setCreateError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setCreateError(msg);
    }
  }, [modelId, selectionManager, draftName, draftFolder, t]);

  // ── Move to folder (B4) ────────────────────────────────────────────

  const handleStartFolderEdit = useCallback((set: SelectionSet) => {
    setFolderEditId(set.id);
    setFolderEditDraft(set.folder ?? '');
  }, []);

  const handleCommitFolderEdit = useCallback(
    (set: SelectionSet) => {
      try {
        // "" clears the folder (back to ungrouped); the store normalises it.
        selectionSetsStore.update(set.id, { folder: folderEditDraft });
      } catch {
        // Keep the input open so the user can fix an over-long label.
        return;
      }
      setFolderEditId(null);
      setFolderEditDraft('');
    },
    [folderEditDraft],
  );

  const handleCancelFolderEdit = useCallback(() => {
    setFolderEditId(null);
    setFolderEditDraft('');
  }, []);

  // ── Render ─────────────────────────────────────────────────────────

  if (!modelId) {
    return (
      <div
        className={`flex flex-col gap-2 p-3 ${className ?? ''}`}
        data-testid="bim-selection-sets-panel"
      >
        <p className="text-[11px] text-content-tertiary italic">
          {t('bim.selection_sets_no_model', {
            defaultValue: 'Load a BIM model to manage selection sets.',
          })}
        </p>
      </div>
    );
  }

  const renderSetRow = (set: SelectionSet) => {
    const isRenaming = renamingId === set.id;
    const isConfirmingDelete = confirmingDeleteId === set.id;
    const isPickingColor = colorPickerId === set.id;
    const isEditingFolder = folderEditId === set.id;
    return (
      <li
        key={set.id}
        data-testid={`bim-selection-set-row-${set.id}`}
        className="flex flex-col gap-1 rounded-md border border-border-light bg-surface-primary px-2 py-1.5"
      >
        <div className="flex items-center gap-1.5 min-w-0">
          {/* Colour tag */}
          <button
            type="button"
            onClick={() => setColorPickerId(isPickingColor ? null : set.id)}
            aria-label={t('bim.selection_sets_color_aria', {
              defaultValue: 'Pick colour tag',
            })}
            className="shrink-0 h-3 w-3 rounded-full border border-border-light"
            style={{ backgroundColor: set.color ?? '#cbd5e1' }}
          />
          {isRenaming ? (
            <input
              type="text"
              value={renameDraft}
              onChange={(e) => setRenameDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleCommitRename(set);
                if (e.key === 'Escape') handleCancelRename();
              }}
              onBlur={() => handleCommitRename(set)}
              autoFocus
              maxLength={60}
              data-testid={`bim-selection-set-rename-input-${set.id}`}
              className="flex-1 min-w-0 rounded border border-border-light bg-surface-secondary px-1 py-0.5 text-[11px]"
            />
          ) : (
            <button
              type="button"
              onDoubleClick={() => handleStartRename(set)}
              title={t('bim.selection_sets_rename_hint', {
                defaultValue: 'Double-click to rename',
              })}
              className="flex-1 min-w-0 text-left text-[11px] font-medium text-content-primary truncate"
              data-testid={`bim-selection-set-name-${set.id}`}
            >
              {set.name}
            </button>
          )}
          <span className="text-[10px] text-content-tertiary tabular-nums shrink-0">
            {set.elementIds.length}
          </span>
          {/* Move to folder (B4) */}
          <button
            type="button"
            onClick={() => handleStartFolderEdit(set)}
            aria-label={t('bim.selection_sets_move_folder', {
              defaultValue: 'Move to folder',
            })}
            title={t('bim.selection_sets_move_folder', {
              defaultValue: 'Move to folder',
            })}
            data-testid={`bim-selection-set-folder-btn-${set.id}`}
            className="shrink-0 inline-flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:bg-surface-tertiary"
          >
            <Folder size={11} />
          </button>
        </div>

        {/* Inline folder editor (B4) */}
        {isEditingFolder && (
          <div
            className="flex items-center gap-1"
            data-testid={`bim-selection-set-folder-editor-${set.id}`}
          >
            <input
              type="text"
              value={folderEditDraft}
              onChange={(e) => setFolderEditDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleCommitFolderEdit(set);
                if (e.key === 'Escape') handleCancelFolderEdit();
              }}
              list="bim-selection-set-folders"
              maxLength={60}
              autoFocus
              placeholder={t('bim.selection_sets_folder_placeholder', {
                defaultValue: 'Folder (optional)',
              })}
              data-testid={`bim-selection-set-folder-edit-input-${set.id}`}
              className="flex-1 min-w-0 rounded border border-border-light bg-surface-secondary px-1 py-0.5 text-[11px]"
            />
            <button
              type="button"
              onClick={() => handleCommitFolderEdit(set)}
              aria-label={t('common.confirm', { defaultValue: 'Confirm' })}
              className="inline-flex h-5 w-5 items-center justify-center rounded text-emerald-600 hover:bg-emerald-50"
            >
              <Check size={11} />
            </button>
            <button
              type="button"
              onClick={handleCancelFolderEdit}
              aria-label={t('common.cancel', { defaultValue: 'Cancel' })}
              className="inline-flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:bg-surface-tertiary"
            >
              <X size={11} />
            </button>
          </div>
        )}

        {/* Colour swatch picker */}
        {isPickingColor && (
          <div
            className="flex items-center gap-1"
            data-testid={`bim-selection-set-color-picker-${set.id}`}
          >
            {SWATCH_COLORS.map((c) => (
              <button
                key={c.name}
                type="button"
                onClick={() => handlePickColor(set, c.hex)}
                aria-label={c.name}
                className="h-4 w-4 rounded-full border border-border-light"
                style={{ backgroundColor: c.hex }}
              />
            ))}
            <button
              type="button"
              onClick={() => handlePickColor(set, undefined)}
              aria-label={t('bim.selection_sets_clear_color', {
                defaultValue: 'Clear colour',
              })}
              className="h-4 w-4 rounded-full border border-border-light bg-surface-secondary text-[8px] text-content-tertiary flex items-center justify-center"
            >
              <X size={8} />
            </button>
          </div>
        )}

        {/* Action row */}
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => handleRestore(set)}
            disabled={!selectionManager}
            title={t('bim.selection_sets_restore', {
              defaultValue: 'Restore selection',
            })}
            data-testid={`bim-selection-set-restore-${set.id}`}
            className="inline-flex items-center justify-center gap-1 px-2 py-0.5 rounded text-[10px] text-content-secondary hover:bg-surface-tertiary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Crosshair size={10} />
            {t('bim.selection_sets_restore_short', {
              defaultValue: 'Restore',
            })}
          </button>
          <button
            type="button"
            onClick={() => handleAddToSelection(set)}
            disabled={!selectionManager}
            title={t('bim.selection_sets_add', {
              defaultValue: 'Add to current selection',
            })}
            data-testid={`bim-selection-set-add-${set.id}`}
            className="inline-flex items-center justify-center gap-1 px-2 py-0.5 rounded text-[10px] text-content-secondary hover:bg-surface-tertiary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Plus size={10} />
            {t('bim.selection_sets_add_short', { defaultValue: 'Add' })}
          </button>
          <button
            type="button"
            onClick={() => handleUpdateFromCurrent(set)}
            disabled={!selectionManager || currentSelectionCount === 0}
            title={t('bim.selection_sets_update', {
              defaultValue: 'Replace with current selection',
            })}
            data-testid={`bim-selection-set-update-${set.id}`}
            className="inline-flex items-center justify-center gap-1 px-2 py-0.5 rounded text-[10px] text-content-secondary hover:bg-surface-tertiary disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <RefreshCw size={10} />
            {t('bim.selection_sets_update_short', {
              defaultValue: 'Update',
            })}
          </button>
          <div className="flex-1" />
          {isConfirmingDelete ? (
            <>
              <button
                type="button"
                onClick={() => handleDeleteConfirm(set.id)}
                data-testid={`bim-selection-set-delete-confirm-${set.id}`}
                className="inline-flex items-center justify-center px-2 py-0.5 rounded text-[10px] text-white bg-rose-600 hover:bg-rose-700"
              >
                {t('common.confirm', { defaultValue: 'Confirm' })}
              </button>
              <button
                type="button"
                onClick={() => setConfirmingDeleteId(null)}
                className="inline-flex items-center justify-center px-2 py-0.5 rounded text-[10px] text-content-tertiary hover:bg-surface-tertiary"
              >
                {t('common.cancel', { defaultValue: 'Cancel' })}
              </button>
            </>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmingDeleteId(set.id)}
              aria-label={t('common.delete', { defaultValue: 'Delete' })}
              data-testid={`bim-selection-set-delete-${set.id}`}
              className="inline-flex h-5 w-5 items-center justify-center rounded text-content-tertiary hover:bg-rose-50 hover:text-rose-600"
            >
              <Trash2 size={10} />
            </button>
          )}
        </div>
      </li>
    );
  };

  return (
    <div
      className={`flex flex-col gap-3 p-3 ${className ?? ''}`}
      data-testid="bim-selection-sets-panel"
    >
      {/* Header */}
      <section className="flex flex-col gap-2">
        <h3 className="text-xs font-semibold text-content-primary uppercase tracking-wide">
          {t('bim.selection_sets_title', { defaultValue: 'Selection sets' })}
        </h3>
        {!showCreate ? (
          <>
            <button
              type="button"
              onClick={handleOpenCreate}
              disabled={!canCreate}
              data-testid="bim-selection-set-save-new"
              className={`flex items-center justify-center gap-2 px-3 py-1.5 rounded-md text-[11px] font-medium border transition-colors ${
                canCreate
                  ? 'bg-oe-blue/10 text-oe-blue border-oe-blue/40 hover:bg-oe-blue/20'
                  : 'bg-surface-secondary text-content-tertiary border-border-light cursor-not-allowed'
              }`}
            >
              <Bookmark size={12} />
              {t('bim.selection_sets_save_new', {
                defaultValue: 'Save current selection as new set...',
              })}
            </button>
            {currentSelectionCount === 0 ? (
              <p className="text-[10px] text-content-tertiary">
                {t('bim.selection_sets_hint_empty', {
                  defaultValue:
                    "Select elements in the viewer, then click here to save them as a set.",
                })}
              </p>
            ) : (
              <p className="text-[10px] text-content-tertiary">
                {t('bim.selection_sets_hint_active', {
                  defaultValue: '{{count}} element(s) currently selected.',
                  count: currentSelectionCount,
                })}
              </p>
            )}
          </>
        ) : (
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-1">
              <input
                type="text"
                value={draftName}
                onChange={(e) => setDraftName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleSubmitCreate();
                  if (e.key === 'Escape') handleCancelCreate();
                }}
                autoFocus
                maxLength={60}
                placeholder={t('bim.selection_sets_name_placeholder', {
                  defaultValue: 'e.g. Level 3 Columns',
                })}
                data-testid="bim-selection-set-name-input"
                className="flex-1 min-w-0 rounded border border-border-light bg-surface-primary px-2 py-1 text-[11px] focus:outline-none focus:ring-1 focus:ring-oe-blue"
              />
              <button
                type="button"
                onClick={handleSubmitCreate}
                aria-label={t('common.confirm', { defaultValue: 'Confirm' })}
                data-testid="bim-selection-set-create-confirm"
                className="inline-flex h-6 w-6 items-center justify-center rounded text-emerald-600 hover:bg-emerald-50"
              >
                <Check size={12} />
              </button>
              <button
                type="button"
                onClick={handleCancelCreate}
                aria-label={t('common.cancel', { defaultValue: 'Cancel' })}
                className="inline-flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:bg-surface-tertiary"
              >
                <X size={12} />
              </button>
            </div>
            {/* Optional folder for the new set (B4) */}
            <input
              type="text"
              value={draftFolder}
              onChange={(e) => setDraftFolder(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSubmitCreate();
                if (e.key === 'Escape') handleCancelCreate();
              }}
              list="bim-selection-set-folders"
              maxLength={60}
              placeholder={t('bim.selection_sets_folder_placeholder', {
                defaultValue: 'Folder (optional)',
              })}
              data-testid="bim-selection-set-folder-input"
              className="rounded border border-border-light bg-surface-primary px-2 py-1 text-[11px] focus:outline-none focus:ring-1 focus:ring-oe-blue"
            />
            {createError ? (
              <p className="text-[10px] text-rose-600">{createError}</p>
            ) : (
              <p className="text-[10px] text-content-tertiary">
                {t('bim.selection_sets_create_hint', {
                  defaultValue:
                    '{{count}} element(s) will be saved into this set.',
                  count: currentSelectionCount,
                })}
              </p>
            )}
          </div>
        )}
      </section>

      {/* Shared folder suggestions for the create + move-to-folder inputs (B4). */}
      <datalist id="bim-selection-set-folders">
        {existingFolders.map((f) => (
          <option key={f} value={f} />
        ))}
      </datalist>

      {/* List */}
      <section
        className="flex flex-col gap-2"
        data-testid="bim-selection-sets-list"
      >
        {sets.length === 0 ? (
          <p
            className="text-[11px] text-content-tertiary italic"
            data-testid="bim-selection-sets-empty"
          >
            {t('bim.selection_sets_empty', {
              defaultValue:
                "No sets saved yet. Pick elements in the viewer and click 'Save current selection as new set'.",
            })}
          </p>
        ) : (
          groups.map((group) => {
            if (group.folder === null) {
              // Ungrouped bucket — rows render directly with no header.
              return (
                <ul
                  key="__ungrouped__"
                  className="flex flex-col gap-1"
                  data-testid="bim-selection-sets-ungrouped"
                >
                  {group.sets.map((set) => renderSetRow(set))}
                </ul>
              );
            }
            const folderName = group.folder;
            const isCollapsed = collapsedFolders.has(folderName);
            return (
              <div
                key={folderName}
                className="flex flex-col gap-1"
                data-testid={`bim-selection-set-folder-${folderName}`}
              >
                <button
                  type="button"
                  onClick={() => toggleFolder(folderName)}
                  data-testid={`bim-selection-set-folder-toggle-${folderName}`}
                  className="flex items-center gap-1 px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-content-secondary hover:bg-surface-tertiary rounded"
                >
                  {isCollapsed ? (
                    <ChevronRight size={11} />
                  ) : (
                    <ChevronDown size={11} />
                  )}
                  <Folder size={11} />
                  <span className="truncate" title={folderName}>
                    {folderName}
                  </span>
                  <span className="text-content-tertiary tabular-nums">
                    ({group.sets.length})
                  </span>
                </button>
                {!isCollapsed && (
                  <ul className="flex flex-col gap-1 pl-2">
                    {group.sets.map((set) => renderSetRow(set))}
                  </ul>
                )}
              </div>
            );
          })
        )}
      </section>

      {/* Footer help — hidden when no sets exist (empty-state already
          covers it). */}
      {sets.length > 0 && (
        <p className="text-[10px] text-content-tertiary">
          <PlusCircle size={10} className="inline mr-1" />
          {t('bim.selection_sets_footer_hint', {
            defaultValue:
              'Sets are stored locally for this model. Use Restore to bring back a saved selection.',
          })}
        </p>
      )}
    </div>
  );
}
