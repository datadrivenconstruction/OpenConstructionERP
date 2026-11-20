// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useState } from 'react';
import { Navigate, useLocation, useParams } from 'react-router-dom';
import { resolveLegacyTender, tenderCardPath, type LegacyTable } from './api';

const LEGACY: Record<'tendering' | 'rfq_bidding', { table: LegacyTable; param: string }> = {
  tendering: { table: 'oe_tendering_package', param: 'package' },
  rfq_bidding: { table: 'oe_rfq_rfq', param: 'rfq' },
};

/**
 * The old /tendering and /rfq-bidding addresses. A link that named one
 * package (``?package=`` / ``?rfq=``) opens that tender's card; any other
 * lands on the Tenders list filtered to where it came from.
 */
export function LegacyTenderRedirect({ source }: { source: 'tendering' | 'rfq_bidding' }) {
  const { search } = useLocation();
  const { projectId } = useParams<{ projectId?: string }>();
  const { table, param } = LEGACY[source];
  const legacyId = new URLSearchParams(search).get(param);
  const list = `${projectId ? `/projects/${projectId}` : ''}/tenders?source=${source}`;
  const [target, setTarget] = useState<string | null>(legacyId ? null : list);

  useEffect(() => {
    if (!legacyId) return;
    let live = true;
    resolveLegacyTender(table, legacyId)
      .then((r) => live && setTarget(tenderCardPath(r.package_id)))
      .catch(() => live && setTarget(list));
    return () => {
      live = false;
    };
  }, [legacyId, table, list]);

  return target ? <Navigate to={target} replace /> : null;
}
