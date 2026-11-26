// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Module tab: sources left, the module with its parameters in the centre,
// consumers right, curved labelled links, and a detail panel for the selected
// link. Cards are buttons in reading order, so Tab and arrows walk the paths.

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import clsx from 'clsx';
import { ArrowRight, Boxes, Clock, TriangleAlert, Waypoints, X } from 'lucide-react';

import { Button } from '@/shared/ui/Button';
import { EmptyState } from '@/shared/ui/EmptyState';
import { ErrorState } from '@/shared/ui/ErrorState';
import { Skeleton } from '@/shared/ui/Skeleton';
import { formatNumber } from '@/shared/lib/formatters';

import { useModulePaths, type Importance, type ModulePaths, type PathOut } from './api';
import { moduleLabel, stateText } from './flowModel';
import { moduleMeta } from './moduleMeta';
import { drivingFields, freshnessOf, layoutDiagram, SIDE_CARD_H } from './pathsModel';

export function importanceText(t: TFunction, importance: Importance): string {
  return String(t(`data_paths.importance_${importance}`, { defaultValue: importance }));
}

export function ImportanceBadge({ importance }: { importance: Importance }) {
  const { t } = useTranslation();
  if (importance === 'supporting') return null;
  return (
    <span
      className={clsx(
        'shrink-0 rounded-sm px-1.5 py-0.5 text-2xs font-medium',
        importance === 'critical' ? 'bg-semantic-error-bg text-semantic-error' : 'bg-semantic-warning-bg text-semantic-warning',
      )}
    >
      {importanceText(t, importance)}
    </span>
  );
}

export function ModuleIcon({ module, size = 'md' }: { module: string; size?: 'md' | 'lg' }) {
  const meta = moduleMeta(module);
  const Icon = meta.icon ?? Boxes;
  return (
    <span
      className={clsx(
        'flex shrink-0 items-center justify-center rounded-lg bg-surface-secondary',
        size === 'lg' ? 'h-11 w-11' : 'h-9 w-9',
      )}
      style={{ color: meta.tone }}
      aria-hidden
    >
      <Icon size={size === 'lg' ? 22 : 18} />
    </span>
  );
}

/** Short text drawn on a link: the declared edge label, else the path's own label. */
export function edgeText(t: TFunction, path: PathOut): string {
  const key = path.edge || path.label;
  return key ? String(t(key, { defaultValue: path.entity })) : path.entity;
}

interface Props {
  module: string;
  projectId: string | null;
  enabled?: boolean;
  /** Opens a module's register; the page navigates, the drawer closes first. */
  onOpen: (route: string) => void;
  /** Opens the field trace of one parameter; absent where there is no trace tab. */
  onTrace?: (field: string) => void;
}

export function ModulePathsView({ module, projectId, enabled = true, onOpen, onTrace }: Props) {
  const { t } = useTranslation();
  const query = useModulePaths(module, projectId, enabled);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => setSelected(null), [module]);
  const data = query.data;
  // The critical link reads first, as on the approved layout.
  useEffect(() => {
    if (!data || selected) return;
    const first = data.paths.find((p) => p.importance === 'critical') ?? data.paths[0];
    if (first) setSelected(first.id);
  }, [data, selected]);

  if (query.isLoading) {
    return (
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]" aria-busy="true">
        <Skeleton height={480} className="rounded-xl" />
        <Skeleton height={480} className="rounded-xl" />
      </div>
    );
  }
  if (query.isError || !data) {
    return <ErrorState title={t('data_paths.load_failed', { defaultValue: 'The data paths could not be loaded.' })} onRetry={() => void query.refetch()} />;
  }
  const name = moduleLabel(t, module);
  if (!data.paths.length) {
    return (
      <div className="space-y-4">
        <CentreCard data={data} onTrace={onTrace} />
        <EmptyState
          icon={<Waypoints size={40} />}
          title={t('data_paths.v2.no_paths_title', { defaultValue: 'No data paths declared for {{module}}', module: name })}
          description={t('data_paths.v2.no_paths_body', { defaultValue: 'This module has no declared sources or consumers yet.' })}
        />
      </div>
    );
  }
  const path = data.paths.find((p) => p.id === selected) ?? null;
  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
      <Diagram data={data} selected={selected} onSelect={setSelected} onTrace={onTrace} />
      {path ? (
        <PathDetail data={data} path={path} onClose={() => setSelected(null)} onOpen={onOpen} />
      ) : (
        <p className="rounded-xl border border-border-light bg-surface-primary p-4 text-sm text-content-tertiary">
          {t('data_paths.v2.pick_path', { defaultValue: 'Select a link to see its fields and freshness.' })}
        </p>
      )}
    </div>
  );
}

function Diagram({ data, selected, onSelect, onTrace }: { data: ModulePaths; selected: string | null; onSelect: (id: string | null) => void; onTrace?: (field: string) => void }) {
  const { t } = useTranslation();
  const wrap = useRef<HTMLDivElement>(null);
  const centreRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [centreH, setCentreH] = useState(320);

  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return undefined;
    const ro = new ResizeObserver(() => {
      setWidth(el.clientWidth);
      if (centreRef.current) setCentreH(centreRef.current.offsetHeight);
    });
    ro.observe(el);
    if (centreRef.current) ro.observe(centreRef.current);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const geo = useMemo(() => layoutDiagram(width, centreH, data.paths), [width, centreH, data.paths]);
  const ins = data.paths.filter((p) => p.direction === 'in');
  const outs = data.paths.filter((p) => p.direction === 'out');
  const order = [...ins, ...outs];

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      onSelect(null);
      return;
    }
    if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return;
    const at = order.findIndex((p) => p.id === selected);
    const next = order[Math.min(order.length - 1, Math.max(0, at + (e.key === 'ArrowDown' ? 1 : -1)))];
    if (!next) return;
    e.preventDefault();
    onSelect(next.id);
    wrap.current?.querySelector<HTMLButtonElement>(`[data-path-id="${CSS.escape(next.id)}"]`)?.focus();
  };

  const heading = (key: string, def: string, n?: number) => (
    <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
      {t(key, { defaultValue: def })}
      {n !== undefined && <span className="tabular-nums"> · {formatNumber(n)}</span>}
    </span>
  );

  return (
    <div
      ref={wrap}
      onKeyDown={onKey}
      role="group"
      aria-label={t('data_paths.v2.diagram_aria', { defaultValue: 'Data paths of {{module}}', module: moduleLabel(t, data.module) })}
      className="min-w-0"
      data-testid="dp-module-diagram"
    >
      {geo.wide ? (
        <>
          <div className="mb-3 grid grid-cols-3" style={{ columnGap: geo.centre.x - geo.centre.w }}>
            {heading('data_paths.v2.sources', 'Sources', ins.length)}
            {heading('data_paths.v2.tab_module', 'Module')}
            {heading('data_paths.v2.step_consumers', 'Consumers', outs.length)}
          </div>
          <div className="relative" style={{ height: geo.height }}>
            <svg className="pointer-events-none absolute inset-0 overflow-visible" width={width} height={geo.height} aria-hidden>
              {geo.links.map((l) => {
                const on = l.path.id === selected;
                return (
                  <path
                    key={l.path.id}
                    d={l.d}
                    fill="none"
                    strokeWidth={on ? 2.5 : 1.5}
                    strokeDasharray={l.path.live.state === 'not_installed' ? '4 4' : undefined}
                    className={on ? 'stroke-oe-blue' : 'stroke-border'}
                  />
                );
              })}
            </svg>
            {geo.links.map((l) => (
              <EdgePill key={`p-${l.path.id}`} path={l.path} x={l.pill.x} y={l.pill.y} on={l.path.id === selected} onSelect={onSelect} />
            ))}
            <div ref={centreRef} className="absolute" style={{ left: geo.centre.x, top: geo.centre.y, width: geo.centre.w }}>
              <CentreCard data={data} onTrace={onTrace} />
            </div>
            {geo.links.map((l) => (
              <div key={`c-${l.path.id}`} className="absolute" style={{ left: l.card.x, top: l.card.y, width: l.card.w, height: SIDE_CARD_H }}>
                <SideCard path={l.path} on={l.path.id === selected} onSelect={onSelect} />
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="space-y-3">
          {heading('data_paths.v2.sources', 'Sources', ins.length)}
          {ins.map((p) => (
            <SideCard key={p.id} path={p} on={p.id === selected} onSelect={onSelect} stacked />
          ))}
          <div ref={centreRef}>
            <CentreCard data={data} onTrace={onTrace} />
          </div>
          {heading('data_paths.v2.step_consumers', 'Consumers', outs.length)}
          {outs.map((p) => (
            <SideCard key={p.id} path={p} on={p.id === selected} onSelect={onSelect} stacked />
          ))}
        </div>
      )}
    </div>
  );
}

function EdgePill({ path, x, y, on, onSelect }: { path: PathOut; x: number; y: number; on: boolean; onSelect: (id: string) => void }) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      tabIndex={-1}
      onClick={() => onSelect(path.id)}
      className={clsx(
        'absolute max-w-[140px] -translate-x-1/2 -translate-y-1/2 truncate rounded-full border px-2.5 py-0.5 text-xs transition-colors duration-150',
        on ? 'border-oe-blue bg-oe-blue text-content-inverse' : 'border-border-light bg-surface-primary text-content-secondary hover:border-oe-blue',
      )}
      style={{ left: x, top: y }}
    >
      {edgeText(t, path)}
    </button>
  );
}

function SideCard({ path, on, onSelect, stacked = false }: { path: PathOut; on: boolean; onSelect: (id: string) => void; stacked?: boolean }) {
  const { t } = useTranslation();
  const count = path.live.count;
  const state = path.live.state;
  return (
    <button
      type="button"
      data-path-id={path.id}
      aria-pressed={on}
      onClick={() => onSelect(path.id)}
      className={clsx(
        'flex w-full flex-col rounded-xl border bg-surface-primary p-3 text-start transition-colors duration-150 hover:shadow-sm',
        stacked ? '' : 'h-full',
        on ? 'border-oe-blue ring-2 ring-oe-blue/30' : 'border-border-light hover:border-border',
      )}
    >
      <span className="flex w-full items-start gap-2.5">
        <ModuleIcon module={path.module} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-semibold text-content-primary">{moduleLabel(t, path.module)}</span>
          <span className="block truncate font-mono text-2xs text-content-tertiary">{path.module}</span>
        </span>
        <ImportanceBadge importance={path.importance} />
      </span>
      <span className="mt-auto flex w-full items-center gap-2 pt-2 text-xs text-content-secondary">
        <span className="min-w-0 flex-1 truncate">{path.label ? t(path.label, { defaultValue: path.entity }) : path.entity}</span>
        {state !== 'ok' && state !== 'unknown' ? (
          <span className={clsx('shrink-0', state === 'stale' ? 'text-semantic-warning' : 'text-content-tertiary')}>{stateText(t, state)}</span>
        ) : count !== null ? (
          <span className="shrink-0 tabular-nums text-content-tertiary">{formatNumber(count)}</span>
        ) : null}
      </span>
    </button>
  );
}

function CentreCard({ data, onTrace }: { data: ModulePaths; onTrace?: (field: string) => void }) {
  const { t } = useTranslation();
  return (
    <section className="rounded-xl border border-oe-blue/40 bg-surface-primary p-4 shadow-sm" data-testid="dp-centre">
      <div className="flex items-start gap-3">
        <ModuleIcon module={data.module} size="lg" />
        <div className="min-w-0">
          <h3 className="truncate text-lg font-semibold text-content-primary">{moduleLabel(t, data.module)}</h3>
          <p className="truncate font-mono text-2xs text-content-tertiary">{data.module}</p>
        </div>
      </div>
      {data.why && <p className="mt-3 text-sm text-content-secondary">{t(data.why, { defaultValue: '' })}</p>}
      {data.entities.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-1.5">
          {data.entities.map((e) => (
            <li key={e.id} className="rounded-sm bg-surface-secondary px-2 py-0.5 text-xs text-content-secondary">
              {e.label ? t(e.label, { defaultValue: e.model }) : e.model}
              {e.live.count !== null && <span className="ms-1 tabular-nums text-content-tertiary">{formatNumber(e.live.count)}</span>}
            </li>
          ))}
        </ul>
      )}
      {data.parameters.length > 0 && (
        <>
          <p className="mt-4 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
            {t('data_paths.v2.parameters', { defaultValue: 'Parameters' })}
          </p>
          <ul className="mt-1 divide-y divide-border-light">
            {data.parameters.map((p) => {
              const body = (
                <>
                  <span className="min-w-0 truncate text-content-secondary">{p.label ? t(p.label, { defaultValue: p.field }) : p.field}</span>
                  <span className="shrink-0 font-mono text-xs text-content-primary">{p.field}</span>
                </>
              );
              return (
                <li key={p.field}>
                  {onTrace ? (
                    <button
                      type="button"
                      onClick={() => onTrace(p.field)}
                      className="flex w-full items-center justify-between gap-3 py-2 text-start text-sm hover:text-oe-blue"
                      title={t('data_paths.v2.trace_this', { defaultValue: 'Trace this field' })}
                    >
                      {body}
                    </button>
                  ) : (
                    <div className="flex items-center justify-between gap-3 py-2 text-sm">{body}</div>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}

function PathDetail({ data, path, onClose, onOpen }: { data: ModulePaths; path: PathOut; onClose: () => void; onOpen: (route: string) => void }) {
  const { t } = useTranslation();
  const [src, dst] = path.direction === 'in' ? [path.module, data.module] : [data.module, path.module];
  const fields = drivingFields(data, path);
  const fresh = freshnessOf(data, path);
  const route = path.route || moduleMeta(path.module).route;
  const other = moduleLabel(t, path.module);
  const row = (key: string, def: string, value: string) =>
    value ? (
      <div>
        <dt className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">{t(key, { defaultValue: def })}</dt>
        <dd className="mt-0.5 break-all font-mono text-xs text-content-primary">{value}</dd>
      </div>
    ) : null;
  return (
    <aside className="flex flex-col gap-4 rounded-xl border border-border-light bg-surface-primary p-4 xl:sticky xl:top-4" data-testid="dp-path-detail" aria-live="polite">
      <div className="flex items-center justify-between">
        <span className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">
          {t('data_paths.v2.selected_path', { defaultValue: 'Selected path' })}
        </span>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label={t('common.close', { defaultValue: 'Close' })} icon={<X size={14} />} />
      </div>
      <div className="flex items-center gap-2">
        <ModuleIcon module={src} />
        <ArrowRight size={14} className="text-content-tertiary rtl:rotate-180" aria-hidden />
        <ModuleIcon module={dst} />
        <span className="flex-1" />
        <ImportanceBadge importance={path.importance} />
      </div>
      <div>
        <h3 className="text-lg font-semibold text-content-primary">
          {t('data_paths.v2.path_title', { defaultValue: '{{source}} to {{target}}', source: moduleLabel(t, src), target: moduleLabel(t, dst) })}
        </h3>
        <p className="mt-1 text-sm text-content-secondary">{edgeText(t, path)}</p>
      </div>
      <dl className="space-y-3">
        {row('data_paths.v2.entity', 'Entity', path.entity)}
        {row('data_paths.v2.linked_by', 'Linked by', path.via)}
        {row('data_paths.v2.route', 'Route', route ?? '')}
      </dl>
      {path.breaks && (
        <p className="flex gap-2 rounded-lg bg-semantic-error-bg p-3 text-sm text-semantic-error">
          <TriangleAlert size={16} className="mt-0.5 shrink-0" aria-hidden />
          {t(path.breaks, { defaultValue: '' })}
        </p>
      )}
      {fields.length > 0 && (
        <div>
          <p className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">{t('data_paths.v2.fields_drive', { defaultValue: 'Fields that drive it' })}</p>
          <ul className="mt-2 space-y-1.5">
            {fields.map((f) => (
              <li key={f.field} className="flex items-start gap-2 font-mono text-xs">
                <span className="min-w-0 flex-1 break-all text-content-secondary">{f.field}</span>
                <ArrowRight size={12} className="mt-0.5 shrink-0 text-content-tertiary rtl:rotate-180" aria-hidden />
                <span className="min-w-0 flex-1 break-all text-content-primary">{f.drives.join(', ')}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <p className="text-2xs font-medium uppercase tracking-wide text-content-tertiary">{t('data_paths.v2.freshness', { defaultValue: 'Freshness check' })}</p>
        {fresh.length ? (
          fresh.map((s) => (
            <div key={`${s.source}-${s.copy_field}`} className="mt-2 rounded-lg border border-border-light p-3">
              <p className="flex items-center gap-2 text-sm font-medium text-content-primary">
                <Clock size={14} className="shrink-0 text-semantic-warning" aria-hidden />
                {s.label ? t(s.label, { defaultValue: '' }) : t('data_paths.v2.stale_rule', { defaultValue: 'Changed after it was sent' })}
              </p>
              <p className="mt-1 break-all font-mono text-xs text-content-secondary">
                {s.source} &gt; {s.copy_field}
              </p>
              {s.count !== null && s.count > 0 && (
                <p className="mt-1 text-xs text-semantic-warning">
                  {t('data_paths.v2.stale_rows', { defaultValue: 'Records changed since the copy: {{count}}', count: s.count })}
                </p>
              )}
            </div>
          ))
        ) : (
          <p className="mt-1 text-xs text-content-tertiary">{t('data_paths.v2.no_freshness', { defaultValue: 'No freshness rule is declared for this path.' })}</p>
        )}
      </div>
      {route && (
        <Button variant="primary" onClick={() => onOpen(route)} icon={<ArrowRight size={16} className="rtl:rotate-180" />} iconPosition="right">
          {t('data_paths.v2.open_module', { defaultValue: 'Open {{module}}', module: other })}
        </Button>
      )}
    </aside>
  );
}
