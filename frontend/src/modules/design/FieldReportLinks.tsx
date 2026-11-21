// Design module (ERP side of the design editor link).
/**
 * Field reports of the selected elements: the reports that name them (or a BOQ position they feed), each one opening
 * the elements it points at (ERP viewer isolate / editor selection); and a picker to link another report to the
 * selection. The person chooses the report and confirms; nothing is linked by itself.
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { getErrorMessage } from '@/shared/lib/api';
import { tr } from './BriefFields';
import { editorUrl, fetchFieldReports, fetchReportElements, putReportLinks, reportViewerUrl, type FieldReportRow } from './linksApi';

/** ``inBlock``: inside a selection panel block, which carries the heading and says when loading failed. */
export function FieldReportLinks({ projectId, keys, inBlock = false }: { projectId: string; keys: string[]; inBlock?: boolean }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [picking, setPicking] = useState(false);
  const [chosen, setChosen] = useState('');
  const [error, setError] = useState<string | null>(null);
  const hits = useQuery({
    queryKey: ['design-field-reports', projectId, keys], queryFn: () => fetchFieldReports(projectId, keys),
    enabled: keys.length > 0, retry: false, staleTime: 30_000,
  });
  const all = useQuery({
    queryKey: ['design-field-reports', projectId, 'all'], queryFn: () => fetchFieldReports(projectId, []),
    enabled: picking, retry: false,
  });
  const link = useMutation({
    mutationFn: (r: FieldReportRow) => putReportLinks(projectId, r.id, {
      keys: [...new Set([...r.keys, ...keys])], position_ids: r.position_ids }),
    onSuccess: () => { setPicking(false); setChosen(''); setError(null); void qc.invalidateQueries({ queryKey: ['design-field-reports'] }); },
    onError: (e) => setError(getErrorMessage(e)),
  });
  const open = async (r: FieldReportRow, target: 'model' | 'editor') => {
    setError(null);
    try {
      const e = await fetchReportElements(projectId, r.id);
      const url = target === 'model' ? reportViewerUrl(projectId, e) : editorUrl(e.keys);
      if (!url || e.keys.length === 0) setError(tr(t, 'design.reports.no_elements'));
      else navigate(url);
    } catch (err) {
      setError(getErrorMessage(err));
    }
  };
  if (keys.length === 0) return null;
  if (hits.isError) return inBlock ? <p className="text-content-secondary">{tr(t, 'design.panel.failed')}</p> : null;
  const items = hits.data?.items ?? [];
  const linkable = (all.data?.items ?? []).filter((r) => r.status !== 'approved' && !keys.every((k) => r.keys.includes(k)));
  const btn = 'rounded-md px-1.5 py-0.5 text-xs text-oe-blue-text hover:bg-surface-secondary hover:underline disabled:opacity-50';
  const label = (r: FieldReportRow) => `${r.report_date} · ${r.report_type}${r.excerpt ? ` · ${r.excerpt.slice(0, 60)}` : ''}`;
  return (
    <div className="flex flex-col gap-1.5" data-testid="field-report-links">
      {!inBlock && <p className="text-2xs font-medium text-content-tertiary">{tr(t, 'design.reports.title')}</p>}
      {hits.isLoading ? <p className="text-content-tertiary">…</p>
        : items.length === 0 ? <p className="text-content-secondary">{tr(t, 'design.reports.none')}</p>
        : items.map((r) => (
          <div key={r.id} className="rounded-md border border-border-light px-2.5 py-1.5" data-testid={`report-${r.id}`}>
            <p className="truncate font-medium text-content-primary">{label(r)}</p>
            <p className="flex flex-wrap items-center gap-1 text-xs text-content-tertiary">
              <span>{r.status}</span>
              <button type="button" className={btn} onClick={() => void open(r, 'model')} data-testid={`report-model-${r.id}`}>
                {tr(t, 'design.links.show_in_model')}</button>
              <button type="button" className={btn} onClick={() => void open(r, 'editor')} data-testid={`report-editor-${r.id}`}>
                {tr(t, 'design.links.select_in_editor')}</button>
            </p>
          </div>
        ))}
      {picking ? (
        <div className="flex flex-col gap-1.5">
          <select value={chosen} onChange={(e) => setChosen(e.target.value)} aria-label={tr(t, 'design.reports.pick')}
            className="rounded-md border border-border-light bg-surface-primary px-2 py-1 text-xs" data-testid="report-pick">
            <option value="">{all.isLoading ? '…' : tr(t, 'design.reports.pick')}</option>
            {linkable.map((r) => <option key={r.id} value={r.id}>{label(r)}</option>)}
          </select>
          <div className="flex gap-2">
            <button type="button" className={btn} disabled={!chosen || link.isPending} data-testid="report-confirm"
              onClick={() => { const r = linkable.find((x) => x.id === chosen); if (r) link.mutate(r); }}>
              {tr(t, 'design.reports.confirm', { count: keys.length })}</button>
            <button type="button" className={btn} onClick={() => setPicking(false)}>{tr(t, 'design.reports.cancel')}</button>
          </div>
        </div>
      ) : (
        <button type="button" className={`${btn} self-start`} onClick={() => setPicking(true)} data-testid="report-link-open">
          {tr(t, 'design.reports.link')}</button>
      )}
      {error && <p role="alert" className="text-xs text-semantic-error">{error}</p>}
    </div>
  );
}
