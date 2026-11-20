// Design module (ERP side of the design editor link).
/**
 * Tender addendum drafts waiting for a person: an accepted revision changed a package already issued to bidders,
 * so the ERP prepared an addendum DRAFT there (positions before/after, linked elements, sheets). It is never sent
 * on its own; each row opens the package in Tendering, where a person reviews, edits and publishes it.
 */
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { ArrowRight, FileWarning } from 'lucide-react';
import { tr } from './BriefFields';
import { packageUrl } from './linksApi';
import { fetchProcurement } from './procurementApi';

export function AddendumDrafts({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const q = useQuery({ queryKey: ['design-procurement', projectId], queryFn: () => fetchProcurement(projectId), retry: false });
  const rows = (q.data?.packages ?? []).flatMap((p) => (p.addenda ?? [])
    .filter((a) => a.state === 'draft' && p.package_id)
    .map((a) => ({ ...a, package_id: p.package_id!, name: p.name ?? p.ifc_class })));
  if (!rows.length) return null;
  return (
    <section aria-labelledby="addenda-title" data-testid="addendum-drafts"
      className="rounded-xl border border-semantic-warning/50 bg-semantic-warning/5 p-4">
      <h2 id="addenda-title" className="flex items-center gap-2 text-sm font-semibold text-content-primary">
        <FileWarning size={16} aria-hidden className="text-semantic-warning" />
        {tr(t, 'design.addendum.title', { count: rows.length })}
      </h2>
      <p className="mt-1 text-sm text-content-secondary">{tr(t, 'design.addendum.hint')}</p>
      <ul className="mt-3 flex flex-col gap-2">
        {rows.map((a) => (
          <li key={a.addendum_id}>
            <Link to={packageUrl(a)} data-testid={`addendum-${a.addendum_id}`}
              className="group flex flex-col gap-0.5 rounded-lg border border-border-light bg-surface-primary px-3 py-2 hover:border-oe-blue focus-visible:outline focus-visible:outline-2 focus-visible:outline-oe-blue sm:flex-row sm:items-center sm:gap-3">
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-content-primary">
                  {tr(t, 'design.addendum.row', { name: a.name, no: a.revision_no ?? '–', revision: a.revision_number ?? '–' })}
                </span>
                <span className="block text-xs text-content-secondary">
                  {tr(t, 'design.addendum.contents', { lines: a.lines, elements: a.elements, sheets: a.sheets })}
                </span>
              </span>
              <span className="inline-flex shrink-0 items-center gap-1 text-sm text-oe-blue-text group-hover:underline">
                {tr(t, 'design.addendum.review')} <ArrowRight size={14} aria-hidden />
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
