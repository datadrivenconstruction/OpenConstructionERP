// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Model Review - where a coordination review is held against the model.
 *
 * One sentence: open the model that is current, walk the issues raised against
 * it with the camera following each one, settle them in place, and leave with a
 * record the other side can open in their own tool.
 *
 * How it differs from the Issues register (/bcf, `BcfIssuesPanel`): the
 * register is the project-wide list of model issues and has to work with no
 * model and no viewer - imported archives, triage, print, project-wide export.
 * This page is the meeting: 3D on screen, checks on the left, the issues that
 * matter on the right, and a guided walk that ends in a hand-over. The two were
 * previously the same thing twice - the review page embedded the whole register
 * in a 380px dock, where its import / version / print toolbar was noise and the
 * things a review needs (filter to what is open against this model, step from
 * issue to issue, close the meeting with a record) did not exist. The dock is
 * now purpose-built (`ReviewIssuesDock`) and reuses the register's api, status
 * vocabulary, capture dialog and guided walk rather than restating them.
 *
 * It keeps the shared <BIMViewer> (and its streaming tile loader) and the BCF
 * capture bridge: pick an element, hit "Raise issue here", and the issue records
 * the camera, the selection and a snapshot of exactly what is on screen.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  Cuboid,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Play,
  Plus,
} from 'lucide-react';

import { BcfIssueModal, CoordinationMode, type BcfMember } from '@/features/bcf';
import {
  exportBcfSelection,
  listTopics,
  type Topic,
  type Viewpoint,
} from '@/features/bcf/api';
import { computeIssueStats } from '@/features/bcf/issueStats';
import { buildIssueReportHtml, type IssueReportRow } from '@/features/bcf/issueReport';
import { isDone, primaryViewpoint } from '@/features/bcf/issueStatus';
import { listAnchors } from '@/features/geo-hub/api';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { apiGet, triggerDownload } from '@/shared/lib/api';
import { fetchProjectList } from '@/shared/lib/projectList';
import { getIntlLocale } from '@/shared/lib/formatters';
import { Button, DismissibleInfo, EmptyState, ModuleGuideButton } from '@/shared/ui';
import { BIMViewer } from '@/shared/ui/BIMViewer';
import type { BIMElementData, ElementManager, SelectionManager } from '@/shared/ui/BIMViewer';
import { metresToModelUnits as unitsToModelScale } from '@/shared/ui/BIMViewer/geoLocate';
import { buildElementQuestion } from '@/shared/ui/BIMViewer/elementQuestion';
import { OfflineModelButton } from '@/shared/ui/BIMViewer/OfflineModelButton';
import type { SceneManager } from '@/shared/ui/BIMViewer/SceneManager';
import { useFloatingChatStore } from '@/features/erp-chat/useFloatingChat';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';

import { makeBcfBridge } from './bcfBridge';
import { ModelChecksPanel } from './ModelChecksPanel';
import { modelReviewGuide } from './modelReviewGuide';
import { restoreBcfViewpoint } from './restoreViewpoint';
import { ReviewIssuesDock } from './ReviewIssuesDock';
import { ReviewSessionSummary } from './ReviewSessionSummary';
import {
  EMPTY_REVIEW_FILTER,
  buildReviewAgenda,
  countReviewTopics,
  filterReviewTopics,
  sortReviewTopics,
  type ReviewFilter,
  type ReviewSort,
} from './reviewFilters';
import { buildReviewMinutesHtml, type ReviewDecision } from './reviewMinutes';
import { useModelViewerData } from './useModelViewerData';

interface RawUser {
  id: string;
  email: string;
  full_name?: string | null;
  is_active?: boolean;
}

/** A review in progress: what was on the agenda and what got settled. */
interface ReviewSessionState {
  startedAt: number;
  agendaGuids: string[];
  decisions: ReviewDecision[];
}

function ModelReviewInner({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);

  const [activeModelId, setActiveModelId] = useState<string | null>(null);
  const [issuesOpen, setIssuesOpen] = useState(true);
  const [checksOpen, setChecksOpen] = useState(true);
  const [filter, setFilter] = useState<ReviewFilter>(EMPTY_REVIEW_FILTER);
  const [sort, setSort] = useState<ReviewSort>('newest');
  const [selectedGuid, setSelectedGuid] = useState<string | null>(null);
  const [showCapture, setShowCapture] = useState(false);
  const [session, setSession] = useState<ReviewSessionState | null>(null);
  const [walking, setWalking] = useState(false);
  const [summaryOpen, setSummaryOpen] = useState(false);
  const [exporting, setExporting] = useState(false);

  const { models, activeModel, elements, geometryUrl, isLoadingModels, isLoadingElements } =
    useModelViewerData(projectId, activeModelId);

  /* ── Issues ──────────────────────────────────────────────────────────── */

  const topicsQuery = useQuery({
    queryKey: ['bcf', 'topics', projectId],
    queryFn: () => listTopics(projectId),
    enabled: Boolean(projectId),
  });
  const topics = useMemo(() => topicsQuery.data ?? [], [topicsQuery.data]);

  const refreshTopics = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['bcf', 'topics', projectId] });
  }, [qc, projectId]);

  // Resolve user ids to names. Shares the ['users-search'] cache with the issue
  // register, so the queryFn must store the SAME raw-row shape other consumers
  // cache under this key; the member mapping happens in the memo below.
  const { data: rawUsers = [] } = useQuery({
    queryKey: ['users-search'],
    queryFn: async () => {
      const res = await apiGet<RawUser[] | { items: RawUser[] }>(
        '/v1/users/?limit=100&is_active=true',
      );
      return Array.isArray(res) ? res : (res.items ?? []);
    },
    staleTime: 60_000,
    retry: false,
  });
  const members = useMemo<BcfMember[]>(
    () => rawUsers.map((u) => ({ id: u.id, name: (u.full_name ?? '').trim() || u.email })),
    [rawUsers],
  );
  const memberById = useMemo(() => {
    const map = new Map<string, string>();
    for (const m of members) map.set(m.id, m.name);
    return map;
  }, [members]);
  const memberName = useCallback(
    (id: string | null): string => {
      if (!id) return t('bcf.unassigned', { defaultValue: 'Unassigned' });
      return memberById.get(id) ?? id;
    },
    [memberById, t],
  );

  const chairName = useAuthStore(
    (s) => (s.userFullName ?? '').trim() || (s.userEmail ?? ''),
  );

  const counts = useMemo(
    () => countReviewTopics(topics, activeModelId),
    [topics, activeModelId],
  );
  // One derivation feeds the dock, the guided walk and the hand-over, so the
  // three can never disagree about what "these issues" means.
  const visible = useMemo(
    () => sortReviewTopics(filterReviewTopics(topics, filter, activeModelId), sort),
    [topics, filter, activeModelId, sort],
  );
  const agenda = useMemo(() => buildReviewAgenda(visible), [visible]);

  /* ── Viewer plumbing ─────────────────────────────────────────────────── */

  // Project geo anchor + model units power the viewer's "locate me" pin. The
  // control hides itself when the project has no anchor.
  const geoAnchorQuery = useQuery({
    queryKey: ['geo-hub', 'anchors', projectId],
    queryFn: () => listAnchors(projectId),
    enabled: Boolean(projectId),
    staleTime: 60_000,
  });
  const geoAnchor = useMemo(() => {
    const a = geoAnchorQuery.data?.[0];
    if (!a) return null;
    const lat = Number(a.lat);
    const lon = Number(a.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    return { lat, lon };
  }, [geoAnchorQuery.data]);
  const modelUnitsScale = useMemo(() => {
    const meta = (activeModel?.metadata ?? null) as Record<string, unknown> | null;
    const units =
      (meta?.units as unknown) ??
      ((meta?.metadata as Record<string, unknown> | undefined)?.units as unknown);
    return unitsToModelScale(units);
  }, [activeModel]);

  // Auto-pick the first renderable model so the page is useful on open.
  useEffect(() => {
    if (activeModelId || models.length === 0) return;
    const firstReady =
      models.find((m) => m.status === 'ready' || m.status === 'degraded') ?? models[0];
    if (firstReady) setActiveModelId(firstReady.id);
  }, [models, activeModelId]);

  // A stable BCF bridge that reads the live scene + selection through refs, so
  // its identity never changes (and never re-renders the dock) even as the
  // camera moves and the selection changes.
  const sceneRef = useRef<SceneManager | null>(null);
  const guidsRef = useRef<string[]>([]);
  const [sceneReady, setSceneReady] = useState(false);
  const bridge = useMemo(
    () =>
      makeBcfBridge(
        () => sceneRef.current,
        () => guidsRef.current,
      ),
    [],
  );

  const handleSceneReady = useCallback((scene: SceneManager | null) => {
    sceneRef.current = scene;
    setSceneReady(!!scene);
  }, []);

  // "Ask AI about this element" - seed the shared assistant with a full
  // element-context prompt. Same behaviour as on the main BIM page.
  const handleAskAiAboutElement = useCallback((element: BIMElementData) => {
    useFloatingChatStore.getState().seedPrompt(buildElementQuestion(element));
  }, []);

  const handleSelectionChange = useCallback((_ids: string[], els: BIMElementData[]) => {
    // BCF wants stable ids (IFC GlobalId / RVT UniqueId); fall back to the
    // mesh ref, then the row id, and drop anything empty.
    guidsRef.current = els
      .map((e) => e.stable_id ?? e.mesh_ref ?? e.id)
      .filter((v): v is string => !!v);
  }, []);

  // Map a viewpoint's stable ids (IFC GlobalId / RVT UniqueId / mesh ref) back
  // to the internal element id the scene managers key on, so restoring a
  // viewpoint can select exactly the elements the issue was raised against.
  const stableIdToElementId = useMemo(() => {
    const map = new Map<string, string>();
    for (const el of elements) {
      if (el.id) map.set(el.id, el.id);
      if (el.stable_id) map.set(el.stable_id, el.id);
      if (el.mesh_ref) map.set(el.mesh_ref, el.id);
    }
    return (stableId: string): string | undefined => map.get(stableId);
  }, [elements]);

  const restoreViewpoint = useCallback(
    (vp: Viewpoint) => {
      const scene = sceneRef.current;
      if (!scene) return;
      const bim = (
        window as unknown as {
          __oeBim?: {
            elementManager: ElementManager | null;
            selectionManager: SelectionManager | null;
          };
        }
      ).__oeBim;
      void restoreBcfViewpoint(vp, {
        scene,
        elementManager: bim?.elementManager ?? null,
        selectionManager: bim?.selectionManager ?? null,
        stableIdToElementId,
      });
    },
    [stableIdToElementId],
  );

  // An issue raised against another loaded model is still reachable: switch to
  // its model and fly once the scene has that model on screen. Without this the
  // camera would restore into geometry the issue does not belong to.
  const [pendingView, setPendingView] = useState<{ topicGuid: string; vpGuid: string } | null>(
    null,
  );

  const goToIssue = useCallback(
    (topic: Topic) => {
      setSelectedGuid(topic.guid);
      const vp = primaryViewpoint(topic);
      if (!vp) return;
      const otherModel =
        topic.bim_model_id && topic.bim_model_id !== activeModelId ? topic.bim_model_id : null;
      if (otherModel) {
        if (models.some((m) => m.id === otherModel)) {
          setActiveModelId(otherModel);
          setPendingView({ topicGuid: topic.guid, vpGuid: vp.guid });
        } else {
          addToast({
            type: 'info',
            title: t('bim.review_issue_other_model', {
              defaultValue: 'This issue belongs to a model that is not in this project.',
            }),
          });
        }
        return;
      }
      restoreViewpoint(vp);
    },
    [activeModelId, models, restoreViewpoint, addToast, t],
  );

  useEffect(() => {
    if (!pendingView || !sceneReady || isLoadingElements) return;
    const topic = topics.find((tp) => tp.guid === pendingView.topicGuid);
    const vp = topic?.viewpoints.find((v) => v.guid === pendingView.vpGuid);
    if (vp) restoreViewpoint(vp);
    setPendingView(null);
  }, [pendingView, sceneReady, isLoadingElements, topics, restoreViewpoint]);

  // The guided walk hands back the topic it stepped to; keep the dock in step
  // with it so the list, the detail and the camera all point at one issue.
  const handleOpenViewpoint = useCallback(
    (topic: Topic, vp: Viewpoint) => {
      setSelectedGuid(topic.guid);
      const otherModel =
        topic.bim_model_id && topic.bim_model_id !== activeModelId ? topic.bim_model_id : null;
      if (otherModel && models.some((m) => m.id === otherModel)) {
        setActiveModelId(otherModel);
        setPendingView({ topicGuid: topic.guid, vpGuid: vp.guid });
        return;
      }
      restoreViewpoint(vp);
    },
    [activeModelId, models, restoreViewpoint],
  );

  // Focus a model-check finding in the viewer: select its element (which also
  // updates the BCF bridge's selected guids via handleSelectionChange) and,
  // unless the caller opts out, frame it. Returns whether the element resolved
  // to a mesh in the loaded model so the panel can hint when it cannot be shown.
  const focusElementById = useCallback(
    (elementId: string, opts?: { zoom?: boolean }): boolean => {
      const scene = sceneRef.current;
      if (!scene) return false;
      const bim = (
        window as unknown as {
          __oeBim?: {
            elementManager: ElementManager | null;
            selectionManager: SelectionManager | null;
          };
        }
      ).__oeBim;
      const selectionManager = bim?.selectionManager ?? null;
      const elementManager = bim?.elementManager ?? null;
      if (!selectionManager) return false;
      // Findings carry the BIMElement id (== the viewer's skeleton element id);
      // resolve through the stable-id map so a stable_id / mesh_ref also lands.
      const internalId = stableIdToElementId(elementId) ?? elementId;
      selectionManager.selectByIds([internalId], { exclusive: true });
      const mesh = elementManager?.getMesh(internalId) ?? null;
      if (mesh && opts?.zoom !== false) scene.zoomToSelection([mesh]);
      return Boolean(mesh);
    },
    [stableIdToElementId],
  );

  /* ── Session ─────────────────────────────────────────────────────────── */

  const recordDecision = useCallback((decision: ReviewDecision) => {
    setSession((prev) =>
      prev ? { ...prev, decisions: [...prev.decisions, decision] } : prev,
    );
  }, []);

  const startSession = useCallback(() => {
    if (agenda.length === 0) return;
    setSession({
      startedAt: Date.now(),
      agendaGuids: agenda.map((tp) => tp.guid),
      decisions: [],
    });
    setWalking(true);
    setIssuesOpen(true);
  }, [agenda]);

  const finishSession = useCallback(() => {
    setWalking(false);
    setSummaryOpen(true);
  }, []);

  // Closing the bar ends the walk. If anything was settled, still show the
  // record rather than dropping it silently.
  const abandonSession = useCallback(() => {
    setWalking(false);
    if (session && session.decisions.length > 0) setSummaryOpen(true);
  }, [session]);

  /** Topics that were on the session agenda, in the order they were walked. */
  const sessionAgenda = useMemo(() => {
    if (!session) return [];
    const byGuid = new Map(topics.map((tp) => [tp.guid, tp]));
    return session.agendaGuids
      .map((g) => byGuid.get(g))
      .filter((tp): tp is Topic => Boolean(tp));
  }, [session, topics]);

  const sessionStillOpen = useMemo(
    () => sessionAgenda.filter((tp) => !isDone(tp.topic_status)).length,
    [sessionAgenda],
  );

  /* ── Hand-over: archive + print ──────────────────────────────────────── */

  const exportTopics = useCallback(
    async (selection: Topic[], stem: string) => {
      if (selection.length === 0) return;
      setExporting(true);
      try {
        const stamp = new Date().toISOString().slice(0, 10);
        const { blob, filename } = await exportBcfSelection(projectId, {
          topicGuids: selection.map((tp) => tp.guid),
          filename: `${stem}-${stamp}.bcfzip`,
        });
        triggerDownload(blob, filename);
        addToast({
          type: 'success',
          title: t('bcf.exported', { defaultValue: 'BCF exported' }),
          message: t('bim.review_exported_count', {
            defaultValue: 'Issues in the archive: {{n}}',
            n: selection.length,
          }),
        });
      } catch (err) {
        addToast({
          type: 'error',
          title: t('bcf.export_failed', { defaultValue: 'Export failed' }),
          message: err instanceof Error ? err.message : undefined,
        });
      } finally {
        setExporting(false);
      }
    },
    [projectId, addToast, t],
  );

  /** Open a standalone document in a print window, or say why it did not. */
  const printDocument = useCallback(
    (html: string) => {
      const w = window.open('', '_blank');
      if (!w) {
        addToast({
          type: 'warning',
          title: t('bcf.report_popup_blocked', {
            defaultValue: 'Allow pop-ups to print the report',
          }),
        });
        return;
      }
      w.document.write(html);
      w.document.close();
      w.focus();
      w.print();
    },
    [addToast, t],
  );

  const printVisible = useCallback(() => {
    const rows: IssueReportRow[] = visible.map((topic) => ({
      index: topic.index,
      title: topic.title,
      status: topic.topic_status,
      priority: topic.priority ?? '',
      assignee: topic.assigned_to ? memberName(topic.assigned_to) : '',
      due: topic.due_date ? topic.due_date.slice(0, 10) : null,
      comments: topic.comments.length,
      description: topic.description,
    }));
    printDocument(
      buildIssueReportHtml({
        title: t('bcf.report_title', { defaultValue: 'Coordination issue report' }),
        scopeLabel: activeModel?.name ?? '',
        generatedOn: new Date().toLocaleString(getIntlLocale()),
        stats: computeIssueStats(visible),
        rows,
        labels: {
          summary: t('bcf.dashboard_summary', { defaultValue: 'Summary' }),
          total: t('bcf.report_total', { defaultValue: 'Total issues' }),
          open: t('bcf.dashboard_open', { defaultValue: 'Open' }),
          closed: t('bcf.report_closed', { defaultValue: 'Closed' }),
          overdue: t('bcf.dashboard_overdue', { defaultValue: 'Overdue' }),
          unassigned: t('bcf.report_unassigned', { defaultValue: 'Unassigned (open)' }),
          issues: t('bcf.report_issues', { defaultValue: 'Issues' }),
          colNum: '#',
          colTitle: t('bcf.report_col_issue', { defaultValue: 'Issue' }),
          colStatus: t('bcf.field_status', { defaultValue: 'Status' }),
          colPriority: t('bcf.field_priority', { defaultValue: 'Priority' }),
          colAssignee: t('bcf.field_assigned_to', { defaultValue: 'Assigned to' }),
          colDue: t('bcf.field_due_date', { defaultValue: 'Due date' }),
          colComments: t('bcf.comments', { defaultValue: 'Comments' }),
          none: '-',
        },
      }),
    );
  }, [visible, memberName, activeModel, printDocument, t]);

  const printMinutes = useCallback(() => {
    if (!session) return;
    printDocument(
      buildReviewMinutesHtml({
        title: t('bim.review_minutes_title', { defaultValue: 'Model review minutes' }),
        modelName: activeModel?.name ?? null,
        // Whoever is signed in ran the meeting; the name is what the minutes
        // are signed with, and it falls back to the email when the profile has
        // no full name yet.
        chair: chairName,
        heldOn: new Date(session.startedAt).toLocaleString(getIntlLocale()),
        agenda: sessionAgenda.map((topic) => ({
          index: topic.index,
          title: topic.title,
          status: topic.topic_status,
          priority: topic.priority ?? '',
          assignee: topic.assigned_to ? memberName(topic.assigned_to) : '',
          due: topic.due_date ? topic.due_date.slice(0, 10) : null,
        })),
        decisions: session.decisions,
        stillOpen: sessionStillOpen,
        labels: {
          model: t('bim.review_minutes_model', { defaultValue: 'Model' }),
          chair: t('bim.review_minutes_chair', { defaultValue: 'Chaired by' }),
          held: t('bim.review_minutes_held', { defaultValue: 'Held' }),
          agendaSize: t('bim.review_summary_agenda', { defaultValue: 'Issues reviewed' }),
          decisionsTaken: t('bim.review_summary_decisions', { defaultValue: 'Decisions taken' }),
          stillOpen: t('bim.review_summary_still_open', { defaultValue: 'Still open' }),
          decisions: t('bim.review_summary_decisions', { defaultValue: 'Decisions taken' }),
          agenda: t('bim.review_summary_agenda', { defaultValue: 'Issues reviewed' }),
          colIssue: t('bcf.report_col_issue', { defaultValue: 'Issue' }),
          colChange: t('bim.review_minutes_change', { defaultValue: 'Change' }),
          colNote: t('bim.review_minutes_note', { defaultValue: 'Note' }),
          colNum: '#',
          colStatus: t('bcf.field_status', { defaultValue: 'Status' }),
          colPriority: t('bcf.field_priority', { defaultValue: 'Priority' }),
          colAssignee: t('bcf.field_assigned_to', { defaultValue: 'Assigned to' }),
          colDue: t('bcf.field_due_date', { defaultValue: 'Due date' }),
          noDecisions: t('bim.review_minutes_no_decisions', {
            defaultValue: 'No status changes or notes were recorded in this session.',
          }),
          none: '-',
        },
      }),
    );
  }, [session, sessionAgenda, sessionStillOpen, activeModel, memberName, chairName, printDocument, t]);

  /* ── Render ──────────────────────────────────────────────────────────── */

  const noModels = !isLoadingModels && models.length === 0;

  return (
    // Full-bleed, DEFINITE height. The page lives inside the app shell's
    // `min-h-screen` main, which only sets a height FLOOR - so a plain
    // `h-full` here resolves to content height and the BIMViewer canvas
    // (sized to its parent by a ResizeObserver) balloons the whole column
    // to tens of thousands of px the moment a tall checks report renders.
    // Pinning the root to `100vh - 56px` (the header offset, same as the
    // main BIM workspace) gives the flex chain a real ceiling, so `flex-1`
    // + `min-h-0` on the body row distribute correctly and the canvas stays
    // bounded. The negative margins negate the padded `main` to go edge-to-edge.
    <div className="flex flex-col -mx-4 -mt-6 -mb-4 sm:-mx-7" style={{ height: 'calc(100vh - 56px)' }}>
      {/* Header: what this page is, which model, and the two actions that
          only exist because a model is on screen. */}
      <div className="flex flex-wrap items-center gap-2 border-b border-border-light px-4 py-2.5">
        <Cuboid size={18} className="shrink-0 text-oe-blue" />
        <h1 className="text-sm font-semibold text-content-primary">
          {t('nav.model_review', { defaultValue: 'Model Review' })}
        </h1>
        <select
          className="ms-1 max-w-[240px] rounded-lg border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-secondary"
          value={activeModelId ?? ''}
          onChange={(e) => setActiveModelId(e.target.value || null)}
          disabled={isLoadingModels || models.length === 0}
          aria-label={t('bim.review_model_select', { defaultValue: 'Model under review' })}
          data-testid="review-model-select"
        >
          {models.length === 0 && (
            <option value="">
              {isLoadingModels
                ? t('common.loading', { defaultValue: 'Loading...' })
                : t('bim.no_models', { defaultValue: 'No models yet' })}
            </option>
          )}
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name}
            </option>
          ))}
        </select>

        {/* Headline counts: the first question a coordinator asks. Rendered as
            number + label rather than one interpolated sentence, so no locale
            needs a plural form for them. */}
        {topics.length > 0 && (
          <div className="flex items-center gap-2 text-2xs text-content-tertiary">
            <span className="inline-flex items-center gap-1">
              <span className="font-semibold tabular-nums text-content-secondary">
                {counts.open}
              </span>
              {t('bcf.dashboard_open', { defaultValue: 'Open' })}
            </span>
            {counts.overdue > 0 && (
              <span className="inline-flex items-center gap-1 text-semantic-error">
                <AlertTriangle size={11} />
                <span className="font-semibold tabular-nums">{counts.overdue}</span>
                {t('bcf.dashboard_overdue', { defaultValue: 'Overdue' })}
              </span>
            )}
          </div>
        )}

        <div className="flex-1" />

        <ModuleGuideButton content={modelReviewGuide} onCta={startSession} />

        <Button
          variant="primary"
          size="sm"
          onClick={startSession}
          disabled={agenda.length === 0 || walking}
          icon={<Play size={14} />}
          data-testid="review-start-session"
          title={t('bim.review_start_hint', {
            defaultValue: 'Step through the issues below, one at a time, with the camera following.',
          })}
        >
          {t('bim.review_start', { defaultValue: 'Start review' })}
          {agenda.length > 0 && (
            <span className="ms-1.5 tabular-nums opacity-80">{agenda.length}</span>
          )}
        </Button>

        {/* The capture action lives in the dock; surface it here too when the
            dock is closed so it never becomes unreachable. */}
        {!issuesOpen && sceneReady && (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setShowCapture(true)}
            icon={<Plus size={14} />}
          >
            {t('bcf.raise_issue', { defaultValue: 'Raise issue here' })}
          </Button>
        )}

        {activeModelId && <OfflineModelButton modelId={activeModelId} />}
        <button
          type="button"
          onClick={() => setChecksOpen((v) => !v)}
          className="flex items-center gap-1.5 rounded-lg border border-border-light px-2.5 py-1.5 text-sm text-content-secondary hover:bg-surface-secondary"
          aria-pressed={checksOpen}
        >
          {checksOpen ? <PanelLeftClose size={15} /> : <PanelLeftOpen size={15} />}
          {t('bim.checks_title', { defaultValue: 'Checks' })}
        </button>
        <button
          type="button"
          onClick={() => setIssuesOpen((v) => !v)}
          className="flex items-center gap-1.5 rounded-lg border border-border-light px-2.5 py-1.5 text-sm text-content-secondary hover:bg-surface-secondary"
          aria-pressed={issuesOpen}
        >
          {issuesOpen ? <PanelRightClose size={15} /> : <PanelRightOpen size={15} />}
          {t('bim.issues', { defaultValue: 'Issues' })}
        </button>
      </div>

      {/* What this page is for, in one line. Collapses to nothing and re-opens
          from the info icon beside the module name in the top bar. */}
      <div className="shrink-0 px-4 pt-2.5">
        <DismissibleInfo
          storageKey="model-review.intro"
          title={t('bim.review_intro_title', { defaultValue: 'Hold the review against the model' })}
          links={[
            {
              label: t('bim.review_link_bim', { defaultValue: 'Load a model in BIM Hub' }),
              onClick: () => navigate('/bim'),
            },
            {
              label: t('bim.review_link_register', { defaultValue: 'All project issues' }),
              onClick: () => navigate('/bcf'),
            },
          ]}
        >
          {t('bim.review_intro_body', {
            defaultValue:
              'Run the automated checks on the left, then work the issues on the right: filter to what is open, late or raised against this model, click one to fly the camera to it, and settle it in place. Start review walks them one by one and ends with minutes plus a .bcfzip hand-over.',
          })}
        </DismissibleInfo>
      </div>

      {/* Body: checks dock + viewer + issues dock.
          Every column carries `min-h-0 overflow-hidden` so a tall dock (a long
          checks-findings list) scrolls INSIDE its own panel instead of
          stretching the flex row. Without it the row grows to the dock's content
          height and the viewer's `h-full` canvas balloons to thousands of px
          tall, pushing the model off-screen the moment checks are run. */}
      <div className="flex min-h-0 flex-1">
        {checksOpen && (
          <aside className="flex w-[340px] shrink-0 flex-col border-e border-border-light bg-surface-primary min-h-0 overflow-hidden">
            <ModelChecksPanel
              // Re-key per model so the run/report state is scoped to it.
              key={activeModelId ?? 'none'}
              projectId={projectId}
              modelId={activeModelId}
              bridge={bridge}
              viewerReady={sceneReady}
              onFocusElement={focusElementById}
            />
          </aside>
        )}

        <div className="relative min-h-0 min-w-0 flex-1">
          {activeModelId ? (
            <BIMViewer
              modelId={activeModelId}
              projectId={projectId}
              modelName={activeModel?.name}
              modelMetadata={activeModel?.metadata ?? null}
              elements={elements}
              geometryUrl={geometryUrl}
              geoAnchor={geoAnchor}
              metresToModelUnits={modelUnitsScale}
              isLoading={isLoadingElements}
              onSelectionChange={handleSelectionChange}
              onSceneReady={handleSceneReady}
              onAskAiAboutElement={handleAskAiAboutElement}
              className="h-full"
            />
          ) : (
            <div className="flex h-full items-center justify-center p-6">
              {noModels ? (
                // Nothing to review yet: name the next action and where it is.
                <EmptyState
                  icon={<Cuboid size={26} strokeWidth={1.5} />}
                  title={t('bim.review_no_models_title', { defaultValue: 'No model to review yet' })}
                  description={t('bim.review_no_models_desc', {
                    defaultValue:
                      'A review needs a converted model. Load one in the BIM Hub - conversion runs in the background - then come back and it will be waiting in the picker above. Issues imported from another tool are already readable in the issue register.',
                  })}
                  action={{
                    label: t('bim.review_go_to_bim', { defaultValue: 'Go to BIM Hub' }),
                    onClick: () => navigate('/bim'),
                  }}
                />
              ) : (
                <EmptyState
                  icon={<Cuboid size={26} strokeWidth={1.5} />}
                  title={t('bim.review_pick_model_title', { defaultValue: 'Pick a model to review' })}
                  description={t('bim.review_pick_model_desc', {
                    defaultValue:
                      'Choose one of the project models in the picker above. Its issues, checks and 3D view all follow the model you pick.',
                  })}
                />
              )}
            </div>
          )}
        </div>

        {issuesOpen && (
          <div className="flex w-[380px] shrink-0 flex-col border-s border-border-light bg-surface-primary min-h-0 overflow-hidden">
            <ReviewIssuesDock
              projectId={projectId}
              modelId={activeModelId}
              topics={topics}
              visible={visible}
              counts={counts}
              filter={filter}
              onFilterChange={setFilter}
              sort={sort}
              onSortChange={setSort}
              isLoading={topicsQuery.isLoading}
              isError={topicsQuery.isError}
              members={members}
              memberName={memberName}
              selectedGuid={selectedGuid}
              onSelect={(guid) => {
                if (!guid) {
                  setSelectedGuid(null);
                  return;
                }
                const topic = topics.find((tp) => tp.guid === guid);
                if (topic) goToIssue(topic);
                else setSelectedGuid(guid);
              }}
              onZoom={goToIssue}
              viewerReady={sceneReady}
              onRaiseIssue={sceneReady ? () => setShowCapture(true) : undefined}
              onRefresh={refreshTopics}
              onDecision={recordDecision}
              onExport={() => void exportTopics(visible, 'model-review-issues')}
              onPrint={printVisible}
              onOpenRegister={() => navigate('/bcf')}
              exporting={exporting}
            />
          </div>
        )}
      </div>

      {/* Raise issue - capture the live camera, selection and snapshot. */}
      <BcfIssueModal
        open={showCapture}
        onClose={() => setShowCapture(false)}
        projectId={projectId}
        bridge={bridge}
        bimModelId={activeModelId}
        assignees={members}
        onCreated={(result) => {
          refreshTopics();
          setSelectedGuid(result.topic.guid);
        }}
      />

      {/* The guided walk: one issue at a time, camera following, over the
          model rather than beside it. */}
      {walking && session && (
        <CoordinationMode
          projectId={projectId}
          topics={topics}
          agenda={sessionAgenda}
          onOpenViewpoint={handleOpenViewpoint}
          onChanged={refreshTopics}
          onDecision={recordDecision}
          onFinish={finishSession}
          onClose={abandonSession}
        />
      )}

      {/* The record to leave with. */}
      {session && (
        <ReviewSessionSummary
          open={summaryOpen}
          onClose={() => setSummaryOpen(false)}
          modelName={activeModel?.name ?? null}
          heldOn={new Date(session.startedAt).toLocaleString(getIntlLocale())}
          agendaSize={sessionAgenda.length}
          stillOpen={sessionStillOpen}
          decisions={session.decisions}
          onPrintMinutes={printMinutes}
          onExportAgenda={() => void exportTopics(sessionAgenda, 'model-review')}
          exporting={exporting}
        />
      )}
    </div>
  );
}

/** Route wrapper: resolve the active project, then render the review surface. */
export function ModelReviewPage() {
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<Array<{ id: string; name: string }>>(),
  });
  const projectId = activeProjectId || projects[0]?.id || '';
  return (
    <RequiresProject>
      {projectId ? <ModelReviewInner projectId={projectId} /> : null}
    </RequiresProject>
  );
}

export default ModelReviewPage;
