// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useLocation, useParams, useSearchParams } from 'react-router-dom';
import {
  Table, Table2, ArrowRight, Copy, Trash2, Plus,
  Search, ArrowUpDown, ChevronDown, GitCompareArrows, X, Loader2,
  CalendarDays,
} from 'lucide-react';
import { Card, Badge, EmptyState, Skeleton, Button, Breadcrumb, FileTypeChips, DismissibleInfo, IntroRichText, RecoveryCard } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { apiGet } from '@/shared/lib/api';
import { fmtCompact, fmtNumber, fmtPercent } from '@/shared/lib/formatters';
import { useNameCollator } from '@/shared/lib/collator';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { boqApi, type BOQWithPositions, groupPositionsIntoSections, type SectionGroup } from './api';
import { resourceAwareTotalInBase, getCurrencyCode } from './boqHelpers';
import { projectsApi, type ProjectFxRate } from '@/features/projects/api';
import { useToastStore } from '@/stores/useToastStore';
import { useModuleStore } from '@/stores/useModuleStore';
import { PresenceAvatars } from '@/modules/collaboration/components/PresenceAvatars';
import { usePresenceStore } from '@/modules/collaboration/hooks/usePresence';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { CreateBOQModal } from './CreateBOQPage';

interface Project {
  id: string;
  name: string;
  currency: string;
  classification_standard: string;
}

interface BOQ {
  id: string;
  project_id: string;
  name: string;
  description: string;
  status: string;
  created_at: string;
  position_count?: number;
  // Backend v3 §10 contract serializes money as Decimal-as-string. Keep
  // the type honest so the boundary coercion below is type-safe and so
  // future call-sites can't `b.grand_total - x` without thinking.
  grand_total?: number | string | null;
}

interface BOQWithProject extends BOQ {
  projectName: string;
  currency: string;
  positionCount: number;
  grandTotal: number;
  classificationStandard: string;
}

const ITEMS_PER_PAGE = 12;

// Stable display order for the status stat badges: known statuses in their
// natural workflow order first, then any unrecognised value alphabetically
// so a new backend status doesn't reshuffle the row it lands in.
const STATUS_DISPLAY_ORDER = ['draft', 'in_review', 'final', 'approved', 'archived'];

/**
 * A whole-number amount in the reader's language.
 *
 * This used to be an `Intl.NumberFormat` built at module scope. The language
 * switcher deliberately does not reload the app, so a formatter built when
 * the chunk first loaded kept writing in whatever language the page opened
 * in: a German reader who arrived in English saw `12,550,880` beside rows
 * formatted `12.550.880`. Reading the locale per call is what every other
 * helper in `shared/lib/formatters` already does.
 */
const currencyFmt = { format: (value: number) => fmtNumber(value, 0) };

/**
 * Compact money for the stat cards — always paired with its ISO currency
 * code by the caller (money rule: a figure is never shown without its
 * currency). Locale-aware: "22.1M" under en, "22,1 Mio." under de, so the
 * tile agrees with the row-level money formatting on the same screen.
 */
function compactMoney(value: number): string {
  if (value >= 1_000) return fmtCompact(value);
  return currencyFmt.format(value);
}

/* ── Compare Modal ───────────────────────────────────────────────────── */

interface CompareModalProps {
  boqIdA: string;
  boqIdB: string;
  currencyA: string;
  currencyB: string;
  onClose: () => void;
}

function fmtDiff(diff: number, currency: string): string {
  const sign = diff >= 0 ? '+' : '';
  return `${sign}${currencyFmt.format(diff)} ${currency}`;
}

function fmtPct(a: number, b: number): string {
  // Coerce defensively — `grand_total` arrives as Decimal-as-string, so a
  // strict `a === 0` would never match the string "0" and would feed NaN
  // into the ratio below. Number() the boundary before any arithmetic.
  const na = Number(a);
  const nb = Number(b);
  if (na === 0) return nb === 0 ? '0%' : '+100%';
  const pct = ((nb - na) / Math.abs(na)) * 100;
  const sign = pct >= 0 ? '+' : '';
  return `${sign}${fmtPercent(pct)}`;
}

function diffColor(diff: number): string {
  if (diff < 0) return 'text-semantic-success';
  if (diff > 0) return 'text-semantic-error';
  return 'text-content-tertiary';
}

/** Flatten a project's ``fx_rates`` (``{code, rate:string}``) into the
 *  ``{currency, rate:number}`` shape ``groupPositionsIntoSections`` /
 *  ``resourceAwareTotalInBase`` expect. Mirrors the BOQ editor's plumbing so
 *  the compare totals convert foreign-currency resources to base identically
 *  (Issue #150). */
function flattenFxRates(rates: ProjectFxRate[] | undefined): Array<{ currency: string; rate: number }> {
  return (rates ?? [])
    .map((fx) => ({ currency: fx.code, rate: Number(fx.rate) }))
    .filter((fx) => fx.currency && Number.isFinite(fx.rate));
}

function CompareModal({ boqIdA, boqIdB, currencyA, currencyB, onClose }: CompareModalProps) {
  const { t } = useTranslation();
  const [boqA, setBoqA] = useState<BOQWithPositions | null>(null);
  const [boqB, setBoqB] = useState<BOQWithPositions | null>(null);
  // Issue #150 — each BOQ's project carries its own base currency + FX rates
  // (rates are project-scoped). Fetch both so section subtotals convert
  // foreign-currency resources to each side's base, matching the editor grid.
  const [fxA, setFxA] = useState<Array<{ currency: string; rate: number }>>([]);
  const [fxB, setFxB] = useState<Array<{ currency: string; rate: number }>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([boqApi.get(boqIdA), boqApi.get(boqIdB)])
      .then(async ([a, b]) => {
        if (cancelled) return;
        setBoqA(a);
        setBoqB(b);
        // Best-effort FX fetch — if a project read fails (or the BOQ carries
        // no project_id) we fall back to an empty rate list, which leaves
        // totals unconverted rather than blocking the comparison.
        const [pa, pb] = await Promise.all([
          a.project_id ? projectsApi.get(a.project_id).catch(() => null) : Promise.resolve(null),
          b.project_id ? projectsApi.get(b.project_id).catch(() => null) : Promise.resolve(null),
        ]);
        if (cancelled) return;
        setFxA(flattenFxRates(pa?.fx_rates));
        setFxB(flattenFxRates(pb?.fx_rates));
      })
      .catch(() => {
        if (!cancelled) setError(t('boq.compare_load_error', { defaultValue: 'Failed to load BOQ data for comparison' }));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => { cancelled = true; };
  }, [boqIdA, boqIdB, t]);

  // Build section comparison: match sections by ordinal or description
  const comparison = useMemo(() => {
    if (!boqA || !boqB) return null;

    // Issue #150 — convert each side's foreign-currency resources into that
    // side's own base currency before comparing subtotals (same conversion as
    // the editor grid). The two sides keep their own currency; a cross-currency
    // blended diff is still blocked below via ``currencyMismatch``.
    // ``currencyA/B`` can be a display string ("USD ($) — US Dollar"); extract
    // the bare ISO code so it matches the resources' / fx_rates' codes.
    const baseA = getCurrencyCode(currencyA) || currencyA;
    const baseB = getCurrencyCode(currencyB) || currencyB;
    const fxOptsA = { baseCurrency: baseA, fxRates: fxA };
    const fxOptsB = { baseCurrency: baseB, fxRates: fxB };
    const groupA = groupPositionsIntoSections(boqA.positions, fxOptsA);
    const groupB = groupPositionsIntoSections(boqB.positions, fxOptsB);

    // Build a map of section key -> section data for both sides
    const sectionKey = (sg: SectionGroup) =>
      sg.section.ordinal.trim() || sg.section.description.trim().toLowerCase();

    const mapA = new Map<string, SectionGroup>();
    const mapB = new Map<string, SectionGroup>();
    for (const s of groupA.sections) mapA.set(sectionKey(s), s);
    for (const s of groupB.sections) mapB.set(sectionKey(s), s);

    const allKeys = new Set([...mapA.keys(), ...mapB.keys()]);
    const paired: { key: string; nameA: string; nameB: string; totalA: number; totalB: number; countA: number; countB: number }[] = [];

    for (const key of allKeys) {
      const a = mapA.get(key);
      const b = mapB.get(key);
      paired.push({
        key,
        nameA: a?.section.description ?? '--',
        nameB: b?.section.description ?? '--',
        totalA: a?.subtotal ?? 0,
        totalB: b?.subtotal ?? 0,
        countA: a?.children.length ?? 0,
        countB: b?.children.length ?? 0,
      });
    }

    // Add ungrouped totals if any (resource-aware base conversion per side).
    const ungroupedTotalA = groupA.ungrouped.reduce(
      (s, p) => s + resourceAwareTotalInBase(p, baseA, fxA), 0);
    const ungroupedTotalB = groupB.ungrouped.reduce(
      (s, p) => s + resourceAwareTotalInBase(p, baseB, fxB), 0);
    if (ungroupedTotalA > 0 || ungroupedTotalB > 0) {
      paired.push({
        key: '__ungrouped__',
        nameA: t('boq.ungrouped', { defaultValue: 'Ungrouped' }),
        nameB: t('boq.ungrouped', { defaultValue: 'Ungrouped' }),
        totalA: ungroupedTotalA,
        totalB: ungroupedTotalB,
        countA: groupA.ungrouped.length,
        countB: groupB.ungrouped.length,
      });
    }

    return { paired };
  }, [boqA, boqB, currencyA, currencyB, fxA, fxB, t]);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  // The two BOQs may live in different projects with different base
  // currencies. There is NO cross-project FX rate table (rates are scoped
  // WITHIN a project), so a blended diff would be financially meaningless.
  // Block the numeric comparison and tell the user, but still show each
  // side's own total labelled with its own ISO code.
  const currencyMismatch = !!currencyA && !!currencyB && currencyA !== currencyB;

  // v3 §10 contract: `grand_total` arrives as Decimal-as-string. Coerce at
  // the modal boundary so every figure/diff/format below is a finite number.
  const totalA = boqA ? Number(boqA.grand_total) : 0;
  const totalB = boqB ? Number(boqB.grand_total) : 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in" onClick={onClose}>
      <div
        className="relative mx-4 max-h-[85vh] w-full max-w-4xl overflow-hidden rounded-2xl bg-surface-primary border border-border-light shadow-2xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border-light px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text">
              <GitCompareArrows size={18} />
            </div>
            <h2 className="text-lg font-bold text-content-primary">{t('boq.compare_title', { defaultValue: 'BOQ Comparison' })}</h2>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-6">
          {loading ? (
            <div className="flex items-center justify-center gap-3 py-16 text-content-tertiary">
              <Loader2 size={20} className="animate-spin" />
              <span className="text-sm">{t('common.loading')}</span>
            </div>
          ) : error ? (
            <div className="py-16 text-center text-sm text-semantic-error">{error}</div>
          ) : boqA && boqB && comparison ? (
            <div className="space-y-6">
              {/* Summary row */}
              <div className="grid grid-cols-2 gap-4">
                {/* BOQ A summary */}
                <div className="rounded-xl border border-border-light bg-surface-elevated p-4">
                  <div className="text-xs font-medium text-content-tertiary uppercase tracking-wider mb-1">A</div>
                  <div className="text-sm font-bold text-content-primary truncate">{boqA.name}</div>
                  <div className="mt-2 flex items-baseline gap-2">
                    <span className="text-xl font-bold text-content-primary tabular-nums">{currencyFmt.format(totalA)}</span>
                    <span className="text-xs text-content-tertiary">{currencyA || '--'}</span>
                  </div>
                  <div className="mt-1 text-xs text-content-tertiary">{boqA.positions.length} {t('boq.positions_label', { defaultValue: 'positions' })}</div>
                </div>

                {/* BOQ B summary */}
                <div className="rounded-xl border border-border-light bg-surface-elevated p-4">
                  <div className="text-xs font-medium text-content-tertiary uppercase tracking-wider mb-1">B</div>
                  <div className="text-sm font-bold text-content-primary truncate">{boqB.name}</div>
                  <div className="mt-2 flex items-baseline gap-2">
                    <span className="text-xl font-bold text-content-primary tabular-nums">{currencyFmt.format(totalB)}</span>
                    <span className="text-xs text-content-tertiary">{currencyB || '--'}</span>
                  </div>
                  <div className="mt-1 text-xs text-content-tertiary">{boqB.positions.length} {t('boq.positions_label', { defaultValue: 'positions' })}</div>
                </div>
              </div>

              {/* Difference banner — only when both sides share a currency.
                  Across currencies there is no cross-project FX rate, so we
                  never blend them into one diff (money rule b). */}
              {currencyMismatch ? (
                <div className="rounded-xl border border-amber-500/30 bg-amber-50 dark:bg-amber-950/30 p-4 text-center">
                  <div className="text-xs font-medium text-content-tertiary uppercase tracking-wider mb-1">
                    {t('boq.compare_difference', { defaultValue: 'Difference (B vs A)' })}
                  </div>
                  <div className="text-sm font-medium text-amber-700 dark:text-amber-400">
                    {t('boq.compare_currency_mismatch', {
                      defaultValue:
                        'These estimates use different currencies ({{currencyA}} vs {{currencyB}}), so totals cannot be subtracted. Compare each side in its own currency above.',
                      currencyA,
                      currencyB,
                    })}
                  </div>
                </div>
              ) : (
                (() => {
                  const diff = totalB - totalA;
                  const currency = currencyA || currencyB || 'EUR';
                  return (
                    <div className={`rounded-xl border p-4 text-center ${diff > 0 ? 'border-semantic-error/30 bg-semantic-error-bg' : diff < 0 ? 'border-semantic-success/30 bg-semantic-success-bg' : 'border-border-light bg-surface-secondary'}`}>
                      <div className="text-xs font-medium text-content-tertiary uppercase tracking-wider mb-1">
                        {t('boq.compare_difference', { defaultValue: 'Difference (B vs A)' })}
                      </div>
                      <div className={`text-lg font-bold tabular-nums ${diffColor(diff)}`}>
                        {fmtDiff(diff, currency)} ({fmtPct(totalA, totalB)})
                      </div>
                    </div>
                  );
                })()
              )}

              {/* Section-by-section breakdown */}
              {comparison.paired.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-content-primary mb-3">
                    {t('boq.compare_by_section', { defaultValue: 'By Section' })}
                  </h3>
                  <div className="rounded-xl border border-border-light overflow-hidden">
                    {/* Table header — drop the Diff column when the two BOQs
                        use different currencies (no valid cross-currency
                        subtraction). The A/B columns are labelled with each
                        side's own ISO code so figures stay unambiguous. */}
                    <div className={`grid ${currencyMismatch ? 'grid-cols-[1fr_auto_auto]' : 'grid-cols-[1fr_auto_auto_auto]'} gap-2 bg-surface-secondary px-4 py-2.5 text-2xs font-medium text-content-tertiary uppercase tracking-wider`}>
                      <div>{t('boq.section', { defaultValue: 'Section' })}</div>
                      <div className="w-28 text-right">A{currencyA ? ` (${currencyA})` : ''}</div>
                      <div className="w-28 text-right">B{currencyB ? ` (${currencyB})` : ''}</div>
                      {!currencyMismatch && (
                        <div className="w-24 text-right">{t('boq.compare_diff', { defaultValue: 'Diff' })}</div>
                      )}
                    </div>
                    {/* Rows */}
                    {comparison.paired.map((row, i) => {
                      const diff = row.totalB - row.totalA;
                      return (
                        <div
                          key={row.key}
                          className={`grid ${currencyMismatch ? 'grid-cols-[1fr_auto_auto]' : 'grid-cols-[1fr_auto_auto_auto]'} gap-2 px-4 py-2.5 text-sm ${i % 2 === 0 ? 'bg-surface-primary' : 'bg-surface-elevated/50'}`}
                        >
                          <div className="text-content-primary truncate font-medium">
                            {row.nameA !== '--' ? row.nameA : row.nameB}
                          </div>
                          <div className="w-28 text-right tabular-nums text-content-secondary">
                            {row.totalA > 0 ? currencyFmt.format(row.totalA) : '--'}
                          </div>
                          <div className="w-28 text-right tabular-nums text-content-secondary">
                            {row.totalB > 0 ? currencyFmt.format(row.totalB) : '--'}
                          </div>
                          {!currencyMismatch && (
                            <div className={`w-24 text-right tabular-nums font-medium ${diffColor(diff)}`}>
                              {row.totalA === 0 && row.totalB === 0
                                ? '--'
                                : `${diff >= 0 ? '+' : ''}${currencyFmt.format(diff)}`}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/* ── BOQ List Page ───────────────────────────────────────────────────── */

type SortField = 'name' | 'total' | 'positions' | 'date';

export function BOQListPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  // /projects/:projectId/boq deep-link — pre-filter to that project so the
  // list isn't a tour through every project's BOQs first.
  const { projectId: projectIdFromUrl } = useParams<{ projectId?: string }>();

  // Create BOQ modal
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [createModalProjectId, setCreateModalProjectId] = useState<string | undefined>();

  // Handle redirect from /projects/:id/boq/new route
  useEffect(() => {
    const state = location.state as { openCreateModal?: boolean; projectId?: string } | null;
    if (state?.openCreateModal) {
      setCreateModalProjectId(state.projectId);
      setCreateModalOpen(true);
      // Clear location state so modal doesn't re-open on navigation
      window.history.replaceState({}, '');
    }
  }, [location.state]);

  // Deep link: /boq?positionId=<id> (or the older ?position=<id> from the BIM
  // viewer). A position id alone does not tell us which BOQ owns it, so we
  // resolve the owning boq_id from the API and redirect to that BOQ's editor
  // with the per-position ?highlight convention BOQEditorPage already reads.
  // Invalid or missing ids leave the user on the list with the param cleared,
  // never a crash or a hang.
  const [searchParams, setSearchParams] = useSearchParams();
  useEffect(() => {
    const positionId = searchParams.get('positionId') ?? searchParams.get('position');
    if (!positionId) return;
    let cancelled = false;
    const clearParam = () => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.delete('positionId');
          next.delete('position');
          return next;
        },
        { replace: true },
      );
    };
    boqApi
      .getPosition(positionId)
      .then((pos) => {
        if (cancelled) return;
        if (pos?.boq_id) {
          // Replace (no extra history entry) so Back returns to wherever the
          // user came from, not to this transient list state.
          navigate(`/boq/${pos.boq_id}?highlight=${encodeURIComponent(positionId)}`, {
            replace: true,
          });
        } else {
          clearParam();
        }
      })
      .catch(() => {
        if (cancelled) return;
        // Unknown / deleted position: stay on the list, drop the param.
        clearParam();
      });
    return () => {
      cancelled = true;
    };
  }, [searchParams, navigate, setSearchParams]);

  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('oe_boq_filters') ?? '{}');
      return saved.status ?? '';
    } catch { return ''; }
  });
  // The project the user picked in the dropdown, and only that. A project the
  // route pins (/projects/:projectId/boq) or the one active in the top bar is
  // a scope this page was opened under, not a choice made in its toolbar, and
  // it never enters this state: the state is persisted, so a scope written
  // here outlived the page that imposed it, and /boq opened after one
  // project's estimates listed that project alone under a header that still
  // counted every estimate.
  const [projectFilter, setProjectFilter] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('oe_boq_filters') ?? '{}');
      return saved.project ?? '';
    } catch { return ''; }
  });
  // On a route-scoped page the fetch below is already narrowed to that
  // project, so the persisted choice does not apply on top of it: a project
  // remembered from /boq would empty another project's page.
  const userProjectFilter = projectIdFromUrl ? '' : projectFilter;
  const [sortField, setSortField] = useState<SortField>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('oe_boq_filters') ?? '{}');
      return saved.sortField ?? 'date';
    } catch { return 'date'; }
  });
  const [sortAsc, setSortAsc] = useState(() => {
    try {
      const saved = JSON.parse(localStorage.getItem('oe_boq_filters') ?? '{}');
      return saved.sortAsc ?? false;
    } catch { return false; }
  });
  const [page, setPage] = useState(1);

  // Switching the active project in the header while this page is open is a
  // choice made with the page in view, so the filter follows it. The project
  // that was already active when the page mounted is not: it used to be copied
  // into the persisted filter on every mount, which is the leak above.
  const activeProjectAtMount = useRef(activeProjectId);
  useEffect(() => {
    if (activeProjectId && activeProjectId !== activeProjectAtMount.current) {
      setProjectFilter(activeProjectId);
    }
    activeProjectAtMount.current = activeProjectId;
  }, [activeProjectId]);

  // Persist filters to localStorage
  useEffect(() => {
    try {
      localStorage.setItem('oe_boq_filters', JSON.stringify({
        status: statusFilter,
        project: projectFilter,
        sortField,
        sortAsc,
      }));
    } catch {}
  }, [statusFilter, projectFilter, sortField, sortAsc]);

  // Compare mode state
  const [compareMode, setCompareMode] = useState(false);
  const [selectedForCompare, setSelectedForCompare] = useState<{ id: string; currency: string } | null>(null);
  const [compareTarget, setCompareTarget] = useState<{ idA: string; idB: string; currencyA: string; currencyB: string } | null>(null);

  const exitCompareMode = useCallback(() => {
    setCompareMode(false);
    setSelectedForCompare(null);
    setCompareTarget(null);
  }, []);

  const handleCompareClick = useCallback((boqId: string, currency: string) => {
    if (!compareMode) {
      // Enter compare mode and select first BOQ
      setCompareMode(true);
      setSelectedForCompare({ id: boqId, currency });
    } else if (selectedForCompare && selectedForCompare.id !== boqId) {
      // Second selection — open modal. Warn up-front when the two BOQs use
      // different currencies: there is no cross-project FX rate, so the
      // modal can only compare each side in its own currency (money rule b).
      if (selectedForCompare.currency && currency && selectedForCompare.currency !== currency) {
        addToast({
          type: 'warning',
          title: t('boq.compare_currency_mismatch_toast', {
            defaultValue: 'Comparing different currencies ({{currencyA}} vs {{currencyB}}); totals are shown side by side, not subtracted.',
            currencyA: selectedForCompare.currency,
            currencyB: currency,
          }),
        });
      }
      setCompareTarget({
        idA: selectedForCompare.id,
        idB: boqId,
        currencyA: selectedForCompare.currency,
        currencyB: currency,
      });
    }
  }, [compareMode, selectedForCompare, addToast, t]);

  const {
    data: projects,
    isLoading: projLoading,
    isError: projError,
    error: projErrorValue,
    refetch: refetchProjects,
  } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const { data: fileTypesByProject } = useQuery({
    queryKey: ['projects-file-types'],
    queryFn: () => apiGet<Record<string, string[]>>('/v1/documents/file-types-by-project/'),
    staleTime: 5 * 60_000,
  });

  // When the URL pins a single project, only fetch that project's BOQs —
  // not every project's. On prod with 50+ projects, the parallel fan-out
  // was costing 1-2s of skeleton state for no reason.
  const scopedProjects = projectIdFromUrl
    ? projects?.filter((p) => p.id === projectIdFromUrl)
    : projects;

  const { data: allBoqs, isLoading: boqLoading } = useQuery({
    queryKey: ['all-boqs', scopedProjects?.map((p) => p.id).join(',')],
    queryFn: async () => {
      if (!scopedProjects || scopedProjects.length === 0) return [];

      // Fetch all BOQs in parallel (one request per project, no N+1 for grand_total)
      const fetches = scopedProjects.map(async (p) => {
        try {
          const boqs = await apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${p.id}`);
          return boqs.map((b) => {
            // v3 §10 contract: money fields arrive as Decimal-as-string. The
            // TypeScript `number` annotation lies — reducing across them
            // string-concatenates ("634204086.52" + "528523" → "634…528…"),
            // and `Number(multi-dot-string)` → NaN. Coerce once at the
            // boundary so every downstream consumer (reduce, comparator,
            // `currencyFmt.format`, threshold checks) sees a finite number.
            const gtRaw = b.grand_total;
            const gtNum =
              typeof gtRaw === 'number' ? gtRaw : Number(gtRaw ?? 0);
            return {
              ...b,
              projectName: p.name,
              currency: p.currency,
              positionCount: b.position_count ?? 0,
              grandTotal: Number.isFinite(gtNum) ? gtNum : 0,
              classificationStandard: p.classification_standard,
            } as BOQWithProject;
          });
        } catch (err) {
          if (import.meta.env.DEV) console.error(`Failed to fetch BOQs for project ${p.id}:`, err);
          return [] as BOQWithProject[];
        }
      });

      const results = await Promise.all(fetches);
      return results.flat();
    },
    enabled: !!scopedProjects && scopedProjects.length > 0,
  });

  // Seed demo presence when collaboration module is enabled and BOQs load
  const isCollabEnabled = useModuleStore((s) => s.isModuleEnabled('collaboration'));
  // The GAEB Exchange module keeps no sidebar entry of its own, so the way in
  // for someone who has not opened a BOQ yet - the estimator who just received
  // an X83 and has nothing to open - is here (Issue #439).
  const isGaebExchangeEnabled = useModuleStore((s) => s.isModuleEnabled('gaeb-exchange'));
  // Regional Exchange is the same shape of surface for the other twenty cost
  // standards, and it kept no sidebar entry either (#217 - twenty country rows
  // would swamp the menu). Until this link existed, none of its twenty routes
  // was reachable by clicking anywhere in the app; the module's hub page picks
  // the country and hands over to the route that was already there.
  const isRegionalExchangeEnabled = useModuleStore((s) => s.isModuleEnabled('regional-exchange'));
  const seedDemoPresence = usePresenceStore((s) => s.seedDemoPresence);
  useEffect(() => {
    if (isCollabEnabled && allBoqs && allBoqs.length > 0) {
      seedDemoPresence(allBoqs.map((b) => b.id));
    }
  }, [isCollabEnabled, allBoqs, seedDemoPresence]);

  /* ── Filter + Sort ────────────────────────────────────────────────── */

  // Estimate names are user data, so the name column has to order them the
  // way this reader's language does rather than by UTF-16 code unit.
  const compareNames = useNameCollator();

  const filtered = useMemo(() => {
    if (!allBoqs) return [];
    let list = [...allBoqs];

    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      list = list.filter(
        (b) =>
          b.name.toLowerCase().includes(q) ||
          b.projectName.toLowerCase().includes(q) ||
          (b.description && b.description.toLowerCase().includes(q)),
      );
    }
    if (statusFilter) {
      list = list.filter((b) => b.status === statusFilter);
    }
    if (userProjectFilter) {
      list = list.filter((b) => b.project_id === userProjectFilter);
    }

    list.sort((a, b) => {
      let cmp = 0;
      switch (sortField) {
        case 'name': cmp = compareNames(a.name, b.name); break;
        case 'total': cmp = a.grandTotal - b.grandTotal; break;
        case 'positions': cmp = a.positionCount - b.positionCount; break;
        case 'date': cmp = new Date(a.created_at).getTime() - new Date(b.created_at).getTime(); break;
      }
      return sortAsc ? cmp : -cmp;
    });

    return list;
  }, [allBoqs, searchQuery, statusFilter, userProjectFilter, sortField, sortAsc, compareNames]);

  const isFiltered = !!(searchQuery || statusFilter || userProjectFilter);

  // Reset page when filters/search/sort change
  useEffect(() => {
    setPage(1);
  }, [searchQuery, statusFilter, projectFilter, sortField, sortAsc]);

  // Pagination
  const totalPages = Math.max(1, Math.ceil(filtered.length / ITEMS_PER_PAGE));
  const paginatedBoqs = filtered.slice(
    (page - 1) * ITEMS_PER_PAGE,
    page * ITEMS_PER_PAGE,
  );

  /* ── Stats ────────────────────────────────────────────────────────── */

  // Stats are computed from the SAME filtered set the list below renders, so
  // the cards never contradict the visible rows. Money is grouped by ISO
  // currency: there is no cross-project FX table, so we never blend
  // currencies into one scalar (money rule b). When every visible BOQ
  // shares a currency the UI shows one labelled total; otherwise it shows
  // per-currency chips.
  const stats = useMemo(() => {
    if (!allBoqs) return null;
    const byCurrency = new Map<string, number>();
    for (const b of filtered) {
      const code = b.currency || 'UNKNOWN';
      byCurrency.set(code, (byCurrency.get(code) ?? 0) + b.grandTotal);
    }
    const totalsByCurrency = [...byCurrency.entries()]
      .map(([currency, total]) => ({ currency, total }))
      .sort((a, b) => b.total - a.total);
    const totalPositions = filtered.reduce((s, b) => s + b.positionCount, 0);
    // Tally every status value present in the filtered set rather than a
    // hardcoded draft/final pair - the backend status column is a free
    // string (models.py), and seeding already writes 'approved' straight
    // to the DB alongside the 'draft' -> 'final' router transition, so a
    // fixed pair silently drops whatever else shows up.
    const byStatus = new Map<string, number>();
    for (const b of filtered) {
      byStatus.set(b.status, (byStatus.get(b.status) ?? 0) + 1);
    }
    return {
      totalsByCurrency,
      multiCurrency: byCurrency.size > 1,
      totalPositions,
      byStatus,
      count: filtered.length,
    };
  }, [allBoqs, filtered]);

  const statusEntries = useMemo(() => {
    if (!stats) return [];
    return [...stats.byStatus.entries()].sort(([a], [b]) => {
      const ia = STATUS_DISPLAY_ORDER.indexOf(a);
      const ib = STATUS_DISPLAY_ORDER.indexOf(b);
      if (ia === -1 && ib === -1) return a.localeCompare(b);
      if (ia === -1) return 1;
      if (ib === -1) return -1;
      return ia - ib;
    });
  }, [stats]);

  /* ── Mutations ────────────────────────────────────────────────────── */

  const duplicateMutation = useMutation({
    mutationFn: (boqId: string) => boqApi.duplicateBoq(boqId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['all-boqs'] });
      addToast({ type: 'success', title: t('boq.duplicated', { defaultValue: 'BOQ duplicated' }) });
    },
    onError: (e: Error) => {
      addToast({ type: 'error', title: t('boq.duplicate_failed', { defaultValue: 'Failed to duplicate' }), message: e.message });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (boqId: string) => boqApi.deleteBoq(boqId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['all-boqs'] });
      setConfirmDeleteId(null);
      addToast({ type: 'success', title: t('boq.deleted', { defaultValue: 'BOQ deleted' }) });
    },
    onError: (e: Error) => {
      setConfirmDeleteId(null);
      addToast({ type: 'error', title: t('boq.delete_failed', { defaultValue: 'Failed to delete' }), message: e.message });
    },
  });

  const handleSort = useCallback((field: SortField) => {
    if (sortField === field) {
      setSortAsc(!sortAsc);
    } else {
      setSortField(field);
      setSortAsc(false);
    }
  }, [sortField, sortAsc]);

  function statusVariant(status: string): 'success' | 'blue' | 'warning' | 'neutral' {
    switch (status) {
      case 'final': return 'success';
      case 'approved': return 'success';
      case 'draft': return 'blue';
      case 'in_review': return 'warning';
      default: return 'neutral';
    }
  }

  // Translate the BOQ status enum for display. Known statuses go through
  // i18n; unknown server-side values fall back to a title-cased token so the
  // badge/filter never shows a raw snake_case key.
  function statusLabel(status: string): string {
    switch (status) {
      case 'draft': return t('boq.status_draft', { defaultValue: 'Draft' });
      case 'in_review': return t('boq.status_in_review', { defaultValue: 'In Review' });
      case 'final': return t('boq.status_final', { defaultValue: 'Final' });
      case 'approved': return t('boq.status_approved', { defaultValue: 'Approved' });
      case 'archived': return t('boq.status_archived', { defaultValue: 'Archived' });
      default:
        return status
          .split('_')
          .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
          .join(' ');
    }
  }

  const isLoading = projLoading || boqLoading;
  const uniqueProjects = Array.from(
    new Map((projects ?? []).map((p) => [p.name, p])).values(),
  );
  const uniqueStatuses = [...new Set((allBoqs ?? []).map((b) => b.status))];

  function valueBorderColor(value: number): string {
    if (value > 10_000_000) return 'border-l-amber-500';
    if (value > 1_000_000) return 'border-l-emerald-500';
    if (value > 100_000) return 'border-l-blue-500';
    return 'border-l-gray-300 dark:border-l-gray-600';
  }

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb items={[{ label: t('boq.title') }]} />
      {/* Canonical top block — module name + icon are shown by the global
          top app bar. The page renders only its subtitle (left) and the
          page actions (right). */}
      <PageHeader
        srTitle={t('boq.title')}
        subtitle={
          /*
            Bug #217 (mobile /boq stuck on "Loading…"): the subtitle previously
            gated on ``allBoqs`` truthiness alone, but the per-project boqs
            query is ``enabled`` only after ``scopedProjects`` resolves and
            has at least one entry — so on first paint (and forever if the
            user has zero projects) ``allBoqs`` stays ``undefined`` and the
            subtitle hangs on "Loading…". Drive the spinner from the actual
            ``isLoading`` query state instead, and fall back to a real
            "0 estimates" count once the query has settled.
          */
          isLoading
            ? t('common.loading')
            : t('boq.list_subtitle_count', {
                defaultValue: '{{boqCount}} estimates across {{projectCount}} projects',
                boqCount: allBoqs?.length ?? 0,
                projectCount: scopedProjects?.length ?? 0,
              })
        }
        actions={
          <>
            {compareMode ? (
              <Button
                variant="ghost"
                size="sm"
                icon={<X size={14} />}
                onClick={exitCompareMode}
              >
                {t('boq.cancel_compare', { defaultValue: 'Cancel Compare' })}
              </Button>
            ) : null}
            <Button
              variant="primary"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => {
                const pid = projectIdFromUrl || activeProjectId || projectFilter || (projects && projects.length === 1 ? projects[0]!.id : undefined) || undefined;
                setCreateModalProjectId(pid);
                setCreateModalOpen(true);
              }}
            >
              {t('boq.new_estimate', { defaultValue: 'New Estimate' })}
            </Button>
          </>
        }
      />

      <DismissibleInfo
        storageKey="boq"
        title={t('boq.intro_title', { defaultValue: 'Every work item priced and totalled' })}
        more={t('boq.intro_more', { defaultValue: '' }) ? <IntroRichText text={t('boq.intro_more')} /> : undefined}
        links={[
          { label: t('nav.validation', { defaultValue: 'Validation' }), onClick: () => navigate('/validation') },
          { label: t('nav.finance', { defaultValue: 'Finance' }), onClick: () => navigate('/finance') },
          { label: t('nav.costs', { defaultValue: 'Cost Database' }), onClick: () => navigate('/costs') },
          {
            label: t('nav.cost_explorer', { defaultValue: 'Cost Explorer' }),
            onClick: () => navigate('/cost-explorer'),
          },
          ...(isGaebExchangeEnabled
            ? [
                {
                  label: t('nav.gaeb_exchange', { defaultValue: 'GAEB Exchange' }),
                  onClick: () =>
                    navigate(
                      activeProjectId
                        ? `/gaeb-exchange?project_id=${encodeURIComponent(activeProjectId)}&tab=import`
                        : '/gaeb-exchange?tab=import',
                    ),
                },
              ]
            : []),
          // No project_id on this one: the hub picks a country before there is
          // a screen to scope, and each country route reads the project from
          // the same context anyway.
          ...(isRegionalExchangeEnabled
            ? [
                {
                  label: t('boq.preset_regional', { defaultValue: 'Regional standards' }),
                  onClick: () => navigate('/regional-exchange'),
                },
              ]
            : []),
        ]}
      >
        {t('boq.intro_body', {
          defaultValue:
            'List the work items, quantities and unit rates for a project and watch them roll up to a live total. Rates come from the cost database and quantities from BIM or PDF takeoff, and the finished estimate feeds validation, the budget and tender packages.',
        })}
      </DismissibleInfo>

      {/* Stats cards — scoped to the SAME filtered set the list renders.
          When a filter narrows the set, an inline scope label says so.
          Canon KPI tile: shared Card, top-aligned label+value, text-lg value. */}
      {stats && allBoqs && allBoqs.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="flex flex-col justify-start rounded-xl border border-slate-200/70 dark:border-slate-700/50 bg-gradient-to-b from-slate-50/70 to-slate-100/45 dark:from-slate-800/50 dark:to-slate-900/35 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
            <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
              {isFiltered
                ? t('boq.matching_estimates', { defaultValue: 'Matching Estimates' })
                : t('boq.total_estimates', { defaultValue: 'Total Estimates' })}
            </div>
            <div className="mt-1 text-lg font-semibold text-content-primary tabular-nums">{stats.count}</div>
          </div>
          <div className="flex flex-col justify-start rounded-xl border border-slate-200/70 dark:border-slate-700/50 bg-gradient-to-b from-slate-50/70 to-slate-100/45 dark:from-slate-800/50 dark:to-slate-900/35 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
            <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">{t('boq.total_positions', { defaultValue: 'Total Positions' })}</div>
            <div className="mt-1 text-lg font-semibold text-content-primary tabular-nums">{stats.totalPositions.toLocaleString(getNumberLocale())}</div>
          </div>
          <div className="flex flex-col justify-start rounded-xl border border-slate-200/70 dark:border-slate-700/50 bg-gradient-to-b from-slate-50/70 to-slate-100/45 dark:from-slate-800/50 dark:to-slate-900/35 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
            <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">{t('boq.total_value', { defaultValue: 'Total Value' })}</div>
            {/* Money rule: never blend currencies into one scalar. One
                labelled total when all share a currency; the dominant
                currency plus a "+N more" affordance otherwise, so the tile
                keeps one baseline and one height across the row. ISO code
                always shown. */}
            {stats.totalsByCurrency.length === 0 ? (
              <div className="mt-1 text-lg font-semibold text-content-primary tabular-nums">&mdash;</div>
            ) : stats.multiCurrency ? (
              <div className="mt-1 text-lg font-semibold text-content-primary tabular-nums">
                {compactMoney(stats.totalsByCurrency[0]!.total)}
                <span className="ml-1 text-xs font-medium text-content-tertiary">
                  {stats.totalsByCurrency[0]!.currency}
                </span>
                <span className="ml-1 text-2xs font-medium text-content-tertiary">
                  {t('boq.plus_n_more', {
                    defaultValue: '+{{count}} more',
                    count: stats.totalsByCurrency.length - 1,
                  })}
                </span>
              </div>
            ) : (
              <div className="mt-1 text-lg font-semibold text-content-primary tabular-nums">
                {compactMoney(stats.totalsByCurrency[0]!.total)}
                <span className="ml-1 text-xs font-medium text-content-tertiary">
                  {stats.totalsByCurrency[0]!.currency}
                </span>
              </div>
            )}
          </div>
          <div className="flex flex-col justify-start rounded-xl border border-slate-200/70 dark:border-slate-700/50 bg-gradient-to-b from-slate-50/70 to-slate-100/45 dark:from-slate-800/50 dark:to-slate-900/35 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
            <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">{t('boq.status', { defaultValue: 'Status' })}</div>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              {statusEntries.map(([status, n]) => (
                <Badge key={status} variant={statusVariant(status)} size="sm" dot>
                  {n} {statusLabel(status)}
                </Badge>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Search + Filters */}
      {allBoqs && allBoqs.length > 0 && (
        <Card padding="none">
          <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center">
            {/* Search */}
            <div className="relative flex-1">
              <div className="pointer-events-none absolute inset-y-0 start-0 flex items-center pl-3 text-content-tertiary">
                <Search size={16} />
              </div>
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t('boq.search_placeholder', { defaultValue: 'Search estimates...' })}
                className="h-10 w-full rounded-lg border border-border bg-surface-primary ps-10 pe-3 text-sm text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent"
              />
            </div>

            {/* Project filter */}
            {!projectIdFromUrl && uniqueProjects.length > 1 && (
              <div className="relative">
                <select
                  value={projectFilter}
                  onChange={(e) => setProjectFilter(e.target.value)}
                  aria-label={t('a11y.boq.project_filter', {
                    defaultValue: 'Filter estimates by project',
                  })}
                  className="h-10 max-w-full appearance-none rounded-lg border border-border bg-surface-primary ps-3 pe-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:min-w-44 sm:max-w-80"
                >
                  <option value="">{t('boq.all_projects', { defaultValue: 'All projects' })}</option>
                  {uniqueProjects.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
                <div className="pointer-events-none absolute inset-y-0 end-0 flex items-center pe-2.5 text-content-tertiary">
                  <ChevronDown size={14} />
                </div>
              </div>
            )}

            {/* Status filter */}
            {uniqueStatuses.length > 1 && (
              <div className="relative">
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  aria-label={t('a11y.boq.status_filter', {
                    defaultValue: 'Filter estimates by status',
                  })}
                  className="h-10 appearance-none rounded-lg border border-border bg-surface-primary ps-3 pe-9 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue sm:w-32"
                >
                  <option value="">{t('boq.all_statuses', { defaultValue: 'All statuses' })}</option>
                  {uniqueStatuses.map((s) => (
                    <option key={s} value={s}>{statusLabel(s)}</option>
                  ))}
                </select>
                <div className="pointer-events-none absolute inset-y-0 end-0 flex items-center pe-2.5 text-content-tertiary">
                  <ChevronDown size={14} />
                </div>
              </div>
            )}

            {/* Sort buttons */}
            <div className="flex items-center gap-1 shrink-0">
              {([
                ['name', t('boq.name', { defaultValue: 'Name' })],
                ['total', t('boq.value', { defaultValue: 'Value' })],
                ['date', t('boq.date', { defaultValue: 'Date' })],
              ] as [SortField, string][]).map(([field, label]) => (
                <button
                  key={field}
                  onClick={() => handleSort(field)}
                  className={`flex items-center gap-1 rounded-md px-2 py-1.5 text-2xs font-medium transition-colors ${
                    sortField === field
                      ? 'bg-oe-blue-subtle text-oe-blue-text'
                      : 'text-content-tertiary hover:text-content-secondary hover:bg-surface-secondary'
                  }`}
                >
                  {label}
                  {sortField === field && (
                    <ArrowUpDown size={10} className={sortAsc ? '' : 'rotate-180'} />
                  )}
                </button>
              ))}
            </div>
          </div>
        </Card>
      )}

      {/* Compare mode banner */}
      {compareMode && selectedForCompare && !compareTarget && (
        <div className="flex items-center gap-3 rounded-xl border border-oe-blue/30 bg-oe-blue-subtle px-4 py-3">
          <GitCompareArrows size={16} className="text-oe-blue shrink-0" />
          <span className="text-sm text-oe-blue font-medium">
            {t('boq.compare_select_second', { defaultValue: 'Select a second BOQ to compare' })}
          </span>
        </div>
      )}

      {/* Results */}
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} height={80} className="w-full" rounded="lg" />
          ))}
        </div>
      ) : projError ? (
        // The projects query gates the whole BOQ list (BOQs are fetched per
        // project). When it fails we'd otherwise fall through to "No BOQs
        // yet", hiding the real auth/permission/server error — surface a
        // recovery affordance instead.
        <RecoveryCard error={projErrorValue} onRetry={() => refetchProjects()} />
      ) : filtered.length === 0 && (searchQuery || statusFilter || userProjectFilter) ? (
        <EmptyState
          icon={<Search size={28} strokeWidth={1.5} />}
          title={t('boq.no_results', { defaultValue: 'No matching estimates' })}
          description={t('boq.no_results_hint', { defaultValue: 'Try adjusting your search or filters' })}
        />
      ) : !allBoqs || allBoqs.length === 0 ? (
        <EmptyState
          icon={<Table size={28} strokeWidth={1.5} />}
          title={t('boq.no_boqs', { defaultValue: 'No BOQs yet' })}
          description={t('boq.no_boqs_hint', { defaultValue: 'A Bill of Quantities is the foundation of your estimate. Start by creating a project, then add sections (trade groups) and positions (work items) with quantities and rates.' })}
          action={{
            label: t('boq.create_boq', { defaultValue: 'Create BOQ' }),
            onClick: () => navigate('/projects/new'),
          }}
        />
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {paginatedBoqs.map((boq, i) => (
            <Card
              key={boq.id}
              hoverable
              padding="none"
              className={`group relative flex h-full flex-col cursor-pointer animate-card-in overflow-hidden border-l-4 ${valueBorderColor(boq.grandTotal)} ${selectedForCompare?.id === boq.id ? 'ring-2 ring-oe-blue' : ''}`}
              style={{ animationDelay: `${50 + i * 30}ms` }}
              onClick={() => {
                if (compareMode && selectedForCompare && selectedForCompare.id !== boq.id) {
                  handleCompareClick(boq.id, boq.currency);
                } else if (!compareMode) {
                  navigate(`/boq/${boq.id}`);
                }
              }}
            >
              {/* Card body, product-card rhythm: identity at the top (icon,
                  status, the estimate name and where it lives); the money is
                  anchored to the bottom just above the actions, so every card
                  in a row lines its total and controls up on one baseline no
                  matter how many lines each name wraps to. */}
              <div className="flex flex-col gap-2.5 p-4 pb-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue-text">
                    <Table2 size={18} strokeWidth={1.75} />
                  </div>
                  <Badge variant={statusVariant(boq.status)} size="sm" dot>{statusLabel(boq.status)}</Badge>
                </div>

                <div>
                  <h3
                    className="text-sm font-semibold leading-snug text-content-primary line-clamp-2"
                    title={boq.name}
                  >
                    {boq.name}
                  </h3>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-content-tertiary">
                    <span className="max-w-[55%] truncate">{boq.projectName}</span>
                    <FileTypeChips
                      fileTypes={fileTypesByProject?.[boq.project_id]}
                      size="xs"
                    />
                  </div>
                </div>
              </div>

              {/* Money + actions form one bottom summary zone, split from the
                  identity block by a single hairline. `mt-auto` pins the zone
                  to the card bottom, so the breathing room on a short card
                  falls above the rule and reads as deliberate. */}
              <div className="mt-auto border-t border-border-light px-4 pb-2 pt-3">
                <div className="text-xl font-bold leading-none text-content-primary tabular-nums">
                  {currencyFmt.format(boq.grandTotal)}
                  <span className="ml-1 text-xs font-medium text-content-tertiary">{boq.currency}</span>
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-2xs text-content-tertiary">
                  <span className="tabular-nums">
                    {boq.positionCount} {t('boq.positions_short', { defaultValue: 'pos.' })}
                  </span>
                  <span aria-hidden>·</span>
                  <span className="inline-flex items-center gap-1">
                    <CalendarDays size={11} />
                    {/* All-numeric so a de-DE reader sees 14.03.2026, matching
                        the tendering cards (PLAN fixes the numeric form). */}
                    <DateDisplay value={boq.created_at} format="numeric" />
                  </span>
                  {isCollabEnabled && (
                    <span className="ml-auto"><PresenceAvatars boqId={boq.id} /></span>
                  )}
                </div>
              </div>

              {/* Footer action bar — flows directly under the total in the
                  same bottom zone (no second rule), so the summary reads as one
                  block rather than two stacked strips. */}
              <div className="flex items-center justify-between gap-1 px-2.5 pb-2.5 pt-1">
                {confirmDeleteId === boq.id ? (
                  <div className="flex w-full items-center justify-between gap-1" onClick={(e) => e.stopPropagation()}>
                    <span className="pl-1 text-2xs text-content-tertiary">
                      {t('boq.delete_confirm_q', { defaultValue: 'Delete?' })}
                    </span>
                    <div className="flex items-center gap-1">
                      <Button variant="danger" size="sm" onClick={() => deleteMutation.mutate(boq.id)} loading={deleteMutation.isPending}>
                        {t('common.delete')}
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => setConfirmDeleteId(null)}>
                        {t('common.cancel')}
                      </Button>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="flex items-center gap-0.5">
                      <button
                        onClick={(e) => { e.stopPropagation(); handleCompareClick(boq.id, boq.currency); }}
                        className={`flex h-7 w-7 items-center justify-center rounded-md transition-all ${
                          selectedForCompare?.id === boq.id
                            ? 'text-oe-blue-text bg-oe-blue-subtle'
                            : 'text-content-tertiary hover:text-oe-blue-text hover:bg-oe-blue-subtle'
                        }`}
                        title={
                          compareMode && selectedForCompare?.id === boq.id
                            ? t('boq.compare_selected', { defaultValue: 'Selected for comparison' })
                            : t('boq.compare', { defaultValue: 'Compare' })
                        }
                      >
                        <GitCompareArrows size={13} />
                      </button>

                      {/* CONN-34: build a 4D schedule straight from this BOQ. */}
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          navigate(
                            `/schedule?project_id=${encodeURIComponent(boq.project_id)}&generateBoqId=${encodeURIComponent(boq.id)}`,
                          );
                        }}
                        className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-oe-blue-text hover:bg-oe-blue-subtle transition-all"
                        title={t('boq.build_schedule', { defaultValue: 'Build schedule from this BOQ' })}
                      >
                        <CalendarDays size={13} />
                      </button>

                      <button
                        onClick={(e) => { e.stopPropagation(); duplicateMutation.mutate(boq.id); }}
                        disabled={duplicateMutation.isPending}
                        className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-oe-blue-text hover:bg-oe-blue-subtle transition-all disabled:opacity-40"
                        title={t('boq.duplicate', { defaultValue: 'Duplicate' })}
                      >
                        <Copy size={13} />
                      </button>

                      <button
                        onClick={(e) => { e.stopPropagation(); setConfirmDeleteId(boq.id); }}
                        className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-semantic-error hover:bg-semantic-error-bg transition-all"
                        title={t('common.delete')}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>

                    {/* Open affordance — appears on hover so the card reads as
                        clickable without adding permanent clutter. */}
                    <span className="inline-flex items-center gap-1 pr-1 text-2xs font-semibold text-oe-blue-text opacity-0 transition-opacity group-hover:opacity-100">
                      {t('boq.open', { defaultValue: 'Open' })}
                      <ArrowRight size={13} />
                    </span>
                  </>
                )}
              </div>
            </Card>
          ))}
          </div>

          {/* Pagination */}
          <div className="flex flex-col items-center gap-3">
            {totalPages > 1 && (
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPage(1)}
                  disabled={page === 1}
                  className="rounded-lg border border-border-light px-3 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  title={t('common.first_page', { defaultValue: 'First page' })}
                >
                  &laquo;
                </button>
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="rounded-lg border border-border-light px-4 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  {t('common.previous', { defaultValue: 'Previous' })}
                </button>

                {/* Page numbers */}
                {Array.from({ length: totalPages }, (_, i) => i + 1)
                  .filter((p) => p === 1 || p === totalPages || Math.abs(p - page) <= 1)
                  .reduce<(number | 'dots')[]>((acc, p, i, arr) => {
                    if (i > 0 && arr[i - 1] !== undefined && p - (arr[i - 1] as number) > 1) acc.push('dots');
                    acc.push(p);
                    return acc;
                  }, [])
                  .map((item, i) =>
                    item === 'dots' ? (
                      <span key={`dots-${i}`} className="px-1 text-content-quaternary">...</span>
                    ) : (
                      <button
                        key={item}
                        onClick={() => setPage(item as number)}
                        className={`rounded-lg min-w-[40px] py-2 text-sm font-semibold transition-colors ${
                          page === item
                            ? 'bg-oe-blue text-white shadow-sm'
                            : 'border border-border-light text-content-secondary hover:bg-surface-secondary'
                        }`}
                      >
                        {item}
                      </button>
                    ),
                  )}

                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="rounded-lg border border-border-light px-4 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                >
                  {t('common.next', { defaultValue: 'Next' })}
                </button>
                <button
                  onClick={() => setPage(totalPages)}
                  disabled={page === totalPages}
                  className="rounded-lg border border-border-light px-3 py-2 text-sm font-medium text-content-secondary hover:bg-surface-secondary disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                  title={t('common.last_page', { defaultValue: 'Last page' })}
                >
                  &raquo;
                </button>
              </div>
            )}

            {/* Summary footer */}
            <p className="text-sm text-content-tertiary">
              {t('boq.pagination_range', { defaultValue: '{{from}}–{{to}} of {{total}} estimates', from: (page - 1) * ITEMS_PER_PAGE + 1, to: Math.min(page * ITEMS_PER_PAGE, filtered.length), total: filtered.length })}
              {(searchQuery || statusFilter || userProjectFilter) && filtered.length !== (allBoqs?.length ?? 0)
                ? ` (${t('boq.filtered_from', { defaultValue: 'filtered from {{total}}', total: allBoqs?.length ?? 0 })})`
                : ''}
            </p>
          </div>
        </div>
      )}

      {/* Compare modal */}
      {compareTarget && (
        <CompareModal
          boqIdA={compareTarget.idA}
          boqIdB={compareTarget.idB}
          currencyA={compareTarget.currencyA}
          currencyB={compareTarget.currencyB}
          onClose={exitCompareMode}
        />
      )}

      {/* Create BOQ modal */}
      <CreateBOQModal
        open={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
        defaultProjectId={createModalProjectId}
      />
    </div>
  );
}
