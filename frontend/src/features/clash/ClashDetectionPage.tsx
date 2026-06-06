/**
 * Clash Detection — geometric AABB interference / clearance coordination
 * over canonical BIM elements, with a discipline×discipline clash matrix,
 * a Navisworks/Solibri-grade clash-review workspace and one-click BCF export.
 *
 * Route: /clash  (project chosen via ?project= query param)
 *
 * Results area is a full client-side review tool: KPI tiles, a filter bar
 * (matrix click-through, status, type, min-penetration, free-text search),
 * a sticky-header sortable paginated table, optimistic status workflow,
 * per-row + bulk BCF export and a "Isolate in 3D" deep-link into the BIM
 * viewer.
 *
 * BIM deep-link contract (verified in features/bim/BIMPage.tsx):
 *   /projects/{projectId}/bim/{modelId}?isolate=id1,id2
 *   — the viewer reads `?isolate=` (BIMPage L1795-1813), isolates the listed
 *     element ids in the 3D scene and selects them when there is one. There
 *     is no camera/point param, so we isolate both clash elements by id.
 */

import { useMemo, useState, useEffect, useCallback, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Radar,
  AlertTriangle,
  Ruler,
  CheckCircle2,
  Layers,
  Trash2,
  FileDown,
  Play,
  Search,
  X,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Box,
  Grid3x3,
  ChevronLeft,
  ChevronRight,
  SlidersHorizontal,
  Upload,
  Loader2,
  Boxes,
  ArrowUpRight,
  FolderOpen,
  MessageSquare,
  CalendarClock,
  User,
  GitCompareArrows,
  Keyboard,
  Sparkles,
  Eye,
  EyeOff,
  History,
  Reply,
  AtSign,
  FileUp,
  ChevronDown,
  Filter,
  Link2,
  ArrowRightCircle,
  Bookmark,
  Save,
} from 'lucide-react';
import { Card } from '@/shared/ui/Card';
import { Button } from '@/shared/ui/Button';
import { Badge } from '@/shared/ui/Badge';
import { EmptyState } from '@/shared/ui/EmptyState';
import { MiniGeometryPreview } from '@/shared/ui/MiniGeometryPreview';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { DismissibleInfo, BetaBanner, Breadcrumb } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  clashApi,
  type ClashResult,
  type ClashResultSummary,
  type ClashRunSummary,
  type ClashSelectionSet,
  type ClashCategories,
  type ClashCompare,
  type ClashGroupBy,
  type ClashType,
  type ClashSeverity,
  type ClashComment,
  type ClashHistoryEntry,
  type ClashProfile,
  type ClashGroupingDimension,
  type ClashMatrixCell,
} from './api';
import { buildClashBimLink } from './clashBimLink';
import {
  createDebouncedPersist,
  loadFilters,
} from './clashFilterPersistence';
import { ClashClusterChips } from './ClashClusterChips';
import { ClashRuleEditor } from './ClashRuleEditor';
import { ClashRuleSuggestionBanner } from './ClashRuleSuggestionBanner';
import { ClashKpiPanel } from './ClashKpiPanel';
import { ClashCostImpactColumn } from './ClashCostImpactColumn';

const EMPTY_SET: ClashSelectionSet = {
  disciplines: [],
  element_types: [],
  categories: [],
  ifc_entities: [],
  properties: {},
};

/** The four built-in grouping parameters. UI labels are resolved at
 *  render (i18n); ``available_group_by`` from the categories endpoint
 *  narrows these to what the selected models actually carry, and
 *  ``available_properties`` appends any distinct element-property key as
 *  a dynamic ``property:<key>`` parameter. */
const BUILTIN_GROUP_BY = [
  'discipline',
  'type',
  'category',
  'ifc_entity',
] as const;
type BuiltinGroupBy = (typeof BUILTIN_GROUP_BY)[number];

/** Backward-compatible alias — older code referenced this name. */
const ALL_GROUP_BY: readonly BuiltinGroupBy[] = BUILTIN_GROUP_BY;

/** True for the dynamic ``property:<key>`` grouping parameter. */
function isPropertyGroupBy(g: ClashGroupBy): g is `property:${string}` {
  return g.startsWith('property:');
}

/** Bare property key behind a ``property:<key>`` grouping parameter. */
function propertyKeyOf(g: `property:${string}`): string {
  return g.slice('property:'.length);
}

/** Which {@link ClashSelectionSet} list the four built-in grouping
 *  parameters write into, so the engine resolves set membership by the
 *  same parameter the user faceted by (see backend ``_in_set``). The
 *  ``property:<key>`` case routes into ``properties[key]`` instead — see
 *  {@link SelectionSetPicker}. */
/** The four list-typed {@link ClashSelectionSet} fields (excludes the
 *  `properties` map, which the `property:<key>` path handles). */
type SelectionSetListField =
  | 'disciplines'
  | 'element_types'
  | 'categories'
  | 'ifc_entities';

const GROUP_BY_FIELD: Record<BuiltinGroupBy, SelectionSetListField> = {
  discipline: 'disciplines',
  type: 'element_types',
  category: 'categories',
  ifc_entity: 'ifc_entities',
};

type TFn = ReturnType<typeof useTranslation>['t'];

/** i18n label for each built-in grouping parameter (built lazily — needs
 *  `t`). The ``property:<key>`` form uses the raw key as its own label. */
const GROUP_BY_LABELS: Record<BuiltinGroupBy, (t: TFn) => string> = {
  discipline: (t) =>
    t('clash.group_discipline', { defaultValue: 'Discipline' }),
  type: (t) => t('clash.group_type', { defaultValue: 'Type' }),
  category: (t) =>
    t('clash.group_category', { defaultValue: 'Category' }),
  ifc_entity: (t) =>
    t('clash.group_ifc_entity', { defaultValue: 'IfcEntity' }),
};

/** UI label for any grouping parameter — i18n for the built-ins, the raw
 *  property key for the dynamic ``property:<key>`` form. */
function groupByLabel(g: ClashGroupBy, t: TFn): string {
  return isPropertyGroupBy(g)
    ? propertyKeyOf(g)
    : GROUP_BY_LABELS[g as BuiltinGroupBy](t);
}

/** Tolerance presets (mm) — so users coordinate at a sane scale instead
 *  of guessing a raw number. Matches the granularity bands a coordinator
 *  reaches for (rough first pass → final sign-off). */
const TOLERANCE_PRESETS: { mm: number; key: string; label: string }[] = [
  { mm: 25, key: 'coarse', label: 'Coarse · 25 mm' },
  { mm: 10, key: 'standard', label: 'Standard · 10 mm' },
  { mm: 3, key: 'fine', label: 'Fine · 3 mm' },
  { mm: 1, key: 'precise', label: 'Precise · 1 mm' },
];

/** Result-table aggregation (client-side only — no backend round-trip).
 *  `none` keeps the flat sortable list. The rest mirror the Navisworks
 *  "Group clashes" axes a reviewer triages by. */
type ResultGroupBy =
  | 'none'
  | 'pair'
  | 'clash_type'
  | 'status'
  | 'element_a';

const OPEN_STATUSES = ['new', 'active'];
const STATUS_OPTIONS = [
  'new',
  'active',
  'reviewed',
  'approved',
  'resolved',
  'ignored',
] as const;
type StatusOpt = (typeof STATUS_OPTIONS)[number];

/** Linear three-step workflow that 95% of clashes follow:
 *  ``new → active → reviewed``. After ``reviewed`` the coordinator
 *  picks one of the terminal states (approved / resolved / ignored)
 *  explicitly from the dropdown. */
const STATUS_FLOW: readonly StatusOpt[] = ['new', 'active', 'reviewed'] as const;
/** Next state for one-click advance; ``null`` at the flow tail / terminal. */
function nextStatusOf(s: string): StatusOpt | null {
  const i = STATUS_FLOW.indexOf(s as StatusOpt);
  if (i < 0) return null;
  if (i >= STATUS_FLOW.length - 1) return null;
  return STATUS_FLOW[i + 1] ?? null;
}

/** Coordination priority — high → low. The order doubles as the sort
 *  ranking (critical sorts first). */
const SEVERITY_OPTIONS: ClashSeverity[] = [
  'critical',
  'high',
  'medium',
  'low',
];
/** Severity → Tailwind badge classes. Reuses the page's existing colour
 *  language (semantic-error for critical, amber/slate scale below). */
const SEVERITY_BADGE: Record<ClashSeverity, string> = {
  critical:
    'bg-semantic-error-bg text-semantic-error',
  high: 'bg-orange-100 text-orange-700 dark:bg-orange-950/40 dark:text-orange-300',
  medium:
    'bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300',
  low: 'bg-slate-100 text-slate-600 dark:bg-slate-800/60 dark:text-slate-300',
};
/** Stable sort rank — lower = more urgent (critical first when asc). */
const SEVERITY_RANK: Record<ClashSeverity, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};
/** Older payloads may omit `severity`; treat the absence as `medium`. */
function severityOf(r: { severity?: ClashSeverity }): ClashSeverity {
  return r.severity ?? 'medium';
}

/** Engine-suggested severity bump (Wave A2). Surfaces only when a
 *  meaningful upgrade is on offer (suggestion is strictly more urgent
 *  than the current severity). */
function suggestionOf(r: ClashResult): ClashSeverity | undefined {
  const s = r.meta?.severity_suggestion;
  if (!s) return undefined;
  const cur = severityOf(r);
  if (SEVERITY_RANK[s] >= SEVERITY_RANK[cur]) return undefined;
  return s;
}

/** Order-independent two-value key — discipline, storey or model pair.
 *  ``null``/``undefined`` normalises to "—" so the facet picks up
 *  "(no level)" as a real bucket instead of silently dropping rows. */
function orderedPairKey(
  a: string | number | null | undefined,
  b: string | number | null | undefined,
): string {
  const sa = a == null || a === '' ? '—' : String(a);
  const sb = b == null || b === '' ? '—' : String(b);
  const [lo, hi] = sa < sb ? [sa, sb] : [sb, sa];
  return `${lo}|${hi}`;
}

/** Pair-cluster signature — unordered ``a_stable_id|b_stable_id``,
 *  independent of ``clash_type`` so sub-clashes between the same two
 *  elements collapse into one master row. */
function pairClusterKey(r: ClashResult): string {
  return orderedPairKey(r.a_stable_id || r.a_name, r.b_stable_id || r.b_name);
}

/** True when an ISO "YYYY-MM-DD" due date is strictly before today (local
 *  date). Used for the overdue chip styling. */
function isOverdue(due: string | null | undefined): boolean {
  if (!due) return false;
  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(
    today.getMonth() + 1,
  ).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  return due < todayStr;
}

/** How many result rows we page into the browser for client-side
 *  filter/sort. Multiple of the backend's 500-row max. KPI tiles come from
 *  the authoritative run `summary`, NOT this capped set, so the tiles stay
 *  correct even when the row set is capped. Wave A2 raised this from
 *  2000 to 10000 — the table now uses IntersectionObserver-windowed
 *  chunks so very large runs stay smooth. */
const CLIENT_CAP = 10000;
const PAGE_SIZE = 100;
/** Chunk size for the IntersectionObserver-windowed body. Renders in
 *  batches of N — only chunks intersecting the viewport (or its 600 px
 *  lookahead) mount their rows. */
const WINDOW_CHUNK = 50;

type SortKey =
  | 'idx'
  | 'a_name'
  | 'b_name'
  | 'clash_type'
  | 'severity'
  | 'penetration_m'
  | 'distance_m'
  | 'status';
type SortDir = 'asc' | 'desc';

/** Heat colour for a matrix cell, scaled against the busiest cell. */
function heat(count: number, max: number): string {
  if (count === 0) return 'bg-surface-secondary text-content-tertiary';
  const r = max > 0 ? count / max : 0;
  if (r > 0.66) return 'bg-semantic-error text-content-inverse';
  if (r > 0.33) return 'bg-amber-500 text-content-inverse';
  return 'bg-amber-200 text-amber-900';
}

/** Stable per-discipline chip palette (deterministic — same discipline →
 *  same colour for the whole session). */
const DISCIPLINE_PALETTE = [
  'bg-blue-100 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300',
  'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300',
  'bg-purple-100 text-purple-700 dark:bg-purple-950/40 dark:text-purple-300',
  'bg-orange-100 text-orange-700 dark:bg-orange-950/40 dark:text-orange-300',
  'bg-cyan-100 text-cyan-700 dark:bg-cyan-950/40 dark:text-cyan-300',
  'bg-pink-100 text-pink-700 dark:bg-pink-950/40 dark:text-pink-300',
  'bg-lime-100 text-lime-700 dark:bg-lime-950/40 dark:text-lime-300',
  'bg-indigo-100 text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-300',
];
function disciplineHash(d: string): number {
  let h = 0;
  for (let i = 0; i < d.length; i++) h = (h * 31 + d.charCodeAt(i)) >>> 0;
  return h % DISCIPLINE_PALETTE.length;
}
/** The seeded BIM models carry the project name baked into their label
 *  (e.g. "Edifício Comercial Faria Lima — São Paulo — Modelo Estrutural
 *  Revit"). Clash is intra-project and the project is already chosen
 *  globally, so the project/location prefix is pure noise here — and
 *  worse, two such models read like "two projects", which confuses users
 *  (clash is always single-project). Strip it down to the discipline/type
 *  tail. We do NOT rely on the global project name being hydrated (it is
 *  often empty on a direct nav / ``?project=`` deep-link, which is exactly
 *  when the full prefixed name leaked through before): the seeded labels
 *  use a spaced dash ( — / – / - ) between "Project — City — Discipline",
 *  so the last dash-delimited segment is the model's real identity. Falls
 *  back to the full name if stripping would empty it. */
export function shortModelName(
  full: string,
  projectName?: string | null,
): string {
  let s = (full ?? '').trim();
  const pn = (projectName ?? '').trim();
  // Precise strip first when the project name is known.
  if (pn && s.toLowerCase().startsWith(pn.toLowerCase())) {
    s = s
      .slice(pn.length)
      .replace(/^[\s—–\-:/·|]+/, '')
      .trim();
  }
  // Generic strip: if a "Prefix — … — Discipline" structure remains,
  // keep only the final segment (the discipline/type). This makes the
  // two model cards read as two *models*, not two projects, regardless
  // of whether the global project name was available.
  const parts = s
    .split(/\s+[—–|]\s+|\s+-\s+/)
    .map((p) => p.trim())
    .filter(Boolean);
  if (parts.length >= 2) s = parts[parts.length - 1] ?? s;
  return s || (full ?? '').trim();
}

/** Stable group key + human label for the review-table aggregation.
 *  Discipline pairs are order-independent (Struct↔Mech == Mech↔Struct). */
function resultGroupKey(
  r: ClashResult,
  by: ResultGroupBy,
): { key: string; label: string } {
  switch (by) {
    case 'pair': {
      const a = r.a_discipline || '—';
      const b = r.b_discipline || '—';
      const [x, y] = a < b ? [a, b] : [b, a];
      return { key: `${x}|${y}`, label: `${x} ↔ ${y}` };
    }
    case 'clash_type':
      return { key: r.clash_type, label: r.clash_type };
    case 'status':
      return { key: r.status, label: r.status };
    case 'element_a': {
      const v = r.a_name || r.a_stable_id || '—';
      return { key: v, label: v };
    }
    default:
      return { key: '', label: '' };
  }
}

/** A flat render list entry: either a group header or a clash row. */
type RenderItem =
  | { kind: 'group'; key: string; label: string; count: number }
  | {
      kind: 'pair';
      key: string;
      label: string;
      members: ClashResult[];
      head: ClashResult;
    }
  | { kind: 'row'; row: ClashResult };

/** Coloured priority badge. critical=red, high=orange, medium=amber,
 *  low=slate (see {@link SEVERITY_BADGE}). i18n label, English fallback. */
function SeverityBadge({
  severity,
  t,
}: {
  severity: ClashSeverity;
  t: TFn;
}) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full px-1.5 py-0.5 text-2xs font-medium capitalize',
        SEVERITY_BADGE[severity],
      )}
    >
      {t(`clash.severity.${severity}`, { defaultValue: severity })}
    </span>
  );
}

function DisciplineChip({ name }: { name: string }) {
  const label = name || '—';
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full px-1.5 py-0.5 text-2xs font-medium',
        name
          ? DISCIPLINE_PALETTE[disciplineHash(name)]
          : 'bg-surface-secondary text-content-tertiary',
      )}
    >
      {label}
    </span>
  );
}

export function ClashDetectionPage() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const qc = useQueryClient();
  const { confirm, ...confirmProps } = useConfirm();
  const [params, setParams] = useSearchParams();
  // The active project is chosen once, globally, from the selector at the
  // top of the app — clash does NOT show its own project picker. We fall
  // back to a legacy ``?project=`` deep-link only when no global context
  // is set yet (external links into a specific project's clashes).
  const ctxProjectId = useProjectContextStore((s) => s.activeProjectId);
  const ctxProjectName = useProjectContextStore((s) => s.activeProjectName);
  const projectId = ctxProjectId ?? params.get('project') ?? '';
  const runId = params.get('run') ?? '';
  const navigate = useNavigate();

  // Run-config form state.
  const [selModels, setSelModels] = useState<string[]>([]);
  const [runName, setRunName] = useState('');
  const [runDesc, setRunDesc] = useState('');
  // Navisworks-style "Type": hard interpenetration only, clearance
  // (proximity) only, or both. `both` is the universal default.
  const [clashType, setClashType] = useState<ClashType>('both');
  // Federated noise filter — drop pairs whose two elements are in the
  // same model (only meaningful when >1 model is selected).
  const [ignoreSameModel, setIgnoreSameModel] = useState(false);
  const [toleranceMm, setToleranceMm] = useState(10);
  const [clearanceMm, setClearanceMm] = useState(0);
  // Category/type-based search (Set A × Set B) is the primary mode — it is
  // what users reach for first when coordinating a model.
  const [mode, setMode] = useState('selection_sets');
  const [setA, setSetA] = useState<ClashSelectionSet>(EMPTY_SET);
  const [setB, setSetB] = useState<ClashSelectionSet>(EMPTY_SET);
  // Which element parameter the Set A / Set B facet lists are grouped by
  // (sourced from all project element parameters). "type" is universal;
  // "category" / "ifc_entity" only when the selected models carry them.
  const [groupBy, setGroupBy] = useState<ClashGroupBy>('type');

  // ── Persistent profiles (item #23) ─────────────────────────────────
  // The currently selected profile in the config-form picker (or '' for
  // "no profile"). Selecting one pre-populates every engine parameter; the
  // user is still free to tweak before launching. The Save-as-profile
  // dialog is opened from the active run.
  const [profileId, setProfileId] = useState<string>('');
  const [saveProfileName, setSaveProfileName] = useState('');
  const [showSaveProfile, setShowSaveProfile] = useState(false);

  // Result filters (all client-side).
  const [fStatus, setFStatus] = useState<Set<string>>(new Set());
  const [fType, setFType] = useState<'all' | 'hard' | 'clearance'>('all');
  const [fSeverity, setFSeverity] = useState<Set<ClashSeverity>>(
    new Set(),
  );
  const [fPair, setFPair] = useState<string>(''); // "A|B" ordered pair
  const [fMinPen, setFMinPen] = useState(0); // mm
  const [fSearch, setFSearch] = useState('');
  const [kpiFilter, setKpiFilter] = useState<
    'all' | 'hard' | 'clearance' | 'open' | 'resolved'
  >('all');
  // Wave A4 — selected spatial-cluster id (or null = "all"). Filters
  // the review table to that DBSCAN bucket so the coordinator can walk
  // through a single hot-spot at a time.
  const [selectedClusterId, setSelectedClusterId] = useState<number | null>(
    null,
  );
  // Wave A4 — UI flags for the new rule editor modal + KPI dashboard tab.
  const [rulesOpen, setRulesOpen] = useState(false);
  const [kpiTabOpen, setKpiTabOpen] = useState(false);

  // Table state.
  const [sortKey, setSortKey] = useState<SortKey>('idx');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [page, setPage] = useState(0);
  const [selResults, setSelResults] = useState<Set<string>>(new Set());
  // Per-clash collaboration side panel: the result id whose detail
  // (assignee / due date / comments thread) is open, or null.
  const [detailId, setDetailId] = useState<string | null>(null);
  // Keyboard navigation: index into the current page's data rows, or -1
  // when nothing is keyboard-focused. ↑/↓ or j/k move it, Enter → 3D.
  const [kbRow, setKbRow] = useState<number>(-1);
  // Run-to-run comparison: which earlier run to diff the active run
  // against (null = comparison panel closed) + collapsed buckets.
  const [compareBaseId, setCompareBaseId] = useState<string | null>(null);
  const [compareCollapsed, setCompareCollapsed] = useState<Set<string>>(
    new Set(),
  );
  // Review-table aggregation (client-side). `none` = flat list.
  const [resultGroupBy, setResultGroupBy] =
    useState<ResultGroupBy>('none');
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(
    new Set(),
  );
  // Wave A2 — pair clustering. When ON, every row sharing the same
  // unordered element-pair signature collapses into one master row with
  // a count×N badge, expandable in place. Independent of `resultGroupBy`.
  const [pairCluster, setPairCluster] = useState(false);
  const [expandedPairs, setExpandedPairs] = useState<Set<string>>(new Set());
  // Wave A2 — collapsible faceted filter rail. Default OFF so the pill
  // bar stays the lightweight quick filter; the rail is the power view.
  const [showFacets, setShowFacets] = useState(false);
  const [fDiscPair, setFDiscPair] = useState<Set<string>>(new Set());
  const [fLevelPair, setFLevelPair] = useState<Set<string>>(new Set());
  const [fModelPair, setFModelPair] = useState<Set<string>>(new Set());

  // Wave A5 — per-project filter persistence (localStorage + LRU).
  // Hydrate on the first project mount; thereafter every filter change
  // schedules a debounced write so rapid clicks coalesce into one save.
  // Filters that don't survive a reload (e.g. transient search text) are
  // intentionally left out of the persisted envelope.
  const filterPersistRef = useRef(createDebouncedPersist());
  const hydratedProjectRef = useRef<string | null>(null);

  useEffect(() => {
    if (!projectId || hydratedProjectRef.current === projectId) return;
    hydratedProjectRef.current = projectId;
    const saved = loadFilters(projectId);
    if (saved.severity.length > 0)
      setFSeverity(new Set(saved.severity as ClashSeverity[]));
    if (saved.status.length > 0) setFStatus(new Set(saved.status));
    if (saved.discipline.length > 0) setFDiscPair(new Set(saved.discipline));
    if (saved.sortBy) setSortKey(saved.sortBy as SortKey);
  }, [projectId]);

  useEffect(() => {
    if (!projectId || hydratedProjectRef.current !== projectId) return;
    filterPersistRef.current.schedule(projectId, {
      severity: [...fSeverity],
      status: [...fStatus],
      discipline: [...fDiscPair],
      sortBy: sortKey,
    });
  }, [projectId, fSeverity, fStatus, fDiscPair, sortKey]);

  // ── Coordination-Hub trade-matrix deep-link ────────────────────────────
  // The trade-matrix cell navigates here with ``?disciplineA=X&disciplineB=Y``
  // — seed the discipline-pair facet (and the legacy `trade_a/trade_b`
  // shape from earlier links). We do this AFTER the localStorage-hydrate
  // effect so the deep-link wins over a stale saved filter on the same
  // project. Strip the params once consumed so a back-then-forward
  // navigation does not re-apply them.
  const deepLinkAppliedRef = useRef(false);
  useEffect(() => {
    if (!projectId || deepLinkAppliedRef.current) return;
    const dA =
      params.get('disciplineA') ?? params.get('trade_a') ?? '';
    const dB =
      params.get('disciplineB') ?? params.get('trade_b') ?? '';
    if (!dA && !dB) return;
    deepLinkAppliedRef.current = true;
    if (dA && dB) {
      setFDiscPair(new Set([orderedPairKey(dA, dB)]));
    } else {
      // Single-discipline link — treat it as a one-sided filter using
      // the unordered key with the other half normalised to "—".
      const lone = dA || dB;
      setFDiscPair(new Set([orderedPairKey(lone, '—')]));
    }
    // Prune the consumed params from the URL so refresh / back-forward
    // doesn't keep clobbering the filter every time the page rehydrates.
    const next = new URLSearchParams(params);
    next.delete('disciplineA');
    next.delete('disciplineB');
    next.delete('trade_a');
    next.delete('trade_b');
    setParams(next, { replace: true });
  }, [projectId, params, setParams]);

  // Flush any pending write when this page unmounts so the last edit
  // isn't lost between an "apply filter → navigate away" beat.
  useEffect(() => {
    const persist = filterPersistRef.current;
    return () => persist.flush();
  }, []);

  const modelsQ = useQuery({
    queryKey: ['clash-models', projectId],
    queryFn: () => clashApi.models(projectId),
    enabled: !!projectId,
  });
  const runsQ = useQuery({
    queryKey: ['clash-runs', projectId],
    queryFn: () => clashApi.listRuns(projectId),
    enabled: !!projectId,
  });
  const runQ = useQuery({
    queryKey: ['clash-run', projectId, runId],
    queryFn: () => clashApi.getRun(projectId, runId),
    enabled: !!projectId && !!runId,
  });
  // Facets for the Set A vs Set B pickers, grouped by the chosen
  // parameter. Keyed by the selected models + grouping so switching
  // either refreshes the lists/counts.
  const categoriesQ = useQuery({
    queryKey: [
      'clash-categories',
      projectId,
      [...selModels].sort(),
      groupBy,
    ],
    queryFn: () => clashApi.categories(projectId, selModels, groupBy),
    enabled:
      !!projectId && mode === 'selection_sets' && selModels.length > 0,
  });
  // Available built-in grouping parameters across the selected models. If
  // the active built-in is no longer available (e.g. dropped the only IFC
  // model), fall back to the universal "type".
  const availableGroupBy: ClashGroupBy[] = useMemo(
    () => categoriesQ.data?.available_group_by ?? ['discipline', 'type'],
    [categoriesQ.data],
  );
  // Distinct element-property keys the backend surfaced for the selected
  // models — each becomes a dynamic `property:<key>` grouping parameter.
  // Absent on older backends → no dynamic options (graceful degrade).
  const availableProperties = useMemo(
    () => categoriesQ.data?.available_properties ?? [],
    [categoriesQ.data],
  );
  useEffect(() => {
    if (!categoriesQ.data) return;
    if (isPropertyGroupBy(groupBy)) {
      // A `property:<key>` selection is valid only while that key is still
      // surfaced for the current model set; otherwise fall back to "type".
      const key = propertyKeyOf(groupBy);
      const stillThere = availableProperties.some((p) => p.key === key);
      if (!stillThere && availableProperties.length >= 0) {
        setGroupBy('type');
      }
      return;
    }
    if (availableGroupBy.length > 0 && !availableGroupBy.includes(groupBy)) {
      setGroupBy('type');
    }
  }, [availableGroupBy, availableProperties, groupBy, categoriesQ.data]);
  // Page the result rows into the browser at the backend's 500-row max
  // (single limit=2000 used to 422 → empty UI). KPI tiles do NOT depend on
  // this set — they read the authoritative run `summary`. This set only
  // backs the client-side table filter/sort, and may be capped.
  const resultsQ = useQuery({
    queryKey: ['clash-results', projectId, runId],
    queryFn: ({ signal }) =>
      clashApi.loadAllResults(projectId, runId, {
        cap: CLIENT_CAP,
        signal,
      }),
    enabled: !!projectId && !!runId,
    retry: 1,
  });
  const allResults: ClashResult[] = useMemo(
    () => resultsQ.data?.items ?? [],
    [resultsQ.data],
  );
  /** Server-reported full filtered row count (authoritative for paging). */
  const loadedTotal = resultsQ.data?.total ?? 0;
  /** True when the run has more result rows than we paged into the browser. */
  const rowsCapped = resultsQ.data?.capped ?? false;

  // Surface a fetch failure as a toast (don't swallow it — a non-2xx must
  // never look like "models are clean").
  useEffect(() => {
    if (resultsQ.isError) {
      addToast({
        type: 'error',
        title: t('clash.results_error', {
          defaultValue: 'Failed to load clash results',
        }),
        message:
          resultsQ.error instanceof Error
            ? resultsQ.error.message
            : undefined,
      });
    }
  }, [resultsQ.isError]); // eslint-disable-line react-hooks/exhaustive-deps

  // Default the model selection once models load. When the file manager
  // deep-links a specific model via ``?model=<id>`` (the "Clash
  // Detection" action on a BIM file), pre-select THAT model so the run
  // config is already focused on what the user clicked; otherwise select
  // every non-empty parsed model.
  const deepLinkModelId = params.get('model') ?? '';
  useEffect(() => {
    if (modelsQ.data && selModels.length === 0) {
      const nonEmpty = modelsQ.data.filter((m) => m.element_count > 0);
      const focused =
        deepLinkModelId && nonEmpty.some((m) => m.id === deepLinkModelId)
          ? [deepLinkModelId]
          : nonEmpty.map((m) => m.id);
      setSelModels(focused);
    }
  }, [modelsQ.data]); // eslint-disable-line react-hooks/exhaustive-deps

  // Reset filters/paging/selection whenever the active run changes.
  useEffect(() => {
    setFStatus(new Set());
    setFType('all');
    setFSeverity(new Set());
    setFPair('');
    setFMinPen(0);
    setFSearch('');
    setKpiFilter('all');
    setSortKey('idx');
    setSortDir('asc');
    setPage(0);
    setSelResults(new Set());
    setResultGroupBy('none');
    setCollapsedGroups(new Set());
    setPairCluster(false);
    setExpandedPairs(new Set());
    setFDiscPair(new Set());
    setFLevelPair(new Set());
    setFModelPair(new Set());
    setDetailId(null);
    setKbRow(-1);
    setCompareBaseId(null);
    setCompareCollapsed(new Set());
  }, [runId]);

  const setNonEmpty = (s: ClashSelectionSet) =>
    s.disciplines.length > 0 ||
    s.element_types.length > 0 ||
    s.categories.length > 0 ||
    s.ifc_entities.length > 0 ||
    Object.values(s.properties ?? {}).some((v) => v.length > 0);
  const selectionSetsValid =
    mode !== 'selection_sets' ||
    (setNonEmpty(setA) && setNonEmpty(setB));

  // Models actually selected that carry geometry (the run scope).
  const multiModelScope = selModels.length > 1;
  // A clearance-only run with no clearance distance can never report
  // anything — guard it the same way the backend contract implies.
  const clearanceMisconfigured =
    clashType === 'clearance' && clearanceMm <= 0;

  const runMut = useMutation({
    mutationFn: () =>
      clashApi.createRun(projectId, {
        ...(runName.trim() ? { name: runName.trim() } : {}),
        ...(runDesc.trim() ? { description: runDesc.trim() } : {}),
        model_ids: selModels,
        clash_type: clashType,
        // Only meaningful with a federated (>1 model) scope.
        ignore_same_model: multiModelScope ? ignoreSameModel : false,
        tolerance_m: toleranceMm / 1000,
        clearance_m: clearanceMm / 1000,
        mode,
        ...(mode === 'selection_sets'
          ? { set_a: setA, set_b: setB }
          : {}),
      }),
    onSuccess: (run) => {
      qc.invalidateQueries({ queryKey: ['clash-runs', projectId] });
      setParams((p) => {
        p.set('run', run.id);
        return p;
      });
      if (run.status === 'failed') {
        addToast({
          type: 'error',
          title: t('clash.run_failed', { defaultValue: 'Clash run failed' }),
          message: run.error ?? undefined,
        });
      } else {
        addToast({
          type: 'success',
          title: t('clash.run_done', {
            defaultValue: '{{n}} clashes found across {{e}} elements',
            n: run.total_clashes,
            e: run.element_count,
          }),
        });
      }
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  // ── Profiles (item #23): list for the picker + save-as mutation ──────
  const profilesQ = useQuery({
    queryKey: ['clash-profiles', projectId],
    queryFn: () => clashApi.listProfiles(projectId),
    enabled: !!projectId,
  });
  const profiles = profilesQ.data ?? [];

  // Load a profile into the run-config form (pre-populate). Mirrors the
  // exact column set a profile snapshots; model selection is never touched.
  const applyProfileToForm = useCallback(
    (p: ClashProfile) => {
      setClashType(p.clash_type);
      setIgnoreSameModel(p.ignore_same_model);
      setToleranceMm(Math.round(p.tolerance_m * 1000));
      setClearanceMm(Math.round(p.clearance_m * 1000));
      setMode(p.mode);
      setSetA(p.set_a ?? EMPTY_SET);
      setSetB(p.set_b ?? EMPTY_SET);
    },
    [],
  );

  const onPickProfile = useCallback(
    (id: string) => {
      setProfileId(id);
      const p = profiles.find((x) => x.id === id);
      if (p) applyProfileToForm(p);
    },
    [profiles, applyProfileToForm],
  );

  const saveProfileMut = useMutation({
    mutationFn: () =>
      clashApi.createProfile(projectId, {
        name: saveProfileName.trim(),
        clash_type: clashType,
        ignore_same_model: multiModelScope ? ignoreSameModel : false,
        tolerance_m: toleranceMm / 1000,
        clearance_m: clearanceMm / 1000,
        mode,
        ...(mode === 'selection_sets' ? { set_a: setA, set_b: setB } : {}),
      }),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['clash-profiles', projectId] });
      setShowSaveProfile(false);
      setSaveProfileName('');
      setProfileId(created.id);
      addToast({
        type: 'success',
        title: t('clash.profile_saved', {
          defaultValue: 'Configuration saved as profile',
        }),
      });
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const statusMut = useMutation({
    mutationFn: (v: { id: string; status: string }) =>
      clashApi.updateResult(projectId, runId, v.id, { status: v.status }),
    // Optimistic: flip the cached row immediately, roll back on error.
    onMutate: async (v) => {
      await qc.cancelQueries({
        queryKey: ['clash-results', projectId, runId],
      });
      const prev = qc.getQueryData<{ items: ClashResult[] }>([
        'clash-results',
        projectId,
        runId,
      ]);
      qc.setQueryData<{ items: ClashResult[] }>(
        ['clash-results', projectId, runId],
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((r) =>
                  r.id === v.id ? { ...r, status: v.status } : r,
                ),
              }
            : old,
      );
      return { prev };
    },
    onError: (e: Error, _v, ctx) => {
      if (ctx?.prev)
        qc.setQueryData(['clash-results', projectId, runId], ctx.prev);
      addToast({
        type: 'error',
        title: t('clash.status_failed', {
          defaultValue: 'Could not update status',
        }),
        message: e.message,
      });
    },
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('clash.status_saved', { defaultValue: 'Status updated' }),
      });
    },
    onSettled: () => {
      qc.invalidateQueries({
        queryKey: ['clash-results', projectId, runId],
      });
      qc.invalidateQueries({ queryKey: ['clash-run', projectId, runId] });
    },
  });

  // Wave A2 — bulk severity reclassification. Same optimistic+invalidate
  // pattern as `statusMut`; kept as a sibling mutation so the bulk
  // toolbar can fan out one mutate per selected row without touching
  // existing single-row triage paths.
  const severityMut = useMutation({
    mutationFn: (v: { id: string; severity: ClashSeverity }) =>
      clashApi.updateResult(projectId, runId, v.id, { severity: v.severity }),
    onMutate: async (v) => {
      await qc.cancelQueries({
        queryKey: ['clash-results', projectId, runId],
      });
      const prev = qc.getQueryData<{ items: ClashResult[] }>([
        'clash-results',
        projectId,
        runId,
      ]);
      qc.setQueryData<{ items: ClashResult[] }>(
        ['clash-results', projectId, runId],
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((r) =>
                  r.id === v.id ? { ...r, severity: v.severity } : r,
                ),
              }
            : old,
      );
      return { prev };
    },
    onError: (e: Error, _v, ctx) => {
      if (ctx?.prev)
        qc.setQueryData(['clash-results', projectId, runId], ctx.prev);
      addToast({
        type: 'error',
        title: t('clash.severity_failed', {
          defaultValue: 'Could not update severity',
        }),
        message: e.message,
      });
    },
    onSettled: () => {
      qc.invalidateQueries({
        queryKey: ['clash-results', projectId, runId],
      });
      qc.invalidateQueries({ queryKey: ['clash-run', projectId, runId] });
    },
  });

  // Wave A2 — bulk triage in ONE request. The toolbar fans status / severity
  // / assignee changes to the whole selection via a single batch PATCH (was
  // one PATCH per row, which fired thousands of requests + invalidations on a
  // large selection). Optimistic over the cached rows; invalidate once on
  // settle.
  const bulkMut = useMutation({
    mutationFn: (v: {
      ids: string[];
      status?: string;
      severity?: ClashSeverity;
      assigned_to?: string | null;
    }) =>
      clashApi.bulkUpdateResults(projectId, runId, {
        result_ids: v.ids,
        status: v.status,
        severity: v.severity,
        assigned_to: v.assigned_to,
      }),
    onMutate: async (v) => {
      await qc.cancelQueries({
        queryKey: ['clash-results', projectId, runId],
      });
      const prev = qc.getQueryData<{ items: ClashResult[] }>([
        'clash-results',
        projectId,
        runId,
      ]);
      const idSet = new Set(v.ids);
      qc.setQueryData<{ items: ClashResult[] }>(
        ['clash-results', projectId, runId],
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((r) =>
                  idSet.has(r.id)
                    ? {
                        ...r,
                        ...(v.status !== undefined
                          ? { status: v.status }
                          : {}),
                        ...(v.severity !== undefined
                          ? { severity: v.severity }
                          : {}),
                        ...(v.assigned_to !== undefined
                          ? { assigned_to: v.assigned_to }
                          : {}),
                      }
                    : r,
                ),
              }
            : old,
      );
      return { prev };
    },
    onError: (e: Error, _v, ctx) => {
      if (ctx?.prev)
        qc.setQueryData(['clash-results', projectId, runId], ctx.prev);
      addToast({
        type: 'error',
        title: t('clash.bulk_failed', {
          defaultValue: 'Bulk update failed',
        }),
        message: e.message,
      });
    },
    onSuccess: (res) => {
      addToast({
        type: 'success',
        title: t('clash.bulk_done', {
          defaultValue: '{{n}} clash(es) updated',
          n: res.updated,
        }),
      });
    },
    onSettled: () => {
      qc.invalidateQueries({
        queryKey: ['clash-results', projectId, runId],
      });
      qc.invalidateQueries({ queryKey: ['clash-run', projectId, runId] });
    },
  });

  // Per-clash collaboration: assignee / due date / add-comment. Optimistic
  // for the scalar fields; the comment text is appended optimistically with
  // a provisional author/ts, then the server's authoritative result (which
  // carries the real author + ts) replaces the cached row on success.
  const detailMut = useMutation({
    mutationFn: (v: {
      id: string;
      assigned_to?: string | null;
      due_date?: string | null;
      add_comment?: { text: string; reply_to?: string | null };
    }) => {
      const { id, ...body } = v;
      return clashApi.updateResult(projectId, runId, id, body);
    },
    onMutate: async (v) => {
      await qc.cancelQueries({
        queryKey: ['clash-results', projectId, runId],
      });
      const prev = qc.getQueryData<{ items: ClashResult[] }>([
        'clash-results',
        projectId,
        runId,
      ]);
      qc.setQueryData<{ items: ClashResult[] }>(
        ['clash-results', projectId, runId],
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((r) => {
                  if (r.id !== v.id) return r;
                  const next: ClashResult = { ...r };
                  if ('assigned_to' in v)
                    next.assigned_to = v.assigned_to ?? null;
                  if ('due_date' in v)
                    next.due_date = v.due_date ?? null;
                  if (v.add_comment) {
                    next.comments = [
                      ...(r.comments ?? []),
                      {
                        author: t('clash.you', {
                          defaultValue: 'You',
                        }),
                        author_id: null,
                        ts: new Date().toISOString(),
                        text: v.add_comment.text,
                        reply_to: v.add_comment.reply_to ?? null,
                      },
                    ];
                  }
                  return next;
                }),
              }
            : old,
      );
      return { prev };
    },
    onError: (e: Error, _v, ctx) => {
      if (ctx?.prev)
        qc.setQueryData(['clash-results', projectId, runId], ctx.prev);
      addToast({
        type: 'error',
        title: t('clash.detail_failed', {
          defaultValue: 'Could not save clash update',
        }),
        message: e.message,
      });
    },
    onSuccess: (updated) => {
      // Replace the optimistic row with the server's truth (real comment
      // author + ts) without a full refetch flicker.
      qc.setQueryData<{ items: ClashResult[] }>(
        ['clash-results', projectId, runId],
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((r) =>
                  r.id === updated.id ? { ...r, ...updated } : r,
                ),
              }
            : old,
      );
    },
    onSettled: () => {
      qc.invalidateQueries({
        queryKey: ['clash-results', projectId, runId],
      });
    },
  });

  const exportMut = useMutation({
    mutationFn: (ids: string[] | null) =>
      clashApi.exportBcf(projectId, runId, { result_ids: ids }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['clash-results', projectId, runId] });
      setSelResults(new Set());
      addToast({
        type: 'success',
        title: t('clash.bcf_done', {
          defaultValue: 'Exported {{n}} clash(es) to BCF ({{s}} skipped)',
          n: r.exported,
          s: r.skipped,
        }),
      });
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  // BCF round-trip import (Wave A3). Topics are matched by signature
  // (or topic guid as fallback) against the run's existing rows; the
  // toast surfaces matched / unmatched / parse-error counts so the
  // user sees exactly what the round-trip touched.
  const importBcfMut = useMutation({
    mutationFn: (file: File) =>
      clashApi.importBcf(projectId, runId, file),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['clash-results', projectId, runId] });
      qc.invalidateQueries({ queryKey: ['clash-run', projectId, runId] });
      addToast({
        type: 'success',
        title: t('clash.bcf_import_done', {
          defaultValue:
            'BCF import: {{m}} matched, {{u}} unmatched, {{e}} errors',
          m: r.matched,
          u: r.unmatched,
          e: r.errors,
        }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('clash.bcf_import_failed', {
          defaultValue: 'BCF import failed',
        }),
        message: e.message,
      }),
  });
  const bcfFileInputRef = useRef<HTMLInputElement | null>(null);

  const delMut = useMutation({
    mutationFn: (id: string) => clashApi.deleteRun(projectId, id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['clash-runs', projectId] });
      setParams((p) => {
        p.delete('run');
        return p;
      });
      addToast({
        type: 'success',
        title: t('clash.run_deleted', { defaultValue: 'Run deleted' }),
      });
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('clash.run_delete_failed', {
          defaultValue: 'Failed to delete run',
        }),
        message: e.message,
      }),
  });

  // CSV export — server-rendered, honouring the same single-value
  // status/type/severity filters the list endpoint accepts. (The free-text
  // search / pair / min-penetration are client-only refinements and have
  // no server query param, so they are intentionally NOT forwarded.)
  const csvMut = useMutation({
    mutationFn: (f: {
      status?: string;
      clash_type?: string;
      severity?: string;
    }) => clashApi.exportCsv(projectId, runId, f),
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('clash.csv_done', {
          defaultValue: 'CSV export started',
        }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('clash.csv_failed', {
          defaultValue: 'CSV export failed',
        }),
        message: e.message,
      }),
  });

  // Run-to-run comparison — diff the active run against `compareBaseId`.
  const compareQ = useQuery({
    queryKey: ['clash-compare', projectId, runId, compareBaseId],
    queryFn: () =>
      clashApi.compare(projectId, runId, compareBaseId as string),
    enabled: !!projectId && !!runId && !!compareBaseId,
    retry: 1,
  });

  const summary: ClashRunSummary | undefined = runQ.data?.summary;
  const disciplines = summary?.disciplines ?? [];
  const cellMap = useMemo(() => {
    const m = new Map<string, { count: number; open: number }>();
    for (const c of summary?.matrix ?? []) {
      m.set(`${c.a}|${c.b}`, { count: c.count, open: c.open_count });
    }
    return m;
  }, [summary]);
  const maxCell = useMemo(
    () => Math.max(1, ...(summary?.matrix ?? []).map((c) => c.count)),
    [summary],
  );

  // ── KPI counts — AUTHORITATIVE, from the run + its cached summary ──────
  // These reflect the FULL run (which may be 25k+ clashes), never the
  // capped rows loaded into the table. `run.total_clashes` and
  // `summary.by_type` / `summary.by_status` are computed server-side over
  // every clash. The capped row set only feeds the table below.
  const kpis = useMemo(() => {
    const byType = summary?.by_type ?? {};
    const byStatus = summary?.by_status ?? {};
    // Authoritative full-run total: ClashRunResponse.total_clashes.
    const total = runQ.data?.total_clashes ?? 0;
    const hard = byType['hard'] ?? 0;
    const clearance = byType['clearance'] ?? 0;
    const open = OPEN_STATUSES.reduce(
      (acc, s) => acc + (byStatus[s] ?? 0),
      0,
    );
    const resolved =
      (byStatus['resolved'] ?? 0) + (byStatus['approved'] ?? 0);
    const matrixCells = (summary?.matrix ?? []).filter(
      (c) => c.count > 0,
    ).length;
    // Severity histogram — authoritative when the backend supplies it;
    // `bySev` stays undefined on older payloads so the tile degrades.
    const bySev = summary?.by_severity;
    return {
      total,
      hard,
      clearance,
      open,
      resolved,
      resolvedPct: total ? Math.round((resolved / total) * 100) : 0,
      disciplines: (summary?.disciplines ?? []).length,
      matrixCells,
      bySev,
      critical: bySev?.['critical'] ?? 0,
      high: bySev?.['high'] ?? 0,
    };
  }, [runQ.data, summary]);

  // ── Client-side filter pipeline ───────────────────────────────────────
  const filtered = useMemo(() => {
    const q = fSearch.trim().toLowerCase();
    const minPenM = fMinPen / 1000;
    return allResults.filter((r, i) => {
      r.__idx = i; // stable original ordinal for the # column / idx sort
      if (kpiFilter === 'hard' && r.clash_type !== 'hard') return false;
      if (kpiFilter === 'clearance' && r.clash_type !== 'clearance')
        return false;
      if (kpiFilter === 'open' && !OPEN_STATUSES.includes(r.status))
        return false;
      if (
        kpiFilter === 'resolved' &&
        r.status !== 'resolved' &&
        r.status !== 'approved'
      )
        return false;
      if (fType !== 'all' && r.clash_type !== fType) return false;
      if (fSeverity.size > 0 && !fSeverity.has(severityOf(r)))
        return false;
      if (fStatus.size > 0 && !fStatus.has(r.status)) return false;
      if (fPair) {
        const [pa, pb] =
          (r.a_discipline || '') < (r.b_discipline || '')
            ? [r.a_discipline, r.b_discipline]
            : [r.b_discipline, r.a_discipline];
        if (`${pa}|${pb}` !== fPair) return false;
      }
      if (
        fDiscPair.size > 0 &&
        !fDiscPair.has(orderedPairKey(r.a_discipline, r.b_discipline))
      )
        return false;
      if (
        fLevelPair.size > 0 &&
        !fLevelPair.has(orderedPairKey(r.a_storey, r.b_storey))
      )
        return false;
      if (
        fModelPair.size > 0 &&
        !fModelPair.has(orderedPairKey(r.a_model_id, r.b_model_id))
      )
        return false;
      if (r.clash_type === 'hard' && r.penetration_m < minPenM) return false;
      // Wave A4 — restrict to the active cluster chip (null = "all").
      if (
        selectedClusterId !== null &&
        (r.cluster_id ?? null) !== selectedClusterId
      )
        return false;
      if (q) {
        const hay = `${r.a_name} ${r.b_name} ${r.a_stable_id} ${r.b_stable_id} ${r.a_discipline} ${r.b_discipline}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [
    allResults,
    fSearch,
    fMinPen,
    fType,
    fSeverity,
    fStatus,
    fPair,
    fDiscPair,
    fLevelPair,
    fModelPair,
    kpiFilter,
    selectedClusterId,
  ]);

  const sorted = useMemo(() => {
    const arr = [...filtered];
    const dir = sortDir === 'asc' ? 1 : -1;
    arr.sort((a, b) => {
      let av: number | string;
      let bv: number | string;
      switch (sortKey) {
        case 'a_name':
          av = (a.a_name || a.a_stable_id || '').toLowerCase();
          bv = (b.a_name || b.a_stable_id || '').toLowerCase();
          break;
        case 'b_name':
          av = (a.b_name || a.b_stable_id || '').toLowerCase();
          bv = (b.b_name || b.b_stable_id || '').toLowerCase();
          break;
        case 'clash_type':
          av = a.clash_type;
          bv = b.clash_type;
          break;
        case 'severity':
          av = SEVERITY_RANK[severityOf(a)];
          bv = SEVERITY_RANK[severityOf(b)];
          break;
        case 'penetration_m':
          av = a.penetration_m ?? 0;
          bv = b.penetration_m ?? 0;
          break;
        case 'distance_m':
          av = a.distance_m ?? 0;
          bv = b.distance_m ?? 0;
          break;
        case 'status':
          av = STATUS_OPTIONS.indexOf(a.status as StatusOpt);
          bv = STATUS_OPTIONS.indexOf(b.status as StatusOpt);
          break;
        default:
          av = a.__idx ?? 0;
          bv = b.__idx ?? 0;
      }
      if (av < bv) return -1 * dir;
      if (av > bv) return 1 * dir;
      return 0;
    });
    return arr;
  }, [filtered, sortKey, sortDir]);

  // Flat render list. Stacked transforms (applied in order):
  //   1. Group axis — if active, reorder rows by bucket + inject headers.
  //   2. Pair cluster (Wave A2) — if ON, collapse same-pair rows within
  //      each bucket into a master row with N×members, expandable.
  // Pagination runs over this flat list so the sticky table / paging
  // stay unchanged.
  const renderItems = useMemo<RenderItem[]>(() => {
    const cluster = (rows: ClashResult[]): RenderItem[] => {
      if (!pairCluster) {
        return rows.map((row) => ({ kind: 'row', row }) as RenderItem);
      }
      const order: string[] = [];
      const groups = new Map<string, ClashResult[]>();
      for (const r of rows) {
        const k = pairClusterKey(r);
        let g = groups.get(k);
        if (!g) {
          g = [];
          groups.set(k, g);
          order.push(k);
        }
        g.push(r);
      }
      const out: RenderItem[] = [];
      for (const key of order) {
        const members = groups.get(key)!;
        const head = members[0]!;
        if (members.length === 1) {
          out.push({ kind: 'row', row: head });
          continue;
        }
        const label = `${head.a_name || head.a_stable_id} ↔ ${
          head.b_name || head.b_stable_id
        }`;
        out.push({ kind: 'pair', key, label, members, head });
        if (expandedPairs.has(key)) {
          for (const m of members) out.push({ kind: 'row', row: m });
        }
      }
      return out;
    };

    if (resultGroupBy === 'none') {
      return cluster(sorted);
    }
    const order: string[] = [];
    const buckets = new Map<
      string,
      { label: string; rows: ClashResult[] }
    >();
    for (const r of sorted) {
      const { key, label } = resultGroupKey(r, resultGroupBy);
      let b = buckets.get(key);
      if (!b) {
        b = { label, rows: [] };
        buckets.set(key, b);
        order.push(key);
      }
      b.rows.push(r);
    }
    const out: RenderItem[] = [];
    for (const key of order) {
      const b = buckets.get(key)!;
      out.push({
        kind: 'group',
        key,
        label: b.label,
        count: b.rows.length,
      });
      if (!collapsedGroups.has(key)) {
        out.push(...cluster(b.rows));
      }
    }
    return out;
  }, [sorted, resultGroupBy, collapsedGroups, pairCluster, expandedPairs]);

  const pageCount = Math.max(
    1,
    Math.ceil(renderItems.length / PAGE_SIZE),
  );
  const safePage = Math.min(page, pageCount - 1);
  const pageItems = useMemo(
    () =>
      renderItems.slice(
        safePage * PAGE_SIZE,
        safePage * PAGE_SIZE + PAGE_SIZE,
      ),
    [renderItems, safePage],
  );
  // Just the data rows on the current page (selection / select-all only
  // ever operate on actual clashes, never on header markers).
  const pageRows = useMemo(
    () =>
      pageItems
        .filter((it): it is Extract<RenderItem, { kind: 'row' }> =>
          it.kind === 'row',
        )
        .map((it) => it.row),
    [pageItems],
  );

  function toggleGroup(key: string) {
    setCollapsedGroups((s) => {
      const n = new Set(s);
      if (n.has(key)) n.delete(key);
      else n.add(key);
      return n;
    });
  }

  // Reset to first page whenever the filtered set shrinks/changes.
  useEffect(() => {
    setPage(0);
  }, [
    fSearch,
    fMinPen,
    fType,
    fSeverity,
    fStatus,
    fPair,
    fDiscPair,
    fLevelPair,
    fModelPair,
    kpiFilter,
    sortKey,
    sortDir,
    resultGroupBy,
    pairCluster,
  ]);

  const toggleSort = useCallback(
    (k: SortKey) => {
      if (sortKey === k) {
        setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
      } else {
        setSortKey(k);
        setSortDir(k === 'idx' || k === 'a_name' || k === 'b_name' ? 'asc' : 'desc');
      }
    },
    [sortKey],
  );

  const pageIds = useMemo(() => pageRows.map((r) => r.id), [pageRows]);
  const allPageSelected =
    pageIds.length > 0 && pageIds.every((id) => selResults.has(id));
  const somePageSelected = pageIds.some((id) => selResults.has(id));

  function togglePageSelectAll() {
    setSelResults((s) => {
      const n = new Set(s);
      if (allPageSelected) pageIds.forEach((id) => n.delete(id));
      else pageIds.forEach((id) => n.add(id));
      return n;
    });
  }

  function toggleStatusFilter(s: string) {
    setFStatus((cur) => {
      const n = new Set(cur);
      if (n.has(s)) n.delete(s);
      else n.add(s);
      return n;
    });
  }

  function toggleSeverityFilter(s: ClashSeverity) {
    setFSeverity((cur) => {
      const n = new Set(cur);
      if (n.has(s)) n.delete(s);
      else n.add(s);
      return n;
    });
  }

  function clearAllFilters() {
    setFStatus(new Set());
    setFType('all');
    setFSeverity(new Set());
    setFPair('');
    setFMinPen(0);
    setFSearch('');
    setKpiFilter('all');
    setFDiscPair(new Set());
    setFLevelPair(new Set());
    setFModelPair(new Set());
  }

  /** Toggle a key in a Set state (the facet-rail chip contract). */
  function toggleSetKey<T>(
    s: React.Dispatch<React.SetStateAction<Set<T>>>,
    k: T,
  ) {
    s((cur) => {
      const n = new Set(cur);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  }

  const hasActiveFilters =
    fStatus.size > 0 ||
    fType !== 'all' ||
    fSeverity.size > 0 ||
    !!fPair ||
    fMinPen > 0 ||
    !!fSearch.trim() ||
    kpiFilter !== 'all' ||
    fDiscPair.size > 0 ||
    fLevelPair.size > 0 ||
    fModelPair.size > 0;

  // Faceted filter rail counts — derived from the FULL row set so a
  // narrow active filter never makes the other facets read as empty.
  const facets = useMemo(() => {
    const disc = new Map<string, number>();
    const lvl = new Map<string, number>();
    const mdl = new Map<string, number>();
    const sev = new Map<ClashSeverity, number>();
    const sta = new Map<string, number>();
    const typ = new Map<string, number>();
    const modelName = new Map<string, string>();
    for (const m of modelsQ.data ?? []) modelName.set(m.id, m.name);
    for (const r of allResults) {
      disc.set(
        orderedPairKey(r.a_discipline, r.b_discipline),
        (disc.get(orderedPairKey(r.a_discipline, r.b_discipline)) ?? 0) + 1,
      );
      lvl.set(
        orderedPairKey(r.a_storey, r.b_storey),
        (lvl.get(orderedPairKey(r.a_storey, r.b_storey)) ?? 0) + 1,
      );
      mdl.set(
        orderedPairKey(r.a_model_id, r.b_model_id),
        (mdl.get(orderedPairKey(r.a_model_id, r.b_model_id)) ?? 0) + 1,
      );
      const sv = severityOf(r);
      sev.set(sv, (sev.get(sv) ?? 0) + 1);
      sta.set(r.status, (sta.get(r.status) ?? 0) + 1);
      typ.set(r.clash_type, (typ.get(r.clash_type) ?? 0) + 1);
    }
    const modelPairLabel = (key: string) =>
      key
        .split('|')
        .map((id) =>
          id === '—' ? '—' : (modelName.get(id) ?? id.slice(0, 8)),
        )
        .join(' ↔ ');
    const sortDesc = <K,>(m: Map<K, number>) =>
      [...m.entries()].sort((a, b) => b[1] - a[1]);
    return {
      disc: sortDesc(disc),
      level: sortDesc(lvl),
      model: sortDesc(mdl),
      severity: sortDesc(sev),
      status: sortDesc(sta),
      type: sortDesc(typ),
      modelPairLabel,
    };
  }, [allResults, modelsQ.data]);

  /** Build the verified BIM-viewer deep-link for a clash result.
   *
   *  We isolate BOTH interfering elements, flag them clash-red (`clash=1`),
   *  and pass the clash world centroid (`focus=cx,cy,cz`, raw canonical
   *  Z-up — the viewer applies its own Z-up→Y-up rotation) so the camera
   *  reliably frames the interference even on showcase IFC/RVT models whose
   *  GLB nodes are numeric Revit ids that never match the DB element UUIDs
   *  (the per-element mesh resolution is only an approximate positional
   *  fallback there; the centroid is exact). */
  function bimLink(r: ClashResult): string {
    return buildClashBimLink({
      projectId,
      modelId: r.a_model_id,
      aElementId: r.a_element_id,
      bElementId: r.b_element_id,
      cx: r.cx,
      cy: r.cy,
      cz: r.cz,
    });
  }

  // Clamp the keyboard cursor whenever the current page's row set changes
  // (filter / sort / paging) so it never points past the visible rows.
  useEffect(() => {
    setKbRow((cur) =>
      cur < 0 ? cur : Math.min(cur, pageRows.length - 1),
    );
  }, [pageRows.length]);

  // Keyboard navigation for the results table — ↑/↓ or j/k move the
  // selection between visible clash rows, Enter opens the selected clash in
  // the 3D viewer (existing deep-link). MUST ignore keystrokes while an
  // input / textarea / select / contentEditable is focused so it never
  // hijacks typing in the search box, comment field or status dropdown.
  useEffect(() => {
    if (!runId || pageRows.length === 0) return;
    function onKey(e: KeyboardEvent) {
      const el = document.activeElement as HTMLElement | null;
      const tag = el?.tagName;
      if (
        tag === 'INPUT' ||
        tag === 'TEXTAREA' ||
        tag === 'SELECT' ||
        el?.isContentEditable
      ) {
        return;
      }
      if (e.key === 'ArrowDown' || e.key === 'j') {
        e.preventDefault();
        setKbRow((c) => Math.min(pageRows.length - 1, c + 1));
      } else if (e.key === 'ArrowUp' || e.key === 'k') {
        e.preventDefault();
        setKbRow((c) => (c <= 0 ? 0 : c - 1));
      } else if (e.key === 'Enter') {
        if (kbRow >= 0 && kbRow < pageRows.length) {
          e.preventDefault();
          navigate(bimLink(pageRows[kbRow]!));
        }
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // bimLink is stable per render (pure of projectId); pageRows + kbRow
    // are the real deps.
  }, [runId, pageRows, kbRow]); // eslint-disable-line react-hooks/exhaustive-deps

  /** The clash whose collaboration detail panel is open (resolved from the
   *  loaded set so it tracks optimistic comment/assignee/due updates). */
  const detailRow = useMemo(
    () =>
      detailId ? allResults.find((r) => r.id === detailId) ?? null : null,
    [detailId, allResults],
  );

  // Layout mode. Before any run is triggered/selected we show a spacious
  // full-width horizontal setup. Once a run is in flight or a run is
  // selected, the config collapses into a left-rail "menu" and the results
  // take over the main area.
  const compactLayout =
    !!runId || runMut.isPending || runQ.data?.status === 'running';

  // ── No active project ────────────────────────────────────────────────
  // The project is selected globally at the top of the app. If none is set
  // we don't show a picker here — we invite the user to upload a BIM model
  // (a new project) to run coordination on.
  if (!projectId) {
    return (
      <div className="space-y-5 animate-fade-in">
        <Header />
        <Card>
          <EmptyState
            icon={<Upload className="h-10 w-10" />}
            title={t('clash.no_project_title', {
              defaultValue: 'No active project',
            })}
            description={t('clash.no_project_desc', {
              defaultValue:
                'Pick a project from the selector at the top of the page, or upload a BIM model to start coordinating clashes.',
            })}
            action={
              <Link to="/bim">
                <Button
                  variant="primary"
                  size="sm"
                  icon={<Upload className="h-4 w-4" />}
                >
                  {t('clash.upload_model', {
                    defaultValue: 'Upload a BIM model',
                  })}
                </Button>
              </Link>
            }
          />
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Canonical top block: PageHeader (subtitle + actions) then the Beta
            banner, via the shared Header. Project actions are the working
            deep-links into the 3D viewer / element matcher / project
            overview - the selectable CAD-BIM model cards below ARE the
            project's data surface, so there is no separate summary panel. */}
      <Header
        projectId={projectId}
        projectName={ctxProjectName}
        actions={
          <>
            <Button
              variant="secondary"
              size="sm"
              icon={<Box className="h-3.5 w-3.5" />}
              disabled={!projectId}
              onClick={() => {
                // Target the first model that actually has parsed
                // geometry so the viewer opens on valid data, not an
                // empty/unparsed model. Falls back to the global viewer.
                const m =
                  modelsQ.data?.find((x) => (x.element_count ?? 0) > 0) ??
                  modelsQ.data?.[0];
                navigate(
                  m
                    ? `/projects/${projectId}/bim/${m.id}`
                    : projectId
                      ? `/projects/${projectId}/bim`
                      : '/bim',
                );
              }}
            >
              {t('clash.open_bim_viewer', {
                defaultValue: 'Open BIM 3D Viewer',
              })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<ArrowUpRight className="h-3.5 w-3.5" />}
              disabled={!projectId}
              onClick={() => navigate(`/match-elements?project=${projectId}`)}
            >
              {t('clash.match_elements', {
                defaultValue: 'Match / Analyze elements',
              })}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              icon={<FolderOpen className="h-3.5 w-3.5" />}
              disabled={!projectId}
              onClick={() => navigate(`/projects/${projectId}`)}
            >
              {t('clash.project_overview', {
                defaultValue: 'Project overview',
              })}
            </Button>
          </>
        }
      />

      <DismissibleInfo
        storageKey="clash"
        title={t('info.clash.title', {
          defaultValue: 'Clash detection',
        })}
      >
        {t('info.clash.body', {
          defaultValue:
            'Run geometric interference and clearance checks across the canonical BIM models in this project, then triage each clash by discipline, status and severity. Resolved issues link straight into the 3D viewer and export to BCF for coordination with the rest of the platform.',
        })}
      </DismissibleInfo>

      {/* ── Selectable CAD-BIM model cards ──────────────────────────────
            One card per BIM model in the project. Clicking a card toggles
            it into the clash set (cards ARE the model selection). Sits in
            the setup area; shown in both layouts so the user can re-scope
            between runs. */}
      <ModelCardPicker
        models={modelsQ.data}
        loading={modelsQ.isLoading}
        selected={selModels}
        projectName={ctxProjectName}
        compact={compactLayout}
        onToggle={(id) =>
          setSelModels((s) =>
            s.includes(id) ? s.filter((x) => x !== id) : [...s, id],
          )
        }
        onSelectAll={() =>
          setSelModels(
            (modelsQ.data ?? [])
              .filter((m) => m.element_count > 0)
              .map((m) => m.id),
          )
        }
        onClear={() => setSelModels([])}
      />

      <div
        className={clsx(
          'mt-6 grid gap-6',
          compactLayout ? 'lg:grid-cols-[300px_1fr]' : 'grid-cols-1',
        )}
      >
        {/* ── Config rail. Compact → narrow left menu; initial → a wide,
              horizontal full-page setup. ─────────────────────────────── */}
        <div
          className={clsx(
            compactLayout
              ? 'space-y-4'
              : 'grid gap-6 lg:grid-cols-[1fr_320px] lg:items-start',
          )}
        >
          <Card padding="md">
            <div className="flex items-center justify-between gap-2">
              <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
                <Radar className="h-4 w-4 text-oe-blue" />
                {t('clash.new_run', { defaultValue: 'New clash run' })}
              </h2>
              <Link
                to={`/clash/profiles${ctxProjectId ? '' : `?project=${projectId}`}`}
                className="flex items-center gap-1 text-2xs font-medium text-oe-blue hover:underline"
              >
                <Bookmark className="h-3.5 w-3.5" />
                {t('clash.manage_profiles', {
                  defaultValue: 'Manage profiles',
                })}
              </Link>
            </div>

            {/* ── Profile picker (item #23) — pre-populate the form from a
                saved configuration template. Optional; an empty pick keeps
                whatever the user has set. ─────────────────────────────── */}
            {profiles.length > 0 && (
              <label className="mt-3 block text-xs font-medium text-content-secondary">
                {t('clash.load_profile', {
                  defaultValue: 'Load a saved profile',
                })}
                <select
                  value={profileId}
                  onChange={(e) => onPickProfile(e.target.value)}
                  className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
                >
                  <option value="">
                    {t('clash.no_profile', {
                      defaultValue: '- No profile (custom) -',
                    })}
                  </option>
                  {profiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div
              className={clsx(
                'mt-3',
                compactLayout
                  ? 'space-y-3'
                  : 'grid gap-x-6 gap-y-4 md:grid-cols-2 xl:grid-cols-4 items-start',
              )}
            >
              {/* PRIMARY control — what to coordinate. Clash is always
                  intra-project (every selected model's elements tested
                  against each other); the project itself is chosen once,
                  globally, at the top of the app. */}
              <label
                className={clsx(
                  'block text-xs font-medium text-content-secondary',
                  !compactLayout && 'md:col-span-2 xl:col-span-4',
                )}
              >
                {t('clash.mode', {
                  defaultValue: 'What to check for clashes',
                })}
                <select
                  value={mode}
                  onChange={(e) => setMode(e.target.value)}
                  className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
                >
                  <option value="selection_sets">
                    {t('clash.mode_sets', {
                      defaultValue: 'By category / type (Set A vs Set B)',
                    })}
                  </option>
                  <option value="cross_discipline">
                    {t('clash.mode_cross', {
                      defaultValue: 'Cross-discipline only',
                    })}
                  </option>
                  <option value="all">
                    {t('clash.mode_all', { defaultValue: 'Every pair' })}
                  </option>
                </select>
              </label>

              {mode === 'selection_sets' && (
                <div
                  className={clsx(
                    'space-y-2 rounded-lg border border-border bg-surface-secondary/30 p-2',
                    !compactLayout && 'md:col-span-2 xl:col-span-4',
                  )}
                >
                  <p className="text-2xs leading-snug text-content-tertiary">
                    {t('clash.sets_hint', {
                      defaultValue:
                        'Only pairs where one element is in Set A and the other in Set B are tested - e.g. all Walls (A) against all Pipes (B).',
                    })}
                  </p>

                  {/* GROUPING parameter — the element parameter the Set A
                      / Set B facet lists are built from. The four built-ins
                      (IFC-only options appear only when the selected models
                      carry that data) plus every distinct element-property
                      key the backend surfaced (older backends → built-ins
                      only). */}
                  <label className="block text-2xs font-medium text-content-secondary">
                    {t('clash.group_by', {
                      defaultValue: 'Group elements by',
                    })}
                    <select
                      value={groupBy}
                      onChange={(e) =>
                        setGroupBy(e.target.value as ClashGroupBy)
                      }
                      className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-xs"
                    >
                      {ALL_GROUP_BY.filter((g) =>
                        availableGroupBy.includes(g),
                      ).map((g) => (
                        <option key={g} value={g}>
                          {GROUP_BY_LABELS[g](t)}
                        </option>
                      ))}
                      {availableProperties.length > 0 && (
                        <optgroup
                          label={t('clash.group_properties', {
                            defaultValue: 'Element properties',
                          })}
                        >
                          {availableProperties.map((p) => (
                            <option
                              key={`property:${p.key}`}
                              value={`property:${p.key}`}
                            >
                              {t('clash.group_property_option', {
                                defaultValue: '{{key}} ({{count}})',
                                key: p.key,
                                count: p.count,
                              })}
                            </option>
                          ))}
                        </optgroup>
                      )}
                    </select>
                  </label>

                  <div
                    className={clsx(
                      compactLayout
                        ? 'space-y-2'
                        : 'grid gap-3 lg:grid-cols-2',
                    )}
                  >
                    <SelectionSetPicker
                      label={t('clash.set_a', { defaultValue: 'Set A' })}
                      accent="oe-blue"
                      value={setA}
                      onChange={setSetA}
                      categories={categoriesQ.data}
                      groupBy={groupBy}
                      loading={categoriesQ.isLoading}
                    />
                    <SelectionSetPicker
                      label={t('clash.set_b', { defaultValue: 'Set B' })}
                      accent="amber"
                      value={setB}
                      onChange={setSetB}
                      categories={categoriesQ.data}
                      groupBy={groupBy}
                      loading={categoriesQ.isLoading}
                    />
                  </div>
                  {!selectionSetsValid && (
                    <p className="text-2xs text-semantic-error">
                      {t('clash.sets_required', {
                        defaultValue:
                          'Pick at least one value for both Set A and Set B.',
                      })}
                    </p>
                  )}
                </div>
              )}

              {/* CLASH TYPE — Navisworks-style "Type" rule selector. The
                  single most load-bearing run parameter: it decides
                  WHICH interference the engine reports. Hard = real
                  interpenetration; Clearance = proximity (no overlap)
                  within the clearance gap; Both = the universal default
                  (hard, then clearance for the non-hard pairs). */}
              <label
                className={clsx(
                  'block text-xs font-medium text-content-secondary',
                  !compactLayout && 'md:col-span-2 xl:col-span-4',
                )}
              >
                {t('clash.clash_type', {
                  defaultValue: 'Clash type',
                })}
                <select
                  value={clashType}
                  onChange={(e) =>
                    setClashType(e.target.value as ClashType)
                  }
                  className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
                >
                  <option value="both">
                    {t('clash.ct_both', {
                      defaultValue:
                        'Hard + Clearance (interference & proximity)',
                    })}
                  </option>
                  <option value="hard">
                    {t('clash.ct_hard', {
                      defaultValue: 'Hard only - true interpenetration',
                    })}
                  </option>
                  <option value="clearance">
                    {t('clash.ct_clearance', {
                      defaultValue:
                        'Clearance only - proximity, no overlap',
                    })}
                  </option>
                </select>
                <span className="mt-1 block text-2xs leading-snug text-content-tertiary">
                  {clashType === 'hard'
                    ? t('clash.ct_hard_hint', {
                        defaultValue:
                          'Reports only element pairs whose geometry actually interpenetrates beyond the tolerance. The clearance pass is skipped.',
                      })
                    : clashType === 'clearance'
                      ? t('clash.ct_clearance_hint', {
                          defaultValue:
                            'Reports only pairs that do NOT overlap but sit within the clearance distance (e.g. maintenance access). Set a clearance > 0.',
                        })
                      : t('clash.ct_both_hint', {
                          defaultValue:
                            'Reports hard interferences, then a clearance violation for any non-hard pair within the clearance distance.',
                        })}
                </span>
              </label>

              {/* Tolerance presets + the two raw mm inputs. Hard tolerance
                  is greyed when the run is clearance-only (it has no
                  effect); clearance is greyed when hard-only. */}
              <div
                className={clsx(
                  'space-y-2',
                  !compactLayout && 'md:col-span-2 xl:col-span-4',
                )}
              >
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                    {t('clash.tol_presets', {
                      defaultValue: 'Tolerance preset',
                    })}
                  </span>
                  {TOLERANCE_PRESETS.map((p) => (
                    <button
                      key={p.key}
                      type="button"
                      onClick={() => setToleranceMm(p.mm)}
                      className={clsx(
                        'rounded-full px-2 py-0.5 text-2xs font-medium transition-colors',
                        toleranceMm === p.mm
                          ? 'bg-oe-blue text-content-inverse'
                          : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary',
                      )}
                    >
                      {t(`clash.tol_${p.key}`, { defaultValue: p.label })}
                    </button>
                  ))}
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <label
                    className={clsx(
                      'text-xs text-content-secondary',
                      clashType === 'clearance' && 'opacity-50',
                    )}
                  >
                    {t('clash.tolerance', {
                      defaultValue: 'Tolerance (mm)',
                    })}
                    <input
                      type="number"
                      min={0}
                      step={1}
                      disabled={clashType === 'clearance'}
                      value={toleranceMm}
                      onChange={(e) =>
                        setToleranceMm(Number(e.target.value))
                      }
                      className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1 text-sm disabled:cursor-not-allowed"
                    />
                  </label>
                  <label
                    className={clsx(
                      'text-xs text-content-secondary',
                      clashType === 'hard' && 'opacity-50',
                    )}
                  >
                    {t('clash.clearance', {
                      defaultValue: 'Clearance (mm)',
                    })}
                    <input
                      type="number"
                      min={0}
                      step={1}
                      disabled={clashType === 'hard'}
                      value={clearanceMm}
                      onChange={(e) =>
                        setClearanceMm(Number(e.target.value))
                      }
                      className={clsx(
                        'mt-1 w-full rounded-md border bg-surface-primary px-2 py-1 text-sm disabled:cursor-not-allowed',
                        clearanceMisconfigured
                          ? 'border-semantic-error'
                          : 'border-border',
                      )}
                    />
                  </label>
                </div>
                {clearanceMisconfigured && (
                  <p className="text-2xs text-semantic-error">
                    {t('clash.clearance_required', {
                      defaultValue:
                        'A clearance-only run needs a clearance distance greater than 0 to find anything.',
                    })}
                  </p>
                )}
              </div>

              {/* Federated noise filter — only meaningful with >1 model
                  in scope (otherwise every pair is intra-model). */}
              {multiModelScope && (
                <label
                  className={clsx(
                    'flex cursor-pointer items-start gap-2 rounded-lg border border-border bg-surface-secondary/30 p-2 text-xs text-content-secondary',
                    !compactLayout && 'md:col-span-2 xl:col-span-4',
                  )}
                >
                  <input
                    type="checkbox"
                    checked={ignoreSameModel}
                    onChange={(e) =>
                      setIgnoreSameModel(e.target.checked)
                    }
                    className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-oe-blue"
                  />
                  <span>
                    <span className="font-medium text-content-primary">
                      {t('clash.ignore_same_model', {
                        defaultValue:
                          'Ignore clashes within the same model',
                      })}
                    </span>
                    <span className="mt-0.5 block text-2xs leading-snug text-content-tertiary">
                      {t('clash.ignore_same_model_hint', {
                        defaultValue:
                          'Only report pairs whose two elements come from different BIM models - strips the intra-model self-clash noise from a federated coordination run.',
                      })}
                    </span>
                  </span>
                </label>
              )}

              {/* Run identity — name + description so the run is
                  recognisable in history (not "Clash run 2026-…"). */}
              <div
                className={clsx(
                  'grid gap-2',
                  !compactLayout &&
                    'md:col-span-2 xl:col-span-4 sm:grid-cols-2',
                )}
              >
                <label className="text-xs text-content-secondary">
                  {t('clash.run_name', {
                    defaultValue: 'Run name (optional)',
                  })}
                  <input
                    type="text"
                    maxLength={255}
                    value={runName}
                    onChange={(e) => setRunName(e.target.value)}
                    placeholder={t('clash.run_name_ph', {
                      defaultValue: 'e.g. Struct vs MEP - L3 coordination',
                    })}
                    className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1 text-sm"
                  />
                </label>
                <label className="text-xs text-content-secondary">
                  {t('clash.run_desc', {
                    defaultValue: 'Description (optional)',
                  })}
                  <input
                    type="text"
                    maxLength={2000}
                    value={runDesc}
                    onChange={(e) => setRunDesc(e.target.value)}
                    placeholder={t('clash.run_desc_ph', {
                      defaultValue: 'Scope / intent / reviewer note',
                    })}
                    className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1 text-sm"
                  />
                </label>
              </div>

              {/* Model selection lives in the prominent card picker
                  above (the cards ARE the scope). The picker also covers
                  the "no parsed models" empty state. */}

              <div
                className={clsx(
                  'flex items-end gap-2',
                  !compactLayout && 'md:col-span-2 xl:col-span-4',
                )}
              >
                <Button
                  variant="primary"
                  size="sm"
                  className="flex-1"
                  loading={runMut.isPending}
                  disabled={
                    selModels.length === 0 ||
                    !selectionSetsValid ||
                    clearanceMisconfigured
                  }
                  icon={<Play className="h-4 w-4" />}
                  onClick={() => runMut.mutate()}
                >
                  {t('clash.run', { defaultValue: 'Run clash detection' })}
                </Button>
                {/* Save-as-profile (item #23): snapshot the current config
                    as a reusable named profile. Disabled when the config is
                    invalid (same gate as Run, minus the model requirement —
                    a profile carries no models). */}
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!selectionSetsValid || clearanceMisconfigured}
                  icon={<Bookmark className="h-4 w-4" />}
                  onClick={() => {
                    setSaveProfileName(runName.trim());
                    setShowSaveProfile(true);
                  }}
                  title={t('clash.save_as_profile', {
                    defaultValue: 'Save configuration as a profile',
                  })}
                >
                  {t('clash.save_profile', { defaultValue: 'Save profile' })}
                </Button>
              </div>
            </div>
          </Card>

          {/* Save-as-profile dialog (item #23). */}
          {showSaveProfile && (
            <div
              className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
              role="dialog"
              aria-modal="true"
              onClick={() => setShowSaveProfile(false)}
            >
              <div
                className="w-full max-w-md rounded-2xl border border-border-subtle bg-surface-0 shadow-xl"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="flex items-center justify-between border-b border-border-subtle px-5 py-4">
                  <h2 className="flex items-center gap-2 text-base font-semibold text-content-primary">
                    <Bookmark className="h-4 w-4 text-oe-blue" />
                    {t('clash.save_as_profile', {
                      defaultValue: 'Save configuration as a profile',
                    })}
                  </h2>
                  <button
                    type="button"
                    onClick={() => setShowSaveProfile(false)}
                    aria-label={t('common.close', { defaultValue: 'Close' })}
                    className="flex h-7 w-7 items-center justify-center rounded text-content-tertiary hover:text-content-primary"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
                <div className="px-5 py-4">
                  <label className="block text-xs font-medium text-content-secondary">
                    {t('clash.profile_name', { defaultValue: 'Profile name' })}
                    <input
                      type="text"
                      maxLength={255}
                      value={saveProfileName}
                      onChange={(e) => setSaveProfileName(e.target.value)}
                      placeholder={t('clash.profile_name_ph', {
                        defaultValue: 'e.g. MEP × Structural - tight',
                      })}
                      className="mt-1 w-full rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
                    />
                  </label>
                  <p className="mt-2 text-2xs text-content-tertiary">
                    {t('clash.save_profile_hint', {
                      defaultValue:
                        'Saves the tolerance, clearance, type, mode and selection sets above. Models are not part of a profile.',
                    })}
                  </p>
                </div>
                <div className="flex items-center justify-end gap-2 border-t border-border-subtle px-5 py-4">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setShowSaveProfile(false)}
                  >
                    {t('common.cancel', { defaultValue: 'Cancel' })}
                  </Button>
                  <Button
                    size="sm"
                    loading={saveProfileMut.isPending}
                    disabled={
                      !saveProfileName.trim() || saveProfileMut.isPending
                    }
                    icon={<Save className="h-4 w-4" />}
                    onClick={() => saveProfileMut.mutate()}
                  >
                    {t('common.save', { defaultValue: 'Save' })}
                  </Button>
                </div>
              </div>
            </div>
          )}

          <Card padding="md">
            <h2 className="text-sm font-semibold text-content-primary">
              {t('clash.history', { defaultValue: 'Run history' })}
            </h2>

            {/* Run-to-run comparison — pick an earlier run to diff the
                active run against. The diff renders in the main column. */}
            {runId &&
              (runsQ.data ?? []).filter((r) => r.id !== runId).length >
                0 && (
                <label className="mt-2 flex items-center gap-1.5 text-2xs text-content-secondary">
                  <GitCompareArrows className="h-3.5 w-3.5 shrink-0 text-content-tertiary" />
                  <span className="shrink-0 font-medium uppercase tracking-wide text-content-tertiary">
                    {t('clash.compare_to', {
                      defaultValue: 'Compare to',
                    })}
                  </span>
                  <select
                    value={compareBaseId ?? ''}
                    onChange={(e) =>
                      setCompareBaseId(e.target.value || null)
                    }
                    className="h-7 min-w-0 flex-1 rounded-md border border-border bg-surface-primary px-1.5 text-2xs text-content-primary"
                  >
                    <option value="">
                      {t('clash.compare_none', {
                        defaultValue: 'No comparison',
                      })}
                    </option>
                    {(runsQ.data ?? [])
                      .filter((r) => r.id !== runId)
                      .map((r) => (
                        <option key={r.id} value={r.id}>
                          {r.name} · {r.total_clashes}
                        </option>
                      ))}
                  </select>
                </label>
              )}

            <div className="mt-2 space-y-1">
              {(runsQ.data ?? []).length === 0 && (
                <p className="text-xs text-content-tertiary">
                  {t('clash.no_runs', { defaultValue: 'No runs yet.' })}
                </p>
              )}
              {(runsQ.data ?? []).map((r) => (
                <div
                  key={r.id}
                  className={clsx(
                    'flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs',
                    r.id === runId
                      ? 'bg-oe-blue/10 text-oe-blue'
                      : 'hover:bg-surface-secondary text-content-primary',
                  )}
                >
                  <button
                    className="flex-1 truncate text-left"
                    title={r.description || r.name}
                    onClick={() =>
                      setParams((p) => {
                        p.set('run', r.id);
                        return p;
                      })
                    }
                  >
                    {r.name}
                    {r.clash_type && r.clash_type !== 'both' && (
                      <span className="ml-1 rounded-full bg-surface-secondary px-1.5 text-[10px] font-medium text-content-secondary">
                        {r.clash_type === 'hard'
                          ? t('clash.type_hard', {
                              defaultValue: 'Hard',
                            })
                          : t('clash.type_clearance', {
                              defaultValue: 'Clearance',
                            })}
                      </span>
                    )}
                    <span className="ml-1 text-content-tertiary">
                      · {r.total_clashes}
                    </span>
                  </button>
                  <button
                    aria-label={t('common.delete', {
                      defaultValue: 'Delete',
                    })}
                    onClick={async () => {
                      const ok = await confirm({
                        title: t('clash.run_delete_title', {
                          defaultValue: 'Delete run?',
                        }),
                        message: t('clash.run_delete_confirm', {
                          defaultValue:
                            'Delete run "{{name}}" and all its results, comments and history? This cannot be undone.',
                          name: r.name,
                        }),
                        confirmLabel: t('common.delete', {
                          defaultValue: 'Delete',
                        }),
                        variant: 'danger',
                      });
                      if (!ok) return;
                      delMut.mutate(r.id);
                    }}
                    className="text-content-tertiary hover:text-semantic-error"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* ── Main: KPIs + matrix + review workspace ────────────────── */}
        <div className="min-w-0 space-y-6">
          {(runMut.isPending || runQ.data?.status === 'running') && (
            <Card padding="md" className="border-oe-blue/30">
              <div className="flex items-center gap-3">
                <Loader2 className="h-5 w-5 shrink-0 animate-spin text-oe-blue" />
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-content-primary">
                    {t('clash.running_title', {
                      defaultValue: 'Running clash detection…',
                    })}
                  </p>
                  <p className="text-xs text-content-tertiary">
                    {t('clash.running_desc', {
                      defaultValue:
                        'Testing element geometry for interferences. This can take up to ~30s on large models - please keep this tab open.',
                    })}
                  </p>
                </div>
              </div>
              <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-surface-secondary">
                <div
                  className="h-full w-1/3 rounded-full bg-gradient-to-r from-oe-blue/40 via-oe-blue to-oe-blue/40"
                  style={{
                    animation: 'indeterminate 1.15s ease-in-out infinite',
                  }}
                />
              </div>
            </Card>
          )}

          {/* ── Run-to-run comparison ──────────────────────────────
                Diff the active run against the picked base run: New /
                Resolved / Persistent buckets. Lives in the main column,
                ABOVE the KPI/matrix/table — it is what a coordinator
                checks first after a re-run. */}
          {compareBaseId && (
            <CompareSection
              loading={compareQ.isLoading}
              error={
                compareQ.isError
                  ? compareQ.error instanceof Error
                    ? compareQ.error.message
                    : t('clash.compare_error', {
                        defaultValue:
                          'Could not compare the runs.',
                      })
                  : null
              }
              data={compareQ.data}
              collapsed={compareCollapsed}
              onToggle={(k) =>
                setCompareCollapsed((s) => {
                  const n = new Set(s);
                  if (n.has(k)) n.delete(k);
                  else n.add(k);
                  return n;
                })
              }
              onClose={() => setCompareBaseId(null)}
              resultById={(id) =>
                allResults.find((r) => r.id === id) ?? null
              }
              bimLink={bimLink}
              t={t}
            />
          )}

          {runId && runQ.data && (
            <>
              {/* ── Wave A4 — rule-suggestion banner + cluster chips +
                    KPI / rules quick actions. Sits just above the KPI
                    tiles so the coordinator sees engine-mined hints
                    before drilling into the result table. */}
              <ClashRuleSuggestionBanner
                projectId={projectId}
                runId={runId}
              />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <ClashClusterChips
                  projectId={projectId}
                  runId={runId}
                  selectedClusterId={selectedClusterId}
                  onSelect={setSelectedClusterId}
                  totalClashes={runQ.data.total_clashes}
                />
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => setRulesOpen(true)}
                  >
                    {t('clash.rules.open_editor', { defaultValue: 'Rules…' })}
                  </Button>
                  <Button
                    variant={kpiTabOpen ? 'primary' : 'secondary'}
                    size="sm"
                    onClick={() => setKpiTabOpen((v) => !v)}
                  >
                    {kpiTabOpen
                      ? t('clash.kpi_panel.hide', { defaultValue: 'Hide KPI dashboard' })
                      : t('clash.kpi_panel.show', { defaultValue: 'KPI dashboard' })}
                  </Button>
                </div>
              </div>
              {kpiTabOpen && (
                <ClashKpiPanel projectId={projectId} runId={runId} />
              )}
              <ClashRuleEditor
                open={rulesOpen}
                onClose={() => setRulesOpen(false)}
                projectId={projectId}
                runId={runId}
              />

              {/* ── KPI tiles ──────────────────────────────────────── */}
              <div
                className={clsx(
                  'grid grid-cols-2 gap-3 sm:grid-cols-4',
                  // The severity tile only renders when the backend sends
                  // `by_severity` — keep the row balanced either way.
                  kpis.bySev ? 'xl:grid-cols-8' : 'xl:grid-cols-7',
                )}
              >
                <Kpi
                  icon={<Layers className="h-4 w-4" />}
                  label={t('clash.kpi_total', {
                    defaultValue: 'Total clashes',
                  })}
                  value={kpis.total}
                  active={kpiFilter === 'all'}
                  onClick={() => setKpiFilter('all')}
                />
                {kpis.bySev && (
                  <Kpi
                    icon={
                      <AlertTriangle className="h-4 w-4 text-semantic-error" />
                    }
                    label={t('clash.kpi_critical', {
                      defaultValue: 'Critical / High',
                    })}
                    value={`${kpis.critical} / ${kpis.high}`}
                    active={
                      fSeverity.has('critical') || fSeverity.has('high')
                    }
                    onClick={() =>
                      setFSeverity((cur) => {
                        // One-click "show the urgent ones": toggle the
                        // critical+high severity filter as a pair.
                        const on =
                          cur.has('critical') || cur.has('high');
                        const n = new Set(cur);
                        if (on) {
                          n.delete('critical');
                          n.delete('high');
                        } else {
                          n.add('critical');
                          n.add('high');
                        }
                        return n;
                      })
                    }
                  />
                )}
                <Kpi
                  icon={
                    <AlertTriangle className="h-4 w-4 text-semantic-error" />
                  }
                  label={t('clash.kpi_hard', { defaultValue: 'Hard' })}
                  value={kpis.hard}
                  active={kpiFilter === 'hard'}
                  onClick={() =>
                    setKpiFilter((v) => (v === 'hard' ? 'all' : 'hard'))
                  }
                />
                <Kpi
                  icon={<Ruler className="h-4 w-4 text-amber-500" />}
                  label={t('clash.kpi_clearance', {
                    defaultValue: 'Clearance',
                  })}
                  value={kpis.clearance}
                  active={kpiFilter === 'clearance'}
                  onClick={() =>
                    setKpiFilter((v) =>
                      v === 'clearance' ? 'all' : 'clearance',
                    )
                  }
                />
                <Kpi
                  icon={<CheckCircle2 className="h-4 w-4 text-oe-blue" />}
                  label={t('clash.kpi_open', { defaultValue: 'Open' })}
                  value={kpis.open}
                  active={kpiFilter === 'open'}
                  onClick={() =>
                    setKpiFilter((v) => (v === 'open' ? 'all' : 'open'))
                  }
                />
                <Kpi
                  icon={
                    <CheckCircle2 className="h-4 w-4 text-semantic-success" />
                  }
                  label={t('clash.kpi_resolved', {
                    defaultValue: 'Resolved',
                  })}
                  value={`${kpis.resolvedPct}%`}
                  active={kpiFilter === 'resolved'}
                  onClick={() =>
                    setKpiFilter((v) =>
                      v === 'resolved' ? 'all' : 'resolved',
                    )
                  }
                />
                <Kpi
                  icon={<Box className="h-4 w-4 text-content-tertiary" />}
                  label={t('clash.kpi_disciplines', {
                    defaultValue: 'Disciplines',
                  })}
                  value={kpis.disciplines}
                />
                <Kpi
                  icon={<Grid3x3 className="h-4 w-4 text-content-tertiary" />}
                  label={t('clash.kpi_matrix_cells', {
                    defaultValue: 'Matrix cells',
                  })}
                  value={kpis.matrixCells}
                />
              </div>

              {/* ── Clash matrix ───────────────────────────────────── */}
              <Card padding="md">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold text-content-primary">
                    {t('clash.matrix_title', {
                      defaultValue:
                        'Clash matrix - discipline × discipline',
                    })}
                  </h2>
                  {fPair && (
                    <Button
                      variant="ghost"
                      size="sm"
                      icon={<X className="h-3.5 w-3.5" />}
                      onClick={() => setFPair('')}
                    >
                      {t('clash.clear_filter', {
                        defaultValue: 'Clear filter',
                      })}
                    </Button>
                  )}
                </div>
                {disciplines.length === 0 ? (
                  <p className="mt-3 text-sm text-content-tertiary">
                    {t('clash.no_clashes', {
                      defaultValue:
                        'No clashes - the models are clean.',
                    })}
                  </p>
                ) : (
                  <div className="mt-3 overflow-auto">
                    <table className="border-collapse text-xs">
                      <thead>
                        <tr>
                          <th className="p-2" />
                          {disciplines.map((d) => (
                            <th
                              key={d}
                              className="p-2 font-medium text-content-secondary"
                            >
                              {d}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {disciplines.map((row) => (
                          <tr key={row}>
                            <th className="p-2 text-right font-medium text-content-secondary">
                              {row}
                            </th>
                            {disciplines.map((col) => {
                              const [a, b] =
                                row < col ? [row, col] : [col, row];
                              const cell = cellMap.get(`${a}|${b}`);
                              const c = cell?.count ?? 0;
                              const pairKey = `${a}|${b}`;
                              const isActive = fPair === pairKey;
                              return (
                                <td key={col} className="p-1">
                                  <button
                                    disabled={c === 0}
                                    onClick={() =>
                                      setFPair((cur) =>
                                        cur === pairKey ? '' : pairKey,
                                      )
                                    }
                                    className={clsx(
                                      'flex h-12 w-16 flex-col items-center justify-center rounded-md font-semibold transition-transform',
                                      heat(c, maxCell),
                                      c > 0 && 'hover:scale-105',
                                      isActive &&
                                        'ring-2 ring-oe-blue ring-offset-1',
                                    )}
                                    title={`${a} ↔ ${b}: ${c}`}
                                  >
                                    <span>{c || '·'}</span>
                                    {cell && cell.open > 0 && (
                                      <span className="text-[10px] font-normal opacity-80">
                                        {t('clash.matrix_open', {
                                          defaultValue: '{{n}} open',
                                          n: cell.open,
                                        })}
                                      </span>
                                    )}
                                  </button>
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>

              {/* ── Multi-dimensional grouping (item #23) ─────────────── */}
              {runId && disciplines.length > 0 && (
                <ClashGroupingPanel projectId={projectId} runId={runId} />
              )}

              {/* ── Review workspace ──────────────────────────────── */}
              <Card padding="none">
                {/* Toolbar */}
                <div className="border-b border-border-light p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
                      {t('clash.results', {
                        defaultValue: 'Clash results',
                      })}
                      <Badge variant="neutral" size="sm">
                        {t('clash.count_of', {
                          defaultValue: '{{shown}} of {{total}}',
                          shown: sorted.length,
                          total: kpis.total,
                        })}
                      </Badge>
                    </h2>

                    <div className="relative ml-auto">
                      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-content-tertiary" />
                      <input
                        value={fSearch}
                        onChange={(e) => setFSearch(e.target.value)}
                        placeholder={t('clash.search_ph', {
                          defaultValue: 'Search element name…',
                        })}
                        className="h-8 w-56 rounded-md border border-border bg-surface-primary pl-8 pr-2 text-xs"
                      />
                    </div>

                    <select
                      value={fType}
                      onChange={(e) =>
                        setFType(
                          e.target.value as 'all' | 'hard' | 'clearance',
                        )
                      }
                      className="h-8 rounded-md border border-border bg-surface-primary px-2 text-xs"
                    >
                      <option value="all">
                        {t('clash.all_types', {
                          defaultValue: 'All types',
                        })}
                      </option>
                      <option value="hard">
                        {t('clash.type_hard', { defaultValue: 'Hard' })}
                      </option>
                      <option value="clearance">
                        {t('clash.type_clearance', {
                          defaultValue: 'Clearance',
                        })}
                      </option>
                    </select>

                    {/* Result aggregation — group the review list the way
                        a coordinator triages (Navisworks "Group by"). */}
                    <label className="flex items-center gap-1.5 text-2xs text-content-tertiary">
                      <Layers className="h-3.5 w-3.5" />
                      <span className="font-medium uppercase tracking-wide">
                        {t('clash.group_results', {
                          defaultValue: 'Group',
                        })}
                      </span>
                      <select
                        value={resultGroupBy}
                        onChange={(e) =>
                          setResultGroupBy(
                            e.target.value as ResultGroupBy,
                          )
                        }
                        className="h-8 rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary"
                      >
                        <option value="none">
                          {t('clash.grp_none', {
                            defaultValue: 'No grouping',
                          })}
                        </option>
                        <option value="pair">
                          {t('clash.grp_pair', {
                            defaultValue: 'Discipline pair',
                          })}
                        </option>
                        <option value="clash_type">
                          {t('clash.grp_type', {
                            defaultValue: 'Clash type',
                          })}
                        </option>
                        <option value="status">
                          {t('clash.grp_status', {
                            defaultValue: 'Status',
                          })}
                        </option>
                        <option value="element_a">
                          {t('clash.grp_element_a', {
                            defaultValue: 'Element A',
                          })}
                        </option>
                      </select>
                    </label>

                    {/* Wave A2 — pair clustering. Independent of the group
                        axis: collapses every row sharing the same unordered
                        element pair into one master row with N×members. */}
                    <button
                      type="button"
                      onClick={() => setPairCluster((v) => !v)}
                      className={clsx(
                        'inline-flex h-8 items-center gap-1 rounded-md border px-2 text-2xs font-medium transition-colors',
                        pairCluster
                          ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                          : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-tertiary',
                      )}
                      title={t('clash.pair_cluster_hint', {
                        defaultValue:
                          'Collapse rows that share the same element pair into one master row.',
                      })}
                    >
                      <Link2 className="h-3.5 w-3.5" />
                      {t('clash.pair_cluster_toggle', {
                        defaultValue: 'Group by element pair',
                      })}
                    </button>

                    {/* Wave A2 — Advanced (faceted) filter rail toggle. */}
                    <button
                      type="button"
                      onClick={() => setShowFacets((v) => !v)}
                      className={clsx(
                        'inline-flex h-8 items-center gap-1 rounded-md border px-2 text-2xs font-medium transition-colors',
                        showFacets
                          ? 'border-oe-blue bg-oe-blue/10 text-oe-blue'
                          : 'border-border bg-surface-primary text-content-secondary hover:bg-surface-tertiary',
                      )}
                    >
                      <Filter className="h-3.5 w-3.5" />
                      {t('clash.advanced_filters', {
                        defaultValue: 'Advanced filters',
                      })}
                    </button>

                    {/* Wave A3 — BCF round-trip import. Hidden file input
                        driven by a regular Button so the action sits in
                        the same toolbar row as the Export BCF button. */}
                    <input
                      ref={bcfFileInputRef}
                      type="file"
                      accept=".bcfzip,.bcf,application/zip"
                      className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0];
                        if (f) importBcfMut.mutate(f);
                        if (e.target) e.target.value = '';
                      }}
                    />
                    <Button
                      variant="secondary"
                      size="sm"
                      loading={importBcfMut.isPending}
                      icon={<FileUp className="h-4 w-4" />}
                      onClick={() => bcfFileInputRef.current?.click()}
                    >
                      {t('clash.import_bcf', {
                        defaultValue: 'Import BCF',
                      })}
                    </Button>

                    <Button
                      variant={
                        selResults.size ? 'primary' : 'secondary'
                      }
                      size="sm"
                      loading={exportMut.isPending}
                      icon={<FileDown className="h-4 w-4" />}
                      onClick={() =>
                        exportMut.mutate(
                          selResults.size ? [...selResults] : null,
                        )
                      }
                    >
                      {selResults.size
                        ? t('clash.export_sel', {
                            defaultValue: 'Export {{n}} to BCF',
                            n: selResults.size,
                          })
                        : t('clash.export_open', {
                            defaultValue: 'Export open → BCF',
                          })}
                    </Button>

                    {/* CSV export — server-rendered, honours the active
                        single-value status/type/severity filters. */}
                    <Button
                      variant="secondary"
                      size="sm"
                      loading={csvMut.isPending}
                      icon={<FileDown className="h-4 w-4" />}
                      onClick={() =>
                        csvMut.mutate({
                          // Only forward filters the list endpoint accepts:
                          // a single status / a single severity / type.
                          ...(fStatus.size === 1
                            ? { status: [...fStatus][0] }
                            : {}),
                          ...(fSeverity.size === 1
                            ? { severity: [...fSeverity][0] }
                            : {}),
                          ...(fType !== 'all'
                            ? { clash_type: fType }
                            : {}),
                        })
                      }
                    >
                      {t('clash.export_csv', {
                        defaultValue: 'Export CSV',
                      })}
                    </Button>
                  </div>

                  {/* Status filter pills + min-penetration slider.
                      Wave A2 — hidden when the facet rail is open
                      (the rail covers status / severity / type natively). */}
                  {!showFacets && (
                  <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-3">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="flex items-center gap-1 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                        <SlidersHorizontal className="h-3 w-3" />
                        {t('clash.filter_status', {
                          defaultValue: 'Status',
                        })}
                      </span>
                      {STATUS_OPTIONS.map((s) => (
                        <button
                          key={s}
                          onClick={() => toggleStatusFilter(s)}
                          className={clsx(
                            'rounded-full px-2 py-0.5 text-2xs font-medium transition-colors',
                            fStatus.has(s)
                              ? 'bg-oe-blue text-content-inverse'
                              : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary',
                          )}
                        >
                          {t(`clash.status.${s}`, { defaultValue: s })}
                        </button>
                      ))}
                    </div>

                    {/* Severity filter pills — coloured to match the table
                        badge so the filter and the column read as one. */}
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="flex items-center gap-1 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
                        <AlertTriangle className="h-3 w-3" />
                        {t('clash.filter_severity', {
                          defaultValue: 'Severity',
                        })}
                      </span>
                      {SEVERITY_OPTIONS.map((s) => (
                        <button
                          key={s}
                          onClick={() => toggleSeverityFilter(s)}
                          className={clsx(
                            'rounded-full px-2 py-0.5 text-2xs font-medium capitalize transition-colors',
                            fSeverity.has(s)
                              ? 'bg-oe-blue text-content-inverse'
                              : SEVERITY_BADGE[s],
                          )}
                        >
                          {t(`clash.severity.${s}`, { defaultValue: s })}
                        </button>
                      ))}
                    </div>

                    <label className="flex items-center gap-2 text-2xs text-content-secondary">
                      <span className="font-medium uppercase tracking-wide text-content-tertiary">
                        {t('clash.filter_min_pen', {
                          defaultValue: 'Min penetration',
                        })}
                      </span>
                      <input
                        type="range"
                        min={0}
                        max={500}
                        step={5}
                        value={fMinPen}
                        onChange={(e) =>
                          setFMinPen(Number(e.target.value))
                        }
                        className="h-1 w-32 accent-oe-blue"
                      />
                      <span className="w-14 tabular-nums text-content-primary">
                        {fMinPen} mm
                      </span>
                    </label>

                    {/* Keyboard-navigation hint — subtle, non-blocking. */}
                    <span
                      className="ml-auto hidden items-center gap-1.5 text-2xs text-content-tertiary sm:flex"
                      title={t('clash.kbd_hint_full', {
                        defaultValue:
                          'Use ↑/↓ or J/K to move between clashes, Enter to open the selected clash in 3D.',
                      })}
                    >
                      <Keyboard className="h-3.5 w-3.5" />
                      <kbd className="rounded border border-border bg-surface-secondary px-1 font-mono">
                        ↑↓
                      </kbd>
                      <span>/</span>
                      <kbd className="rounded border border-border bg-surface-secondary px-1 font-mono">
                        J K
                      </kbd>
                      <span>
                        {t('clash.kbd_move', { defaultValue: 'move' })}
                      </span>
                      <kbd className="rounded border border-border bg-surface-secondary px-1 font-mono">
                        ↵
                      </kbd>
                      <span>
                        {t('clash.kbd_open3d', {
                          defaultValue: '3D',
                        })}
                      </span>
                    </span>
                  </div>
                  )}

                  {/* Wave A2 — Faceted filter rail (advanced view). */}
                  {showFacets && (
                    <FacetRail
                      facets={facets}
                      fStatus={fStatus}
                      fSeverity={fSeverity}
                      fType={fType}
                      fDiscPair={fDiscPair}
                      fLevelPair={fLevelPair}
                      fModelPair={fModelPair}
                      onToggleStatus={(s) => toggleStatusFilter(s)}
                      onToggleSeverity={(s) => toggleSeverityFilter(s)}
                      onSetType={setFType}
                      onToggleDiscPair={(k) => toggleSetKey(setFDiscPair, k)}
                      onToggleLevelPair={(k) => toggleSetKey(setFLevelPair, k)}
                      onToggleModelPair={(k) => toggleSetKey(setFModelPair, k)}
                      onClear={clearAllFilters}
                      t={t}
                    />
                  )}

                  {/* Active-filter chips */}
                  {hasActiveFilters && (
                    <div className="mt-3 flex flex-wrap items-center gap-1.5">
                      {kpiFilter !== 'all' && (
                        <FilterChip
                          label={t(`clash.kpi_${kpiFilter}`, {
                            defaultValue: kpiFilter,
                          })}
                          onClear={() => setKpiFilter('all')}
                        />
                      )}
                      {fType !== 'all' && (
                        <FilterChip
                          label={t(`clash.type_${fType}`, {
                            defaultValue: fType,
                          })}
                          onClear={() => setFType('all')}
                        />
                      )}
                      {fPair && (
                        <FilterChip
                          label={fPair.replace('|', ' ↔ ')}
                          onClear={() => setFPair('')}
                        />
                      )}
                      {[...fStatus].map((s) => (
                        <FilterChip
                          key={s}
                          label={t(`clash.status.${s}`, {
                            defaultValue: s,
                          })}
                          onClear={() => toggleStatusFilter(s)}
                        />
                      ))}
                      {[...fSeverity].map((s) => (
                        <FilterChip
                          key={s}
                          label={t(`clash.severity.${s}`, {
                            defaultValue: s,
                          })}
                          onClear={() => toggleSeverityFilter(s)}
                        />
                      ))}
                      {fMinPen > 0 && (
                        <FilterChip
                          label={`≥ ${fMinPen} mm`}
                          onClear={() => setFMinPen(0)}
                        />
                      )}
                      {fSearch.trim() && (
                        <FilterChip
                          label={`"${fSearch.trim()}"`}
                          onClear={() => setFSearch('')}
                        />
                      )}
                      <button
                        onClick={clearAllFilters}
                        className="ml-1 text-2xs font-medium text-oe-blue hover:underline"
                      >
                        {t('clash.clear_all', {
                          defaultValue: 'Clear all',
                        })}
                      </button>
                    </div>
                  )}
                </div>

                {/* Table — honest three-state handling so a failed fetch
                    can NEVER read as "models are clean". Order matters:
                    error → loading/rows-arriving → genuinely-zero →
                    filtered-to-zero → table. */}
                {resultsQ.isError ? (
                  <EmptyState
                    icon={
                      <AlertTriangle className="h-10 w-10 text-semantic-error" />
                    }
                    title={t('clash.results_error', {
                      defaultValue: 'Failed to load clash results',
                    })}
                    description={
                      (resultsQ.error instanceof Error
                        ? resultsQ.error.message
                        : '') ||
                      t('clash.results_error_desc', {
                        defaultValue:
                          'The clash results could not be loaded. This does not mean the models are clean - please retry.',
                      })
                    }
                    action={
                      <Button
                        variant="secondary"
                        size="sm"
                        loading={resultsQ.isFetching}
                        onClick={() => resultsQ.refetch()}
                      >
                        {t('clash.retry', { defaultValue: 'Retry' })}
                      </Button>
                    }
                  />
                ) : resultsQ.isLoading ||
                  (kpis.total > 0 && allResults.length === 0) ? (
                  <TableSkeleton />
                ) : kpis.total === 0 ? (
                  <EmptyState
                    icon={<Radar className="h-10 w-10" />}
                    title={t('clash.no_clashes_title', {
                      defaultValue: 'No clashes detected',
                    })}
                    description={t('clash.no_clashes', {
                      defaultValue:
                        'No clashes - the models are clean.',
                    })}
                  />
                ) : sorted.length === 0 ? (
                  <EmptyState
                    icon={<Radar className="h-10 w-10" />}
                    title={t('clash.no_match_title', {
                      defaultValue: 'No clashes match the filters',
                    })}
                    description={t('clash.no_match_desc', {
                      defaultValue:
                        'Try widening or clearing the active filters.',
                    })}
                    action={
                      hasActiveFilters ? (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={clearAllFilters}
                        >
                          {t('clash.clear_all', {
                            defaultValue: 'Clear all',
                          })}
                        </Button>
                      ) : undefined
                    }
                  />
                ) : (
                  <div>
                    {/* Capped-rows notice: the run has more clashes than we
                        paged into the browser. KPIs above are still the
                        full authoritative totals. Lives ABOVE the scroll
                        container so it doesn't fight the sticky header. */}
                    {rowsCapped && (
                      <div className="flex items-center gap-2 border-b border-amber-200 bg-amber-50 px-3 py-2 text-2xs text-amber-800 dark:border-amber-900/40 dark:bg-amber-950/30 dark:text-amber-300">
                        <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                        <span>
                          {t('clash.capped_notice', {
                            defaultValue:
                              'Showing the first {{loaded}} of {{total}} clashes - refine the filters to narrow the review set.',
                            loaded: allResults.length,
                            total: loadedTotal,
                          })}
                        </span>
                      </div>
                    )}
                    <div className="max-h-[640px] overflow-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="sticky top-0 z-10 bg-surface-elevated">
                        <tr className="border-b border-border-light text-content-tertiary">
                          <th className="w-9 px-3 py-2.5">
                            <input
                              type="checkbox"
                              aria-label={t('clash.select_all', {
                                defaultValue: 'Select all on page',
                              })}
                              checked={allPageSelected}
                              ref={(el) => {
                                if (el)
                                  el.indeterminate =
                                    !allPageSelected && somePageSelected;
                              }}
                              onChange={togglePageSelectAll}
                            />
                          </th>
                          <SortableTh
                            label="#"
                            k="idx"
                            sortKey={sortKey}
                            sortDir={sortDir}
                            onSort={toggleSort}
                            className="w-12"
                          />
                          <SortableTh
                            label={t('clash.col_a', {
                              defaultValue: 'Element A',
                            })}
                            k="a_name"
                            sortKey={sortKey}
                            sortDir={sortDir}
                            onSort={toggleSort}
                          />
                          <SortableTh
                            label={t('clash.col_b', {
                              defaultValue: 'Element B',
                            })}
                            k="b_name"
                            sortKey={sortKey}
                            sortDir={sortDir}
                            onSort={toggleSort}
                          />
                          <SortableTh
                            label={t('clash.col_type', {
                              defaultValue: 'Type',
                            })}
                            k="clash_type"
                            sortKey={sortKey}
                            sortDir={sortDir}
                            onSort={toggleSort}
                          />
                          <SortableTh
                            label={t('clash.col_severity', {
                              defaultValue: 'Severity',
                            })}
                            k="severity"
                            sortKey={sortKey}
                            sortDir={sortDir}
                            onSort={toggleSort}
                          />
                          <SortableTh
                            label={t('clash.col_penetration', {
                              defaultValue: 'Penetration',
                            })}
                            k="penetration_m"
                            sortKey={sortKey}
                            sortDir={sortDir}
                            onSort={toggleSort}
                            align="right"
                          />
                          <SortableTh
                            label={t('clash.col_distance', {
                              defaultValue: 'Distance',
                            })}
                            k="distance_m"
                            sortKey={sortKey}
                            sortDir={sortDir}
                            onSort={toggleSort}
                            align="right"
                          />
                          <SortableTh
                            label={t('clash.col_status', {
                              defaultValue: 'Status',
                            })}
                            k="status"
                            sortKey={sortKey}
                            sortDir={sortDir}
                            onSort={toggleSort}
                          />
                          {/* Cost impact column — unique-to-AGPL-ERP move.
                              Owned by the backend ``clash_cost_impact``
                              module: surfaces the estimated rework cost
                              per clash so a coordinator can prioritise
                              by money, not just by geometry. */}
                          <th className="px-3 py-2.5 text-right">
                            {t('clash.col_cost_impact', {
                              defaultValue: 'Cost impact',
                            })}
                          </th>
                          <th className="px-3 py-2.5 text-right">
                            {t('clash.col_actions', {
                              defaultValue: 'Actions',
                            })}
                          </th>
                        </tr>
                      </thead>
                      {/* Wave A2 — windowed body. Chunks of 50 mount via
                          IntersectionObserver so very large pages stay
                          interactive. */}
                      <ChunkedBody chunkSize={WINDOW_CHUNK} items={pageItems}>
                        {(it: RenderItem) => {
                          if (it.kind === 'group') {
                            const collapsed = collapsedGroups.has(
                              it.key,
                            );
                            return (
                              <tr
                                key={`g-${it.key}`}
                                className="border-b border-border-light bg-surface-secondary/60"
                              >
                                <td colSpan={11} className="px-3 py-1.5">
                                  <button
                                    type="button"
                                    onClick={() => toggleGroup(it.key)}
                                    className="flex w-full items-center gap-2 text-left text-2xs font-semibold text-content-primary"
                                  >
                                    {collapsed ? (
                                      <ChevronRight className="h-3.5 w-3.5 text-content-tertiary" />
                                    ) : (
                                      <ChevronLeft className="h-3.5 w-3.5 rotate-[-90deg] text-content-tertiary" />
                                    )}
                                    <span className="truncate">
                                      {it.label || '—'}
                                    </span>
                                    <span className="rounded-full bg-surface-primary px-1.5 text-[10px] font-medium text-content-secondary">
                                      {it.count}
                                    </span>
                                  </button>
                                </td>
                              </tr>
                            );
                          }
                          if (it.kind === 'pair') {
                            // Pair-cluster master — applies status changes
                            // to every member (bulk mutate via statusMut).
                            const expanded = expandedPairs.has(it.key);
                            const head = it.head;
                            return (
                              <tr
                                key={`p-${it.key}`}
                                className="border-b border-border-light bg-oe-blue/[0.04]"
                              >
                                <td colSpan={11} className="px-3 py-2">
                                  <div className="flex flex-wrap items-center gap-2">
                                    <button
                                      type="button"
                                      onClick={() =>
                                        toggleSetKey(setExpandedPairs, it.key)
                                      }
                                      className="inline-flex items-center gap-1 text-left text-xs font-semibold text-content-primary"
                                      aria-expanded={expanded}
                                    >
                                      {expanded ? (
                                        <ChevronDown className="h-3.5 w-3.5 text-content-tertiary" />
                                      ) : (
                                        <ChevronRight className="h-3.5 w-3.5 text-content-tertiary" />
                                      )}
                                      <Link2 className="h-3.5 w-3.5 text-oe-blue" />
                                      <span className="truncate">
                                        {it.label}
                                      </span>
                                    </button>
                                    <Badge variant="blue" size="sm">
                                      {t('clash.pair_count', {
                                        defaultValue: '{{n}}× clashes',
                                        n: it.members.length,
                                      })}
                                    </Badge>
                                    <span className="ml-auto inline-flex items-center gap-1">
                                      <StatusWorkflow
                                        status={head.status}
                                        onChange={(s) => {
                                          for (const m of it.members) {
                                            statusMut.mutate({
                                              id: m.id,
                                              status: s,
                                            });
                                          }
                                        }}
                                        t={t}
                                      />
                                      <span className="text-2xs text-content-tertiary">
                                        {t('clash.pair_bulk_hint', {
                                          defaultValue:
                                            'applies to all members',
                                        })}
                                      </span>
                                    </span>
                                  </div>
                                </td>
                              </tr>
                            );
                          }
                          const r = it.row;
                          const selected = selResults.has(r.id);
                          // Index within the current page's data rows — for
                          // the keyboard cursor highlight (header markers
                          // are excluded from `pageRows`).
                          const kbIndex = pageRows.indexOf(r);
                          const kbActive = kbRow >= 0 && kbIndex === kbRow;
                          const sev = severityOf(r);
                          const cCount = r.comments?.length ?? 0;
                          const overdue = isOverdue(r.due_date);
                          return (
                            <tr
                              key={r.id}
                              className={clsx(
                                'border-b border-border-light/60 transition-colors',
                                kbActive &&
                                  'ring-2 ring-inset ring-oe-blue/60',
                                selected
                                  ? 'bg-oe-blue/5'
                                  : kbActive
                                    ? 'bg-oe-blue/5'
                                    : 'hover:bg-surface-secondary',
                              )}
                              onClick={() => {
                                if (kbIndex >= 0) setKbRow(kbIndex);
                              }}
                            >
                              <td className="px-3 py-2">
                                <input
                                  type="checkbox"
                                  aria-label={t('clash.select_row', {
                                    defaultValue: 'Select clash',
                                  })}
                                  checked={selected}
                                  onChange={(e) =>
                                    setSelResults((s) => {
                                      const n = new Set(s);
                                      if (e.target.checked) n.add(r.id);
                                      else n.delete(r.id);
                                      return n;
                                    })
                                  }
                                />
                              </td>
                              <td className="px-3 py-2 tabular-nums text-content-tertiary">
                                {(r.__idx ?? 0) + 1}
                              </td>
                              <td className="max-w-[220px] px-3 py-2">
                                <div className="truncate font-medium text-content-primary">
                                  {r.a_name || r.a_stable_id}
                                </div>
                                <div className="mt-0.5 flex items-center gap-1">
                                  <DisciplineChip
                                    name={r.a_discipline}
                                  />
                                  {r.a_element_type && (
                                    <span
                                      className="max-w-[130px] truncate text-2xs text-content-tertiary"
                                      title={r.a_element_type}
                                    >
                                      {r.a_element_type}
                                    </span>
                                  )}
                                </div>
                              </td>
                              <td className="max-w-[220px] px-3 py-2">
                                <div className="truncate font-medium text-content-primary">
                                  {r.b_name || r.b_stable_id}
                                </div>
                                <div className="mt-0.5 flex items-center gap-1">
                                  <DisciplineChip
                                    name={r.b_discipline}
                                  />
                                  {r.b_element_type && (
                                    <span
                                      className="max-w-[130px] truncate text-2xs text-content-tertiary"
                                      title={r.b_element_type}
                                    >
                                      {r.b_element_type}
                                    </span>
                                  )}
                                </div>
                              </td>
                              <td className="px-3 py-2">
                                <Badge
                                  size="sm"
                                  variant={
                                    r.clash_type === 'hard'
                                      ? 'error'
                                      : 'warning'
                                  }
                                >
                                  {r.clash_type === 'hard'
                                    ? t('clash.type_hard', {
                                        defaultValue: 'Hard',
                                      })
                                    : t('clash.type_clearance', {
                                        defaultValue: 'Clearance',
                                      })}
                                </Badge>
                              </td>
                              <td className="px-3 py-2">
                                <div className="flex flex-wrap items-center gap-1">
                                  <SeverityBadge severity={sev} t={t} />
                                  {(() => {
                                    const sug = suggestionOf(r);
                                    if (!sug) return null;
                                    return (
                                      <button
                                        type="button"
                                        onClick={() =>
                                          severityMut.mutate({
                                            id: r.id,
                                            severity: sug,
                                          })
                                        }
                                        title={t('clash.severity_suggested_hint', {
                                          defaultValue:
                                            'Engine-suggested severity from geometry. Click to accept.',
                                        })}
                                        className="inline-flex items-center gap-0.5 rounded-full border border-dashed border-oe-blue/60 px-1.5 py-0.5 text-[10px] font-medium text-oe-blue hover:bg-oe-blue/10"
                                      >
                                        <Sparkles className="h-2.5 w-2.5" />
                                        {t('clash.severity_suggested', {
                                          defaultValue:
                                            'Suggested: {{s}}',
                                          s: t(`clash.severity.${sug}`, {
                                            defaultValue: sug,
                                          }),
                                        })}
                                      </button>
                                    );
                                  })()}
                                </div>
                              </td>
                              <td className="px-3 py-2 text-right tabular-nums text-content-secondary">
                                {r.clash_type === 'hard'
                                  ? `${r.penetration_m.toFixed(3)} m`
                                  : '—'}
                              </td>
                              <td className="px-3 py-2 text-right tabular-nums text-content-secondary">
                                {r.clash_type === 'clearance'
                                  ? `${r.distance_m.toFixed(3)} m`
                                  : '—'}
                              </td>
                              <td className="px-3 py-2">
                                <StatusWorkflow
                                  status={r.status}
                                  onChange={(s) =>
                                    statusMut.mutate({
                                      id: r.id,
                                      status: s,
                                    })
                                  }
                                  t={t}
                                />
                                {/* Coordination state at a glance —
                                    assignee chip, comment count, due date
                                    (overdue = red). Click opens the detail
                                    panel for editing. */}
                                {(r.assigned_to ||
                                  cCount > 0 ||
                                  r.due_date) && (
                                  <button
                                    type="button"
                                    onClick={() => setDetailId(r.id)}
                                    title={t('clash.open_detail', {
                                      defaultValue:
                                        'Open clash details',
                                    })}
                                    className="mt-1 flex flex-wrap items-center gap-1"
                                  >
                                    {r.assigned_to && (
                                      <span className="inline-flex max-w-[120px] items-center gap-0.5 truncate rounded-full bg-surface-secondary px-1.5 py-0.5 text-[10px] font-medium text-content-secondary">
                                        <User className="h-2.5 w-2.5 shrink-0" />
                                        <span className="truncate">
                                          {r.assigned_to}
                                        </span>
                                      </span>
                                    )}
                                    {cCount > 0 && (
                                      <span className="inline-flex items-center gap-0.5 rounded-full bg-surface-secondary px-1.5 py-0.5 text-[10px] font-medium text-content-secondary">
                                        <MessageSquare className="h-2.5 w-2.5" />
                                        {cCount}
                                      </span>
                                    )}
                                    {r.due_date && (
                                      <span
                                        className={clsx(
                                          'inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-medium',
                                          overdue
                                            ? 'bg-semantic-error-bg text-semantic-error'
                                            : 'bg-surface-secondary text-content-secondary',
                                        )}
                                      >
                                        <CalendarClock className="h-2.5 w-2.5" />
                                        {r.due_date}
                                      </span>
                                    )}
                                  </button>
                                )}
                              </td>
                              {/* Cost impact cell — fetches the per-clash
                                  rework estimate from the
                                  ``clash_cost_impact`` backend module. */}
                              <ClashCostImpactColumn clashId={r.id} />
                              <td className="px-3 py-2">
                                <div className="flex items-center justify-end gap-1.5">
                                  {r.bcf_topic_guid && (
                                    <Badge variant="blue" size="sm">
                                      {t('clash.bcf', {
                                        defaultValue: 'BCF',
                                      })}
                                    </Badge>
                                  )}
                                  <button
                                    aria-label={t('clash.open_detail', {
                                      defaultValue:
                                        'Open clash details',
                                    })}
                                    title={t('clash.open_detail', {
                                      defaultValue:
                                        'Open clash details',
                                    })}
                                    onClick={() => setDetailId(r.id)}
                                    className="rounded-md p-1 text-content-tertiary hover:bg-surface-tertiary hover:text-content-primary"
                                  >
                                    <MessageSquare className="h-3.5 w-3.5" />
                                  </button>
                                  <button
                                    aria-label={t('clash.export_row', {
                                      defaultValue:
                                        'Export this clash to BCF',
                                    })}
                                    title={t('clash.export_row', {
                                      defaultValue:
                                        'Export this clash to BCF',
                                    })}
                                    onClick={() =>
                                      exportMut.mutate([r.id])
                                    }
                                    className="rounded-md p-1 text-content-tertiary hover:bg-surface-tertiary hover:text-content-primary"
                                  >
                                    <FileDown className="h-3.5 w-3.5" />
                                  </button>
                                  <Link
                                    to={bimLink(r)}
                                    title={t('clash.isolate_3d', {
                                      defaultValue: 'Isolate in 3D',
                                    })}
                                    className="inline-flex items-center gap-1 rounded-md bg-oe-blue/10 px-2 py-1 text-2xs font-medium text-oe-blue hover:bg-oe-blue/20"
                                  >
                                    <Box className="h-3.5 w-3.5" />
                                    {t('clash.isolate_3d_short', {
                                      defaultValue: '3D',
                                    })}
                                  </Link>
                                </div>
                              </td>
                            </tr>
                          );
                        }}
                      </ChunkedBody>
                    </table>
                    </div>
                  </div>
                )}

                {/* Wave A2 — Bulk-actions toolbar. Applies severity / status
                    / assignee changes to the whole selection in ONE batch
                    request (`bulkMut`) instead of one PATCH per row.
                    Severity gated by a confirm in the caller (the most
                    disruptive of the three). */}
                {selResults.size > 0 && sorted.length > 0 && (
                  <BulkActionsBar
                    count={selResults.size}
                    busy={bulkMut.isPending}
                    onSetSeverity={async (sv) => {
                      const ok = await confirm({
                        title: t('clash.bulk_severity_title', {
                          defaultValue: 'Update severity?',
                        }),
                        message: t('clash.bulk_severity_confirm', {
                          defaultValue:
                            'Set severity to "{{s}}" for {{n}} selected clash(es)?',
                          s: sv,
                          n: selResults.size,
                        }),
                        confirmLabel: t('common.apply', { defaultValue: 'Apply' }),
                        variant: 'warning',
                      });
                      if (!ok) return;
                      bulkMut.mutate({
                        ids: Array.from(selResults),
                        severity: sv,
                      });
                    }}
                    onSetStatus={(s) => {
                      bulkMut.mutate({
                        ids: Array.from(selResults),
                        status: s,
                      });
                    }}
                    onSetAssignee={(v) => {
                      const trimmed = v.trim();
                      bulkMut.mutate({
                        ids: Array.from(selResults),
                        assigned_to: trimmed || null,
                      });
                    }}
                    onClear={() => setSelResults(new Set())}
                    t={t}
                  />
                )}

                {/* Footer: selection summary + pagination */}
                {sorted.length > 0 && (
                  <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border-light p-3 text-xs">
                    <div className="text-content-tertiary">
                      {selResults.size > 0 ? (
                        <span className="flex items-center gap-2">
                          {t('clash.n_selected', {
                            defaultValue: '{{n}} selected',
                            n: selResults.size,
                          })}
                          <button
                            onClick={() => setSelResults(new Set())}
                            className="text-oe-blue hover:underline"
                          >
                            {t('clash.clear_selection', {
                              defaultValue: 'Clear',
                            })}
                          </button>
                        </span>
                      ) : (
                        t('clash.page_range', {
                          defaultValue:
                            '{{from}}–{{to}} of {{total}}',
                          from: safePage * PAGE_SIZE + 1,
                          to: Math.min(
                            (safePage + 1) * PAGE_SIZE,
                            renderItems.length,
                          ),
                          total: sorted.length,
                        })
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={safePage === 0}
                        icon={<ChevronLeft className="h-4 w-4" />}
                        onClick={() => setPage((p) => Math.max(0, p - 1))}
                      >
                        {t('clash.prev', { defaultValue: 'Prev' })}
                      </Button>
                      <span className="tabular-nums text-content-secondary">
                        {t('clash.page_of', {
                          defaultValue: 'Page {{p}} / {{n}}',
                          p: safePage + 1,
                          n: pageCount,
                        })}
                      </span>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={safePage >= pageCount - 1}
                        icon={<ChevronRight className="h-4 w-4" />}
                        iconPosition="right"
                        onClick={() =>
                          setPage((p) =>
                            Math.min(pageCount - 1, p + 1),
                          )
                        }
                      >
                        {t('clash.next', { defaultValue: 'Next' })}
                      </Button>
                    </div>
                  </div>
                )}
              </Card>
            </>
          )}
        </div>
      </div>

      {/* ── Per-clash collaboration panel ───────────────────────────────
            Right-hand slide-over: assignee, due date, comments thread.
            Keyboard-accessible (Esc to close, focusable controls). */}
      {detailRow && (
        <ClashDetailPanel
          row={detailRow}
          projectId={projectId}
          runId={runId}
          onClose={() => setDetailId(null)}
          onSaveAssignee={(v) =>
            detailMut.mutate({ id: detailRow.id, assigned_to: v })
          }
          onSaveDueDate={(v) =>
            detailMut.mutate({ id: detailRow.id, due_date: v })
          }
          onAddComment={(text, replyTo) =>
            detailMut.mutate({
              id: detailRow.id,
              add_comment: { text, reply_to: replyTo ?? null },
            })
          }
          saving={detailMut.isPending}
          bimLink={bimLink(detailRow)}
          t={t}
        />
      )}
      <ConfirmDialog {...confirmProps} />
    </div>
  );
}

/* ── Sub-components ───────────────────────────────────────────────────── */

/** A small discipline×discipline (or system×system) heat grid, reused by
 *  the grouping panel for every matrix-shaped dimension. */
function GroupMatrix({
  axes,
  cells,
}: {
  axes: string[];
  cells: ClashMatrixCell[];
}) {
  const { t } = useTranslation();
  const lookup = useMemo(() => {
    const m = new Map<string, ClashMatrixCell>();
    for (const c of cells) m.set(`${c.a}|${c.b}`, c);
    return m;
  }, [cells]);
  const maxCell = useMemo(
    () => Math.max(1, ...cells.map((c) => c.count)),
    [cells],
  );
  if (axes.length === 0) {
    return (
      <p className="text-sm text-content-tertiary">
        {t('clash.no_clashes', {
          defaultValue: 'No clashes - the models are clean.',
        })}
      </p>
    );
  }
  return (
    <div className="overflow-auto">
      <table className="border-collapse text-xs">
        <thead>
          <tr>
            <th className="p-2" />
            {axes.map((d) => (
              <th
                key={d}
                className="p-2 font-medium text-content-secondary"
              >
                {d}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {axes.map((row) => (
            <tr key={row}>
              <th className="p-2 text-right font-medium text-content-secondary">
                {row}
              </th>
              {axes.map((col) => {
                const [a, b] = row < col ? [row, col] : [col, row];
                const cell = lookup.get(`${a}|${b}`);
                const c = cell?.count ?? 0;
                return (
                  <td key={col} className="p-1">
                    <div
                      className={clsx(
                        'flex h-12 w-16 flex-col items-center justify-center rounded-md font-semibold',
                        heat(c, maxCell),
                      )}
                      title={`${a} ↔ ${b}: ${c}`}
                    >
                      <span>{c || '·'}</span>
                      {cell && cell.open_count > 0 && (
                        <span className="text-[10px] font-normal opacity-80">
                          {t('clash.matrix_open', {
                            defaultValue: '{{n}} open',
                            n: cell.open_count,
                          })}
                        </span>
                      )}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Item #23 — multi-dimensional grouping of a run's clashes. A selector
 *  switches the run summary between the discipline×discipline matrix
 *  (default), a per-level breakdown, a discipline matrix per level, and a
 *  discipline·system grid. Data is fetched on demand from the grouped
 *  summary endpoint and cached per (run, dimension). The discipline_system
 *  option is hidden until at least one clash carries system metadata. */
function ClashGroupingPanel({
  projectId,
  runId,
}: {
  projectId: string;
  runId: string;
}) {
  const { t } = useTranslation();
  const [dimension, setDimension] =
    useState<ClashGroupingDimension>('discipline_pair');

  const groupedQ = useQuery({
    queryKey: ['clash-grouped', projectId, runId, dimension],
    queryFn: () => clashApi.groupedSummary(projectId, runId, dimension),
    enabled: !!projectId && !!runId,
  });

  // Whether the run has system metadata — derived from any fetched payload
  // so we can hide the discipline_system option when there is no data. We
  // probe via the active payload (every dimension returns has_system_data).
  const data = groupedQ.data;
  const hasSystemData = data?.has_system_data ?? false;

  const DIMENSIONS: Array<{
    value: ClashGroupingDimension;
    label: string;
  }> = [
    {
      value: 'discipline_pair',
      label: t('clash.group_discipline_pair', {
        defaultValue: 'Discipline × Discipline',
      }),
    },
    {
      value: 'level',
      label: t('clash.group_level', { defaultValue: 'By level' }),
    },
    {
      value: 'level_discipline',
      label: t('clash.group_level_discipline', {
        defaultValue: 'Level × Discipline',
      }),
    },
    ...(hasSystemData || dimension === 'discipline_system'
      ? [
          {
            value: 'discipline_system' as ClashGroupingDimension,
            label: t('clash.group_discipline_system', {
              defaultValue: 'Discipline · System',
            }),
          },
        ]
      : []),
  ];

  return (
    <Card padding="md">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
          <Layers className="h-4 w-4 text-oe-blue" />
          {t('clash.grouping_title', {
            defaultValue: 'Group clashes by',
          })}
        </h2>
        <select
          value={dimension}
          onChange={(e) =>
            setDimension(e.target.value as ClashGroupingDimension)
          }
          className="rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
        >
          {DIMENSIONS.map((d) => (
            <option key={d.value} value={d.value}>
              {d.label}
            </option>
          ))}
        </select>
      </div>

      <div className="mt-3">
        {groupedQ.isLoading ? (
          <div className="flex items-center gap-2 py-4 text-sm text-content-tertiary">
            <Loader2 className="h-4 w-4 animate-spin" />
            {t('common.loading', { defaultValue: 'Loading…' })}
          </div>
        ) : !data ? (
          <p className="text-sm text-content-tertiary">
            {t('clash.no_clashes', {
              defaultValue: 'No clashes - the models are clean.',
            })}
          </p>
        ) : dimension === 'discipline_pair' ? (
          <GroupMatrix axes={data.disciplines} cells={data.matrix} />
        ) : dimension === 'discipline_system' ? (
          <GroupMatrix axes={data.systems} cells={data.system_matrix} />
        ) : dimension === 'level' ? (
          data.levels.length === 0 ? (
            <p className="text-sm text-content-tertiary">
              {t('clash.no_level_data', {
                defaultValue:
                  'No level data - the model has no resolved storeys.',
              })}
            </p>
          ) : (
            <div className="space-y-1.5">
              {data.levels.map((lvl) => (
                <div
                  key={lvl.key}
                  className="flex items-center justify-between gap-3 rounded-md border border-border-subtle px-3 py-2 text-sm"
                >
                  <span className="font-medium text-content-primary">
                    {lvl.key === '(no level)'
                      ? t('clash.no_level', { defaultValue: '(no level)' })
                      : t('clash.level_n', {
                          defaultValue: 'Level {{n}}',
                          n: lvl.key,
                        })}
                  </span>
                  <span className="flex items-center gap-3 text-content-secondary">
                    <span>
                      {t('clash.level_total', {
                        defaultValue: '{{n}} total',
                        n: lvl.count,
                      })}
                    </span>
                    {lvl.open_count > 0 && (
                      <Badge variant="warning" size="sm">
                        {t('clash.matrix_open', {
                          defaultValue: '{{n}} open',
                          n: lvl.open_count,
                        })}
                      </Badge>
                    )}
                  </span>
                </div>
              ))}
            </div>
          )
        ) : data.level_disciplines.length === 0 ? (
          <p className="text-sm text-content-tertiary">
            {t('clash.no_level_data', {
              defaultValue:
                'No level data - the model has no resolved storeys.',
            })}
          </p>
        ) : (
          <div className="space-y-4">
            {data.level_disciplines.map((grp) => {
              const axes = Array.from(
                new Set(grp.cells.flatMap((c) => [c.a, c.b])),
              ).sort();
              return (
                <div key={grp.level}>
                  <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                    {t('clash.level_n', {
                      defaultValue: 'Level {{n}}',
                      n: grp.level,
                    })}
                  </h3>
                  <GroupMatrix axes={axes} cells={grp.cells} />
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Card>
  );
}

function Header({
  actions,
  projectId,
  projectName,
}: {
  actions?: React.ReactNode;
  projectId?: string;
  projectName?: string | null;
}) {
  const { t } = useTranslation();
  // Canonical top block (MODULE_STYLE_GUIDE.md §2): Breadcrumb (project ->
  // module, hidden when it has no depth), the shared BetaBanner, then the
  // shared PageHeader - the same order /bim/federations and the EIR matrix
  // use, so the three coordination pages read identically. The module name +
  // icon live in the global top app bar, so the page renders only its
  // subtitle (srTitle for a11y) - never an in-page H1.
  return (
    <>
      <Breadcrumb
        items={[
          ...(projectId && projectName
            ? [{ label: projectName, to: `/projects/${projectId}` }]
            : []),
          { label: t('nav.clash_detection', { defaultValue: 'Clash Detection' }) },
        ]}
      />
      <BetaBanner moduleKey="clash" />
      <PageHeader
        srTitle={t('clash.title', { defaultValue: 'Clash Detection' })}
        subtitle={t('clash.subtitle', {
          defaultValue:
            'Geometric interference and clearance coordination across federated BIM models, with a clash matrix and BCF export.',
        })}
        actions={actions}
      />
    </>
  );
}

function Kpi({
  icon,
  label,
  value,
  active,
  onClick,
}: {
  icon: React.ReactNode;
  label: string;
  value: number | string;
  active?: boolean;
  onClick?: () => void;
}) {
  const interactive = !!onClick;
  return (
    <button
      type="button"
      disabled={!interactive}
      onClick={onClick}
      className={clsx(
        'rounded-xl border bg-surface-elevated/90 p-3 text-left shadow-xs transition-all',
        interactive && 'hover:-translate-y-0.5 hover:shadow-md',
        active
          ? 'border-oe-blue ring-2 ring-oe-blue/20'
          : 'border-border-light',
        !interactive && 'cursor-default',
      )}
    >
      <div className="flex items-center gap-1.5 text-content-tertiary">
        {icon}
        <span className="truncate text-2xs">{label}</span>
      </div>
      <div className="mt-1 text-2xl font-bold tabular-nums text-content-primary">
        {value}
      </div>
    </button>
  );
}

function SortableTh({
  label,
  k,
  sortKey,
  sortDir,
  onSort,
  align = 'left',
  className,
}: {
  label: string;
  k: SortKey;
  sortKey: SortKey;
  sortDir: SortDir;
  onSort: (k: SortKey) => void;
  align?: 'left' | 'right';
  className?: string;
}) {
  const isActive = sortKey === k;
  return (
    <th
      className={clsx(
        'select-none px-3 py-2.5 font-medium',
        align === 'right' ? 'text-right' : 'text-left',
        className,
      )}
    >
      <button
        onClick={() => onSort(k)}
        className={clsx(
          'inline-flex items-center gap-1 hover:text-content-primary',
          align === 'right' && 'flex-row-reverse',
          isActive ? 'text-content-primary' : 'text-content-tertiary',
        )}
      >
        {label}
        {isActive ? (
          sortDir === 'asc' ? (
            <ArrowUp className="h-3 w-3" />
          ) : (
            <ArrowDown className="h-3 w-3" />
          )
        ) : (
          <ArrowUpDown className="h-3 w-3 opacity-40" />
        )}
      </button>
    </th>
  );
}

function FilterChip({
  label,
  onClear,
}: {
  label: string;
  onClear: () => void;
}) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-oe-blue/10 py-0.5 pl-2 pr-1 text-2xs font-medium text-oe-blue">
      <span className="max-w-[160px] truncate">{label}</span>
      <button
        onClick={onClear}
        className="rounded-full p-0.5 hover:bg-oe-blue/20"
        aria-label="clear"
      >
        <X className="h-3 w-3" />
      </button>
    </span>
  );
}

function TableSkeleton() {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: 10 }).map((_, i) => (
        <div
          key={i}
          className="h-9 animate-pulse rounded-md bg-surface-secondary"
        />
      ))}
    </div>
  );
}

/**
 * Three-step status workflow control (Wave A2). Replaces the per-row
 * ``<select>``: one chip per stage of the linear ``new → active →
 * reviewed`` path (the 95% case), an arrow that advances to the next
 * stage, and a small dropdown for the terminal states
 * (approved / resolved / ignored). One-click "advance" is disabled at
 * the end of the flow — the user picks a terminal state explicitly.
 */
function StatusWorkflow({
  status,
  onChange,
  t,
}: {
  status: string;
  onChange: (s: string) => void;
  t: TFn;
}) {
  const idx = STATUS_FLOW.indexOf(status as StatusOpt);
  const inFlow = idx >= 0;
  const terminal = !inFlow;
  const next = nextStatusOf(status);
  return (
    <div className="flex items-center gap-1">
      {STATUS_FLOW.map((s, i) => {
        const isActive = inFlow && i === idx;
        const isPast = inFlow && i < idx;
        return (
          <button
            key={s}
            type="button"
            onClick={() => onChange(s)}
            title={t(`clash.status.${s}`, { defaultValue: s })}
            className={clsx(
              'h-6 rounded-full px-2 text-[10px] font-medium capitalize transition-colors',
              isActive &&
                'bg-oe-blue text-content-inverse shadow-sm',
              isPast &&
                'bg-oe-blue/15 text-oe-blue hover:bg-oe-blue/25',
              !isActive &&
                !isPast &&
                'bg-surface-secondary text-content-tertiary hover:bg-surface-tertiary',
            )}
          >
            {t(`clash.status.${s}`, { defaultValue: s })}
          </button>
        );
      })}
      <button
        type="button"
        disabled={!next}
        onClick={() => next && onChange(next)}
        title={
          next
            ? t('clash.status_advance', {
                defaultValue: 'Advance to {{s}}',
                s: t(`clash.status.${next}`, { defaultValue: next }),
              })
            : t('clash.status_terminal', {
                defaultValue: 'At terminal status - pick from menu',
              })
        }
        className={clsx(
          'inline-flex h-6 w-6 items-center justify-center rounded-full transition-colors',
          next
            ? 'bg-oe-blue/10 text-oe-blue hover:bg-oe-blue/20'
            : 'cursor-not-allowed bg-surface-secondary text-content-tertiary opacity-50',
        )}
      >
        <ArrowRightCircle className="h-3.5 w-3.5" />
      </button>
      <select
        value={terminal ? status : ''}
        onChange={(e) => {
          if (e.target.value) onChange(e.target.value);
        }}
        className={clsx(
          'h-6 rounded-md border border-border bg-surface-primary px-1 text-[10px] font-medium',
          terminal ? 'text-content-primary' : 'text-content-tertiary',
        )}
        title={t('clash.status_terminal_picker', {
          defaultValue: 'Pick a terminal status',
        })}
      >
        <option value="">
          {terminal
            ? t(`clash.status.${status}`, { defaultValue: status })
            : t('clash.status_more', { defaultValue: '…' })}
        </option>
        {STATUS_OPTIONS.filter(
          (s) => !STATUS_FLOW.includes(s) || (terminal && s !== status),
        ).map((s) => (
          <option key={s} value={s}>
            {t(`clash.status.${s}`, { defaultValue: s })}
          </option>
        ))}
      </select>
    </div>
  );
}

/**
 * Bulk-actions toolbar (Wave A2). Fans severity / status / assignee
 * mutations across the current selection. Pure controlled component —
 * the parent gates severity behind a confirm before calling
 * ``onSetSeverity`` (the destructive change of the three).
 */
function BulkActionsBar({
  count,
  busy,
  onSetSeverity,
  onSetStatus,
  onSetAssignee,
  onClear,
  t,
}: {
  count: number;
  busy: boolean;
  onSetSeverity: (s: ClashSeverity) => void;
  onSetStatus: (s: string) => void;
  onSetAssignee: (v: string) => void;
  onClear: () => void;
  t: TFn;
}) {
  const [assignee, setAssignee] = useState('');
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-oe-blue/30 bg-oe-blue/[0.05] p-3 text-xs">
      <span className="font-semibold text-oe-blue">
        {t('clash.bulk_selected', {
          defaultValue: '{{n}} selected - apply to all:',
          n: count,
        })}
      </span>
      <label className="flex items-center gap-1">
        <span className="text-content-tertiary">
          {t('clash.bulk_severity', { defaultValue: 'Severity' })}
        </span>
        <select
          disabled={busy}
          defaultValue=""
          onChange={(e) => {
            const v = e.target.value as ClashSeverity | '';
            if (v) onSetSeverity(v);
            e.target.value = '';
          }}
          className="h-7 rounded-md border border-border bg-surface-primary px-2 text-2xs"
        >
          <option value="">
            {t('clash.bulk_pick', { defaultValue: 'Pick…' })}
          </option>
          {SEVERITY_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {t(`clash.severity.${s}`, { defaultValue: s })}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-1">
        <span className="text-content-tertiary">
          {t('clash.bulk_status', { defaultValue: 'Status' })}
        </span>
        <select
          disabled={busy}
          defaultValue=""
          onChange={(e) => {
            const v = e.target.value;
            if (v) onSetStatus(v);
            e.target.value = '';
          }}
          className="h-7 rounded-md border border-border bg-surface-primary px-2 text-2xs"
        >
          <option value="">
            {t('clash.bulk_pick', { defaultValue: 'Pick…' })}
          </option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {t(`clash.status.${s}`, { defaultValue: s })}
            </option>
          ))}
        </select>
      </label>
      <label className="flex items-center gap-1">
        <span className="text-content-tertiary">
          {t('clash.bulk_assignee', { defaultValue: 'Assignee' })}
        </span>
        <input
          value={assignee}
          onChange={(e) => setAssignee(e.target.value)}
          placeholder={t('clash.bulk_assignee_ph', {
            defaultValue: 'name or e-mail',
          })}
          className="h-7 w-40 rounded-md border border-border bg-surface-primary px-2 text-2xs"
        />
        <Button
          size="sm"
          variant="secondary"
          disabled={busy}
          onClick={() => onSetAssignee(assignee)}
        >
          {t('clash.bulk_assign_apply', { defaultValue: 'Apply' })}
        </Button>
      </label>
      <button
        onClick={onClear}
        className="ml-auto text-2xs font-medium text-content-tertiary hover:text-content-primary"
      >
        {t('clash.clear_selection', { defaultValue: 'Clear' })}
      </button>
    </div>
  );
}

/**
 * Faceted filter rail (Wave A2). Multi-facet AND across categories, OR
 * within each category. Counts derive from the FULL row set so a narrow
 * active filter never makes other facets read as empty (standard
 * faceted-search contract).
 */
function FacetRail({
  facets,
  fStatus,
  fSeverity,
  fType,
  fDiscPair,
  fLevelPair,
  fModelPair,
  onToggleStatus,
  onToggleSeverity,
  onSetType,
  onToggleDiscPair,
  onToggleLevelPair,
  onToggleModelPair,
  onClear,
  t,
}: {
  facets: {
    disc: [string, number][];
    level: [string, number][];
    model: [string, number][];
    severity: [ClashSeverity, number][];
    status: [string, number][];
    type: [string, number][];
    modelPairLabel: (key: string) => string;
  };
  fStatus: Set<string>;
  fSeverity: Set<ClashSeverity>;
  fType: 'all' | 'hard' | 'clearance';
  fDiscPair: Set<string>;
  fLevelPair: Set<string>;
  fModelPair: Set<string>;
  onToggleStatus: (s: string) => void;
  onToggleSeverity: (s: ClashSeverity) => void;
  onSetType: (v: 'all' | 'hard' | 'clearance') => void;
  onToggleDiscPair: (k: string) => void;
  onToggleLevelPair: (k: string) => void;
  onToggleModelPair: (k: string) => void;
  onClear: () => void;
  t: TFn;
}) {
  return (
    <div className="mt-3 grid gap-3 rounded-lg border border-border-light bg-surface-elevated p-3 md:grid-cols-2 lg:grid-cols-3">
      <FacetGroup
        title={t('clash.facet_status', { defaultValue: 'Status' })}
        rows={facets.status.map(([k, c]) => ({
          key: k,
          label: t(`clash.status.${k}`, { defaultValue: k }),
          count: c,
          on: fStatus.has(k),
          onToggle: () => onToggleStatus(k),
        }))}
      />
      <FacetGroup
        title={t('clash.facet_severity', { defaultValue: 'Severity' })}
        rows={facets.severity.map(([k, c]) => ({
          key: k,
          label: t(`clash.severity.${k}`, { defaultValue: k }),
          count: c,
          on: fSeverity.has(k),
          onToggle: () => onToggleSeverity(k),
        }))}
      />
      <FacetGroup
        title={t('clash.facet_type', { defaultValue: 'Clash type' })}
        rows={facets.type.map(([k, c]) => ({
          key: k,
          label: t(`clash.type_${k}`, { defaultValue: k }),
          count: c,
          on: fType === k,
          onToggle: () =>
            onSetType(
              (fType === k ? 'all' : (k as 'hard' | 'clearance')) as
                | 'all'
                | 'hard'
                | 'clearance',
            ),
        }))}
      />
      <FacetGroup
        title={t('clash.facet_disc_pair', {
          defaultValue: 'Discipline pair',
        })}
        rows={facets.disc.map(([k, c]) => ({
          key: k,
          label: k.replace('|', ' ↔ '),
          count: c,
          on: fDiscPair.has(k),
          onToggle: () => onToggleDiscPair(k),
        }))}
      />
      <FacetGroup
        title={t('clash.facet_level_pair', {
          defaultValue: 'Level pair',
        })}
        rows={facets.level.map(([k, c]) => ({
          key: k,
          label: k.replace('|', ' ↔ '),
          count: c,
          on: fLevelPair.has(k),
          onToggle: () => onToggleLevelPair(k),
        }))}
      />
      <FacetGroup
        title={t('clash.facet_model_pair', {
          defaultValue: 'Model pair',
        })}
        rows={facets.model.map(([k, c]) => ({
          key: k,
          label: facets.modelPairLabel(k),
          count: c,
          on: fModelPair.has(k),
          onToggle: () => onToggleModelPair(k),
        }))}
      />
      <div className="md:col-span-2 lg:col-span-3">
        <button
          onClick={onClear}
          className="text-2xs font-medium text-oe-blue hover:underline"
        >
          {t('clash.clear_all', { defaultValue: 'Clear all' })}
        </button>
      </div>
    </div>
  );
}

function FacetGroup({
  title,
  rows,
}: {
  title: string;
  rows: {
    key: string;
    label: string;
    count: number;
    on: boolean;
    onToggle: () => void;
  }[];
}) {
  if (rows.length === 0) return null;
  return (
    <div>
      <div className="mb-1.5 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
        {title}
      </div>
      <div className="max-h-40 space-y-0.5 overflow-y-auto pr-1">
        {rows.map((r) => (
          <button
            key={r.key}
            type="button"
            onClick={r.onToggle}
            className={clsx(
              'flex w-full items-center justify-between gap-2 rounded-md px-2 py-1 text-left text-2xs transition-colors',
              r.on
                ? 'bg-oe-blue/10 text-oe-blue ring-1 ring-oe-blue/30'
                : 'hover:bg-surface-secondary text-content-secondary',
            )}
          >
            <span className="min-w-0 flex-1 truncate" title={r.label}>
              {r.label || '—'}
            </span>
            <span
              className={clsx(
                'shrink-0 rounded-full px-1.5 text-[10px] font-medium tabular-nums',
                r.on
                  ? 'bg-oe-blue/20 text-oe-blue'
                  : 'bg-surface-secondary text-content-tertiary',
              )}
            >
              {r.count}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * IntersectionObserver-windowed tbody (Wave A2). Renders rows in chunks
 * of N; off-screen chunks mount a height-preserving placeholder so the
 * scrollbar geometry stays correct.
 */
function ChunkedBody({
  items,
  chunkSize,
  children,
}: {
  items: RenderItem[];
  chunkSize: number;
  children: (it: RenderItem) => React.ReactNode;
}) {
  const chunks = useMemo(() => {
    const out: RenderItem[][] = [];
    for (let i = 0; i < items.length; i += chunkSize) {
      out.push(items.slice(i, i + chunkSize));
    }
    return out;
  }, [items, chunkSize]);
  return (
    <tbody>
      {chunks.map((chunk, i) => (
        <ChunkRow key={i} chunk={chunk} index={i} renderItem={children} />
      ))}
    </tbody>
  );
}

function ChunkRow({
  chunk,
  index,
  renderItem,
}: {
  chunk: RenderItem[];
  index: number;
  renderItem: (it: RenderItem) => React.ReactNode;
}) {
  // Keep the first two chunks always-mounted so the initial paint never
  // shows a placeholder gap at the top.
  const [visible, setVisible] = useState(index < 2);
  const sentinelRef = useRef<HTMLTableRowElement | null>(null);
  useEffect(() => {
    if (visible) return;
    const el = sentinelRef.current;
    if (!el || typeof IntersectionObserver === 'undefined') {
      setVisible(true);
      return;
    }
    // 600 px lookahead so we mount before the chunk enters the viewport.
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true);
          obs.disconnect();
        }
      },
      { rootMargin: '600px 0px 600px 0px' },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [visible]);
  if (!visible) {
    return (
      <tr
        ref={sentinelRef}
        style={{ height: chunk.length * 36 }}
        aria-hidden
      >
        <td colSpan={11} />
      </tr>
    );
  }
  // ``children`` can be a multi-row group (no Fragment wrapper) — fine
  // because tbody accepts adjacent <tr> nodes natively.
  return <>{chunk.map((it) => renderItem(it))}</>;
}

/**
 * One side (A or B) of a Navisworks-style selection-set clash.
 *
 * A "set" is the union of the ticked disciplines + element types — every
 * chip widens it. Searchable, count-annotated, scroll-bounded so a model
 * with hundreds of distinct Revit types stays usable. Pure controlled
 * component: it owns no state beyond the local search box.
 */
function SelectionSetPicker({
  label,
  accent,
  value,
  onChange,
  categories,
  groupBy,
  loading,
}: {
  label: string;
  accent: 'oe-blue' | 'amber';
  value: ClashSelectionSet;
  onChange: (next: ClashSelectionSet) => void;
  categories: ClashCategories | undefined;
  groupBy: ClashGroupBy;
  loading: boolean;
}) {
  const { t } = useTranslation();
  const [q, setQ] = useState('');
  // A set can carry chips from multiple grouping params (Navisworks-style
  // union); the badge reflects every chip — built-in lists plus every
  // `property:<key>` map — and the list shows the active one.
  const selectedCount =
    value.disciplines.length +
    value.element_types.length +
    value.categories.length +
    value.ifc_entities.length +
    Object.values(value.properties ?? {}).reduce(
      (n, v) => n + v.length,
      0,
    );
  const dot = accent === 'oe-blue' ? 'bg-oe-blue' : 'bg-amber-500';
  const ql = q.trim().toLowerCase();

  // The chips this grouping reads/writes. The four built-ins route into
  // their dedicated list field (`GROUP_BY_FIELD`); the dynamic
  // `property:<key>` form routes into `properties[key]` instead, mirroring
  // the backend's union-of-everything set-membership contract.
  const propKey = isPropertyGroupBy(groupBy)
    ? propertyKeyOf(groupBy)
    : null;
  const chosen: string[] =
    propKey !== null
      ? (value.properties?.[propKey] ?? [])
      : value[GROUP_BY_FIELD[groupBy as BuiltinGroupBy]];
  const groups = (categories?.groups ?? []).filter(
    (g) => !ql || g.value.toLowerCase().includes(ql),
  );

  function toggle(v: string) {
    const cur = chosen;
    const next = cur.includes(v)
      ? cur.filter((x) => x !== v)
      : [...cur, v];
    if (propKey !== null) {
      onChange({
        ...value,
        properties: { ...(value.properties ?? {}), [propKey]: next },
      });
    } else {
      const field = GROUP_BY_FIELD[groupBy as BuiltinGroupBy];
      onChange({ ...value, [field]: next });
    }
  }

  return (
    <div className="rounded-lg border border-border bg-surface-primary p-2">
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5 text-xs font-semibold text-content-primary">
          <span className={clsx('h-2 w-2 rounded-full', dot)} />
          {label}
          {selectedCount > 0 && (
            <span className="rounded-full bg-surface-secondary px-1.5 text-2xs text-content-secondary">
              {selectedCount}
            </span>
          )}
        </span>
        {selectedCount > 0 && (
          <button
            type="button"
            onClick={() => onChange({ ...EMPTY_SET })}
            className="text-2xs text-content-tertiary hover:text-semantic-error"
          >
            {t('common.clear', { defaultValue: 'Clear' })}
          </button>
        )}
      </div>

      <div className="relative mt-1.5">
        <Search className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-content-tertiary" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t('clash.set_search', {
            defaultValue: 'Search…',
          })}
          className="w-full rounded-md border border-border bg-surface-primary py-1 pl-7 pr-2 text-2xs"
        />
      </div>

      <div className="mt-1.5 max-h-44 space-y-2 overflow-y-auto pr-0.5">
        {loading && (
          <p className="px-1 py-2 text-2xs text-content-tertiary">
            {t('common.loading', { defaultValue: 'Loading…' })}
          </p>
        )}
        {!loading && groups.length === 0 && (
          <p className="px-1 py-2 text-2xs text-content-tertiary">
            {t('clash.set_empty', {
              defaultValue: 'No elements - select a parsed model first.',
            })}
          </p>
        )}
        {groups.length > 0 && (
          <div>
            <p className="px-1 pb-0.5 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
              {groupByLabel(groupBy, t)}
            </p>
            {groups.map((g) => (
              <SetRow
                key={`g-${g.value}`}
                checked={chosen.includes(g.value)}
                label={g.value}
                count={g.count}
                onToggle={() => toggle(g.value)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function SetRow({
  checked,
  label,
  count,
  onToggle,
}: {
  checked: boolean;
  label: string;
  count: number;
  onToggle: () => void;
}) {
  return (
    <label
      className={clsx(
        'flex cursor-pointer items-center gap-1.5 rounded px-1 py-0.5 text-2xs',
        checked
          ? 'bg-oe-blue/10 text-content-primary'
          : 'hover:bg-surface-secondary text-content-secondary',
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        className="h-3 w-3 shrink-0 accent-oe-blue"
      />
      <span className="flex-1 truncate" title={label}>
        {label}
      </span>
      <span className="shrink-0 text-content-tertiary">{count}</span>
    </label>
  );
}

/** Status → badge variant for a CAD-BIM model card. */
function modelStatusVariant(
  status: string | null,
): 'success' | 'warning' | 'error' | 'neutral' {
  const s = (status ?? '').toLowerCase();
  if (s === 'ready' || s === 'completed') return 'success';
  if (s === 'processing' || s === 'pending' || s === 'queued')
    return 'warning';
  if (s === 'failed' || s === 'error') return 'error';
  return 'neutral';
}

/**
 * Selectable CAD-BIM model cards — the project's model surface and the
 * clash scope picker in one. Clicking a card toggles that model into the
 * clash set (`selModels`). Replaces the old project-description panel and
 * the collapsed "models in scope" disclosure. A model with no parsed
 * geometry can't clash, so it is shown disabled.
 */
function ModelCardPicker({
  models,
  loading,
  selected,
  projectName,
  compact,
  onToggle,
  onSelectAll,
  onClear,
}: {
  models: { id: string; name: string; element_count: number; status: string | null }[] | undefined;
  loading: boolean;
  selected: string[];
  projectName?: string | null;
  compact: boolean;
  onToggle: (id: string) => void;
  onSelectAll: () => void;
  onClear: () => void;
}) {
  const { t } = useTranslation();
  const list = models ?? [];
  const selectable = list.filter((m) => m.element_count > 0);

  return (
    <Card padding="md" className="mt-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
          <Boxes className="h-4 w-4 text-oe-blue" />
          {t('clash.models_title', {
            defaultValue: 'CAD-BIM models - pick what to coordinate',
          })}
          {selectable.length > 0 && (
            <span className="rounded-full bg-surface-secondary px-1.5 text-2xs font-medium text-content-secondary">
              {t('clash.models_selected', {
                defaultValue: '{{n}} of {{total}} selected',
                n: selected.length,
                total: selectable.length,
              })}
            </span>
          )}
        </h2>
        {selectable.length > 0 && (
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={onSelectAll}
              className="rounded-md px-2 py-1 text-2xs font-medium text-content-secondary hover:bg-surface-secondary"
            >
              {t('clash.select_all', { defaultValue: 'Select all' })}
            </button>
            <button
              type="button"
              onClick={onClear}
              className="rounded-md px-2 py-1 text-2xs font-medium text-content-secondary hover:bg-surface-secondary"
            >
              {t('common.clear', { defaultValue: 'Clear' })}
            </button>
          </div>
        )}
      </div>

      {loading && (
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-24 animate-pulse rounded-xl bg-surface-secondary"
            />
          ))}
        </div>
      )}

      {!loading && list.length === 0 && (
        <div className="mt-3">
          <EmptyState
            icon={<Upload className="h-9 w-9" />}
            title={t('clash.no_models', {
              defaultValue: 'No parsed BIM models in this project.',
            })}
            description={t('clash.no_models_desc', {
              defaultValue:
                'Upload and parse a BIM model to run clash detection on it.',
            })}
            action={
              <Link to="/bim">
                <Button
                  variant="primary"
                  size="sm"
                  icon={<Upload className="h-4 w-4" />}
                >
                  {t('clash.upload_model', {
                    defaultValue: 'Upload a BIM model',
                  })}
                </Button>
              </Link>
            }
          />
        </div>
      )}

      {!loading && list.length > 0 && (
        <div
          className={clsx(
            'mt-3 grid gap-3',
            compact
              ? 'grid-cols-1 sm:grid-cols-2'
              : 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4',
          )}
        >
          {list.map((m) => {
            const disabled = m.element_count <= 0;
            const isSel = selected.includes(m.id);
            return (
              <button
                key={m.id}
                type="button"
                disabled={disabled}
                aria-pressed={isSel}
                onClick={() => !disabled && onToggle(m.id)}
                className={clsx(
                  'group relative flex flex-col gap-2 rounded-xl border p-3 text-left transition-all',
                  disabled
                    ? 'cursor-not-allowed border-border-light bg-surface-secondary/40 opacity-60'
                    : isSel
                      ? 'border-oe-blue bg-oe-blue/5 ring-2 ring-oe-blue/20 hover:shadow-md'
                      : 'border-border-light bg-surface-elevated hover:-translate-y-0.5 hover:shadow-md',
                )}
              >
                <div className="flex items-start justify-between gap-2">
                  <span
                    className={clsx(
                      'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
                      isSel
                        ? 'bg-oe-blue text-content-inverse'
                        : 'bg-surface-secondary text-content-tertiary',
                    )}
                  >
                    <Box className="h-4 w-4" />
                  </span>
                  <span
                    className={clsx(
                      'flex h-5 w-5 shrink-0 items-center justify-center rounded-full border',
                      isSel
                        ? 'border-oe-blue bg-oe-blue text-content-inverse'
                        : 'border-border bg-surface-primary text-transparent',
                    )}
                    aria-hidden
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  </span>
                </div>
                <div className="min-w-0">
                  <p
                    className="truncate text-xs font-semibold text-content-primary"
                    title={m.name}
                  >
                    {shortModelName(m.name, projectName)}
                  </p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    <Badge
                      variant={modelStatusVariant(m.status)}
                      size="sm"
                    >
                      {m.status ??
                        t('clash.status_unknown', {
                          defaultValue: 'unknown',
                        })}
                    </Badge>
                    <span className="inline-flex items-center gap-1 text-2xs text-content-tertiary">
                      <Layers className="h-3 w-3" />
                      {m.element_count.toLocaleString()}{' '}
                      {t('clash.ctx_elements', {
                        defaultValue: 'elements',
                      })}
                    </span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </Card>
  );
}

/**
 * Per-clash collaboration slide-over. A right-hand panel (not a modal) so
 * the reviewer keeps the results table visible while triaging. Holds the
 * assignee editor (free-text — no user-picker dependency), a native
 * due-date input, a tabbed "Comments / Activity" pane and the watchers
 * chip. Keyboard-accessible: Esc closes, every control is natively
 * focusable, the backdrop is click-to-close.
 */
function ClashDetailPanel({
  row,
  projectId,
  runId,
  onClose,
  onSaveAssignee,
  onSaveDueDate,
  onAddComment,
  saving,
  bimLink,
  t,
}: {
  row: ClashResult;
  projectId: string;
  runId: string;
  onClose: () => void;
  onSaveAssignee: (v: string | null) => void;
  onSaveDueDate: (v: string | null) => void;
  onAddComment: (text: string, replyTo: string | null) => void;
  saving: boolean;
  bimLink: string;
  t: TFn;
}) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const userEmail = useAuthStore((s) => s.userEmail);
  const [assignee, setAssignee] = useState(row.assigned_to ?? '');
  const [due, setDue] = useState(row.due_date ?? '');
  const [draft, setDraft] = useState('');
  const [tab, setTab] = useState<'comments' | 'activity'>('comments');
  const onCollabTabKeyDown = useTabKeyboardNav<'comments' | 'activity'>({
    ids: ['comments', 'activity'] as const,
    activeId: tab,
    onChange: setTab,
    orientation: 'horizontal',
  });
  const [replyTo, setReplyTo] = useState<string | null>(null);
  // @mention autocomplete state. ``mentionOpen`` is the cursor-relative
  // dropdown anchor; ``mentionQuery`` is the substring after the last
  // unmatched ``@`` token used to filter the project-members list.
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionQuery, setMentionQuery] = useState('');
  // Pre-existing GLB load state — mirrors the BOQ grid `glbOk` pattern:
  // flips false on a load error so we swap the canvas for a hint.
  const [glbOk, setGlbOk] = useState(true);
  const draftRef = useRef<HTMLTextAreaElement | null>(null);

  // Fetch project members for @mention autocomplete + author resolution.
  // Falls back to an empty list when the caller isn't a project owner /
  // admin (the endpoint 403s for plain viewers, which is the policy).
  const membersQ = useQuery({
    queryKey: ['clash-project-members', projectId],
    queryFn: () => clashApi.projectMembers(projectId),
    enabled: !!projectId,
    staleTime: 60_000,
  });
  const members = membersQ.data ?? [];

  // Resolve the caller's own ``user_id`` from the members list by email
  // (the JWT in the auth store carries an email, not a UUID). Lets the
  // watchers chip / mention chip render the caller's display name.
  const currentUserId = useMemo(() => {
    if (!userEmail) return null;
    const m = members.find(
      (mm) => mm.email?.toLowerCase() === userEmail.toLowerCase(),
    );
    return m?.user_id ?? null;
  }, [members, userEmail]);

  function getUserName(id: string): string {
    const m = members.find((mm) => mm.user_id === id);
    if (!m) return id;
    return (m.full_name && m.full_name.trim()) || m.email || id;
  }

  // Watch / unwatch — optimistic; the server returns the authoritative
  // watcher list which the cache merge picks up on settle.
  const watchMut = useMutation({
    mutationFn: (watching: boolean) =>
      watching
        ? clashApi.watch(projectId, runId, row.id)
        : clashApi.unwatch(projectId, runId, row.id),
    onSuccess: (resp) => {
      qc.setQueryData<{ items: ClashResult[] }>(
        ['clash-results', projectId, runId],
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((r) =>
                  r.id === row.id
                    ? { ...r, watchers: resp.watchers }
                    : r,
                ),
              }
            : old,
      );
    },
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('clash.watch_failed', {
          defaultValue: 'Could not update watch state',
        }),
        message: e.message,
      }),
  });

  // Keep the local editors in sync if the underlying row updates (e.g. the
  // optimistic cache swap after a save).
  useEffect(() => {
    setAssignee(row.assigned_to ?? '');
    setDue(row.due_date ?? '');
  }, [row.assigned_to, row.due_date]);

  // The clash element pair to isolate in the preview. The link helper
  // builds the deep-link off `a_model_id`, so prefer that model; element
  // ids are nullable on older payloads, so filter blanks.
  const previewModelId = row.a_model_id || row.b_model_id;
  const previewElementIds = useMemo(
    () => [row.a_element_id, row.b_element_id].filter(Boolean),
    [row.a_element_id, row.b_element_id],
  );
  const canPreview =
    !!previewModelId && previewElementIds.length > 0;

  // A different clash may have a working model — reset the error flag so
  // the preview retries when the panel is reused for another row.
  useEffect(() => {
    setGlbOk(true);
  }, [previewModelId, previewElementIds]);

  // Esc closes the panel.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const comments = row.comments ?? [];
  const history = row.history ?? [];
  const watchers = row.watchers ?? [];
  const isWatching = !!currentUserId && watchers.includes(currentUserId);
  const assigneeDirty = (row.assigned_to ?? '') !== assignee.trim();
  const dueDirty = (row.due_date ?? '') !== due;

  // Build the threaded comment tree: top-level comments (no reply_to or
  // dangling reply_to) plus children keyed by parent ts. A dangling
  // reply (parent no longer present) gracefully degrades to top-level
  // rather than disappearing.
  const tsSet = new Set(comments.map((c) => c.ts));
  const topLevel: ClashComment[] = [];
  const childrenByParent = new Map<string, ClashComment[]>();
  for (const c of comments) {
    if (c.reply_to && tsSet.has(c.reply_to)) {
      const arr = childrenByParent.get(c.reply_to) ?? [];
      arr.push(c);
      childrenByParent.set(c.reply_to, arr);
    } else {
      topLevel.push(c);
    }
  }

  // Activity entries — reverse-chronological so the latest event is on
  // top. Mutates a copy (never the cached array). Falls back to an
  // empty list when the backend is older / never wrote one.
  const activity: ClashHistoryEntry[] = [...history].sort((a, b) =>
    b.ts.localeCompare(a.ts),
  );

  // Mention-autocomplete candidates — case-insensitive substring match
  // against email + full_name, capped at the visual budget.
  const mentionCandidates = useMemo(() => {
    const q = mentionQuery.trim().toLowerCase();
    const base = members.filter((m) => !!m.user_id);
    if (!q) return base.slice(0, 8);
    return base
      .filter((m) => {
        const name = (m.full_name || '').toLowerCase();
        const email = (m.email || '').toLowerCase();
        return name.includes(q) || email.includes(q);
      })
      .slice(0, 8);
  }, [members, mentionQuery]);

  function handleDraftChange(value: string) {
    setDraft(value);
    // Track the unmatched ``@`` at-or-before the caret; if there is one
    // (and no whitespace between it and the caret) → open the popover.
    const ta = draftRef.current;
    const caret = ta ? ta.selectionStart ?? value.length : value.length;
    const before = value.slice(0, caret);
    const at = before.lastIndexOf('@');
    if (at < 0) {
      setMentionOpen(false);
      return;
    }
    const tail = before.slice(at + 1);
    if (/\s/.test(tail)) {
      setMentionOpen(false);
      return;
    }
    setMentionQuery(tail);
    setMentionOpen(true);
  }

  function insertMention(uid: string) {
    const ta = draftRef.current;
    if (!ta) return;
    const caret = ta.selectionStart ?? draft.length;
    const before = draft.slice(0, caret);
    const at = before.lastIndexOf('@');
    if (at < 0) return;
    const tag = `<at>${uid}</at>`;
    const next = draft.slice(0, at) + tag + ' ' + draft.slice(caret);
    setDraft(next);
    setMentionOpen(false);
    // Restore caret position one space after the inserted mention tag.
    setTimeout(() => {
      if (!draftRef.current) return;
      const pos = at + tag.length + 1;
      draftRef.current.focus();
      draftRef.current.setSelectionRange(pos, pos);
    }, 0);
  }

  function submitDraft() {
    const text = draft.trim();
    if (!text) return;
    onAddComment(text, replyTo);
    setDraft('');
    setReplyTo(null);
    setMentionOpen(false);
  }

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-label={t('clash.detail_title', {
        defaultValue: 'Clash details',
      })}
    >
      <button
        type="button"
        aria-label={t('common.close', { defaultValue: 'Close' })}
        onClick={onClose}
        className="absolute inset-0 bg-black/30 backdrop-blur-[1px]"
      />
      <div className="relative flex h-full w-full max-w-md flex-col overflow-y-auto border-l border-border bg-surface-elevated shadow-2xl animate-slide-in-right">
        <div className="flex items-start justify-between gap-3 border-b border-border-light p-4">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
              <MessageSquare className="h-4 w-4 text-oe-blue" />
              {t('clash.detail_title', {
                defaultValue: 'Clash details',
              })}
            </h2>
            <p className="mt-1 truncate text-2xs text-content-tertiary">
              {(row.a_name || row.a_stable_id) +
                ' ↔ ' +
                (row.b_name || row.b_stable_id)}
            </p>
          </div>
          <button
            type="button"
            aria-label={t('common.close', { defaultValue: 'Close' })}
            onClick={onClose}
            className="rounded-md p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-5 p-4">
          {/* Quick 3D preview of the two clashing elements + a prominent
              jump into the full BIM viewer. Mirrors the BOQ grid
              MiniGeometryPreview usage (load GLB, isolate the ids,
              auto-rotate); degrades to a hint when the model/element ids
              are missing or the GLB fails to load. */}
          <div>
            <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-content-secondary">
              <Box className="h-3.5 w-3.5" />
              {t('clash.quick_preview', {
                defaultValue: 'Quick 3D preview',
              })}
            </h3>
            {canPreview && glbOk ? (
              <MiniGeometryPreview
                modelId={previewModelId}
                elementIds={previewElementIds}
                width={416}
                height={220}
                className="w-full border border-border-light bg-surface-secondary"
                onError={() => setGlbOk(false)}
              />
            ) : (
              <div className="flex h-[220px] w-full flex-col items-center justify-center gap-1.5 rounded-md border border-dashed border-border-light bg-surface-secondary/40 px-4 text-center">
                <Box className="h-6 w-6 text-content-tertiary" />
                <p className="text-2xs text-content-tertiary">
                  {t('clash.preview_unavailable', {
                    defaultValue:
                      'Preview unavailable - open the full viewer.',
                  })}
                </p>
              </div>
            )}
            <Button
              variant="primary"
              size="sm"
              className="mt-2 w-full"
              icon={<Box className="h-4 w-4" />}
              onClick={() => navigate(bimLink)}
            >
              {t('clash.open_full_viewer', {
                defaultValue: 'Open in full 3D viewer',
              })}
            </Button>
          </div>

          {/* Assignee — free text (no user-picker dependency). */}
          <div>
            <label className="flex items-center gap-1.5 text-xs font-medium text-content-secondary">
              <User className="h-3.5 w-3.5" />
              {t('clash.assignee', { defaultValue: 'Assignee' })}
            </label>
            <div className="mt-1 flex items-center gap-2">
              <input
                type="text"
                value={assignee}
                maxLength={255}
                placeholder={t('clash.assignee_ph', {
                  defaultValue: 'e.g. MEP coordinator',
                })}
                onChange={(e) => setAssignee(e.target.value)}
                className="h-8 min-w-0 flex-1 rounded-md border border-border bg-surface-primary px-2 text-sm"
              />
              <Button
                variant="secondary"
                size="sm"
                disabled={saving || !assigneeDirty}
                onClick={() =>
                  onSaveAssignee(assignee.trim() || null)
                }
              >
                {t('common.save', { defaultValue: 'Save' })}
              </Button>
            </div>
          </div>

          {/* Due date — native date input. */}
          <div>
            <label className="flex items-center gap-1.5 text-xs font-medium text-content-secondary">
              <CalendarClock className="h-3.5 w-3.5" />
              {t('clash.due_date', { defaultValue: 'Due date' })}
            </label>
            <div className="mt-1 flex items-center gap-2">
              <input
                type="date"
                value={due}
                onChange={(e) => setDue(e.target.value)}
                className="h-8 min-w-0 flex-1 rounded-md border border-border bg-surface-primary px-2 text-sm"
              />
              <Button
                variant="secondary"
                size="sm"
                disabled={saving || !dueDirty}
                onClick={() => onSaveDueDate(due || null)}
              >
                {t('common.save', { defaultValue: 'Save' })}
              </Button>
            </div>
            {isOverdue(row.due_date) && (
              <p className="mt-1 text-2xs font-medium text-semantic-error">
                {t('clash.overdue', {
                  defaultValue: 'This clash is overdue.',
                })}
              </p>
            )}
          </div>

          {/* Watchers chip (Wave A3). Click toggles the caller's own
              subscription. ``getUserName`` falls back to the raw id
              when the watcher isn't in the project members list — a
              graceful degradation for cross-team coordination. */}
          <div>
            <h3 className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-content-secondary">
              <Eye className="h-3.5 w-3.5" />
              {t('clash.watchers', { defaultValue: 'Watchers' })}
              <span className="rounded-full bg-surface-secondary px-1.5 text-[10px] font-medium text-content-tertiary">
                {watchers.length}
              </span>
            </h3>
            <div className="flex flex-wrap items-center gap-1.5">
              {watchers.map((w) => (
                <span
                  key={w}
                  className="inline-flex items-center gap-1 rounded-full bg-surface-secondary px-2 py-0.5 text-[10px] font-medium text-content-secondary"
                  title={w}
                >
                  {getUserName(w)}
                </span>
              ))}
              {watchers.length === 0 && (
                <span className="text-2xs text-content-tertiary">
                  {t('clash.no_watchers', {
                    defaultValue: 'No watchers yet.',
                  })}
                </span>
              )}
              <Button
                variant={isWatching ? 'primary' : 'secondary'}
                size="sm"
                disabled={!currentUserId || watchMut.isPending}
                icon={
                  isWatching ? (
                    <EyeOff className="h-3.5 w-3.5" />
                  ) : (
                    <Eye className="h-3.5 w-3.5" />
                  )
                }
                onClick={() => watchMut.mutate(!isWatching)}
              >
                {isWatching
                  ? t('clash.unwatch', { defaultValue: 'Unwatch' })
                  : t('clash.watch', { defaultValue: 'Watch' })}
              </Button>
            </div>
          </div>

          {/* Tabbed pane: Comments thread (with threading + @mentions)
              and Activity audit log. */}
          <div>
            <div
              role="tablist"
              onKeyDown={onCollabTabKeyDown}
              aria-label={t('clash.collaboration_tabs', {
                defaultValue: 'Collaboration tabs',
              })}
              className="flex items-center gap-1 border-b border-border-light"
            >
              <button
                type="button"
                role="tab"
                id="clash-collab-tab-comments"
                aria-selected={tab === 'comments'}
                aria-controls="clash-collab-panel-comments"
                tabIndex={tab === 'comments' ? 0 : -1}
                onClick={() => setTab('comments')}
                className={clsx(
                  'inline-flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-xs font-medium',
                  tab === 'comments'
                    ? 'border-oe-blue text-content-primary'
                    : 'border-transparent text-content-tertiary hover:text-content-secondary',
                )}
              >
                <MessageSquare className="h-3.5 w-3.5" />
                {t('clash.comments', { defaultValue: 'Comments' })}
                <span className="rounded-full bg-surface-secondary px-1.5 text-[10px] font-medium text-content-tertiary">
                  {comments.length}
                </span>
              </button>
              <button
                type="button"
                role="tab"
                id="clash-collab-tab-activity"
                aria-selected={tab === 'activity'}
                aria-controls="clash-collab-panel-activity"
                tabIndex={tab === 'activity' ? 0 : -1}
                onClick={() => setTab('activity')}
                className={clsx(
                  'inline-flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-xs font-medium',
                  tab === 'activity'
                    ? 'border-oe-blue text-content-primary'
                    : 'border-transparent text-content-tertiary hover:text-content-secondary',
                )}
              >
                <History className="h-3.5 w-3.5" />
                {t('clash.activity', { defaultValue: 'Activity' })}
                <span className="rounded-full bg-surface-secondary px-1.5 text-[10px] font-medium text-content-tertiary">
                  {activity.length}
                </span>
              </button>
            </div>

            {tab === 'comments' && (
              <div className="mt-2 space-y-2">
                {comments.length === 0 && (
                  <p className="text-2xs text-content-tertiary">
                    {t('clash.no_comments', {
                      defaultValue: 'No comments yet.',
                    })}
                  </p>
                )}
                {topLevel.flatMap((c) => {
                  const replies = childrenByParent.get(c.ts) ?? [];
                  const bubbles: React.ReactNode[] = [
                    <ClashCommentBubble
                      key={`tl-${c.ts}`}
                      comment={c}
                      indent={0}
                      onReply={() => {
                        setReplyTo(c.ts);
                        draftRef.current?.focus();
                      }}
                      getUserName={getUserName}
                      t={t}
                    />,
                  ];
                  for (const child of replies) {
                    bubbles.push(
                      <ClashCommentBubble
                        key={`rep-${child.ts}`}
                        comment={child}
                        indent={1}
                        onReply={() => {
                          setReplyTo(c.ts);
                          draftRef.current?.focus();
                        }}
                        getUserName={getUserName}
                        t={t}
                      />,
                    );
                  }
                  return bubbles;
                })}
              </div>
            )}

            {tab === 'activity' && (
              <div className="mt-2 space-y-1.5">
                {activity.length === 0 && (
                  <p className="text-2xs text-content-tertiary">
                    {t('clash.no_activity', {
                      defaultValue: 'No activity yet.',
                    })}
                  </p>
                )}
                {activity.map((h, i) => (
                  <div
                    key={`act-${h.ts}-${i}`}
                    className="flex items-start gap-2 rounded-md border border-border-light bg-surface-secondary/30 px-2 py-1.5"
                  >
                    <History className="mt-0.5 h-3 w-3 shrink-0 text-content-tertiary" />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-1 text-[10px] text-content-tertiary">
                        <span className="font-medium text-content-secondary">
                          {getUserName(h.actor)}
                        </span>
                        <span>·</span>
                        <span className="tabular-nums">
                          {new Date(h.ts).toLocaleString()}
                        </span>
                      </div>
                      <p className="mt-0.5 break-words text-2xs text-content-primary">
                        <span className="font-medium">{h.field}</span>
                        {h.before !== null && h.after !== null && (
                          <>
                            : <span className="line-through opacity-60">{h.before}</span>{' '}
                            → <span>{h.after}</span>
                          </>
                        )}
                        {h.before === null && h.after !== null && (
                          <>: {h.after}</>
                        )}
                        {h.before !== null && h.after === null && (
                          <>: <span className="line-through opacity-60">{h.before}</span></>
                        )}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Add-comment composer. Stays visible on either tab so the
                user can drop a note without flipping back. */}
            {tab === 'comments' && (
              <div className="relative mt-3">
                {replyTo && (
                  <div className="mb-1.5 flex items-center gap-1.5 rounded-md border border-border-light bg-surface-secondary/60 px-2 py-1 text-2xs text-content-secondary">
                    <Reply className="h-3 w-3" />
                    <span className="truncate">
                      {t('clash.replying_to', {
                        defaultValue: 'Replying to {{author}}',
                        author:
                          comments.find((c) => c.ts === replyTo)?.author ?? '',
                      })}
                    </span>
                    <button
                      type="button"
                      className="ml-auto rounded p-0.5 text-content-tertiary hover:bg-surface-primary"
                      onClick={() => setReplyTo(null)}
                      aria-label={t('clash.cancel_reply', {
                        defaultValue: 'Cancel reply',
                      })}
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                )}
                <textarea
                  ref={draftRef}
                  value={draft}
                  rows={3}
                  maxLength={4000}
                  placeholder={t('clash.comment_ph_mention', {
                    defaultValue: 'Add a coordination note… (@ to mention)',
                  })}
                  onChange={(e) => handleDraftChange(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Escape' && mentionOpen) {
                      e.stopPropagation();
                      setMentionOpen(false);
                    }
                  }}
                  className="w-full resize-y rounded-md border border-border bg-surface-primary px-2 py-1.5 text-sm"
                />
                {mentionOpen && mentionCandidates.length > 0 && (
                  <div
                    role="listbox"
                    className="absolute z-10 mt-1 max-h-56 w-full overflow-y-auto rounded-md border border-border bg-surface-elevated shadow-lg"
                  >
                    {mentionCandidates.map((m) => (
                      <button
                        key={m.user_id}
                        type="button"
                        role="option"
                        aria-selected={false}
                        onClick={() => insertMention(m.user_id)}
                        className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs hover:bg-surface-secondary"
                      >
                        <AtSign className="h-3 w-3 text-content-tertiary" />
                        <span className="truncate font-medium text-content-primary">
                          {(m.full_name && m.full_name.trim()) || m.email}
                        </span>
                        {m.full_name && (
                          <span className="ml-auto truncate text-2xs text-content-tertiary">
                            {m.email}
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
                <div className="mt-2 flex justify-end">
                  <Button
                    variant="primary"
                    size="sm"
                    loading={saving}
                    disabled={!draft.trim()}
                    icon={<MessageSquare className="h-4 w-4" />}
                    onClick={submitDraft}
                  >
                    {replyTo
                      ? t('clash.reply', { defaultValue: 'Reply' })
                      : t('clash.add_comment', {
                          defaultValue: 'Add comment',
                        })}
                  </Button>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="mt-auto border-t border-border-light p-4">
          <Link
            to={bimLink}
            className="inline-flex items-center gap-1.5 rounded-md bg-oe-blue/10 px-3 py-1.5 text-xs font-medium text-oe-blue hover:bg-oe-blue/20"
          >
            <Box className="h-4 w-4" />
            {t('clash.isolate_3d', {
              defaultValue: 'Isolate in 3D',
            })}
          </Link>
        </div>
      </div>
    </div>
  );
}

/**
 * Render a comment text body with ``<at>userId</at>`` mention tokens
 * resolved to user-name chips (Wave A3). Plain text segments survive
 * verbatim; the parser is the matching client-side counterpart of the
 * backend ``_extract_mentions`` extractor.
 */
function renderCommentText(
  text: string,
  getUserName: (id: string) => string,
): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < text.length) {
    const start = text.indexOf('<at>', i);
    if (start < 0) {
      parts.push(text.slice(i));
      break;
    }
    if (start > i) parts.push(text.slice(i, start));
    const end = text.indexOf('</at>', start + 4);
    if (end < 0) {
      parts.push(text.slice(start));
      break;
    }
    const uid = text.slice(start + 4, end).trim();
    parts.push(
      <span
        key={`mention-${key++}`}
        className="inline-flex items-center gap-0.5 rounded bg-oe-blue/10 px-1 py-px text-[11px] font-medium text-oe-blue"
        title={uid}
      >
        <AtSign className="h-2.5 w-2.5" />
        {getUserName(uid)}
      </span>,
    );
    i = end + 5;
  }
  return parts;
}

/**
 * One comment row inside the threaded comments list (Wave A3). Indented
 * one level when ``indent > 0`` (replies), otherwise rendered at the
 * top level. Mentions are resolved to user-name chips.
 */
function ClashCommentBubble({
  comment,
  indent,
  onReply,
  getUserName,
  t,
}: {
  comment: ClashComment;
  indent: number;
  onReply: () => void;
  getUserName: (id: string) => string;
  t: TFn;
}) {
  return (
    <div
      className={clsx(
        'rounded-lg border border-border-light bg-surface-secondary/40 p-2',
        indent > 0 && 'ml-6 border-l-2 border-l-oe-blue/40',
      )}
    >
      <div className="flex items-center justify-between gap-2 text-[10px] text-content-tertiary">
        <span className="truncate font-medium text-content-secondary">
          {comment.author}
        </span>
        <span className="shrink-0 tabular-nums">
          {new Date(comment.ts).toLocaleString()}
        </span>
      </div>
      <p className="mt-1 whitespace-pre-wrap break-words text-xs text-content-primary">
        {renderCommentText(comment.text, getUserName)}
      </p>
      <div className="mt-1 flex justify-end">
        <button
          type="button"
          onClick={onReply}
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium text-content-tertiary hover:bg-surface-primary hover:text-content-secondary"
        >
          <Reply className="h-3 w-3" />
          {t('clash.reply', { defaultValue: 'Reply' })}
        </button>
      </div>
    </div>
  );
}

/** One bucket (New / Resolved / Persistent) of the run-to-run diff. */
function CompareBucket({
  bucketKey,
  title,
  count,
  tone,
  collapsed,
  onToggle,
  children,
}: {
  bucketKey: string;
  title: string;
  count: number;
  tone: 'new' | 'resolved' | 'persistent';
  collapsed: boolean;
  onToggle: (k: string) => void;
  children: React.ReactNode;
}) {
  const badge =
    tone === 'new'
      ? 'bg-semantic-error-bg text-semantic-error'
      : tone === 'resolved'
        ? 'bg-semantic-success-bg text-semantic-success'
        : 'bg-surface-secondary text-content-secondary';
  return (
    <div className="rounded-lg border border-border-light">
      <button
        type="button"
        onClick={() => onToggle(bucketKey)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-semibold text-content-primary"
      >
        {collapsed ? (
          <ChevronRight className="h-3.5 w-3.5 text-content-tertiary" />
        ) : (
          <ChevronLeft className="h-3.5 w-3.5 rotate-[-90deg] text-content-tertiary" />
        )}
        <span>{title}</span>
        <span
          className={clsx(
            'rounded-full px-1.5 py-0.5 text-[10px] font-medium',
            badge,
          )}
        >
          {count}
        </span>
      </button>
      {!collapsed && count > 0 && (
        <div className="border-t border-border-light">{children}</div>
      )}
    </div>
  );
}

/** Run-to-run comparison view — New / Resolved / Persistent buckets with
 *  colour-coded counts. New is emphasised (needs attention), Resolved is
 *  muted green, Persistent neutral. Compared clashes still open in 3D when
 *  the result is still in the loaded set. Stays inside the page. */
function CompareSection({
  loading,
  error,
  data,
  collapsed,
  onToggle,
  onClose,
  resultById,
  bimLink,
  t,
}: {
  loading: boolean;
  error: string | null;
  data: ClashCompare | undefined;
  collapsed: Set<string>;
  onToggle: (k: string) => void;
  onClose: () => void;
  resultById: (id: string) => ClashResult | null;
  bimLink: (r: ClashResult) => string;
  t: TFn;
}) {
  function Row({ s }: { s: ClashResultSummary }) {
    const full = resultById(s.id);
    return (
      <div className="flex items-center gap-2 border-b border-border-light/60 px-3 py-1.5 text-xs last:border-b-0">
        <span className="min-w-0 flex-1 truncate text-content-primary">
          {s.a_name} ↔ {s.b_name}
        </span>
        <SeverityBadge severity={s.severity} t={t} />
        <span className="shrink-0 text-2xs text-content-tertiary">
          {t(`clash.status.${s.status}`, { defaultValue: s.status })}
        </span>
        {full && (
          <Link
            to={bimLink(full)}
            title={t('clash.isolate_3d', {
              defaultValue: 'Isolate in 3D',
            })}
            className="inline-flex shrink-0 items-center gap-1 rounded-md bg-oe-blue/10 px-1.5 py-0.5 text-2xs font-medium text-oe-blue hover:bg-oe-blue/20"
          >
            <Box className="h-3 w-3" />
            {t('clash.isolate_3d_short', { defaultValue: '3D' })}
          </Link>
        )}
      </div>
    );
  }

  return (
    <Card padding="md" className="border-oe-blue/30">
      <div className="flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
          <GitCompareArrows className="h-4 w-4 text-oe-blue" />
          {t('clash.compare_title', {
            defaultValue: 'Run-to-run comparison',
          })}
        </h2>
        <button
          type="button"
          aria-label={t('common.close', { defaultValue: 'Close' })}
          onClick={onClose}
          className="rounded-md p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {loading ? (
        <div className="mt-3 space-y-2">
          {Array.from({ length: 3 }).map((_, i) => (
            <div
              key={i}
              className="h-9 animate-pulse rounded-md bg-surface-secondary"
            />
          ))}
        </div>
      ) : error ? (
        <p className="mt-3 flex items-center gap-2 text-xs text-semantic-error">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {error}
        </p>
      ) : data ? (
        <>
          <div className="mt-3 grid grid-cols-3 gap-2">
            <div className="rounded-lg bg-semantic-error-bg p-2 text-center">
              <div className="text-lg font-bold tabular-nums text-semantic-error">
                {data.stats.new}
              </div>
              <div className="text-2xs font-medium text-semantic-error">
                {t('clash.cmp_new', { defaultValue: 'New' })}
              </div>
            </div>
            <div className="rounded-lg bg-semantic-success-bg p-2 text-center">
              <div className="text-lg font-bold tabular-nums text-semantic-success">
                {data.stats.resolved}
              </div>
              <div className="text-2xs font-medium text-semantic-success">
                {t('clash.cmp_resolved', {
                  defaultValue: 'Resolved',
                })}
              </div>
            </div>
            <div className="rounded-lg bg-surface-secondary p-2 text-center">
              <div className="text-lg font-bold tabular-nums text-content-primary">
                {data.stats.persistent}
              </div>
              <div className="text-2xs font-medium text-content-secondary">
                {t('clash.cmp_persistent', {
                  defaultValue: 'Persistent',
                })}
              </div>
            </div>
          </div>
          <p className="mt-2 text-2xs text-content-tertiary">
            {t('clash.cmp_totals', {
              defaultValue:
                'Base run: {{b}} clashes · this run: {{c}} clashes',
              b: data.stats.base_total,
              c: data.stats.current_total,
            })}
          </p>

          <div className="mt-3 space-y-2">
            <CompareBucket
              bucketKey="new"
              tone="new"
              title={t('clash.cmp_new_title', {
                defaultValue: 'New clashes - need attention',
              })}
              count={data.new.length}
              collapsed={collapsed.has('new')}
              onToggle={onToggle}
            >
              {data.new.map((s) => (
                <Row key={s.id} s={s} />
              ))}
            </CompareBucket>

            <CompareBucket
              bucketKey="resolved"
              tone="resolved"
              title={t('clash.cmp_resolved_title', {
                defaultValue: 'Resolved since the base run',
              })}
              count={data.resolved.length}
              collapsed={
                // Default-collapse the muted bucket unless explicitly opened.
                !collapsed.has('resolved:open')
              }
              onToggle={() => onToggle('resolved:open')}
            >
              {data.resolved.map((s) => (
                <Row key={s.id} s={s} />
              ))}
            </CompareBucket>

            <CompareBucket
              bucketKey="persistent"
              tone="persistent"
              title={t('clash.cmp_persistent_title', {
                defaultValue: 'Still present in both runs',
              })}
              count={data.persistent.length}
              collapsed={!collapsed.has('persistent:open')}
              onToggle={() => onToggle('persistent:open')}
            >
              {data.persistent.map((p) => (
                <Row key={p.current.id} s={p.current} />
              ))}
            </CompareBucket>
          </div>
        </>
      ) : null}
    </Card>
  );
}

export default ClashDetectionPage;
