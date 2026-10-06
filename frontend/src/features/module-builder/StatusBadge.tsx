// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The stage a record of a generated module is in, as a coloured badge.
 *
 * Colour follows meaning rather than position in the list, so it reads the
 * same in every module: the starting stage is neutral, a stage in between is
 * blue, a finished stage is green. The words are the module author's own and
 * are shown as written.
 */
import { Badge, type BadgeVariant } from '@/shared/ui';

import type { ModuleSpec, ModuleStateSpec } from './api';
import { statusStates } from './fields';

export function statusVariant(states: readonly ModuleStateSpec[], code: unknown): BadgeVariant {
  const index = states.findIndex((s) => s.code === code);
  if (index < 0) return 'neutral';
  if (states[index]?.done) return 'success';
  return index === 0 ? 'neutral' : 'blue';
}

export function StatusBadge({ spec, code }: { spec: Pick<ModuleSpec, 'features'>; code: unknown }) {
  const states = statusStates(spec);
  const state = states.find((s) => s.code === code);
  // A code the spec no longer lists (a stage removed by a reinstall) is still
  // the stored truth, so it is shown as stored rather than hidden.
  const text = state?.label ?? (typeof code === 'string' ? code : '');
  if (!text) return null;
  return (
    <Badge variant={statusVariant(states, code)} size="sm" dot>
      {text}
    </Badge>
  );
}
