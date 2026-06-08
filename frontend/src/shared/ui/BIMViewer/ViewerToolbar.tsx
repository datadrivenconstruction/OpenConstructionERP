/**
 * ViewerToolbar — floating overlay surfacing the three BIM-coordination-tool-style
 * tools added by this slice: Section Box, Walk mode, Measure.
 *
 * Only one tool is active at a time (mutual exclusion is enforced at the
 * component level, not at the helper level — each helper is independent).
 * The active tool's sub-panel renders directly below the button row.
 *
 * The toolbar is intentionally additive: it lives in its own React tree,
 * does not depend on the rest of the viewer's Zustand stores, and is
 * driven only by the three helper instances passed in as props. That
 * keeps it composable from FederationsPage (which has multiple viewers)
 * and the single-model BIMPage alike.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import { Crop, Move3d, Ruler, RotateCcw, Copy, X } from 'lucide-react';
import type { SectionBox } from './SectionBox';
import type { WalkMode } from './WalkMode';
import type { MeasureTool, Measurement } from './MeasureTool';
import { copyToClipboard } from '@/shared/lib/browser';

export type ActiveViewerTool = 'section' | 'walk' | 'measure' | null;

export interface ViewerToolbarProps {
  sectionBox: SectionBox;
  walkMode: WalkMode;
  measureTool: MeasureTool;
  /** Notified whenever the active tool changes (including to null). */
  onToolChange?: (tool: ActiveViewerTool) => void;
  /** Hook called when the user clicks "Fit to selection" / "Fit to all" /
   *  "Reset" — the host component knows the current selection / model
   *  bounds and should drive `sectionBox.setBoundsToBox(...)` from here.
   *  Return `false` from a `fit_*` action when there is no usable geometry
   *  to clip (empty selection / degenerate bounds) so the toolbar can show
   *  a "No geometry to clip" hint instead of leaving an invisible model. */
  onSectionAction?: (
    action: 'fit_selection' | 'fit_all' | 'reset',
  ) => boolean | void;
  /**
   * Called BEFORE a tool is enabled / AFTER a tool is disabled so the host
   * can flip externally-owned dependencies (most importantly: disable
   * OrbitControls before WalkMode.enable() runs, then re-enable it once
   * the user exits walk mode).  Return false from the "before" hook to
   * veto the activation (the toolbar will stay on the previous tool).
   */
  onBeforeToolEnable?: (next: Exclude<ActiveViewerTool, null>) => boolean | void;
  onAfterToolDisable?: (prev: Exclude<ActiveViewerTool, null>) => void;
  /** Floating overlay position. */
  position?: 'top-right' | 'bottom-center' | 'bottom-left';
  /** Extra horizontal offset (px) when `position === 'bottom-left'` — used
   *  to anchor the toolbar next to a bottom-left ViewCube. Ignored for
   *  the other positions. */
  leftOffset?: number;
  /** Initial flight speed for the walk-mode slider (m/s). */
  initialFlightSpeed?: number;
  /** Inclusive slider range for flight speed (m/s). */
  flightSpeedRange?: { min: number; max: number };
}

export function ViewerToolbar({
  sectionBox,
  walkMode,
  measureTool,
  onToolChange,
  onSectionAction,
  onBeforeToolEnable,
  onAfterToolDisable,
  position = 'top-right',
  leftOffset,
  initialFlightSpeed,
  flightSpeedRange,
}: ViewerToolbarProps): JSX.Element {
  const { t } = useTranslation();
  const [active, setActive] = useState<ActiveViewerTool>(null);
  const [measurementCount, setMeasurementCount] = useState(0);
  const [lastMeasurement, setLastMeasurement] = useState<Measurement | null>(null);
  const [copiedFlash, setCopiedFlash] = useState(false);
  const [flightSpeed, setFlightSpeedState] = useState<number>(
    initialFlightSpeed ?? walkMode.getFlightSpeed(),
  );
  /** Transient "No geometry to clip" hint shown when a Fit action found no
   *  usable bounds. Auto-clears so it doesn't linger after a later success. */
  const [noGeometryHint, setNoGeometryHint] = useState(false);

  // Subscribe to MeasureTool completions so the badge updates.
  useEffect(() => {
    const unsub = measureTool.onMeasurement((m: Measurement) => {
      setMeasurementCount(measureTool.count());
      setLastMeasurement(m);
    });
    return unsub;
  }, [measureTool]);

  const setTool = useCallback(
    (next: ActiveViewerTool) => {
      // Disable everything currently active.
      const prev = active;
      // Leaving section mode clears any stale "no geometry" hint so it
      // doesn't flash back on the next activation.
      if (next !== 'section') setNoGeometryHint(false);
      if (sectionBox.isEnabled() && next !== 'section') sectionBox.disable();
      if (walkMode.isEnabled() && next !== 'walk') walkMode.disable();
      if (measureTool.isEnabled() && next !== 'measure') measureTool.disable();
      if (prev && prev !== next) onAfterToolDisable?.(prev);

      // Enable the new tool (if any).
      if (next !== null) {
        const veto = onBeforeToolEnable?.(next);
        if (veto === false) return;
      }
      try {
        if (next === 'section') sectionBox.enable();
        else if (next === 'walk') walkMode.enable();
        else if (next === 'measure') measureTool.enable();
      } catch (err) {
        // WalkMode throws if OrbitControls is still enabled; surface as
        // a console warning so the host can diagnose but don't crash.
        // The caller is expected to disable OrbitControls before this
        // toolbar enables walk mode (via onBeforeToolEnable).
        // eslint-disable-next-line no-console
        console.warn('ViewerToolbar.setTool:', err);
        return;
      }
      setActive(next);
      onToolChange?.(next);
    },
    [
      active,
      sectionBox,
      walkMode,
      measureTool,
      onToolChange,
      onBeforeToolEnable,
      onAfterToolDisable,
    ],
  );

  const toggleTool = useCallback(
    (tool: Exclude<ActiveViewerTool, null>) => {
      setTool(active === tool ? null : tool);
    },
    [active, setTool],
  );

  const handleSpeedChange = useCallback(
    (next: number) => {
      walkMode.setFlightSpeed(next);
      setFlightSpeedState(next);
    },
    [walkMode],
  );

  const handleSectionAction = useCallback(
    (action: 'fit_selection' | 'fit_all' | 'reset') => {
      // Reset must ALWAYS succeed regardless of host wiring: drop the clip
      // here so an empty / mis-fitted box can never strand the user with an
      // invisible model. The host's onSectionAction can do extra cleanup.
      if (action === 'reset') {
        if (sectionBox.isEnabled()) sectionBox.disable();
        setNoGeometryHint(false);
        onSectionAction?.('reset');
        return;
      }
      // Fit actions: the host owns the bounds (selection / whole model) and
      // returns false when there is nothing usable to clip. Surface the
      // hint in that case instead of leaving everything clipped away.
      const applied = onSectionAction?.(action);
      setNoGeometryHint(applied === false);
    },
    [sectionBox, onSectionAction],
  );

  const handleClearMeasurements = useCallback(() => {
    measureTool.clearAll();
    setMeasurementCount(0);
    setLastMeasurement(null);
  }, [measureTool]);

  const handleCopyMeasurement = useCallback(async () => {
    if (!lastMeasurement) return;
    const value =
      lastMeasurement.distance >= 1
        ? `${lastMeasurement.distance.toFixed(3)} m`
        : `${(lastMeasurement.distance * 1000).toFixed(0)} mm`;
    await copyToClipboard(value);
    setCopiedFlash(true);
    window.setTimeout(() => setCopiedFlash(false), 1200);
  }, [lastMeasurement]);

  // Listen for Escape to exit the active tool — feels native because the
  // hint label tells the user Esc works. PointerLock's own Escape is
  // browser-driven and only unlocks the cursor; WalkMode then needs to
  // be fully disabled here so OrbitControls comes back.
  useEffect(() => {
    if (active === null) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setTool(null);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [active, setTool]);

  const positionClass =
    position === 'bottom-center'
      ? 'bottom-4 start-1/2 -translate-x-1/2'
      : position === 'bottom-left'
        ? 'bottom-3'
        : 'top-4 end-4';
  const positionStyle =
    position === 'bottom-left' ? { left: leftOffset ?? 12 } : undefined;
  // Anchor the active tool's sub-panel (and on-screen hint) so it grows
  // upward from a bottom-left toolbar — otherwise the hint would clip
  // off the bottom of the viewport.
  const flexDirectionClass =
    position === 'bottom-left' ? 'flex-col-reverse' : 'flex-col';

  return (
    <div
      className={clsx(
        'absolute z-20 flex items-stretch gap-2',
        flexDirectionClass,
        positionClass,
      )}
      style={positionStyle}
      data-testid="viewer-toolbar"
      data-position={position}
    >
      <div className="flex items-center gap-1 rounded-lg bg-surface-primary/95 backdrop-blur-sm border border-border-light shadow-md p-1">
        <ToolButton
          icon={Crop}
          label={t('viewerTools.section_box', { defaultValue: 'Section box' })}
          active={active === 'section'}
          onClick={() => toggleTool('section')}
          testId="viewer-tool-section"
        />
        <ToolButton
          icon={Move3d}
          label={t('viewerTools.walk', { defaultValue: 'Walk' })}
          active={active === 'walk'}
          onClick={() => toggleTool('walk')}
          testId="viewer-tool-walk"
        />
        <ToolButton
          icon={Ruler}
          label={t('viewerTools.measure', { defaultValue: 'Measure' })}
          active={active === 'measure'}
          onClick={() => toggleTool('measure')}
          testId="viewer-tool-measure"
        />
      </div>

      {active === 'section' && (
        <div
          className="flex flex-col gap-1 rounded-md bg-surface-primary border border-border-light shadow-sm p-2 text-[11px] text-content-secondary min-w-[180px]"
          data-testid="viewer-tool-section-panel"
        >
          <div className="flex items-center gap-1.5 px-1 pb-1 text-[10px] uppercase tracking-wide text-content-tertiary border-b border-border-light/60">
            <Crop size={10} />
            {t('viewerTools.section_box', { defaultValue: 'Section box' })}
          </div>
          <button
            type="button"
            className="px-2 py-1 rounded hover:bg-surface-secondary text-start"
            onClick={() => handleSectionAction('fit_selection')}
            data-testid="viewer-section-fit-selection"
          >
            {t('viewerTools.fit_selection', { defaultValue: 'Fit to selection' })}
          </button>
          <button
            type="button"
            className="px-2 py-1 rounded hover:bg-surface-secondary text-start"
            onClick={() => handleSectionAction('fit_all')}
            data-testid="viewer-section-fit-all"
          >
            {t('viewerTools.fit_all', { defaultValue: 'Fit to all' })}
          </button>
          <button
            type="button"
            className="px-2 py-1 rounded hover:bg-surface-secondary text-start inline-flex items-center gap-1.5"
            onClick={() => handleSectionAction('reset')}
            data-testid="viewer-section-reset"
          >
            <RotateCcw size={11} />
            {t('viewerTools.reset', { defaultValue: 'Reset' })}
          </button>
          {noGeometryHint && (
            <p
              className="mt-0.5 px-1 text-[10px] text-amber-600 leading-tight"
              data-testid="viewer-section-no-geometry"
              role="status"
            >
              {t('viewerTools.no_geometry_to_clip', {
                defaultValue: 'No geometry to clip',
              })}
            </p>
          )}
          <SectionOffsetsReadout sectionBox={sectionBox} />
          <p className="mt-1 px-1 text-[10px] text-content-tertiary leading-tight">
            {t('viewerTools.section_hint', {
              defaultValue:
                'Drag handles to slice · Reset to disable · Esc to exit',
            })}
          </p>
        </div>
      )}

      {active === 'walk' && (
        <div
          className="flex flex-col gap-2 rounded-md bg-surface-primary border border-border-light shadow-sm p-2 text-[11px] text-content-secondary min-w-[220px]"
          data-testid="viewer-tool-walk-panel"
        >
          <div className="flex items-center gap-1.5 px-1 text-[10px] uppercase tracking-wide text-content-tertiary border-b border-border-light/60 pb-1">
            <Move3d size={10} />
            {t('viewerTools.walk', { defaultValue: 'Walk' })}
          </div>
          <label className="flex items-center gap-2">
            <span className="shrink-0">
              {t('viewerTools.flight_speed', { defaultValue: 'Flight speed' })}
            </span>
            <input
              type="range"
              min={flightSpeedRange?.min ?? 0.5}
              max={flightSpeedRange?.max ?? 20}
              step={0.1}
              value={flightSpeed}
              onChange={(e) => handleSpeedChange(Number(e.target.value))}
              data-testid="viewer-walk-speed"
              aria-label={t('viewerTools.flight_speed', {
                defaultValue: 'Flight speed',
              })}
              className="flex-1"
            />
            <span className="tabular-nums w-10 text-end">
              {flightSpeed.toFixed(1)}
            </span>
          </label>
          <p className="px-1 text-[10px] text-content-tertiary leading-tight">
            {t('viewerTools.walk_hint', {
              defaultValue:
                'Mouse: look · WASD / arrows: move · Space/Shift: up/down · Shift+W: sprint · Esc: exit',
            })}
          </p>
        </div>
      )}

      {active === 'measure' && (
        <div
          className="flex flex-col gap-2 rounded-md bg-surface-primary border border-border-light shadow-sm p-2 text-[11px] text-content-secondary min-w-[220px]"
          data-testid="viewer-tool-measure-panel"
        >
          <div className="flex items-center gap-1.5 px-1 text-[10px] uppercase tracking-wide text-content-tertiary border-b border-border-light/60 pb-1">
            <Ruler size={10} />
            {t('viewerTools.measure', { defaultValue: 'Measure' })}
          </div>
          <div className="flex items-center justify-between gap-2">
            <span data-testid="viewer-measure-count">
              {t('viewerTools.measurements_count', {
                defaultValue: 'Measurements: {{count}}',
                count: measurementCount,
              })
                .toString()
                .replace('{{count}}', String(measurementCount))}
            </span>
            <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full bg-oe-blue text-white text-[10px] font-medium">
              {measurementCount}
            </span>
          </div>
          {lastMeasurement && (
            <div
              className="flex items-center justify-between gap-2 px-2 py-1 rounded bg-surface-secondary border border-border-light/60"
              data-testid="viewer-measure-last"
            >
              <span className="font-mono tabular-nums text-content-primary">
                {lastMeasurement.distance >= 1
                  ? `${lastMeasurement.distance.toFixed(3)} m`
                  : `${(lastMeasurement.distance * 1000).toFixed(0)} mm`}
              </span>
              <button
                type="button"
                onClick={handleCopyMeasurement}
                title={t('viewerTools.copy_value', { defaultValue: 'Copy value' })}
                aria-label={t('viewerTools.copy_value', {
                  defaultValue: 'Copy value',
                })}
                data-testid="viewer-measure-copy"
                className={clsx(
                  'inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors',
                  copiedFlash
                    ? 'bg-emerald-500/20 text-emerald-600'
                    : 'text-content-secondary hover:bg-surface-tertiary',
                )}
              >
                <Copy size={11} />
                {copiedFlash
                  ? t('viewerTools.copied', { defaultValue: 'Copied' })
                  : t('viewerTools.copy', { defaultValue: 'Copy' })}
              </button>
            </div>
          )}
          <button
            type="button"
            className="px-2 py-1 rounded hover:bg-surface-secondary text-start inline-flex items-center gap-1.5"
            onClick={handleClearMeasurements}
            data-testid="viewer-measure-clear"
          >
            <X size={11} />
            {t('viewerTools.clear_measurements', {
              defaultValue: 'Clear all measurements',
            })}
          </button>
          <p className="px-1 text-[10px] text-content-tertiary leading-tight">
            {t('viewerTools.measure_hint', {
              defaultValue:
                'Click to add points · Right-click to finish · Esc to cancel',
            })}
          </p>
        </div>
      )}
    </div>
  );
}

interface ToolButtonProps {
  icon: React.ElementType;
  label: string;
  active: boolean;
  onClick: () => void;
  testId: string;
}

function ToolButton({
  icon: Icon,
  label,
  active,
  onClick,
  testId,
}: ToolButtonProps): JSX.Element {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={active}
      data-testid={testId}
      className={clsx(
        'flex h-7 w-7 items-center justify-center rounded transition-colors',
        active
          ? 'bg-oe-blue text-white'
          : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary',
      )}
    >
      <Icon size={14} />
    </button>
  );
}

/** Read-only display of the current section AABB. The host can switch
 *  between metric / imperial later — for now, metres with 3 decimals. */
function SectionOffsetsReadout({
  sectionBox,
}: {
  sectionBox: SectionBox;
}): JSX.Element {
  const bounds = sectionBox.getBounds();
  const fmt = (v: number): string => v.toFixed(3);
  return (
    <div
      className="grid grid-cols-3 gap-x-2 text-[10px] text-content-tertiary tabular-nums mt-1"
      data-testid="viewer-section-offsets"
    >
      <span>X: {fmt(bounds.min.x)}…{fmt(bounds.max.x)}</span>
      <span>Y: {fmt(bounds.min.y)}…{fmt(bounds.max.y)}</span>
      <span>Z: {fmt(bounds.min.z)}…{fmt(bounds.max.z)}</span>
    </div>
  );
}
