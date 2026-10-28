// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The load and dimension limits of one site entrance, shown on its card in
// the gates tab. The plan checks every transport against them; an entrance
// without limits cannot be checked, and the card says so.

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Weight } from 'lucide-react';

import { updateGate, type Gate, type UpdateGatePayload } from '../api';
import { num } from './format';
import { useCatalogue, useInvalidatePlan, useWords } from './hooks';
import { FormDialog } from './PlanBits';
import { codeLabel, codeOptions, type Field } from './rules';
import { tx } from './texts';

export const GATE_LIMITS = [
  'max_gross_t',
  'max_axle_load_t',
  'max_height_m',
  'max_width_m',
  'max_length_m',
  'turning_radius_m',
] as const;

export function GateLimits({ gate, canEdit }: { gate: Gate; canEdit: boolean }) {
  const words = useWords();
  const { t } = words;
  const qc = useQueryClient();
  const catalogue = useCatalogue(gate.project_id).data ?? null;
  const invalidate = useInvalidatePlan(gate.project_id);
  const [editing, setEditing] = useState(false);

  const known = GATE_LIMITS.filter((name) => gate[name] !== null && gate[name] !== undefined);
  const fields: Field[] = [
    { name: 'access_kind', label: 'f.access_kind', kind: 'select', options: codeOptions(words, 'access_kinds', catalogue), wide: true },
    ...GATE_LIMITS.map((name): Field => ({ name, label: `f.${name}`, kind: 'decimal' })),
  ];

  return (
    <div className="mt-1 border-t border-border-light pt-2" data-testid="gate-limits">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs font-medium text-content-secondary">
          <Weight size={12} className="text-content-tertiary" aria-hidden />
          {tx(t, 'gate.limits')}
        </span>
        {canEdit && (
          <button
            type="button"
            className="text-xs font-medium text-oe-blue hover:underline"
            onClick={() => setEditing(true)}
            data-testid="gate-limits-edit"
          >
            {tx(t, 'gate.edit_limits')}
          </button>
        )}
      </div>
      {gate.access_kind && (
        <p className="mt-1 text-xs text-content-secondary">{codeLabel(words, 'access_kinds', gate.access_kind, catalogue)}</p>
      )}
      {known.length === 0 ? (
        <div className="mt-1 rounded-md border border-dashed border-border-light px-2 py-2 text-center" data-testid="gate-limits-none">
          <p className="text-xs font-medium text-content-primary">{tx(t, 'gate.no_limits_title')}</p>
          <p className="mt-0.5 text-2xs text-content-tertiary">{tx(t, 'gate.no_limits')}</p>
        </div>
      ) : (
        <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-2xs text-content-secondary">
          {known.map((name) => (
            <div key={name} className="flex justify-between gap-2">
              <dt className="truncate">{tx(t, `f.${name}`)}</dt>
              <dd className="tabular-nums text-content-primary">{num(gate[name])}</dd>
            </div>
          ))}
        </dl>
      )}
      {editing && (
        <FormDialog
          title="edit_title.gate_limits"
          fields={fields}
          record={gate}
          projectId={gate.project_id}
          catalogue={catalogue}
          onSubmit={(body) => updateGate(gate.id, body as UpdateGatePayload)}
          onSaved={async () => {
            await qc.invalidateQueries({ queryKey: ['site-logistics-gates'] });
            await invalidate();
          }}
          onClose={() => setEditing(false)}
        />
      )}
    </div>
  );
}
