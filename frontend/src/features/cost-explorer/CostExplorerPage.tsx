// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Cost Explorer - one search-first workspace over the cost and resource
// databases. Five tabs, one backbone (the resource -> work reverse index):
//   By resources | Find work | Analog rates | Compare bases | Substitute
// Any result can hand its work or code to another tab, so an estimator moves
// from "which works use this material" to "which analog rate fits this need"
// to "how is it priced elsewhere" to "what if I swap it" without re-entering
// anything.

import { Fragment, useState, type ReactNode } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  ArrowRight,
  Boxes,
  GitCompareArrows,
  ListPlus,
  Network,
  RefreshCw,
  Repeat2,
  Scale,
  Search,
} from 'lucide-react';
import { Button, CollapsibleSection, PageHeader, TabBar, tabIds } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { getIndexStatus, reindex } from './api';
import { ByResourcesPanel } from './ByResourcesPanel';
import { FindWorkPanel } from './FindWorkPanel';
import { AnalogRatesPanel } from './AnalogRatesPanel';
import { ComparePanel } from './ComparePanel';
import { SubstitutePanel } from './SubstitutePanel';
import type { CostExplorerTab, CrossNav, SubstituteSeed } from './types';
import { fmtList } from '@/shared/lib/formatters';

/** Local tab set: the shared four (see {@link CostExplorerTab}) plus the
 *  analog-rates compare wired in here. Kept local so the cross-tab nav contract
 *  in ``types.ts`` stays untouched. */
type ExplorerTab = CostExplorerTab | 'analogs';

export function CostExplorerPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<ExplorerTab>('by-resources');
  const [compareCode, setCompareCode] = useState('');
  const [subSeed, setSubSeed] = useState<SubstituteSeed | null>(null);

  const nav: CrossNav = {
    openCompare: (code) => {
      setCompareCode(code);
      setTab('compare');
    },
    openSubstitute: (seed) => {
      setSubSeed(seed);
      setTab('substitute');
    },
  };

  const ids = tabIds('cost-explorer');
  const tabs = [
    { id: 'by-resources' as const, label: t('costExplorer.tabs.byResources', { defaultValue: 'By resources' }), icon: <Boxes className="h-4 w-4" /> },
    { id: 'find-work' as const, label: t('costExplorer.tabs.findWork', { defaultValue: 'Find work' }), icon: <Search className="h-4 w-4" /> },
    { id: 'analogs' as const, label: t('costExplorer.tabs.analogs', { defaultValue: 'Analog rates' }), icon: <Scale className="h-4 w-4" /> },
    { id: 'compare' as const, label: t('costExplorer.tabs.compare', { defaultValue: 'Compare bases' }), icon: <GitCompareArrows className="h-4 w-4" /> },
    { id: 'substitute' as const, label: t('costExplorer.tabs.substitute', { defaultValue: 'Substitute' }), icon: <Repeat2 className="h-4 w-4" /> },
  ];

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        srTitle={t('costExplorer.title', { defaultValue: 'Cost Explorer' })}
        subtitle={t('costExplorer.subtitle', {
          defaultValue: 'Find priced work by the resources it uses, search the catalogs, compare price bases and test substitutions.',
        })}
      />

      <HowCostExplorerWorks />

      <IndexStatusNote />

      <div>
        <TabBar<ExplorerTab>
          tabs={tabs}
          activeId={tab}
          onChange={setTab}
          idPrefix="cost-explorer"
          ariaLabel={t('costExplorer.title', { defaultValue: 'Cost Explorer' })}
        />
        {/* All five panels stay mounted; only the active one is shown. Keeping
            them mounted preserves each panel's in-progress input (picked
            resources, a typed query, its results) when the user switches tabs
            and comes back, instead of resetting it on every switch. Every
            panel's data fetch is gated (mutation or an enabled query), so the
            hidden panels issue no requests until acted on. */}
        <div role="tabpanel" id={ids.panelId('by-resources')} aria-labelledby={ids.tabId('by-resources')} hidden={tab !== 'by-resources'} className="pt-4">
          <ByResourcesPanel nav={nav} />
        </div>
        <div role="tabpanel" id={ids.panelId('find-work')} aria-labelledby={ids.tabId('find-work')} hidden={tab !== 'find-work'} className="pt-4">
          <FindWorkPanel nav={nav} />
        </div>
        <div role="tabpanel" id={ids.panelId('analogs')} aria-labelledby={ids.tabId('analogs')} hidden={tab !== 'analogs'} className="pt-4">
          <AnalogRatesPanel nav={nav} />
        </div>
        <div role="tabpanel" id={ids.panelId('compare')} aria-labelledby={ids.tabId('compare')} hidden={tab !== 'compare'} className="pt-4">
          <ComparePanel code={compareCode} onCodeChange={setCompareCode} />
        </div>
        <div role="tabpanel" id={ids.panelId('substitute')} aria-labelledby={ids.tabId('substitute')} hidden={tab !== 'substitute'} className="pt-4">
          <SubstitutePanel seed={subSeed} />
        </div>
      </div>
    </div>
  );
}

/* ── How-it-works flow + module integrations ───────────────────────────── */

/** A compact inline link to a sibling module (keeps the flow copy readable). */
function ModLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className="font-medium text-oe-blue-text hover:underline">
      {children}
    </Link>
  );
}

/**
 * Explains, in one glance, what Cost Explorer is and how it connects to the rest
 * of the platform: start from the resources you know (or a plain description),
 * search across every loaded price base, compare the same code across regions or
 * test a substitution, then push the result straight into a BOQ or save it as a
 * reusable assembly. The founder's ask was that the module make its purpose and
 * its integrations obvious, so every connected module is a link.
 */
function HowCostExplorerWorks() {
  const { t } = useTranslation();

  const steps: { icon: ReactNode; title: string; desc: string }[] = [
    {
      icon: <Boxes size={14} className="text-oe-blue" />,
      title: t('costExplorer.flow_1_title', { defaultValue: 'Start from what you know' }),
      desc: t('costExplorer.flow_1_desc', {
        defaultValue: 'Pick the resources a work consumes, or just describe the work in plain words.',
      }),
    },
    {
      icon: <Search size={14} className="text-oe-blue" />,
      title: t('costExplorer.flow_2_title', { defaultValue: 'Search the price bases' }),
      desc: t('costExplorer.flow_2_desc', {
        defaultValue: 'Search across every loaded price base at once, or narrow to one region.',
      }),
    },
    {
      icon: <GitCompareArrows size={14} className="text-oe-blue" />,
      title: t('costExplorer.flow_3_title', { defaultValue: 'Compare and test' }),
      desc: t('costExplorer.flow_3_desc', {
        defaultValue:
          'Compare the same code across regions, or test a material substitution to see the rate move.',
      }),
    },
    {
      icon: <ListPlus size={14} className="text-oe-blue" />,
      title: t('costExplorer.flow_4_title', { defaultValue: 'Use it in an estimate' }),
      desc: t('costExplorer.flow_4_desc', {
        defaultValue: 'Add the priced work onto a BOQ position, or save it as a reusable assembly.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="costExplorer.how"
      icon={<Network size={15} className="text-oe-blue" />}
      title={t('costExplorer.flow_title', { defaultValue: 'How Cost Explorer fits together' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('costExplorer.flow_intro', {
          defaultValue:
            'Cost Explorer is your search-first workspace over every loaded price base - look up priced work by the resources it consumes, search the catalogs, compare the same code across regions, and test material substitutions, then push what you find straight into an estimate.',
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
            {t('costExplorer.flow_searches', { defaultValue: 'Searches:' })}
          </span>{' '}
          <ModLink to="/costs">
            {t('costExplorer.mod_costs', { defaultValue: 'Cost Database' })}
          </ModLink>{' '}
          ·{' '}
          <ModLink to="/catalog">
            {t('costExplorer.mod_catalog', { defaultValue: 'Catalog' })}
          </ModLink>
        </span>
        <span>
          <span className="font-medium text-content-secondary">
            {t('costExplorer.flow_feeds', { defaultValue: 'Feeds:' })}
          </span>{' '}
          <ModLink to="/boq">{t('costExplorer.mod_boq', { defaultValue: 'BOQ' })}</ModLink> ·{' '}
          <ModLink to="/assemblies">
            {t('costExplorer.mod_assemblies', { defaultValue: 'Assemblies' })}
          </ModLink>{' '}
          ·{' '}
          <ModLink to="/cost-match">
            {t('costExplorer.mod_cost_match', { defaultValue: 'Cost Match' })}
          </ModLink>
        </span>
      </div>
    </CollapsibleSection>
  );
}

/**
 * Surfaces when the reverse index is empty but there are works to index, or when
 * a loaded cost base carries works that are missing from the index (e.g. a large
 * second base imported past the auto-rebuild cap). Offers a one-click rebuild;
 * managers succeed, others get a clear message. Silent once every base is indexed.
 */
function IndexStatusNote() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const status = useQuery({
    queryKey: ['cost-explorer', 'status'],
    queryFn: getIndexStatus,
    staleTime: 60_000,
  });

  const rebuild = useMutation({
    mutationFn: reindex,
    onSuccess: (r) => {
      addToast({
        type: 'success',
        title: t('costExplorer.index.rebuilt', { defaultValue: 'Resource index rebuilt' }),
        message: t('costExplorer.index.rebuiltDetail', {
          defaultValue: '{{edges}} resource links across {{items}} works.',
          edges: r.edges_written,
          items: r.items_scanned,
        }),
      });
      queryClient.invalidateQueries({ queryKey: ['cost-explorer', 'status'] });
    },
    onError: (e) => {
      addToast({
        type: 'error',
        title: t('costExplorer.index.rebuildFailed', { defaultValue: 'Could not rebuild the index' }),
        message: getErrorMessage(e),
      });
    },
  });

  const data = status.data;
  const isEmpty = !!data && data.indexed_edges === 0 && data.cost_items > 0;
  const staleRegions = data?.unindexed_regions ?? [];
  const show = isEmpty || staleRegions.length > 0;
  if (!show) return null;

  // The empty message links "import a base" to the Cost Database, so the empty
  // path points straight to where cost bases are loaded (see /costs/import too).
  const message: ReactNode = isEmpty ? (
    <>
      {t('costExplorer.index.emptyPre', {
        defaultValue:
          'The resource index is empty, so by-resources search has nothing to match yet. Rebuild it to index the loaded cost bases, or ',
      })}
      <ModLink to="/costs">
        {t('costExplorer.index.emptyImportLink', { defaultValue: 'import a base' })}
      </ModLink>
      {t('costExplorer.index.emptyPost', { defaultValue: ' if none is loaded yet.' })}
    </>
  ) : (
    t('costExplorer.index.stale', {
      defaultValue:
        'Some loaded cost bases are not in the resource index yet ({{regions}}), so by-resources search will miss them. Rebuild to index them.',
      regions: fmtList(staleRegions),
    })
  );

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-lg border border-semantic-warning/30 bg-semantic-warning/10 px-3 py-2.5">
      <AlertTriangle className="h-4 w-4 shrink-0 text-semantic-warning" aria-hidden />
      <span className="min-w-0 flex-1 text-sm text-content-secondary">{message}</span>
      <Button size="sm" variant="secondary" onClick={() => rebuild.mutate()} disabled={rebuild.isPending}>
        <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${rebuild.isPending ? 'animate-spin' : ''}`} />
        {rebuild.isPending ? t('costExplorer.index.rebuilding', { defaultValue: 'Rebuilding...' }) : t('costExplorer.index.rebuild', { defaultValue: 'Rebuild index' })}
      </Button>
    </div>
  );
}
