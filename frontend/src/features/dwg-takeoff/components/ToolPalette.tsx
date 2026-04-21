/**
 * Horizontal toolbar for DWG takeoff annotation tools.
 *
 * Emits per-tool keyboard shortcuts in the button tooltip so users can
 * discover them without reading the docs (AutoCAD has conditioned every
 * estimator to hover for this information).
 */

import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  MousePointer2,
  Hand,
  Ruler,
  PenTool,
  Type,
  ArrowRight,
  Square,
  Circle,
  Spline,
  Minus,
} from 'lucide-react';

export type DwgTool =
  | 'select'
  | 'pan'
  | 'distance'
  | 'area'
  | 'text_pin'
  | 'arrow'
  | 'rectangle'
  | 'circle'
  | 'polyline'
  | 'line';

interface ToolDef {
  id: DwgTool;
  icon: React.ElementType;
  labelKey: string;
  labelFallback: string;
  shortcut?: string;
}

/** Pair each tool with a human-readable English fallback so the tooltip
 *  reads as "Distance (D)" even when the translation bundle is empty.
 *  All shortcuts are uppercase single-char keys; `Esc` cancels the draw
 *  (tracked globally, not shown per button). */
const TOOLS: ToolDef[] = [
  { id: 'select', icon: MousePointer2, labelKey: 'dwg_takeoff.tool_select', labelFallback: 'Select', shortcut: 'V' },
  { id: 'pan', icon: Hand, labelKey: 'dwg_takeoff.tool_pan', labelFallback: 'Pan', shortcut: 'H' },
  { id: 'distance', icon: Ruler, labelKey: 'dwg_takeoff.tool_distance', labelFallback: 'Distance', shortcut: 'D' },
  { id: 'line', icon: Minus, labelKey: 'dwg_takeoff.tool_line', labelFallback: 'Line', shortcut: 'L' },
  { id: 'polyline', icon: Spline, labelKey: 'dwg_takeoff.tool_polyline', labelFallback: 'Polyline', shortcut: 'P' },
  { id: 'area', icon: PenTool, labelKey: 'dwg_takeoff.tool_area', labelFallback: 'Area', shortcut: 'A' },
  { id: 'rectangle', icon: Square, labelKey: 'dwg_takeoff.tool_rectangle', labelFallback: 'Rectangle', shortcut: 'R' },
  { id: 'circle', icon: Circle, labelKey: 'dwg_takeoff.tool_circle', labelFallback: 'Circle', shortcut: 'C' },
  { id: 'arrow', icon: ArrowRight, labelKey: 'dwg_takeoff.tool_arrow', labelFallback: 'Arrow' },
  { id: 'text_pin', icon: Type, labelKey: 'dwg_takeoff.tool_text_pin', labelFallback: 'Text pin', shortcut: 'T' },
];

const PRESET_COLORS = ['#ef4444', '#f59e0b', '#22c55e', '#3b82f6', '#8b5cf6', '#ec4899'];

interface Props {
  activeTool: DwgTool;
  onToolChange: (tool: DwgTool) => void;
  activeColor: string;
  onColorChange: (color: string) => void;
}

export function ToolPalette({ activeTool, onToolChange, activeColor, onColorChange }: Props) {
  const { t } = useTranslation();

  return (
    <div
      className="flex items-center gap-1 rounded-lg border border-border bg-surface px-2 py-1 shadow-sm"
      data-testid="dwg-tool-palette"
    >
      {TOOLS.map(({ id, icon: Icon, labelKey, labelFallback, shortcut }) => {
        const label = t(labelKey, { defaultValue: labelFallback }) as string;
        const title = shortcut ? `${label} (${shortcut})` : label;
        return (
          <button
            key={id}
            type="button"
            title={title}
            aria-label={title}
            data-testid={`dwg-tool-${id}`}
            data-shortcut={shortcut ?? ''}
            onClick={() => onToolChange(id)}
            className={clsx(
              'flex h-8 w-8 items-center justify-center rounded-md transition-colors',
              activeTool === id
                ? 'bg-oe-blue text-white'
                : 'text-muted-foreground hover:bg-surface-secondary hover:text-foreground',
            )}
          >
            <Icon size={16} />
          </button>
        );
      })}

      <div className="mx-1 h-6 w-px bg-border" />

      {PRESET_COLORS.map((color) => (
        <button
          key={color}
          type="button"
          title={color}
          aria-label={`Color ${color}`}
          onClick={() => onColorChange(color)}
          className={clsx(
            'h-5 w-5 rounded-full border-2 transition-transform',
            activeColor === color ? 'scale-125 border-foreground' : 'border-transparent',
          )}
          style={{ backgroundColor: color }}
        />
      ))}
    </div>
  );
}
