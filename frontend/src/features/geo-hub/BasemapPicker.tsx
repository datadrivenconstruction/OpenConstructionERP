// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Basemap picker - chooses the backdrop for the 2D MapLibre map: a full
 * street map, a faded minimal map, or a tile-free "paper" / "blueprint"
 * canvas that works fully offline. See {@link BASEMAPS} in ./mapStyles.
 *
 * Only meaningful while the 2D engine is active (the 3D globe has its own
 * imagery handling), so the host page renders it in place of the Cesium
 * scene-mode picker when the engine is ``2d``.
 *
 * Thin stateless segmented pill matching the chrome of the other Geo Hub
 * toolbar pills, with the standard WAI-ARIA tabs keyboard pattern.
 */

import { useTranslation } from 'react-i18next';
import {
  Map as MapIcon,
  Layers,
  FileText,
  Grid3x3,
  type LucideIcon,
} from 'lucide-react';

import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';

import { BASEMAPS, type BasemapId } from './mapStyles';

const ICONS: Record<string, LucideIcon> = {
  Map: MapIcon,
  Layers,
  FileText,
  Grid3x3,
};

const BASEMAP_IDS: readonly BasemapId[] = BASEMAPS.map((b) => b.id);

interface BasemapPickerProps {
  current: BasemapId;
  onChange: (next: BasemapId) => void;
}

export function BasemapPicker({ current, onChange }: BasemapPickerProps) {
  const { t } = useTranslation();

  const onTabKeyDown = useTabKeyboardNav<BasemapId>({
    ids: BASEMAP_IDS,
    activeId: current,
    onChange,
    orientation: 'horizontal',
  });

  return (
    <div
      className={[
        'inline-flex items-center gap-0.5 rounded-lg border border-border',
        'bg-surface-primary p-0.5 shadow-xs',
      ].join(' ')}
      role="tablist"
      aria-label={t('geo.basemap.tablist', { defaultValue: 'Basemap' })}
      onKeyDown={onTabKeyDown}
      data-testid="geo-basemap-picker"
    >
      {BASEMAPS.map((b) => {
        const active = b.id === current;
        const Icon = ICONS[b.icon] ?? MapIcon;
        return (
          <button
            key={b.id}
            type="button"
            role="tab"
            id={`geo-hub-basemap-tab-${b.id}`}
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            title={t(b.descKey, { defaultValue: b.descDefault })}
            onClick={() => {
              if (b.id !== current) onChange(b.id);
            }}
            className={[
              'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium',
              'transition-colors duration-fast ease-oe',
              active
                ? 'bg-content-primary text-content-inverse shadow-sm'
                : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
            ].join(' ')}
            data-testid={`geo-basemap-tab-${b.id}`}
          >
            <Icon size={13} strokeWidth={2} />
            {t(b.labelKey, { defaultValue: b.labelDefault })}
          </button>
        );
      })}
    </div>
  );
}

export default BasemapPicker;
