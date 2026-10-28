// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Plan Room page.
 *
 * Opens one drawing sheet and shows every mark the platform holds for that
 * page - punch pins, plan pins, drawing markups, takeoff measurements and
 * project photos - in a single view with a per-source layer toggle. Write
 * users can drop their own plan pins straight onto the sheet.
 *
 * The page owns: which document / page is open, the layer visibility, the
 * revision indicator and the optimistic pin create / delete. The heavy pdf.js
 * rendering and the on-sheet marks live in {@link PlanRoomViewer}.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Camera,
  ChevronDown,
  ChevronRight,
  ClipboardCheck,
  FileWarning,
  FolderOpen,
  GitBranch,
  Layers as LayersIcon,
  Lock,
  Map as MapIcon,
  Upload,
} from 'lucide-react';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { Badge, EmptyState, Skeleton } from '@/shared/ui';
import { CollapsibleSection } from '@/shared/ui/CollapsibleSection';
import { PageHeader } from '@/shared/ui/PageHeader';
import { Breadcrumb } from '@/shared/ui/Breadcrumb';
import { useAuthStore } from '@/stores/useAuthStore';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  createPlanPin,
  deletePlanPin,
  fetchOverlays,
  fetchPlanRoomDrawings,
  type OverlayPhoto,
  type OverlayPin,
  type OverlaysResponse,
  type OverlayVersion,
} from './api';
import { allLayersVisible, type LayerKey } from './layers';
import { LayerPanel } from './LayerPanel';
import { PlanRoomViewer } from './PlanRoomViewer';
import { SheetCompletenessPanel } from './SheetCompletenessPanel';
import { getIntlLocale } from '@/shared/lib/formatters';

/** Roles that satisfy ``plan_room.write`` (EDITOR and above, plus the role
 *  aliases the backend permission registry maps). Used only to decide whether
 *  to OFFER the pin controls - the POST / DELETE are still authoritatively
 *  gated server-side. Mirrors the coordination hub's WRITE_ROLES set. */
const WRITE_ROLES = new Set([
  'admin',
  'manager',
  'editor',
  'estimator',
  'quantity_surveyor',
  'qs',
  'user',
  'superuser',
  'owner',
]);

interface Project {
  id: string;
  name: string;
}

interface PlanRoomPageProps {
  /** Open a specific document straight away (integrator deep-link). Falls back
   *  to the `?doc=` search param, then the first project drawing. */
  documentId?: string;
  /** 1-based initial page (falls back to `?page=`, then 1). */
  initialPage?: number;
}

export function PlanRoomPage({ documentId: documentIdProp, initialPage }: PlanRoomPageProps = {}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);
  const userRole = useAuthStore((s) => s.userRole);
  const canWrite = !!userRole && WRITE_ROLES.has(userRole.toLowerCase());

  /* ── Project + drawings ────────────────────────────────────────────── */
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
    staleTime: 5 * 60_000,
  });
  // No silent fallback to the first project: opening someone else's drawings
  // because no project was picked reads as a wrong page. The empty state below
  // sends the reader to the project list instead.
  const projectId = activeProjectId || '';
  const projectName =
    activeProjectName || projects.find((p) => p.id === projectId)?.name || '';

  const drawingsQuery = useQuery({
    queryKey: ['plan-room-drawings', projectId],
    queryFn: () => fetchPlanRoomDrawings(projectId),
    enabled: !!projectId,
    staleTime: 60_000,
  });
  const drawings = useMemo(() => drawingsQuery.data ?? [], [drawingsQuery.data]);
  const drawingsLoading = !!projectId && drawingsQuery.isLoading;
  const noDrawings = !!projectId && drawingsQuery.isSuccess && drawings.length === 0;

  /* ── Selected document + page ──────────────────────────────────────── */
  const [selectedDocId, setSelectedDocId] = useState(
    documentIdProp ?? searchParams.get('doc') ?? searchParams.get('openDoc') ?? '',
  );
  const [page, setPage] = useState(() => {
    const raw = initialPage ?? Number(searchParams.get('page'));
    return Number.isFinite(raw) && raw > 0 ? Math.floor(raw) : 1;
  });

  // Default to the first drawing once the list loads, but never fight an
  // explicit prop / search-param / user selection.
  useEffect(() => {
    if (!selectedDocId && drawings[0]) setSelectedDocId(drawings[0].id);
  }, [drawings, selectedDocId]);

  /* ── Overlay composite ─────────────────────────────────────────────── */
  const overlaysKey = ['plan-room-overlays', selectedDocId, page] as const;
  const overlaysQuery = useQuery({
    queryKey: overlaysKey,
    queryFn: () => fetchOverlays(selectedDocId, page),
    enabled: !!selectedDocId,
  });
  const overlays = overlaysQuery.data;

  /* ── Layer visibility ──────────────────────────────────────────────── */
  const [visibility, setVisibility] = useState<Record<LayerKey, boolean>>(allLayersVisible);
  const toggleLayer = (key: LayerKey) =>
    setVisibility((prev) => ({ ...prev, [key]: !prev[key] }));

  const counts = useMemo(() => {
    const pins = overlays?.pins ?? [];
    return {
      punch: pins.filter((p) => p.kind === 'punch').length,
      plan: pins.filter((p) => p.kind === 'plan').length,
      markups: overlays?.markups?.length ?? 0,
      measurements: overlays?.measurements?.length ?? 0,
      photos: overlays?.photos?.length ?? 0,
    } satisfies Record<LayerKey, number>;
  }, [overlays]);

  const totalOverlays =
    counts.punch + counts.plan + counts.markups + counts.measurements + counts.photos;

  /* ── Sheet completeness disclosure (closed until asked for) ─────────── */
  const [completenessOpen, setCompletenessOpen] = useState(false);

  /* ── Drop-pin mode + mutations ─────────────────────────────────────── */
  const [placing, setPlacing] = useState(false);

  const createMut = useMutation({
    mutationFn: (vars: { x: number; y: number; note: string }) =>
      createPlanPin(selectedDocId, page, {
        page,
        x: vars.x,
        y: vars.y,
        note: vars.note || null,
      }),
    onMutate: async (vars) => {
      await qc.cancelQueries({ queryKey: overlaysKey });
      const prev = qc.getQueryData<OverlaysResponse>(overlaysKey);
      if (prev) {
        const optimistic: OverlayPin = {
          kind: 'plan',
          id: `temp-${Date.now()}`,
          x: vars.x,
          y: vars.y,
          title: null,
          note: vars.note || null,
          status: null,
          priority: null,
          assigned_to: null,
          photo_ref: null,
          file_version_id: null,
        };
        qc.setQueryData<OverlaysResponse>(overlaysKey, {
          ...prev,
          pins: [...prev.pins, optimistic],
        });
      }
      return { prev };
    },
    onError: (err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(overlaysKey, ctx.prev);
      addToast({
        type: 'error',
        title: t('plan_room.pin_failed', { defaultValue: 'Could not drop the pin' }),
        message: getErrorMessage(err),
      });
    },
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('plan_room.pin_placed', { defaultValue: 'Pin placed on the drawing' }),
      }),
    onSettled: () => qc.invalidateQueries({ queryKey: overlaysKey }),
  });

  const deleteMut = useMutation({
    mutationFn: (pinId: string) => deletePlanPin(pinId),
    onMutate: async (pinId) => {
      await qc.cancelQueries({ queryKey: overlaysKey });
      const prev = qc.getQueryData<OverlaysResponse>(overlaysKey);
      if (prev) {
        qc.setQueryData<OverlaysResponse>(overlaysKey, {
          ...prev,
          pins: prev.pins.filter((p) => p.id !== pinId),
        });
      }
      return { prev };
    },
    onError: (err, _pinId, ctx) => {
      if (ctx?.prev) qc.setQueryData(overlaysKey, ctx.prev);
      addToast({
        type: 'error',
        title: t('plan_room.pin_delete_failed', { defaultValue: 'Could not remove the pin' }),
        message: getErrorMessage(err),
      });
    },
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('plan_room.pin_deleted', { defaultValue: 'Pin removed' }),
      }),
    onSettled: () => qc.invalidateQueries({ queryKey: overlaysKey }),
  });

  const handleDeletePin = (pin: OverlayPin) => {
    // Only plan pins are owned here; the viewer never offers delete on a punch
    // pin. Guard anyway so a stray call can't hit the wrong endpoint.
    if (pin.kind !== 'plan') return;
    deleteMut.mutate(pin.id);
  };

  /* ── Render ────────────────────────────────────────────────────────── */
  const forbidden = overlaysQuery.error instanceof ApiError && overlaysQuery.error.status === 403;

  // The three steps are what a first-time reader needs, so they stay open while
  // the project has no drawings and start folded once there is a sheet to look
  // at. Mounted only after the drawings list settles, because the collapsed
  // default is read once on mount.
  const stepsReady = !projectId || drawingsQuery.isSuccess || drawingsQuery.isError;

  return (
    <div className="animate-fade-in space-y-5">
      <Breadcrumb
        items={[
          ...(projectId && projectName ? [{ label: projectName, to: `/projects/${projectId}` }] : []),
          { label: t('plan_room.title', { defaultValue: 'Plan Room' }) },
        ]}
      />

      <PageHeader
        srTitle={t('plan_room.title', { defaultValue: 'Plan Room' })}
        subtitle={t('plan_room.page_subtitle', {
          defaultValue:
            'Open a drawing and see what is marked on it: punch items, markups, measurements and photos.',
        })}
      />

      {stepsReady && (
        <CollapsibleSection
          storageKey="plan_room.steps"
          defaultCollapsed={drawings.length > 0}
          icon={<MapIcon size={15} className="text-oe-blue" />}
          title={t('plan_room.steps_title', { defaultValue: 'How it works' })}
        >
          <ol className="list-decimal space-y-1 pl-5 text-sm text-content-secondary">
            <li>{t('plan_room.step_1', { defaultValue: 'Open a drawing from the list.' })}</li>
            <li>
              {t('plan_room.step_2', {
                defaultValue:
                  'Switch layers on and off to see punch items, markups, measurements and photos on it.',
              })}
            </li>
            <li>
              {t('plan_room.step_3', {
                defaultValue: 'Drop a pin to leave a note at a spot on the drawing.',
              })}
            </li>
          </ol>
        </CollapsibleSection>
      )}

      {/* Drawing picker + revision indicator. Hidden while there is nothing to
          pick, so an empty dropdown never stands in for the way forward. */}
      {drawingsLoading ? (
        <Skeleton className="h-9 w-full max-w-md" />
      ) : drawings.length > 0 ? (
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <MapIcon size={16} className="shrink-0 text-content-tertiary" />
            <select
              value={selectedDocId}
              onChange={(e) => {
                setSelectedDocId(e.target.value);
                setPage(1);
                setPlacing(false);
              }}
              aria-label={t('plan_room.select_drawing', { defaultValue: 'Select drawing' })}
              className="h-9 max-w-md flex-1 rounded-lg border border-border bg-surface-primary px-2 text-sm focus:border-oe-blue focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
            >
              {drawings.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.filename || d.id.slice(0, 8)}
                </option>
              ))}
            </select>
          </div>
          {overlays?.version && <RevisionIndicator version={overlays.version} />}
        </div>
      ) : null}

      {/* Body */}
      {!projectId && !selectedDocId ? (
        <EmptyState
          icon={<FolderOpen size={24} />}
          title={t('plan_room.no_project_title', { defaultValue: 'Pick a project first' })}
          description={t('plan_room.no_project_desc', {
            defaultValue: 'Select an active project to open its drawings in the Plan Room.',
          })}
          action={{
            label: t('plan_room.go_projects', { defaultValue: 'Go to projects' }),
            onClick: () => navigate('/projects'),
          }}
        />
      ) : drawingsLoading && !selectedDocId ? (
        <Skeleton className="h-96 w-full" />
      ) : noDrawings && !selectedDocId ? (
        <EmptyState
          icon={<Upload size={24} />}
          title={t('plan_room.no_drawings_title', { defaultValue: 'No drawings in this project yet' })}
          description={t('plan_room.no_drawings_desc', {
            defaultValue: 'Upload PDF drawings in Documents. They show up here, ready to open and mark.',
          })}
          action={{
            label: t('plan_room.upload_drawings', { defaultValue: 'Upload drawings' }),
            onClick: () => navigate('/files'),
          }}
        />
      ) : forbidden ? (
        <EmptyState
          icon={<Lock size={24} />}
          title={t('plan_room.forbidden_title', { defaultValue: 'No access to this drawing' })}
          description={t('plan_room.forbidden_drawings_desc', {
            defaultValue: 'You do not have permission to see the drawings of this project.',
          })}
        />
      ) : overlaysQuery.isError ? (
        <EmptyState
          icon={<FileWarning size={24} />}
          title={t('plan_room.error_marks_title', { defaultValue: 'Could not load the marks on this drawing' })}
          description={getErrorMessage(overlaysQuery.error)}
          action={{
            label: t('common.retry', { defaultValue: 'Retry' }),
            onClick: () => overlaysQuery.refetch(),
          }}
        />
      ) : !selectedDocId ? (
        <EmptyState
          icon={<MapIcon size={24} />}
          title={t('plan_room.pick_drawing_title', { defaultValue: 'Select a drawing' })}
          description={t('plan_room.pick_drawing_desc', {
            defaultValue: 'Choose a drawing above to see its pins, markups, measurements and photos.',
          })}
        />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_300px]">
            {/* The sheet with its marks */}
            <PlanRoomViewer
              documentId={selectedDocId}
              page={page}
              onPageChange={(p) => {
                setPage(p);
                setPlacing(false);
              }}
              overlays={overlays}
              visibility={visibility}
              canWrite={canWrite}
              placing={placing}
              onStartPlacing={() => setPlacing(true)}
              onCancelPlacing={() => setPlacing(false)}
              onCreatePin={(x, y, note) => createMut.mutate({ x, y, note })}
              onDeletePin={handleDeletePin}
              isSaving={createMut.isPending}
            />

            {/* Side panel: layers + photos */}
            <div className="space-y-4">
              <LayerPanel visibility={visibility} counts={counts} onToggle={toggleLayer} />

              {/* Nothing on this page yet (the sheet still renders). */}
              {overlaysQuery.isSuccess && totalOverlays === 0 && (
                <div className="flex items-center gap-2 rounded-xl border border-dashed border-border bg-surface-primary px-3 py-4 text-sm text-content-tertiary">
                  <LayersIcon size={15} className="shrink-0" />
                  {t('plan_room.nothing_marked', { defaultValue: 'Nothing marked on this page yet.' })}
                </div>
              )}

              {/* Photos layer (document-level, so shown as a gallery not on the sheet). */}
              {visibility.photos && (overlays?.photos?.length ?? 0) > 0 && (
                <PhotoGallery photos={overlays!.photos} />
              )}
            </div>
          </div>

          {/* Sheet completeness: a set-level check, so it lives below the
              sheet in its own section and stays closed until asked for. */}
          {projectId && (
            <section className="rounded-xl border border-border-light bg-surface-primary">
              <button
                type="button"
                onClick={() => setCompletenessOpen((v) => !v)}
                aria-expanded={completenessOpen}
                className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-surface-secondary/40"
              >
                <ClipboardCheck size={16} className="shrink-0 text-content-tertiary" />
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className="text-sm font-semibold text-content-primary">
                    {t('plan_room.completeness_title', { defaultValue: 'Is the drawing set complete?' })}
                  </span>
                  <span className="text-xs text-content-tertiary">
                    {t('plan_room.completeness_desc', {
                      defaultValue:
                        'Compare your drawing list with the uploaded drawings to find missing or outdated sheets.',
                    })}
                  </span>
                </span>
                {completenessOpen ? (
                  <ChevronDown size={16} className="shrink-0 text-content-tertiary" aria-hidden />
                ) : (
                  <ChevronRight size={16} className="shrink-0 text-content-tertiary" aria-hidden />
                )}
              </button>
              {completenessOpen && (
                <div className="border-t border-border-light p-4">
                  <SheetCompletenessPanel projectId={projectId} defaultIndexDocumentId={selectedDocId} embedded />
                </div>
              )}
            </section>
          )}
        </>
      )}
    </div>
  );
}

/* ── Revision indicator ──────────────────────────────────────────────────── */

/**
 * Which drawing revision the marks were placed against. The Plan Room
 * backend exposes only the document's current revision (there is no
 * revision-list endpoint yet), so we surface it clearly rather than offering a
 * switcher - switching between revisions is a documented follow-on.
 */
function RevisionIndicator({ version }: { version: OverlayVersion }) {
  const { t } = useTranslation();
  if (!version.revision_code) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs text-content-quaternary">
        <GitBranch size={13} />
        {t('plan_room.revision_none', { defaultValue: 'No revision number' })}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      <GitBranch size={13} className="text-content-tertiary" />
      <span className="text-xs text-content-secondary">
        {t('plan_room.revision', { defaultValue: 'Rev {{code}}', code: version.revision_code })}
      </span>
      {version.is_current_revision ? (
        <Badge variant="success" size="sm">
          {t('plan_room.revision_current', { defaultValue: 'Current' })}
        </Badge>
      ) : (
        <Badge variant="warning" size="sm">
          {t('plan_room.revision_superseded', { defaultValue: 'Superseded' })}
        </Badge>
      )}
    </span>
  );
}

/* ── Photo gallery ───────────────────────────────────────────────────────── */

/**
 * Photos attached to the document. They carry no page or (x, y), so they belong
 * to the whole document and render here rather than as marks on the sheet.
 * Thumbnails are not streamed yet (the payload gives only a stored path, with
 * no photo-serving route) - a documented follow-on - so each shows its file
 * name, caption and capture date.
 */
function PhotoGallery({ photos }: { photos: OverlayPhoto[] }) {
  const { t } = useTranslation();
  return (
    <div className="rounded-xl border border-border-light bg-surface-primary p-3">
      <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
        <Camera size={13} />
        {t('plan_room.layer_photos', { defaultValue: 'Photos' })}
        <span className="text-content-quaternary">({photos.length})</span>
      </h4>
      <ul className="space-y-1.5">
        {photos.map((ph) => (
          <li key={ph.id} className="flex items-start gap-2 text-sm">
            <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-surface-secondary text-content-tertiary">
              <Camera size={14} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-content-secondary">
                {ph.caption || ph.filename}
              </span>
              {ph.taken_at && (
                <span className="block text-2xs text-content-quaternary">
                  {new Date(ph.taken_at).toLocaleDateString(getIntlLocale())}
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
