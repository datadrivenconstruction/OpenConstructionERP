// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// /data-paths and /data-paths/:module: three views of the same declarations.
// Module: where one module gets its data and who reads it. Field trace: where
// one parameter comes from and what it changes. Platform map: every declared
// module by project phase. The tab, module and field live in the URL.

import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { CircleAlert, CircleCheck, LayoutGrid, Map as MapIcon, Route, Search, Waypoints } from 'lucide-react';

import { PageHeader } from '@/shared/ui/PageHeader';
import { TabBar } from '@/shared/ui/TabBar';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { Skeleton } from '@/shared/ui/Skeleton';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

import { usePlatformMap, type HealthItem } from './api';
import { moduleLabel } from './flowModel';
import { FieldTraceView } from './FieldTraceView';
import { ModulePathsView } from './ModulePathsView';
import { PhaseMapView } from './PhaseMapView';
import { moduleMeta } from './moduleMeta';

type View = 'module' | 'trace' | 'map';
const VIEWS: readonly View[] = ['module', 'trace', 'map'];

export function DataPathsPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const params = useParams<{ module?: string }>();
  const [search] = useSearchParams();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const focus = params.module ?? search.get('focus') ?? null;
  const asked = search.get('view') as View | null;
  const view: View = asked && VIEWS.includes(asked) ? asked : focus ? 'module' : 'map';
  const field = search.get('field');
  const [query, setQuery] = useState('');

  const map = usePlatformMap(projectId);

  const declared = useMemo(
    () =>
      (map.data?.modules ?? [])
        .filter((m) => m.declared || m.name === focus)
        .map((m) => ({ name: m.name, label: moduleLabel(t, m.name, m.display_name) }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [map.data, focus, t],
  );

  const go = (next: { module?: string | null; view?: View; field?: string | null }) => {
    const mod = next.module === undefined ? focus : next.module;
    const qs = new URLSearchParams();
    const v = next.view ?? view;
    if (v !== (mod ? 'module' : 'map')) qs.set('view', v);
    const f = next.field === undefined ? field : next.field;
    if (f && v === 'trace') qs.set('field', f);
    const tail = qs.toString();
    navigate(`/data-paths${mod ? `/${encodeURIComponent(mod)}` : ''}${tail ? `?${tail}` : ''}`);
  };
  const setView = (v: View) => go({ view: v });

  const focusLabel = focus ? moduleLabel(t, focus) : '';
  const subtitle =
    view === 'map'
      ? t('data_paths.v2.map_subtitle', { defaultValue: 'Modules with a data paths declaration, by project phase' })
      : view === 'trace'
        ? t('data_paths.v2.trace_subtitle', { defaultValue: 'Where a field of {{module}} comes from and what it changes', module: focusLabel })
        : focus
          ? t('data_paths.v2.module_subtitle', { defaultValue: 'Where {{module}} gets its data and who reads it', module: focusLabel })
          : t('data_paths.map_title', { defaultValue: 'Platform data map' });

  const tabs = [
    { id: 'module' as const, label: t('data_paths.v2.tab_module', { defaultValue: 'Module' }), icon: <LayoutGrid size={14} /> },
    { id: 'trace' as const, label: t('data_paths.v2.tab_trace', { defaultValue: 'Field trace' }), icon: <Route size={14} /> },
    { id: 'map' as const, label: t('data_paths.v2.tab_map', { defaultValue: 'Platform map' }), icon: <MapIcon size={14} /> },
  ];

  const pickModule = (
    <label className="flex items-center gap-2 text-sm text-content-secondary">
      <span className="sr-only">{t('data_paths.v2.pick_module_placeholder', { defaultValue: 'Choose a module' })}</span>
      <select
        className="oe-select w-64"
        value={focus ?? ''}
        onChange={(e) => go({ module: e.target.value || null, view: view === 'map' ? 'module' : view, field: null })}
        data-testid="dp-module-select"
      >
        <option value="">{t('data_paths.v2.pick_module_placeholder', { defaultValue: 'Choose a module' })}</option>
        {declared.map((m) => (
          <option key={m.name} value={m.name}>
            {m.label}
          </option>
        ))}
      </select>
    </label>
  );

  return (
    <div className="space-y-5 animate-fade-in" data-testid="data-paths-page">
      <PageHeader srTitle={t('data_paths.button', { defaultValue: 'Data paths' })} subtitle={subtitle} />
      {!projectId && (
        <p className="text-sm text-content-tertiary">{t('data_paths.subtitle_no_project', { defaultValue: 'Pick a project to see live numbers' })}</p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <TabBar<View>
          tabs={tabs}
          activeId={view}
          onChange={setView}
          ariaLabel={t('data_paths.v2.tabs_aria', { defaultValue: 'Data paths view' })}
          variant="segmented"
          size="sm"
          idPrefix="dp-view"
        />
        {pickModule}
        {view === 'map' && (
          <label className="relative">
            <span className="sr-only">{t('data_paths.search', { defaultValue: 'Find a module' })}</span>
            <Search size={14} className="pointer-events-none absolute start-2.5 top-1/2 -translate-y-1/2 text-content-tertiary" aria-hidden />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t('data_paths.search', { defaultValue: 'Find a module' })}
              className="oe-input w-56 ps-8"
              data-testid="dp-search"
            />
          </label>
        )}
      </div>

      {view === 'map' ? (
        map.isLoading ? (
          <Skeleton height={520} className="rounded-xl" />
        ) : map.isError || !map.data ? (
          <ErrorState title={t('data_paths.load_failed', { defaultValue: 'The data paths could not be loaded.' })} onRetry={() => void map.refetch()} />
        ) : (
          <>
            <PhaseMapView map={map.data} focus={focus} query={query} onSelect={(m) => go({ module: m, view: 'module', field: null })} />
            <HealthPanel health={map.data.health} hasProject={!!projectId} />
          </>
        )
      ) : !focus ? (
        <EmptyState
          icon={<Waypoints size={40} />}
          title={t('data_paths.v2.pick_module_placeholder', { defaultValue: 'Choose a module' })}
          description={t('data_paths.v2.no_module_body', { defaultValue: 'Pick a module above or on the platform map to see where its data comes from and who reads it.' })}
          action={{ label: t('data_paths.v2.tab_map', { defaultValue: 'Platform map' }), onClick: () => setView('map') }}
        />
      ) : view === 'trace' ? (
        <FieldTraceView module={focus} projectId={projectId} field={field} onField={(f) => go({ field: f })} />
      ) : (
        <ModulePathsView module={focus} projectId={projectId} onOpen={(route) => navigate(route)} onTrace={(f) => go({ view: 'trace', field: f })} />
      )}
    </div>
  );
}

function HealthPanel({ health, hasProject }: { health: HealthItem[]; hasProject: boolean }) {
  const { t } = useTranslation();
  if (!hasProject) return null;
  return (
    <section className="rounded-xl border border-border-light bg-surface-primary p-4" data-testid="dp-health">
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
                    className="shrink-0 self-start rounded-lg border border-border-light px-2 py-0.5 font-medium text-oe-blue hover:bg-surface-secondary"
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
