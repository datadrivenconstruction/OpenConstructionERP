// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Engine toggle - switches the Geo Hub between the lightweight 2D map
 * (MapLibre GL) and the rich 3D globe (Cesium).
 *
 * This is a different axis from {@link GeoSceneModePicker}, which only
 * changes Cesium's projection (2D / 3D / Columbus) while still loading the
 * full ~3 MB Cesium runtime. The engine toggle picks the renderer itself:
 * the 2D map is instant and "like paper" (no Cesium download), the 3D
 * globe is the immersive view with terrain + 3D tilesets.
 *
 * Thin stateless segmented pill - the host page owns the value and
 * persists it. Matches the chrome of {@link GeoSceneModePicker} so the two
 * read as one toolbar surface. Keyboard nav via {@link useTabKeyboardNav}.
 */

import { useTranslation } from 'react-i18next';
import { Map as MapIcon, Globe2 } from 'lucide-react';

import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';

/** Which renderer backs the Geo Hub canvas. */
export type GeoEngine = '2d' | '3d';

const ENGINES: readonly GeoEngine[] = ['2d', '3d'];

interface EngineModePickerProps {
  current: GeoEngine;
  onChange: (next: GeoEngine) => void;
}

export function EngineModePicker({ current, onChange }: EngineModePickerProps) {
  const { t } = useTranslation();

  const items: ReadonlyArray<{
    key: GeoEngine;
    label: string;
    description: string;
    Icon: typeof MapIcon;
  }> = [
    {
      key: '2d',
      label: t('geo.engine.map2d', { defaultValue: '2D Map' }),
      description: t('geo.engine.map2d_hint', {
        defaultValue:
          'Light, instant map - place projects and drawings on a clear canvas. Works offline.',
      }),
      Icon: MapIcon,
    },
    {
      key: '3d',
      label: t('geo.engine.globe3d', { defaultValue: '3D Globe' }),
      description: t('geo.engine.globe3d_hint', {
        defaultValue: 'Immersive 3D globe with terrain and 3D models.',
      }),
      Icon: Globe2,
    },
  ];

  const onTabKeyDown = useTabKeyboardNav<GeoEngine>({
    ids: ENGINES,
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
      aria-label={t('geo.engine.tablist', { defaultValue: 'Map engine' })}
      onKeyDown={onTabKeyDown}
      data-testid="geo-engine-picker"
    >
      {items.map((it) => {
        const active = it.key === current;
        const Icon = it.Icon;
        return (
          <button
            key={it.key}
            type="button"
            role="tab"
            id={`geo-hub-engine-tab-${it.key}`}
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            title={it.description}
            onClick={() => {
              if (it.key !== current) onChange(it.key);
            }}
            className={[
              'inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium',
              'transition-colors duration-fast ease-oe',
              active
                ? 'bg-content-primary text-content-inverse shadow-sm'
                : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
            ].join(' ')}
            data-testid={`geo-engine-tab-${it.key}`}
          >
            <Icon size={13} strokeWidth={2} />
            {it.label}
          </button>
        );
      })}
    </div>
  );
}

export default EngineModePicker;
