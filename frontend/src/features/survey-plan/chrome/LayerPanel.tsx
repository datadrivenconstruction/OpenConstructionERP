// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Layer popover: visibility, lock, opacity, legend; basemap and label choice. */

import { useTranslation } from 'react-i18next';
import { Eye, EyeOff, Lock, LockOpen } from 'lucide-react';
import type { LabelMode } from '../cartography';
import type { LayerViewState, PlanLayerSpec } from '../types';

export type Basemap = 'paper' | 'map';

interface Props {
  layers: PlanLayerSpec[];
  state: Record<string, LayerViewState>;
  onChange: (id: string, next: LayerViewState) => void;
  basemap: Basemap;
  onBasemap: (b: Basemap) => void;
  canMap: boolean;
  labels: LabelMode;
  onLabels: (m: LabelMode) => void;
  activeLayer: string;
  onActiveLayer?: (id: string) => void;
}

const LABEL_MODES: [LabelMode, string, string][] = [
  ['id', 'plan.labels.id', 'Point id'],
  ['code', 'plan.labels.code', 'Code'],
  ['z', 'plan.labels.z', 'Height'],
  ['none', 'plan.labels.none', 'None'],
];

export function LayerPanel({ layers, state, onChange, basemap, onBasemap, canMap, labels, onLabels, activeLayer, onActiveLayer }: Props) {
  const { t } = useTranslation();
  const sorted = [...layers].sort((a, b) => b.order - a.order);
  return (
    <div className="w-72 space-y-3 p-3 text-sm" data-testid="plan-layer-panel">
      <div className="flex gap-1" role="radiogroup" aria-label={t('plan.basemap', { defaultValue: 'Background' })}>
        {(['paper', 'map'] as const).map((b) => (
          <button
            key={b}
            type="button"
            role="radio"
            aria-checked={basemap === b}
            disabled={b === 'map' && !canMap}
            onClick={() => onBasemap(b)}
            title={b === 'map' && !canMap ? t('plan.basemap_local', { defaultValue: 'A local grid has no place on a map' }) : undefined}
            className={`h-8 flex-1 rounded-md text-xs font-medium disabled:opacity-40 ${
              basemap === b ? 'bg-oe-blue text-content-inverse' : 'bg-surface-secondary text-content-secondary hover:text-content-primary'
            }`}
          >
            {b === 'paper' ? t('plan.basemap_paper', { defaultValue: 'Paper' }) : t('plan.basemap_map', { defaultValue: 'Map' })}
          </button>
        ))}
      </div>
      <label className="flex items-center justify-between gap-2 text-xs text-content-secondary">
        {t('plan.labels.title', { defaultValue: 'Point labels' })}
        <select className="oe-input w-32 text-xs" value={labels} onChange={(e) => onLabels(e.target.value as LabelMode)}>
          {LABEL_MODES.map(([m, k, d]) => (
            <option key={m} value={m}>
              {t(k, { defaultValue: d })}
            </option>
          ))}
        </select>
      </label>
      <ul className="space-y-1">
        {sorted.map((l) => {
          const s = state[l.id] ?? { visible: !l.defaultHidden, locked: false, opacity: 1 };
          const title = t(l.titleKey, { defaultValue: l.defaultTitle });
          return (
            <li key={l.id} className={`rounded-lg px-2 py-1.5 ${activeLayer === l.id ? 'bg-oe-blue/10' : ''}`} data-testid={`plan-layer-${l.id}`}>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  className="flex h-8 w-8 items-center justify-center rounded text-content-secondary hover:bg-surface-secondary"
                  onClick={() => onChange(l.id, { ...s, visible: !s.visible })}
                  aria-pressed={s.visible}
                  aria-label={t('plan.layer_toggle', { defaultValue: 'Show {{layer}}', layer: title })}
                >
                  {s.visible ? <Eye size={15} aria-hidden /> : <EyeOff size={15} aria-hidden />}
                </button>
                <button
                  type="button"
                  className="min-w-0 flex-1 truncate text-start text-content-primary disabled:cursor-default"
                  disabled={!l.editable || !onActiveLayer}
                  onClick={() => onActiveLayer?.(l.id)}
                  title={l.editable ? t('plan.layer_activate', { defaultValue: 'Draw on this layer' }) : undefined}
                >
                  {title}
                  <span className="ms-1 text-xs text-content-tertiary">{l.features.length || ''}</span>
                </button>
                {l.editable && (
                  <button
                    type="button"
                    className="flex h-8 w-8 items-center justify-center rounded text-content-tertiary hover:bg-surface-secondary"
                    onClick={() => onChange(l.id, { ...s, locked: !s.locked })}
                    aria-pressed={s.locked}
                    aria-label={t('plan.layer_lock', { defaultValue: 'Lock {{layer}}', layer: title })}
                  >
                    {s.locked ? <Lock size={14} aria-hidden /> : <LockOpen size={14} aria-hidden />}
                  </button>
                )}
              </div>
              {s.visible && (
                <input
                  type="range"
                  min={0.1}
                  max={1}
                  step={0.05}
                  value={s.opacity}
                  onChange={(e) => onChange(l.id, { ...s, opacity: Number(e.target.value) })}
                  className="ms-9 w-40 accent-oe-blue"
                  aria-label={t('plan.layer_opacity', { defaultValue: 'Opacity of {{layer}}', layer: title })}
                />
              )}
              {s.visible && l.legend && l.legend.length > 0 && (
                <ul className="ms-9 mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-content-secondary">
                  {l.legend.map((item) => (
                    <li key={item.labelKey} className="inline-flex items-center gap-1">
                      <span
                        aria-hidden
                        className={item.kind === 'line' ? 'h-0 w-4 border-t-2' : 'h-3 w-3 rounded-sm'}
                        style={item.kind === 'line' ? { borderColor: item.colour, borderStyle: item.dashed ? 'dashed' : 'solid' } : { background: item.colour }}
                      />
                      {t(item.labelKey, { defaultValue: item.defaultLabel })}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
