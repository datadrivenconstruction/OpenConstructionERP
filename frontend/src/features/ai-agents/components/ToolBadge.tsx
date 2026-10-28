// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import clsx from 'clsx';
import { Wrench } from 'lucide-react';

import { toolLabel } from './agentMeta';

/**
 * A single agent tool rendered as a readable pill (with a hover tooltip
 * explaining what the tool does) instead of a monospace slug.
 */
export function ToolBadge({ tool, className }: { tool: string; className?: string }): JSX.Element {
  const { label, hint } = toolLabel(tool);
  return (
    <span
      title={hint}
      className={clsx(
        'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-medium',
        'bg-surface-secondary text-content-secondary',
        className,
      )}
    >
      <Wrench className="h-2.5 w-2.5 shrink-0 text-content-tertiary" aria-hidden="true" />
      {label}
    </span>
  );
}
