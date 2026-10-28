// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The procurement records of this project that a package or an
// owner-furnished item can point to, read from the modules that own them so
// the reader picks a record by its number and title instead of pasting an id.
//
// Requisitions have no project list endpoint yet, so that kind answers with
// `null`: the dialog then says the list is not available, which is different
// from "this project has none".

import { apiGet, type Page } from '@/shared/lib/api';
import { listPackages as listBidPackages } from '@/features/bid-management/api';
import { listContracts } from '@/features/contracts/api';
import { fetchRFQs } from '@/features/rfq-bidding/api';
import { listAgreements } from '@/features/subcontractors/api';

import type { OfiLinkKind, PackageLinkKind } from './api';

export type LinkKind = PackageLinkKind | OfiLinkKind;

export interface LinkTarget {
  id: string;
  /** The record's own number or code, when it has one. */
  code: string;
  title: string;
}

/** Candidates for one kind, or null when no list exists for that kind. */
export async function fetchLinkTargets(projectId: string, kind: LinkKind): Promise<LinkTarget[] | null> {
  const pid = encodeURIComponent(projectId);
  switch (kind) {
    case 'contract': {
      const page = await listContracts({ project_id: projectId, limit: 200 });
      return page.items.map((c) => ({ id: c.id, code: c.code, title: c.title }));
    }
    case 'bid_package': {
      const rows = await listBidPackages({ project_id: projectId, limit: 200 });
      return rows.map((b) => ({ id: b.id, code: b.code, title: b.title }));
    }
    case 'tender_package': {
      const rows = await apiGet<Array<{ id: string; name: string }>>(`/v1/tendering/packages/?project_id=${pid}`);
      return rows.map((r) => ({ id: r.id, code: '', title: r.name }));
    }
    case 'rfq': {
      const page = await fetchRFQs(projectId);
      return page.items.map((r) => ({ id: r.id, code: r.rfq_number, title: r.title }));
    }
    case 'subcontract_agreement': {
      const rows = await listAgreements({ project_id: projectId });
      return rows.map((a) => ({ id: a.id, code: '', title: a.title }));
    }
    case 'purchase_order': {
      const page = await apiGet<Page<{ id: string; po_number: string; vendor_name: string | null }>>(
        `/v1/procurement/?project_id=${pid}&limit=100`,
      );
      return page.items.map((o) => ({ id: o.id, code: o.po_number, title: o.vendor_name ?? '' }));
    }
    default:
      return null;
  }
}
