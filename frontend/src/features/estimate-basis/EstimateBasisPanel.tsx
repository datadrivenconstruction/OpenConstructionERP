// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Basis-of-estimate panel.
//
// The page answers one question: how firm is this number, what is it built
// from, and what would change it. It reads top to bottom in that order.
//
//   1. The figure the document qualifies, its accuracy class and the range that
//      follows from it. The class is the estimator's; the platform suggests one
//      from the evidence and shows its reasoning.
//   2. Where the numbers came from - measured, imported, catalogue-priced or
//      typed - and the coverage of trades behind them.
//   3. The two judgements no derivation can make: market conditions and the
//      reason the contingency is the size it is.
//   4. The qualification lists themselves, drafted from the estimate and
//      editable line by line.
//
// Everything above the lists is derived on generate and never retyped, because
// a basis of estimate that has to be maintained by hand goes stale, and a stale
// one is worse than none.

import { Fragment, useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import {
  AlertTriangle,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  ClipboardList,
  Download,
  FileText,
  History,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  Send,
  ShieldCheck,
  Square,
  Trash2,
} from 'lucide-react';
import { Badge, Button, Card, CardContent, CardHeader, EmptyState, ErrorState } from '@/shared/ui';
import { getErrorMessage, triggerDownload } from '@/shared/lib/api';
import { formatCurrency } from '@/shared/lib/money';
import { BasisHeadline } from './BasisHeadline';
import { BasisProvenance } from './BasisProvenance';
import {
  generateBasis,
  getBasis,
  listBasis,
  listEstimateClasses,
  updateBasis,
  type CoverageSummary,
  type EstimateBasisDocument,
  type EstimateBasisSummary,
  type QualificationCategory,
  type QualificationItem,
} from './api';
import {
  basisFilename,
  makeItemId,
  newManualItem,
  parseAccuracyPct,
  renderBasisMarkdown,
  type MarkdownLabels,
} from './parts';

export interface EstimateBasisPanelProps {
  /** Project whose estimate the basis is drafted from. */
  projectId: string;
  /** Optionally scope the derivation to a single BOQ. */
  boqId?: string | null;
  /** ISO currency code, woven into the money assumption and used for display. */
  currency?: string;
  /** Optional base date, woven into the escalation assumption. */
  baseDate?: string | null;
}

interface Draft {
  title: string;
  status: string;
  notes: string;
  inclusions: QualificationItem[];
  exclusions: QualificationItem[];
  assumptions: QualificationItem[];
  /** The AACE class the estimator has stated. `null` = nobody has stated one. */
  estimateClass: number | null;
  accuracyLowPct: string;
  accuracyHighPct: string;
  marketConditions: string;
  contingencyRationale: string;
}

function draftFromDoc(doc: EstimateBasisDocument): Draft {
  return {
    title: doc.title,
    status: doc.status,
    notes: doc.notes ?? '',
    inclusions: doc.inclusions ?? [],
    exclusions: doc.exclusions ?? [],
    assumptions: doc.assumptions ?? [],
    estimateClass: doc.estimate_class ?? null,
    accuracyLowPct: doc.accuracy_low_pct ?? '',
    accuracyHighPct: doc.accuracy_high_pct ?? '',
    marketConditions: doc.market_conditions ?? '',
    contingencyRationale: doc.contingency_rationale ?? '',
  };
}

/**
 * Merge the editable draft back over the loaded document for export.
 *
 * The two carry the same facts under different names (the draft is camelCase
 * local state), so a plain spread would leave the server's snake_case fields
 * holding the pre-edit values and the exported document would disagree with the
 * screen it was exported from.
 */
function documentForExport(loaded: EstimateBasisDocument, draft: Draft): EstimateBasisDocument {
  return {
    ...loaded,
    title: draft.title,
    status: draft.status,
    notes: draft.notes,
    inclusions: draft.inclusions,
    exclusions: draft.exclusions,
    assumptions: draft.assumptions,
    estimate_class: draft.estimateClass,
    accuracy_low_pct: draft.accuracyLowPct,
    accuracy_high_pct: draft.accuracyHighPct,
    market_conditions: draft.marketConditions,
    contingency_rationale: draft.contingencyRationale,
  };
}

const CATEGORY_KEYS = ['inclusions', 'exclusions', 'assumptions'] as const;
type CategoryKey = (typeof CATEGORY_KEYS)[number];

const CATEGORY_OF: Record<CategoryKey, QualificationCategory> = {
  inclusions: 'inclusion',
  exclusions: 'exclusion',
  assumptions: 'assumption',
};

export function EstimateBasisPanel({ projectId, boqId, currency, baseDate }: EstimateBasisPanelProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [dirty, setDirty] = useState(false);
  /** OC-09: timestamp of last successful save, drives the "Saved" indicator. */
  const [savedAt, setSavedAt] = useState<number | null>(null);

  // OC-09: warn on page close/refresh with unsaved changes.
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => { e.preventDefault(); };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [dirty]);

  const listQuery = useQuery({
    queryKey: ['estimate-basis', 'list', projectId],
    queryFn: () => listBasis(projectId),
    enabled: projectId.length > 0,
  });

  // Default the selection to the newest document once the list arrives.
  const newestId = listQuery.data?.items[0]?.id ?? null;
  useEffect(() => {
    if (selectedId === null && newestId) setSelectedId(newestId);
  }, [newestId, selectedId]);

  const docQuery = useQuery({
    queryKey: ['estimate-basis', 'doc', selectedId],
    queryFn: () => getBasis(selectedId as string),
    enabled: !!selectedId,
  });

  // The class table is a published standard, not project data: fetched once and
  // kept, so the selector never hardcodes a standard's accuracy ranges.
  const classesQuery = useQuery({
    queryKey: ['estimate-basis', 'classes'],
    queryFn: listEstimateClasses,
    staleTime: Infinity,
  });

  const loaded = docQuery.data;
  // Re-seed the editable draft whenever a different revision loads.
  useEffect(() => {
    if (loaded) {
      setDraft(draftFromDoc(loaded));
      setDirty(false);
    }
  }, [loaded?.id, loaded?.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps

  const generateMutation = useMutation({
    mutationFn: () =>
      generateBasis({
        project_id: projectId,
        boq_id: boqId ?? null,
        currency: currency ?? '',
        base_date: baseDate ?? null,
      }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['estimate-basis', 'list', projectId] });
      queryClient.setQueryData(['estimate-basis', 'doc', created.id], created);
      setSelectedId(created.id);
      setDraft(draftFromDoc(created));
      setDirty(false);
    },
  });

  const saveMutation = useMutation({
    mutationFn: () => {
      if (!selectedId || !draft) throw new Error('nothing to save');
      return updateBasis(selectedId, {
        title: draft.title,
        status: draft.status === 'final' ? 'final' : 'draft',
        notes: draft.notes,
        inclusions: draft.inclusions,
        exclusions: draft.exclusions,
        assumptions: draft.assumptions,
        // 0 is how the API is told to unstate the class; omitting it would mean
        // "leave it alone", which is the one thing clearing it must not do.
        estimate_class: draft.estimateClass ?? 0,
        accuracy_low_pct: draft.accuracyLowPct,
        accuracy_high_pct: draft.accuracyHighPct,
        market_conditions: draft.marketConditions,
        contingency_rationale: draft.contingencyRationale,
      });
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(['estimate-basis', 'doc', updated.id], updated);
      queryClient.invalidateQueries({ queryKey: ['estimate-basis', 'list', projectId] });
      setDraft(draftFromDoc(updated));
      setDirty(false);
      setSavedAt(Date.now());
    },
  });

  // ── Draft mutations ────────────────────────────────────────────────────────

  function patchItems(key: CategoryKey, next: QualificationItem[]) {
    setDraft((prev) => (prev ? { ...prev, [key]: next } : prev));
    setDirty(true);
  }

  function updateItemText(key: CategoryKey, id: string, text: string) {
    if (!draft) return;
    patchItems(
      key,
      draft[key].map((it) => (it.id === id ? { ...it, text } : it)),
    );
  }

  function toggleItem(key: CategoryKey, id: string) {
    if (!draft) return;
    patchItems(
      key,
      draft[key].map((it) => (it.id === id ? { ...it, enabled: !it.enabled } : it)),
    );
  }

  /** OC-08: bulk toggle all auto-generated (template) items in a section. */
  function toggleAllAuto(key: CategoryKey, enabled: boolean) {
    if (!draft) return;
    patchItems(
      key,
      draft[key].map((it) => (it.source === 'auto' ? { ...it, enabled } : it)),
    );
  }

  function removeItem(key: CategoryKey, id: string) {
    if (!draft) return;
    patchItems(
      key,
      draft[key].filter((it) => it.id !== id),
    );
  }

  function addItem(key: CategoryKey) {
    if (!draft) return;
    patchItems(key, [...draft[key], newManualItem(CATEGORY_OF[key], makeItemId())]);
  }

  function setTitle(title: string) {
    setDraft((prev) => (prev ? { ...prev, title } : prev));
    setDirty(true);
  }

  function setNotes(notes: string) {
    setDraft((prev) => (prev ? { ...prev, notes } : prev));
    setDirty(true);
  }

  function toggleFinal() {
    setDraft((prev) => (prev ? { ...prev, status: prev.status === 'final' ? 'draft' : 'final' } : prev));
    setDirty(true);
  }

  function setJudgement(field: 'marketConditions' | 'contingencyRationale', value: string) {
    setDraft((prev) => (prev ? { ...prev, [field]: value } : prev));
    setDirty(true);
  }

  /**
   * State, change or clear the accuracy class.
   *
   * Picking a class seeds its published accuracy band straight away, so the
   * range on screen moves with the choice instead of waiting for a save. The
   * server seeds the same band on its side; doing it here as well is what makes
   * the decision one click rather than three.
   */
  function setEstimateClass(next: number) {
    const option = classesQuery.data?.items.find((o) => o.estimate_class === next);
    setDraft((prev) => {
      if (!prev) return prev;
      if (next <= 0) {
        return { ...prev, estimateClass: null, accuracyLowPct: '', accuracyHighPct: '' };
      }
      return {
        ...prev,
        estimateClass: next,
        accuracyLowPct: option ? parseAccuracyPct(option.accuracy_low) : prev.accuracyLowPct,
        accuracyHighPct: option ? parseAccuracyPct(option.accuracy_high) : prev.accuracyHighPct,
      };
    });
    setDirty(true);
  }

  function setBand(bound: 'low' | 'high', value: string) {
    setDraft((prev) =>
      prev ? { ...prev, [bound === 'low' ? 'accuracyLowPct' : 'accuracyHighPct']: value } : prev,
    );
    setDirty(true);
  }

  function onExport() {
    if (!loaded || !draft) return;
    const labels: MarkdownLabels = {
      inclusions: t('estimateBasis.section.inclusions', { defaultValue: 'Inclusions' }),
      exclusions: t('estimateBasis.section.exclusions', { defaultValue: 'Exclusions' }),
      assumptions: t('estimateBasis.section.assumptions', { defaultValue: 'Assumptions' }),
      notes: t('estimateBasis.section.notes', { defaultValue: 'Notes' }),
      none: t('estimateBasis.none', { defaultValue: 'None.' }),
      status: t('estimateBasis.meta.status', { defaultValue: 'Status' }),
      generated: t('estimateBasis.meta.generated', { defaultValue: 'Generated' }),
      estimate: t('estimateBasis.export.estimate', { defaultValue: 'The estimate' }),
      total: t('estimateBasis.headline.total', { defaultValue: 'Estimate total' }),
      directCost: t('estimateBasis.headline.directCost', { defaultValue: 'Direct cost' }),
      markups: t('estimateBasis.headline.markups', { defaultValue: 'Markups' }),
      estimateClass: t('estimateBasis.export.estimateClass', { defaultValue: 'Estimate class' }),
      classNotStated: t('estimateBasis.headline.classNotStated', { defaultValue: 'Not stated' }),
      expectedRange: t('estimateBasis.headline.expectedRange', { defaultValue: 'Expected range' }),
      rangeTo: t('estimateBasis.headline.rangeTo', { defaultValue: 'to' }),
      pricedAt: t('estimateBasis.export.pricedAt', { defaultValue: 'Prices current as of' }),
      provenance: t('estimateBasis.provenance.title', {
        defaultValue: 'Where the numbers came from',
      }),
      shareOfValue: t('estimateBasis.export.shareOfValue', { defaultValue: 'Share of value' }),
      shareOfLines: t('estimateBasis.export.shareOfLines', { defaultValue: 'Share of line items' }),
      familyMeasured: t('estimateBasis.provenance.family.measured', {
        defaultValue: 'Measured from a drawing or model',
      }),
      familyImported: t('estimateBasis.provenance.family.imported', {
        defaultValue: 'Imported from a supplied bill',
      }),
      familyCatalogue: t('estimateBasis.provenance.family.catalogue', {
        defaultValue: 'From a cost database or assembly',
      }),
      familyManual: t('estimateBasis.provenance.family.manual', { defaultValue: 'Entered by hand' }),
      marketConditions: t('estimateBasis.judgement.market', { defaultValue: 'Market conditions' }),
      contingencyRationale: t('estimateBasis.judgement.contingency', {
        defaultValue: 'Contingency rationale',
      }),
    };
    // Export exactly what the estimator is looking at (their unsaved edits too).
    const md = renderBasisMarkdown(documentForExport(loaded, draft), labels);
    triggerDownload(new Blob([md], { type: 'text/markdown;charset=utf-8;' }), basisFilename(draft.title));
  }

  const generating = generateMutation.isPending;
  const hasDocuments = (listQuery.data?.items.length ?? 0) > 0;

  // ── Render ───────────────────────────────────────────────────────────────

  if (listQuery.isError) {
    return <ErrorState title={getErrorMessage(listQuery.error)} onRetry={() => listQuery.refetch()} />;
  }

  // Initial fetch: show a loader so the panel is never a bare header with
  // disabled buttons while the document list is still on the wire.
  if (listQuery.isLoading && !hasDocuments) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-border-light px-3 py-4 text-sm text-content-tertiary">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        {t('estimateBasis.loadingList', { defaultValue: 'Loading basis of estimate...' })}
      </div>
    );
  }

  if (!hasDocuments && !generating && !listQuery.isLoading) {
    return (
      <EmptyState
        icon={<FileText className="h-6 w-6" aria-hidden />}
        title={t('estimateBasis.empty.title', { defaultValue: 'No basis of estimate yet' })}
        description={t('estimateBasis.empty.body', {
          defaultValue:
            'Draft the inclusions, exclusions and assumptions automatically from the estimate contents.',
        })}
        action={
          <Button onClick={() => generateMutation.mutate()} disabled={generating}>
            {t('estimateBasis.generate', { defaultValue: 'Draft basis of estimate' })}
          </Button>
        }
      />
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <FileText className="h-5 w-5 text-content-tertiary" aria-hidden />
          <h2 className="text-lg font-semibold text-content-primary">
            {t('estimateBasis.heading', { defaultValue: 'Basis of estimate' })}
          </h2>
          {draft && (
            <Badge variant={draft.status === 'final' ? 'success' : 'neutral'}>
              {draft.status === 'final'
                ? t('estimateBasis.status.final', { defaultValue: 'Final' })
                : t('estimateBasis.status.draft', { defaultValue: 'Draft' })}
            </Badge>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            onClick={() => generateMutation.mutate()}
            disabled={generating}
            icon={
              generating ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <RefreshCw className="h-4 w-4" aria-hidden />
              )
            }
          >
            {hasDocuments
              ? t('estimateBasis.regenerate', { defaultValue: 'Regenerate' })
              : t('estimateBasis.generate', { defaultValue: 'Draft basis of estimate' })}
          </Button>
          <Button
            variant="secondary"
            onClick={onExport}
            disabled={!draft}
            icon={<Download className="h-4 w-4" aria-hidden />}
          >
            {t('estimateBasis.export', { defaultValue: 'Export' })}
          </Button>
          <Button
            variant="secondary"
            onClick={() => navigate('/tendering')}
            icon={<Send className="h-4 w-4" aria-hidden />}
          >
            {t('estimateBasis.openTendering', { defaultValue: 'Open Tendering' })}
          </Button>
          <Button
            onClick={() => saveMutation.mutate()}
            disabled={!dirty || saveMutation.isPending}
            icon={
              saveMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Save className="h-4 w-4" aria-hidden />
              )
            }
          >
            {t('estimateBasis.save', { defaultValue: 'Save' })}
          </Button>
          {/* OC-09: brief "Saved" confirmation after a successful save. */}
          {savedAt && !dirty && !saveMutation.isPending && (
            <span className="flex items-center gap-1 text-xs text-semantic-success transition-opacity duration-300">
              <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
              {t('estimateBasis.saved', { defaultValue: 'Saved' })}
            </span>
          )}
        </div>
      </div>

      {generateMutation.isError && (
        <ErrorState title={getErrorMessage(generateMutation.error)} onRetry={() => generateMutation.mutate()} />
      )}
      {saveMutation.isError && <ErrorState title={getErrorMessage(saveMutation.error)} />}

      {(docQuery.isLoading || (generating && !draft)) && (
        <div className="flex items-center gap-2 rounded-lg border border-border-light px-3 py-4 text-sm text-content-tertiary">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          {generating
            ? t('estimateBasis.drafting', { defaultValue: 'Drafting basis of estimate...' })
            : t('estimateBasis.loading', { defaultValue: 'Loading basis of estimate...' })}
        </div>
      )}
      {docQuery.isError && (
        <ErrorState title={getErrorMessage(docQuery.error)} onRetry={() => docQuery.refetch()} />
      )}

      {loaded && draft && (
        <div className="space-y-4">
          <input
            aria-label={t('estimateBasis.titleLabel', { defaultValue: 'Document title' })}
            value={draft.title}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm font-medium text-content-primary"
          />

          <VersionPicker
            items={listQuery.data?.items ?? []}
            selectedId={selectedId}
            onSelect={setSelectedId}
            dirty={dirty}
          />

          {/* 1. The number, and how firm it is. */}
          <BasisHeadline
            doc={loaded}
            classes={classesQuery.data?.items ?? []}
            estimateClass={draft.estimateClass}
            accuracyLowPct={draft.accuracyLowPct}
            accuracyHighPct={draft.accuracyHighPct}
            onClassChange={setEstimateClass}
            onBandChange={setBand}
          />

          {/* 2. What it was built from. */}
          <BasisProvenance
            provenance={loaded.provenance}
            currency={loaded.currency || currency}
            boqHref={boqId ? `/boq/${boqId}` : '/boq'}
          />
          <CoverageStrip coverage={loaded.coverage} currency={loaded.currency || currency} boqId={boqId} />

          {/* 3. The judgements no derivation can make. */}
          <Card>
            <CardHeader
              title={
                <span className="text-sm font-semibold text-content-primary">
                  {t('estimateBasis.judgement.title', { defaultValue: 'Your judgement' })}
                </span>
              }
            />
            <CardContent className="space-y-3">
              <p className="text-xs text-content-tertiary">
                {t('estimateBasis.judgement.intro', {
                  defaultValue:
                    'Everything above is read from the estimate. These two are not derivable from it, and they are the first thing a reviewing cost manager reads.',
                })}
              </p>
              <JudgementField
                id="estimate-basis-market"
                label={t('estimateBasis.judgement.market', { defaultValue: 'Market conditions' })}
                hint={t('estimateBasis.judgement.marketHint', {
                  defaultValue:
                    'What the market was doing when this was priced: competition, supply chain, whether the rates were market-tested.',
                })}
                value={draft.marketConditions}
                onChange={(v) => setJudgement('marketConditions', v)}
              />
              <JudgementField
                id="estimate-basis-contingency"
                label={t('estimateBasis.judgement.contingency', { defaultValue: 'Contingency rationale' })}
                hint={t('estimateBasis.judgement.contingencyHint', {
                  defaultValue:
                    'Why the contingency is the size it is, and what would have to happen for it to move.',
                })}
                value={draft.contingencyRationale}
                onChange={(v) => setJudgement('contingencyRationale', v)}
              />
            </CardContent>
          </Card>

          {/* 4. The qualification lists. */}
          {CATEGORY_KEYS.map((key) => (
            <Section
              key={key}
              heading={t(`estimateBasis.section.${CATEGORY_OF[key]}s`, {
                defaultValue:
                  key === 'inclusions' ? 'Inclusions' : key === 'exclusions' ? 'Exclusions' : 'Assumptions',
              })}
              items={draft[key]}
              onToggle={(id) => toggleItem(key, id)}
              onText={(id, text) => updateItemText(key, id, text)}
              onRemove={(id) => removeItem(key, id)}
              onAdd={() => addItem(key)}
              onToggleAllAuto={(enabled) => toggleAllAuto(key, enabled)}
              addLabel={t('estimateBasis.addLine', { defaultValue: 'Add line' })}
              emptyLabel={t('estimateBasis.sectionEmpty', { defaultValue: 'No lines yet.' })}
            />
          ))}

          <div>
            <label
              htmlFor="estimate-basis-notes"
              className="mb-1.5 block text-sm font-medium text-content-primary"
            >
              {t('estimateBasis.section.notes', { defaultValue: 'Notes' })}
            </label>
            <textarea
              id="estimate-basis-notes"
              value={draft.notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              placeholder={t('estimateBasis.notesPlaceholder', {
                defaultValue: 'Any additional qualification for the client...',
              })}
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary"
            />
          </div>

          <div className="flex items-center justify-between">
            <Button variant="ghost" onClick={toggleFinal}>
              {draft.status === 'final'
                ? t('estimateBasis.reopen', { defaultValue: 'Reopen as draft' })
                : t('estimateBasis.markFinal', { defaultValue: 'Mark as final' })}
            </Button>
            {dirty && (
              <span className="text-xs text-content-tertiary">
                {t('estimateBasis.unsaved', { defaultValue: 'Unsaved changes' })}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Version picker ───────────────────────────────────────────────────────────

/**
 * The document's own history, which the module keeps and the page never showed.
 *
 * Regenerating never overwrites: every draft is a new row, so a project that has
 * been through concept, tender and a current re-estimate carries three
 * documents. Before this the panel silently opened the newest and the other two
 * were unreachable from the screen, which is a poor way to treat the record a
 * client's approval was given against.
 */
function VersionPicker({
  items,
  selectedId,
  onSelect,
  dirty,
}: {
  items: EstimateBasisSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  dirty: boolean;
}) {
  const { t } = useTranslation();
  if (items.length < 2) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2">
      <span className="flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-content-tertiary">
        <History className="h-3.5 w-3.5" aria-hidden />
        {t('estimateBasis.versions.label', { defaultValue: 'Versions' })}
      </span>
      {items.map((item) => {
        const active = item.id === selectedId;
        return (
          <button
            key={item.id}
            type="button"
            onClick={() => onSelect(item.id)}
            aria-current={active ? 'true' : undefined}
            className={`rounded-full border px-2.5 py-0.5 text-xs transition-colors ${
              active
                ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text'
                : 'border-border-light bg-surface-primary text-content-secondary hover:border-oe-blue'
            }`}
          >
            {item.title}
            {item.estimate_class !== null && (
              <span className="ml-1 text-content-tertiary">
                {t('estimateBasis.versions.class', { defaultValue: 'cl. {{n}}', n: item.estimate_class })}
              </span>
            )}
          </button>
        );
      })}
      {dirty && (
        <span className="text-2xs text-semantic-warning">
          {t('estimateBasis.versions.dirtyWarning', {
            defaultValue: 'Switching version discards unsaved changes.',
          })}
        </span>
      )}
    </div>
  );
}

// ── Judgement field ──────────────────────────────────────────────────────────

/** A labelled paragraph the estimator writes, with the prompt that earns it. */
function JudgementField({
  id,
  label,
  hint,
  value,
  onChange,
}: {
  id: string;
  label: string;
  hint: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-content-primary">
        {label}
      </label>
      <p className="mb-1.5 text-2xs text-content-tertiary">{hint}</p>
      <textarea
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        placeholder={hint}
        className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary"
      />
    </div>
  );
}

// ── Coverage strip ───────────────────────────────────────────────────────────

function CoverageStrip({
  coverage,
  currency,
  boqId,
}: {
  coverage: CoverageSummary;
  currency?: string;
  boqId?: string | null;
}) {
  const { t } = useTranslation();
  // A coverage gap should be one click from where it gets fixed: the bill of
  // quantities. Deep-link to the scoped BOQ when we have its id, else the list.
  const boqHref = boqId ? `/boq/${boqId}` : '/boq';
  const openBoqTitle = t('estimateBasis.coverage.openBoq', {
    defaultValue: 'Open in the bill of quantities',
  });
  const flags = useMemo(() => {
    const parts: string[] = [];
    if (coverage.zero_rate_positions > 0)
      parts.push(t('estimateBasis.flag.unpriced', { defaultValue: '{{n}} unpriced', n: coverage.zero_rate_positions }));
    if (coverage.missing_quantity_positions > 0)
      parts.push(
        t('estimateBasis.flag.missingQty', {
          defaultValue: '{{n}} missing qty',
          n: coverage.missing_quantity_positions,
        }),
      );
    if (coverage.provisional_positions > 0)
      parts.push(
        t('estimateBasis.flag.provisional', {
          defaultValue: '{{n}} provisional',
          n: coverage.provisional_positions,
        }),
      );
    if (coverage.unclassified_positions > 0)
      parts.push(
        t('estimateBasis.flag.unclassified', {
          defaultValue: '{{n}} unclassified',
          n: coverage.unclassified_positions,
        }),
      );
    return parts;
  }, [coverage, t]);

  return (
    <Card>
      <CardHeader
        title={t('estimateBasis.coverage.title', {
          defaultValue: 'Coverage · {{count}} items',
          count: coverage.total_positions,
        })}
      />
      <CardContent className="space-y-3">
        <div>
          <div className="mb-1 text-xs font-medium uppercase tracking-wide text-content-tertiary">
            {t('estimateBasis.coverage.present', { defaultValue: 'Trades present' })}
          </div>
          {coverage.present_trades.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {coverage.present_trades.map((tr) => (
                <Link
                  key={tr.code}
                  to={boqHref}
                  title={openBoqTitle}
                  className="inline-flex items-center gap-1 rounded-full border border-border-light bg-surface-secondary px-2 py-0.5 text-xs text-content-secondary transition-colors hover:border-oe-blue hover:bg-oe-blue-subtle hover:text-oe-blue-text"
                >
                  <span className="font-medium text-content-primary">{tr.label}</span>
                  <span className="text-content-tertiary">· {tr.position_count}</span>
                  <span className="tabular-nums">· {formatCurrency(tr.total, currency)}</span>
                </Link>
              ))}
            </div>
          ) : (
            <span className="text-xs text-content-tertiary">
              {t('estimateBasis.coverage.noTrades', { defaultValue: 'No classified trades' })}
            </span>
          )}
        </div>

        {coverage.absent_trades.length > 0 && (
          <div>
            <div className="mb-1 flex items-center gap-1 text-xs font-medium uppercase tracking-wide text-content-tertiary">
              <AlertTriangle className="h-3.5 w-3.5 text-semantic-warning" aria-hidden />
              {t('estimateBasis.coverage.absent', { defaultValue: 'Expected trades not found' })}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {coverage.absent_trades.map((tr) => (
                <Link
                  key={tr.code}
                  to={boqHref}
                  title={openBoqTitle}
                  className="rounded-full border border-semantic-warning/30 bg-semantic-warning/10 px-2 py-0.5 text-xs text-content-secondary transition-colors hover:border-semantic-warning hover:bg-semantic-warning/20"
                >
                  {tr.label}
                </Link>
              ))}
            </div>
          </div>
        )}

        {flags.length > 0 && (
          <div className="flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs text-content-tertiary">
            <span>{t('estimateBasis.coverage.flags', { defaultValue: 'Flags' })}:</span>
            {flags.map((f, i) => (
              <Fragment key={f}>
                {i > 0 && (
                  <span aria-hidden className="text-content-quaternary">
                    ·
                  </span>
                )}
                <Link
                  to={boqHref}
                  title={openBoqTitle}
                  className="rounded text-oe-blue-text underline-offset-2 hover:underline"
                >
                  {f}
                </Link>
              </Fragment>
            ))}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-border-light pt-3 text-xs">
          <Link
            to={boqHref}
            className="inline-flex items-center gap-1 font-medium text-oe-blue-text hover:underline"
          >
            <ClipboardList className="h-3.5 w-3.5" aria-hidden />
            {openBoqTitle}
          </Link>
          <Link
            to="/validation"
            className="inline-flex items-center gap-1 font-medium text-oe-blue-text hover:underline"
          >
            <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
            {t('estimateBasis.coverage.reviewValidation', { defaultValue: 'Review in Validation' })}
          </Link>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Section editor ───────────────────────────────────────────────────────────

interface SectionProps {
  heading: string;
  items: QualificationItem[];
  onToggle: (id: string) => void;
  onText: (id: string, text: string) => void;
  onRemove: (id: string) => void;
  onAdd: () => void;
  /** OC-08: bulk enable/disable all auto-generated items. */
  onToggleAllAuto: (enabled: boolean) => void;
  addLabel: string;
  emptyLabel: string;
}

function Section({
  heading,
  items,
  onToggle,
  onText,
  onRemove,
  onAdd,
  onToggleAllAuto,
  addLabel,
  emptyLabel,
}: SectionProps) {
  const { t } = useTranslation();
  // Open by default: these lists ARE the document, and a reader who has to
  // discover them behind a chevron will decide the page has nothing in it. The
  // fold exists so somebody working on one section can put the other two away,
  // not so the page can look tidy on arrival.
  const [open, setOpen] = useState(true);
  const enabledCount = items.filter((it) => it.enabled).length;
  const autoItems = items.filter((it) => it.source === 'auto');
  const autoEnabledCount = autoItems.filter((it) => it.enabled).length;
  const hasAuto = autoItems.length > 0;
  const allAutoEnabled = autoEnabledCount === autoItems.length;

  return (
    <Card>
      <CardHeader
        title={
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            className="flex items-center gap-1.5 text-sm font-semibold text-content-primary"
          >
            {open ? (
              <ChevronDown className="h-4 w-4 text-content-tertiary" aria-hidden />
            ) : (
              <ChevronRight className="h-4 w-4 text-content-tertiary" aria-hidden />
            )}
            {heading}{' '}
            <span className="font-normal text-content-tertiary">
              {enabledCount === items.length
                ? t('estimateBasis.sectionCount', { defaultValue: '{{count}} lines', count: items.length })
                : t('estimateBasis.sectionCountPartial', {
                    defaultValue: '{{on}} of {{total}} lines included',
                    on: enabledCount,
                    total: items.length,
                  })}
            </span>
          </button>
        }
        action={
          <div className="flex items-center gap-1">
            {hasAuto && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onToggleAllAuto(!allAutoEnabled)}
                icon={allAutoEnabled
                  ? <CheckSquare className="h-4 w-4" aria-hidden />
                  : <Square className="h-4 w-4" aria-hidden />
                }
              >
                {allAutoEnabled
                  ? t('estimateBasis.uncheckTemplate', { defaultValue: 'Uncheck template' })
                  : t('estimateBasis.checkTemplate', { defaultValue: 'Check template' })}
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={onAdd} icon={<Plus className="h-4 w-4" aria-hidden />}>
              {addLabel}
            </Button>
          </div>
        }
      />
      <CardContent className={`space-y-2 ${open ? '' : 'hidden'}`}>
        {items.length === 0 && <p className="text-sm text-content-tertiary">{emptyLabel}</p>}
        {items.map((it) => (
          <div key={it.id} className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={it.enabled}
              onChange={() => onToggle(it.id)}
              className="mt-2 h-4 w-4 shrink-0 rounded border-border-light"
              aria-label={t('estimateBasis.includeLine', {
                defaultValue: 'Include this line in the export',
              })}
            />
            <textarea
              value={it.text}
              onChange={(e) => onText(it.id, e.target.value)}
              rows={1}
              aria-label={t('estimateBasis.lineText', { defaultValue: 'Line text' })}
              className={`min-h-[2.25rem] flex-1 rounded-lg border border-border-light bg-surface-primary px-2.5 py-1.5 text-sm text-content-primary ${
                it.enabled ? '' : 'text-content-tertiary line-through'
              }`}
            />
            {it.trade_label && (
              <span className="mt-1.5 hidden shrink-0 rounded bg-surface-secondary px-1.5 py-0.5 text-xs text-content-tertiary sm:inline">
                {it.trade_label}
              </span>
            )}
            <button
              type="button"
              onClick={() => onRemove(it.id)}
              className="mt-1.5 shrink-0 rounded p-1 text-content-tertiary hover:text-semantic-error"
              aria-label={t('estimateBasis.removeLine', { defaultValue: 'Remove line' })}
            >
              <Trash2 className="h-4 w-4" aria-hidden />
            </button>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
