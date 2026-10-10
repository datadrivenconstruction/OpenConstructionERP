// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { Fragment, useMemo, useRef, useState } from 'react';
import type { ChangeEvent, ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';
import clsx from 'clsx';
import {
  AlertTriangle,
  ArrowRight,
  Check,
  FileStack,
  FileText,
  Layers,
  RefreshCw,
  Ruler,
  Search,
  Upload,
} from 'lucide-react';
import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  CollapsibleSection,
  DateDisplay,
  EmptyState,
  SkeletonTable,
} from '@/shared/ui';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { apiGet, type Page } from '@/shared/lib/api';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { fetchProjectList } from '@/shared/lib/projectList';
import { ConfirmDialog } from '@/shared/ui/ConfirmDialog';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  bulkUpdateSheets,
  rereadTitleBlocks,
  splitPdfIntoSheets,
  type SheetBulkPatch,
  type SheetRereadSummary,
} from './api';
import { SheetsBulkEditBar } from './SheetsBulkEditBar';
import { SheetDetailDrawer } from './SheetDetailDrawer';
import { buildSheetsInsights } from './sheetsInsights';
import { earlierRevisionCounts, revisionOrderUnclear } from './sheetStack';
import type { SheetRow } from './types';
import { getIntlLocale } from '@/shared/lib/formatters';

/* ── API types ────────────────────────────────────────────────────────
   `SheetRow` mirrors SheetResponse and lives in ./types so the detail
   drawer can share it. */

interface ProjectLite {
  id: string;
  name: string;
}

/* ── Helpers ─────────────────────────────────────────────────────────── */

function disciplineVariant(d: string | null): 'neutral' | 'blue' | 'success' | 'warning' | 'error' {
  if (!d) return 'neutral';
  // Stable pseudo-hash → keeps the same colour across renders.
  let h = 0;
  for (let i = 0; i < d.length; i += 1) {
    h = (h * 31 + d.charCodeAt(i)) >>> 0;
  }
  const pool = ['blue', 'success', 'warning', 'neutral'] as const;
  return pool[h % pool.length] ?? 'neutral';
}

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/* ── Explainer ───────────────────────────────────────────────────────── */

/** Modules this register reads from and hands off to. Written out rather than
 *  derived so the row names real destinations, and reusing the sidebar's own
 *  label keys means a link here never drifts from the menu entry it points at. */
const PULLS_FROM = [{ key: 'nav.documents', def: 'Documents', to: '/files' }];

const FEEDS = [
  { key: 'nav.plan_room', def: 'Plan Room', to: '/plan-room' },
  { key: 'nav.pdf_measurements', def: 'PDF Measurements', to: '/takeoff?tab=measurements' },
  { key: 'nav.markups', def: 'Markups', to: '/markups' },
  { key: 'validation.title', def: 'Validation', to: '/validation' },
];

function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * One-glance explainer: what the sheet index is, and what it is not.
 *
 * The register indexes nothing by itself. Every row here exists because a
 * multi-page PDF was uploaded to the Files module and split, so a user whose
 * table is empty needs to be told where drawings come in, not left to hunt for
 * an "add sheet" button that does not exist. The closing row names the modules
 * a found drawing actually opens into, which is the reason to be on this page.
 */
function HowSheetsWork() {
  const { t } = useTranslation();

  const steps: { icon: ReactNode; title: string; desc: string }[] = [
    {
      icon: <Upload size={14} className="text-oe-blue" />,
      title: t('sheets.flow_1_title', { defaultValue: 'A drawing set arrives' }),
      // New key, not an edit of `sheets.flow_1_desc`: that key is already in
      // all 29 bundles, so its old text ("Nothing is created here by hand")
      // would keep rendering and a changed defaultValue would do nothing.
      desc: t('sheets.flow_1_desc_split', {
        defaultValue:
          'A multi-page PDF is uploaded to Project files, or split straight from this page with the button above the table.',
      }),
    },
    {
      icon: <FileStack size={14} className="text-oe-blue" />,
      title: t('sheets.flow_2_title', { defaultValue: 'Pages become sheets' }),
      // New key, not an edit of `sheets.flow_2_desc`, which is translated in
      // every bundle and says nothing about dates, file names or stacking.
      desc: t('sheets.flow_2_desc_stack', {
        defaultValue:
          'Each page is read for its number, title, scale, revision and date, and a single-drawing PDF also by its file name. A newer revision of a sheet already here stacks on top of it.',
      }),
    },
    {
      icon: <Search size={14} className="text-oe-blue" />,
      title: t('sheets.flow_3_title', { defaultValue: 'Find the one you need' }),
      desc: t('sheets.flow_3_desc', {
        defaultValue:
          'Filter by discipline or search by number, title and revision. A superseded sheet stays on the list with the revision that replaced it.',
      }),
    },
    {
      icon: <Ruler size={14} className="text-oe-blue" />,
      title: t('sheets.flow_4_title', { defaultValue: 'Open it where the work is' }),
      desc: t('sheets.flow_4_desc', {
        defaultValue:
          'Pick a row to open that exact page in the plan room, or in PDF takeoff to measure it.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="sheets.how"
      icon={<Layers size={15} className="text-oe-blue" />}
      title={t('sheets.flow_title', {
        defaultValue: 'How the Drawing Sheet register fits together',
      })}
    >
      <p className="text-xs text-content-tertiary">
        {t('sheets.flow_intro', {
          defaultValue:
            'One searchable index of every drawing page on the project. It does not store drawings of its own; it indexes the pages of the drawing sets already uploaded, so a sheet number is enough to reach the page it names.',
        })}
      </p>

      <ol className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-stretch">
        {steps.map((s, i) => (
          <Fragment key={s.title}>
            <li className="flex-1 rounded-lg border border-border-light bg-surface-secondary/40 p-3">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-oe-blue-subtle text-2xs font-bold text-oe-blue-text">
                  {i + 1}
                </span>
                <span className="flex items-center gap-1 text-xs font-semibold text-content-primary">
                  {s.icon}
                  {s.title}
                </span>
              </div>
              <p className="mt-1.5 text-2xs leading-relaxed text-content-tertiary">{s.desc}</p>
            </li>
            {i < steps.length - 1 && (
              <li
                aria-hidden="true"
                className="hidden shrink-0 items-center self-center text-content-quaternary lg:flex"
              >
                <ArrowRight size={16} />
              </li>
            )}
          </Fragment>
        ))}
      </ol>

      <div className="mt-3 flex flex-col gap-1.5 border-t border-border-light pt-3 text-2xs text-content-tertiary sm:flex-row sm:flex-wrap sm:items-center sm:gap-x-5 sm:gap-y-1">
        <span>
          <span className="font-medium text-content-secondary">
            {t('sheets.flow_pulls', { defaultValue: 'Pulls from:' })}
          </span>{' '}
          {PULLS_FROM.map((m, i) => (
            <Fragment key={m.key}>
              {i > 0 && ' · '}
              <ModLink to={m.to}>{t(m.key, { defaultValue: m.def })}</ModLink>
            </Fragment>
          ))}
        </span>
        <span>
          <span className="font-medium text-content-secondary">
            {t('sheets.flow_feeds', { defaultValue: 'Feeds:' })}
          </span>{' '}
          {FEEDS.map((m, i) => (
            <Fragment key={m.key}>
              {i > 0 && ' · '}
              <ModLink to={m.to}>{t(m.key, { defaultValue: m.def })}</ModLink>
            </Fragment>
          ))}
        </span>
      </div>
    </CollapsibleSection>
  );
}

/* ── Main page ───────────────────────────────────────────────────────── */

export function SheetsIndexPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const queryClient = useQueryClient();

  const [searchQuery, setSearchQuery] = useState('');
  const [disciplineFilter, setDisciplineFilter] = useState<string | null>(null);
  const [currentOnly, setCurrentOnly] = useState(false);
  const [openSheet, setOpenSheet] = useState<SheetRow | null>(null);
  const [splitError, setSplitError] = useState<string | null>(null);
  const [splitAdded, setSplitAdded] = useState<number | null>(null);
  const [rereadAsked, setRereadAsked] = useState(false);
  const [rereadResult, setRereadResult] = useState<SheetRereadSummary | null>(null);
  const [rereadError, setRereadError] = useState<string | null>(null);
  const canEdit = useHasPermission('documents.update');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set());
  const [bulkError, setBulkError] = useState<string | null>(null);
  // One input for the whole page - both triggers open it. A second one would
  // duplicate the accessible name and give the register two half-states.
  const pdfInputRef = useRef<HTMLInputElement>(null);

  // Pick a working project id (route → store → first available).
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchProjectList<ProjectLite[]>(),
    staleTime: 5 * 60_000,
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';
  const projectName = projects.find((p) => p.id === projectId)?.name || '';

  const { data: sheetPage, isLoading } = useQuery({
    queryKey: ['sheets', projectId],
    queryFn: () =>
      apiGet<Page<SheetRow>>(
        `/v1/documents/sheets/?project_id=${encodeURIComponent(projectId)}&limit=500`,
      ),
    enabled: !!projectId,
  });
  // The register asks for the maximum the route allows, so a drawing set past
  // 500 sheets arrives cut. `total` is what lets the page below say so.
  const sheets = useMemo(() => sheetPage?.items ?? [], [sheetPage]);

  const { data: disciplines = [] } = useQuery({
    queryKey: ['sheet-disciplines', projectId],
    queryFn: () =>
      apiGet<string[]>(
        `/v1/documents/sheets/disciplines/?project_id=${encodeURIComponent(projectId)}`,
      ),
    enabled: !!projectId,
  });

  /* The only way a row gets into this register: hand the drawing set to
     /sheets/split-pdf/ and let it read one sheet out of every page. The split
     is per-page text extraction plus a thumbnail render, so a full set is
     minutes, not seconds - hence the running state rather than a spinner that
     appears and vanishes. */
  const splitMutation = useMutation({
    mutationFn: (file: File) => splitPdfIntoSheets(projectId, file),
    onSuccess: (created) => {
      setSplitError(null);
      setSplitAdded(created.length);
      queryClient.invalidateQueries({ queryKey: ['sheets', projectId] });
      // The chip row is built from a separate query: a set that brings in a
      // discipline the project had never seen leaves it stale otherwise.
      queryClient.invalidateQueries({ queryKey: ['sheet-disciplines', projectId] });
    },
    onError: (err: unknown) => {
      setSplitAdded(null);
      setSplitError(err instanceof Error ? err.message : String(err));
    },
  });

  // A successful apply clears the selection, which unmounts the bar, so its
  // inputs start empty the next time sheets are ticked.
  const bulkMutation = useMutation({
    mutationFn: ({ ids, patch }: { ids: string[]; patch: SheetBulkPatch }) =>
      bulkUpdateSheets(projectId, ids, patch),
    onSuccess: () => {
      setBulkError(null);
      setSelectedIds(new Set());
      queryClient.invalidateQueries({ queryKey: ['sheets', projectId] });
      queryClient.invalidateQueries({ queryKey: ['sheet-disciplines', projectId] });
    },
    onError: (err: unknown) => setBulkError(err instanceof Error ? err.message : String(err)),
  });

  function toggleSelected(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  /* For a register imported before the title block reader was fixed: every
     sheet is read again from the PDF already stored, so a revision read as
     "ole" or a number not read at all is corrected without a re-upload, which
     would add a second copy of every drawing. Fields corrected by hand stay. */
  const rereadMutation = useMutation({
    mutationFn: () => rereadTitleBlocks(projectId),
    onSuccess: (summary) => {
      setRereadAsked(false);
      setRereadError(null);
      setRereadResult(summary);
      queryClient.invalidateQueries({ queryKey: ['sheets', projectId] });
      queryClient.invalidateQueries({ queryKey: ['sheet-versions'] });
      queryClient.invalidateQueries({ queryKey: ['sheet-disciplines', projectId] });
    },
    onError: (err: unknown) => {
      setRereadAsked(false);
      setRereadResult(null);
      setRereadError(err instanceof Error ? err.message : String(err));
    },
  });

  function onPickPdf(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    // Clear the input, or picking the same file after a failure fires no
    // change event and the retry looks like a dead button.
    e.target.value = '';
    if (!file) return;
    setSplitError(null);
    setSplitAdded(null);
    splitMutation.mutate(file);
  }

  const splitLabel = t('sheets.split_cta', { defaultValue: 'Split a PDF into sheets' });
  /* Rendered twice - once beside the search box where it stays reachable, once
     in the empty state, which is where somebody with nothing in the register
     is actually looking. `aria-label` because the button swaps its text for a
     spinner while the split runs, and the control should keep its name. */
  const splitButton = (
    <Button
      variant="primary"
      icon={<Upload size={14} />}
      loading={splitMutation.isPending}
      aria-label={splitLabel}
      onClick={() => pdfInputRef.current?.click()}
    >
      {splitLabel}
    </Button>
  );

  /* Client-side filter (discipline chip + free-text search). Sheets are
     usually <500 per project, so filtering in memory keeps the UI snappy
     without extra round-trips. */
  const filtered = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return sheets.filter((s) => {
      if (disciplineFilter && s.discipline !== disciplineFilter) return false;
      if (currentOnly && !s.is_current) return false;
      if (!q) return true;
      const hay = [
        s.sheet_number,
        s.sheet_title,
        s.discipline,
        s.revision,
        s.scale,
      ]
        .filter((x): x is string => Boolean(x))
        .join(' ')
        .toLowerCase();
      return hay.includes(q);
    });
  }, [sheets, disciplineFilter, currentOnly, searchQuery]);
  // A bulk edit changes only the ticked sheets the filters still show, so a
  // sheet ticked and then filtered away is never changed out of sight.
  const selectedShown = useMemo(
    () => filtered.filter((s) => selectedIds.has(s.id)).map((s) => s.id),
    [filtered, selectedIds],
  );

  /* How many revisions each row stands on, read off the loaded rows' links, so
     a current sheet can say it is the top of a stack and not a lone upload. */
  const earlierCounts = useMemo(() => earlierRevisionCounts(sheets), [sheets]);

  /* Insights are built from the rows the page already holds - no extra
     request. Built from the project's whole set rather than `filtered`: the
     panel describes the register, and a "sheets by discipline" chart that
     collapsed to one bar the moment a discipline chip was clicked would be
     answering a question the chip has already answered. Kept with the other
     top-level hooks so the hook order cannot change between renders. */
  const insights = useModuleInsights('sheets', { defaultOpen: true });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildSheetsInsights(sheets, t),
    [sheets, t],
  );

  return (
    <div className="w-full animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          { label: t('nav.documents', { defaultValue: 'Documents' }), to: '/files' },
          ...(projectName ? [{ label: projectName }] : []),
          { label: t('sheets.title', { defaultValue: 'Sheets' }) },
        ]}
        className="mb-4"
      />

      {/* Header */}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-content-primary">
            {t('sheets.page_title', { defaultValue: 'Drawing Sheets' })}
          </h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('sheets.subtitle', {
              defaultValue:
                'Indexed drawing sheets across project documents - filter by discipline or search by number, title, revision.',
            })}
          </p>
        </div>
        <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
      </div>

      <div className="mb-4">
        <HowSheetsWork />
      </div>

      {!projectId && <RequiresProject>{null}</RequiresProject>}

      {projectId && (
        <>
          <InsightsPanel
            open={insights.open}
            title={t('sheets.insights.title', { defaultValue: 'Sheet insights' })}
            datasets={insightDatasets}
            builtins={insightBuiltins}
            custom={insights.custom}
            onAdd={insights.addCustom}
            onUpdate={insights.updateCustom}
            onRemove={insights.removeCustom}
            onCollapse={() => insights.setOpen(false)}
          />

          {/* Discipline filter chips */}
          {disciplines.length > 0 && (
            <div className="mb-4 flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => setDisciplineFilter(null)}
                className={clsx(
                  'inline-flex items-center h-7 px-3 rounded-full text-xs font-medium transition-colors',
                  disciplineFilter === null
                    ? 'bg-oe-blue text-white'
                    : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary',
                )}
              >
                {t('sheets.filter_all_disciplines', { defaultValue: 'All disciplines' })}
                <span className="ms-1.5 tabular-nums opacity-70">{sheets.length}</span>
              </button>
              {disciplines.map((d) => {
                const count = sheets.filter((s) => s.discipline === d).length;
                const active = disciplineFilter === d;
                return (
                  <button
                    key={d}
                    type="button"
                    onClick={() => setDisciplineFilter(d)}
                    className={clsx(
                      'inline-flex items-center h-7 px-3 rounded-full text-xs font-medium transition-colors',
                      active
                        ? 'bg-oe-blue text-white'
                        : 'bg-surface-secondary text-content-secondary hover:bg-surface-tertiary',
                    )}
                  >
                    {d}
                    <span className="ms-1.5 tabular-nums opacity-70">{count}</span>
                  </button>
                );
              })}
            </div>
          )}

          {/* Search */}
          <div className="mb-6 flex flex-col sm:flex-row sm:items-center gap-3">
            <div className="relative flex-1 max-w-sm">
              <Search
                size={16}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary"
              />
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={t('sheets.search_placeholder', {
                  defaultValue: 'Search by sheet #, title, revision…',
                })}
                aria-label={t('sheets.search_placeholder', {
                  defaultValue: 'Search by sheet #, title, revision…',
                })}
                className={inputCls + ' pl-9'}
              />
            </div>
            <label className="inline-flex items-center gap-2 text-sm text-content-secondary">
              <input
                type="checkbox"
                checked={currentOnly}
                onChange={(e) => setCurrentOnly(e.target.checked)}
                className="h-4 w-4 rounded border-border accent-oe-blue"
              />
              {t('sheets.filter_current_only', { defaultValue: 'Current revisions only' })}
            </label>
            <div className="sm:ms-auto flex flex-wrap items-center gap-2">
              {canEdit && sheets.length > 0 && (
                <Button
                  variant="secondary"
                  icon={<RefreshCw size={14} />}
                  loading={rereadMutation.isPending}
                  disabled={splitMutation.isPending}
                  title={t('sheets.reread_hint', {
                    defaultValue:
                      'Read every sheet again from the stored PDFs. Fields you corrected by hand are kept.',
                  })}
                  onClick={() => {
                    setRereadResult(null);
                    setRereadError(null);
                    setRereadAsked(true);
                  }}
                >
                  {t('sheets.reread_cta', { defaultValue: 'Re-read title blocks' })}
                </Button>
              )}
              {splitButton}
            </div>
          </div>

          <ConfirmDialog
            open={rereadAsked}
            variant="warning"
            loading={rereadMutation.isPending}
            title={t('sheets.reread_confirm_title', {
              defaultValue: 'Re-read all title blocks?',
            })}
            message={t('sheets.reread_confirm_body', {
              defaultValue:
                'Every sheet in this project is read again from its stored PDF. Number, title, revision, date, scale and discipline are replaced with what is read now, and revision stacks are rebuilt. Fields you corrected by hand are not changed. Nothing is uploaded or deleted.',
            })}
            confirmLabel={t('sheets.reread_confirm_action', { defaultValue: 'Re-read' })}
            cancelLabel={t('sheets.edit_cancel', { defaultValue: 'Cancel' })}
            onConfirm={() => rereadMutation.mutate()}
            onCancel={() => setRereadAsked(false)}
          />

          {/* Hidden native input - both split triggers proxy their click here. */}
          <input
            ref={pdfInputRef}
            type="file"
            accept="application/pdf,.pdf"
            className="sr-only"
            aria-label={t('sheets.split_input_label', {
              defaultValue: 'Drawing set PDF to split into sheets',
            })}
            disabled={splitMutation.isPending}
            onChange={onPickPdf}
          />

          {/* Split status. Sits above the table so it is in view from either
              branch - the empty state below it, or the rows it just added. */}
          {splitMutation.isPending && (
            <p role="status" className="mb-4 text-sm text-content-secondary">
              {t('sheets.split_running', {
                defaultValue:
                  'Reading the drawing set page by page. A large set takes a few minutes - leave this page open.',
              })}
            </p>
          )}
          {splitError && (
            <p
              role="alert"
              className="mb-4 rounded-lg border border-semantic-error/30 bg-semantic-error/5 px-3 py-2 text-sm text-semantic-error"
            >
              {t('sheets.split_failed', { defaultValue: 'That PDF could not be split.' })}{' '}
              {splitError}
            </p>
          )}
          {splitAdded !== null && !splitMutation.isPending && (
            <p role="status" className="mb-4 text-sm text-semantic-success">
              {t('sheets.split_done', {
                defaultValue: '{{count}} sheets added to the register.',
                count: splitAdded,
              })}
            </p>
          )}

          {rereadMutation.isPending && (
            <p role="status" className="mb-4 text-sm text-content-secondary">
              {t('sheets.reread_running', {
                defaultValue: 'Reading the stored drawings again. A large register takes a few minutes.',
              })}
            </p>
          )}
          {rereadError && (
            <p
              role="alert"
              className="mb-4 rounded-lg border border-semantic-error/30 bg-semantic-error/5 px-3 py-2 text-sm text-semantic-error"
            >
              {t('sheets.reread_failed', { defaultValue: 'The title blocks could not be re-read.' })}{' '}
              {rereadError}
            </p>
          )}
          {rereadResult && !rereadMutation.isPending && (
            <p role="status" className="mb-4 text-sm text-semantic-success">
              {t('sheets.reread_done', {
                defaultValue: 'Sheets updated: {{updated}} of {{checked}}.',
                updated: rereadResult.sheets_updated,
                checked: rereadResult.sheets_checked,
              })}
              {rereadResult.files_missing > 0 && (
                <>
                  {' '}
                  {t('sheets.reread_missing', {
                    defaultValue: '{{count}} sheets were left as they were: their PDF could not be read.',
                    count: rereadResult.files_missing,
                  })}
                </>
              )}
            </p>
          )}
          {rereadResult && rereadResult.current_conflicts.length > 0 && !rereadMutation.isPending && (
            <p
              role="alert"
              className="mb-4 rounded-lg border border-semantic-warning/30 bg-semantic-warning/5 px-3 py-2 text-sm text-content-primary"
            >
              {t('sheets.reread_conflicts', {
                defaultValue:
                  '{{count}} sheets keep the current or superseded state set by hand, although their revisions now say otherwise. Check them.',
                count: rereadResult.current_conflicts.length,
              })}
            </p>
          )}

          {/* Table */}
          {isLoading ? (
            <SkeletonTable rows={6} columns={7} />
          ) : filtered.length === 0 ? (
            <EmptyState
              icon={<FileText size={28} strokeWidth={1.5} />}
              title={
                searchQuery || disciplineFilter || currentOnly
                  ? t('sheets.no_results', { defaultValue: 'No matching sheets' })
                  : t('sheets.no_sheets', { defaultValue: 'No sheets indexed yet' })
              }
              description={
                searchQuery || disciplineFilter || currentOnly
                  ? t('sheets.no_results_hint', {
                      defaultValue:
                        'Try adjusting the search box or pick a different discipline.',
                    })
                  : // New key rather than an edit of `sheets.no_sheets_hint`,
                    // which is already translated in all 29 bundles and sends
                    // the reader off to another module for a job this page now
                    // does itself.
                    t('sheets.no_sheets_hint_split', {
                      defaultValue:
                        'Pick the multi-page PDF of the drawing set and every page becomes a sheet here - number, title, discipline, revision and scale are read off the page.',
                    })
              }
              // Only on the "nothing indexed" branch. A search that matched
              // nothing is not fixed by uploading, and offering the upload
              // there would read as if the filter had eaten the register.
              action={searchQuery || disciplineFilter || currentOnly ? undefined : splitButton}
            />
          ) : (
            <>
              <p className="mb-3 text-sm text-content-tertiary">
                {t('sheets.showing_count', {
                  defaultValue: '{{count}} sheets',
                  count: filtered.length,
                })}
              </p>
              {/* The line above counts the rows the filters left on screen.
                  This one is about the register behind them, so it is fed the
                  server page and never the filtered array. */}
              {sheetPage ? <TruncationNotice page={sheetPage} className="-mt-2 mb-3" /> : null}
              {canEdit && (
                <p className="-mt-2 mb-3 text-2xs text-content-tertiary">
                  {t('sheets.row_edit_hint', {
                    defaultValue:
                      'Click a sheet to correct its number, title, revision, discipline or date and to see its earlier revisions. Tick several to change them together.',
                  })}
                </p>
              )}
              {canEdit && selectedShown.length > 0 && (
                <SheetsBulkEditBar
                  selectedCount={selectedShown.length}
                  disciplines={disciplines}
                  saving={bulkMutation.isPending}
                  error={bulkError}
                  onApply={(patch) => bulkMutation.mutate({ ids: selectedShown, patch })}
                  onClear={() => {
                    setSelectedIds(new Set());
                    setBulkError(null);
                  }}
                />
              )}

              <Card padding="none" className="overflow-x-auto">
                <table className="w-full text-sm border-collapse">
                  <thead className="sticky top-0 z-10 bg-surface-secondary/95 backdrop-blur-sm">
                    <tr className="text-2xs font-medium text-content-tertiary uppercase tracking-wider">
                      {canEdit && (
                        <th className="w-10 px-3 py-2.5 border-b border-border-light">
                          <input
                            type="checkbox"
                            aria-label={t('sheets.select_all', { defaultValue: 'Select all sheets shown' })}
                            checked={filtered.length > 0 && filtered.every((s) => selectedIds.has(s.id))}
                            onChange={(e) =>
                              setSelectedIds(e.target.checked ? new Set(filtered.map((s) => s.id)) : new Set())
                            }
                            className="h-4 w-4 rounded border-border accent-oe-blue"
                          />
                        </th>
                      )}
                      <th className="text-start px-4 py-2.5 border-b border-border-light font-medium">
                        {t('sheets.col_number', { defaultValue: 'Sheet #' })}
                      </th>
                      <th className="text-start px-4 py-2.5 border-b border-border-light font-medium">
                        {t('sheets.col_title', { defaultValue: 'Title' })}
                      </th>
                      <th className="text-start px-4 py-2.5 border-b border-border-light font-medium">
                        {t('sheets.col_discipline', { defaultValue: 'Discipline' })}
                      </th>
                      <th className="text-start px-4 py-2.5 border-b border-border-light font-medium">
                        {t('sheets.col_revision', { defaultValue: 'Rev' })}
                      </th>
                      <th className="text-start px-4 py-2.5 border-b border-border-light font-medium">
                        {t('sheets.col_issue_date', { defaultValue: 'Issue Date' })}
                      </th>
                      <th className="text-start px-4 py-2.5 border-b border-border-light font-medium">
                        {t('sheets.col_scale', { defaultValue: 'Scale' })}
                      </th>
                      <th className="text-center px-4 py-2.5 border-b border-border-light font-medium">
                        {t('sheets.col_current', { defaultValue: 'Current?' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((s) => (
                      <tr
                        key={s.id}
                        // Whole-row click for the mouse; the sheet-number cell
                        // carries a real button so the same action has a tab
                        // stop and a name for assistive tech.
                        onClick={() => setOpenSheet(s)}
                        className={clsx(
                          'cursor-pointer hover:bg-surface-secondary/50 transition-colors border-b border-border-light last:border-b-0',
                          selectedIds.has(s.id) && 'bg-oe-blue/5',
                        )}
                      >
                        {canEdit && (
                          <td className="w-10 px-3 py-3" onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              aria-label={t('sheets.select_row', {
                                defaultValue: 'Select sheet {{number}}',
                                number: s.sheet_number ?? `p.${s.page_number}`,
                              })}
                              checked={selectedIds.has(s.id)}
                              onChange={() => toggleSelected(s.id)}
                              className="h-4 w-4 rounded border-border accent-oe-blue"
                            />
                          </td>
                        )}
                        <td className="px-4 py-3 font-mono text-content-primary whitespace-nowrap">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              setOpenSheet(s);
                            }}
                            className="rounded text-oe-blue-text hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue"
                          >
                            {s.sheet_number ?? `p.${s.page_number}`}
                          </button>
                        </td>
                        <td className="px-4 py-3 text-content-primary">
                          {s.sheet_title ?? (
                            <span className="text-content-quaternary">&mdash;</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          {s.discipline ? (
                            <Badge variant={disciplineVariant(s.discipline)} size="sm">
                              {s.discipline}
                            </Badge>
                          ) : (
                            <span className="text-content-quaternary">&mdash;</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <span className="inline-flex items-center gap-1.5">
                            {s.revision ? (
                              <Badge variant="neutral" size="sm">
                                {s.revision}
                              </Badge>
                            ) : (
                              <span className="text-content-quaternary">&mdash;</span>
                            )}
                            {revisionOrderUnclear(s) && (
                              <span
                                role="img"
                                title={t('sheets.revision_order_unclear', {
                                  defaultValue: 'Revision order unclear, check',
                                })}
                                aria-label={t('sheets.revision_order_unclear', {
                                  defaultValue: 'Revision order unclear, check',
                                })}
                                className="inline-flex text-semantic-warning"
                              >
                                <AlertTriangle size={14} aria-hidden="true" />
                              </span>
                            )}
                          </span>
                          {s.is_current && (earlierCounts.get(s.id) ?? 0) > 0 && (
                            <span className="mt-0.5 block text-2xs text-content-tertiary">
                              {t('sheets.stack_earlier', {
                                defaultValue: '{{count}} earlier revisions',
                                count: earlierCounts.get(s.id) ?? 0,
                              })}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-content-secondary">
                          {s.revision_date ? (
                            <span
                              title={new Date(s.revision_date).toLocaleString(getIntlLocale())}
                            >
                              <DateDisplay value={s.revision_date} format="relative" />
                            </span>
                          ) : (
                            <span className="text-content-quaternary">&mdash;</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-content-secondary tabular-nums">
                          {s.scale ?? <span className="text-content-quaternary">&mdash;</span>}
                        </td>
                        <td className="px-4 py-3 text-center">
                          {s.is_current ? (
                            <Check
                              size={16}
                              className="inline-block text-semantic-success"
                              aria-label={t('sheets.is_current_yes', {
                                defaultValue: 'Current revision',
                              })}
                            />
                          ) : (
                            /* Not an em-dash. The two columns to its left print
                               one for "this sheet has no revision date" and "no
                               scale", so the same glyph here reads as a field
                               nobody filled in rather than as a sheet a later
                               upload replaced. The word was in the markup all
                               along, but only inside an aria-label, which
                               carries it to the part of the audience that was
                               not the one being misled. */
                            <span className="inline-flex items-center h-5 px-2 rounded-full bg-surface-tertiary text-2xs font-medium text-content-tertiary">
                              {t('sheets.is_current_no', {
                                defaultValue: 'Superseded',
                              })}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            </>
          )}
        </>
      )}

      <SheetDetailDrawer
        sheet={openSheet}
        onClose={() => setOpenSheet(null)}
        onSheetChange={setOpenSheet}
      />
    </div>
  );
}
