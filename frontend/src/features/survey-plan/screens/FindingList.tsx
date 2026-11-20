// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { Badge } from '@/shared/ui';

export interface PlanFinding {
  rule_id: string;
  severity: string;
  message: string;
  suggestion?: string | null;
}

/** Validation findings of a plan screen: rule id badge, message, suggestion. */
export function FindingList({ items, testId }: { items: readonly PlanFinding[]; testId?: string }) {
  if (!items.length) return null;
  return (
    <ul className="space-y-1 text-sm" data-testid={testId}>
      {items.map((f, i) => (
        <li key={`${f.rule_id}-${i}`} className="flex gap-2">
          <Badge variant={f.severity === 'error' ? 'error' : f.severity === 'warning' ? 'warning' : 'neutral'} size="sm">
            {f.rule_id}
          </Badge>
          <span>
            {f.message}
            {f.suggestion && <span className="block text-content-tertiary">{f.suggestion}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}
