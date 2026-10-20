// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * FederatedViewerLegend — pure presentational floating legend for the
 * federated 3D viewer. One row per member with a discipline color
 * swatch, name, element count badge, and a visibility checkbox.
 *
 * Stateless by design — the parent owns the visibility map and pushes
 * changes into the viewer's scene. Tests hit the checkbox callback
 * without mounting a real Three.js viewport.
 *
 * Slice 3 of BIM Federations.
 */
import { useTranslation } from 'react-i18next';
import { disciplineLabel } from '@/shared/lib/disciplineLabel';

import { DISCIPLINE_PALETTE } from './FederatedViewerScene';
import { getNumberLocale } from '@/stores/usePreferencesStore';

export interface LegendDiscipline {
  modelId: string;
  discipline: string;
  modelName: string;
  elementCount?: number;
  visible: boolean;
}

interface Props {
  disciplines: LegendDiscipline[];
  onToggleVisible: (modelId: string, visible: boolean) => void;
}

export function FederatedViewerLegend({ disciplines, onToggleVisible }: Props) {
  const { t } = useTranslation();
  if (disciplines.length === 0) return null;
  return (
    <div
      data-testid="federated-viewer-legend"
      className="absolute right-3 top-3 z-10 max-w-xs rounded-lg border border-slate-200 bg-white/95 p-3 shadow-md backdrop-blur"
    >
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {t('bim.federation.viewer.legend_title', {
          defaultValue: 'Models',
        })}
      </div>
      <ul className="space-y-1.5">
        {disciplines.map((d) => {
          const color =
            DISCIPLINE_PALETTE[d.discipline] ?? DISCIPLINE_PALETTE.other;
          return (
            <li
              key={d.modelId}
              data-testid={`federated-viewer-legend-row-${d.modelId}`}
              className="flex items-center gap-2 text-xs text-slate-700"
            >
              <input
                type="checkbox"
                checked={d.visible}
                onChange={(e) => onToggleVisible(d.modelId, e.target.checked)}
                data-testid={`federated-viewer-legend-toggle-${d.modelId}`}
                aria-label={t('bim.federation.viewer.toggle_member_visible', {
                  defaultValue: 'Toggle visibility',
                })}
                className="h-3.5 w-3.5"
              />
              <span
                className="inline-block h-3 w-3 rounded"
                style={{ backgroundColor: color }}
                aria-hidden
              />
              <span className="truncate font-medium">{d.modelName}</span>
              <span className="ml-auto rounded bg-slate-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-slate-500">
                {disciplineLabel(t, d.discipline)}
              </span>
              {typeof d.elementCount === 'number' ? (
                <span className="font-mono text-[10px] text-slate-400">
                  {d.elementCount.toLocaleString(getNumberLocale())}
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default FederatedViewerLegend;
