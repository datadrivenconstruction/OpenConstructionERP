// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The material flow of a delivery, picked from the flows of the logistics
// concept. Renders nothing while the concept names no flow, so the booking
// form never shows a field that has nothing to offer.

import { useConcept, useWords } from './hooks';
import { tx } from './texts';

export function FlowSelect({
  projectId,
  value,
  onChange,
  className,
}: {
  projectId: string;
  value: string;
  onChange: (flowCode: string) => void;
  className: string;
}) {
  const { t } = useWords();
  const flows = useConcept(projectId).data?.strategy ?? [];
  if (flows.length === 0 && !value) return null;
  const label = tx(t, 'delivery.flow');
  return (
    <div data-testid="delivery-flow">
      <label htmlFor="delivery-flow-code" className="mb-1.5 block text-sm font-medium text-content-primary">
        {label}
      </label>
      <select id="delivery-flow-code" value={value} onChange={(e) => onChange(e.target.value)} className={className}>
        <option value="">{tx(t, 'not_set')}</option>
        {/* A flow the concept has since dropped stays visible on the booking that still names it. */}
        {value && !flows.some((f) => f.flow_code === value) && <option value={value}>{value}</option>}
        {flows.map((f) => (
          <option key={f.flow_code} value={f.flow_code}>
            {f.description ? `${f.flow_code} - ${f.description}` : f.flow_code}
          </option>
        ))}
      </select>
      <p className="mt-1 text-xs text-content-tertiary">{tx(t, 'delivery.flow_hint')}</p>
    </div>
  );
}
