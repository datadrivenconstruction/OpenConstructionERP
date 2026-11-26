// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Platform map tab: every module with a data paths declaration, in columns by
// project phase (the phase comes from the API), with the selected module's
// sources (IN) and consumers (OUT) marked.

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Map as MapIcon } from 'lucide-react';

import { EmptyState } from '@/shared/ui/EmptyState';
import { formatNumber } from '@/shared/lib/formatters';

import type { MapModule, PlatformMap } from './api';
import { moduleLabel } from './flowModel';
import { phaseColumns, type Relation } from './pathsModel';

interface Props {
  map: PlatformMap;
  focus: string | null;
  query: string;
  onSelect: (module: string) => void;
}

export function PhaseMapView({ map, focus, query, onSelect }: Props) {
  const { t } = useTranslation();
  const label = (m: MapModule) => moduleLabel(t, m.name, m.display_name);
  const columns = useMemo(() => phaseColumns(map, focus, label), [map, focus, t]); // eslint-disable-line react-hooks/exhaustive-deps
  const needle = query.trim().toLowerCase();
  const focusName = focus ? moduleLabel(t, focus) : '';

  if (!columns.length) {
    return <EmptyState icon={<MapIcon size={40} />} title={t('data_paths.v2.map_empty', { defaultValue: 'No module has declared its data paths yet.' })} />;
  }
  const tag = (r: Relation) =>
    r === 'in' ? t('data_paths.v2.badge_in', { defaultValue: 'IN' }) : r === 'out' ? t('data_paths.v2.badge_out', { defaultValue: 'OUT' }) : null;

  return (
    <div className="space-y-3" data-testid="dp-phase-map">
      {focus && (
        <ul className="flex flex-wrap items-center gap-x-5 gap-y-1 text-xs text-content-secondary">
          <li className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-sm bg-oe-blue" aria-hidden />
            {t('data_paths.v2.legend_selected', { defaultValue: 'Selected module' })}
          </li>
          <li className="flex items-center gap-1.5">
            <span className="h-3 w-3 rounded-sm border border-oe-blue" aria-hidden />
            {t('data_paths.v2.legend_linked', { defaultValue: 'Reads from or feeds {{module}}', module: focusName })}
          </li>
          <li className="flex items-center gap-1.5">
            <span className="font-mono text-2xs font-medium text-oe-blue">{tag('in')}</span>
            {t('data_paths.v2.legend_in', { defaultValue: '{{module}} reads from it', module: focusName })}
          </li>
          <li className="flex items-center gap-1.5">
            <span className="font-mono text-2xs font-medium text-oe-blue">{tag('out')}</span>
            {t('data_paths.v2.legend_out', { defaultValue: 'It reads from {{module}}', module: focusName })}
          </li>
        </ul>
      )}
      <div className="flex gap-3 overflow-x-auto pb-2">
        {columns.map((col) => (
          <section
            key={col.phase}
            className="w-56 shrink-0 rounded-xl border border-border-light bg-surface-primary p-3"
            aria-labelledby={`dp-phase-${col.phase}`}
          >
            <h3 id={`dp-phase-${col.phase}`} className="mb-3 flex items-center justify-between text-sm font-semibold text-content-primary">
              {t(`data_paths.phase.${col.phase}`, { defaultValue: col.phase })}
              <span className="text-xs font-normal tabular-nums text-content-tertiary">{formatNumber(col.modules.length)}</span>
            </h3>
            <ul className="space-y-2">
              {col.modules.map(({ module: m, relation }) => {
                const hit = !needle || `${label(m)} ${m.name}`.toLowerCase().includes(needle);
                const badge = tag(relation);
                return (
                  <li key={m.name}>
                    <button
                      type="button"
                      onClick={() => onSelect(m.name)}
                      aria-current={relation === 'focus' ? 'true' : undefined}
                      className={clsx(
                        'flex w-full items-center gap-2 rounded-lg border px-2.5 py-2 text-start transition-colors duration-150',
                        relation === 'focus'
                          ? 'border-oe-blue bg-oe-blue text-content-inverse'
                          : relation
                            ? 'border-oe-blue/60 bg-surface-primary hover:bg-surface-secondary'
                            : 'border-border-light bg-surface-primary hover:bg-surface-secondary',
                        !hit && 'opacity-40',
                        !m.installed && 'border-dashed',
                      )}
                      data-testid={`dp-map-${m.name}`}
                    >
                      <span
                        className={clsx('h-1.5 w-1.5 shrink-0 rounded-full', relation === 'focus' ? 'bg-content-inverse' : relation ? 'bg-oe-blue' : 'bg-border')}
                        aria-hidden
                      />
                      <span className="min-w-0 flex-1">
                        <span className={clsx('block truncate text-xs font-medium', relation === 'focus' ? '' : relation ? 'text-content-primary' : 'text-content-secondary')}>
                          {label(m)}
                        </span>
                        <span className={clsx('block truncate font-mono text-2xs', relation === 'focus' ? 'opacity-80' : 'text-content-tertiary')}>{m.name}</span>
                      </span>
                      {m.count !== null && m.count > 0 && (
                        <span className={clsx('shrink-0 text-2xs tabular-nums', relation === 'focus' ? '' : 'text-content-tertiary')}>{formatNumber(m.count)}</span>
                      )}
                      {badge && relation !== 'focus' && (
                        <span className="shrink-0 rounded-sm bg-oe-blue-subtle px-1.5 py-0.5 font-mono text-2xs font-medium text-oe-blue-text">{badge}</span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
