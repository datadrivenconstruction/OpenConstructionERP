// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// POSourceRequisitions - where the lines of a purchase order came from.
//
// An order raised by converting approved requisitions keeps, on every line,
// the requisition line it was raised from, and that line keeps the BOQ
// positions its quantity came from. This panel reads that chain back for one
// order. An order typed by hand has no requisition and shows nothing.

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link2 } from 'lucide-react';
import { tracePurchaseOrder } from './requisitionsApi';

/** "ordinal description" of a source position, or its short id when neither is known. */
export function positionLabel(s: {
  boq_position_id: string | null;
  position_ordinal?: string | null;
  position_description?: string | null;
}): string {
  const label = [s.position_ordinal, s.position_description]
    .map((v) => (v ?? '').trim())
    .filter(Boolean)
    .join(' ');
  if (label) return label;
  return s.boq_position_id ? s.boq_position_id.slice(0, 8) : '-';
}

export function POSourceRequisitions({ poId }: { poId: string }) {
  const { t } = useTranslation();
  const { data, isLoading, isError } = useQuery({
    queryKey: ['procurement-po-trace', poId],
    queryFn: () => tracePurchaseOrder(poId),
    staleTime: 30_000,
  });

  // An older server answers this route with something else; show nothing then.
  if (isLoading || isError || !data || !Array.isArray(data.requisitions) || data.requisitions.length === 0) return null;

  const linked = (Array.isArray(data.lines) ? data.lines : []).filter((l) => l.requisition_item_id);
  return (
    <section
      aria-label={t('procurement.trace.po_sources_title', { defaultValue: 'Source requisitions' })}
      className="mt-4 rounded-lg border border-border-light bg-surface-secondary/40 p-3 text-sm"
    >
      <h4 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-content-tertiary">
        <Link2 size={13} />
        {t('procurement.trace.po_sources_title', { defaultValue: 'Source requisitions' })}
      </h4>
      <p className="mb-2 text-content-secondary">
        {data.requisitions.map((r) => r.req_number ?? r.id.slice(0, 8)).join(', ')}
      </p>
      <ul className="space-y-1.5">
        {linked.map((line) => (
          <li key={line.po_item_id} className="text-xs">
            <span className="font-medium text-content-primary">{line.description}</span>
            <span className="text-content-tertiary">
              {' · '}
              {t('procurement.trace.po_line_from', {
                defaultValue: '{{quantity}} {{unit}} from {{requisition}}',
                quantity: line.quantity,
                unit: line.unit ?? '',
                requisition: line.req_number ?? '-',
              })}
            </span>
            {line.sources.length > 0 && (
              <div className="text-content-tertiary">
                {t('procurement.trace.boq_sources', {
                  defaultValue: 'BOQ positions: {{positions}}',
                  positions: line.sources.map((s) => `${positionLabel(s)} (${s.quantity} ${s.unit ?? ''})`).join(', '),
                })}
              </div>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
