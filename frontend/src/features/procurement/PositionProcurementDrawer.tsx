// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// PositionProcurementDrawer - what has been requested and ordered for one BOQ
// position.
//
// Opened from the bill editor's row menu. Each row is one BOQ source of a
// requisition line: the quantity this position contributed, the line it went
// into, the requisition's status, and the purchase order lines raised from
// that requisition line. The figures are the ones stored at the source, so a
// later edit of the position does not rewrite what was asked for.
//
// Above the list, the supplier suggested for the position's materials can be
// set (issue #516); new requisitions raised from the bill carry it.

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { ClipboardList } from 'lucide-react';
import { SideDrawer, Skeleton } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { traceBoqPosition } from './requisitionsApi';
import { PositionSuggestedSupplier } from './PositionSuggestedSupplier';

interface PositionProcurementDrawerProps {
  open: boolean;
  onClose: () => void;
  projectId: string | undefined;
  positionId: string | null;
  positionOrdinal: string;
  positionDescription: string;
}

export function PositionProcurementDrawer({
  open,
  onClose,
  projectId,
  positionId,
  positionOrdinal,
  positionDescription,
}: PositionProcurementDrawerProps) {
  const { t } = useTranslation();
  const { data, isLoading, error } = useQuery({
    queryKey: ['procurement-position-trace', projectId, positionId],
    queryFn: () => traceBoqPosition(positionId!, projectId!),
    enabled: open && !!positionId && !!projectId,
  });

  return (
    <SideDrawer
      open={open}
      onClose={onClose}
      title={t('procurement.trace.position_title', { defaultValue: 'Requisitions and orders' })}
      subtitle={[positionOrdinal, positionDescription].filter(Boolean).join(' · ')}
    >
      <div className="space-y-3 p-4 text-sm">
        {open && positionId && <PositionSuggestedSupplier positionId={positionId} />}
        {isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : error ? (
          <p role="alert" className="text-semantic-error">
            {getErrorMessage(error)}
          </p>
        ) : !data || data.items.length === 0 ? (
          <p className="text-content-secondary">
            {t('procurement.trace.position_empty', {
              defaultValue: 'Nothing has been requested for this position yet.',
            })}
          </p>
        ) : (
          <ul className="space-y-2">
            {data.items.map((row) => (
              <li
                key={`${row.requisition_item_id}-${row.resource_key ?? ''}`}
                className="rounded-lg border border-border-light p-3"
              >
                <div className="flex items-center justify-between gap-2">
                  <Link
                    to={`/procurement?requisition=${encodeURIComponent(row.requisition_id)}`}
                    className="flex items-center gap-1.5 font-mono text-xs text-oe-blue hover:underline"
                  >
                    <ClipboardList size={13} />
                    {row.req_number ?? row.requisition_id.slice(0, 8)}
                  </Link>
                  <span className="text-2xs uppercase tracking-wide text-content-tertiary">
                    {t(`procurement.requisitions.status.${row.requisition_status}`, {
                      defaultValue: row.requisition_status,
                    })}
                  </span>
                </div>
                <p className="mt-1 text-content-primary">{row.description}</p>
                <p className="text-xs text-content-secondary">
                  {t('procurement.trace.position_contributed', {
                    defaultValue: 'This position: {{quantity}} {{unit}} of {{requested}} {{line_unit}} requested',
                    quantity: row.source_quantity,
                    unit: row.source_unit ?? '',
                    requested: row.quantity_requested,
                    line_unit: row.line_unit ?? '',
                  })}
                </p>
                {row.purchase_orders.length === 0 ? (
                  <p className="mt-1 text-xs text-content-tertiary">
                    {t('procurement.trace.not_ordered', { defaultValue: 'Not ordered yet' })}
                  </p>
                ) : (
                  <ul className="mt-1 space-y-0.5">
                    {row.purchase_orders.map((po) => (
                      <li key={po.po_item_id} className="text-xs text-content-secondary">
                        {t('procurement.requisitions.po_line_ref', {
                          defaultValue: 'PO {{number}}: {{quantity}} {{unit}}',
                          number: po.po_number ?? po.po_id.slice(0, 8),
                          quantity: po.quantity,
                          unit: po.unit ?? '',
                        })}
                        {po.po_status ? <span className="text-content-tertiary"> ({po.po_status})</span> : null}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </SideDrawer>
  );
}
