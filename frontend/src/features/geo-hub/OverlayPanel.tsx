// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Raster overlay panel — floating chrome over the Cesium canvas.
 *
 * Lists the project's raster overlays (PDF pages / images / DWG
 * top-views), lets the user toggle visibility, drag-edit corners,
 * draw a crop polygon, and add new ones via upload modal.
 *
 * Persistence:
 * * Collapsed state lives in localStorage so the user's preferred
 *   chrome density survives reloads (same pattern as the existing
 *   AnchoredProjectsOverlay rail).
 * * All mutations go through React Query so refetches stay coherent
 *   with whatever else is reading the same list (e.g. OverlayLayer).
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ChevronLeft,
  ChevronRight,
  Crop,
  Eye,
  EyeOff,
  Image as ImageIcon,
  Layers,
  Loader2,
  Move,
  Plus,
  Trash2,
  Upload,
} from 'lucide-react';

import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { WideModal } from '@/shared/ui/WideModal';
import { Button } from '@/shared/ui';

import {
  deleteRasterOverlay,
  listRasterOverlays,
  updateRasterOverlay,
  uploadImageRasterOverlay,
  uploadPdfRasterOverlay,
} from './api';
// Reuse the validator from OverlayLayer so the panel + layer agree on
// what "degenerate" means — single source of truth.
import { isOverlayDegenerate } from './OverlayLayer';

const PANEL_COLLAPSED_LS_KEY = 'oe.geo_hub.overlay_panel_collapsed.v1';

function readPanelCollapsed(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem(PANEL_COLLAPSED_LS_KEY) === '1';
  } catch {
    return false;
  }
}

/** Editing mode for one overlay — surfaced to the OverlayLayer via prop. */
export type OverlayEditMode = 'idle' | 'corners' | 'crop';

interface OverlayPanelProps {
  projectId: string;
  /** Currently active overlay (the one whose corners/crop are editable). */
  activeOverlayId: string | null;
  editMode: OverlayEditMode;
  onSelectOverlay: (id: string | null) => void;
  onChangeEditMode: (mode: OverlayEditMode) => void;
}

export function OverlayPanel({
  projectId,
  activeOverlayId,
  editMode,
  onSelectOverlay,
  onChangeEditMode,
}: OverlayPanelProps) {
  const { t } = useTranslation();
  const [collapsed, setCollapsed] = useState<boolean>(readPanelCollapsed);
  const [showUpload, setShowUpload] = useState(false);
  const { confirm, ...confirmProps } = useConfirm();
  useEffect(() => {
    if (typeof window === 'undefined') return;
    try {
      window.localStorage.setItem(
        PANEL_COLLAPSED_LS_KEY,
        collapsed ? '1' : '0',
      );
    } catch {
      /* localStorage disabled — UX still works in-memory */
    }
  }, [collapsed]);

  const queryClient = useQueryClient();
  const overlaysQuery = useQuery({
    queryKey: ['geo-hub', 'raster-overlays', projectId],
    queryFn: () => listRasterOverlays(projectId, { includeHidden: true }),
    enabled: Boolean(projectId),
    staleTime: 15_000,
  });

  const invalidate = useCallback(() => {
    queryClient.invalidateQueries({
      queryKey: ['geo-hub', 'raster-overlays', projectId],
    });
  }, [projectId, queryClient]);

  const overlays = overlaysQuery.data ?? [];

  const patchMutation = useMutation({
    mutationFn: ({
      id,
      body,
    }: {
      id: string;
      body: Parameters<typeof updateRasterOverlay>[1];
    }) => updateRasterOverlay(id, body),
    onSuccess: () => invalidate(),
    onError: (err) => {
      useToastStore.getState().addToast({
        type: 'error',
        title: t('geo.overlays.toast_patch_failed', {
          defaultValue: 'Could not save overlay change',
        }),
        message: getErrorMessage(err),
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteRasterOverlay(id),
    onSuccess: () => invalidate(),
    onError: (err) => {
      useToastStore.getState().addToast({
        type: 'error',
        title: t('geo.overlays.toast_delete_failed', {
          defaultValue: 'Could not delete overlay',
        }),
        message: getErrorMessage(err),
      });
    },
  });

  if (collapsed) {
    return (
      <button
        type="button"
        onClick={() => setCollapsed(false)}
        className={[
          'absolute top-3 right-3 z-20 inline-flex items-center gap-2',
          'rounded-full border border-white/15 bg-slate-900/85 px-3 py-1.5',
          'text-xs font-medium text-white shadow-lg shadow-black/20 backdrop-blur-md',
          'ring-1 ring-white/5 transition hover:bg-slate-800/90',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400',
        ].join(' ')}
        aria-expanded={false}
        aria-label={t('geo.overlays.expand', { defaultValue: 'Show overlays' })}
      >
        <Layers size={13} strokeWidth={2} className="text-sky-300" />
        <span className="tabular-nums">{overlays.length}</span>
        <ChevronLeft size={13} strokeWidth={2.25} className="text-white/70" />
      </button>
    );
  }

  return (
    <aside
      data-testid="geo-overlay-panel"
      className={[
        'absolute top-3 right-3 z-20 flex w-80 max-w-[calc(100vw-1.5rem)] flex-col',
        'rounded-xl border border-white/15 bg-white/95 dark:bg-slate-900/90',
        'shadow-lg shadow-black/20 ring-1 ring-black/5 backdrop-blur-md',
        'hidden md:flex',
      ].join(' ')}
      aria-label={t('geo.overlays.aria', {
        defaultValue: 'Raster overlays',
      })}
    >
      <div className="flex items-center justify-between gap-2 border-b border-black/5 px-3 py-2.5 dark:border-white/10">
        <div className="min-w-0">
          <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-content-secondary">
            {t('geo.overlays.title', { defaultValue: 'Overlays' })}
          </h2>
          <p className="mt-0.5 text-2xs text-content-tertiary">
            {overlaysQuery.isLoading
              ? t('geo.overlays.counter_loading', { defaultValue: 'Loading…' })
              : t('geo.overlays.counter', {
                  defaultValue: '{{count}} pinned to globe',
                  count: overlays.length,
                })}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={() => setShowUpload(true)}
            data-testid="geo-overlay-add-button"
            className={[
              'inline-flex items-center gap-1 rounded-md border border-border px-2 py-1',
              'text-2xs font-medium text-content-secondary',
              'hover:bg-surface-secondary hover:text-content-primary',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
            ].join(' ')}
          >
            <Plus size={12} strokeWidth={2.25} />
            {t('geo.overlays.add', { defaultValue: 'Add' })}
          </button>
          <button
            type="button"
            onClick={() => setCollapsed(true)}
            className={[
              'inline-flex h-7 w-7 items-center justify-center rounded-md',
              'text-content-tertiary hover:bg-surface-secondary hover:text-content-primary',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
            ].join(' ')}
            aria-expanded
            aria-label={t('geo.overlays.collapse', {
              defaultValue: 'Hide overlays',
            })}
          >
            <ChevronRight size={14} strokeWidth={2} />
          </button>
        </div>
      </div>

      <div className="max-h-[60vh] overflow-y-auto">
        {overlaysQuery.isLoading && (
          <div className="flex items-center justify-center gap-2 px-4 py-6 text-2xs text-content-tertiary">
            <Loader2 size={14} className="animate-spin" />
            <span>
              {t('geo.overlays.loading', {
                defaultValue: 'Loading overlays…',
              })}
            </span>
          </div>
        )}
        {!overlaysQuery.isLoading && overlays.length === 0 && (
          <div
            data-testid="geo-overlay-empty"
            className="px-4 py-6 text-center text-2xs text-content-tertiary"
          >
            <p className="mb-2">
              {t('geo.overlays.empty', {
                defaultValue:
                  'No overlays yet. Click Add to pin a PDF or image to the globe.',
              })}
            </p>
            <button
              type="button"
              onClick={() => setShowUpload(true)}
              className="inline-flex items-center gap-1 rounded-md border border-oe-blue/50 px-2 py-1 text-2xs font-medium text-oe-blue hover:bg-oe-blue/10 focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
            >
              <Plus size={11} aria-hidden />
              {t('geo.overlays.empty_cta', {
                defaultValue: 'Add your first overlay',
              })}
            </button>
          </div>
        )}
        {overlays.length > 0 && (
          <ul className="m-2 space-y-1">
            {overlays.map((o) => {
              const isActive = activeOverlayId === o.id;
              const degenerate = isOverlayDegenerate(o);
              return (
                <li
                  key={o.id}
                  data-testid="geo-overlay-row"
                  data-overlay-id={o.id}
                  data-overlay-degenerate={degenerate ? 'true' : 'false'}
                  className={[
                    'rounded-md border px-2 py-2 transition-colors',
                    isActive
                      ? 'border-sky-400/60 bg-sky-50 dark:bg-sky-950/30'
                      : 'border-transparent hover:border-border hover:bg-surface-secondary',
                  ].join(' ')}
                >
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        patchMutation.mutate({
                          id: o.id,
                          body: { visible: !o.visible },
                        })
                      }
                      data-testid="geo-overlay-toggle-visible"
                      aria-pressed={o.visible}
                      aria-label={
                        o.visible
                          ? t('geo.overlays.hide_overlay_aria', {
                              defaultValue: 'Hide overlay {{name}}',
                              name: o.name || 'untitled',
                            })
                          : t('geo.overlays.show_overlay_aria', {
                              defaultValue: 'Show overlay {{name}}',
                              name: o.name || 'untitled',
                            })
                      }
                      title={
                        o.visible
                          ? t('geo.overlays.hide', { defaultValue: 'Hide' })
                          : t('geo.overlays.show', { defaultValue: 'Show' })
                      }
                      className={[
                        'inline-flex h-7 w-7 items-center justify-center rounded-md',
                        o.visible
                          ? 'text-sky-600 hover:bg-sky-100 dark:text-sky-300 dark:hover:bg-sky-950/50'
                          : 'text-content-tertiary hover:bg-surface-secondary',
                        'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
                      ].join(' ')}
                    >
                      {o.visible ? <Eye size={13} aria-hidden /> : <EyeOff size={13} aria-hidden />}
                    </button>
                    <button
                      type="button"
                      onClick={() => onSelectOverlay(isActive ? null : o.id)}
                      className="min-w-0 flex-1 truncate text-left text-xs font-medium text-content-primary hover:text-oe-blue focus:outline-none focus-visible:underline"
                      title={o.name}
                    >
                      {o.name || t('geo.overlays.untitled', {
                        defaultValue: 'Untitled overlay',
                      })}
                    </button>
                    <span
                      className="rounded bg-surface-tertiary px-1.5 py-0.5 text-2xs uppercase tracking-wide text-content-tertiary"
                      title={o.source_kind}
                    >
                      {o.source_kind}
                    </span>
                  </div>
                  <div className="ml-9 mt-1.5 flex items-center gap-2 text-2xs text-content-tertiary">
                    <label className="flex flex-1 items-center gap-1">
                      <span className="sr-only">
                        {t('geo.overlays.opacity', {
                          defaultValue: 'Opacity',
                        })}
                      </span>
                      <input
                        type="range"
                        min={0}
                        max={1}
                        step={0.05}
                        value={Number(o.opacity)}
                        onChange={(e) =>
                          patchMutation.mutate({
                            id: o.id,
                            body: { opacity: e.target.value },
                          })
                        }
                        data-testid="geo-overlay-opacity-slider"
                        className="flex-1 accent-sky-500"
                        aria-label={t('geo.overlays.opacity', {
                          defaultValue: 'Opacity',
                        })}
                      />
                      <span className="w-7 text-right tabular-nums">
                        {Math.round(Number(o.opacity) * 100)}%
                      </span>
                    </label>
                  </div>
                  {degenerate && (
                    <div
                      className="ml-9 mt-1.5 flex flex-wrap items-center gap-1.5"
                      data-testid="geo-overlay-needs-corners"
                    >
                      <span
                        className="inline-flex items-center gap-1 rounded-full border border-amber-300/70 bg-amber-50 px-1.5 py-0.5 text-2xs font-medium text-amber-800 dark:border-amber-400/40 dark:bg-amber-950/30 dark:text-amber-200"
                        role="status"
                        title={t('geo.overlays.needs_corners_hint', {
                          defaultValue:
                            'Overlay has no valid corners - showing fallback square at project anchor.',
                        })}
                      >
                        {t('geo.overlays.needs_corners', {
                          defaultValue: 'Needs corners',
                        })}
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          onSelectOverlay(o.id);
                          onChangeEditMode('corners');
                        }}
                        data-testid="geo-overlay-fix-corners-cta"
                        className="inline-flex items-center gap-1 rounded-md border border-amber-300/70 px-1.5 py-0.5 text-2xs font-medium text-amber-800 hover:bg-amber-100 dark:border-amber-400/40 dark:text-amber-200 dark:hover:bg-amber-950/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-amber-400"
                      >
                        {t('geo.overlays.edit_corners', {
                          defaultValue: 'Edit corners',
                        })}
                      </button>
                    </div>
                  )}
                  {isActive && (
                    <div className="ml-9 mt-1.5 flex flex-wrap items-center gap-1">
                      <button
                        type="button"
                        onClick={() =>
                          onChangeEditMode(
                            editMode === 'corners' ? 'idle' : 'corners',
                          )
                        }
                        data-testid="geo-overlay-edit-corners"
                        aria-pressed={editMode === 'corners'}
                        className={[
                          'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-2xs font-medium',
                          editMode === 'corners'
                            ? 'border-sky-400 bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-200'
                            : 'border-border text-content-secondary hover:bg-surface-secondary',
                          'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
                        ].join(' ')}
                      >
                        <Move size={11} />
                        {t('geo.overlays.edit_corners', {
                          defaultValue: 'Edit corners',
                        })}
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          onChangeEditMode(
                            editMode === 'crop' ? 'idle' : 'crop',
                          )
                        }
                        data-testid="geo-overlay-crop"
                        aria-pressed={editMode === 'crop'}
                        className={[
                          'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-2xs font-medium',
                          editMode === 'crop'
                            ? 'border-amber-400 bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-200'
                            : 'border-border text-content-secondary hover:bg-surface-secondary',
                          'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
                        ].join(' ')}
                      >
                        <Crop size={11} />
                        {t('geo.overlays.crop', { defaultValue: 'Crop' })}
                      </button>
                      <button
                        type="button"
                        onClick={async () => {
                          const ok = await confirm({
                            title: t('geo.overlays.delete_title', {
                              defaultValue: 'Delete overlay?',
                            }),
                            message: t('geo.overlays.delete_confirm', {
                              defaultValue:
                                'Delete this overlay? You can re-upload it later.',
                            }),
                            confirmLabel: t('common.delete', { defaultValue: 'Delete' }),
                            variant: 'danger',
                          });
                          if (!ok) return;
                          deleteMutation.mutate(o.id);
                          if (activeOverlayId === o.id) {
                            onSelectOverlay(null);
                            onChangeEditMode('idle');
                          }
                        }}
                        data-testid="geo-overlay-delete"
                        className="inline-flex items-center gap-1 rounded-md border border-red-300/50 px-1.5 py-0.5 text-2xs font-medium text-red-700 hover:bg-red-50 dark:border-red-400/40 dark:text-red-300 dark:hover:bg-red-950/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-400"
                      >
                        <Trash2 size={11} />
                        {t('common.delete', { defaultValue: 'Delete' })}
                      </button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {showUpload && (
        <OverlayUploadModal
          projectId={projectId}
          onClose={() => setShowUpload(false)}
          onUploaded={() => {
            setShowUpload(false);
            invalidate();
          }}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </aside>
  );
}

interface OverlayUploadModalProps {
  projectId: string;
  onClose: () => void;
  onUploaded: () => void;
}

function OverlayUploadModal({
  projectId,
  onClose,
  onUploaded,
}: OverlayUploadModalProps) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<'pdf' | 'image'>('pdf');
  const pdfInputRef = useRef<HTMLInputElement>(null);
  const imgInputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  const handleUpload = useCallback(
    async (file: File) => {
      setBusy(true);
      try {
        if (tab === 'pdf') {
          await uploadPdfRasterOverlay(projectId, file);
        } else {
          await uploadImageRasterOverlay(projectId, file);
        }
        useToastStore.getState().addToast({
          type: 'success',
          title: t('geo.overlays.toast_uploaded', {
            defaultValue: 'Overlay added to the globe',
          }),
        });
        onUploaded();
      } catch (err) {
        useToastStore.getState().addToast({
          type: 'error',
          title: t('geo.overlays.toast_upload_failed', {
            defaultValue: 'Upload failed',
          }),
          message: getErrorMessage(err),
        });
      } finally {
        setBusy(false);
      }
    },
    [onUploaded, projectId, t, tab],
  );

  return (
    <WideModal
      open
      onClose={onClose}
      title={t('geo.overlays.upload_title', {
        defaultValue: 'Add overlay to globe',
      })}
      size="md"
      busy={busy}
      footer={
        <Button variant="ghost" onClick={onClose} disabled={busy}>
          {t('common.cancel', { defaultValue: 'Cancel' })}
        </Button>
      }
    >
      <div data-testid="geo-overlay-upload-modal">
        <div className="mb-4 flex gap-1 rounded-md bg-surface-secondary p-1">
          {(['pdf', 'image'] as const).map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => setTab(k)}
              data-testid={`geo-overlay-tab-${k}`}
              className={[
                'flex-1 rounded px-3 py-1.5 text-xs font-medium transition',
                tab === k
                  ? 'bg-white text-slate-900 shadow-sm dark:bg-slate-700 dark:text-slate-100'
                  : 'text-content-secondary hover:text-content-primary',
              ].join(' ')}
            >
              {k === 'pdf'
                ? t('geo.overlays.tab_pdf', { defaultValue: 'PDF page' })
                : t('geo.overlays.tab_image', { defaultValue: 'Image' })}
            </button>
          ))}
        </div>

        {tab === 'pdf' ? (
          <div className="space-y-3">
            <p className="text-xs text-content-secondary">
              {t('geo.overlays.pdf_hint', {
                defaultValue:
                  'Upload a PDF. The first page will be rasterised and pinned to your project location.',
              })}
            </p>
            <input
              ref={pdfInputRef}
              type="file"
              accept="application/pdf,.pdf"
              data-testid="geo-overlay-pdf-input"
              className="block w-full text-sm"
              disabled={busy}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleUpload(f);
              }}
            />
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-content-secondary">
              {t('geo.overlays.image_hint', {
                defaultValue:
                  'Upload a PNG or JPEG site image. Drag corners on the globe to fit.',
              })}
            </p>
            <input
              ref={imgInputRef}
              type="file"
              accept="image/png,image/jpeg,.png,.jpg,.jpeg"
              data-testid="geo-overlay-image-input"
              className="block w-full text-sm"
              disabled={busy}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleUpload(f);
              }}
            />
          </div>
        )}

        {busy && (
          <div className="mt-3 flex items-center gap-2 text-xs text-content-secondary">
            <Loader2 size={13} className="animate-spin" />
            <span>
              {t('geo.overlays.uploading', { defaultValue: 'Uploading…' })}
            </span>
          </div>
        )}
        <div className="mt-3 flex items-center gap-2 text-2xs text-content-tertiary">
          {tab === 'pdf' ? (
            <Upload size={11} aria-hidden />
          ) : (
            <ImageIcon size={11} aria-hidden />
          )}
          <span>
            {t('geo.overlays.max_hint', {
              defaultValue: 'Max 25 MB; magic-byte validated server-side.',
            })}
          </span>
        </div>
      </div>
    </WideModal>
  );
}

export default OverlayPanel;
