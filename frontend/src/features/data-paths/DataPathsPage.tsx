// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// /data-paths and /data-paths/:module: the user-facing data map. Three zoom
// levels: one module's path, its one-to-two hop neighbourhood, and the whole
// platform. The project data map filters show where the project has data,
// what is installed but empty and what is not installed; the health panel
// names the critical inputs that are missing; the honeycomb shows who works
// on the project and lights the modules they touch.

import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { CircleAlert, CircleCheck, Search } from 'lucide-react';

import { PageHeader } from '@/shared/ui/PageHeader';
import { TabBar } from '@/shared/ui/TabBar';
import { fmtList, formatNumber } from '@/shared/lib/formatters';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

import { useModulePaths, usePlatformMap, useProjectParties, type HealthItem, type Party } from './api';
import { buildFlowModel, moduleLabel } from './flowModel';
import { DataPathsFlow } from './DataPathsFlow';
import { DataPathsList } from './DataPathsDrawer';
import { PartiesHoneycomb } from './PartiesHoneycomb';
import { PlatformMapCanvas, type CanvasModule, type ModuleStatus } from './PlatformMapCanvas';
import { neighbourhood } from './layout';
import { moduleMeta } from './moduleMeta';

type Level = 'module' | 'neighbourhood' | 'platform';
type Filter = 'all' | ModuleStatus;

export function DataPathsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const params = useParams<{ module?: string }>();
  const [search, setSearch] = useSearchParams();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const focus = params.module ?? search.get('focus') ?? null;
  const [level, setLevel] = useState<Level>(params.module ? 'module' : 'platform');
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');
  const [showTechnical, setShowTechnical] = useState(false);
  const [hovered, setHovered] = useState<string | null>(null);
  const [partyLit, setPartyLit] = useState<Set<string> | null>(null);

  const map = usePlatformMap(projectId);
  const paths = useModulePaths(focus, projectId, !!focus && level === 'module');
  const parties = useProjectParties(projectId);
  const flow = useMemo(() => (paths.data ? buildFlowModel(t, paths.data) : null), [paths.data, t]);

  const critical = useMemo(() => new Set((map.data?.health ?? []).map((h) => h.module)), [map.data]);
  const modules: CanvasModule[] = useMemo(
    () =>
      (map.data?.modules ?? []).map((m) => ({
        module: m,
        status: !m.installed ? 'not_installed' : m.count ? 'with_data' : 'empty',
        critical: critical.has(m.name),
      })),
    [map.data, critical],
  );
  const tally = useMemo(() => {
    const out: Record<ModuleStatus, number> = { with_data: 0, empty: 0, not_installed: 0 };
    for (const m of modules) out[m.status] += 1;
    return out;
  }, [modules]);

  const edges = map.data?.edges ?? [];
  const needle = query.trim().toLowerCase();
  const visible = useMemo(() => {
    let set: Set<string> | null = null;
    if (focus && level === 'neighbourhood') {
      set = neighbourhood(focus, edges.filter((e) => showTechnical || e.kind === 'declared'), 2);
    }
    if (filter !== 'all') {
      const keep = new Set(modules.filter((m) => m.status === filter).map((m) => m.module.name));
      set = set ? new Set([...set].filter((x) => keep.has(x))) : keep;
      if (focus) set.add(focus);
    }
    if (needle) {
      const hit = new Set(
        modules
          .filter((m) => `${moduleLabel(t, m.module.name, m.module.display_name)} ${m.module.name}`.toLowerCase().includes(needle))
          .map((m) => m.module.name),
      );
      set = set ? new Set([...set].filter((x) => hit.has(x))) : hit;
    }
    return set;
  }, [focus, level, edges, showTechnical, filter, modules, needle, t]);

  // A module selected on the map lights the parties who work in it.
  const litByModule = useMemo(() => (hovered ?? focus ? new Set([(hovered ?? focus) as string]) : null), [hovered, focus]);

  const select = (module: string) => {
    setLevel('neighbourhood');
    navigate(`/data-paths/${encodeURIComponent(module)}`);
  };
  const toPlatform = () => {
    setLevel('platform');
    if (search.get('focus')) {
      search.delete('focus');
      setSearch(search, { replace: true });
    }
  };

  const focusLabel = focus ? moduleLabel(t, focus) : null;
  const levelTabs = [
    ...(focus
      ? [
          { id: 'module' as const, label: t('data_paths.level_module', { defaultValue: 'Module path' }) },
          { id: 'neighbourhood' as const, label: t('data_paths.level_neighbourhood', { defaultValue: 'Neighbourhood' }) },
        ]
      : []),
    { id: 'platform' as const, label: t('data_paths.level_platform', { defaultValue: 'Whole platform' }) },
  ];

  const filters: { id: Filter; label: string; n: number | null }[] = [
    { id: 'all', label: t('data_paths.filter_all', { defaultValue: 'All modules' }), n: modules.length },
    { id: 'with_data', label: t('data_paths.filter_with_data', { defaultValue: 'With data' }), n: tally.with_data },
    { id: 'empty', label: t('data_paths.filter_empty', { defaultValue: 'Installed, empty' }), n: tally.empty },
    { id: 'not_installed', label: t('data_paths.filter_not_installed', { defaultValue: 'Not installed' }), n: tally.not_installed },
  ];

  return (
    <div className="space-y-4" data-testid="data-paths-page">
      <PageHeader
        srTitle={t('data_paths.button', { defaultValue: 'Data paths' })}
        subtitle={
          focusLabel
            ? t('data_paths.drawer_title', { defaultValue: 'Data paths: {{module}}', module: focusLabel })
            : t('data_paths.map_title', { defaultValue: 'Platform data map' })
        }
      />
      {!projectId && (
        <p className="text-sm text-content-tertiary">
          {t('data_paths.subtitle_no_project', { defaultValue: 'Pick a project to see live numbers' })}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <TabBar<Level>
          tabs={levelTabs}
          activeId={level}
          onChange={(next) => (next === 'platform' ? toPlatform() : setLevel(next))}
          ariaLabel={t('data_paths.level_aria', { defaultValue: 'Zoom level' })}
          variant="segmented"
          size="sm"
          idPrefix="dp-level"
        />
        {level !== 'module' && (
          <label className="relative">
            <span className="sr-only">{t('data_paths.search', { defaultValue: 'Find a module' })}</span>
            <Search size={14} className="pointer-events-none absolute start-2.5 top-1/2 -translate-y-1/2 text-content-tertiary" aria-hidden />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('data_paths.search', { defaultValue: 'Find a module' })}
              className="h-8 w-56 rounded-lg border border-border bg-surface-primary ps-8 pe-2 text-sm text-content-primary focus:border-oe-blue focus:outline-none"
              data-testid="dp-search"
            />
          </label>
        )}
        {level !== 'module' && (
          <label className="flex items-center gap-1.5 text-sm text-content-secondary">
            <input type="checkbox" checked={showTechnical} onChange={(e) => setShowTechnical(e.target.checked)} />
            {t('data_paths.show_all_links', { defaultValue: 'Show all links' })}
          </label>
        )}
      </div>

      {level !== 'module' && (
        <div className="flex flex-wrap gap-2" role="group" aria-label={t('data_paths.filter_aria', { defaultValue: 'Project data map' })}>
          {filters.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setFilter(f.id)}
              aria-pressed={filter === f.id}
              className={clsx(
                'inline-flex h-7 items-center gap-1.5 rounded-full border px-3 text-xs transition-colors duration-150',
                filter === f.id ? 'border-oe-blue bg-oe-blue-subtle text-oe-blue-text' : 'border-border-light text-content-secondary hover:bg-surface-secondary',
              )}
              data-testid={`dp-filter-${f.id}`}
            >
              {f.label}
              {f.n !== null && <span className="tabular-nums text-content-tertiary">{formatNumber(f.n)}</span>}
            </button>
          ))}
        </div>
      )}

      {map.isError && (
        <p className="text-sm text-semantic-error">{t('data_paths.load_failed', { defaultValue: 'The data paths could not be loaded.' })}</p>
      )}

      {/* The map takes the full width so it reads without zooming; health and people sit below. */}
      <div className="space-y-4">
        <div className="min-w-0 space-y-4">
          {level === 'module' && focus ? (
            <div className="rounded-xl border border-border-light bg-surface-primary p-4">
              {flow?.why && <p className="mb-3 text-sm text-content-secondary">{flow.why}</p>}
              {paths.isLoading && <div className="h-64 animate-pulse rounded-xl bg-surface-secondary" />}
              {flow && <DataPathsFlow model={flow} />}
              {flow && (
                <details className="mt-4">
                  <summary className="cursor-pointer text-sm text-content-secondary">{t('data_paths.tab_list', { defaultValue: 'List' })}</summary>
                  <div className="mt-2">
                    <DataPathsList model={flow} />
                  </div>
                </details>
              )}
            </div>
          ) : map.isLoading ? (
            <div className="h-[620px] animate-pulse rounded-xl bg-surface-secondary" />
          ) : (
            <PlatformMapCanvas
              modules={modules}
              edges={edges}
              focus={focus}
              visible={visible}
              lit={partyLit}
              hovered={hovered}
              onHover={setHovered}
              onSelect={select}
              showTechnical={showTechnical}
            />
          )}
        </div>

        <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <HealthPanel health={map.data?.health ?? []} hasProject={!!projectId} />
          <section className="rounded-xl border border-border-light bg-surface-primary p-3">
            <h3 className="mb-2 text-sm font-semibold text-content-primary">{t('data_paths.people_title', { defaultValue: 'People on this project' })}</h3>
            {projectId ? (
              <PartiesHoneycomb
                parties={parties.data?.parties ?? []}
                litModules={partyLit ? null : litByModule}
                onHoverParty={(mods) => setPartyLit(mods && mods.length ? new Set(mods) : null)}
                onSelectParty={(p: Party) => {
                  if (p.modules[0]) select(p.modules[0]);
                }}
              />
            ) : (
              <p className="text-xs text-content-tertiary">
                {t('data_paths.subtitle_no_project', { defaultValue: 'Pick a project to see live numbers' })}
              </p>
            )}
          </section>
        </div>
        <MapList modules={modules} edges={edges} visible={visible} />
      </div>
    </div>
  );
}

function HealthPanel({ health, hasProject }: { health: HealthItem[]; hasProject: boolean }) {
  const { t } = useTranslation();
  if (!hasProject) return null;
  return (
    <section className="rounded-xl border border-border-light bg-surface-primary p-3" data-testid="dp-health">
      <h3 className="mb-2 text-sm font-semibold text-content-primary">{t('data_paths.health_title', { defaultValue: 'Project health' })}</h3>
      {health.length === 0 ? (
        <p className="flex items-center gap-1.5 text-xs text-semantic-success">
          <CircleCheck size={14} aria-hidden />
          {t('data_paths.health_ok', { defaultValue: 'Every critical input has data.' })}
        </p>
      ) : (
        <ul className="space-y-2.5">
          {health.map((h) => {
            const upstream = h.upstream || h.source;
            const downstream = h.downstream || h.module;
            const sentence = h.missing
              ? t(h.missing, { defaultValue: '' })
              : t('data_paths.health_missing_plain', {
                  defaultValue: 'Nothing has reached {{module}} from {{source}} yet',
                  module: moduleLabel(t, downstream),
                  source: moduleLabel(t, upstream),
                });
            const fixRoute = moduleMeta(downstream).route;
            return (
              <li key={h.path_id} className="flex gap-2 text-xs" data-testid="dp-health-item">
                <CircleAlert size={14} className="mt-0.5 shrink-0 text-semantic-error" aria-hidden />
                <span className="min-w-0 flex-1">
                  <Link to={`/data-paths/${encodeURIComponent(downstream)}`} className="font-medium text-content-primary hover:text-oe-blue">
                    {sentence}
                  </Link>
                  {h.breaks && <span className="block text-content-tertiary">{t(h.breaks, { defaultValue: '' })}</span>}
                </span>
                {fixRoute && (
                  <Link
                    to={fixRoute}
                    className="shrink-0 self-start rounded-md border border-border-light px-2 py-0.5 font-medium text-oe-blue hover:bg-surface-secondary"
                    aria-label={t('data_paths.health_fix_aria', { defaultValue: 'Fix in {{module}}', module: moduleLabel(t, downstream) })}
                  >
                    {t('data_paths.health_fix', { defaultValue: 'Fix' })}
                  </Link>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/** The accessible equivalent of the canvas: every visible module, its count and where its data goes. */
function MapList({ modules, edges, visible }: { modules: CanvasModule[]; edges: { source: string; target: string; kind: string; count: number | null }[]; visible: Set<string> | null }) {
  const { t } = useTranslation();
  const shown = modules.filter((m) => !visible || visible.has(m.module.name));
  if (!shown.length) return null;
  return (
    <details className="rounded-xl border border-border-light bg-surface-primary p-3">
      <summary className="cursor-pointer text-sm text-content-secondary">
        {t('data_paths.map_list', { defaultValue: 'Map as a list' })}
      </summary>
      <ul className="mt-2 divide-y divide-border-light text-sm">
        {shown.map((m) => {
          const out = edges.filter((e) => e.kind === 'declared' && e.source === m.module.name);
          return (
            <li key={m.module.name} className="py-1.5">
              <Link to={`/data-paths/${encodeURIComponent(m.module.name)}`} className="font-medium text-content-primary hover:text-oe-blue">
                {moduleLabel(t, m.module.name, m.module.display_name)}
              </Link>
              {m.module.count !== null && <span className="ms-2 tabular-nums text-content-tertiary">{formatNumber(m.module.count)}</span>}
              {out.length > 0 && (
                <span className="block text-xs text-content-tertiary">
                  {fmtList(out.map((e) => moduleLabel(t, e.target)))}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </details>
  );
}
