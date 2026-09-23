// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Users,
  Wifi,
  Shield,
  Zap,
  MessageSquare,
  Camera,
  Plus,
  Loader2,
  ChevronDown,
  Radio,
  Lock,
  X,
} from 'lucide-react';
import { apiGet, apiPost, getErrorMessage } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { CommentThread } from '@/shared/ui/CommentThread';
import { EmptyState } from '@/shared/ui/EmptyState';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DismissibleInfo, IntroRichText } from '@/shared/ui/DismissibleInfo';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  usePresenceWebSocket,
  listMyLocks,
  type CollabLock,
} from '@/features/collab_locks';
import { COLLAB_COLORS } from './types';

/* ── Types ───────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
}

interface Viewpoint {
  id: string;
  entity_type: string;
  entity_id: string;
  viewpoint_type: string;
  data: { title?: string; description?: string; [k: string]: unknown };
  created_by: string;
  comment_id: string | null;
  created_at: string;
  updated_at: string;
}

interface ViewpointListResponse {
  items: Viewpoint[];
  total: number;
}

/* ── Avatar helpers (deterministic colour from id) ───────────────────── */

function colorFor(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = ((hash << 5) - hash + id.charCodeAt(i)) | 0;
  }
  return COLLAB_COLORS[Math.abs(hash) % COLLAB_COLORS.length] ?? '#818cf8';
}

function initialFor(name: string): string {
  return (name.trim()[0] ?? 'U').toUpperCase();
}

/**
 * Real project collaboration hub.
 *
 * Leads with live data for the selected project:
 *  - Discussion: a live, threaded comment feed (entity_type "project") that
 *    posts, replies, edits and deletes against the collaboration API.
 *  - Viewpoints: real saved viewpoints for the project, with a create form
 *    (title + description) wired to POST /collaboration/viewpoints.
 *  - Active now: live presence roster (WebSocket) plus the locks the current
 *    user holds, so the operator can see who else is in the project right now.
 *
 * A condensed how-it-works card and the Yjs display-name setting are kept
 * below the live sections.
 */
export default function CollaborationModule() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const { data: projects = [], isLoading: projectsLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Project[]>(),
    staleTime: 5 * 60_000,
  });

  // Resolve the working project: the global active project if it still exists
  // in the list, otherwise the first project. Never guess a stale id.
  const projectId = useMemo(() => {
    if (activeProjectId && projects.some((p) => p.id === activeProjectId)) {
      return activeProjectId;
    }
    return projects[0]?.id ?? '';
  }, [activeProjectId, projects]);

  const projectName = projects.find((p) => p.id === projectId)?.name ?? '';

  return (
    <div className="space-y-5">
      {/* Header */}
      <PageHeader
        srTitle={t('collab.title', { defaultValue: 'Real-time Collaboration' })}
        subtitle={t('collab.hub_subtitle', {
          defaultValue:
            'Discuss, share viewpoints and see who is working on a project right now',
        })}
      />

      {/* Canonical module info card — pain-named title + workflow body. */}
      <DismissibleInfo
        storageKey="collaboration"
        title={t('collaboration.intro_title', { defaultValue: 'See who is on the project right now' })}
        more={
          t('collaboration.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('collaboration.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('boq.title', { defaultValue: 'Bill of Quantities' }),
            onClick: () => navigate('/boq'),
          },
          {
            label: t('bim.title', { defaultValue: 'BIM' }),
            onClick: () => navigate('/bim'),
          },
        ]}
      >
        {t('collaboration.intro_body', {
          defaultValue:
            'A per-project hub for a threaded discussion, saved viewpoints and a live presence roster showing who is connected and what they have open for editing. The same comment thread also appears in context on BOQ positions, Documents, RFIs and BIM elements, and camera-anchored viewpoints can be saved from the BIM viewer and PDF takeoff. Live co-editing uses peer-to-peer WebRTC, which needs a WebSocket provider configured for persistent server-side sync.',
        })}
      </DismissibleInfo>

      {projectsLoading ? (
        <div className="flex items-center justify-center py-16 text-content-tertiary">
          <Loader2 className="h-5 w-5 animate-spin" />
        </div>
      ) : !projectId ? (
        <EmptyState
          icon={<Users className="h-6 w-6" />}
          title={t('collab.no_projects_title', { defaultValue: 'No project to collaborate on yet' })}
          description={t('collab.no_projects_desc', {
            defaultValue:
              'Create a project first. Once you have one, this hub becomes the place to discuss it with your team, capture viewpoints and see who is online.',
          })}
        />
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {/* Discussion — spans 2 cols on large screens */}
          <div className="lg:col-span-2">
            <DiscussionCard projectId={projectId} projectName={projectName} />
          </div>

          {/* Right column: active now + viewpoints */}
          <div className="space-y-6">
            <ActiveNowCard projectId={projectId} />
            <ViewpointsCard projectId={projectId} />
          </div>
        </div>
      )}

      {/* Secondary: how it works + settings */}
      <HowItWorksCard />
    </div>
  );
}

/* ── Discussion ──────────────────────────────────────────────────────── */

function DiscussionCard({
  projectId,
  projectName,
}: {
  projectId: string;
  projectName: string;
}) {
  const { t } = useTranslation();
  return (
    <div className="rounded-xl border border-border bg-surface-primary p-5">
      <div className="mb-1 flex items-center gap-2">
        <MessageSquare className="h-4 w-4 text-oe-blue" />
        <h2 className="text-sm font-semibold text-content-primary">
          {t('collab.discussion_title', { defaultValue: 'Project discussion' })}
        </h2>
      </div>
      <p className="mb-4 text-xs text-content-tertiary">
        {t('collab.discussion_desc', {
          defaultValue:
            'Project-wide comments live here. You can also comment directly on individual BOQ positions, documents, RFIs and BIM elements where the same thread appears in context.',
        })}
        {projectName ? ` (${projectName})` : ''}
      </p>
      {/* entity_id is keyed in the key prop so switching projects remounts the
          thread with a fresh query rather than leaking the previous feed. */}
      <CommentThread key={projectId} entityType="project" entityId={projectId} />
    </div>
  );
}

/* ── Active now ──────────────────────────────────────────────────────── */

function ActiveNowCard({ projectId }: { projectId: string }) {
  const { t } = useTranslation();

  // Live presence roster for this project (WebSocket). Honest: when no one
  // else is connected the roster is just the current viewer (or empty until
  // the snapshot arrives), and we say so plainly.
  const { status, users } = usePresenceWebSocket('project', projectId, true);

  // Locks the current user currently holds anywhere — surfaced so the
  // operator can see what they have open for editing across the app.
  const { data: myLocks = [] } = useQuery({
    queryKey: ['collab', 'my-locks'],
    queryFn: () => listMyLocks(),
    staleTime: 10_000,
    refetchInterval: 20_000,
    retry: false,
  });

  const connecting = status === 'connecting' || status === 'idle';

  return (
    <div className="rounded-xl border border-border bg-surface-primary p-5">
      <div className="mb-1 flex items-center gap-2">
        <Radio
          className={
            'h-4 w-4 ' +
            (status === 'open' ? 'text-emerald-500' : 'text-content-tertiary')
          }
        />
        <h2 className="text-sm font-semibold text-content-primary">
          {t('collab.active_now_title', { defaultValue: 'Active now' })}
        </h2>
      </div>
      <p className="mb-3 text-xs text-content-tertiary">
        {t('collab.active_now_desc', {
          defaultValue: 'People connected to this project hub right now.',
        })}
      </p>

      {connecting ? (
        <div className="flex items-center gap-2 py-3 text-xs text-content-tertiary">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          {t('collab.presence_connecting', { defaultValue: 'Connecting…' })}
        </div>
      ) : users.length === 0 ? (
        <p className="py-3 text-xs text-content-tertiary">
          {t('collab.presence_empty', {
            defaultValue: 'No one else is viewing this project right now.',
          })}
        </p>
      ) : (
        <ul className="space-y-2">
          {users.map((u) => (
            <li key={u.user_id} className="flex items-center gap-2.5">
              <span
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[11px] font-bold text-white"
                style={{ backgroundColor: colorFor(u.user_id) }}
                title={u.user_name}
              >
                {initialFor(u.user_name)}
              </span>
              <span className="min-w-0 flex-1 truncate text-xs font-medium text-content-primary">
                {u.user_name}
              </span>
              <span className="flex items-center gap-1 text-2xs text-emerald-600 dark:text-emerald-400">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                {t('collab.online', { defaultValue: 'online' })}
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* What the current user has locked for editing */}
      <div className="mt-4 border-t border-border-light pt-3">
        <div className="mb-2 flex items-center gap-1.5">
          <Lock className="h-3.5 w-3.5 text-content-tertiary" />
          <span className="text-xs font-semibold text-content-secondary">
            {t('collab.my_locks_title', { defaultValue: 'Open for editing by you' })}
          </span>
        </div>
        {myLocks.length === 0 ? (
          <p className="text-2xs text-content-tertiary">
            {t('collab.my_locks_empty', {
              defaultValue:
                'You are not editing anything right now. Locks appear here while you edit a BOQ or other record so teammates know it is busy.',
            })}
          </p>
        ) : (
          <ul className="space-y-1.5">
            {myLocks.map((lock: CollabLock) => (
              <li
                key={lock.id}
                className="flex items-center justify-between gap-2 text-2xs text-content-secondary"
              >
                <span className="truncate">
                  {t('collab.lock_entity', {
                    defaultValue: '{{type}}',
                    type: lock.entity_type.replace(/_/g, ' '),
                  })}
                </span>
                <span className="shrink-0 text-content-tertiary">
                  {t('collab.lock_remaining', {
                    defaultValue: '{{count}}s left',
                    count: Math.max(0, Math.round(lock.remaining_seconds)),
                  })}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/* ── Viewpoints ──────────────────────────────────────────────────────── */

function ViewpointsCard({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');

  const queryKey = useMemo(() => ['collab', 'viewpoints', projectId], [projectId]);

  const { data, isLoading } = useQuery({
    queryKey,
    queryFn: () =>
      apiGet<ViewpointListResponse>(
        `/v1/collaboration/viewpoints/?entity_type=project&entity_id=${encodeURIComponent(projectId)}`,
      ),
    staleTime: 15_000,
    retry: false,
  });

  const viewpoints = data?.items ?? [];

  const createMutation = useMutation({
    mutationFn: (body: { title: string; description: string }) =>
      apiPost<Viewpoint>('/v1/collaboration/viewpoints/', {
        entity_type: 'project',
        entity_id: projectId,
        viewpoint_type: 'general',
        data: { title: body.title, description: body.description },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey });
      setTitle('');
      setDescription('');
      setShowForm(false);
      addToast({
        type: 'success',
        title: t('collab.viewpoint_created', { defaultValue: 'Viewpoint saved' }),
      });
    },
    onError: (err: unknown) => {
      addToast({
        type: 'error',
        title: t('collab.viewpoint_create_failed', {
          defaultValue: 'Could not save viewpoint',
        }),
        message: getErrorMessage(err),
      });
    },
  });

  const handleSubmit = useCallback(() => {
    const trimmed = title.trim();
    if (!trimmed) return;
    createMutation.mutate({ title: trimmed, description: description.trim() });
  }, [title, description, createMutation]);

  return (
    <div className="rounded-xl border border-border bg-surface-primary p-5">
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Camera className="h-4 w-4 text-amber-500" />
          <h2 className="text-sm font-semibold text-content-primary">
            {t('collab.viewpoints_title', { defaultValue: 'Viewpoints' })}
          </h2>
        </div>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-2xs font-medium text-content-secondary hover:border-oe-blue hover:text-oe-blue transition-colors"
          aria-label={t('collab.add_viewpoint', { defaultValue: 'Add viewpoint' })}
        >
          {showForm ? <X size={11} /> : <Plus size={11} />}
          {showForm
            ? t('common.cancel', { defaultValue: 'Cancel' })
            : t('collab.add_viewpoint', { defaultValue: 'Add viewpoint' })}
        </button>
      </div>
      <p className="mb-3 text-xs text-content-tertiary">
        {t('collab.viewpoints_desc', {
          defaultValue:
            'Saved markers for a discussion topic. Capture one here, or save camera-anchored viewpoints from the BIM viewer and PDF takeoff.',
        })}
      </p>

      {showForm && (
        <div className="mb-4 space-y-2 rounded-lg border border-border-light bg-surface-secondary p-3">
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder={t('collab.viewpoint_title_ph', {
              defaultValue: 'Viewpoint title',
            })}
            aria-label={t('collab.viewpoint_title_ph', { defaultValue: 'Viewpoint title' })}
            className="w-full rounded-md border border-border bg-surface-primary px-2.5 py-1.5 text-xs text-content-primary placeholder:text-content-quaternary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue/30"
          />
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t('collab.viewpoint_desc_ph', {
              defaultValue: 'What should the team look at? (optional)',
            })}
            aria-label={t('collab.viewpoint_desc_ph', {
              defaultValue: 'What should the team look at? (optional)',
            })}
            rows={2}
            className="w-full resize-none rounded-md border border-border bg-surface-primary px-2.5 py-1.5 text-xs text-content-primary placeholder:text-content-quaternary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue/30"
          />
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!title.trim() || createMutation.isPending}
            className="flex items-center gap-1.5 rounded-md bg-oe-blue px-3 py-1.5 text-2xs font-medium text-white hover:bg-oe-blue-hover disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
          >
            {createMutation.isPending && <Loader2 size={11} className="animate-spin" />}
            {t('collab.save_viewpoint', { defaultValue: 'Save viewpoint' })}
          </button>
        </div>
      )}

      {isLoading ? (
        <div className="space-y-2">
          {[1, 2].map((i) => (
            <div key={i} className="h-10 animate-pulse rounded-lg bg-surface-secondary" />
          ))}
        </div>
      ) : viewpoints.length === 0 ? (
        <p className="py-2 text-xs text-content-tertiary">
          {t('collab.viewpoints_empty', {
            defaultValue:
              'No viewpoints yet. Add one above, or save a camera view from the BIM viewer to anchor a discussion to a spot in the model.',
          })}
        </p>
      ) : (
        <ul className="space-y-2">
          {viewpoints.map((vp) => (
            <li
              key={vp.id}
              className="rounded-lg border border-border-light bg-surface-secondary px-3 py-2"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="min-w-0 flex-1 truncate text-xs font-medium text-content-primary">
                  {vp.data?.title?.trim() ||
                    t('collab.viewpoint_untitled', { defaultValue: 'Untitled viewpoint' })}
                </span>
                <span className="shrink-0 rounded bg-surface-tertiary px-1.5 py-0.5 text-2xs font-medium uppercase text-content-tertiary">
                  {vp.viewpoint_type.replace(/_/g, ' ')}
                </span>
              </div>
              {vp.data?.description?.trim() && (
                <p className="mt-0.5 line-clamp-2 text-2xs text-content-secondary">
                  {vp.data.description}
                </p>
              )}
              <p className="mt-1 text-2xs text-content-quaternary">
                <DateDisplay value={vp.created_at} format="relative" />
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/* ── How it works (condensed, collapsible) + settings ────────────────── */

function HowItWorksCard() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [displayName, setDisplayName] = useState(
    () => localStorage.getItem('oe_collab_name') || 'User',
  );
  const addToast = useToastStore((s) => s.addToast);

  const handleSaveName = () => {
    localStorage.setItem('oe_collab_name', displayName.trim() || 'User');
    addToast({
      type: 'success',
      title: t('collab.name_saved', { defaultValue: 'Display name saved' }),
    });
  };

  return (
    <div className="rounded-xl border border-border bg-surface-primary">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-5 py-3 text-left"
        aria-expanded={open}
      >
        <span className="text-sm font-semibold text-content-primary">
          {t('collab.how_it_works', {
            defaultValue: 'How real-time editing works & your settings',
          })}
        </span>
        <ChevronDown
          className={
            'h-4 w-4 shrink-0 text-content-tertiary transition-transform ' +
            (open ? 'rotate-180' : '')
          }
        />
      </button>

      {open && (
        <div className="space-y-5 border-t border-border-light px-5 py-4">
          {/* Display name (feeds Yjs awareness) */}
          <div>
            <h3 className="mb-2 text-sm font-semibold text-content-primary">
              {t('collab.settings', { defaultValue: 'Collaboration Settings' })}
            </h3>
            <div className="flex max-w-sm items-end gap-3">
              <div className="flex-1">
                <label className="mb-1 block text-xs text-content-tertiary">
                  {t('collab.display_name', { defaultValue: 'Your display name' })}
                </label>
                <input
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-content-primary"
                  placeholder={t('collab.name_placeholder', { defaultValue: 'Your name' })}
                  aria-label={t('collab.display_name', { defaultValue: 'Your display name' })}
                />
              </div>
              <button
                onClick={handleSaveName}
                className="rounded-lg bg-oe-blue px-4 py-2 text-xs font-medium text-white hover:bg-oe-blue-hover transition-colors"
                aria-label={t('collab.save_name', { defaultValue: 'Save display name' })}
              >
                {t('common.save', { defaultValue: 'Save' })}
              </button>
            </div>
            <p className="mt-2 text-2xs text-content-tertiary">
              {t('collab.display_name_hint', {
                defaultValue:
                  'This name is shown to teammates as your cursor and presence label while editing a BOQ together.',
              })}
            </p>
            <div className="mt-3 flex items-center gap-2">
              <span className="text-2xs text-content-tertiary">
                {t('collab.color_palette', { defaultValue: 'User Colors' })}:
              </span>
              {COLLAB_COLORS.map((color) => (
                <span
                  key={color}
                  className="h-5 w-5 rounded-full border-2 border-surface-primary shadow-sm"
                  style={{ backgroundColor: color }}
                  role="presentation"
                  aria-hidden="true"
                />
              ))}
            </div>
          </div>

          {/* Condensed feature cards */}
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <MiniFeature
              icon={<Wifi className="h-4 w-4 text-blue-500" />}
              title={t('collab.feature_sync', { defaultValue: 'Peer-to-Peer Sync' })}
              description={t('collab.feature_sync_short', {
                defaultValue: 'Edits sync directly between browsers via WebRTC.',
              })}
            />
            <MiniFeature
              icon={<Zap className="h-4 w-4 text-amber-500" />}
              title={t('collab.feature_crdt', { defaultValue: 'CRDT Conflict Resolution' })}
              description={t('collab.feature_crdt_short', {
                defaultValue: 'Built on Yjs - concurrent edits merge with no data loss.',
              })}
            />
            <MiniFeature
              icon={<Shield className="h-4 w-4 text-emerald-500" />}
              title={t('collab.feature_presence', { defaultValue: 'Presence Awareness' })}
              description={t('collab.feature_presence_short', {
                defaultValue: 'See who is online and where their cursor is.',
              })}
            />
          </div>

          <p className="text-2xs text-content-quaternary">
            {t('collab.disclaimer', {
              defaultValue:
                'Real-time collaboration uses peer-to-peer WebRTC connections. Data syncs directly between browsers. For persistent server-side sync, configure a WebSocket provider in production.',
            })}
          </p>
        </div>
      )}
    </div>
  );
}

function MiniFeature({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary p-3">
      <div className="mb-1 flex items-center gap-1.5">
        {icon}
        <h4 className="text-xs font-semibold text-content-primary">{title}</h4>
      </div>
      <p className="text-2xs leading-relaxed text-content-tertiary">{description}</p>
    </div>
  );
}
