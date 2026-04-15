/**
 * Layer visibility toggle panel for the DXF viewer.
 */

import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { Eye, EyeOff, Search } from 'lucide-react';
import clsx from 'clsx';
import type { DxfLayer } from '../api';
import { resolveColor } from '../lib/dxf-renderer';

interface Props {
  layers: DxfLayer[];
  visibleLayers: Set<string>;
  onToggleLayer: (name: string) => void;
  onShowAll: () => void;
  onHideAll: () => void;
}

export function LayerPanel({ layers, visibleLayers, onToggleLayer, onShowAll, onHideAll }: Props) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    if (!search) return layers;
    const q = search.toLowerCase();
    return layers.filter((l) => l.name.toLowerCase().includes(q));
  }, [layers, search]);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground">
          {t('dwg_takeoff.layers', 'Layers')}
        </h3>
        <div className="flex gap-1">
          <button
            onClick={onShowAll}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            title={t('dwg_takeoff.show_all', 'Show all')}
          >
            {t('dwg_takeoff.all_on', 'All on')}
          </button>
          <span className="text-muted-foreground">/</span>
          <button
            onClick={onHideAll}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            title={t('dwg_takeoff.hide_all', 'Hide all')}
          >
            {t('dwg_takeoff.all_off', 'All off')}
          </button>
        </div>
      </div>

      <div className="relative">
        <Search size={14} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('dwg_takeoff.search_layers', 'Filter layers...')}
          className="w-full rounded-md border border-border bg-surface-secondary py-1 pl-7 pr-2 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-oe-blue"
        />
      </div>

      <div className="flex flex-col gap-0.5 overflow-y-auto max-h-[400px]">
        {filtered.map((layer) => {
          const visible = visibleLayers.has(layer.name);
          return (
            <button
              key={layer.name}
              onClick={() => onToggleLayer(layer.name)}
              className={clsx(
                'flex items-center gap-2 rounded px-2 py-1 text-xs transition-colors',
                visible
                  ? 'text-foreground hover:bg-surface-secondary'
                  : 'text-muted-foreground hover:bg-surface-secondary',
              )}
            >
              {visible ? <Eye size={13} /> : <EyeOff size={13} />}
              <span
                className="h-2.5 w-2.5 rounded-full flex-shrink-0"
                style={{ backgroundColor: resolveColor(layer.color) }}
              />
              <span className="truncate flex-1 text-left">{layer.name}</span>
              <span className="text-muted-foreground tabular-nums">{layer.entity_count}</span>
            </button>
          );
        })}
        {filtered.length === 0 && (
          <p className="py-4 text-center text-xs text-muted-foreground">
            {t('dwg_takeoff.no_layers_found', 'No layers found')}
          </p>
        )}
      </div>
    </div>
  );
}
