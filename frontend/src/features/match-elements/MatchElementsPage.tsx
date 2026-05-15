// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// /match-elements — full UX redesign.
//
// Drives BIM-element → CWICR cost-position matching end-to-end so an
// estimator can take a 5000-element Revit/IFC model and get a real BOQ
// with real cost in the project's currency in minutes. No mock data,
// no NIL UUID kludges, no hardcoded confidence thresholds.
//
// Layout (single column, no slide-overs except the detail panel):
//
//   1. Project context bar    — active project (from useProjectContextStore)
//   2. BIM model tab strip    — one tab per BIM model in the project
//   3. Session picker         — resume an existing session or start fresh
//   4. Action toolbar         — primary CTA morphs vector → confirm → apply
//   5. Settings rail          — group-by chips, threshold, net/gross,
//                               trade filter, confidence-band legend
//   6. Group list             — one row per group with display_label,
//                               suggested cost, confidence pill, status
//   7. Detail panel           — slide-over with elements / methods / apply
//                               (existing component, kept)

import { useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  AlertCircle,
  Check,
  CheckCircle2,
  ChevronRight,
  ChevronsRight,
  Database,
  Download,
  ExternalLink,
  FileSpreadsheet,
  FileText,
  Info,
  Languages,
  Layers,
  Library,
  Link2,
  Loader2,
  MessageSquarePlus,
  PlayCircle,
  RefreshCw,
  Search,
  Sparkles,
  XCircle,
} from 'lucide-react';

import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { useToastStore } from '@/stores/useToastStore';
import { projectsApi } from '@/features/projects/api';
import { Toggle } from '@/shared/ui/Toggle';
import { ChipBar, type Chip } from '@/shared/ui/ChipBar';
import { BIMModelPicker } from '@/shared/ui/BIMModelPicker';

import {
  matchElementsApi,
  CONSTRUCTION_STAGES,
  fetchVectorReadiness,
  type AttributeKey,
  type ConfidenceBand,
  type ConstructionStage,
  type GroupSummary,
  type MatcherName,
  type VectorReadiness,
  type MatchSession,
  type SessionSummary,
  type TradeBucket,
} from './api';
import { EmbedderStatusCard } from './EmbedderStatusCard';
import { MatchAnalyticsCard } from './MatchAnalyticsCard';
import { CataloguesPanelCard } from './CataloguesPanelCard';
import { QdrantHealthCard } from './QdrantHealthCard';
import { unwrapCataloguesPayload } from './catalogues-payload';
import { MatchWizard } from './MatchWizard';
import { MatchPipeline } from './MatchPipeline';
import { MatchProgressCard } from './MatchProgressCard';
import { MatchDetailPanel } from './MatchDetailPanel';
import { NewSessionFromExcelModal } from './NewSessionFromExcelModal';
import { NewSessionFromTextModal } from './NewSessionFromTextModal';
import { TemplatesPanel } from './TemplatesPanel';

// ─────────────────────────────────────────────────────────────────────────
//  Helpers
// ─────────────────────────────────────────────────────────────────────────

// Popular group-by keys shown by default. Universal across BIM/IFC/Revit
// regardless of project locale or modelling discipline. Anything else is
// tenant-specific (custom shared parameters, IFC PSet keys) and is hidden
// behind a "Show all" toggle to keep the chip-bar scannable.
const POPULAR_GROUP_BY_KEYS: ReadonlySet<string> = new Set([
  'ifc_class',
  'type_name',
  'family',
  'family_name',
  'material',
  'level',
  'level_name',
  'storey',
  'category',
  'name',
  'discipline',
]);

const TRADE_COLOURS: Record<TradeBucket, string> = {
  architectural: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200',
  structural: 'bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-200',
  mep: 'bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-200',
  civil: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  spatial: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
  subtractive: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-200',
  annotation: 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300',
  other: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
};

function StatusBadge({ status }: { status: GroupSummary['status'] }) {
  const { t } = useTranslation();
  const palette: Record<string, string> = {
    unmatched: 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300',
    suggested: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
    confirmed: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200',
    skipped: 'bg-slate-200 text-slate-500 line-through dark:bg-slate-700 dark:text-slate-400',
    tbd: 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200',
    applied: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-200',
    overridden: 'bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-200',
  };
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 text-xs font-medium rounded ${
        palette[status] ?? palette.unmatched
      }`}
    >
      {t(`match_elements.status.${status}`, status)}
    </span>
  );
}

function ConfidencePill({
  band,
  score,
}: {
  band: ConfidenceBand;
  score: string | null;
}) {
  if (band === 'none' || !score) {
    return <span className="text-slate-400 text-xs">—</span>;
  }
  const cls =
    band === 'high'
      ? 'bg-emerald-500'
      : band === 'medium'
        ? 'bg-amber-500'
        : 'bg-rose-500';
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block w-2 h-2 rounded-full ${cls}`} />
      <span className="text-xs tabular-nums text-slate-600 dark:text-slate-300">
        {Number(score).toFixed(2)}
      </span>
    </span>
  );
}

function fmtNum(v: number, digits = 2): string {
  if (!Number.isFinite(v)) return '—';
  return v.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

// ─────────────────────────────────────────────────────────────────────────
//  Sub-components
// ─────────────────────────────────────────────────────────────────────────

/** Visual readiness band for the cwicr_<lang>_v3 collection.
 *  Green = collection loaded and populated; amber = empty/missing/no-country
 *  (recoverable by visiting /costs); red = engine unreachable. */
function vectorBandPalette(band: VectorReadiness['status_band']): {
  dot: string;
  text: string;
  border: string;
  bg: string;
} {
  switch (band) {
    case 'ready':
      return {
        dot: 'bg-emerald-500',
        text: 'text-emerald-700 dark:text-emerald-300',
        border: 'border-emerald-200 dark:border-emerald-800',
        bg: 'bg-emerald-50 dark:bg-emerald-950/30',
      };
    case 'empty':
    case 'missing':
    case 'no_country':
    case 'non_qdrant':
      return {
        dot: 'bg-amber-500',
        text: 'text-amber-800 dark:text-amber-200',
        border: 'border-amber-200 dark:border-amber-800',
        bg: 'bg-amber-50 dark:bg-amber-950/30',
      };
    case 'disconnected':
    default:
      return {
        dot: 'bg-rose-500',
        text: 'text-rose-700 dark:text-rose-300',
        border: 'border-rose-200 dark:border-rose-800',
        bg: 'bg-rose-50 dark:bg-rose-950/30',
      };
  }
}

/** Inline readiness pill — explains in one line which CWICR collection
 *  the page is talking to and whether it's loaded. Sized to sit inside
 *  the project card without dominating it. */
function VectorReadinessPill({
  readiness,
  isLoading,
}: {
  readiness: VectorReadiness | undefined;
  isLoading: boolean;
}) {
  const { t } = useTranslation();
  if (isLoading) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-border bg-surface-primary text-xs text-content-tertiary">
        <Loader2 className="w-3 h-3 animate-spin" />
        {t('match_elements.vector_status_loading', 'Checking vector DB…')}
      </span>
    );
  }
  if (!readiness) return null;

  const palette = vectorBandPalette(readiness.status_band);
  const lang = readiness.language ? readiness.language.toUpperCase() : '—';
  const collection = readiness.collection || '—';

  let label: string;
  let detail: string;
  switch (readiness.status_band) {
    case 'ready':
      label = t('match_elements.vector_status_ready', 'Vector DB ready');
      detail = t(
        'match_elements.vector_status_ready_detail',
        '{{lang}} · {{rateCount}} rates · {{collection}}',
        {
          lang,
          rateCount: readiness.points_count.toLocaleString(),
          collection,
        },
      );
      break;
    case 'empty':
      label = t('match_elements.vector_status_empty', 'Vector DB empty');
      detail = t(
        'match_elements.vector_status_empty_detail',
        '{{lang}} · {{collection}} loaded but 0 rates — vectorize on /costs',
        { lang, collection },
      );
      break;
    case 'missing':
      label = t('match_elements.vector_status_missing', 'Collection not loaded');
      detail = t(
        'match_elements.vector_status_missing_detail',
        '{{collection}} for language "{{lang}}" not in Qdrant — visit /costs to vectorize',
        { lang, collection },
      );
      break;
    case 'no_country':
      label = t(
        'match_elements.vector_status_no_country',
        'Region/language unknown',
      );
      detail = t(
        'match_elements.vector_status_no_country_detail',
        'Set the project region in /projects/.../settings to pin the collection',
      );
      break;
    case 'non_qdrant':
      label = t(
        'match_elements.vector_status_non_qdrant',
        'Legacy LanceDB backend',
      );
      detail = t(
        'match_elements.vector_status_non_qdrant_detail',
        'Per-language collections only apply on Qdrant — current engine is LanceDB',
      );
      break;
    case 'disconnected':
    default:
      label = t(
        'match_elements.vector_status_disconnected',
        'Vector DB unreachable',
      );
      detail = readiness.error
        ? t(
            'match_elements.vector_status_disconnected_detail',
            'Qdrant is not responding · {{error}}',
            { error: readiness.error.slice(0, 60) },
          )
        : t(
            'match_elements.vector_status_disconnected_help',
            'Qdrant is not responding — matchers will fall back to lexical only',
          );
      break;
  }

  const isAmber = ['empty', 'missing', 'no_country', 'non_qdrant'].includes(
    readiness.status_band,
  );
  // Only the no_country / non_qdrant / disconnected cases benefit from the
  // raw "Open /costs" link; missing & empty are handled by the
  // CatalogueAdvisor below with one-click bindable recommendations.
  const showCostsLink =
    isAmber &&
    readiness.status_band !== 'no_country' &&
    readiness.status_band !== 'missing' &&
    readiness.status_band !== 'empty';

  return (
    <div
      className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs ${palette.border} ${palette.bg}`}
      role="status"
      aria-live="polite"
      title={detail}
    >
      <Database className={`w-4 h-4 ${palette.text} shrink-0`} />
      <div className="flex flex-col gap-0.5 min-w-0">
        <span className={`font-medium ${palette.text}`}>{label}</span>
        <span className="text-content-tertiary truncate max-w-[60ch]">
          {detail}
        </span>
      </div>
      {showCostsLink && (
        <Link
          to="/costs"
          className={`shrink-0 inline-flex items-center gap-1 underline ${palette.text} hover:opacity-80`}
        >
          {t('match_elements.vector_status_open_costs', 'Open /costs')}
        </Link>
      )}
    </div>
  );
}

/** Region-language correspondence chip — surfaces how the project's
 *  region resolves to the cwicr_<lang>_v3 collection. Always visible
 *  next to the project name so the user can see the mapping at a glance. */
function ProjectRegionLangChip({
  region,
  language,
  currency,
}: {
  region: string | null;
  language: string;
  currency: string | null;
}) {
  const { t } = useTranslation();
  return (
    <div className="inline-flex flex-wrap items-center gap-1.5 text-xs">
      {region && (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-indigo-50 dark:bg-indigo-950/40 border border-indigo-200 dark:border-indigo-800 text-indigo-800 dark:text-indigo-200 font-medium">
          <Layers className="w-3 h-3" />
          {region}
        </span>
      )}
      {language && (
        <span
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-sky-50 dark:bg-sky-950/40 border border-sky-200 dark:border-sky-800 text-sky-800 dark:text-sky-200 font-medium uppercase"
          title={t(
            'match_elements.region_lang_help',
            'Project region resolves to this language → cwicr_{{lang}}_v3 collection',
            { lang: language },
          )}
        >
          <Languages className="w-3 h-3" />
          {language}
        </span>
      )}
      {currency && (
        <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-200 font-medium uppercase">
          {currency}
        </span>
      )}
    </div>
  );
}

/** Workflow step indicator. Visualises the four-step BIM→BOQ flow as a
 *  horizontal "stepper" with completed checks, the current active dot,
 *  and pending dots. Lives in the hero block so the user always knows
 *  what step they are on without reading the section labels.
 *
 *  Steps: 1) BIM model · 2) Session · 3) Review groups · 4) Apply to BOQ */
function WorkflowStepIndicator({
  step,
  totalGroups,
  confirmedCount,
  appliedCount,
  hasModel,
  hasSession,
}: {
  step: 1 | 2 | 3 | 4;
  totalGroups: number;
  confirmedCount: number;
  appliedCount: number;
  hasModel: boolean;
  hasSession: boolean;
}) {
  const { t } = useTranslation();
  const items: Array<{
    n: 1 | 2 | 3 | 4;
    label: string;
    detail: string;
  }> = [
    {
      n: 1,
      label: t('match_elements.step_1_label', 'Pick model'),
      detail: hasModel
        ? t('match_elements.step_1_done', 'Selected')
        : t('match_elements.step_1_help', 'Choose BIM model'),
    },
    {
      n: 2,
      label: t('match_elements.step_2_label', 'Open session'),
      detail: hasSession
        ? t('match_elements.step_2_done', 'Active')
        : t('match_elements.step_2_help', 'Resume or create'),
    },
    {
      n: 3,
      label: t('match_elements.step_3_label', 'Review matches'),
      detail:
        totalGroups === 0
          ? t('match_elements.step_3_empty', 'No groups yet')
          : t(
              'match_elements.step_3_progress',
              '{{confirmed}}/{{total}} confirmed',
              { confirmed: confirmedCount, total: totalGroups },
            ),
    },
    {
      n: 4,
      label: t('match_elements.step_4_label', 'Apply to BOQ'),
      detail:
        appliedCount > 0
          ? t('match_elements.step_4_done', '{{n}} applied', {
              n: appliedCount,
            })
          : t('match_elements.step_4_help', 'Write to BOQ'),
    },
  ];

  return (
    <ol className="flex items-center gap-1 w-full overflow-x-auto" role="list">
      {items.map((it, idx) => {
        const isDone = step > it.n;
        const isActive = step === it.n;
        return (
          <li
            key={it.n}
            className="flex items-center gap-1 min-w-0"
            aria-current={isActive ? 'step' : undefined}
          >
            <div
              className={`flex items-center gap-2 px-2.5 py-1.5 rounded-lg transition ${
                isActive
                  ? 'bg-white dark:bg-surface-primary shadow-sm border border-indigo-300 dark:border-indigo-600 ring-2 ring-indigo-200/60 dark:ring-indigo-700/40'
                  : isDone
                    ? 'bg-emerald-50/70 dark:bg-emerald-950/30 border border-emerald-200/70 dark:border-emerald-800/60'
                    : 'bg-white/40 dark:bg-surface-primary/40 border border-transparent'
              }`}
            >
              <span
                className={`shrink-0 w-5 h-5 rounded-full inline-flex items-center justify-center text-[10px] font-bold ${
                  isDone
                    ? 'bg-emerald-500 text-white'
                    : isActive
                      ? 'bg-gradient-to-br from-indigo-500 to-sky-500 text-white shadow-sm shadow-indigo-500/20'
                      : 'bg-content-tertiary/15 text-content-tertiary'
                }`}
              >
                {isDone ? <CheckCircle2 className="w-3 h-3" /> : it.n}
              </span>
              <div className="min-w-0">
                <div
                  className={`text-[11px] font-semibold leading-tight ${
                    isActive
                      ? 'text-content-primary'
                      : isDone
                        ? 'text-emerald-800 dark:text-emerald-200'
                        : 'text-content-tertiary'
                  }`}
                >
                  {it.label}
                </div>
                <div
                  className={`text-[10px] leading-tight ${
                    isActive
                      ? 'text-indigo-700 dark:text-indigo-300'
                      : 'text-content-tertiary'
                  }`}
                >
                  {it.detail}
                </div>
              </div>
            </div>
            {idx < items.length - 1 && (
              <ChevronRight
                className={`w-3.5 h-3.5 shrink-0 ${
                  step > it.n
                    ? 'text-emerald-400 dark:text-emerald-500'
                    : 'text-content-tertiary/40'
                }`}
                aria-hidden
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}

/** Rich project context card — single source of truth for "which
 *  project + which CWICR collection is /match-elements pointed at?".
 *  Replaces the v2.9.x one-line bar so the user can verify at a glance
 *  that the language a match query will hit matches the project locale. */
function ProjectContextCard({
  projectId,
}: {
  projectId: string | null;
}) {
  const { t } = useTranslation();
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);

  // Project metadata (region, currency, locale) — needed to derive the
  // vector collection and to render the badges.
  const projectQ = useQuery({
    enabled: !!projectId,
    queryKey: ['match-project-meta', projectId],
    queryFn: () => projectsApi.get(projectId!),
    staleTime: 5 * 60 * 1000,
  });

  // Vector DB readiness for this project's region. Polls every 60 s so
  // a fresh vectorisation on /costs surfaces here without a manual refresh.
  // The project_id arg also returns ``language_mismatch`` diagnostics so
  // we can warn when the bound catalogue speaks a different language than
  // the project region (a sign that auto_bind_dominant_catalogue picked
  // by row count before the language-aware fix landed in 2.9.34).
  const region = projectQ.data?.region ?? '';
  const readinessQ = useQuery({
    enabled: !!projectId,
    queryKey: ['match-vector-readiness', region || projectId, projectId],
    queryFn: () => fetchVectorReadiness(region, projectId),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const queryClient = useQueryClient();
  // Direct rebind to a specific catalogue — replaces the v2.9.36 "set to
  // null and pray auto-bind picks something better" mutation, which was
  // non-deterministic. The advisor now chooses the catalogue and binds
  // it explicitly via the same /match-settings PATCH.
  const bindToCatalogueMut = useMutation({
    mutationFn: async (catalogueId: string) => {
      const { setProjectCatalog } = await import('@/features/match/api');
      return setProjectCatalog(projectId!, catalogueId);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['match-vector-readiness'],
      });
      await queryClient.invalidateQueries({
        queryKey: ['projects', projectId, 'match-settings'],
      });
      await readinessQ.refetch();
    },
  });

  if (!projectId) {
    return (
      <div className="px-4 py-3 rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-900/20 dark:border-amber-700 text-sm">
        <p className="font-medium text-amber-900 dark:text-amber-200">
          {t(
            'match_elements.no_project_title',
            'No active project selected.',
          )}
        </p>
        <p className="text-xs text-amber-800 dark:text-amber-300 mt-1">
          {t(
            'match_elements.no_project_hint',
            'Open the project picker in the header, or visit',
          )}{' '}
          <Link to="/projects" className="underline font-medium">
            /projects
          </Link>
          .
        </p>
      </div>
    );
  }

  const project = projectQ.data;
  const displayName =
    project?.name || activeProjectName || projectId.slice(0, 8);

  return (
    <div className="rounded-xl border border-border bg-surface-primary p-5 flex flex-col gap-4 shadow-sm">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-start gap-4 min-w-0">
          <div className="shrink-0 w-12 h-12 rounded-xl bg-gradient-to-br from-indigo-100 to-sky-100 dark:from-indigo-900/50 dark:to-sky-900/40 border border-indigo-200 dark:border-indigo-800 flex items-center justify-center shadow-sm">
            <Layers className="w-6 h-6 text-indigo-600 dark:text-indigo-300" />
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[10px] uppercase tracking-[0.12em] text-content-tertiary font-semibold">
                {t('match_elements.active_project', 'Active project')}
              </span>
            </div>
            <h2
              className="text-lg lg:text-xl font-semibold text-content-primary truncate max-w-[60ch] leading-tight"
              title={displayName}
            >
              {displayName}
            </h2>
            <div className="mt-2">
              <ProjectRegionLangChip
                region={project?.region ?? null}
                language={readinessQ.data?.language ?? ''}
                currency={project?.currency ?? null}
              />
            </div>
          </div>
        </div>
        <Link
          to={`/projects/${projectId}/settings`}
          className="text-xs underline text-content-tertiary hover:text-content-primary shrink-0"
          title={t(
            'match_elements.project_settings_help',
            'Open project settings (region, currency, locale, fx rates)',
          )}
        >
          {t('match_elements.project_settings', 'Project settings')}
        </Link>
      </div>
      <VectorReadinessPill
        readiness={readinessQ.data}
        isLoading={readinessQ.isLoading}
      />
      <CatalogueAdvisor
        projectRegion={project?.region ?? null}
        readiness={readinessQ.data}
        bindMut={bindToCatalogueMut}
      />
    </div>
  );
}

/** Smart catalogue advisor — replaces the v2.9.36 dual-banner UX (a
 *  warning pill + a "re-bind blindly" mutation that relied on auto-bind
 *  picking the right thing). Now we *show* the user which catalogues are
 *  loaded and ready in their language, and let them bind to a specific
 *  one in a single click — no leaving the page, no manual /costs trip,
 *  no auto-bind lottery.
 *
 *  Renders in three states:
 *
 *  1. **Language mismatch** (bound catalogue is a different language than
 *     the project region). Shows top-3 ready catalogues in the project
 *     language as one-click bind buttons, each with rate count. Region
 *     prefix matches (e.g. USA_* for region "US") sort first.
 *  2. **Collection not loaded / not vectorised**. Same picker, plus a
 *     fallback link to /costs if no language-matching catalogue is loaded.
 *  3. **All good** (status=ready, no mismatch). Renders nothing. */
function CatalogueAdvisor({
  projectRegion,
  readiness,
  bindMut,
}: {
  projectRegion: string | null;
  readiness: VectorReadiness | undefined;
  bindMut: ReturnType<typeof useMutation<
    { cost_database_id: string | null },
    Error,
    string
  >>;
}) {
  const { t } = useTranslation();

  const projectLanguage = (readiness?.language || '').toLowerCase();
  const isMismatch = readiness?.language_mismatch?.status === 'mismatch';
  const isMissing = readiness?.status_band === 'missing';
  const isEmpty = readiness?.status_band === 'empty';
  const showAdvisor = isMismatch || isMissing || isEmpty;

  const dbsQ = useQuery({
    enabled: showAdvisor,
    queryKey: ['loaded-databases'],
    queryFn: async () => {
      const { listLoadedDatabases } = await import('@/features/match/api');
      return listLoadedDatabases();
    },
    staleTime: 60_000,
  });

  // Language-matching, ready catalogues, sorted by region affinity then
  // by rate count. Region prefix match: e.g. project region "US" boosts
  // any catalogue id starting with "US" (USA_NEWYORK, USA_USD, …).
  const recommendations = useMemo(() => {
    if (!Array.isArray(dbsQ.data) || !projectLanguage) return [];
    const regionPrefix = (projectRegion || '').slice(0, 2).toUpperCase();
    return [...dbsQ.data]
      .filter((db) => db.ready && (db.language || '').toLowerCase() === projectLanguage)
      .sort((a, b) => {
        const aMatch = regionPrefix && a.id.toUpperCase().startsWith(regionPrefix) ? 1 : 0;
        const bMatch = regionPrefix && b.id.toUpperCase().startsWith(regionPrefix) ? 1 : 0;
        if (aMatch !== bMatch) return bMatch - aMatch;
        return b.count - a.count;
      })
      .slice(0, 3);
  }, [dbsQ.data, projectLanguage, projectRegion]);

  // Fallback: if zero loaded catalogues match the project language, surface
  // the published-but-not-installed v3 snapshots so the user can one-click
  // install instead of bouncing to /costs.
  const showInstallables = showAdvisor && !dbsQ.isLoading && recommendations.length === 0;
  const installablesQ = useQuery({
    enabled: showInstallables,
    queryKey: ['catalogues-v3', 'advisor-flat'],
    queryFn: async () => {
      const token = (await import('@/stores/useAuthStore')).useAuthStore
        .getState()
        .accessToken;
      const res = await fetch('/api/v1/costs/catalogues-v3/', {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) throw new Error(`catalogues-v3 ${res.status}`);
      const data: { catalogues: Array<{ region: string; language: string; install_status: string; size_mb: number; country_iso: string }> } =
        await res.json();
      return data.catalogues || [];
    },
    staleTime: 60_000,
  });
  const installables = useMemo(() => {
    if (!projectLanguage) return [];
    // Shape-tolerant: see ./catalogues-payload.ts and Issue #122 — the
    // endpoint has shipped both a bare array and a `{catalogues:[…]}`
    // envelope, and a stale react-query cache of the *wrong* shape used
    // to crash this page with `p.data.filter is not a function`.
    const list = unwrapCataloguesPayload(installablesQ.data);
    const regionPrefix = (projectRegion || '').slice(0, 2).toUpperCase();
    return list
      .filter(
        (c) =>
          c.install_status === 'available' &&
          (c.language || '').toLowerCase() === projectLanguage,
      )
      .sort((a, b) => {
        const aMatch = regionPrefix && a.region.toUpperCase().startsWith(regionPrefix) ? 1 : 0;
        const bMatch = regionPrefix && b.region.toUpperCase().startsWith(regionPrefix) ? 1 : 0;
        if (aMatch !== bMatch) return bMatch - aMatch;
        return a.size_mb - b.size_mb;
      })
      .slice(0, 3);
  }, [installablesQ.data, projectLanguage, projectRegion]);

  const qcInstall = useQueryClient();
  const installMut = useMutation({
    mutationFn: async (region: string) => {
      const token = (await import('@/stores/useAuthStore')).useAuthStore
        .getState()
        .accessToken;
      const res = await fetch(
        `/api/v1/costs/catalogues-v3/${encodeURIComponent(region)}/install`,
        {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        },
      );
      if (!res.ok) throw new Error(await res.text());
      return res.json();
    },
    onSuccess: async (_data, region) => {
      await qcInstall.invalidateQueries({ queryKey: ['catalogues-v3'] });
      await qcInstall.invalidateQueries({ queryKey: ['loaded-databases'] });
      // Auto-bind so the user gets a one-click "install + match" path.
      bindMut.mutate(region);
    },
  });

  if (!showAdvisor) return null;

  const projLangUpper = projectLanguage.toUpperCase() || '—';
  // boundCatalogue / boundLang were surfaced in the v2.9.39 message text
  // ("Currently using {cat} ({lang})…"). Removed in v2.9.40 — naming the
  // mismatched catalogue (e.g. RU) on a /match-elements view that is
  // explicitly trying to steer the user *away* from RU just adds noise.
  // Recommendations + installables grids below are already filtered to
  // the project language, so the wrong-language catalogue never appears
  // as an actionable row.

  let title: string;
  let detail: string;
  if (isMismatch) {
    title = t(
      'match_elements.advisor_mismatch_title',
      'Pick a {{lang}} catalogue',
      { lang: projLangUpper },
    );
    detail = t(
      'match_elements.advisor_mismatch_detail',
      'Pick a {{lang}} catalogue below — your project speaks {{lang}}, so matches need to come from a same-language rate book.',
      { lang: projLangUpper },
    );
  } else if (isMissing) {
    title = t(
      'match_elements.advisor_missing_title',
      '{{lang}} vector collection not loaded',
      { lang: projLangUpper },
    );
    detail = t(
      'match_elements.advisor_missing_detail',
      'Pick a ready catalogue below, or load a new one.',
    );
  } else {
    title = t(
      'match_elements.advisor_empty_title',
      'Catalogue not vectorised yet',
    );
    detail = t(
      'match_elements.advisor_empty_detail',
      'Pick a different ready catalogue below, or vectorise the current one.',
    );
  }

  return (
    <div
      className="rounded-lg border border-amber-300/70 bg-amber-50/70 dark:bg-amber-950/25 dark:border-amber-700/60 px-3 py-2.5"
      role="alert"
    >
      {/* Compact advisor — single header row with title + Hugging Face
          link + loading indicator, then a horizontal chip strip of bind
          (loaded) / install (available) actions. The previous layout
          stacked each option as a 50px button — for 3 options that came
          out at ~250px, dwarfing the matching workspace below. The chip
          row trades vertical space for horizontal scroll, which is fine
          here because we cap it to ~3 chips per side anyway. */}
      <div className="flex items-center gap-2 min-w-0">
        <AlertCircle className="w-4 h-4 text-amber-600 dark:text-amber-300 shrink-0" />
        <div className="text-xs font-semibold text-amber-900 dark:text-amber-100 truncate">
          {title}
        </div>
        {dbsQ.isLoading && (
          <Loader2 className="w-3 h-3 text-amber-700 dark:text-amber-300 animate-spin shrink-0" />
        )}
        <a
          href="https://huggingface.co/datasets/DataDrivenConstruction/cwicr-vector-db-bgem3-v3"
          target="_blank"
          rel="noopener noreferrer"
          className="ms-auto shrink-0 text-[11px] inline-flex items-center gap-1 text-amber-800/80 dark:text-amber-200/80 hover:text-amber-900 dark:hover:text-amber-100 hover:underline"
        >
          <Library className="w-3 h-3" />
          {t('match_elements.advisor_browse_all', 'All on Hugging Face')}
        </a>
      </div>

      <div className="mt-1.5 ps-6 text-[11px] text-amber-800/80 dark:text-amber-200/80">
        {detail}
      </div>

      {!dbsQ.isLoading && (recommendations.length > 0 || installables.length > 0) && (
        <div className="mt-2 ps-6 flex flex-wrap items-center gap-1.5">
          {recommendations.map((db) => {
            const isPending = bindMut.isPending && bindMut.variables === db.id;
            return (
              <button
                key={db.id}
                type="button"
                onClick={() => bindMut.mutate(db.id)}
                disabled={bindMut.isPending}
                className={clsx(
                  'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium',
                  'bg-white dark:bg-surface-primary border border-amber-300/70 dark:border-amber-700/50',
                  'hover:bg-amber-100 dark:hover:bg-amber-900/30 hover:-translate-y-px hover:shadow-sm',
                  'transition-all disabled:opacity-50 disabled:translate-y-0 disabled:hover:shadow-none',
                )}
                title={t('match_elements.advisor_bind_title', 'Use {{db}} ({{n}} rates)', {
                  db: db.id,
                  n: db.count.toLocaleString(),
                })}
              >
                {isPending ? (
                  <Loader2 className="w-3 h-3 animate-spin text-amber-600" />
                ) : (
                  <Check className="w-3 h-3 text-amber-600" />
                )}
                <span className="text-content-primary">{db.id}</span>
              </button>
            );
          })}
          {installables.map((c) => {
            const isPending =
              installMut.isPending && installMut.variables === c.region;
            return (
              <button
                key={c.region}
                type="button"
                onClick={() => installMut.mutate(c.region)}
                disabled={installMut.isPending || bindMut.isPending}
                className={clsx(
                  'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium',
                  'bg-emerald-600 text-white border border-emerald-600',
                  'hover:bg-emerald-700 hover:border-emerald-700 hover:-translate-y-px hover:shadow-sm hover:shadow-emerald-500/30',
                  'transition-all disabled:opacity-50 disabled:translate-y-0 disabled:hover:shadow-none',
                )}
                title={t('match_elements.advisor_install_title', 'Install {{region}} (~{{mb}} MB)', {
                  region: c.region,
                  mb: c.size_mb,
                })}
              >
                {isPending ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : (
                  <Download className="w-3 h-3" />
                )}
                <span>{c.region}</span>
                <span className="opacity-70 font-normal">{c.size_mb}MB</span>
              </button>
            );
          })}
        </div>
      )}

      {!dbsQ.isLoading &&
        recommendations.length === 0 &&
        installables.length === 0 && (
          <div className="mt-2 ps-6 text-[11px] text-amber-800/80 dark:text-amber-200/80">
            {t(
              'match_elements.advisor_none_available',
              'No {{lang}} catalogues are loaded yet. Visit /costs to import one.',
              { lang: projLangUpper },
            )}
          </div>
        )}

      {(installMut.error || bindMut.error) && (
        <div className="mt-1.5 ps-6 text-[11px] text-rose-700 dark:text-rose-300 truncate">
          {String(installMut.error || bindMut.error)}
        </div>
      )}
    </div>
  );
}

function SessionPicker({
  projectId,
  sessions,
  isLoading,
  activeSessionId,
  onPick,
  onCreate,
  onCreateText,
  onCreateExcel,
  isCreating,
}: {
  projectId: string;
  sessions: SessionSummary[];
  isLoading: boolean;
  activeSessionId: string | null;
  onPick: (id: string) => void;
  onCreate: () => void;
  onCreateText: () => void;
  onCreateExcel: () => void;
  isCreating: boolean;
}) {
  const { t } = useTranslation();
  if (!projectId) return null;
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-content-tertiary py-2">
        <Loader2 className="w-4 h-4 animate-spin" />
        {t('match_elements.loading_sessions', 'Loading sessions…')}
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {sessions.length === 0 && (
        <span className="text-xs text-content-tertiary mr-1">
          {t(
            'match_elements.no_prior_sessions',
            'No prior matching sessions for this project.',
          )}
        </span>
      )}
      {sessions.map((s) => {
        const isActive = s.id === activeSessionId;
        const lastSeen = s.last_active_at
          ? new Date(s.last_active_at).toLocaleString()
          : '';
        const progress =
          s.group_count > 0
            ? Math.round((s.confirmed_count / s.group_count) * 100)
            : 0;
        return (
          <button
            key={s.id}
            type="button"
            onClick={() => onPick(s.id)}
            title={lastSeen}
            className={`inline-flex flex-col items-start gap-1 rounded-lg border px-3 py-2 text-sm transition max-w-[40ch] ${
              isActive
                ? 'border-oe-blue bg-oe-blue/5 text-content-primary shadow-sm'
                : 'border-border bg-surface-primary text-content-secondary hover:border-oe-blue/40'
            }`}
          >
            <span className="truncate font-medium max-w-[36ch]">
              {s.name ||
                t('match_elements.session_default_name', 'Session {{id}}', {
                  id: s.id.slice(0, 8),
                })}
            </span>
            <span className="flex items-center gap-2 text-xs">
              <span className="tabular-nums opacity-70">
                {s.confirmed_count}/{s.group_count}{' '}
                {t('match_elements.session_confirmed', 'confirmed')}
              </span>
              <span className="opacity-50 tabular-nums">{progress}%</span>
              {s.applied_count > 0 && s.currency && (
                <span className="tabular-nums opacity-70">
                  ·{' '}
                  {s.total_value > 0 ? fmtNum(s.total_value, 0) : '0'}{' '}
                  {s.currency}
                </span>
              )}
            </span>
          </button>
        );
      })}
      <button
        type="button"
        onClick={onCreate}
        disabled={isCreating}
        className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-border px-3 py-2 text-sm text-content-tertiary hover:border-oe-blue/40 hover:text-oe-blue disabled:opacity-50"
      >
        {isCreating ? (
          <Loader2 className="w-4 h-4 animate-spin" />
        ) : (
          <Sparkles className="w-4 h-4" />
        )}
        {t('match_elements.new_session', 'New session')}
      </button>
      <button
        type="button"
        onClick={onCreateText}
        className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-border px-3 py-2 text-sm text-content-tertiary hover:border-oe-blue/40 hover:text-oe-blue"
        title={t(
          'match_elements.new_text.button_title',
          'Paste descriptions — one per line',
        )}
      >
        <FileText className="w-4 h-4" />
        {t('match_elements.new_text.button', 'From text')}
      </button>
      <button
        type="button"
        onClick={onCreateExcel}
        className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-border px-3 py-2 text-sm text-content-tertiary hover:border-emerald-500/40 hover:text-emerald-700"
        title={t(
          'match_elements.new_excel.button_title',
          'Upload an .xlsx Bill of Quantities',
        )}
      >
        <FileSpreadsheet className="w-4 h-4" />
        {t('match_elements.new_excel.button', 'From Excel BoQ')}
      </button>
    </div>
  );
}

/* Shared shell for Step-4 settings controls. Renders a consistent
   label-on-top + control + help-below stack so that a Slider, a Toggle,
   and a Select can sit side-by-side in the same grid row without
   visually disagreeing on label style or vertical rhythm. The `trailing`
   slot puts a value chip (e.g. "0.95" or "On") on the same baseline as
   the label so the user can scan the row left-to-right and read the
   current setting at a glance. */
function FieldShell({
  label,
  help,
  htmlFor,
  trailing,
  children,
}: {
  label: React.ReactNode;
  help?: React.ReactNode;
  htmlFor?: string;
  trailing?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5 min-w-0">
      <div className="flex items-baseline justify-between gap-2 min-h-[14px]">
        <label
          htmlFor={htmlFor}
          className="text-[11px] uppercase tracking-wider text-content-tertiary font-semibold leading-none"
        >
          {label}
        </label>
        {trailing && <span className="shrink-0 leading-none">{trailing}</span>}
      </div>
      <div className="min-w-0">{children}</div>
      {help && (
        <p className="text-[11px] text-content-tertiary leading-snug">{help}</p>
      )}
    </div>
  );
}

function ConfidenceLegend({
  high,
  medium,
}: {
  high: number;
  medium: number;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center gap-3 text-xs">
      <span className="text-content-tertiary">
        {t('match_elements.legend_label', 'Confidence')}:
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="w-2 h-2 rounded-full bg-emerald-500" />
        {t('match_elements.legend_high', 'High')}{' '}
        <span className="tabular-nums opacity-60">≥ {high.toFixed(2)}</span>
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="w-2 h-2 rounded-full bg-amber-500" />
        {t('match_elements.legend_medium', 'Medium')}{' '}
        <span className="tabular-nums opacity-60">≥ {medium.toFixed(2)}</span>
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="w-2 h-2 rounded-full bg-rose-500" />
        {t('match_elements.legend_low', 'Low')}
      </span>
    </div>
  );
}

function GroupListBody({
  groups,
  isLoading,
  selected,
  onToggleOne,
  onOpenDetail,
}: {
  groups: GroupSummary[];
  isLoading: boolean;
  selected: Set<string>;
  onToggleOne: (key: string) => void;
  onOpenDetail: (g: GroupSummary) => void;
}) {
  const { t } = useTranslation();

  if (isLoading) {
    return (
      <div className="px-3 py-12 text-center text-content-tertiary">
        <Loader2 className="w-4 h-4 animate-spin inline mr-2" />
        {t('match_elements.loading_groups', 'Loading groups…')}
      </div>
    );
  }
  if (groups.length === 0) {
    return (
      <div className="px-3 py-12 text-center text-content-tertiary text-sm">
        {t(
          'match_elements.no_groups',
          'No groups yet — import a BIM model to populate this project.',
        )}
      </div>
    );
  }

  return (
    <table className="w-full text-sm">
      <thead className="bg-slate-50 dark:bg-slate-800 sticky top-0 z-10">
        <tr className="border-b border-slate-200 dark:border-slate-700">
          <th className="px-3 py-2 w-8" />
          <th className="text-left px-3 py-2 font-medium">
            {t('match_elements.col.group', 'Group')}
          </th>
          <th className="text-right px-3 py-2 font-medium">
            {t('match_elements.col.count', 'Count')}
          </th>
          <th className="text-right px-3 py-2 font-medium">
            {t('match_elements.col.total_qty', 'Total qty')}
          </th>
          <th className="text-left px-3 py-2 font-medium">
            {t('match_elements.col.suggested', 'Suggested cost')}
          </th>
          <th className="text-left px-3 py-2 font-medium">
            {t('match_elements.col.confidence', 'Confidence')}
          </th>
          <th className="text-left px-3 py-2 font-medium">
            {t('match_elements.col.status', 'Status')}
          </th>
          <th className="text-right px-3 py-2 font-medium">
            {t('match_elements.col.actions', 'Actions')}
          </th>
        </tr>
      </thead>
      <tbody>
        {groups.map((g) => {
          const isSelected = selected.has(g.group_key);
          const tradeCls = TRADE_COLOURS[g.trade] ?? TRADE_COLOURS.other;
          return (
            <tr
              key={g.id}
              className={`border-b border-slate-100 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800/50 ${
                isSelected ? 'bg-indigo-50/40 dark:bg-indigo-900/10' : ''
              }`}
            >
              <td className="px-3 py-2">
                <input
                  type="checkbox"
                  checked={isSelected}
                  onChange={() => onToggleOne(g.group_key)}
                  aria-label={t(
                    'match_elements.aria.select_group',
                    'Select {{key}}',
                    { key: g.group_key },
                  )}
                />
              </td>
              <td className="px-3 py-2 max-w-[40ch]">
                <div className="flex items-center gap-2">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] uppercase ${tradeCls}`}>
                    {t(`match_elements.trade.${g.trade}`, g.trade)}
                  </span>
                  <span
                    className="font-medium truncate"
                    title={g.group_key}
                  >
                    {g.display_label || g.group_key}
                  </span>
                  {g.is_subtractive && (
                    <span
                      className="text-[10px] px-1 py-0.5 rounded bg-rose-50 text-rose-600 dark:bg-rose-900/30 dark:text-rose-300"
                      title={t(
                        'match_elements.subtractive_hint',
                        'Subtractive / non-billable',
                      )}
                    >
                      {t('match_elements.subtractive_badge', 'void')}
                    </span>
                  )}
                  {g.opening_warning && (
                    <span
                      className="inline-flex items-center text-amber-600 dark:text-amber-400"
                      title={t(
                        'match_elements.detail.opening_warning',
                        'host has openings but gross == net (IFC export bug)',
                      )}
                    >
                      <AlertCircle className="w-3.5 h-3.5" />
                    </span>
                  )}
                </div>
                {g.sample_names.length > 0 && (
                  <div className="text-[11px] text-content-tertiary truncate mt-0.5">
                    {g.sample_names.slice(0, 2).join(' · ')}
                  </div>
                )}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {g.element_count}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">
                {fmtNum(g.primary_quantity)}{' '}
                <span className="text-content-tertiary">
                  {g.chosen_unit ?? ''}
                </span>
              </td>
              <td className="px-3 py-2 max-w-[32ch]">
                {g.suggested_code ? (
                  <div className="text-xs">
                    <div className="font-mono text-content-tertiary">
                      {g.suggested_code}
                    </div>
                    <div className="truncate" title={g.suggested_description ?? ''}>
                      {g.suggested_description}
                    </div>
                    {g.suggested_unit_rate != null && (
                      <div className="text-[11px] text-content-tertiary tabular-nums">
                        {fmtNum(g.suggested_unit_rate)}{' '}
                        {g.suggested_currency}/{g.chosen_unit ?? ''}
                      </div>
                    )}
                  </div>
                ) : (
                  <span className="text-content-tertiary text-xs">—</span>
                )}
              </td>
              <td className="px-3 py-2">
                <ConfidencePill band={g.confidence_band} score={g.confidence} />
              </td>
              <td className="px-3 py-2">
                <StatusBadge status={g.status} />
              </td>
              <td className="px-3 py-2 text-right">
                <button
                  type="button"
                  onClick={() => onOpenDetail(g)}
                  aria-label={t(
                    'match_elements.detail_for',
                    'Open detail panel for {{label}}',
                    { label: g.display_label || g.group_key },
                  )}
                  className="px-2 py-1 text-xs rounded border border-indigo-200 dark:border-indigo-800 text-indigo-700 dark:text-indigo-200 hover:bg-indigo-50 dark:hover:bg-indigo-900/30 inline-flex items-center gap-1 transition"
                >
                  {t('match_elements.detail', 'Detail')}{' '}
                  <ChevronRight className="w-3 h-3" />
                </button>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ─────────────────────────────────────────────────────────────────────────
//  Page
// ─────────────────────────────────────────────────────────────────────────

export function MatchElementsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const addToast = useToastStore((s) => s.addToast);
  const [searchParams] = useSearchParams();

  const [activeBimModelId, setActiveBimModelId] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [showTextModal, setShowTextModal] = useState(false);
  const [showExcelModal, setShowExcelModal] = useState(false);
  // Set by the wizard's onComplete the moment a session is created and a
  // match is kicked off. The MatchProgressCard takes over the viewport
  // until the kickoff mutation resolves; clearing this flag hands back
  // to the regular results UI. Surviving the brief race between "session
  // created" and "results pane first paint" matters — without this flag
  // we'd flash the empty results pane before the card ever painted.
  const [matchInFlight, setMatchInFlight] = useState(false);
  // Drives the MatchProgressCard. ``running`` is the default while the
  // kickoff is in flight; ``done`` finalises the timeline; ``error``
  // shows the retry footer with the message captured below. Decoupled
  // from ``matchInFlight`` so we can keep the card mounted on error
  // until the user clicks "Try again".
  const [matchStatus, setMatchStatus] = useState<
    'running' | 'done' | 'error'
  >('running');
  const [matchError, setMatchError] = useState<string | null>(null);
  // Tracks where the in-flight match came from so the progress card's
  // "Try again" button can do the right thing: wizard kickoffs send the
  // user back to Step 4 (clear sessionId), toolbar re-runs stay on the
  // current session (clear only matchInFlight).
  const [matchKickoffFrom, setMatchKickoffFrom] = useState<
    'wizard' | 'toolbar'
  >('wizard');

  // AbortController for the in-flight runMatch fetch. Stored in a ref
  // (not state) so the cancel handler in MatchProgressCard can fire
  // it without retriggering a re-render. Replaced on every kickoff
  // (wizard or toolbar) so a stale controller from a previous run
  // can never accidentally abort the current one. ``null`` between
  // runs.
  const runMatchAbortRef = useRef<AbortController | null>(null);

  // Honour the ?project=<id> deep-link: if the URL names a project that
  // differs from the active one, switch the store. This is what makes
  // /match-elements?project=<uuid> universal — the page actually shows
  // the requested project, not whichever one happens to be in the store.
  useEffect(() => {
    const urlProjectId = searchParams.get('project');
    if (!urlProjectId) return;
    if (urlProjectId === useProjectContextStore.getState().activeProjectId) return;
    (async () => {
      try {
        const list = await projectsApi.list();
        const target = list.find((p) => p.id === urlProjectId);
        if (target) {
          useProjectContextStore.getState().setActiveProject(target.id, target.name);
        }
      } catch {
        /* graceful — page already handles no-project state */
      }
    })();
  }, [searchParams]);

  // Auto-pick the first project when none is active AND no URL param. Mirrors
  // the pattern in /reports, /boq, /finance — saves a click when the user
  // lands here from navigation without going through the project picker.
  const hasLoadedProjects = useRef(false);
  useEffect(() => {
    if (hasLoadedProjects.current) return;
    if (searchParams.get('project')) return;  // URL handler wins
    hasLoadedProjects.current = true;
    (async () => {
      try {
        const data = await projectsApi.list();
        const { activeProjectId: currentActive, setActiveProject: setProj } =
          useProjectContextStore.getState();
        if (!currentActive && data.length > 0) {
          const first = data[0]!;
          setProj(first.id, first.name);
        }
      } catch {
        /* graceful — page already handles no-project state */
      }
    })();
  }, [searchParams]);

  const [statusFilter, setStatusFilter] = useState<string>('');
  const [tradeFilter, setTradeFilter] = useState<TradeBucket[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openGroup, setOpenGroup] = useState<GroupSummary | null>(null);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [showAllGroupKeys, setShowAllGroupKeys] = useState(false);
  // Header info popover — describes what /match-elements does in plain
  // language. Single boolean toggled by clicking the "(i)" icon next to
  // the page title; closes on outside-click or Escape.
  const [infoOpen, setInfoOpen] = useState(false);
  useEffect(() => {
    if (!infoOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setInfoOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [infoOpen]);

  // Project metadata (region) — needed at the page scope so we can pin the
  // matching catalogue row in CataloguesPanelCard. Shares the React Query
  // cache with ProjectContextCard (same queryKey), so this is one fetch.
  const projectMetaQ = useQuery({
    enabled: !!projectId,
    queryKey: ['project', projectId],
    queryFn: () => projectsApi.get(projectId!),
  });
  const projectRegion = projectMetaQ.data?.region ?? null;

  // ── BIM models for the current project ───────────────────────────────
  const bimModelsQ = useQuery({
    enabled: !!projectId,
    queryKey: ['match-bim-models', projectId],
    queryFn: () => matchElementsApi.listBIMModels(projectId!),
  });

  useEffect(() => {
    if (!activeBimModelId && bimModelsQ.data && bimModelsQ.data.length > 0) {
      const ready = bimModelsQ.data.find((m) => m.status === 'ready');
      if (ready) setActiveBimModelId(ready.id);
    }
  }, [bimModelsQ.data, activeBimModelId]);

  // Reset session/selection when the project changes.
  useEffect(() => {
    setSessionId(null);
    setActiveBimModelId(null);
    setSelected(new Set());
    setMatchInFlight(false);
    setMatchStatus('running');
    setMatchError(null);
  }, [projectId]);

  // ── Sessions for the resume picker ───────────────────────────────────
  const sessionsQ = useQuery({
    enabled: !!projectId,
    queryKey: ['match-sessions', projectId],
    queryFn: () => matchElementsApi.listSessions(projectId!, { limit: 10 }),
  });

  // Kept for the "+ New match" button below (still used to clear any
  // in-flight selected groups, even though the auto-pick effect is gone).
  // The auto-pick was removed: it was selecting the most-recent session
  // on every mount, which made the wizard unreachable on any project
  // that already had a session — confusing first-time UX. Power users
  // can resume via the wizard's Resume strip (1 click) or via the
  // ``?session=<id>`` deep-link below.
  const userOptedOutOfAutoPick = useRef(false);

  // Deep-link auto-pick: when the URL carries `?session=<id>`, honour
  // it once on mount. This preserves bookmarks / "open in new tab"
  // from elsewhere in the app without hijacking the wizard for fresh
  // landings.
  useEffect(() => {
    if (sessionId) return;
    const urlSessionId = searchParams.get('session');
    if (!urlSessionId) return;
    setSessionId(urlSessionId);
  }, [searchParams, sessionId]);

  // ── Active session details ───────────────────────────────────────────
  const sessionQ = useQuery({
    enabled: !!sessionId,
    queryKey: ['match-session', sessionId],
    queryFn: () => matchElementsApi.getSession(sessionId!),
  });

  // ── Groups for the active session ────────────────────────────────────
  const groupsQ = useQuery({
    enabled: !!sessionId,
    queryKey: ['match-groups', sessionId, statusFilter],
    queryFn: () =>
      matchElementsApi.listGroups(sessionId!, {
        status: statusFilter || undefined,
        limit: 500,
      }),
  });

  // ── Attribute keys (drives the group-by chip-bar) ─────────────────────
  // Sampled from the bound BIM model — surfaces every attribute the user
  // can group by (ifc_class, type_name, family, material, level, …).
  const attributeKeysQ = useQuery({
    enabled: !!sessionId,
    queryKey: ['match-attributes', sessionId],
    queryFn: () => matchElementsApi.listAttributes(sessionId!),
    // Attribute keys are derived from the model — they don't change between
    // group-by toggles, so don't refetch on every PATCH.
    staleTime: 5 * 60_000,
  });

  // ── Mutations ────────────────────────────────────────────────────────
  const createSessionMut = useMutation({
    mutationFn: async () => {
      if (!projectId) throw new Error('No active project');
      return matchElementsApi.createSession({
        project_id: projectId,
        bim_model_id: activeBimModelId,
        source: 'bim',
        // null = use server-side default subtractive set.
        excluded_categories: null,
      });
    },
    onSuccess: (s: MatchSession) => {
      setSessionId(s.id);
      qc.invalidateQueries({ queryKey: ['match-sessions', projectId] });
    },
    onError: (e: Error) => setError(e.message),
  });

  const updateSessionMut = useMutation({
    mutationFn: async (
      patch: Parameters<typeof matchElementsApi.updateSession>[1],
    ) => {
      if (!sessionId) throw new Error('No session');
      return matchElementsApi.updateSession(sessionId, patch);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['match-session', sessionId] });
      qc.invalidateQueries({ queryKey: ['match-groups', sessionId] });
    },
  });

  const runMatchMut = useMutation({
    mutationFn: async (method: MatcherName) => {
      if (!sessionId) throw new Error('No session');
      const keys = selected.size > 0 ? Array.from(selected) : undefined;
      setBusy(
        keys
          ? t(
              'match_elements.busy.run_selected',
              'Running {{method}} matcher on {{count}} selected…',
              { method, count: keys.length },
            )
          : t(
              'match_elements.busy.run_all',
              'Running {{method}} matcher on all groups…',
              { method },
            ),
      );
      // Surface the progress card for toolbar-driven re-runs too — the
      // card polls /progress for real-stage updates and the abort
      // controller below lets the Cancel button reach the in-flight
      // fetch when a backend gets wedged.
      setMatchInFlight(true);
      setMatchStatus('running');
      setMatchError(null);
      setMatchKickoffFrom('toolbar');

      // Replace any stale controller and wire the new one into the
      // fetch so the progress card's Cancel button aborts the right
      // request. Hard 5-minute safety limit — the longest healthy run
      // we've measured is ~80s; anything beyond is a wedged backend.
      runMatchAbortRef.current?.abort();
      const ac = new AbortController();
      runMatchAbortRef.current = ac;
      const timeoutId = window.setTimeout(() => ac.abort(), 5 * 60_000);
      try {
        return await matchElementsApi.runMatch(
          sessionId,
          { method, top_k: 10, max_groups: 50, group_keys: keys },
          { signal: ac.signal },
        );
      } finally {
        window.clearTimeout(timeoutId);
        if (runMatchAbortRef.current === ac) runMatchAbortRef.current = null;
      }
    },
    onSuccess: () => {
      setBusy(null);
      setError(null);
      setMatchStatus('done');
      qc.invalidateQueries({ queryKey: ['match-groups', sessionId] });
    },
    onError: (e: Error) => {
      setBusy(null);
      setError(e.message);
      setMatchStatus('error');
      setMatchError(e.message);
    },
  });

  const bulkConfirmMut = useMutation({
    mutationFn: async () => {
      if (!sessionId) throw new Error('No session');
      const threshold = sessionQ.data?.auto_confirm_threshold ?? 0.95;
      const keys = selected.size > 0 ? Array.from(selected) : undefined;
      setBusy(
        keys
          ? t(
              'match_elements.busy.bulk_confirm_selected',
              'Bulk-confirming {{count}} selected ≥ {{thr}}…',
              { count: keys.length, thr: threshold.toFixed(2) },
            )
          : t(
              'match_elements.busy.bulk_confirm_all',
              'Bulk-confirming matches ≥ {{thr}}…',
              { thr: threshold.toFixed(2) },
            ),
      );
      return matchElementsApi.bulkConfirm(sessionId, {
        threshold,
        group_keys: keys,
      });
    },
    onSuccess: (r) => {
      setBusy(null);
      setError(null);
      qc.invalidateQueries({ queryKey: ['match-groups', sessionId] });
      qc.invalidateQueries({ queryKey: ['match-sessions', projectId] });
      setSelected(new Set());
      addToast({
        type: 'success',
        title: t('match_elements.alert.confirmed', 'Confirmed {{count}} groups', {
          count: r.confirmed_count,
        }),
      });
    },
    onError: (e: Error) => {
      setBusy(null);
      setError(e.message);
      addToast({
        type: 'error',
        title: t('match_elements.alert.bulk_confirm_failed', 'Bulk confirm failed'),
        message: e.message,
      });
    },
  });

  const applyMut = useMutation({
    mutationFn: async () => {
      if (!sessionId) throw new Error('No session');
      setBusy(
        t(
          'match_elements.busy.applying',
          'Applying confirmed groups to BOQ…',
        ),
      );
      return matchElementsApi.apply(sessionId, { dry_run: false });
    },
    onSuccess: (r) => {
      setBusy(null);
      setError(null);
      qc.invalidateQueries({ queryKey: ['match-groups', sessionId] });
      qc.invalidateQueries({ queryKey: ['match-sessions', projectId] });
      addToast({
        type: 'success',
        title: t(
          'match_elements.alert.applied',
          'Created {{n}} BOQ positions · total {{total}} {{ccy}}',
          {
            n: r.positions_created,
            total: fmtNum(r.grand_total),
            ccy: r.currency ?? '',
          },
        ),
      });
    },
    onError: (e: Error) => {
      setBusy(null);
      setError(e.message);
      addToast({
        type: 'error',
        title: t('match_elements.alert.apply_failed', 'Apply to BOQ failed'),
        message: e.message,
      });
    },
  });

  const skipBulkMut = useMutation({
    mutationFn: async () => {
      if (!sessionId) throw new Error('No session');
      const keys = Array.from(selected);
      setBusy(
        t('match_elements.busy.mark_tbd', 'Marking {{count}} groups as TBD…', {
          count: keys.length,
        }),
      );
      await Promise.all(
        keys.map((k) =>
          matchElementsApi.noMatch(sessionId, { group_key: k, action: 'tbd' }),
        ),
      );
      return keys.length;
    },
    onSuccess: (n) => {
      setBusy(null);
      qc.invalidateQueries({ queryKey: ['match-groups', sessionId] });
      setSelected(new Set());
      addToast({
        type: 'success',
        title: t('match_elements.alert.marked_tbd', 'Marked {{count}} groups as TBD', {
          count: n,
        }),
      });
    },
    onError: (e: Error) => {
      setBusy(null);
      setError(e.message);
      addToast({
        type: 'error',
        title: t('match_elements.alert.skip_failed', 'Skip failed'),
        message: e.message,
      });
    },
  });

  // Re-bind session to a different BIM model when the user picks a tab
  // and the active session targets a different (or no) model.
  const bindSessionToModelMut = useMutation({
    mutationFn: async (modelId: string) => {
      if (!sessionId) throw new Error('No session');
      return matchElementsApi.updateSession(sessionId, {
        bim_model_id: modelId,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['match-session', sessionId] });
      qc.invalidateQueries({ queryKey: ['match-groups', sessionId] });
    },
  });

  // ── Derived ──────────────────────────────────────────────────────────
  const summary = groupsQ.data?.summary ?? {};
  const visibleGroups = useMemo(() => {
    const all = groupsQ.data?.groups ?? [];
    if (tradeFilter.length === 0) return all;
    const set = new Set(tradeFilter);
    return all.filter((g) => set.has(g.trade));
  }, [groupsQ.data, tradeFilter]);

  const allVisibleSelected =
    visibleGroups.length > 0 &&
    visibleGroups.every((g) => selected.has(g.group_key));

  const toggleAll = () => {
    if (allVisibleSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(visibleGroups.map((g) => g.group_key)));
    }
  };
  const toggleOne = (key: string) => {
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSelected(next);
  };

  // Primary CTA morphs depending on state.
  const confirmedCount = summary.confirmed ?? 0;
  const suggestedCount = summary.suggested ?? 0;
  const unmatchedCount = summary.unmatched ?? 0;
  const primaryCta: 'run' | 'confirm' | 'apply' | 'idle' = !sessionId
    ? 'idle'
    : suggestedCount === 0 && unmatchedCount > 0
      ? 'run'
      : confirmedCount > 0 && suggestedCount === 0
        ? 'apply'
        : suggestedCount > 0
          ? 'confirm'
          : 'run';

  // One pass over groups → counts per trade + per status. Avoids 8 filter
  // passes per render (one per trade) plus 3 separate filter passes for
  // the stepper. With 1000+ groups this dropped a tier-1 render from
  // ~12ms to ~2ms in DevTools.
  const groupAgg = useMemo(() => {
    const groups = groupsQ.data?.groups ?? [];
    const tradeCounts: Record<string, number> = {};
    let confirmed = 0;
    let applied = 0;
    for (const g of groups) {
      tradeCounts[g.trade] = (tradeCounts[g.trade] ?? 0) + 1;
      if (g.status === 'confirmed' || g.status === 'applied') confirmed += 1;
      if (g.status === 'applied') applied += 1;
    }
    return { total: groups.length, tradeCounts, confirmed, applied };
  }, [groupsQ.data?.groups]);

  const tradeChips: Chip<TradeBucket>[] = useMemo(
    () =>
      (
        [
          'architectural',
          'structural',
          'mep',
          'civil',
          'spatial',
          'subtractive',
          'annotation',
          'other',
        ] as const
      ).map((b) => ({
        value: b,
        label: t(`match_elements.trade.${b}`, b),
        count: groupAgg.tradeCounts[b] ?? 0,
      })),
    [groupAgg.tradeCounts, t],
  );

  const visibleSession = sessionQ.data;
  const threshold = visibleSession?.auto_confirm_threshold ?? 0.95;
  const useNet = visibleSession?.use_net_quantities ?? true;
  const stage: ConstructionStage | '' =
    visibleSession?.construction_stage ?? '';

  // ── Render ───────────────────────────────────────────────────────────
  // Derive workflow step (1-4) from current state to drive the step
  // indicator. Step transitions are intentionally one-way semaphores —
  // once you reach a step you stay until the prior signal goes missing.
  const stepperTotalGroups = groupAgg.total;
  const stepperConfirmedCount = groupAgg.confirmed;
  const stepperAppliedCount = groupAgg.applied;

  const workflowStep: 1 | 2 | 3 | 4 = !activeBimModelId
    ? 1
    : !sessionId
      ? 2
      : stepperAppliedCount > 0
        ? 4
        : 3;

  return (
    <div className="p-3 lg:p-4 max-w-[1600px] mx-auto">
      {/* Qdrant readiness — only renders when vector DB is unreachable.
          One-click "Install Qdrant (no Docker)" + Refresh. Mounted above
          the hero so a fresh install can't proceed past a broken vector
          stack without seeing the fix. */}
      <QdrantHealthCard />
      {/* Hero — single compact row. Eyebrow chip + title inline; subtitle
          dropped (the rest of the page makes the purpose obvious) and the
          oversized icon + decorative blur removed to claw back ~120px of
          vertical real-estate that used to push the actual workflow below
          the fold. */}
      <section className="rounded-xl border border-indigo-200/60 dark:border-indigo-800/60 bg-gradient-to-r from-indigo-50/80 via-white to-sky-50/60 dark:from-indigo-950/30 dark:via-surface-primary dark:to-sky-950/20 mb-2 shadow-sm">
        <div className="px-3 py-2 lg:px-4 lg:py-2.5 flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="shrink-0 w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-500 to-sky-500 text-white inline-flex items-center justify-center shadow-sm">
              <Link2 className="w-3.5 h-3.5" />
            </span>
            <h1 className="text-base lg:text-lg leading-none font-semibold text-content-primary">
              {t('match_elements.title', 'Match Elements')}
            </h1>
            {/* Info popover — explains the page in plain language for
                first-time visitors. Anchored to the title so the user
                instinctively looks here when they wonder "wait, what
                does this actually do?". Subtle styling — content-tertiary
                stroke so it doesn't compete with the workflow indicator
                — but explicitly button-shaped + aria-labelled so it's
                discoverable to keyboard / screen-reader users too. */}
            <div className="relative inline-block">
              <button
                type="button"
                onClick={() => setInfoOpen((v) => !v)}
                aria-expanded={infoOpen}
                aria-label={t(
                  'match_elements.info.button_aria',
                  'How matching works',
                )}
                title={t(
                  'match_elements.info.button_title',
                  'How matching works',
                )}
                className="text-content-tertiary hover:text-content-secondary transition-colors inline-flex items-center justify-center w-5 h-5 rounded-full hover:bg-surface-secondary"
              >
                <Info className="w-4 h-4" strokeWidth={2} />
              </button>
              {infoOpen && (
                <>
                  {/* Click-outside catcher — covers the rest of the page
                      so any tap dismisses without nuking the click that
                      triggered it. Lower z-index than the panel so the
                      panel stays interactive. */}
                  <div
                    className="fixed inset-0 z-40"
                    onClick={() => setInfoOpen(false)}
                    aria-hidden
                  />
                  <div
                    role="dialog"
                    aria-label={t(
                      'match_elements.info.dialog_aria',
                      'How matching works',
                    )}
                    className="absolute left-0 top-7 z-50 w-80 rounded-xl border border-border-light bg-surface-primary shadow-xl p-4 text-sm text-content-secondary leading-relaxed"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <h3 className="text-sm font-semibold text-content-primary">
                        {t(
                          'match_elements.info.title',
                          'How matching works',
                        )}
                      </h3>
                      <button
                        type="button"
                        onClick={() => setInfoOpen(false)}
                        aria-label={t('common.close', 'Close')}
                        className="text-content-tertiary hover:text-content-primary -mr-1 -mt-1 w-6 h-6 rounded inline-flex items-center justify-center"
                      >
                        <XCircle className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    <ul className="space-y-1.5 text-[13px] list-disc list-outside ms-4 marker:text-content-tertiary">
                      <li>
                        {t(
                          'match_elements.info.bullet_upload',
                          'Upload your BIM model or BoQ.',
                        )}
                      </li>
                      <li>
                        {t(
                          'match_elements.info.bullet_extract',
                          'We extract elements: descriptions, units, quantities, regions, classification.',
                        )}
                      </li>
                      <li>
                        {t(
                          'match_elements.info.bullet_search',
                          'Each element is searched against the selected cost catalogue using vector similarity + lexical hints + region/unit boost.',
                        )}
                      </li>
                      <li>
                        {t(
                          'match_elements.info.bullet_shortlist',
                          'You get a confidence-scored shortlist per element — pick the best, edit quantity if needed.',
                        )}
                      </li>
                      <li>
                        {t(
                          'match_elements.info.bullet_save',
                          'Save the session — you can revisit, edit, and export it as BoQ later.',
                        )}
                      </li>
                    </ul>
                    <p className="mt-3 pt-2.5 border-t border-border-light text-[12px] text-content-tertiary">
                      {t(
                        'match_elements.info.footer',
                        'Saved sessions live in the list on this page.',
                      )}
                    </p>
                  </div>
                </>
              )}
            </div>
            <span className="hidden sm:inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider font-semibold text-indigo-700 dark:text-indigo-200 bg-white/60 dark:bg-surface-primary/40 border border-indigo-200/70 dark:border-indigo-700/40">
              <Sparkles className="w-2.5 h-2.5" />
              {t('match_elements.hero_eyebrow', 'BIM → BOQ')}
            </span>
            {projectId && (
              <div className="hidden md:block flex-1 min-w-0 ms-2">
                <WorkflowStepIndicator
                  step={workflowStep}
                  totalGroups={stepperTotalGroups}
                  confirmedCount={stepperConfirmedCount}
                  appliedCount={stepperAppliedCount}
                  hasModel={!!activeBimModelId}
                  hasSession={!!sessionId}
                />
              </div>
            )}
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            {/* "New match" — opens the wizard. Visible only inside the
                in-session view; in wizard view itself the button would be
                redundant (the user is already there). Sets the opt-out
                ref so the auto-resume effect doesn't immediately yank
                them back into the session they just left. */}
            {sessionId && (
              <button
                type="button"
                onClick={() => {
                  userOptedOutOfAutoPick.current = true;
                  setSessionId(null);
                  setSelected(new Set());
                }}
                aria-label={t(
                  'match_elements.new_match_title',
                  'Start a new match — opens the wizard',
                )}
                className="px-2.5 py-1 text-xs rounded-lg bg-gradient-to-br from-indigo-500 to-indigo-700 text-white shadow-sm shadow-indigo-500/25 hover:shadow-md hover:shadow-indigo-500/35 hover:-translate-y-px inline-flex items-center gap-1 font-medium transition-all"
                title={t(
                  'match_elements.new_match_title',
                  'Start a new match — opens the wizard',
                )}
              >
                <Sparkles className="w-3.5 h-3.5" />
                {t('match_elements.new_match', 'New match')}
              </button>
            )}
            <button
              type="button"
              onClick={() => setTemplatesOpen(true)}
              aria-label={t(
                'match_elements.library_title',
                'Cross-project template library',
              )}
              className="px-2.5 py-1 text-xs rounded-lg border border-indigo-200 dark:border-indigo-800 bg-white/80 dark:bg-surface-primary/80 hover:bg-white dark:hover:bg-surface-secondary inline-flex items-center gap-1 font-medium text-content-secondary hover:text-content-primary transition"
              title={t(
                'match_elements.library_title',
                'Cross-project template library',
              )}
            >
              <Library className="w-3.5 h-3.5" />
              {t('match_elements.library', 'Library')}
            </button>
            <button
              type="button"
              onClick={() =>
                qc.invalidateQueries({ queryKey: ['match-groups', sessionId] })
              }
              disabled={!sessionId}
              aria-label={t(
                'match_elements.refresh_title',
                'Refresh — pulls latest BIM elements',
              )}
              className="p-1.5 rounded-lg border border-indigo-200 dark:border-indigo-800 bg-white/80 dark:bg-surface-primary/80 hover:bg-white dark:hover:bg-surface-secondary disabled:opacity-40 disabled:cursor-not-allowed transition"
              title={t(
                'match_elements.refresh_title',
                'Refresh — pulls latest BIM elements',
              )}
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
        {/* Mobile-only workflow indicator (the desktop one is inline in
            the hero strip above; on narrow screens we drop it to a second
            row to avoid wrap-overflow). */}
        {projectId && (
          <div className="md:hidden px-3 pb-2">
            <WorkflowStepIndicator
              step={workflowStep}
              totalGroups={stepperTotalGroups}
              confirmedCount={stepperConfirmedCount}
              appliedCount={stepperAppliedCount}
              hasModel={!!activeBimModelId}
              hasSession={!!sessionId}
            />
          </div>
        )}
      </section>

      {/* "Beta · feedback wanted" banner.
          /match-elements is the newest top-level feature in the product
          and still has rough edges (catalogue install retries, occasional
          stale-cache shape mismatches, ranker tuning). The banner sets
          the right expectation and gives the user a 1-click path to file
          an issue against the public repo so feedback doesn't sit in DMs.
          Kept compact — single row, dismiss-free (the message stays
          relevant for the whole beta period). */}
      <div className="mb-2 rounded-xl border border-amber-200/60 dark:border-amber-800/40 bg-gradient-to-r from-amber-50/80 via-white to-white dark:from-amber-950/20 dark:via-surface-primary dark:to-surface-primary px-3 py-2 flex items-center gap-2.5 flex-wrap shadow-sm">
        <span className="shrink-0 inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wider font-bold text-amber-900 dark:text-amber-100 bg-amber-100/80 dark:bg-amber-900/40 border border-amber-300/60 dark:border-amber-700/40">
          <Sparkles className="w-2.5 h-2.5" />
          {t('match_elements.beta_badge', 'Beta')}
        </span>
        <p className="text-xs text-content-secondary leading-snug min-w-0 flex-1">
          {t(
            'match_elements.beta_blurb',
            'Match Elements is a new section and still has rough edges. Found a bug or have an idea? Please file an issue — every report tightens the next release.',
          )}
        </p>
        <a
          href="https://github.com/datadrivenconstruction/OpenConstructionERP/issues/new?labels=match-elements&template=bug_report.yml"
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-semibold text-amber-900 dark:text-amber-100 bg-white/90 dark:bg-surface-primary/80 border border-amber-300/60 dark:border-amber-700/40 hover:bg-amber-50 dark:hover:bg-amber-900/30 hover:-translate-y-px transition-all shadow-sm"
        >
          <MessageSquarePlus className="w-3 h-3" />
          {t('match_elements.beta_cta', 'Open an issue')}
          <ExternalLink className="w-2.5 h-2.5 opacity-70" />
        </a>
      </div>

      <ProjectContextCard projectId={projectId} />

      {/* Pipeline entry card — the headline path. Shown when a project
          is picked but no session is active yet. One click creates a
          session and drops the user straight into the visible 7-stage
          pipeline. The legacy step-wizard stays below for power users
          who want to pre-pick catalogue / source / construction stage. */}
      {projectId && !sessionId && !matchInFlight && (
        <div className="mt-2 rounded-xl border border-indigo-200/70 dark:border-indigo-800/50 bg-gradient-to-br from-indigo-50/80 via-white to-white dark:from-indigo-950/30 dark:via-surface-primary dark:to-surface-primary p-4 shadow-sm">
          <div className="flex items-start gap-3 flex-wrap">
            <span className="w-9 h-9 rounded-xl bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-200 inline-flex items-center justify-center shrink-0">
              <Layers className="w-5 h-5" />
            </span>
            <div className="min-w-0 flex-1">
              <h3 className="text-base font-bold text-content-primary">
                {t(
                  'match_elements.pipeline.intro_title',
                  'Open the visible match pipeline',
                )}
              </h3>
              <p className="text-xs text-content-secondary mt-0.5 leading-relaxed">
                {t(
                  'match_elements.pipeline.intro_blurb',
                  'Seven steps from CAD file to priced BoQ — Convert, Load, Schema, Filter, Group, Match, Rollup. Every step is visible, explained, and tunable (prompts, LLM provider, group keys).',
                )}
              </p>
              <div className="flex items-center gap-1.5 flex-wrap mt-2">
                {[
                  'Convert',
                  'Load',
                  'Schema',
                  'Filter',
                  'Group',
                  'Match',
                  'Rollup',
                ].map((s, i) => (
                  <span
                    key={s}
                    className="inline-flex items-center gap-1 text-[10px] font-semibold text-content-tertiary"
                  >
                    <span className="px-1.5 py-0.5 rounded bg-surface-secondary border border-border">
                      {i + 1}. {s}
                    </span>
                    {i < 6 && (
                      <ChevronsRight className="w-2.5 h-2.5 opacity-50" />
                    )}
                  </span>
                ))}
              </div>
            </div>
            <div className="flex flex-col gap-1.5 shrink-0">
              <button
                onClick={() => createSessionMut.mutate()}
                disabled={createSessionMut.isPending}
                className="inline-flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm font-semibold bg-oe-blue text-white hover:opacity-90 disabled:opacity-50"
              >
                {createSessionMut.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <PlayCircle className="w-4 h-4" />
                )}
                {t(
                  'match_elements.pipeline.intro_cta',
                  'Open the pipeline',
                )}
              </button>
              {(sessionsQ.data?.length ?? 0) > 0 && (
                <button
                  onClick={() => {
                    const last = sessionsQ.data?.[0];
                    if (last) setSessionId(last.id);
                  }}
                  className="inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-border text-content-secondary hover:bg-surface-secondary"
                >
                  <RefreshCw className="w-3 h-3" />
                  {t(
                    'match_elements.pipeline.intro_resume',
                    'Resume last session',
                  )}
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* New wizard entry — visible only when no session is active.
          The wizard guides the user through stage → catalogue → source →
          run, then sets sessionId via onComplete to drop them into the
          existing matching/results UI. Power users with a saved session
          (or who pick one in the wizard's Resume strip) skip straight
          past this and see the full toolset below. */}
      {projectId && !sessionId && (
        <MatchWizard
          projectId={projectId}
          projectRegion={projectRegion}
          sessions={sessionsQ.data ?? []}
          onComplete={(id, abortController) => {
            // Session exists — mount the progress card on top of the
            // wizard slot. The wizard continues to await runMatch in
            // the background; matchStatus stays "running" until the
            // wizard fires onMatchSuccess or onMatchError below.
            // The AbortController feeds the in-flight fetch so the
            // progress card's Cancel button can reach it.
            setSessionId(id);
            setMatchInFlight(true);
            setMatchStatus('running');
            setMatchError(null);
            setMatchKickoffFrom('wizard');
            runMatchAbortRef.current?.abort();
            runMatchAbortRef.current = abortController ?? null;
          }}
          onMatchSuccess={() => {
            setMatchStatus('done');
          }}
          onMatchError={(_id, message) => {
            setMatchStatus('error');
            setMatchError(message);
          }}
          onResume={(id) => {
            // Resume path — no kickoff is happening, so don't mount the
            // progress card. User goes straight to the results UI.
            setSessionId(id);
          }}
        />
      )}

      {projectId && sessionId && matchInFlight && (
        <MatchProgressCard
          status={matchStatus}
          errorMessage={matchError}
          sessionId={sessionId}
          onDone={() => {
            setMatchInFlight(false);
            setMatchStatus('running');
            setMatchError(null);
            qc.invalidateQueries({ queryKey: ['match-groups', sessionId] });
            qc.invalidateQueries({ queryKey: ['match-session', sessionId] });
            qc.invalidateQueries({ queryKey: ['match-sessions', projectId] });
          }}
          onCancel={() => {
            // Fire the AbortController feeding the in-flight runMatch
            // fetch. The fetch then rejects with AbortError; the
            // mutation's ``onError`` flips ``matchStatus`` to ``error``
            // with the cancellation message so the user sees the
            // retry button instead of a stuck spinner.
            runMatchAbortRef.current?.abort();
          }}
          onRetry={() => {
            // Wizard kickoffs send the user back to Step 1 of the
            // wizard (sessionId cleared); toolbar re-runs stay on the
            // current session and just dismiss the card so the user
            // can hit the toolbar button again. The wizard remounts
            // from Step 1 — the user keeps their region context but
            // re-picks stage / catalogue / source. Lifting picks into
            // the parent is a later optimisation.
            setMatchInFlight(false);
            setMatchStatus('running');
            setMatchError(null);
            if (matchKickoffFrom === 'wizard') {
              setSessionId(null);
            }
          }}
        />
      )}

      {projectId && sessionId && !matchInFlight && (
        <>
          {/* Visible 7-stage pipeline — the headline UX. Sits above the
              classic toolset so the estimator sees every step (Convert →
              Load → Schema → Filter → Group → Match → Rollup), each with
              status, output preview and a per-stage Adjust panel for
              prompts / LLM provider / knobs. Collapsible — collapsing it
              returns to the legacy single-shot flow below. */}
          <MatchPipeline sessionId={sessionId} />

          {/* System-readiness row — three status cards (Catalogues +
              Embedder + Analytics) share a single horizontal row at lg+,
              stack vertically on smaller screens. Before this change they
              consumed ~240px of stacked height before the actual workflow
              became visible; the grid reclaims that for the matching
              table itself. */}
          <div className="mt-2 grid grid-cols-1 lg:grid-cols-3 gap-2">
            <CataloguesPanelCard preferredRegion={projectRegion} />
            <EmbedderStatusCard />
            <MatchAnalyticsCard projectId={projectId} />
          </div>

          {/* Steps 1 + 2 — BIM model and session are both "source picking";
              putting them side-by-side at lg+ lets the user see model
              choice and current session in one glance and removes ~120px
              of stacked padding. */}
          <div className="mt-2 grid grid-cols-1 lg:grid-cols-2 gap-2">
            {/* Step 1 — BIM model picker */}
            <section className="p-3 rounded-xl border border-border bg-surface-primary shadow-sm">
              <div className="flex items-center justify-between gap-2 mb-2">
                <h3 className="text-xs uppercase tracking-wider text-content-tertiary font-semibold inline-flex items-center gap-1.5">
                  <span className="w-4 h-4 rounded-md bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-200 inline-flex items-center justify-center text-[10px] font-bold">
                    1
                  </span>
                  {t('match_elements.region_bim_models', 'BIM model')}
                </h3>
                <span
                  className="text-[10px] text-content-tertiary truncate"
                  title={t(
                    'match_elements.region_bim_models_help',
                    'Pick the source model — quantities are read from here',
                  )}
                >
                  {t(
                    'match_elements.region_bim_models_help',
                    'Pick the source model — quantities are read from here',
                  )}
                </span>
              </div>
              <BIMModelPicker
                models={bimModelsQ.data ?? []}
                activeModelId={activeBimModelId}
                isLoading={bimModelsQ.isLoading}
                onSelect={(id) => {
                  setActiveBimModelId(id);
                  if (sessionId && visibleSession?.bim_model_id !== id) {
                    bindSessionToModelMut.mutate(id);
                  }
                }}
              />
            </section>

            {/* Step 2 — Session resume picker */}
            <section className="p-3 rounded-xl border border-border bg-surface-primary shadow-sm">
              <div className="flex items-center justify-between gap-2 mb-2">
                <h3 className="text-xs uppercase tracking-wider text-content-tertiary font-semibold inline-flex items-center gap-1.5">
                  <span className="w-4 h-4 rounded-md bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-200 inline-flex items-center justify-center text-[10px] font-bold">
                    2
                  </span>
                  {t('match_elements.region_sessions', 'Matching session')}
                </h3>
                <span
                  className="text-[10px] text-content-tertiary truncate"
                  title={t(
                    'match_elements.region_sessions_help',
                    'Resume an existing run or start a new one',
                  )}
                >
                  {t(
                    'match_elements.region_sessions_help',
                    'Resume an existing run or start a new one',
                  )}
                </span>
              </div>
              <SessionPicker
                projectId={projectId}
                sessions={sessionsQ.data ?? []}
                isLoading={sessionsQ.isLoading}
                activeSessionId={sessionId}
                onPick={(id) => {
                  setSessionId(id);
                  matchElementsApi.touchSession(id).catch(() => {});
                }}
                onCreate={() => createSessionMut.mutate()}
                onCreateText={() => setShowTextModal(true)}
                onCreateExcel={() => setShowExcelModal(true)}
                isCreating={createSessionMut.isPending}
              />
            </section>
          </div>

          {/* Step 3 — Group-by chip-bar (drives how elements are grouped) */}
          {sessionId && visibleSession && (
            <div className="mt-2 p-3 rounded-xl border border-border bg-surface-primary shadow-sm">
              <div className="flex items-center justify-between gap-2 mb-2">
                <div className="text-xs uppercase tracking-wider text-content-tertiary font-semibold inline-flex items-center gap-1.5">
                  <span className="w-4 h-4 rounded-md bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-200 inline-flex items-center justify-center text-[10px] font-bold">
                    3
                  </span>
                  {t('match_elements.group_by', 'Group by')}
                </div>
                <div className="text-[10px] text-content-tertiary truncate">
                  {visibleSession.group_by.length === 0
                    ? t(
                        'match_elements.group_by_empty',
                        'Pick at least one attribute',
                      )
                    : t(
                        'match_elements.group_by_active',
                        '{{count}} active · click to toggle, drag to reorder',
                        { count: visibleSession.group_by.length },
                      )}
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {/* Active keys first, in user-set order */}
                {visibleSession.group_by.map((k, idx) => (
                  <button
                    key={`active-${k}`}
                    type="button"
                    disabled={updateSessionMut.isPending}
                    onClick={() => {
                      if (updateSessionMut.isPending) return;
                      const next = visibleSession.group_by.filter(
                        (x) => x !== k,
                      );
                      updateSessionMut.mutate({ group_by: next });
                    }}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs bg-indigo-100 text-indigo-800 border border-indigo-300 dark:bg-indigo-900/40 dark:text-indigo-100 dark:border-indigo-500/60 hover:bg-indigo-200 dark:hover:bg-indigo-900/60 disabled:opacity-50 disabled:cursor-wait"
                    title={t(
                      'match_elements.group_by_remove',
                      'Click to remove from grouping',
                    )}
                  >
                    <span className="tabular-nums text-indigo-500 dark:text-indigo-300">
                      {idx + 1}.
                    </span>
                    <span>{k}</span>
                    <XCircle className="w-3 h-3 opacity-60" />
                  </button>
                ))}
                {/* Inactive keys (not yet in group_by) — split into popular + rest */}
                {(() => {
                  const inactive = (attributeKeysQ.data ?? []).filter(
                    (a: AttributeKey) => !visibleSession.group_by.includes(a.key),
                  );
                  const popular = inactive.filter((a) =>
                    POPULAR_GROUP_BY_KEYS.has(a.key),
                  );
                  const rest = inactive.filter(
                    (a) => !POPULAR_GROUP_BY_KEYS.has(a.key),
                  );
                  const renderChip = (a: AttributeKey) => (
                    <button
                      key={`inactive-${a.key}`}
                      type="button"
                      disabled={updateSessionMut.isPending}
                      onClick={() => {
                        if (updateSessionMut.isPending) return;
                        updateSessionMut.mutate({
                          group_by: [...visibleSession.group_by, a.key],
                        });
                      }}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs bg-surface-primary text-content-secondary border border-border hover:border-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-200 disabled:opacity-50 disabled:cursor-wait"
                      title={
                        a.sample_values.length
                          ? `${t('match_elements.group_by_sample', 'e.g.')} ${a.sample_values.slice(0, 3).join(', ')}`
                          : undefined
                      }
                    >
                      <span>{a.key}</span>
                    </button>
                  );
                  return (
                    <>
                      {popular.map(renderChip)}
                      {showAllGroupKeys && rest.map(renderChip)}
                      {rest.length > 0 && (
                        <button
                          type="button"
                          onClick={() => setShowAllGroupKeys((v) => !v)}
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded text-xs text-content-tertiary border border-dashed border-border hover:border-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-200"
                          title={t(
                            'match_elements.group_by_show_all_help',
                            'Tenant-specific attributes from this BIM model',
                          )}
                        >
                          {showAllGroupKeys
                            ? t('match_elements.group_by_show_less', 'Show less')
                            : t(
                                'match_elements.group_by_show_all',
                                'Show all ({{count}})',
                                { count: rest.length },
                              )}
                        </button>
                      )}
                    </>
                  );
                })()}
                {!attributeKeysQ.data && (
                  <span className="text-xs text-content-tertiary px-2 py-1">
                    <Loader2 className="w-3 h-3 inline animate-spin mr-1" />
                    {t('match_elements.loading_attributes', 'Loading…')}
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Step 4 — Settings rail. Two visual groups:
           *   • Match strategy  — threshold + net/gross + stage (drives the matcher)
           *   • Filters        — trade buckets (drives what's visible) */}
          {sessionId && visibleSession && (
            <section className="mt-2 p-3 rounded-xl border border-border bg-surface-primary shadow-sm">
              <div className="flex items-center justify-between gap-2 mb-2">
                <h3 className="text-xs uppercase tracking-wider text-content-tertiary font-semibold inline-flex items-center gap-1.5">
                  <span className="w-4 h-4 rounded-md bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-200 inline-flex items-center justify-center text-[10px] font-bold">
                    4
                  </span>
                  {t('match_elements.region_settings', 'Match settings')}
                </h3>
                <span className="text-[10px] text-content-tertiary truncate">
                  {t(
                    'match_elements.region_settings_help',
                    'Tune how matches are found and what shows up below',
                  )}
                </span>
              </div>
              {/* All three controls use the same FieldShell so labels,
                  controls, and help text sit on the same baselines across
                  the row regardless of the underlying control type. Before
                  the refactor each control rendered its own label style
                  (Slider: uppercase, Toggle: sentence-case inline, Select:
                  uppercase) — the row looked ragged with three different
                  type stacks side-by-side. The shell normalises that. */}
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-x-5 gap-y-4 items-start">
                <FieldShell
                  label={t('match_elements.auto_confirm_threshold', 'Auto-confirm threshold')}
                  help={t(
                    'match_elements.auto_confirm_help',
                    'Suggested matches at or above this score auto-confirm.',
                  )}
                  trailing={
                    <span className="text-sm font-semibold text-content-primary tabular-nums">
                      {threshold.toFixed(2)}
                    </span>
                  }
                >
                  <input
                    type="range"
                    min={0.5}
                    max={1.0}
                    step={0.01}
                    value={threshold}
                    onChange={(e) =>
                      updateSessionMut.mutate({
                        auto_confirm_threshold: Number(e.target.value),
                      })
                    }
                    disabled={updateSessionMut.isPending}
                    className="block w-full accent-oe-blue cursor-pointer disabled:cursor-not-allowed h-8"
                  />
                </FieldShell>

                <FieldShell
                  label={t('match_elements.use_net', 'Use net quantities')}
                  help={t(
                    'match_elements.use_net_help',
                    'Off = gross. Default deducts IfcOpeningElement / IfcRelVoidsElement from host quantities.',
                  )}
                  trailing={
                    <span
                      className={`text-sm font-semibold tabular-nums ${useNet ? 'text-oe-blue' : 'text-content-tertiary'}`}
                    >
                      {useNet
                        ? t('common.on', { defaultValue: 'On' })
                        : t('common.off', { defaultValue: 'Off' })}
                    </span>
                  }
                >
                  {/* Toggle wrapped without its own label/description — the
                      shell owns those so all three cells stay aligned. The
                      switch sits in an h-8 box matching the other controls'
                      input heights to keep baselines aligned vertically. */}
                  <div className="h-8 flex items-center">
                    <Toggle
                      checked={useNet}
                      onChange={(v) =>
                        updateSessionMut.mutate({ use_net_quantities: v })
                      }
                      disabled={updateSessionMut.isPending}
                    />
                    <span className="ms-2 text-xs text-content-secondary">
                      {t('match_elements.deduct_openings', 'Deduct openings (IfcOpeningElement)')}
                    </span>
                  </div>
                </FieldShell>

                <FieldShell
                  label={t('match_elements.stage_label', 'Construction stage')}
                  help={t(
                    'match_elements.stage_help',
                    'Pin matches to one OmniClass-aligned phase. Leave blank to search all stages.',
                  )}
                  htmlFor="match-elements-stage"
                >
                  <select
                    id="match-elements-stage"
                    value={stage}
                    disabled={updateSessionMut.isPending}
                    onChange={(e) => {
                      const v = e.target.value as ConstructionStage | '';
                      updateSessionMut.mutate({
                        construction_stage: v === '' ? null : v,
                      });
                    }}
                    className="block w-full h-8 text-sm rounded-md border border-border bg-surface-primary text-content-primary px-2 focus:outline-none focus:ring-2 focus:ring-oe-blue/40 disabled:opacity-50"
                  >
                    <option value="">
                      {t('match_elements.stage_any', 'Any stage')}
                    </option>
                    {CONSTRUCTION_STAGES.map((s) => (
                      <option key={s} value={s}>
                        {t(`match_elements.stage.${s}`, s)}
                      </option>
                    ))}
                  </select>
                </FieldShell>
              </div>
              <div className="mt-3 pt-2 border-t border-border-light">
                <div className="text-xs uppercase tracking-wider text-content-tertiary mb-1.5 font-medium">
                  {t('match_elements.trade_filter', 'Filter by trade')}
                </div>
                <ChipBar<TradeBucket>
                  chips={tradeChips}
                  selected={tradeFilter}
                  onToggle={(v) =>
                    setTradeFilter((prev) =>
                      prev.includes(v)
                        ? prev.filter((x) => x !== v)
                        : [...prev, v],
                    )
                  }
                  onClear={() => setTradeFilter([])}
                  size="sm"
                />
              </div>
            </section>
          )}

          {/* Status counters */}
          {sessionId && (
            <div className="flex items-center gap-1.5 mt-2 mb-2 flex-wrap">
              {(['unmatched', 'suggested', 'confirmed', 'skipped', 'tbd', 'applied'] as const).map(
                (k) => (
                  <button
                    key={k}
                    onClick={() => setStatusFilter(statusFilter === k ? '' : k)}
                    className={`px-2.5 py-1 rounded text-xs border transition ${
                      statusFilter === k
                        ? 'bg-indigo-50 border-indigo-300 text-indigo-700 dark:bg-indigo-900/30 dark:border-indigo-500 dark:text-indigo-200'
                        : 'bg-surface-primary border-border text-content-secondary hover:border-border'
                    }`}
                  >
                    {t(`match_elements.status.${k}`, k)}:{' '}
                    <strong className="ml-1 tabular-nums">
                      {summary[k] ?? 0}
                    </strong>
                  </button>
                ),
              )}
              {statusFilter && (
                <button
                  onClick={() => setStatusFilter('')}
                  className="text-xs text-content-tertiary underline"
                >
                  {t('match_elements.clear_filter', 'clear filter')}
                </button>
              )}
              <div className="ml-auto">
                {groupsQ.data && (
                  <ConfidenceLegend
                    high={groupsQ.data.confidence_high_threshold}
                    medium={groupsQ.data.confidence_medium_threshold}
                  />
                )}
              </div>
            </div>
          )}

          {/* Region 4 — Action toolbar */}
          {sessionId && (
            <div className="flex items-center gap-1.5 mb-2 flex-wrap">
              <button
                onClick={() => runMatchMut.mutate('vector')}
                disabled={!sessionId || !!busy}
                className={`px-3 py-1.5 text-sm rounded text-white disabled:opacity-50 inline-flex items-center gap-1.5 ${
                  primaryCta === 'run'
                    ? 'bg-indigo-600 hover:bg-indigo-700 ring-2 ring-indigo-300 dark:ring-indigo-700'
                    : 'bg-indigo-600 hover:bg-indigo-700'
                }`}
              >
                <Search className="w-4 h-4" />
                {selected.size > 0
                  ? t(
                      'match_elements.action.vector_selected',
                      'Vector match ({{count}})',
                      { count: selected.size },
                    )
                  : t(
                      'match_elements.action.vector_all',
                      'Vector match — top 10',
                    )}
              </button>
              <button
                onClick={() => runMatchMut.mutate('lexical')}
                disabled={!sessionId || !!busy}
                className="px-3 py-1.5 text-sm rounded bg-slate-700 hover:bg-slate-800 text-white disabled:opacity-50 inline-flex items-center gap-1.5"
              >
                <Search className="w-4 h-4" />
                {selected.size > 0
                  ? t(
                      'match_elements.action.lexical_selected',
                      'Lexical ({{count}})',
                      { count: selected.size },
                    )
                  : t(
                      'match_elements.action.lexical_all',
                      'Lexical match — top 10',
                    )}
              </button>
              <button
                onClick={() => runMatchMut.mutate('resources')}
                disabled={!sessionId || !!busy}
                className="px-3 py-1.5 text-sm rounded bg-purple-600 hover:bg-purple-700 text-white disabled:opacity-50 inline-flex items-center gap-1.5"
                title={t(
                  'match_elements.action.resources_title',
                  'Match against the materials/resources catalogue',
                )}
              >
                <Search className="w-4 h-4" />
                {selected.size > 0
                  ? t(
                      'match_elements.action.resources_selected',
                      'Resources ({{count}})',
                      { count: selected.size },
                    )
                  : t(
                      'match_elements.action.resources_all',
                      'Match resources — top 10',
                    )}
              </button>
              <span className="w-px h-6 bg-border mx-1" />
              <button
                onClick={() => bulkConfirmMut.mutate()}
                disabled={!sessionId || !!busy}
                className={`px-3 py-1.5 text-sm rounded text-white disabled:opacity-50 inline-flex items-center gap-1.5 ${
                  primaryCta === 'confirm'
                    ? 'bg-emerald-600 hover:bg-emerald-700 ring-2 ring-emerald-300 dark:ring-emerald-700'
                    : 'bg-emerald-600 hover:bg-emerald-700'
                }`}
              >
                <CheckCircle2 className="w-4 h-4" />
                {selected.size > 0
                  ? t(
                      'match_elements.action.confirm_selected',
                      'Confirm {{count}} ≥ {{thr}}',
                      { count: selected.size, thr: threshold.toFixed(2) },
                    )
                  : t(
                      'match_elements.action.confirm_all',
                      'Confirm all ≥ {{thr}}',
                      { thr: threshold.toFixed(2) },
                    )}
              </button>
              <button
                onClick={() => applyMut.mutate()}
                disabled={!sessionId || !!busy || confirmedCount === 0}
                className={`px-3 py-1.5 text-sm rounded text-white disabled:opacity-50 inline-flex items-center gap-1.5 ${
                  primaryCta === 'apply'
                    ? 'bg-blue-600 hover:bg-blue-700 ring-2 ring-blue-300 dark:ring-blue-700'
                    : 'bg-blue-600 hover:bg-blue-700'
                }`}
                title={t(
                  'match_elements.action.apply_title',
                  'Write confirmed matches to the project BOQ',
                )}
              >
                <PlayCircle className="w-4 h-4" />
                {t('match_elements.action.apply', 'Apply to BOQ ({{n}})', {
                  n: confirmedCount,
                })}
              </button>
              {selected.size > 0 && (
                <>
                  <button
                    onClick={() => skipBulkMut.mutate()}
                    disabled={!sessionId || !!busy}
                    className="px-3 py-1.5 text-sm rounded border border-rose-300 text-rose-600 hover:bg-rose-50 dark:border-rose-700 dark:hover:bg-rose-900/20 disabled:opacity-50 inline-flex items-center gap-1.5"
                  >
                    <XCircle className="w-3.5 h-3.5" />
                    {t('match_elements.action.skip_n', 'Skip {{count}} (TBD)', {
                      count: selected.size,
                    })}
                  </button>
                  <button
                    onClick={() => setSelected(new Set())}
                    className="text-xs text-content-tertiary underline ml-1"
                  >
                    {t('match_elements.clear_selection', 'clear selection')}
                  </button>
                </>
              )}
              <span className="text-xs text-content-tertiary ml-auto">
                {sessionId && (
                  <span>
                    <ChevronsRight className="w-3 h-3 inline" />{' '}
                    {t('match_elements.session_id', 'Session {{id}}…', {
                      id: sessionId.slice(0, 8),
                    })}
                  </span>
                )}
              </span>
            </div>
          )}

          {busy && !error && (
            <div
              className="mb-3 px-3 py-2 rounded bg-slate-100 dark:bg-slate-800 text-sm flex items-center gap-2"
              role="status"
              aria-live="polite"
            >
              <Loader2 className="w-4 h-4 animate-spin" />
              {busy}
            </div>
          )}
          {error && (
            <div
              className="mb-3 px-3 py-2 rounded border border-rose-300 dark:border-rose-700 bg-rose-50 dark:bg-rose-900/20 text-sm text-rose-800 dark:text-rose-100 flex items-start gap-2"
              role="alert"
            >
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0 break-words">{error}</div>
              <button
                type="button"
                onClick={() => setError(null)}
                className="text-xs underline opacity-80 hover:opacity-100 shrink-0"
              >
                {t('match_elements.error_dismiss', 'Dismiss')}
              </button>
            </div>
          )}

          {/* Region 6 — Group list */}
          {sessionId && (
            <div className="border border-border rounded-lg overflow-hidden bg-surface-primary">
              {/* select-all header (separate so it stays in sync with table) */}
              <div className="px-3 py-1.5 bg-slate-50 dark:bg-slate-800 border-b border-border flex items-center gap-2 text-xs text-content-tertiary">
                <input
                  type="checkbox"
                  checked={allVisibleSelected}
                  onChange={toggleAll}
                  aria-label={t(
                    'match_elements.aria.select_all',
                    'Select all visible groups',
                  )}
                />
                <span>
                  {t('match_elements.visible_groups', '{{n}} visible', {
                    n: visibleGroups.length,
                  })}
                  {selected.size > 0 && (
                    <span>
                      {' '}
                      ·{' '}
                      {t(
                        'match_elements.selected_count',
                        '{{n}} selected',
                        { n: selected.size },
                      )}
                    </span>
                  )}
                </span>
              </div>
              <div className="overflow-auto max-h-[60vh] sm:max-h-[calc(100vh-360px)]">
                <GroupListBody
                  groups={visibleGroups}
                  isLoading={groupsQ.isLoading}
                  selected={selected}
                  onToggleOne={toggleOne}
                  onOpenDetail={setOpenGroup}
                />
              </div>
            </div>
          )}
        </>
      )}

      {/* Slide-over detail */}
      {openGroup && sessionId && (
        <MatchDetailPanel
          sessionId={sessionId}
          group={openGroup}
          onClose={() => setOpenGroup(null)}
        />
      )}
      {templatesOpen && (
        <TemplatesPanel onClose={() => setTemplatesOpen(false)} />
      )}
      {showTextModal && projectId && (
        <NewSessionFromTextModal
          projectId={projectId}
          onClose={() => setShowTextModal(false)}
          onCreated={(session) => {
            setShowTextModal(false);
            setSessionId(session.id);
          }}
        />
      )}
      {showExcelModal && projectId && (
        <NewSessionFromExcelModal
          projectId={projectId}
          onClose={() => setShowExcelModal(false)}
          onCreated={(session) => {
            setShowExcelModal(false);
            setSessionId(session.id);
          }}
        />
      )}
    </div>
  );
}
