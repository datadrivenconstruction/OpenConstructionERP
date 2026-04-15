/**
 * Horizontal toolbar for DWG takeoff annotation tools.
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
} from 'lucide-react';

export type DwgTool = 'select' | 'pan' | 'distance' | 'area' | 'text_pin' | 'arrow' | 'rectangle';

const TOOLS: { id: DwgTool; icon: React.ElementType; labelKey: string; shortcut?: string }[] = [
  { id: 'select', icon: MousePointer2, labelKey: 'dwg_takeoff.tool_select', shortcut: 'V' },
  { id: 'pan', icon: Hand, labelKey: 'dwg_takeoff.tool_pan', shortcut: 'H' },
  { id: 'distance', icon: Ruler, labelKey: 'dwg_takeoff.tool_distance', shortcut: 'D' },
  { id: 'area', icon: PenTool, labelKey: 'dwg_takeoff.tool_area', shortcut: 'A' },
  { id: 'text_pin', icon: Type, labelKey: 'dwg_takeoff.tool_text_pin', shortcut: 'T' },
  { id: 'arrow', icon: ArrowRight, labelKey: 'dwg_takeoff.tool_arrow' },
  { id: 'rectangle', icon: Square, labelKey: 'dwg_takeoff.tool_rectangle' },
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
    <div className="flex items-center gap-1 rounded-lg border border-border bg-surface px-2 py-1 shadow-sm">
      {TOOLS.map(({ id, icon: Icon, labelKey, shortcut }) => (
        <button
          key={id}
          title={`${t(labelKey, id)}${shortcut ? ` (${shortcut})` : ''}`}
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
      ))}

      <div className="mx-1 h-6 w-px bg-border" />

      {PRESET_COLORS.map((color) => (
        <button
          key={color}
          title={color}
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
