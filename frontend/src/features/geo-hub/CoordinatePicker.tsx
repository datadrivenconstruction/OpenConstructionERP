// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * <CoordinatePicker> — paired lat/lon input with DD/DMS toggle.
 *
 * Used wherever the user types or pastes coordinates (project form,
 * AnchorAdjustPanel "set precise coords" mode). Provides:
 *
 *   * Live validation: ``-90..90`` for lat, ``-180..180`` for lon
 *   * Format chips: "DD" (decimal degrees) and "DMS" — switching
 *     converts the displayed value in both directions
 *   * Optional "Pick from map" button that calls ``onPickFromMap`` —
 *     parent renders a small inline map dialog and feeds back coords
 *
 * Controlled — keeps the (lat, lon) tuple in props. Conversion errors
 * surface as inline validation messages, not aria-live announcements,
 * because typing-while-DMS-is-half-built would otherwise narrate a
 * stream of false "invalid" warnings.
 */

import { useEffect, useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Crosshair, Pencil } from 'lucide-react';

import {
  ddToDmsString,
  isValidCoord,
  parseDms,
  roundCoord,
} from './coordUtils';

export type CoordFormat = 'DD' | 'DMS';

interface CoordinatePickerProps {
  /** Current latitude (degrees, decimal). May be ``null`` when blank. */
  lat: number | null;
  /** Current longitude (degrees, decimal). May be ``null`` when blank. */
  lon: number | null;
  /** Called on each valid edit. ``null`` means the field was cleared. */
  onChange: (next: { lat: number | null; lon: number | null }) => void;
  /** Optional callback for the "Pick from map" affordance. */
  onPickFromMap?: () => void;
  /** When true the inputs are disabled (read-only display mode). */
  disabled?: boolean;
  /** Optional initial format. Defaults to ``"DD"`` (most familiar). */
  initialFormat?: CoordFormat;
  /** When true, hide the "Pick from map" button even if a handler is given. */
  hidePickFromMap?: boolean;
}

interface AxisState {
  text: string;
  error: string | null;
}

function _toDisplay(
  value: number | null,
  axis: 'lat' | 'lon',
  format: CoordFormat,
): string {
  if (value === null || !Number.isFinite(value)) return '';
  return format === 'DD' ? String(roundCoord(value, 7)) : ddToDmsString(value, axis);
}

export function CoordinatePicker({
  lat,
  lon,
  onChange,
  onPickFromMap,
  disabled,
  initialFormat = 'DD',
  hidePickFromMap,
}: CoordinatePickerProps) {
  const { t } = useTranslation();
  const reactId = useId();
  const [format, setFormat] = useState<CoordFormat>(initialFormat);
  const [latState, setLatState] = useState<AxisState>({
    text: _toDisplay(lat, 'lat', initialFormat),
    error: null,
  });
  const [lonState, setLonState] = useState<AxisState>({
    text: _toDisplay(lon, 'lon', initialFormat),
    error: null,
  });

  // Reflect external value changes (e.g. "Pick from map" updates the
  // tuple) into the local input text. Avoids re-syncing while the user
  // is mid-edit (we only refresh when the prop differs from our parse).
  useEffect(() => {
    const parsed = parseDms(latState.text, 'lat');
    if (parsed !== lat) {
      setLatState({ text: _toDisplay(lat, 'lat', format), error: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lat]);

  useEffect(() => {
    const parsed = parseDms(lonState.text, 'lon');
    if (parsed !== lon) {
      setLonState({ text: _toDisplay(lon, 'lon', format), error: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lon]);

  function commit(
    axis: 'lat' | 'lon',
    text: string,
    setter: (s: AxisState) => void,
  ) {
    if (text.trim() === '') {
      setter({ text, error: null });
      onChange({
        lat: axis === 'lat' ? null : lat,
        lon: axis === 'lon' ? null : lon,
      });
      return;
    }
    const parsed = parseDms(text, axis);
    if (parsed === null) {
      const r = axis === 'lat' ? '-90..90' : '-180..180';
      setter({
        text,
        error: t('geo_hub.coords.out_of_range', {
          defaultValue: 'Out of range ({{range}})',
          range: r,
        }),
      });
      return;
    }
    if (!isValidCoord(parsed, axis)) {
      setter({
        text,
        error: t('geo_hub.coords.out_of_range', {
          defaultValue: 'Out of range ({{range}})',
          range: axis === 'lat' ? '-90..90' : '-180..180',
        }),
      });
      return;
    }
    setter({ text, error: null });
    onChange({
      lat: axis === 'lat' ? parsed : lat,
      lon: axis === 'lon' ? parsed : lon,
    });
  }

  function switchFormat(next: CoordFormat) {
    if (next === format) return;
    setFormat(next);
    // Re-render whatever signed value we currently have under the new format.
    setLatState({ text: _toDisplay(lat, 'lat', next), error: null });
    setLonState({ text: _toDisplay(lon, 'lon', next), error: null });
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="text-2xs font-semibold uppercase tracking-[0.12em] text-content-tertiary">
          {t('geo_hub.coords.format', { defaultValue: 'Format' })}
        </span>
        <div
          role="radiogroup"
          aria-label={t('geo_hub.coords.format_aria', {
            defaultValue: 'Coordinate format',
          })}
          className="inline-flex overflow-hidden rounded-md border border-border"
        >
          {(['DD', 'DMS'] as const).map((f) => (
            <button
              type="button"
              key={f}
              role="radio"
              aria-checked={format === f}
              onClick={() => switchFormat(f)}
              disabled={disabled}
              className={[
                'px-2 py-1 text-2xs font-semibold transition-colors',
                format === f
                  ? 'bg-oe-blue text-white'
                  : 'bg-surface-primary text-content-secondary hover:bg-surface-secondary',
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
              ].join(' ')}
              data-testid={`geo-coords-format-${f.toLowerCase()}`}
            >
              {f}
            </button>
          ))}
        </div>
        {onPickFromMap && !hidePickFromMap && (
          <button
            type="button"
            onClick={onPickFromMap}
            disabled={disabled}
            className={[
              'ml-auto inline-flex items-center gap-1 rounded-md border border-border',
              'px-2 py-1 text-2xs font-medium text-content-secondary',
              'hover:bg-surface-secondary hover:text-content-primary',
              'focus:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue',
            ].join(' ')}
            data-testid="geo-coords-pick-from-map"
          >
            <Crosshair size={11} strokeWidth={2.25} />
            {t('geo_hub.coords.pick_from_map', {
              defaultValue: 'Pick from map',
            })}
          </button>
        )}
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <label htmlFor={`${reactId}-lat`} className="block">
          <span className="text-2xs font-semibold uppercase tracking-[0.12em] text-content-tertiary">
            {t('geo_hub.coords.lat', { defaultValue: 'Latitude' })}
          </span>
          <div className="relative mt-1">
            <input
              id={`${reactId}-lat`}
              type="text"
              value={latState.text}
              placeholder={format === 'DD' ? '52.5200' : "52° 31' 12\" N"}
              onChange={(e) => commit('lat', e.target.value, setLatState)}
              disabled={disabled}
              inputMode="text"
              aria-invalid={latState.error !== null}
              aria-describedby={
                latState.error ? `${reactId}-lat-err` : undefined
              }
              className={[
                'h-9 w-full rounded-md border bg-surface-primary px-2',
                'pr-8 font-mono text-xs tabular-nums text-content-primary',
                latState.error ? 'border-red-500' : 'border-border',
                'focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent',
                disabled ? 'opacity-60 cursor-not-allowed' : '',
              ].join(' ')}
              data-testid="geo-coords-lat-input"
            />
            <Pencil
              size={11}
              className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-content-tertiary"
              aria-hidden
            />
          </div>
          {latState.error && (
            <p
              id={`${reactId}-lat-err`}
              className="mt-1 text-2xs text-red-600"
              role="alert"
            >
              {latState.error}
            </p>
          )}
        </label>
        <label htmlFor={`${reactId}-lon`} className="block">
          <span className="text-2xs font-semibold uppercase tracking-[0.12em] text-content-tertiary">
            {t('geo_hub.coords.lon', { defaultValue: 'Longitude' })}
          </span>
          <div className="relative mt-1">
            <input
              id={`${reactId}-lon`}
              type="text"
              value={lonState.text}
              placeholder={format === 'DD' ? '13.4050' : "13° 24' 18\" E"}
              onChange={(e) => commit('lon', e.target.value, setLonState)}
              disabled={disabled}
              inputMode="text"
              aria-invalid={lonState.error !== null}
              aria-describedby={
                lonState.error ? `${reactId}-lon-err` : undefined
              }
              className={[
                'h-9 w-full rounded-md border bg-surface-primary px-2',
                'pr-8 font-mono text-xs tabular-nums text-content-primary',
                lonState.error ? 'border-red-500' : 'border-border',
                'focus:outline-none focus:ring-2 focus:ring-oe-blue focus:border-transparent',
                disabled ? 'opacity-60 cursor-not-allowed' : '',
              ].join(' ')}
              data-testid="geo-coords-lon-input"
            />
            <Pencil
              size={11}
              className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-content-tertiary"
              aria-hidden
            />
          </div>
          {lonState.error && (
            <p
              id={`${reactId}-lon-err`}
              className="mt-1 text-2xs text-red-600"
              role="alert"
            >
              {lonState.error}
            </p>
          )}
        </label>
      </div>
    </div>
  );
}

export default CoordinatePicker;
