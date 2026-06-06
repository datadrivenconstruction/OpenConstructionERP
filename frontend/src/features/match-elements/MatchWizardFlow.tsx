// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// /match-elements — guided 8-stage wizard.
//
// One focused panel per stage, one canonical step rail, plain-language
// explanation of what each stage does and why, live data/counts at
// every step, Back/Next + per-stage adjustment, and a final
// review→apply→done flow. Drives the real backend pipeline end-to-end
// (BIM elements → CWICR cost-code candidates with scores → BOQ rollup).
//
// Stages (exactly one rail — see STAGES):
//   1 Project        pick / confirm the project (accepts ?project=)
//   2 Source model   pick the BIM model to estimate
//   3 Catalogue      confirm cost catalogue + vector DB readiness
//   4 Scope          construction stage, net/gross, auto-confirm
//   5 Grouping       how elements roll up into estimable groups
//   6 Run match      execute the vector pipeline with live progress
//   7 Review         inspect candidates per group, adjust, confirm
//   8 Apply & done   dry-run BOQ rollup → write → summary

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  ArrowLeft,
  ArrowRight,
  Boxes,
  Check,
  CheckCircle2,
  ChevronRight,
  Database,
  ExternalLink,
  FileSpreadsheet,
  Info,
  Layers,
  Library,
  Loader2,
  MessageSquarePlus,
  PlayCircle,
  RefreshCw,
  Rocket,
  Search,
  SlidersHorizontal,
  Sparkles,
  Wrench,
} from 'lucide-react';

import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { projectsApi, type Project } from '@/features/projects/api';
import { Button } from '@/shared/ui/Button';
import { Card } from '@/shared/ui/Card';
import { BIMModelPicker } from '@/shared/ui/BIMModelPicker';
import { DismissibleInfo, Breadcrumb } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';

import {
  matchElementsApi,
  CONSTRUCTION_STAGES,
  type ApplyPositionPreview,
  type ConstructionStage,
  type GroupSummary,
  type MatchSession,
} from './api';
import { QdrantHealthCard } from './QdrantHealthCard';
import { MatchProgressCard, type MatchProgressStatus } from './MatchProgressCard';
import { MatchDetailPanel } from './MatchDetailPanel';
import { GroupingPanel } from './GroupingPanel';
import {
  CataloguesPanelCard,
  fetchCatalogues,
  type Catalogue,
} from './CataloguesPanelCard';
// dead_button fix: these panels were built, styled and unit-tested but
// nothing reachable from the /match-elements route imported them, so the
// in-app paths the wizard's own copy points at (install a catalogue,
// install the embedder, view §10 analytics, manage the template library)
// led nowhere. They are now mounted in a collapsible "Setup & tools"
// section below so every documented control actually works.
import { EmbedderStatusCard } from './EmbedderStatusCard';
import { MatchAnalyticsCard } from './MatchAnalyticsCard';
import { TemplatesPanel } from './TemplatesPanel';

// ─────────────────────────────────────────────────────────────────────────
//  Stage model — the single source of truth for the one-and-only rail
// ─────────────────────────────────────────────────────────────────────────

type StageId =
  | 'model'
  | 'catalogue'
  | 'scope'
  | 'grouping'
  | 'run'
  | 'review'
  | 'apply';

interface StageDef {
  id: StageId;
  index: number;
  /** i18n key for the short rail label. */
  titleKey: string;
  /** English fallback for the rail label (defaultValue). */
  titleDefault: string;
  /** i18n key for the one-line "what & why" shown in the rail + panel header. */
  blurbKey: string;
  /** English fallback for the blurb (defaultValue). */
  blurbDefault: string;
  Icon: typeof Layers;
}

const STAGES: readonly StageDef[] = [
  {
    id: 'model',
    index: 1,
    titleKey: 'match.stage_model_title',
    titleDefault: 'Source model',
    blurbKey: 'match.stage_model_blurb',
    blurbDefault: 'Pick the BIM/CAD model whose elements get priced.',
    Icon: Boxes,
  },
  {
    id: 'catalogue',
    index: 2,
    titleKey: 'match.stage_catalogue_title',
    titleDefault: 'Cost catalogue',
    blurbKey: 'match.stage_catalogue_blurb',
    blurbDefault: 'Confirm the rate catalogue and vector search are ready.',
    Icon: Database,
  },
  {
    id: 'scope',
    index: 3,
    titleKey: 'match.stage_scope_title',
    titleDefault: 'Scope & rules',
    blurbKey: 'match.stage_scope_blurb',
    blurbDefault: 'Set construction stage, quantities and auto-confirm.',
    Icon: SlidersHorizontal,
  },
  {
    id: 'grouping',
    index: 4,
    titleKey: 'match.stage_grouping_title',
    titleDefault: 'Grouping',
    blurbKey: 'match.stage_grouping_blurb',
    blurbDefault: 'See how elements roll up into estimable groups.',
    Icon: Layers,
  },
  {
    id: 'run',
    index: 5,
    titleKey: 'match.stage_run_title',
    titleDefault: 'Run match',
    blurbKey: 'match.stage_run_blurb',
    blurbDefault: 'Embed every group and rank cost candidates.',
    Icon: PlayCircle,
  },
  {
    id: 'review',
    index: 6,
    titleKey: 'match.stage_review_title',
    titleDefault: 'Review',
    blurbKey: 'match.stage_review_blurb',
    blurbDefault: 'Inspect candidates, adjust and confirm matches.',
    Icon: Search,
  },
  {
    id: 'apply',
    index: 7,
    titleKey: 'match.stage_apply_title',
    titleDefault: 'Apply & finish',
    blurbKey: 'match.stage_apply_blurb',
    blurbDefault: 'Preview the BOQ rollup and write it to the project.',
    Icon: Rocket,
  },
] as const;

const STAGE_INDEX: Record<StageId, number> = STAGES.reduce(
  (acc, s) => {
    acc[s.id] = s.index;
    return acc;
  },
  {} as Record<StageId, number>,
);

// ─────────────────────────────────────────────────────────────────────────
//  Helpers
// ─────────────────────────────────────────────────────────────────────────

function fmtMoney(value: number | null | undefined, currency: string | null | undefined) {
  if (value == null) return '—';
  try {
    return new Intl.NumberFormat(undefined, {
      style: currency ? 'currency' : 'decimal',
      currency: currency || undefined,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    return `${value.toFixed(2)} ${currency ?? ''}`.trim();
  }
}

function StageRail({
  current,
  furthest,
  onJump,
}: {
  current: StageId;
  furthest: number;
  onJump: (id: StageId) => void;
}) {
  const { t } = useTranslation();
  return (
    <ol className="flex flex-col gap-1" aria-label={t('match.wizard.steps', { defaultValue: 'Wizard steps' })}>
      {STAGES.map((s) => {
        const isCurrent = s.id === current;
        const isDone = s.index < STAGE_INDEX[current];
        const reachable = s.index <= furthest;
        const Icon = isDone ? Check : s.Icon;
        return (
          <li key={s.id}>
            <button
              type="button"
              disabled={!reachable}
              onClick={() => reachable && onJump(s.id)}
              className={clsx(
                'group flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left transition-colors',
                isCurrent
                  ? 'bg-oe-blue/10 ring-1 ring-oe-blue/30'
                  : reachable
                    ? 'hover:bg-surface-muted'
                    : 'opacity-50 cursor-not-allowed',
              )}
              aria-current={isCurrent ? 'step' : undefined}
            >
              <span
                className={clsx(
                  'mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
                  isCurrent
                    ? 'bg-oe-blue text-white'
                    : isDone
                      ? 'bg-emerald-500 text-white'
                      : 'bg-surface-muted text-content-secondary',
                )}
              >
                {isDone ? <Check className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
              </span>
              <span className="min-w-0">
                <span
                  className={clsx(
                    'block text-sm font-medium',
                    isCurrent ? 'text-oe-blue' : 'text-content-primary',
                  )}
                >
                  {s.index}. {t(s.titleKey, { defaultValue: s.titleDefault })}
                </span>
                <span className="block text-xs text-content-secondary leading-snug">
                  {t(s.blurbKey, { defaultValue: s.blurbDefault })}
                </span>
              </span>
            </button>
          </li>
        );
      })}
    </ol>
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
          {t('match.wizard.step_counter', {
            defaultValue: 'Step {{n}} of {{total}}',
            n: stage.index,
            total: STAGES.length,
          })}
        </div>
        <h2 className="text-xl font-semibold text-content-primary">
          {t(stage.titleKey, { defaultValue: stage.titleDefault })}
        </h2>
        <p className="mt-0.5 text-sm text-content-secondary">
          {t(stage.blurbKey, { defaultValue: stage.blurbDefault })}
        </p>
      </div>
    </div>
  );
}

function StatTile({
  label,
  value,
  tone = 'default',
}: {
  label: string;
  value: string | number;
  tone?: 'default' | 'good' | 'warn';
}) {
  return (
    <div
      className={clsx(
        'rounded-lg border px-4 py-3',
        tone === 'good'
          ? 'border-emerald-200 bg-emerald-50 dark:border-emerald-900/50 dark:bg-emerald-900/20'
          : tone === 'warn'
            ? 'border-amber-200 bg-amber-50 dark:border-amber-900/50 dark:bg-amber-900/20'
            : 'border-border-light bg-surface-muted',
      )}
    >
      <div className="text-2xl font-semibold text-content-primary tabular-nums">{value}</div>
      <div className="text-xs text-content-secondary">{label}</div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────
//  Main wizard
// ─────────────────────────────────────────────────────────────────────────

export function MatchWizardFlow() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [searchParams] = useSearchParams();

  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const urlProject = searchParams.get('project');

  // ── Wizard navigation ───────────────────────────────────────────────
  const [stage, setStage] = useState<StageId>('model');
  const [furthest, setFurthest] = useState(1);

  const goto = useCallback((id: StageId) => {
    setStage(id);
    setFurthest((f) => Math.max(f, STAGE_INDEX[id]));
  }, []);

  // ── Wizard state ────────────────────────────────────────────────────
  const [projectId, setProjectId] = useState<string | null>(urlProject || activeProjectId);
  const [modelId, setModelId] = useState<string | null>(null);
  const [stageHint, setStageHint] = useState<ConstructionStage | ''>('');
  const [useNet, setUseNet] = useState(true);
  const [autoThreshold, setAutoThreshold] = useState(0.88);
  const [sessionId, setSessionId] = useState<string | null>(null);
  // Stage-3 user overrides for the bound cost catalogue + display currency.
  // ``catalogueId`` is a CWICR-v3 region string (e.g. "de", "us") OR null
  // to fall back to the project-region auto-bind. ``displayCurrency`` is
  // the ISO-4217 code the wizard renders rollup totals in — purely a
  // presentation override, conversion still happens at the rate-layer.
  const [catalogueId, setCatalogueId] = useState<string | null>(null);
  const [displayCurrency, setDisplayCurrency] = useState<string | null>(null);
  const [matchStatus, setMatchStatus] = useState<MatchProgressStatus>('running');
  const [matchError, setMatchError] = useState<string | null>(null);
  const [matchStarted, setMatchStarted] = useState(false);
  const [detailGroup, setDetailGroup] = useState<GroupSummary | null>(null);
  // dead_button fix: the tenant-scoped template library (TemplatesPanel)
  // had no in-app trigger — this state opens it from the "Setup & tools"
  // section. Slide-over closes itself on Escape / backdrop click.
  const [showTemplates, setShowTemplates] = useState(false);
  const [applyResult, setApplyResult] = useState<{
    written: boolean;
    boqId: string | null;
    count: number;
    total: number;
    currency: string | null;
    positions: ApplyPositionPreview[];
  } | null>(null);

  // Clearing the picked model / live session / progress / results when
  // the project changes is mandatory: every one of those is scoped to a
  // single project on the backend. Without this, switching project (via
  // the stage-1 picker OR a ?project= deep-link change) would carry the
  // *previous* project's session forward — Build groups / Review /
  // Apply would then operate on, and write a BOQ into, the wrong
  // project. The wizard is also rewound to stage 1 so the user re-walks
  // the prerequisites for the new project instead of landing on a stage
  // whose prerequisites are now stale.
  const resetForProject = useCallback(() => {
    setModelId(null);
    setSessionId(null);
    setMatchStarted(false);
    setMatchStatus('running');
    setMatchError(null);
    setDetailGroup(null);
    setApplyResult(null);
    setStage('model');
    setFurthest(1);
  }, []);

  // Keep the deep-link / global store in sync with the wizard's project.
  // A genuine project change (not the initial mount) resets all
  // downstream state so nothing stale survives the switch.
  useEffect(() => {
    if (urlProject && urlProject !== projectId) {
      setProjectId(urlProject);
      resetForProject();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlProject]);

  // ── Queries ─────────────────────────────────────────────────────────
  const projectsQ = useQuery({ queryKey: ['projects-all'], queryFn: projectsApi.list });

  const project: Project | undefined = useMemo(
    () => projectsQ.data?.find((p) => p.id === projectId),
    [projectsQ.data, projectId],
  );

  const modelsQ = useQuery({
    enabled: !!projectId,
    queryKey: ['match-bim-models', projectId],
    queryFn: () => matchElementsApi.listBIMModels(projectId!),
  });

  // Catalogues feed the stage-3 picker. We only let users pick from
  // ``loaded`` catalogues — picking ``available`` would queue a match
  // against an empty Qdrant collection and fail at run time. The user
  // installs missing catalogues via the existing CataloguesPanelCard
  // before the picker can offer them.
  const cataloguesQ = useQuery({
    queryKey: ['match-catalogues-v3'],
    queryFn: fetchCatalogues,
    staleTime: 60_000,
  });
  const loadedCatalogues: Catalogue[] = useMemo(
    () => (cataloguesQ.data?.catalogues ?? []).filter((c) => c.install_status === 'loaded'),
    [cataloguesQ.data],
  );

  // Auto-pre-select the catalogue whose region matches the project's
  // region (case-insensitive) the first time we have both lists. Without
  // this the dropdown would show "—" until the user manually picks one,
  // even though auto_bind would have used the same row anyway.
  useEffect(() => {
    if (catalogueId || !project?.region || loadedCatalogues.length === 0) return;
    const want = String(project.region).toLowerCase();
    const hit = loadedCatalogues.find(
      (c) =>
        c.region.toLowerCase() === want ||
        c.country_iso.toLowerCase() === want,
    );
    if (hit) setCatalogueId(hit.region);
  }, [catalogueId, project?.region, loadedCatalogues]);

  useEffect(() => {
    if (displayCurrency || !project?.currency) return;
    setDisplayCurrency(project.currency);
  }, [displayCurrency, project?.currency]);


  const groupsQ = useQuery({
    enabled: !!sessionId && (stage === 'grouping' || stage === 'review'),
    queryKey: ['match-groups', sessionId, stage],
    queryFn: () => matchElementsApi.listGroups(sessionId!, { limit: 300 }),
    refetchInterval: stage === 'review' && matchStatus === 'running' ? 2500 : false,
  });

  // ── Mutations ───────────────────────────────────────────────────────
  const createSessionM = useMutation({
    mutationFn: () =>
      matchElementsApi.createSession({
        project_id: projectId!,
        source: 'bim',
        bim_model_id: modelId,
        name: `${project?.name ?? 'Match'} - ${new Date().toLocaleDateString()}`,
        construction_stage: stageHint || null,
        use_net_quantities: useNet,
        auto_confirm_threshold: autoThreshold,
        catalogue_id: catalogueId,
      }),
    onSuccess: (s: MatchSession) => {
      setSessionId(s.id);
      qc.invalidateQueries({ queryKey: ['match-groups'] });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('match.wizard.sessionFailed', {
          defaultValue: 'Could not create match session',
        }),
        message: e.message,
      }),
  });

  const runMatchM = useMutation({
    mutationFn: () =>
      matchElementsApi.runMatch(sessionId!, { method: 'vector', max_groups: 200, top_k: 10 }),
    onError: (e: Error) => {
      setMatchStatus('error');
      setMatchError(e.message);
    },
  });

  const bulkConfirmM = useMutation({
    mutationFn: () =>
      matchElementsApi.bulkConfirm(sessionId!, { threshold: autoThreshold }),
    onSuccess: (r) => {
      // "0 confirmed" is not a success — it means nothing cleared the
      // threshold. Surfacing it green is misleading; tell the user the
      // actionable next step (lower the auto-confirm score) instead.
      if (r.confirmed_count > 0) {
        addToast({
          type: 'success',
          title: t('match.wizard.bulkConfirmed', {
            defaultValue: '{{n}} groups confirmed',
            n: r.confirmed_count,
          }),
        });
      } else {
        addToast({
          type: 'info',
          title: t('match.wizard.bulkConfirmedNone', {
            defaultValue: 'No groups met the auto-confirm score',
          }),
          message: t('match.wizard.bulkConfirmedNoneBody', {
            defaultValue:
              'Lower the auto-confirm score in Scope & rules, or confirm matches individually below.',
          }),
        });
      }
      qc.invalidateQueries({ queryKey: ['match-groups'] });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('match.wizard.confirmFailed', {
          defaultValue: 'Bulk confirm failed',
        }),
        message: e.message,
      }),
  });

  const applyM = useMutation({
    mutationFn: (dryRun: boolean) =>
      matchElementsApi.apply(sessionId!, { dry_run: dryRun }),
    onSuccess: (r, dryRun) => {
      setApplyResult({
        written: !dryRun,
        boqId: r.boq_id,
        count: r.positions_created,
        total: r.grand_total,
        currency: r.currency,
        positions: r.positions ?? [],
      });
      if (!dryRun) {
        addToast({
          type: 'success',
          title: t('match.wizard.applied', {
            defaultValue: '{{n}} BOQ positions written',
            n: r.positions_created,
          }),
        });
      }
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('match.wizard.applyFailed', {
          defaultValue: 'Apply failed',
        }),
        message: e.message,
      }),
  });

  // PATCH an existing session with the latest scope knobs. Without this,
  // going Back from Grouping to Scope, changing the construction stage /
  // net-gross / auto-confirm threshold, then Next would silently keep
  // the *original* session config — the user's edits would be a no-op
  // and the match would run with stale settings. Re-create is wrong
  // here (it would orphan groups/confirmations); a PATCH is the correct,
  // cheap fix. Failure is surfaced but does not block navigation.
  const updateSessionM = useMutation({
    mutationFn: (id: string) =>
      matchElementsApi.updateSession(id, {
        bim_model_id: modelId,
        construction_stage: stageHint || null,
        use_net_quantities: useNet,
        auto_confirm_threshold: autoThreshold,
        catalogue_id: catalogueId,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['match-groups'] });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('match.wizard.sessionUpdateFailed', {
          defaultValue: 'Could not update match settings',
        }),
        message: e.message,
      }),
  });

  // ── Stage transitions ───────────────────────────────────────────────
  // Non-blocking: fire-and-forget the create / update mutation so the
  // user moves to the next stage immediately. The GroupingPanel reads
  // the session id off the `sessionId` state which onSuccess populates,
  // and renders its own loader while the request is in flight. If
  // creation fails the mutation's onError toasts — the user is on the
  // grouping stage with the loader still spinning and can retry.
  const ensureSessionThen = useCallback(
    (next: StageId) => {
      if (!sessionId) {
        if (!createSessionM.isPending) {
          createSessionM.mutate();
        }
      } else {
        updateSessionM.mutate(sessionId);
      }
      goto(next);
    },
    [sessionId, createSessionM, updateSessionM, goto],
  );

  // ── Eager prep — warm the session + grouping cache when the model
  // is picked, so the user lands on the Grouping stage with data
  // already in hand instead of staring at a spinner.
  useEffect(() => {
    if (!projectId || !modelId || sessionId) return;
    if (createSessionM.isPending) return;
    createSessionM.mutate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, modelId, sessionId]);

  const startMatch = useCallback(async () => {
    if (!sessionId) return;
    setMatchStarted(true);
    setMatchStatus('running');
    setMatchError(null);
    try {
      await runMatchM.mutateAsync();
      setMatchStatus('done');
    } catch {
      /* handled in onError */
    }
  }, [sessionId, runMatchM]);

  // Auto-kick the match when the user lands on the Run stage.
  useEffect(() => {
    if (stage === 'run' && sessionId && !matchStarted) {
      void startMatch();
    }
  }, [stage, sessionId, matchStarted, startMatch]);

  // ── Derived counts ──────────────────────────────────────────────────
  const groups = groupsQ.data?.groups ?? [];
  const groupSummary = groupsQ.data?.summary ?? {};
  const matchedCount =
    (groupSummary.confirmed ?? 0) +
    (groupSummary.suggested ?? 0) +
    (groupSummary.applied ?? 0);

  const currentStageDef = STAGES.find((s) => s.id === stage)!;

  // ── Per-stage navigation guards ─────────────────────────────────────
  const canAdvance = useMemo(() => {
    switch (stage) {
      case 'model':
        return !!modelId;
      case 'catalogue':
        return true;
      case 'scope':
        return true;
      case 'grouping':
        return !!sessionId && groups.length > 0;
      case 'run':
        return matchStatus === 'done';
      case 'review':
        return true;
      default:
        return false;
    }
  }, [stage, projectId, modelId, sessionId, groups.length, matchStatus]);

  const goNext = useCallback(async () => {
    switch (stage) {
      case 'model':
        goto('catalogue');
        break;
      case 'catalogue':
        goto('scope');
        break;
      case 'scope':
        ensureSessionThen('grouping');
        break;
      case 'grouping':
        goto('run');
        break;
      case 'run':
        goto('review');
        break;
      case 'review':
        goto('apply');
        break;
      default:
        break;
    }
  }, [stage, goto, ensureSessionThen]);

  const goBack = useCallback(() => {
    const idx = STAGE_INDEX[stage];
    if (idx > 1) {
      const prev = STAGES.find((s) => s.index === idx - 1);
      if (prev) setStage(prev.id);
    }
  }, [stage]);

  // Hard prerequisite for *landing on* a stage. ``furthest`` only tracks
  // how far the user has been; it can outrun reality (e.g. they reached
  // Review, then went Back and changed the model, invalidating the
  // session). Without this guard a rail click could drop the user onto
  // Run / Review / Apply with no session — every panel there would
  // render empty and the match would silently never start. We let the
  // user jump *backward* freely (re-picking is the whole point of a
  // rail) but block forward jumps that skip a missing prerequisite.
  const stagePrereqMet = useCallback(
    (id: StageId): boolean => {
      switch (id) {
        case 'model':
          return !!projectId;
        case 'catalogue':
        case 'scope':
          return !!modelId;
        case 'grouping':
        case 'run':
        case 'review':
        case 'apply':
          return !!sessionId;
        default:
          return true;
      }
    },
    [projectId, modelId, sessionId],
  );

  const jumpTo = useCallback(
    (id: StageId) => {
      const target = STAGE_INDEX[id];
      const here = STAGE_INDEX[stage];
      // Backward / same → always allowed.
      if (target <= here) {
        setStage(id);
        return;
      }
      if (!stagePrereqMet(id)) {
        addToast({
          type: 'info',
          title: t('match.wizard.jumpBlocked', {
            defaultValue: 'Finish the earlier steps first',
          }),
          message: t('match.wizard.jumpBlockedBody', {
            defaultValue:
              'That step needs the steps before it completed. Use Next to walk through them.',
          }),
        });
        return;
      }
      goto(id);
    },
    [stage, stagePrereqMet, goto, addToast, t],
  );

  // ─────────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-5 animate-fade-in">
      {/* Canonical top block - module name + icon live in the global top app
          bar; the page renders only its subtitle on the left. */}
      <Breadcrumb items={[{ label: t('nav.match_elements', { defaultValue: 'CAD Match → Cost' }) }]} />
      <PageHeader
        srTitle={t('match.wizard.title', { defaultValue: 'CAD Match → Cost' })}
        subtitle={t('match.wizard.subtitle', {
          defaultValue:
            'A guided flow that turns a BIM model into a priced bill of quantities.',
        })}
      />

      <DismissibleInfo
        storageKey="match-elements"
        title={t('info.match-elements.title', { defaultValue: 'CAD Match → Cost' })}
      >
        {t('info.match-elements.body', {
          defaultValue:
            'Price a BIM or CAD model by matching its elements against a regional cost catalogue, then write the result straight into the project as a bill of quantities. The wizard groups elements, ranks cost candidates with semantic search, and lets you confirm matches before they become real BOQ positions with quantities and rates.',
        })}
      </DismissibleInfo>

      {/* Beta · feedback-wanted banner. /match-elements is the newest
          top-level feature and still has rough edges (catalogue install
          retries, occasional stale-cache shape mismatches, ranker
          tuning). The banner sets the right expectation and gives a
          1-click path to file an issue against the public repo. */}
      <div className="flex flex-wrap items-center gap-2.5 rounded-xl border border-amber-200/60 bg-gradient-to-r from-amber-50/80 via-white to-white px-3 py-2 shadow-sm dark:border-amber-800/40 dark:from-amber-950/20 dark:via-surface-primary dark:to-surface-primary">
        <span className="inline-flex shrink-0 items-center gap-1 rounded border border-amber-300/60 bg-amber-100/80 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider text-amber-900 dark:border-amber-700/40 dark:bg-amber-900/40 dark:text-amber-100">
          <Sparkles className="h-2.5 w-2.5" />
          {t('match_elements.beta_badge', { defaultValue: 'Beta' })}
        </span>
        <p className="min-w-0 flex-1 text-xs leading-snug text-content-secondary">
          {t('match_elements.beta_blurb', {
            defaultValue:
              'CAD Match → Cost is a new section and still has rough edges. Found a bug or have an idea? Please file an issue - every report tightens the next release.',
          })}
        </p>
        <a
          href="https://github.com/datadrivenconstruction/OpenConstructionERP/issues/new?labels=match-elements&template=bug_report.yml"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex shrink-0 items-center gap-1 rounded-full border border-amber-300/60 bg-white/90 px-2.5 py-1 text-[11px] font-semibold text-amber-900 shadow-sm transition-all hover:-translate-y-px hover:bg-amber-50 dark:border-amber-700/40 dark:bg-surface-primary/80 dark:text-amber-100 dark:hover:bg-amber-900/30"
        >
          <MessageSquarePlus className="h-3 w-3" />
          {t('match_elements.beta_cta', { defaultValue: 'Open an issue' })}
          <ExternalLink className="h-2.5 w-2.5 opacity-70" />
        </a>
      </div>

      {/* Vector-DB readiness — probed up front so the user knows whether
          semantic search is available before investing time in setup.
          QdrantHealthCard self-hides when Qdrant is healthy (stage 3
          carries the green confirmation) and renders the actionable
          one-click installer card the moment it is unreachable. */}
      <QdrantHealthCard />

      {/* Setup & tools — dead_button fix. These panels were built and
          tested but never reachable from the route: the embedder install
          card, the cost-catalogue install panel (the very place the
          wizard's stage-3 copy and the Qdrant toast tell users to go),
          the §10 match-analytics dashboard, and a launcher for the
          tenant-scoped template library. Collapsed by default so the
          first-screen wizard stays tidy; one click reveals every
          previously-orphaned control. */}
      <details className="group rounded-xl border border-border-light bg-surface-primary">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-medium text-content-primary">
          <Wrench className="h-4 w-4 shrink-0 text-oe-blue" />
          {t('match.wizard.setupTools', {
            defaultValue: 'Setup & tools - language model, catalogues, analytics, templates',
          })}
          <ChevronRight className="ml-auto h-4 w-4 text-content-tertiary transition-transform group-open:rotate-90" />
        </summary>
        <div className="space-y-3 border-t border-border-light px-4 py-3">
          {/* Free language-model (BGE-M3) readiness + one-command install. */}
          <EmbedderStatusCard />
          {/* Cost-catalogue install — pinned to the active project's region
              so the matching catalogue is one click away. */}
          <CataloguesPanelCard preferredRegion={project?.region ?? null} />
          {/* §10 production observability for matches in this project. */}
          <MatchAnalyticsCard projectId={projectId} />
          {/* Launcher for the tenant-scoped template library slide-over. */}
          <button
            type="button"
            onClick={() => setShowTemplates(true)}
            className="inline-flex items-center gap-2 rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm font-medium text-content-primary transition-colors hover:bg-surface-muted"
          >
            <Library className="h-4 w-4 text-indigo-500" />
            {t('match.wizard.openTemplateLibrary', {
              defaultValue: 'Open template library',
            })}
          </button>
        </div>
      </details>

      {/* Plain-language "how it works" — collapsed by default to keep the
          first-screen wizard tidy; one click opens the full 8-stage tour. */}
      <details className="group rounded-xl border border-border-light bg-surface-primary">
        <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-medium text-content-primary">
          <Info className="h-4 w-4 shrink-0 text-oe-blue" />
          {t('match.wizard.howItWorks', {
            defaultValue: 'How matching works - read this first',
          })}
          <ChevronRight className="ml-auto h-4 w-4 text-content-tertiary transition-transform group-open:rotate-90" />
        </summary>
        <div className="space-y-2 border-t border-border-light px-4 py-3 text-sm text-content-secondary">
          <p>
            {t('match.wizard.howItWorksIntro', {
              defaultValue:
                'This wizard turns a BIM/CAD model into a priced bill of quantities. Every model element is grouped, then each group is searched against a regional cost catalogue using multilingual semantic (vector) + keyword + rule-based matching. You review the ranked candidates, confirm them, and the wizard writes a real BOQ with real cost in the project currency.',
            })}
          </p>
          <ol className="grid gap-1.5 sm:grid-cols-2">
            {STAGES.map((s) => (
              <li key={s.id} className="flex gap-2">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-oe-blue/10 text-[11px] font-semibold text-oe-blue">
                  {s.index}
                </span>
                <span>
                  <span className="font-medium text-content-primary">
                    {t(s.titleKey, { defaultValue: s.titleDefault })}
                  </span>
                  {' - '}
                  {t(s.blurbKey, { defaultValue: s.blurbDefault })}
                </span>
              </li>
            ))}
          </ol>
          <p className="text-xs text-content-tertiary">
            {t('match.wizard.howItWorksVector', {
              defaultValue:
                'Semantic search needs a running vector database (Qdrant). If it is offline, matching still works using keyword + rule-based scoring - accuracy is just lower. The status above tells you which mode you are in.',
            })}
          </p>
        </div>
      </details>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[260px_1fr]">
        {/* The ONE step rail */}
        <aside className="lg:sticky lg:top-4 lg:self-start">
          <Card padding="sm">
            <StageRail current={stage} furthest={furthest} onJump={jumpTo} />
          </Card>
        </aside>

        {/* Active stage panel */}
        <section>
          <Card padding="lg" className="min-h-[480px] flex flex-col">
            <PanelHeader stage={currentStageDef} />

            <div className="flex-1 py-6">
              {/* ── 1. Source model ─────────────────────────────────── */}
              {stage === 'model' && (
                <div>
                  <p className="mb-4 text-sm text-content-secondary">
                    {t('match.wizard.modelHelp', {
                      defaultValue:
                        'Choose the BIM/CAD model to price. Every element in it becomes part of the estimate.',
                    })}
                  </p>
                  <BIMModelPicker
                    models={(modelsQ.data ?? []).map((m) => ({
                      id: m.id,
                      name: m.name,
                      model_format: m.model_format,
                      element_count: m.element_count,
                      storey_count: m.storey_count,
                      status: m.status,
                      created_at: m.created_at,
                    }))}
                    activeModelId={modelId}
                    onSelect={setModelId}
                    isLoading={modelsQ.isLoading}
                    uploadHref={projectId ? `/bim?project=${projectId}` : '/bim'}
                  />
                  {modelsQ.isError ? (
                    <div className="mt-4 rounded-lg border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800 dark:border-rose-900/50 dark:bg-rose-900/20 dark:text-rose-200">
                      <div className="font-medium">
                        {t('match.wizard.modelsError', {
                          defaultValue: 'Could not load BIM models',
                        })}
                      </div>
                      <p className="mt-1 text-xs opacity-90 break-words">
                        {String(
                          (modelsQ.error as Error | null)?.message ??
                            modelsQ.error ??
                            '',
                        )}
                      </p>
                      <Button
                        className="mt-3"
                        variant="secondary"
                        size="sm"
                        icon={<RefreshCw className="h-4 w-4" />}
                        onClick={() => modelsQ.refetch()}
                      >
                        {t('common.retry', { defaultValue: 'Retry' })}
                      </Button>
                    </div>
                  ) : (
                    !modelsQ.isLoading &&
                    (modelsQ.data ?? []).length === 0 && (
                      <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-900/20 dark:text-amber-200">
                        {t('match.wizard.noModels', {
                          defaultValue:
                            'This project has no ready BIM models yet. Upload and convert one first.',
                        })}{' '}
                        <Link
                          className="font-medium underline"
                          to={`/bim?project=${projectId}`}
                        >
                          {t('match.wizard.goToBim', {
                            defaultValue: 'Go to BIM models',
                          })}
                        </Link>
                      </div>
                    )
                  )}
                </div>
              )}

              {/* ── 3. Cost catalogue ───────────────────────────────── */}
              {stage === 'catalogue' && (
                <div className="space-y-4">
                  <p className="text-sm text-content-secondary">
                    {t('match.wizard.catalogueHelp', {
                      defaultValue:
                        'Matching ranks every group against a cost catalogue using a multilingual semantic search. Pick the catalogue and display currency; the project region pre-selects a sensible default.',
                    })}
                  </p>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <div>
                      <label className="mb-1.5 block text-sm font-medium text-content-primary">
                        {t('match.wizard.catalogueLabel', { defaultValue: 'Cost catalogue' })}
                      </label>
                      <select
                        value={catalogueId ?? ''}
                        disabled={cataloguesQ.isLoading}
                        onChange={(e) => setCatalogueId(e.target.value || null)}
                        className="w-full rounded-lg border border-border-light bg-surface-elevated px-3 py-2 text-sm disabled:opacity-60"
                      >
                        <option value="">
                          {t('match.wizard.catalogueAuto', {
                            defaultValue: 'Auto (from project region: {{region}})',
                            region: project?.region || '—',
                          })}
                        </option>
                        {loadedCatalogues.map((c) => (
                          // Key on region+collection: several regions can map
                          // to the same shared collection (e.g. all English
                          // regions bind to cwicr_en_v3), so c.collection
                          // alone collided and triggered React duplicate-key
                          // warnings. The option value stays c.region.
                          <option key={`${c.region}:${c.collection}`} value={c.region}>
                            {c.city ? `${c.city}, ` : ''}
                            {c.region.toUpperCase()} — {c.language} · {c.currency}
                          </option>
                        ))}
                      </select>
                      <p className="mt-1 text-xs text-content-tertiary">
                        {cataloguesQ.isError
                          ? t('match.wizard.catalogueLoadError', {
                              defaultValue:
                                'Could not list catalogues. Check that the cost service is reachable.',
                            })
                          : loadedCatalogues.length === 0
                            ? t('match.wizard.catalogueNoneLoaded', {
                                defaultValue:
                                  'No catalogues loaded yet - install one from the Cost catalogues panel on /match-elements home.',
                              })
                            : t('match.wizard.catalogueHelpInline', {
                                defaultValue:
                                  'Only loaded catalogues are listed. Install more from the catalogues panel.',
                              })}
                      </p>
                    </div>

                    <div>
                      <label className="mb-1.5 block text-sm font-medium text-content-primary">
                        {t('match.wizard.displayCurrencyLabel', {
                          defaultValue: 'Display currency',
                        })}
                      </label>
                      <select
                        value={displayCurrency ?? ''}
                        onChange={(e) => setDisplayCurrency(e.target.value || null)}
                        className="w-full rounded-lg border border-border-light bg-surface-elevated px-3 py-2 text-sm"
                      >
                        {(() => {
                          // Build a de-duplicated currency menu: the
                          // project's own currency, every loaded
                          // catalogue's currency, then a short list of
                          // common globals. ``Set`` preserves the order
                          // we add in, so the first occurrence wins.
                          const opts: string[] = [];
                          const seen = new Set<string>();
                          const push = (cur: string | null | undefined) => {
                            if (!cur) return;
                            const k = cur.trim().toUpperCase();
                            if (!k || seen.has(k)) return;
                            seen.add(k);
                            opts.push(k);
                          };
                          push(project?.currency);
                          loadedCatalogues.forEach((c) => push(c.currency));
                          [
                            'EUR',
                            'USD',
                            'GBP',
                            'CHF',
                            'PLN',
                            'CZK',
                            'CAD',
                            'AUD',
                            'JPY',
                            'CNY',
                            'BRL',
                            'INR',
                            'ZAR',
                            'TRY',
                            'AED',
                            'SAR',
                            'NOK',
                            'SEK',
                            'DKK',
                          ].forEach(push);
                          return opts.map((c) => (
                            <option key={c} value={c}>
                              {c}
                            </option>
                          ));
                        })()}
                      </select>
                      <p className="mt-1 text-xs text-content-tertiary">
                        {t('match.wizard.displayCurrencyHelp', {
                          defaultValue:
                            'Rollup totals are shown in this currency. The match itself runs against the catalogue native currency.',
                        })}
                      </p>
                    </div>
                  </div>

                  <QdrantHealthCard alwaysShow />

                  <div className="rounded-lg border border-border-light bg-surface-muted p-4 text-sm text-content-secondary">
                    {t('match.wizard.catalogueNote', {
                      defaultValue:
                        'If your region has no dedicated catalogue, pick a multilingual one (e.g. EN) - the search model is multilingual and still returns real candidates.',
                    })}
                  </div>
                </div>
              )}

              {/* ── 4. Scope & rules ────────────────────────────────── */}
              {stage === 'scope' && (
                <div className="space-y-6">
                  <p className="text-sm text-content-secondary">
                    {t('match.wizard.scopeHelp', {
                      defaultValue:
                        'Narrow the search and decide how confidently a match is accepted automatically.',
                    })}
                  </p>

                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-content-primary">
                      {t('match.wizard.stageHint', {
                        defaultValue: 'Construction stage (optional)',
                      })}
                    </label>
                    <select
                      value={stageHint}
                      onChange={(e) => setStageHint(e.target.value as ConstructionStage | '')}
                      className="w-full max-w-sm rounded-lg border border-border-light bg-surface-elevated px-3 py-2 text-sm"
                    >
                      <option value="">
                        {t('match.wizard.allStages', { defaultValue: 'All stages (no filter)' })}
                      </option>
                      {CONSTRUCTION_STAGES.map((cs) => (
                        <option key={cs} value={cs}>
                          {/* Reuse the already-translated 12-stage taxonomy
                              labels (aiest.stage_*). The match-elements enum
                              tokens are identical to the ai_estimator ones, so
                              the keys map 1:1 and stay translated in all 27
                              locales. Fall back to a humanised token only if a
                              key is somehow missing. */}
                          {t(`aiest.stage_${cs}`, {
                            defaultValue: cs
                              .replace(/^\d+_/, '')
                              .replace(/([a-z])([A-Z])/g, '$1 $2'),
                          })}
                        </option>
                      ))}
                    </select>
                    <p className="mt-1 text-xs text-content-tertiary">
                      {t('match.wizard.stageHintNote', {
                        defaultValue:
                          'Pins candidates to one phase of work. Leave on “All stages” unless your model is single-trade.',
                      })}
                    </p>
                  </div>

                  <div>
                    <span className="mb-1.5 block text-sm font-medium text-content-primary">
                      {t('match.wizard.quantities', { defaultValue: 'Quantities' })}
                    </span>
                    <div className="flex gap-2">
                      {[
                        { v: true, l: t('match.wizard.netQty', { defaultValue: 'Net (deduct openings)' }) },
                        { v: false, l: t('match.wizard.grossQty', { defaultValue: 'Gross' }) },
                      ].map((opt) => (
                        <button
                          key={String(opt.v)}
                          type="button"
                          onClick={() => setUseNet(opt.v)}
                          className={clsx(
                            'rounded-lg border px-3 py-2 text-sm transition-colors',
                            useNet === opt.v
                              ? 'border-oe-blue bg-oe-blue/5 text-oe-blue'
                              : 'border-border-light hover:bg-surface-muted',
                          )}
                        >
                          {opt.l}
                        </button>
                      ))}
                    </div>
                  </div>

                  <div>
                    <label className="mb-1.5 block text-sm font-medium text-content-primary">
                      {t('match.wizard.autoConfirm', {
                        defaultValue: 'Auto-confirm above score',
                      })}{' '}
                      <span className="tabular-nums text-oe-blue">
                        {autoThreshold.toFixed(2)}
                      </span>
                    </label>
                    <input
                      type="range"
                      min={0.5}
                      max={0.99}
                      step={0.01}
                      value={autoThreshold}
                      onChange={(e) => setAutoThreshold(Number(e.target.value))}
                      className="w-full max-w-sm accent-oe-blue"
                    />
                    <p className="mt-1 text-xs text-content-tertiary">
                      {t('match.wizard.autoConfirmNote', {
                        defaultValue:
                          'Groups whose best candidate scores above this are confirmed automatically; the rest wait for your review.',
                      })}
                    </p>
                  </div>
                </div>
              )}

              {/* ── 5. Grouping ─────────────────────────────────────── */}
              {stage === 'grouping' && sessionId && (
                <GroupingPanel
                  sessionId={sessionId}
                  groupsQ={groupsQ}
                  updateSessionM={updateSessionM}
                />
              )}
              {stage === 'grouping' && !sessionId && (
                <div className="flex items-center gap-2 text-sm text-content-secondary">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t('match.wizard.buildingGroups', {
                    defaultValue: 'Building groups…',
                  })}
                </div>
              )}

              {/* ── 6. Run match ────────────────────────────────────── */}
              {stage === 'run' && (
                <div className="space-y-4">
                  <p className="text-sm text-content-secondary">
                    {t('match.wizard.runHelp', {
                      defaultValue:
                        'Each group is embedded with a multilingual model and ranked against the cost catalogue. This can take a minute on large models - progress is live below.',
                    })}
                  </p>
                  {!sessionId ? (
                    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-900/20 dark:text-amber-200">
                      <div className="font-medium">
                        {t('match.wizard.noSession', {
                          defaultValue: 'No match session yet',
                        })}
                      </div>
                      <p className="mt-1 text-xs opacity-90">
                        {t('match.wizard.noSessionHelp', {
                          defaultValue:
                            'The match could not start because the earlier steps were not completed. Go back to Scope & rules to build the session.',
                        })}
                      </p>
                      <Button
                        className="mt-3"
                        variant="secondary"
                        size="sm"
                        icon={<ArrowLeft className="h-4 w-4" />}
                        onClick={() => setStage('scope')}
                      >
                        {t('match.wizard.backToScope', {
                          defaultValue: 'Adjust scope',
                        })}
                      </Button>
                    </div>
                  ) : (
                    <MatchProgressCard
                      status={matchStatus}
                      errorMessage={matchError}
                      sessionId={sessionId}
                      onDone={() => {
                        qc.invalidateQueries({ queryKey: ['match-groups'] });
                        goto('review');
                      }}
                      onRetry={() => {
                        setMatchStarted(false);
                        void startMatch();
                      }}
                    />
                  )}
                </div>
              )}

              {/* ── 7. Review ───────────────────────────────────────── */}
              {stage === 'review' && (
                <div className="space-y-4">
                  <p className="text-sm text-content-secondary">
                    {t('match.wizard.reviewHelp', {
                      defaultValue:
                        'Open any group to see ranked cost candidates with scores. Confirm the right one, or accept all high-confidence matches at once.',
                    })}
                  </p>
                  <div className="grid gap-3 sm:grid-cols-4">
                    <StatTile
                      label={t('match.wizard.groups', { defaultValue: 'Groups' })}
                      value={groups.length}
                    />
                    <StatTile
                      label={t('match.wizard.matched', { defaultValue: 'With candidates' })}
                      value={matchedCount}
                      tone={matchedCount > 0 ? 'good' : 'warn'}
                    />
                    <StatTile
                      label={t('match.wizard.confirmed', { defaultValue: 'Confirmed' })}
                      value={groupSummary.confirmed ?? 0}
                    />
                    <StatTile
                      label={t('match.wizard.tbd', { defaultValue: 'Unmatched' })}
                      value={groupSummary.unmatched ?? 0}
                    />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      icon={<RefreshCw className="h-4 w-4" />}
                      onClick={() => groupsQ.refetch()}
                    >
                      {t('common.refresh', { defaultValue: 'Refresh' })}
                    </Button>
                    <Button
                      variant="primary"
                      size="sm"
                      icon={<Check className="h-4 w-4" />}
                      loading={bulkConfirmM.isPending}
                      onClick={() => bulkConfirmM.mutate()}
                    >
                      {t('match.wizard.confirmAll', {
                        defaultValue: 'Confirm all high-confidence',
                      })}
                    </Button>
                  </div>
                  <div className="max-h-[420px] overflow-auto rounded-lg border border-border-light">
                    <table className="w-full text-sm">
                      <thead className="sticky top-0 bg-surface-muted text-content-secondary">
                        <tr>
                          <th className="px-3 py-2 text-left font-medium">
                            {t('match.wizard.group', { defaultValue: 'Group' })}
                          </th>
                          <th className="px-3 py-2 text-left font-medium">
                            {t('match.wizard.suggestion', {
                              defaultValue: 'Top suggestion',
                            })}
                          </th>
                          <th className="px-3 py-2 text-left font-medium">
                            {t('match.wizard.status', { defaultValue: 'Status' })}
                          </th>
                          <th className="px-3 py-2" />
                        </tr>
                      </thead>
                      <tbody>
                        {groups.map((g) => (
                          <tr key={g.id} className="border-t border-border-light/60">
                            <td className="px-3 py-2">
                              <div className="font-medium text-content-primary">
                                {g.display_label}
                              </div>
                              <div className="text-xs text-content-tertiary">
                                {g.element_count}{' '}
                                {t('match.wizard.elementsLc', {
                                  defaultValue: 'elements',
                                })}
                              </div>
                            </td>
                            <td className="px-3 py-2 text-content-secondary">
                              {g.suggested_code ? (
                                <>
                                  <span className="font-mono text-xs">
                                    {g.suggested_code}
                                  </span>
                                  <div className="truncate max-w-[260px] text-xs">
                                    {g.suggested_description}
                                  </div>
                                </>
                              ) : (
                                <span className="text-content-tertiary">—</span>
                              )}
                            </td>
                            <td className="px-3 py-2">
                              <span
                                className={clsx(
                                  'inline-block rounded-full px-2 py-0.5 text-xs',
                                  g.status === 'confirmed' || g.status === 'applied'
                                    ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200'
                                    : g.status === 'suggested'
                                      ? 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200'
                                      : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
                                )}
                              >
                                {t(`match.group_status_${g.status}`, {
                                  defaultValue: g.status,
                                })}
                              </span>
                            </td>
                            <td className="px-3 py-2 text-right">
                              <button
                                type="button"
                                className="inline-flex items-center gap-1 text-xs font-medium text-oe-blue hover:underline"
                                onClick={() => setDetailGroup(g)}
                              >
                                {t('match.wizard.inspect', {
                                  defaultValue: 'Inspect',
                                })}
                                <ChevronRight className="h-3.5 w-3.5" />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* ── 8. Apply & finish ───────────────────────────────── */}
              {stage === 'apply' && (
                <div className="space-y-5">
                  <p className="text-sm text-content-secondary">
                    {t('match.wizard.applyHelp', {
                      defaultValue:
                        'Preview the bill of quantities that confirmed matches produce, then write it to the project’s BOQ.',
                    })}
                  </p>

                  {!applyResult && (
                    <Button
                      variant="primary"
                      icon={<FileSpreadsheet className="h-4 w-4" />}
                      loading={applyM.isPending}
                      onClick={() => applyM.mutate(true)}
                    >
                      {t('match.wizard.preview', {
                        defaultValue: 'Preview BOQ rollup',
                      })}
                    </Button>
                  )}

                  {applyResult && (
                    <>
                      <div className="grid gap-3 sm:grid-cols-3">
                        <StatTile
                          label={t('match.wizard.positions', {
                            defaultValue: 'BOQ positions',
                          })}
                          value={applyResult.count}
                          tone="good"
                        />
                        <StatTile
                          label={t('match.wizard.grandTotal', {
                            defaultValue: 'Grand total',
                          })}
                          value={fmtMoney(applyResult.total, applyResult.currency)}
                        />
                        <StatTile
                          label={t('match.wizard.mode', { defaultValue: 'Mode' })}
                          value={
                            applyResult.written
                              ? t('match.wizard.written', { defaultValue: 'Written' })
                              : t('match.wizard.dryRun', { defaultValue: 'Preview' })
                          }
                          tone={applyResult.written ? 'good' : 'default'}
                        />
                      </div>

                      {/* Line-by-line preview of the BOQ rollup. The backend
                          returns the full position list (description, unit,
                          qty, rate, line total, classification + resource
                          sub-rows); surfacing it here is what makes the
                          "Preview the bill of quantities" promise real -
                          before, the user only saw three aggregate tiles and
                          had to write blind. Zero-rate lines (unit-mismatch
                          gate, or a TBD/custom line at 0) are flagged so the
                          estimator can fix them before writing. */}
                      {applyResult.positions.length > 0 && (
                        <div className="rounded-lg border border-border-light overflow-hidden">
                          <div className="flex items-center justify-between gap-2 border-b border-border-light bg-surface-muted px-3 py-2">
                            <div className="text-sm font-medium text-content-primary">
                              {t('match.wizard.previewLines', {
                                defaultValue: '{{n}} positions',
                                n: applyResult.positions.length,
                              })}
                            </div>
                            {applyResult.positions.some((p) => Number(p.unit_rate) === 0) && (
                              <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-medium text-amber-800 dark:bg-amber-900/40 dark:text-amber-200">
                                {t('match.wizard.zeroRateWarning', {
                                  defaultValue:
                                    '{{n}} line(s) have no rate yet',
                                  n: applyResult.positions.filter(
                                    (p) => Number(p.unit_rate) === 0,
                                  ).length,
                                })}
                              </span>
                            )}
                          </div>
                          <div className="max-h-80 overflow-auto">
                            <table className="w-full text-sm">
                              <thead className="sticky top-0 bg-surface-primary">
                                <tr className="border-b border-border-light text-left text-xs uppercase tracking-wide text-content-tertiary">
                                  <th className="px-3 py-2 font-medium">
                                    {t('match.wizard.colDescription', {
                                      defaultValue: 'Description',
                                    })}
                                  </th>
                                  <th className="px-3 py-2 font-medium">
                                    {t('match.wizard.colUnit', { defaultValue: 'Unit' })}
                                  </th>
                                  <th className="px-3 py-2 text-right font-medium">
                                    {t('match.wizard.colQty', { defaultValue: 'Qty' })}
                                  </th>
                                  <th className="px-3 py-2 text-right font-medium">
                                    {t('match.wizard.colRate', { defaultValue: 'Rate' })}
                                  </th>
                                  <th className="px-3 py-2 text-right font-medium">
                                    {t('match.wizard.colTotal', { defaultValue: 'Total' })}
                                  </th>
                                </tr>
                              </thead>
                              <tbody>
                                {applyResult.positions.map((p, i) => {
                                  const zeroRate = Number(p.unit_rate) === 0;
                                  return (
                                    <tr
                                      key={`${p.group_key}-${i}`}
                                      className="border-b border-border-light/60 last:border-0 align-top"
                                    >
                                      <td className="px-3 py-2">
                                        <div className="text-content-primary">
                                          {p.description}
                                        </div>
                                        {p.section_path.length > 0 && (
                                          <div className="mt-0.5 text-[11px] text-content-tertiary">
                                            {p.section_path.join(' · ')}
                                          </div>
                                        )}
                                        {p.resources.length > 0 && (
                                          <div className="mt-0.5 text-[11px] text-content-tertiary">
                                            {t('match.wizard.resourceCount', {
                                              defaultValue: '{{n}} resource sub-rows',
                                              n: p.resources.length,
                                            })}
                                          </div>
                                        )}
                                      </td>
                                      <td className="px-3 py-2 text-content-secondary">
                                        {p.unit}
                                      </td>
                                      <td className="px-3 py-2 text-right tabular-nums text-content-secondary">
                                        {Number(p.quantity).toLocaleString(undefined, {
                                          maximumFractionDigits: 3,
                                        })}
                                      </td>
                                      <td
                                        className={clsx(
                                          'px-3 py-2 text-right tabular-nums',
                                          zeroRate
                                            ? 'text-amber-700 dark:text-amber-300'
                                            : 'text-content-secondary',
                                        )}
                                      >
                                        {zeroRate
                                          ? t('match.wizard.noRate', {
                                              defaultValue: 'no rate',
                                            })
                                          : fmtMoney(Number(p.unit_rate), p.currency)}
                                      </td>
                                      <td className="px-3 py-2 text-right tabular-nums font-medium text-content-primary">
                                        {fmtMoney(Number(p.line_total), p.currency)}
                                      </td>
                                    </tr>
                                  );
                                })}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      )}

                      {!applyResult.written ? (
                        <div className="flex flex-wrap gap-2">
                          <Button
                            variant="primary"
                            icon={<Rocket className="h-4 w-4" />}
                            loading={applyM.isPending}
                            onClick={() => applyM.mutate(false)}
                          >
                            {t('match.wizard.writeBoq', {
                              defaultValue: 'Write to project BOQ',
                            })}
                          </Button>
                          <Button
                            variant="ghost"
                            onClick={() => applyM.mutate(true)}
                            loading={applyM.isPending}
                          >
                            {t('common.refresh', { defaultValue: 'Refresh preview' })}
                          </Button>
                        </div>
                      ) : (
                        <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 dark:border-emerald-900/50 dark:bg-emerald-900/20">
                          <div className="flex items-center gap-2 font-medium text-emerald-800 dark:text-emerald-200">
                            <CheckCircle2 className="h-5 w-5" />
                            {t('match.wizard.done', {
                              defaultValue: 'Bill of quantities created.',
                            })}
                          </div>
                          <div className="mt-2 flex gap-2">
                            <Link to={`/projects/${projectId}/boq`}>
                              <Button variant="primary" size="sm">
                                {t('match.wizard.openBoq', {
                                  defaultValue: 'Open the BOQ',
                                })}
                              </Button>
                            </Link>
                          </div>
                        </div>
                      )}

                    </>
                  )}
                </div>
              )}
            </div>

            {/* Footer navigation (single, consistent) */}
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
                {t('match.wizard.stepCounter', {
                  defaultValue: 'Step {{n}} / {{total}}',
                  n: STAGE_INDEX[stage],
                  total: STAGES.length,
                })}
              </div>

              {stage !== 'apply' ? (
                <Button
                  variant="primary"
                  icon={<ArrowRight className="h-4 w-4" />}
                  iconPosition="right"
                  disabled={!canAdvance}
                  loading={createSessionM.isPending}
                  onClick={goNext}
                >
                  {stage === 'scope'
                    ? t('match.wizard.buildGroups', { defaultValue: 'Build groups' })
                    : stage === 'grouping'
                      ? t('match.wizard.runMatchCta', { defaultValue: 'Run match' })
                      : t('common.next', { defaultValue: 'Next' })}
                </Button>
              ) : (
                <Link to={projectId ? `/projects/${projectId}/boq` : '/projects'}>
                  <Button variant="secondary">
                    {t('match.wizard.finish', { defaultValue: 'Finish' })}
                  </Button>
                </Link>
              )}
            </div>
          </Card>
        </section>
      </div>

      {/* Detail slide-over (reused, the only overlay) */}
      {sessionId && detailGroup && (
        <MatchDetailPanel
          sessionId={sessionId}
          group={detailGroup}
          onClose={() => {
            setDetailGroup(null);
            qc.invalidateQueries({ queryKey: ['match-groups'] });
          }}
        />
      )}

      {/* Template-library slide-over — dead_button fix: TemplatesPanel was
          orphaned (no route, no trigger). It is opened from the
          "Setup & tools" section and closes on Escape / backdrop. */}
      {showTemplates && <TemplatesPanel onClose={() => setShowTemplates(false)} />}
    </div>
  );
}
