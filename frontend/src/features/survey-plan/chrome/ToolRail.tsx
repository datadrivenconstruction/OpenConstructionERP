// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Vertical tool rail: one 44 px button per tool, grouped, with its shortcut in the tooltip. */

import { useTranslation } from 'react-i18next';
import type { PlanTool, ToolGroup } from '../types';

const GROUP_ORDER: ToolGroup[] = ['select', 'draw', 'measure', 'annotate'];

interface Props {
  tools: PlanTool[];
  active: string;
  onPick: (id: string) => void;
}

export function ToolRail({ tools, active, onPick }: Props) {
  const { t } = useTranslation();
  const groups = GROUP_ORDER.map((g) => tools.filter((tool) => tool.group === g)).filter((g) => g.length > 0);
  return (
    <div
      role="toolbar"
      aria-orientation="vertical"
      aria-label={t('plan.tools', { defaultValue: 'Plan tools' })}
      className="flex flex-col gap-1 rounded-xl border border-border-light bg-surface-elevated/95 p-1 shadow-md backdrop-blur"
      data-testid="plan-tool-rail"
    >
      {groups.map((group, gi) => (
        <div key={gi} className={gi > 0 ? 'flex flex-col gap-1 border-t border-border-light pt-1' : 'flex flex-col gap-1'}>
          {group.map((tool) => {
            const Icon = tool.icon;
            const label = t(tool.labelKey, { defaultValue: tool.defaultLabel });
            const on = tool.id === active;
            return (
              <button
                key={tool.id}
                type="button"
                onClick={() => onPick(tool.id)}
                aria-pressed={on}
                aria-label={tool.shortcut ? `${label} (${tool.shortcut})` : label}
                title={tool.shortcut ? `${label}  ${tool.shortcut}` : label}
                data-testid={`plan-tool-${tool.id}`}
                className={`flex h-11 w-11 items-center justify-center rounded-lg motion-safe:transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue ${
                  on ? 'bg-oe-blue text-content-inverse shadow-sm' : 'text-content-secondary hover:bg-surface-secondary hover:text-content-primary'
                }`}
              >
                <Icon size={18} strokeWidth={on ? 2.2 : 1.8} aria-hidden />
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
}
