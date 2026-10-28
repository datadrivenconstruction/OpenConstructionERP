// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * DwgDrawingCompareDrawer — revision compare with cost delta (Item 17).
 *
 * Right-side slide-over that diffs two parsed versions of the same DWG/DXF
 * drawing. Three tabs:
 *   - Entities:    per-layer entity-count changes (added / removed / count).
 *   - Annotations: per-annotation changes with a money cost impact for any
 *                  annotation linked to a BOQ position whose value changed.
 *   - Summary:     traffic-light tallies + net cost impact.
 *
 * Controls:
 *   - Two version selectors (baseline "before" + target "after").
 *   - "Hide unchanged" toggle to focus on real changes.
 *   - "Onion-skin overlay" toggle + opacity slider — a visual blend hint
 *     surfaced back to the page via ``onOverlayChange`` so the canvas can
 *     dim the older revision under the newer one.
 *
 * All money is rendered with the shared MoneyDisplay (green/red via
 * ``colorize``) and never blends currencies — the backend returns the
 * impact already expressed in the project base currency.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import {
  GitCompare,
  Loader2,
  ArrowRight,
  Layers,
  MessageSquare,
  BarChart3,
  Eye,
  FilePlus2,
  FileStack,
  Upload,
} from 'lucide-react';

import { SideDrawer, MoneyDisplay, Badge } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import {
  fetchDrawingVersions,
  fetchDrawings,
  uploadDrawing,
  uploadDrawingRevision,
  compareDrawings,
  compareDrawingPair,
  createVariationFromDiff,
  createVariationFromDrawingPair,
  type DwgDrawing,
  type DwgDrawingVersion,
  type DwgDrawingDiffResponse,
  type DwgEntityDiffRow,
  type DwgAnnotationDiffRow,
} from './api';
import { fmtFixed } from '@/shared/lib/formatters';

type CompareTab = 'entities' | 'annotations' | 'summary';

export interface DwgCompareOverlayState {
  /** Whether the onion-skin overlay hint is active. */
  enabled: boolean;
  /** 0..1 opacity for the underlay (older revision). */
  opacity: number;
}

export interface DwgDrawingCompareDrawerProps {
  open: boolean;
  onClose: () => void;
  drawingId: string;
  drawingName: string;
  /** Project the drawing belongs to. Powers the "compare against" picker
   *  (other ready drawings in the project) and the inline upload target. */
  projectId: string;
  /** Notifies the page so the canvas can render the onion-skin underlay. */
  onOverlayChange?: (state: DwgCompareOverlayState) => void;
}

const CHANGE_DOT: Record<DwgEntityDiffRow['change_type'], string> = {
  added: 'bg-emerald-500',
  removed: 'bg-red-500',
  modified: 'bg-amber-500',
  unchanged: 'bg-slate-400',
};

function ChangeBadge({ type }: { type: DwgEntityDiffRow['change_type'] }) {
  const { t } = useTranslation();
  const label = t(`dwg_compare.change_${type}`, {
    defaultValue:
      type === 'added'
        ? 'Added'
        : type === 'removed'
          ? 'Removed'
          : type === 'modified'
            ? 'Modified'
            : 'Unchanged',
  });
  return (
    <span className="inline-flex items-center gap-1 text-[10px] font-medium text-content-secondary">
      <span className={clsx('h-2 w-2 rounded-full', CHANGE_DOT[type])} />
      {label}
    </span>
  );
}

function versionLabel(v: DwgDrawingVersion, t: TFunction): string {
  return t('dwg_compare.version_option', {
    defaultValue: 'v{{n}} · {{count}} entities',
    n: v.version_number,
    count: v.entity_count,
  });
}

export function DwgDrawingCompareDrawer({
  open,
  onClose,
  drawingId,
  drawingName,
  projectId,
  onOverlayChange,
}: DwgDrawingCompareDrawerProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const revisionInputRef = useRef<HTMLInputElement | null>(null);

  const [tab, setTab] = useState<CompareTab>('summary');
  const [fromId, setFromId] = useState<string>('');
  const [toId, setToId] = useState<string>('');
  // Empty string = version-vs-version mode (revisions of THIS drawing); a
  // drawing id = drawing-vs-drawing mode (compare against another drawing).
  const [targetDrawingId, setTargetDrawingId] = useState<string>('');
  // After an "Upload new revision", the id of the freshly appended version.
  // We hold it until it shows up (parsed) in the refetched versions list, then
  // auto-select it as the "after" side so the diff runs against the previous
  // revision. Cleared once selected.
  const [pendingRevisionVersionId, setPendingRevisionVersionId] = useState<string | null>(null);
  const [hideUnchanged, setHideUnchanged] = useState(true);
  const [overlay, setOverlay] = useState(false);
  const [opacity, setOpacity] = useState(0.5);

  const mode: 'version' | 'pair' = targetDrawingId ? 'pair' : 'version';

  const versionsQuery = useQuery({
    queryKey: ['dwg-versions', drawingId],
    queryFn: () => fetchDrawingVersions(drawingId),
    enabled: open && !!drawingId,
    // While a just-uploaded revision is still parsing, poll so it flips to
    // "ready" and the version diff runs automatically (mirrors the pair-mode
    // upload poll below).
    refetchInterval: (q) => {
      if (!pendingRevisionVersionId) return false;
      const list = (q.state.data as DwgDrawingVersion[] | undefined) ?? [];
      const v = list.find((x) => x.id === pendingRevisionVersionId);
      if (v && (!v.status || v.status === 'ready')) return false;
      return 3000;
    },
  });

  const versions = useMemo(() => versionsQuery.data ?? [], [versionsQuery.data]);

  // Drawings in the project usable as a comparison target. Shares the page's
  // query key so the cache is reused (and refreshed after an inline upload).
  const drawingsQuery = useQuery({
    queryKey: ['dwg-drawings', projectId],
    queryFn: () => fetchDrawings(projectId),
    enabled: open && !!projectId,
    // Poll while a just-uploaded target is still converting so the diff runs
    // automatically the moment it reaches "ready".
    refetchInterval: (q) => {
      const list = (q.state.data as DwgDrawing[] | undefined) ?? [];
      const target = list.find((d) => d.id === targetDrawingId);
      const s = target?.status;
      if (!targetDrawingId || !target) return false;
      if (s === 'ready' || s === 'error' || s === 'empty' || s === 'needs_conversion') {
        return false;
      }
      return 3000;
    },
  });

  const drawings = useMemo(() => drawingsQuery.data ?? [], [drawingsQuery.data]);
  const otherDrawings = useMemo(
    () => drawings.filter((d) => d.id !== drawingId && d.status === 'ready'),
    [drawings, drawingId],
  );
  const targetDrawing = useMemo(
    () => drawings.find((d) => d.id === targetDrawingId),
    [drawings, targetDrawingId],
  );
  const targetReady = targetDrawing?.status === 'ready';

  // Seed defaults once versions arrive: baseline = previous, target = latest.
  useEffect(() => {
    if (versions.length === 0) return;
    // versions come back newest-first.
    const latest = versions[0];
    if (!latest) return;
    const previous = versions[1] ?? latest;
    setToId((cur) => cur || latest.id);
    setFromId((cur) => cur || previous.id);
  }, [versions]);

  // Once a freshly uploaded revision has been parsed and shows up in the list,
  // force-select it as the "after" side (and the version just before it as the
  // baseline) so the version diff runs against the previous revision.
  useEffect(() => {
    if (!pendingRevisionVersionId) return;
    const idx = versions.findIndex((v) => v.id === pendingRevisionVersionId);
    if (idx === -1) return; // not in the refetched list yet
    const target = versions[idx];
    if (!target) return;
    if (target.status && target.status !== 'ready') return; // still parsing
    const previous = versions[idx + 1] ?? target;
    setToId(target.id);
    setFromId(previous.id);
    setPendingRevisionVersionId(null);
  }, [pendingRevisionVersionId, versions]);

  // Reset the comparison target when the drawer is pointed at another drawing
  // so a stale target from a previous drawing never leaks in.
  useEffect(() => {
    setTargetDrawingId('');
  }, [drawingId]);

  // Push overlay state up to the page whenever it changes (and clear on close).
  useEffect(() => {
    onOverlayChange?.({ enabled: overlay && open, opacity });
  }, [overlay, opacity, open, onOverlayChange]);

  useEffect(() => {
    if (!open) {
      onOverlayChange?.({ enabled: false, opacity });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const uploadMutation = useMutation({
    mutationFn: (file: File) =>
      uploadDrawing(projectId, file, file.name.replace(/\.[^./\\]+$/, ''), ''),
    onSuccess: (created) => {
      // Select the freshly uploaded drawing as the target; the drawings query
      // polls until it converts, then the diff runs automatically.
      setTargetDrawingId(created.id);
      queryClient.invalidateQueries({ queryKey: ['dwg-drawings', projectId] });
      addToast({
        type: 'success',
        title: t('dwg_compare.upload_started', {
          defaultValue: 'Uploading {{name}}',
          name: created.name || created.filename,
        }),
        message: t('dwg_compare.upload_started_hint', {
          defaultValue: 'The diff runs automatically once the drawing is ready.',
        }),
      });
    },
    onError: () => {
      addToast({
        type: 'error',
        title: t('dwg_compare.upload_error', {
          defaultValue: 'Could not upload the drawing. Please try again.',
        }),
      });
    },
  });

  // "Upload new revision": appends a version to THIS drawing (not a separate
  // drawing). Switch back to version-vs-version mode, refresh the version list
  // and, once the new revision parses, auto-select it against the previous one.
  const revisionUploadMutation = useMutation({
    mutationFn: (file: File) => uploadDrawingRevision(drawingId, file),
    onSuccess: (updated) => {
      setTargetDrawingId(''); // force version-vs-version mode
      setPendingRevisionVersionId(updated.latest_version?.id ?? null);
      queryClient.invalidateQueries({ queryKey: ['dwg-versions', drawingId] });
      queryClient.invalidateQueries({ queryKey: ['dwg-drawings', projectId] });
      addToast({
        type: 'success',
        title: t('dwg_compare.revision_uploaded', {
          defaultValue: 'New revision added',
        }),
        message: t('dwg_compare.revision_uploaded_hint', {
          defaultValue: 'The diff runs automatically against the previous revision once it is ready.',
        }),
      });
    },
    onError: () => {
      addToast({
        type: 'error',
        title: t('dwg_compare.revision_error', {
          defaultValue: 'Could not add the revision. Please try again.',
        }),
      });
    },
  });

  const canCompareVersion = mode === 'version' && !!fromId && !!toId && fromId !== toId;
  const canComparePair = mode === 'pair' && !!targetDrawingId && !!targetReady;
  const canCompare = canCompareVersion || canComparePair;

  const diffQuery = useQuery<DwgDrawingDiffResponse>({
    queryKey:
      mode === 'pair'
        ? ['dwg-compare-pair', projectId, drawingId, targetDrawingId]
        : ['dwg-compare', drawingId, fromId, toId],
    queryFn: () =>
      mode === 'pair'
        ? compareDrawingPair(projectId, drawingId, targetDrawingId)
        : compareDrawings(drawingId, fromId, toId),
    enabled: open && canCompare,
  });

  const diff = diffQuery.data;

  // The diff has a real change when any tally bucket other than "unchanged"
  // is non-zero across entities and annotations. With no changes there is
  // nothing to turn into a variation, so the button is disabled.
  const hasChanges = useMemo(() => {
    if (!diff) return false;
    const s = diff.summary;
    const sum = (tally: Record<'added' | 'removed' | 'modified' | 'unchanged', number>) =>
      (tally.added ?? 0) + (tally.removed ?? 0) + (tally.modified ?? 0);
    return sum(s.entities) > 0 || sum(s.annotations) > 0;
  }, [diff]);

  const createVariationMutation = useMutation({
    mutationFn: () => {
      if (mode === 'pair') {
        if (!canComparePair) throw new Error('no comparison selected');
        return createVariationFromDrawingPair(projectId, drawingId, targetDrawingId);
      }
      if (!canCompareVersion) throw new Error('no comparison selected');
      return createVariationFromDiff(drawingId, fromId, toId);
    },
    onSuccess: (result) => {
      addToast(
        {
          type: 'success',
          title: t('dwg_compare.variation_created', {
            defaultValue: 'Draft variation {{code}} created',
            code: result.code,
          }),
          message: t('dwg_compare.variation_created_hint', {
            defaultValue: 'Review and confirm it in the variations module before submitting.',
          }),
          action: {
            label: t('dwg_compare.view_variation', { defaultValue: 'View variation' }),
            onClick: () => navigate('/variations'),
          },
        },
        { duration: 8000 },
      );
    },
    onError: () => {
      addToast({
        type: 'error',
        title: t('dwg_compare.variation_error', {
          defaultValue: 'Could not create the variation. Please try again.',
        }),
      });
    },
  });

  const entityRows = useMemo(
    () =>
      (diff?.entity_rows ?? []).filter(
        (r) => !hideUnchanged || r.change_type !== 'unchanged',
      ),
    [diff, hideUnchanged],
  );
  const annotationRows = useMemo(
    () =>
      (diff?.annotation_rows ?? []).filter(
        (r) => !hideUnchanged || r.change_type !== 'unchanged',
      ),
    [diff, hideUnchanged],
  );

  const tabs: { id: CompareTab; label: string; icon: typeof Layers; count: number }[] = [
    {
      id: 'summary',
      label: t('dwg_compare.tab_summary', { defaultValue: 'Summary' }),
      icon: BarChart3,
      count: 0,
    },
    {
      id: 'entities',
      label: t('dwg_compare.tab_entities', { defaultValue: 'Entities' }),
      icon: Layers,
      count: entityRows.length,
    },
    {
      id: 'annotations',
      label: t('dwg_compare.tab_annotations', { defaultValue: 'Annotations' }),
      icon: MessageSquare,
      count: annotationRows.length,
    },
  ];

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      widthClass="max-w-2xl"
      title={
        <span className="inline-flex items-center gap-2">
          <GitCompare size={16} className="text-oe-blue" />
          {t('dwg_compare.title', { defaultValue: 'Compare revisions' })}
        </span>
      }
      subtitle={drawingName}
    >
      <div className="flex flex-col gap-4 p-5">
        {/* Compare-against picker: this drawing's revisions, or another
            drawing in the project (or a freshly uploaded one). */}
        <div className="flex items-end gap-2">
          <label className="flex-1 min-w-0">
            <span className="block text-[11px] font-medium text-content-tertiary mb-1">
              {t('dwg_compare.compare_against', { defaultValue: 'Compare against' })}
            </span>
            <select
              value={targetDrawingId}
              onChange={(e) => setTargetDrawingId(e.target.value)}
              data-testid="dwg-compare-target"
              className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue"
            >
              <option value="">
                {t('dwg_compare.this_drawing_revisions', {
                  defaultValue: 'Revisions of this drawing',
                })}
              </option>
              {otherDrawings.length > 0 && (
                <optgroup
                  label={t('dwg_compare.other_drawings', { defaultValue: 'Other drawings' })}
                >
                  {otherDrawings.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name || d.filename}
                    </option>
                  ))}
                </optgroup>
              )}
              {/* Keep a just-uploaded, still-converting target selectable even
                  though it is filtered out of the "ready" list above. */}
              {targetDrawing && targetDrawing.status !== 'ready' && (
                <option value={targetDrawing.id}>
                  {targetDrawing.name || targetDrawing.filename}
                </option>
              )}
            </select>
          </label>
        </div>

        {/* Two upload paths, kept visually distinct. "Upload new revision"
            appends a version to THIS drawing (revision-compare); "Compare a
            different file" uploads a SEPARATE drawing and diffs against it
            (drawing-vs-drawing). */}
        <div className="flex flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => revisionInputRef.current?.click()}
              disabled={revisionUploadMutation.isPending || !drawingId}
              data-testid="dwg-compare-upload-revision"
              className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-oe-blue/40 bg-oe-blue/5 px-2.5 py-1.5 text-xs font-semibold text-oe-blue transition hover:bg-oe-blue/10 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {revisionUploadMutation.isPending ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <FileStack size={13} />
              )}
              <span className="truncate">
                {t('dwg_compare.upload_new_revision', {
                  defaultValue: 'Upload new revision',
                })}
              </span>
            </button>
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadMutation.isPending || !projectId}
              data-testid="dwg-compare-upload"
              className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border-light px-2.5 py-1.5 text-xs font-medium text-content-secondary transition hover:bg-surface-secondary disabled:cursor-not-allowed disabled:opacity-50"
            >
              {uploadMutation.isPending ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <Upload size={13} />
              )}
              <span className="truncate">
                {t('dwg_compare.upload_other_drawing', {
                  defaultValue: 'Compare a different file',
                })}
              </span>
            </button>
          </div>
          <p className="text-[11px] leading-snug text-content-tertiary">
            {t('dwg_compare.upload_actions_hint', {
              defaultValue:
                'A new revision adds a version to this drawing. Comparing a different file diffs this drawing against a separate upload.',
            })}
          </p>
        </div>

        <input
          ref={revisionInputRef}
          type="file"
          accept=".dwg,.dxf"
          className="hidden"
          data-testid="dwg-compare-upload-revision-input"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) revisionUploadMutation.mutate(file);
            e.target.value = '';
          }}
        />
        <input
          ref={fileInputRef}
          type="file"
          accept=".dwg,.dxf"
          className="hidden"
          data-testid="dwg-compare-upload-input"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) uploadMutation.mutate(file);
            e.target.value = '';
          }}
        />

        {/* Version-vs-version pickers (revisions of the same drawing). */}
        {mode === 'version' && (
          <div className="flex items-end gap-2">
            <label className="flex-1 min-w-0">
              <span className="block text-[11px] font-medium text-content-tertiary mb-1">
                {t('dwg_compare.from_version', { defaultValue: 'Baseline (before)' })}
              </span>
              <select
                value={fromId}
                onChange={(e) => setFromId(e.target.value)}
                disabled={versions.length === 0}
                data-testid="dwg-compare-from"
                className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue"
              >
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    {versionLabel(v, t)}
                  </option>
                ))}
              </select>
            </label>
            <ArrowRight size={16} className="mb-2 shrink-0 text-content-tertiary" />
            <label className="flex-1 min-w-0">
              <span className="block text-[11px] font-medium text-content-tertiary mb-1">
                {t('dwg_compare.to_version', { defaultValue: 'Target (after)' })}
              </span>
              <select
                value={toId}
                onChange={(e) => setToId(e.target.value)}
                disabled={versions.length === 0}
                data-testid="dwg-compare-to"
                className="w-full rounded-md border border-border-light bg-surface-primary px-2 py-1.5 text-xs text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue"
              >
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    {versionLabel(v, t)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}

        {/* Drawing-vs-drawing sides (baseline = this drawing, target = picked). */}
        {mode === 'pair' && (
          <div className="flex items-center gap-2 rounded-md border border-border-light bg-surface-secondary px-3 py-2 text-xs">
            <span
              className="min-w-0 flex-1 truncate font-medium text-content-primary"
              title={drawingName}
            >
              {drawingName}
            </span>
            <ArrowRight size={13} className="shrink-0 text-content-tertiary" />
            <span
              className="min-w-0 flex-1 truncate text-right font-medium text-content-primary"
              title={targetDrawing?.name || targetDrawing?.filename || ''}
            >
              {targetDrawing?.name || targetDrawing?.filename || ''}
            </span>
          </div>
        )}

        {/* Helper notes. */}
        {mode === 'version' && versions.length < 2 && !versionsQuery.isLoading && (
          <p className="rounded-md border border-border-light bg-surface-secondary px-3 py-2 text-xs text-content-secondary">
            {t('dwg_compare.single_revision_hint', {
              defaultValue:
                'This drawing has only one revision. Pick another drawing above, or upload one, to compare.',
            })}
          </p>
        )}

        {mode === 'version' && fromId === toId && versions.length >= 2 && (
          <p className="text-xs text-content-tertiary">
            {t('dwg_compare.pick_two', {
              defaultValue: 'Pick two different revisions to compare.',
            })}
          </p>
        )}

        {mode === 'pair' && targetDrawing && !targetReady && (
          <p className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-content-secondary">
            {targetDrawing.status === 'error' ||
            targetDrawing.status === 'empty' ||
            targetDrawing.status === 'needs_conversion'
              ? t('dwg_compare.target_not_ready', {
                  defaultValue:
                    'The comparison drawing could not be prepared. Pick another drawing or upload again.',
                })
              : t('dwg_compare.target_preparing', {
                  defaultValue:
                    'Preparing the comparison drawing. The diff runs automatically once it is ready.',
                })}
          </p>
        )}

        {/* Controls row */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-y border-border-light py-2">
          <label className="inline-flex items-center gap-1.5 text-xs text-content-secondary cursor-pointer">
            <input
              type="checkbox"
              checked={hideUnchanged}
              onChange={(e) => setHideUnchanged(e.target.checked)}
              data-testid="dwg-compare-hide-unchanged"
              className="h-3.5 w-3.5 accent-oe-blue"
            />
            {t('dwg_compare.hide_unchanged', { defaultValue: 'Hide unchanged' })}
          </label>
          <label className="inline-flex items-center gap-1.5 text-xs text-content-secondary cursor-pointer">
            <input
              type="checkbox"
              checked={overlay}
              onChange={(e) => setOverlay(e.target.checked)}
              data-testid="dwg-compare-overlay"
              className="h-3.5 w-3.5 accent-oe-blue"
            />
            <Eye size={13} />
            {t('dwg_compare.overlay', { defaultValue: 'Onion-skin overlay' })}
          </label>
          {overlay && (
            <label className="inline-flex items-center gap-2 text-xs text-content-tertiary">
              {t('dwg_compare.opacity', { defaultValue: 'Opacity' })}
              <input
                type="range"
                min={0}
                max={100}
                value={Math.round(opacity * 100)}
                onChange={(e) => setOpacity(Number(e.target.value) / 100)}
                data-testid="dwg-compare-opacity"
                className="w-28 accent-oe-blue"
              />
              <span className="tabular-nums w-8 text-right">{Math.round(opacity * 100)}%</span>
            </label>
          )}
        </div>

        {/* Tabs */}
        <div className="flex items-center gap-1 rounded-lg bg-surface-secondary p-1">
          {tabs.map(({ id, label, icon: Icon, count }) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              data-testid={`dwg-compare-tab-${id}`}
              className={clsx(
                'flex flex-1 items-center justify-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium transition-colors',
                tab === id
                  ? 'bg-surface-elevated text-oe-blue shadow-sm'
                  : 'text-content-secondary hover:text-content-primary',
              )}
            >
              <Icon size={13} />
              <span className="truncate">{label}</span>
              {count > 0 && (
                <Badge variant="neutral" className="ml-0.5 text-[9px]">
                  {count}
                </Badge>
              )}
            </button>
          ))}
        </div>

        {/* Loading / error / empty states */}
        {((mode === 'version' && versionsQuery.isLoading) ||
          (canCompare && diffQuery.isLoading)) && (
          <div className="flex items-center justify-center gap-2 py-10 text-sm text-content-tertiary">
            <Loader2 size={16} className="animate-spin" />
            {t('dwg_compare.loading', { defaultValue: 'Computing diff…' })}
          </div>
        )}

        {canCompare && diffQuery.isError && (
          <p className="rounded-md border border-red-500/30 bg-red-500/5 px-3 py-2 text-xs text-red-500">
            {t('dwg_compare.error', {
              defaultValue: 'Could not compute the comparison. Please try again.',
            })}
          </p>
        )}

        {/* Body */}
        {diff && !diffQuery.isLoading && (
          <>
            {tab === 'summary' && (
              <SummaryTab
                diff={diff}
                canCreateVariation={hasChanges && canCompare}
                creating={createVariationMutation.isPending}
                onCreateVariation={() => createVariationMutation.mutate()}
              />
            )}
            {tab === 'entities' && <EntitiesTab rows={entityRows} hideUnchanged={hideUnchanged} />}
            {tab === 'annotations' && (
              <AnnotationsTab rows={annotationRows} hideUnchanged={hideUnchanged} />
            )}
          </>
        )}
      </div>
    </SideDrawer>
  );
}

/* ── Summary tab ───────────────────────────────────────────────────────── */

function SummaryTab({
  diff,
  canCreateVariation,
  creating,
  onCreateVariation,
}: {
  diff: DwgDrawingDiffResponse;
  canCreateVariation: boolean;
  creating: boolean;
  onCreateVariation: () => void;
}) {
  const { t } = useTranslation();
  const { summary } = diff;
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3">
        <SummaryCard
          title={t('dwg_compare.entities_heading', { defaultValue: 'Entities (by layer)' })}
          tally={summary.entities}
        />
        <SummaryCard
          title={t('dwg_compare.annotations_heading', { defaultValue: 'Annotations' })}
          tally={summary.annotations}
        />
      </div>

      <div className="rounded-lg border border-border-light p-3">
        <div className="text-[11px] font-medium text-content-tertiary mb-1">
          {t('dwg_compare.net_cost_impact', { defaultValue: 'Net cost impact' })}
        </div>
        {summary.net_cost_impact != null && summary.cost_currency ? (
          <MoneyDisplay
            amount={summary.net_cost_impact}
            currency={summary.cost_currency}
            colorize
            className="text-lg font-semibold"
          />
        ) : (
          <p className="text-xs text-content-tertiary">
            {t('dwg_compare.no_cost_impact', {
              defaultValue:
                'No cost impact - no linked BOQ annotation changed value between these revisions.',
            })}
          </p>
        )}

        {/* Create-variation-from-delta handoff (Item 17). Disabled when the
            two revisions are identical / there are no changes. Creates a
            DRAFT variation the user confirms in the variations module. */}
        <button
          type="button"
          onClick={onCreateVariation}
          disabled={!canCreateVariation || creating}
          data-testid="dwg-compare-create-variation"
          className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-md bg-oe-blue px-3 py-2 text-xs font-semibold text-white transition hover:bg-oe-blue/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {creating ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <FilePlus2 size={14} />
          )}
          {t('dwg_compare.create_variation', { defaultValue: 'Create variation from delta' })}
        </button>
        {!canCreateVariation && (
          <p className="mt-1 text-[10px] text-content-tertiary">
            {t('dwg_compare.create_variation_disabled', {
              defaultValue: 'Pick two revisions with at least one change to raise a variation.',
            })}
          </p>
        )}
      </div>

      <div className="flex items-center justify-between text-xs text-content-secondary">
        <span>
          {t('dwg_compare.entity_count_from', {
            defaultValue: 'Before: {{n}} entities',
            n: summary.from_entity_count,
          })}
        </span>
        <ArrowRight size={13} className="text-content-tertiary" />
        <span>
          {t('dwg_compare.entity_count_to', {
            defaultValue: 'After: {{n}} entities',
            n: summary.to_entity_count,
          })}
        </span>
      </div>
    </div>
  );
}

function SummaryCard({
  title,
  tally,
}: {
  title: string;
  tally: Record<'added' | 'removed' | 'modified' | 'unchanged', number>;
}) {
  const { t } = useTranslation();
  const rows: { key: 'added' | 'removed' | 'modified'; color: string; label: string }[] = [
    { key: 'added', color: 'text-emerald-500', label: t('dwg_compare.change_added', { defaultValue: 'Added' }) },
    { key: 'removed', color: 'text-red-500', label: t('dwg_compare.change_removed', { defaultValue: 'Removed' }) },
    { key: 'modified', color: 'text-amber-500', label: t('dwg_compare.change_modified', { defaultValue: 'Modified' }) },
  ];
  return (
    <div className="rounded-lg border border-border-light p-3">
      <div className="text-[11px] font-medium text-content-tertiary mb-2 truncate">{title}</div>
      <div className="flex flex-col gap-1">
        {rows.map(({ key, color, label }) => (
          <div key={key} className="flex items-center justify-between text-xs">
            <span className={color}>{label}</span>
            <span className="tabular-nums font-semibold text-content-primary">{tally[key] ?? 0}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── Entities tab ──────────────────────────────────────────────────────── */

function EntitiesTab({
  rows,
  hideUnchanged,
}: {
  rows: DwgEntityDiffRow[];
  hideUnchanged: boolean;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <p className="py-8 text-center text-xs text-content-tertiary">
        {hideUnchanged
          ? t('dwg_compare.no_entity_changes', { defaultValue: 'No entity changes between these revisions.' })
          : t('dwg_compare.no_entities', { defaultValue: 'No layers found.' })}
      </p>
    );
  }
  return (
    <div className="overflow-hidden rounded-lg border border-border-light">
      <table className="w-full text-xs">
        <thead className="bg-surface-secondary text-content-tertiary">
          <tr>
            <th className="px-3 py-2 text-left font-medium">{t('dwg_compare.col_layer', { defaultValue: 'Layer' })}</th>
            <th className="px-3 py-2 text-left font-medium">{t('dwg_compare.col_change', { defaultValue: 'Change' })}</th>
            <th className="px-3 py-2 text-right font-medium">{t('dwg_compare.col_before', { defaultValue: 'Before' })}</th>
            <th className="px-3 py-2 text-right font-medium">{t('dwg_compare.col_after', { defaultValue: 'After' })}</th>
            <th className="px-3 py-2 text-right font-medium">{t('dwg_compare.col_delta', { defaultValue: 'Δ' })}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.entity_id} className="border-t border-border-light">
              <td className="px-3 py-2 font-medium text-content-primary truncate max-w-[160px]" title={r.layer}>
                {r.layer}
              </td>
              <td className="px-3 py-2">
                <ChangeBadge type={r.change_type} />
              </td>
              <td className="px-3 py-2 text-right tabular-nums text-content-secondary">{r.old_count}</td>
              <td className="px-3 py-2 text-right tabular-nums text-content-secondary">{r.new_count}</td>
              <td
                className={clsx(
                  'px-3 py-2 text-right tabular-nums font-semibold',
                  r.delta > 0 ? 'text-emerald-500' : r.delta < 0 ? 'text-red-500' : 'text-content-tertiary',
                )}
              >
                {r.delta > 0 ? `+${r.delta}` : r.delta}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── Annotations tab ───────────────────────────────────────────────────── */

function AnnotationsTab({
  rows,
  hideUnchanged,
}: {
  rows: DwgAnnotationDiffRow[];
  hideUnchanged: boolean;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <p className="py-8 text-center text-xs text-content-tertiary">
        {hideUnchanged
          ? t('dwg_compare.no_annotation_changes', {
              defaultValue: 'No annotation changes between these revisions.',
            })
          : t('dwg_compare.no_annotations', { defaultValue: 'No annotations on either revision.' })}
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      {rows.map((r) => (
        <div
          key={r.annotation_id}
          className="rounded-lg border border-border-light p-3"
          data-testid="dwg-compare-annotation-row"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium capitalize text-content-primary truncate">
              {r.label || r.annotation_type.replace('_', ' ')}
            </span>
            <ChangeBadge type={r.change_type} />
          </div>
          <div className="mt-1.5 flex items-center gap-2 text-xs text-content-secondary">
            <span className="tabular-nums">
              {r.old_measurement != null ? fmtFixed(r.old_measurement, 2) : '—'}
            </span>
            <ArrowRight size={12} className="text-content-tertiary" />
            <span className="tabular-nums font-medium text-content-primary">
              {r.new_measurement != null ? fmtFixed(r.new_measurement, 2) : '—'}
            </span>
            {r.measurement_unit && <span className="text-content-tertiary">{r.measurement_unit}</span>}
          </div>
          {r.linked_boq_position_id && (
            <div className="mt-1.5 flex items-center justify-between gap-2">
              <span className="text-[10px] text-content-tertiary">
                {t('dwg_compare.linked_boq', { defaultValue: 'Linked to BOQ position' })}
              </span>
              {r.cost_impact != null && r.cost_currency ? (
                <MoneyDisplay
                  amount={r.cost_impact}
                  currency={r.cost_currency}
                  colorize
                  className="text-xs font-semibold"
                />
              ) : (
                <span className="text-[10px] text-content-tertiary">
                  {t('dwg_compare.no_value_change', { defaultValue: 'No value change' })}
                </span>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
