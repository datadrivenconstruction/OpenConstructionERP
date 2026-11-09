import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { boqApi, type PdfDetails, type PdfOptionalColumn } from './api';

export interface PdfDetailsPanelProps {
  t: (key: string, options?: Record<string, string | number>) => string;
  projectId: string;
  readOnly?: boolean;
}

const EMPTY: PdfDetails = {
  client_name: '',
  client_address: '',
  project_number: '',
  site_address: '',
  payment_terms: '',
  hidden_columns: [],
};

/**
 * Client, site and payment terms printed on the estimate PDF, and which optional
 * columns it carries. Stored once per project; every bill of the project prints
 * them. Fields left empty print nothing.
 */
export function PdfDetailsPanel({ t, projectId, readOnly = false }: PdfDetailsPanelProps) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ['boq-pdf-details', projectId],
    queryFn: () => boqApi.getPdfDetails(projectId),
  });
  const [draft, setDraft] = useState<PdfDetails>(EMPTY);
  useEffect(() => {
    if (query.data) setDraft(query.data);
  }, [query.data]);
  const save = useMutation({
    mutationFn: (value: PdfDetails) => boqApi.putPdfDetails(projectId, value),
    onSuccess: (saved) => {
      queryClient.setQueryData(['boq-pdf-details', projectId], saved);
    },
  });
  const set = (field: keyof Omit<PdfDetails, 'hidden_columns'>, value: string) =>
    setDraft((d) => ({ ...d, [field]: value }));
  const toggleColumn = (column: PdfOptionalColumn, printed: boolean) =>
    setDraft((d) => ({
      ...d,
      hidden_columns: printed ? d.hidden_columns.filter((c) => c !== column) : [...d.hidden_columns, column],
    }));
  const disabled = readOnly || save.isPending;
  const input = 'w-full rounded border border-border-light px-1.5 py-1 text-xs';

  const line = (field: 'client_name' | 'project_number', key: string, fallback: string) => (
    <label className="block text-content-secondary">
      {t(key, { defaultValue: fallback })}
      <input
        type="text"
        className={input}
        value={draft[field]}
        maxLength={field === 'client_name' ? 200 : 60}
        disabled={disabled}
        onChange={(e) => set(field, e.target.value)}
        data-testid={`pdf-details-${field}`}
      />
    </label>
  );
  const block = (field: 'client_address' | 'site_address' | 'payment_terms', key: string, fallback: string, max: number) => (
    <label className="block text-content-secondary">
      {t(key, { defaultValue: fallback })}
      <textarea
        className={input}
        rows={field === 'payment_terms' ? 3 : 2}
        value={draft[field]}
        maxLength={max}
        disabled={disabled}
        onChange={(e) => set(field, e.target.value)}
        data-testid={`pdf-details-${field}`}
      />
    </label>
  );

  return (
    <details className="border-b border-border-light px-3 py-2.5 text-xs" data-testid="pdf-details-panel">
      <summary className="cursor-pointer text-sm text-content-primary">
        {t('boq.pdf_details_title', { defaultValue: 'Estimate PDF details' })}
      </summary>
      <div className="mt-2 space-y-1.5">
        {line('client_name', 'boq.pdf_details_client', 'Client')}
        {block('client_address', 'boq.pdf_details_client_address', 'Client address', 500)}
        {line('project_number', 'boq.pdf_details_project_number', 'Project number')}
        {block('site_address', 'boq.pdf_details_site_address', 'Site address', 500)}
        {block('payment_terms', 'boq.pdf_details_payment_terms', 'Payment terms', 2000)}
        <fieldset className="space-y-0.5">
          <legend className="text-content-secondary">
            {t('boq.pdf_details_cols_title', { defaultValue: 'Columns on the printed estimate' })}
          </legend>
          {(
            [
              ['qty_unit', 'boq.pdf_details_col_qty_unit', 'Quantity and unit'],
              ['rate', 'boq.pdf_details_col_rate', 'Unit rate'],
            ] as const
          ).map(([column, key, fallback]) => (
            <label key={column} className="flex items-center gap-2 text-content-primary">
              <input
                type="checkbox"
                checked={!draft.hidden_columns.includes(column)}
                disabled={disabled}
                onChange={(e) => toggleColumn(column, e.target.checked)}
                data-testid={`pdf-details-col-${column}`}
              />
              {t(key, { defaultValue: fallback })}
            </label>
          ))}
        </fieldset>
        {query.isError && (
          <p className="text-semantic-error" role="alert">
            {t('boq.export_failed', { defaultValue: 'Export failed' })}
          </p>
        )}
        {!readOnly && (
          <button
            type="button"
            className="rounded bg-oe-blue px-3 py-1 text-xs text-white disabled:opacity-50"
            disabled={save.isPending || query.isLoading}
            onClick={() => save.mutate(draft)}
            data-testid="pdf-details-save"
          >
            {save.isSuccess && !save.isPending ? t('common.saved', { defaultValue: 'Saved' }) : t('common.save', { defaultValue: 'Save' })}
          </button>
        )}
      </div>
    </details>
  );
}
