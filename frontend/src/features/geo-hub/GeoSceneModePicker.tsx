// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Scene-mode segmented pill — switches the Cesium viewer between 3D
 * globe, 2D flat top-down and 2.5-D Columbus View projections.
 *
 * Users coming from Google Maps / Mapbox expect a top-down 2D view; users
 * who anchored projects expect the 3D globe; power users sometimes prefer
 * Columbus View for a hybrid perspective. This control is a thin
 * stateless segmented-pill — the host page owns the active value and is
 * responsible for persisting it to localStorage. The picker only renders
 * the buttons and emits ``onChange`` events.
 *
 * Matches the chrome styling of {@link GeoModePicker} so the two read as
 * a single toolbar control surface. Keyboard navigation via
 * {@link useTabKeyboardNav} (ArrowLeft / Right / Home / End + roving
 * tabIndex) — the WAI-ARIA tabs pattern.
 */

import { useTranslation } from 'react-i18next';
import { Map, Globe2, Mountain } from 'lucide-react';

import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';

import type { GeoSceneMode } from './CesiumViewer';

const SCENE_MODES: readonly GeoSceneMode[] = ['2d', '3d', 'columbus'];

interface GeoSceneModePickerProps {
  current: GeoSceneMode;
  onChange: (next: GeoSceneMode) => void;
}

export function GeoSceneModePicker({
  current,
  onChange,
}: GeoSceneModePickerProps) {
  const { t } = useTranslation();

  const items: ReadonlyArray<{
    key: GeoSceneMode;
    label: string;
    description: string;
    Icon: typeof Map;
  }> = [
    {
      key: '2d',
      label: t('geoHub.scene2D', { defaultValue: '2D' }),
      description: t('geoHub.scene2D_hint', {
        defaultValue: 'Flat top-down map (like Google Maps).',
      }),
      Icon: Map,
    },
    {
      key: '3d',
      label: t('geoHub.scene3D', { defaultValue: '3D' }),
      description: t('geoHub.scene3D_hint', {
        defaultValue: 'Interactive 3D globe with perspective.',
      }),
      Icon: Globe2,
    },
    {
      key: 'columbus',
      label: t('geoHub.sceneColumbus', { defaultValue: 'Columbus' }),
      description: t('geoHub.sceneColumbus_hint', {
        defaultValue: '2.5-D oblique view - flat map with depth.',
      }),
      Icon: Mountain,
    },
  ];

  const onTabKeyDown = useTabKeyboardNav<GeoSceneMode>({
    ids: SCENE_MODES,
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
      aria-label={t('geoHub.sceneMode_tablist', {
        defaultValue: 'Map projection',
      })}
      onKeyDown={onTabKeyDown}
      data-testid="geo-scene-mode-picker"
    >
      {items.map((it) => {
        const active = it.key === current;
        const Icon = it.Icon;
        return (
          <button
            key={it.key}
            type="button"
            role="tab"
            id={`geo-hub-scene-tab-${it.key}`}
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
            data-testid={`geo-scene-tab-${it.key}`}
          >
            <Icon size={13} strokeWidth={2} />
            {it.label}
          </button>
        );
      })}
    </div>
  );
}

export default GeoSceneModePicker;
