// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Plan Room page.
 *
 * Opens one drawing sheet and composites every overlay the platform holds for
 * that page - punch pins, plan pins, drawing markups, takeoff measurements and
 * project photos - into a single view with a per-source layer toggle. Write
 * users can drop their own plan pins straight onto the sheet.
 *
 * The page owns: which document / page is open, the layer visibility, the
 * revision indicator and the optimistic pin create / delete. The heavy pdf.js
 * rendering and the on-sheet marks live in {@link PlanRoomViewer}.
 */

import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Camera,
  FileWarning,
  GitBranch,
  Layers as LayersIcon,
  Lock,
  Map as MapIcon,
} from 'lucide-react';
import { ApiError, getErrorMessage } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { Badge, EmptyState } from '@/shared/ui';
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
  const projectId = activeProjectId || projects[0]?.id || '';

  const { data: drawings = [] } = useQuery({
    queryKey: ['plan-room-drawings', projectId],
    queryFn: () => fetchPlanRoomDrawings(projectId),
    enabled: !!projectId,
    staleTime: 60_000,
  });

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

  return (
    <div className="animate-fade-in space-y-5">
      <Breadcrumb
        items={[
          ...(activeProjectId && activeProjectName
            ? [{ label: activeProjectName, to: `/projects/${activeProjectId}` }]
            : []),
          { label: t('plan_room.title', { defaultValue: 'Plan Room' }) },
        ]}
      />

      <PageHeader
        srTitle={t('plan_room.title', { defaultValue: 'Plan Room' })}
        subtitle={t('plan_room.header_subtitle', {
          defaultValue:
            'Every mark on a drawing sheet in one place - pins, markups, measurements and photos as toggleable layers',
        })}
      />

      {/* The page had no explainer, and it is the page that needs one most.
          Nearly everything on a sheet here is owned by another module, so a
          reader who tries to add a markup finds no control and concludes the
          screen is broken rather than that they are in the wrong room. Saying
          which module owns what is the whole answer. */}
      <CollapsibleSection
        storageKey="plan_room.how"
        icon={<MapIcon size={15} className="text-oe-blue" />}
        title={t('plan_room.flow_title', {
          defaultValue: 'What the Plan Room is, and where each mark comes from',
        })}
      >
        <p className="text-xs text-content-tertiary">
          {t('plan_room.flow_intro', {
            defaultValue:
              'A drawing sheet collects marks from several trades and several weeks, and each kind of mark is made somewhere else in the platform. Nobody wants to open four screens to find out what is on one sheet. This room puts all of them back on the sheet at once, as layers you can switch off one at a time.',
          })}
        </p>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-content-tertiary">
          <li>
            {t('plan_room.flow_step1', {
              defaultValue:
                'Pick a drawing. The list holds the project documents that have a sheet to render, so a project with no drawings uploaded yet has nothing to open here.',
            })}
          </li>
          <li>
            {t('plan_room.flow_step2', {
              defaultValue:
                'Everything already recorded against that page is drawn on it: defect pins from the punch list, markups from the drawing review, measurements from takeoff and site photos. Switch a layer off to read the sheet underneath.',
            })}
          </li>
          <li>
            {t('plan_room.flow_step3', {
              defaultValue:
                'Drop a plan pin to put a note or a photo at an exact spot. This is the one mark that belongs to the Plan Room itself, and the only thing created here.',
            })}
          </li>
          <li>
            {t('plan_room.flow_step4', {
              defaultValue:
                'The other layers are read-only on purpose. A markup is edited where markups are made, a measurement where the takeoff is done, a defect in the punch list. Editing them from here would put the same record in two places with two owners.',
            })}
          </li>
        </ol>
        <p className="mt-2 text-xs text-content-tertiary">
          {t('plan_room.flow_empty_note', {
            defaultValue:
              'An empty sheet is the ordinary state of a new project rather than a fault. Marks appear here as the work that makes them happens elsewhere.',
          })}
        </p>
      </CollapsibleSection>

      {/* Document picker + revision indicator */}
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
            {drawings.length === 0 && (
              <option value="">
                {t('plan_room.no_drawings', { defaultValue: 'No drawings available' })}
              </option>
            )}
            {drawings.map((d) => (
              <option key={d.id} value={d.id}>
                {d.filename || d.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </div>
        {overlays?.version && <RevisionIndicator version={overlays.version} />}
      </div>

      {/* Body */}
      {!projectId && !selectedDocId ? (
        <EmptyState
          icon={<MapIcon size={24} />}
          title={t('plan_room.no_project_title', { defaultValue: 'Pick a project first' })}
          description={t('plan_room.no_project_desc', {
            defaultValue: 'Select an active project to open its drawings in the Plan Room.',
          })}
        />
      ) : forbidden ? (
        <EmptyState
          icon={<Lock size={24} />}
          title={t('plan_room.forbidden_title', { defaultValue: 'No access to this drawing' })}
          description={t('plan_room.forbidden_desc', {
            defaultValue: 'You do not have permission to view overlays on this project.',
          })}
        />
      ) : overlaysQuery.isError ? (
        <EmptyState
          icon={<FileWarning size={24} />}
          title={t('plan_room.error_title', { defaultValue: 'Could not load overlays' })}
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
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_300px]">
          {/* Sheet + overlays */}
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

            {/* Sheet completeness: reconcile the set against its drawing index. */}
            <SheetCompletenessPanel projectId={projectId} defaultIndexDocumentId={selectedDocId} />

            {/* Empty-overlays hint (the sheet still renders). */}
            {overlaysQuery.isSuccess && totalOverlays === 0 && (
              <div className="flex items-center gap-2 rounded-xl border border-dashed border-border bg-surface-primary px-3 py-4 text-sm text-content-tertiary">
                <LayersIcon size={15} className="shrink-0" />
                {t('plan_room.no_overlays', { defaultValue: 'No overlays on this page yet.' })}
              </div>
            )}

            {!canWrite && (
              <p className="px-1 text-2xs text-content-quaternary">
                {t('plan_room.read_only', {
                  defaultValue: 'Read-only access - you can view layers but not drop pins.',
                })}
              </p>
            )}

            {/* Photos layer (document-level, so shown as a gallery not on the sheet). */}
            {visibility.photos && (overlays?.photos?.length ?? 0) > 0 && (
              <PhotoGallery photos={overlays!.photos} />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Revision indicator ──────────────────────────────────────────────────── */

/**
 * Which drawing revision the overlays were composited against. The Plan Room
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
        {t('plan_room.revision_untracked', { defaultValue: 'Revision not tracked' })}
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
