// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The estimate part of the header path: Project › Estimate · v2 › Page.
 * Shown on any route that names a bill (/boq/:boqId) or, inside a project,
 * on pages that work on the active bill. The version is the bill's place in
 * its revision chain (parent_estimate_id), counted from the project's bill
 * list the app already caches.
 */
import { Link, matchPath, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ChevronRight } from 'lucide-react';
import { apiGet } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

interface BillRow {
  id: string;
  project_id: string;
  name: string;
  status: string;
  parent_estimate_id?: string | null;
}

/** 1 for an original bill, 2 for its first revision, and so on. */
export function revisionNumber(bills: Pick<BillRow, 'id' | 'parent_estimate_id'>[], id: string): number {
  const byId = new Map(bills.map((b) => [b.id, b]));
  let n = 1;
  let cur = byId.get(id);
  const seen = new Set<string>();
  while (cur?.parent_estimate_id && !seen.has(cur.id) && n < 100) {
    seen.add(cur.id);
    cur = byId.get(cur.parent_estimate_id);
    if (!cur) break;
    n++;
  }
  return n;
}

export function EstimateCrumb() {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const projectId = useProjectContextStore((s) => s.activeProjectId);
  const routeBoq = matchPath('/boq/:boqId', pathname)?.params.boqId ?? null;
  const boqId = routeBoq && routeBoq !== 'new' ? routeBoq : null;

  const bills = useQuery({
    queryKey: ['boqs', projectId],
    queryFn: () => apiGet<BillRow[]>(`/v1/boq/boqs/?project_id=${projectId}`),
    enabled: !!projectId && !!boqId,
    staleTime: 60_000,
  });
  const bill = bills.data?.find((b) => b.id === boqId);
  if (!boqId || !bill) return null;
  const version = revisionNumber(bills.data ?? [], bill.id);

  return (
    <nav aria-label={t('crumbs.estimate', { defaultValue: 'Estimate' })} className="hidden md:flex min-w-0 items-center gap-2">
      <ChevronRight size={14} strokeWidth={1.75} className="shrink-0 text-content-quaternary/60" aria-hidden data-decorative-icon />
      <Link
        to={`/boq/${bill.id}`}
        className="min-w-0 max-w-[16rem] truncate text-sm font-medium text-content-primary hover:underline"
        title={bill.name}
      >
        {bill.name}
      </Link>
      <span
        className="shrink-0 rounded border border-border-light px-1.5 text-xs tabular-nums text-content-secondary"
        title={t('crumbs.version_title', { defaultValue: 'Revision {{n}} of this estimate', n: version })}
      >
        {t('crumbs.version', { defaultValue: 'v{{n}}', n: version })}
      </span>
    </nav>
  );
}
