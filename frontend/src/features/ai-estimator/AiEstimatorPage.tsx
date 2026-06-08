// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// AI Estimate Builder (/ai-estimator). The orchestrator surface that
// drives the founder's 4-stage vision end to end:
//   1 Understand source (any input, auto-detect)
//   2 Group quantities (AI-derived, editable)
//   3 Match rates (grounded catalogue rates with resource breakdowns)
//   4 Review & apply (totals + validation + explicit human confirm)
//
// A run-based flow: a runs list + "New estimate" opens a 4-stage stepper
// with a persistent left rail and a right run-monitor. AI suggests at
// every step; the human confirms; nothing auto-writes. Rates come only
// from the cost database - the LLM never invents a unit rate. Degrades
// gracefully when no AI key or vector DB is present.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Wand2, ArrowLeft, ArrowRight, Check, Loader2 } from 'lucide-react';

import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { IntakePanel } from '@/features/ai/intake';
import { projectsApi, type Project } from '@/features/projects/api';
import { matchElementsApi } from '@/features/match-elements/api';
import { fetchDocuments, uploadDocument } from '@/features/documents/api';
import { getIntlLocale } from '@/shared/lib/formatters';
import { Button, Card, DismissibleInfo } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';

import {
  aiEstimatorApi,
  type GroupUpdate,
  type RunCreate,
  type RunRead,
  type StageName,
  type SuggestedConfig,
} from './api';
import { useAiReadiness } from './useAiReadiness';
import { useAiEstimatorMeta, ScoreThresholdsProvider } from './meta';
import { AiStatusBanner } from './components/AiStatusBanner';
import { RunsList } from './components/RunsList';
import { StageRail, STAGES, STAGE_INDEX, type StageDef } from './components/StageRail';
import { RunMonitor } from './components/RunMonitor';
import { Stage1Intake, Stage1Confirm, type SourceTabId } from './components/Stage1Source';
import { Stage2Groups } from './components/Stage2Groups';
import { Stage3Match } from './components/Stage3Match';
import { Stage4Review } from './components/Stage4Review';
import { InlineErrorRetry } from './components/InlineErrorRetry';

type View = 'list' | 'wizard';

type ConfigEdits = Partial<SuggestedConfig>;

export function AiEstimatorPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [searchParams, setSearchParams] = useSearchParams();
  const locale = getIntlLocale();

  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const urlProject = searchParams.get('project');
  const urlRun = searchParams.get('run');

  const [projectId, setProjectId] = useState<string | null>(urlProject || activeProjectId);
  const [view, setView] = useState<View>(urlRun ? 'wizard' : 'list');
  const [runId, setRunId] = useState<string | null>(urlRun);

  // Wizard navigation state.
  const [stage, setStage] = useState<StageName>('source');
  const [furthest, setFurthest] = useState(1);

  // Stage-1 intake state.
  const [sourceTab, setSourceTab] = useState<SourceTabId>('text');
  const [text, setText] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [selectedModelId, setSelectedModelId] = useState<string | null>(null);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);

  // Confirm-#1 config edits (per-group edits commit live, not batched).
  const [configEdits, setConfigEdits] = useState<ConfigEdits>({});
  const [rematchingId, setRematchingId] = useState<string | null>(null);
  const [savingGroupId, setSavingGroupId] = useState<string | null>(null);
  const [appliedBoqId, setAppliedBoqId] = useState<string | null>(null);

  const readiness = useAiReadiness();
  // Server-driven score bands, construction stages and match-group cap.
  // Fetched once per page; degrades to the contract defaults on a 404.
  const meta = useAiEstimatorMeta();

  // ── Project list + active project ──────────────────────────────────
  const projectsQ = useQuery({ queryKey: ['projects-all'], queryFn: projectsApi.list });
  const project: Project | undefined = useMemo(
    () => projectsQ.data?.find((p) => p.id === projectId),
    [projectsQ.data, projectId],
  );

  useEffect(() => {
    if (!projectId && projectsQ.data && projectsQ.data.length > 0) {
      setProjectId(projectsQ.data[0]!.id);
    }
  }, [projectId, projectsQ.data]);

  // ── Source pickers ─────────────────────────────────────────────────
  const modelsQ = useQuery({
    enabled: !!projectId && sourceTab === 'bim_model' && view === 'wizard' && !runId,
    queryKey: ['aiest-bim-models', projectId],
    queryFn: () => matchElementsApi.listBIMModels(projectId!),
  });

  const docsQ = useQuery({
    enabled: !!projectId && sourceTab === 'documents' && view === 'wizard' && !runId,
    queryKey: ['aiest-documents', projectId],
    queryFn: () => fetchDocuments(projectId!),
  });

  const cataloguesQ = useQuery({
    queryKey: ['aiest-catalogues'],
    queryFn: aiEstimatorApi.listCatalogues,
    staleTime: 60_000,
    retry: false,
  });

  // ── Runs list ──────────────────────────────────────────────────────
  const runsQ = useQuery({
    enabled: !!projectId && view === 'list',
    queryKey: ['aiest-runs', projectId],
    queryFn: () => aiEstimatorApi.listRuns(projectId!, { limit: 50 }),
  });

  // ── Active run ─────────────────────────────────────────────────────
  const runQ = useQuery({
    enabled: !!runId,
    queryKey: ['aiest-run', runId],
    queryFn: () => aiEstimatorApi.getRun(runId!),
  });
  const run: RunRead | undefined = runQ.data;

  // Sync the wizard stage from the run's persisted current_stage only on the
  // FIRST load of a given run, not on every refetch. After the initial sync the
  // user (or a deliberate jump, e.g. the intake bridge landing on matching) owns
  // the stage, so a background run refetch must not snap them backwards. The
  // intake bridge pre-claims the run id (see syncedRunRef) so its forward jump
  // to matching survives the first runQ resolution.
  const syncedRunRef = useRef<string | null>(null);
  useEffect(() => {
    if (!run) return;
    if (syncedRunRef.current !== run.id) {
      syncedRunRef.current = run.id;
      setStage(run.current_stage);
      setFurthest((f) => Math.max(f, STAGE_INDEX[run.current_stage]));
    }
    if (run.boq_id) setAppliedBoqId(run.boq_id);
  }, [run]);

  // "Running" = a background pass is genuinely still working. Only stage 1
  // (analyze) is a true background job whose completion is signalled by data:
  // the backend leaves status at "analyzing" even after the source is detected
  // (the FSM advances only on the source checkpoint), so analyze is done the
  // moment a detected_source appears. Grouping and matching complete
  // synchronously inside their confirm / match calls, so their persisted
  // status ("grouping" / "matching") is a STAGE marker, not work-in-progress -
  // the per-stage panels show their own brief fetch/mutation spinners. Treating
  // those statuses as "running" would pin the stage-2/3 panels on a skeleton
  // forever (the pass already finished). So isRunning tracks analyze only.
  const analyzeDone = !!run?.detected_source;
  const isRunning = run?.status === 'analyzing' && !analyzeDone;

  // Poll progress while a stage is working.
  const progressQ = useQuery({
    enabled: !!runId && view === 'wizard',
    queryKey: ['aiest-progress', runId],
    queryFn: () => aiEstimatorApi.getProgress(runId!),
    refetchInterval: isRunning ? 2000 : false,
  });

  useEffect(() => {
    const status = progressQ.data?.status;
    if (status && !['analyzing', 'grouping', 'matching'].includes(status)) {
      qc.invalidateQueries({ queryKey: ['aiest-run', runId] });
      qc.invalidateQueries({ queryKey: ['aiest-groups', runId] });
    }
  }, [progressQ.data?.status, qc, runId]);

  // ── Groups (stages 2 + 3) ──────────────────────────────────────────
  const groupsQ = useQuery({
    enabled: !!runId && (stage === 'grouping' || stage === 'matching'),
    queryKey: ['aiest-groups', runId, stage],
    queryFn: () => aiEstimatorApi.listGroups(runId!),
  });
  const groups = groupsQ.data?.groups ?? [];

  // ── Preview (stage 4) ──────────────────────────────────────────────
  const previewQ = useQuery({
    enabled: !!runId && stage === 'assembly',
    queryKey: ['aiest-preview', runId],
    queryFn: () => aiEstimatorApi.getPreview(runId!),
  });

  // ── Mutations ──────────────────────────────────────────────────────
  const startRunM = useMutation({
    mutationFn: async (): Promise<RunRead> => {
      if (!projectId) throw new Error('No project selected');
      const base: RunCreate = {
        project_id: projectId,
        agent_name: null,
        currency: project?.currency || null,
        region: project?.region || null,
      };
      if (sourceTab === 'text') {
        return aiEstimatorApi.createRun({ ...base, source: 'text', text_input: text });
      }
      if (sourceTab === 'bim_model') {
        return aiEstimatorApi.createRun({
          ...base,
          source: 'bim',
          bim_model_ids: selectedModelId ? [selectedModelId] : [],
        });
      }
      if (sourceTab === 'documents') {
        return aiEstimatorApi.createRun({
          ...base,
          source: 'documents',
          document_ids: selectedDocIds,
        });
      }
      // files -> upload each as a project document, then start a documents run.
      const uploaded = await Promise.all(files.map((f) => uploadDocument(projectId, f)));
      return aiEstimatorApi.createRun({
        ...base,
        source: 'documents',
        document_ids: uploaded.map((d) => d.id),
      });
    },
    onSuccess: (created) => {
      setRunId(created.id);
      setStage('source');
      setFurthest(1);
      setSearchParams((p) => {
        const next = new URLSearchParams(p);
        next.set('run', created.id);
        return next;
      });
      qc.invalidateQueries({ queryKey: ['aiest-runs', projectId] });
      // The run is created parked at "analyzing"; stage 1 (normalise the source
      // + detect/classify it) runs as an explicit step. Kick it off now so the
      // confirm card (detected source + suggested config) appears instead of
      // the analyzing spinner hanging forever.
      analyzeM.mutate(created.id);
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('aiest.toast.start_failed', { defaultValue: 'Could not start the estimate' }),
        message: e.message,
      }),
  });

  const analyzeM = useMutation({
    mutationFn: (id: string) => aiEstimatorApi.analyze(id, { use_ai: readiness.llmReady }),
    onSuccess: (updated) => {
      qc.setQueryData(['aiest-run', updated.id], updated);
      qc.invalidateQueries({ queryKey: ['aiest-run', updated.id] });
      qc.invalidateQueries({ queryKey: ['aiest-progress', updated.id] });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('aiest.toast.analyze_failed', { defaultValue: 'Could not read the source' }),
        message: e.message,
      }),
  });

  // Recover an opened run that is parked at "analyzing" without a detected
  // source (e.g. created then abandoned before stage 1 ran, or a reload mid
  // analyze): kick analyze so the confirm card can appear instead of an
  // endless spinner. Guarded so it fires once per run, never while a pass runs.
  useEffect(() => {
    if (
      run &&
      run.status === 'analyzing' &&
      !run.detected_source &&
      run.current_stage === 'source' &&
      !analyzeM.isPending &&
      analyzeM.variables !== run.id
    ) {
      analyzeM.mutate(run.id);
    }
  }, [run, analyzeM]);

  const confirmStageM = useMutation({
    mutationFn: (s: StageName) => {
      const edits =
        s === 'source'
          ? {
              catalogue_id: configEdits.catalogue_id,
              region: configEdits.region,
              currency: configEdits.currency,
              group_by: configEdits.group_by,
              construction_stage: configEdits.construction_stage,
            }
          : undefined;
      return aiEstimatorApi.confirmStage(runId!, { stage: s, edits });
    },
    onSuccess: (updated) => {
      qc.setQueryData(['aiest-run', runId], updated);
      qc.invalidateQueries({ queryKey: ['aiest-groups', runId] });
      setConfigEdits({});
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('aiest.toast.confirm_failed', { defaultValue: 'Could not save your changes' }),
        message: e.message,
      }),
  });

  // Match every group, batching in chunks of the server-driven cap. A single
  // /match pass only processes `match_group_cap` groups (vector search over
  // hundreds of groups would block), so when there are more we iterate -
  // passing explicit group_ids per batch so the cap never silently drops the
  // tail. Nothing is fabricated; groups with no grounded rate come back
  // needs_human and stay visible at the top of stage 3.
  const runMatchM = useMutation({
    mutationFn: async () => {
      if (!runId) throw new Error('No run');
      const cap = meta.matchGroupCap;
      // Re-read the live group list so we batch the real unmatched set even
      // when stage-3's own query has not populated yet.
      const list = await aiEstimatorApi.listGroups(runId);
      const pending = list.groups
        .filter((g) => g.status !== 'skipped' && g.status !== 'confirmed' && g.status !== 'overridden')
        .map((g) => g.id);
      if (pending.length === 0) return;
      for (let i = 0; i < pending.length; i += cap) {
        const batch = pending.slice(i, i + cap);
        await aiEstimatorApi.runMatch(runId, {
          group_ids: batch,
          use_reranker: true,
          top_k: 10,
          max_groups: batch.length,
        });
        // Surface progress incrementally so each batch's results render.
        qc.invalidateQueries({ queryKey: ['aiest-groups', runId] });
      }
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['aiest-groups', runId] }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('aiest.toast.match_failed', { defaultValue: 'Matching failed' }),
        message: e.message,
      }),
  });

  const updateGroupM = useMutation({
    mutationFn: (args: { groupId: string; patch: GroupUpdate }) =>
      aiEstimatorApi.updateGroup(runId!, args.groupId, args.patch),
    onMutate: (args) => setSavingGroupId(args.groupId),
    onSettled: () => setSavingGroupId(null),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['aiest-groups', runId] }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('aiest.toast.update_failed', { defaultValue: 'Could not update the group' }),
        message: e.message,
      }),
  });

  const mergeGroupsM = useMutation({
    mutationFn: (groupIds: string[]) => aiEstimatorApi.mergeGroups(runId!, { group_ids: groupIds }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['aiest-groups', runId] }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('aiest.toast.merge_failed', { defaultValue: 'Could not merge the groups' }),
        message: e.message,
      }),
  });

  const confirmGroupM = useMutation({
    mutationFn: (args: { groupId: string; candidateId: string | null }) =>
      aiEstimatorApi.confirmGroup(runId!, args.groupId, {
        ...(args.candidateId ? { candidate_id: args.candidateId } : {}),
      }),
    onSuccess: (_data, args) => {
      qc.invalidateQueries({ queryKey: ['aiest-groups', runId] });
      qc.invalidateQueries({ queryKey: ['aiest-group-detail', runId, args.groupId] });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('aiest.toast.confirm_group_failed', { defaultValue: 'Could not confirm the rate' }),
        message: e.message,
      }),
  });

  const rematchGroupM = useMutation({
    mutationFn: (args: { groupId: string; useAgent: boolean }) =>
      aiEstimatorApi.rematchGroup(runId!, args.groupId, { use_agent: args.useAgent }),
    onMutate: (args) => setRematchingId(args.groupId),
    onSettled: () => setRematchingId(null),
    onSuccess: (_data, args) => {
      qc.invalidateQueries({ queryKey: ['aiest-groups', runId] });
      qc.invalidateQueries({ queryKey: ['aiest-group-detail', runId, args.groupId] });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('aiest.toast.rematch_failed', { defaultValue: 'Re-query failed' }),
        message: e.message,
      }),
  });

  const bulkConfirmM = useMutation({
    mutationFn: (threshold: number) => aiEstimatorApi.bulkConfirm(runId!, { threshold }),
    onSuccess: (r) => {
      if (r.confirmed > 0) {
        addToast({
          type: 'success',
          title: t('aiest.toast.bulk_confirmed', {
            defaultValue: '{{n}} groups confirmed',
            n: r.confirmed,
          }),
        });
      } else {
        addToast({
          type: 'info',
          title: t('aiest.toast.bulk_none', {
            defaultValue: 'No groups met the auto-confirm score',
          }),
          message: t('aiest.toast.bulk_none_body', {
            defaultValue: 'Confirm the remaining rates individually below.',
          }),
        });
      }
      qc.invalidateQueries({ queryKey: ['aiest-groups', runId] });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('aiest.toast.bulk_failed', { defaultValue: 'Bulk confirm failed' }),
        message: e.message,
      }),
  });

  const applyM = useMutation({
    mutationFn: async () => {
      // The "I have reviewed this" tick is the human acceptance of the
      // assembly review checkpoint. The backend's apply() requires that
      // checkpoint accepted, so record it first (idempotent) and then write.
      if (!run?.checkpoints?.assembly) {
        await aiEstimatorApi.confirmStage(runId!, { stage: 'assembly' });
      }
      return aiEstimatorApi.apply(runId!, { append: false });
    },
    onSuccess: (r) => {
      setAppliedBoqId(r.boq_id);
      addToast({
        type: 'success',
        title: t('aiest.toast.applied', {
          defaultValue: '{{n}} BOQ positions written',
          n: r.positions_created,
        }),
      });
      qc.invalidateQueries({ queryKey: ['aiest-run', runId] });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('aiest.toast.apply_failed', { defaultValue: 'Could not write the BOQ' }),
        message: e.message,
      }),
  });

  // ── Navigation ─────────────────────────────────────────────────────
  const openWizardNew = useCallback(() => {
    setRunId(null);
    setView('wizard');
    setStage('source');
    setFurthest(1);
    setSourceTab('text');
    setText('');
    setFiles([]);
    setSelectedModelId(null);
    setSelectedDocIds([]);
    setConfigEdits({});
    setAppliedBoqId(null);
    setSearchParams((p) => {
      const next = new URLSearchParams(p);
      next.delete('run');
      return next;
    });
  }, [setSearchParams]);

  const openRun = useCallback(
    (id: string) => {
      // Force a fresh stage-sync from the run's persisted stage, even if this is
      // the same run id we bridged into earlier this session.
      syncedRunRef.current = null;
      setRunId(id);
      setView('wizard');
      setSearchParams((p) => {
        const next = new URLSearchParams(p);
        next.set('run', id);
        return next;
      });
    },
    [setSearchParams],
  );

  // The conversational intake (Stage A-C of the founder flow) bridges to a run
  // the moment the user confirms the editable group board. The board confirm IS
  // the grouping checkpoint, so we land the wizard on the matching stage of the
  // SAME page and kick off the grounded multi-pass match. No navigation away, no
  // parse_text_scope run: the dialogue's composed groups flow straight into rate
  // matching.
  //
  // pendingIntakeMatch defers the auto-match until runId state has settled (the
  // match mutation reads runId from closure, so we cannot fire it in the same
  // tick as setRunId). The effect below consumes the flag.
  const [pendingIntakeMatch, setPendingIntakeMatch] = useState(false);

  const onIntakeFinished = useCallback(
    (newRunId: string) => {
      // Pre-claim the run so the stage-sync effect does not snap us back to the
      // run's persisted "grouping" stage when runQ first resolves.
      syncedRunRef.current = newRunId;
      setRunId(newRunId);
      setView('wizard');
      setStage('matching');
      setFurthest((f) => Math.max(f, STAGE_INDEX.matching));
      setConfigEdits({});
      setAppliedBoqId(null);
      setPendingIntakeMatch(true);
      setSearchParams((p) => {
        const next = new URLSearchParams(p);
        next.set('run', newRunId);
        return next;
      });
      qc.invalidateQueries({ queryKey: ['aiest-runs', projectId] });
    },
    [projectId, qc, setSearchParams],
  );

  // Consume the bridge flag once runId has settled: the composed groups ARE the
  // grouping output, so matching has not run yet. Fire it so grounded candidates
  // appear the moment the user lands on the matching stage.
  useEffect(() => {
    if (pendingIntakeMatch && runId && stage === 'matching') {
      setPendingIntakeMatch(false);
      runMatchM.mutate();
    }
  }, [pendingIntakeMatch, runId, stage, runMatchM]);

  const backToList = useCallback(() => {
    setView('list');
    setRunId(null);
    setSearchParams((p) => {
      const next = new URLSearchParams(p);
      next.delete('run');
      return next;
    });
    qc.invalidateQueries({ queryKey: ['aiest-runs', projectId] });
  }, [projectId, qc, setSearchParams]);

  const goto = useCallback((id: StageName) => {
    setStage(id);
    setFurthest((f) => Math.max(f, STAGE_INDEX[id]));
  }, []);

  const jumpTo = useCallback(
    (id: StageName) => {
      if (STAGE_INDEX[id] <= STAGE_INDEX[stage]) {
        setStage(id);
        return;
      }
      if (!runId) {
        addToast({
          type: 'info',
          title: t('aiest.toast.start_first', {
            defaultValue: 'Start the estimate before jumping ahead',
          }),
        });
        return;
      }
      goto(id);
    },
    [stage, runId, goto, addToast, t],
  );

  // Advance through the confirm gate, kicking off the next stage's work.
  const goNext = useCallback(async () => {
    if (!runId) return;
    switch (stage) {
      case 'source':
        await confirmStageM.mutateAsync('source');
        goto('grouping');
        break;
      case 'grouping':
        await confirmStageM.mutateAsync('grouping');
        goto('matching');
        runMatchM.mutate();
        break;
      case 'matching':
        await confirmStageM.mutateAsync('matching');
        goto('assembly');
        break;
      default:
        break;
    }
  }, [runId, stage, confirmStageM, runMatchM, goto]);

  const goBack = useCallback(() => {
    const idx = STAGE_INDEX[stage];
    if (idx > 1) {
      const prev = STAGES.find((s) => s.index === idx - 1);
      if (prev) setStage(prev.id);
    }
  }, [stage]);

  // ── Per-stage advance guards ───────────────────────────────────────
  const canStart = useMemo(() => {
    if (!projectId) return false;
    switch (sourceTab) {
      case 'text':
        return text.trim().length > 0;
      case 'files':
        return files.length > 0;
      case 'bim_model':
        return !!selectedModelId;
      case 'documents':
        return selectedDocIds.length > 0;
      default:
        return false;
    }
  }, [projectId, sourceTab, text, files, selectedModelId, selectedDocIds]);

  const canAdvance = useMemo(() => {
    switch (stage) {
      case 'source':
        return !!run?.detected_source && !isRunning;
      case 'grouping':
        return groups.some((g) => g.status !== 'skipped');
      case 'matching':
        return groups.some((g) => g.status === 'confirmed' || g.status === 'overridden');
      default:
        return false;
    }
  }, [stage, run, isRunning, groups]);

  const currentStageDef = STAGES.find((s) => s.id === stage) as StageDef;

  // ── Render: runs list ──────────────────────────────────────────────
  if (view === 'list') {
    return (
      <div className="space-y-5 animate-fade-in">
        <PageHeader
          srTitle={t('nav.ai_estimator', { defaultValue: 'AI Estimate Builder' })}
          subtitle={t('aiest.subtitle', {
            defaultValue:
              'A full AI-driven estimate from any source. The agent groups quantities and finds catalogue rates, and you confirm every step.',
          })}
        />
        <IntroBanner />
        <AiStatusBanner readiness={readiness} />
        <RunsList
          runs={runsQ.data?.runs ?? []}
          loading={runsQ.isLoading}
          error={runsQ.isError ? (runsQ.error as Error).message : null}
          onRetry={() => runsQ.refetch()}
          locale={locale}
          onNew={openWizardNew}
          onOpen={openRun}
        />
      </div>
    );
  }

  // ── Render: wizard ─────────────────────────────────────────────────
  const hasRun = !!runId;

  return (
    <ScoreThresholdsProvider value={meta.thresholds}>
    <div className="space-y-5 animate-fade-in">
      <PageHeader
        srTitle={t('nav.ai_estimator', { defaultValue: 'AI Estimate Builder' })}
        subtitle={t('aiest.subtitle', {
          defaultValue:
            'A full AI-driven estimate from any source. The agent groups quantities and finds catalogue rates, and you confirm every step.',
        })}
        actions={
          <Button
            variant="ghost"
            size="sm"
            icon={<ArrowLeft className="h-4 w-4" />}
            onClick={backToList}
          >
            {t('aiest.wizard.back_to_runs', { defaultValue: 'All estimates' })}
          </Button>
        }
      />
      <AiStatusBanner readiness={readiness} />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[240px_1fr_300px]">
        {/* Left rail */}
        <aside className="lg:sticky lg:top-4 lg:self-start">
          <Card padding="sm">
            <StageRail current={stage} furthest={furthest} onJump={jumpTo} />
          </Card>
        </aside>

        {/* Active stage panel */}
        <section>
          <Card padding="lg" className="flex min-h-[480px] flex-col">
            <PanelHeader stage={currentStageDef} />

            <div className="flex-1 py-6">
              {/* Stage 1 */}
              {stage === 'source' && !hasRun && (
                <Stage1Intake
                  projectId={projectId}
                  sourceKind={sourceTab}
                  onSourceKind={setSourceTab}
                  text={text}
                  onText={setText}
                  files={files}
                  onFiles={setFiles}
                  bimModels={modelsQ.data ?? []}
                  bimModelsLoading={modelsQ.isLoading}
                  selectedModelId={selectedModelId}
                  onSelectModel={setSelectedModelId}
                  documents={docsQ.data ?? []}
                  selectedDocIds={selectedDocIds}
                  onToggleDoc={(id) =>
                    setSelectedDocIds((prev) =>
                      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
                    )
                  }
                  canStart={canStart}
                  starting={startRunM.isPending}
                  onStart={() => startRunM.mutate()}
                  textSlot={
                    <IntakePanel
                      projectId={projectId ?? ''}
                      initialText={text}
                      region={project?.region || undefined}
                      currency={project?.currency || undefined}
                      onFinished={onIntakeFinished}
                    />
                  }
                />
              )}
              {stage === 'source' && hasRun && isRunning && (
                <Analyzing
                  label={t('aiest.wizard.analyzing', {
                    defaultValue: 'Reading and classifying your source...',
                  })}
                />
              )}
              {stage === 'source' &&
                hasRun &&
                !isRunning &&
                run?.detected_source &&
                run.suggested_config && (
                  <Stage1Confirm
                    run={run}
                    detected={run.detected_source}
                    config={run.suggested_config}
                    catalogues={cataloguesQ.data ?? []}
                    constructionStages={meta.constructionStages}
                    edits={configEdits}
                    onChange={(patch) => setConfigEdits((prev) => ({ ...prev, ...patch }))}
                  />
                )}

              {/* Stage 2 */}
              {stage === 'grouping' &&
                (groupsQ.isError ? (
                  <InlineErrorRetry
                    message={(groupsQ.error as Error).message}
                    onRetry={() => groupsQ.refetch()}
                  />
                ) : (
                  <Stage2Groups
                    runId={runId!}
                    groups={groups}
                    loading={groupsQ.isLoading || isRunning}
                    savingId={savingGroupId}
                    onEdit={(groupId, patch) => updateGroupM.mutate({ groupId, patch })}
                    onMerge={(groupIds) => mergeGroupsM.mutate(groupIds)}
                    merging={mergeGroupsM.isPending}
                  />
                ))}

              {/* Stage 3 */}
              {stage === 'matching' && groupsQ.isError && (
                <InlineErrorRetry
                  message={(groupsQ.error as Error).message}
                  onRetry={() => groupsQ.refetch()}
                />
              )}
              {stage === 'matching' && !groupsQ.isError && (
                <Stage3Match
                  runId={runId!}
                  groups={groups}
                  loading={groupsQ.isLoading}
                  matching={runMatchM.isPending}
                  locale={locale}
                  aiConnected={progressQ.data?.ai_connected ?? readiness.llmReady}
                  highThreshold={groupsQ.data?.confidence_high_threshold ?? meta.thresholds.high}
                  matchGroupCap={meta.matchGroupCap}
                  onAccept={(groupId, candidateId) =>
                    confirmGroupM.mutate({ groupId, candidateId })
                  }
                  onSkip={(groupId) =>
                    updateGroupM.mutate({ groupId, patch: { status: 'skipped' } })
                  }
                  onRematch={(groupId, useAgent) =>
                    rematchGroupM.mutate({ groupId, useAgent })
                  }
                  rematchingId={rematchingId}
                  onBulkAccept={(threshold) => bulkConfirmM.mutate(threshold)}
                  bulkPending={bulkConfirmM.isPending}
                />
              )}

              {/* Stage 4 */}
              {stage === 'assembly' &&
                (previewQ.isError ? (
                  <InlineErrorRetry
                    message={(previewQ.error as Error).message}
                    onRetry={() => previewQ.refetch()}
                  />
                ) : (
                  <Stage4Review
                    preview={previewQ.data}
                    loading={previewQ.isLoading}
                    locale={locale}
                    applied={!!appliedBoqId}
                    appliedBoqId={appliedBoqId}
                    applyPending={applyM.isPending}
                    onApply={() => applyM.mutate()}
                  />
                ))}
            </div>

            {/* Footer nav (hidden on the pre-run intake) */}
            {hasRun && (
              <div className="flex items-center justify-between border-t border-border-light pt-4">
                <Button
                  variant="ghost"
                  icon={<ArrowLeft className="h-4 w-4" />}
                  disabled={STAGE_INDEX[stage] === 1}
                  onClick={goBack}
                >
                  {t('common.back', { defaultValue: 'Back' })}
                </Button>

                <div className="text-xs text-content-tertiary">
                  {t('aiest.wizard.step_counter', {
                    defaultValue: 'Step {{n}} / {{total}}',
                    n: STAGE_INDEX[stage],
                    total: STAGES.length,
                  })}
                </div>

                {stage !== 'assembly' ? (
                  <Button
                    variant="primary"
                    icon={<ArrowRight className="h-4 w-4" />}
                    iconPosition="right"
                    disabled={!canAdvance}
                    loading={confirmStageM.isPending}
                    onClick={goNext}
                  >
                    {stage === 'source'
                      ? t('aiest.wizard.to_groups', { defaultValue: 'Confirm & group' })
                      : stage === 'grouping'
                        ? t('aiest.wizard.to_matching', { defaultValue: 'Match rates' })
                        : t('aiest.wizard.to_review', { defaultValue: 'Review estimate' })}
                  </Button>
                ) : (
                  <Button
                    variant="secondary"
                    icon={<Check className="h-4 w-4" />}
                    onClick={backToList}
                  >
                    {t('aiest.wizard.finish', { defaultValue: 'Done' })}
                  </Button>
                )}
              </div>
            )}
          </Card>
        </section>

        {/* Right run-monitor */}
        <aside className="lg:sticky lg:top-4 lg:self-start">
          {hasRun ? (
            <RunMonitor runId={runId!} progress={progressQ.data} isPolling={isRunning} />
          ) : (
            <Card padding="sm">
              <p className="text-xs text-content-tertiary">
                {t('aiest.monitor.before_start', {
                  defaultValue:
                    'Pick a source and start the estimate to watch the agent work through each stage here.',
                })}
              </p>
            </Card>
          )}
        </aside>
      </div>
    </div>
    </ScoreThresholdsProvider>
  );
}

// ── Small local presentational helpers ───────────────────────────────

function IntroBanner() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  return (
    <DismissibleInfo
      storageKey="ai-estimator"
      title={t('ai-estimator.intro_title', { defaultValue: 'A guided estimate you can actually trust' })}
      links={[
        { label: t('ai-estimator.intro_link_boq', { defaultValue: 'Open BOQ' }), onClick: () => navigate('/boq') },
        { label: t('ai-estimator.intro_link_costs', { defaultValue: 'Cost database' }), onClick: () => navigate('/costs') },
        { label: t('ai-estimator.intro_link_validation', { defaultValue: 'Validation' }), onClick: () => navigate('/validation') },
      ]}
    >
      {t('ai-estimator.intro_body', {
        defaultValue:
          'Bring any source, a BIM or CAD model, a DWG or PDF takeoff, an Excel or GAEB import, photos or a written description. The agent detects the format, reads it into elements, groups quantities and finds catalogue rates with resource breakdowns, and you confirm each stage before it moves on. Every rate comes from the cost database, never invented, and the validated result writes straight into a BOQ.',
      })}
    </DismissibleInfo>
  );
}

function PanelHeader({ stage }: { stage: StageDef }) {
  const { t } = useTranslation();
  const Icon = stage.Icon;
  return (
    <div className="flex items-start gap-3 border-b border-border-light pb-4">
      <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue/10 text-oe-blue">
        <Icon className="h-5 w-5" />
      </span>
      <div>
        <div className="text-xs font-medium uppercase tracking-wide text-content-tertiary">
          {t('aiest.wizard.step_of', {
            defaultValue: 'Step {{n}} of {{total}}',
            n: stage.index,
            total: STAGES.length,
          })}
        </div>
        <h2 className="text-xl font-semibold text-content-primary">
          {t(stage.titleKey, { defaultValue: stage.titleFallback })}
        </h2>
        <p className="mt-0.5 text-sm text-content-secondary">
          {t(stage.blurbKey, { defaultValue: stage.blurbFallback })}
        </p>
      </div>
    </div>
  );
}

function Analyzing({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <div className="relative">
        <Loader2 className="h-8 w-8 animate-spin text-oe-blue" />
        <Wand2 className="absolute inset-0 m-auto h-3.5 w-3.5 text-oe-blue" />
      </div>
      <p className="text-sm text-content-secondary">{label}</p>
    </div>
  );
}
