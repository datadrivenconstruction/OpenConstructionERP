// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Quote capture and levelling: upload supplier and subcontractor quotes for a
 * tender package, review what was read, level the quotes against the scope and
 * confirm each into a bid, a price list or a purchase order draft.
 */
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useParams, useSearchParams } from 'react-router-dom';
import { PageHeader } from '@/shared/ui/PageHeader';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { getErrorMessage } from '@/shared/lib/api';
import { formatCurrency } from '@/shared/lib/money';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { createQuoteFromText, uploadQuote, usePackages, useQuote, useQuotes, useQuoteMutation } from './api';
import { QuoteReview } from './QuoteReview';
import { LevellingView } from './LevellingView';

const ACCEPT = '.pdf,.xlsx,.xlsm,.png,.jpg,.jpeg,.eml,.txt,.csv';

export function QuoteCapturePage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const projectId = routeProjectId || activeProjectId || '';
  const [search, setSearch] = useSearchParams();
  const addToast = useToastStore((s) => s.addToast);

  const packagesQ = usePackages(projectId);
  const [packageId, setPackageId] = useState<string>(search.get('package') ?? '');
  const [selected, setSelected] = useState<string | null>(search.get('quote'));
  const [tab, setTab] = useState<'review' | 'levelling'>('review');
  const [pasted, setPasted] = useState('');
  const quotesQ = useQuotes(projectId, packageId || undefined);
  const quoteQ = useQuote(selected);

  useEffect(() => {
    if (!packageId && packagesQ.data && packagesQ.data.length > 0) setPackageId(packagesQ.data[0]!.id);
  }, [packageId, packagesQ.data]);

  useEffect(() => {
    const next = new URLSearchParams(search);
    if (packageId) next.set('package', packageId);
    if (selected) next.set('quote', selected);
    else next.delete('quote');
    if (next.toString() !== search.toString()) setSearch(next, { replace: true });
  }, [packageId, selected, search, setSearch]);

  const onDone = {
    onSuccess: (q: { id: string }) => {
      setSelected(q.id);
      setTab('review');
      addToast({ type: 'success', title: t('quote_capture.captured', 'Quote read, please review it') });
    },
    onError: (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) }),
  };
  const uploadMut = useQuoteMutation((file: File) => uploadQuote(projectId, file, packageId || undefined));
  const textMut = useQuoteMutation((text: string) =>
    createQuoteFromText({ project_id: projectId, package_id: packageId || undefined, text }),
  );

  if (!projectId) return <RequiresProject>{null}</RequiresProject>;

  return (
    <div className="flex flex-col gap-4 p-4">
      <PageHeader
        srTitle={t('quote_capture.title', 'Quote capture and levelling')}
        subtitle={t(
          'quote_capture.subtitle',
          'Read supplier quotes from PDF, scans, Excel or email, check every value against the document, level them and confirm.',
        )}
      />

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col text-xs text-content-secondary">
          {t('quote_capture.package', 'Tender package')}
          <select
            className="rounded border px-2 py-1 text-sm text-content-primary"
            value={packageId}
            onChange={(e) => {
              setPackageId(e.target.value);
              setSelected(null);
            }}
          >
            {(packagesQ.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </label>
        <label className="cursor-pointer rounded bg-oe-blue px-3 py-1.5 text-sm text-white">
          {uploadMut.isPending ? t('quote_capture.reading', 'Reading...') : t('quote_capture.upload', 'Upload quote')}
          <input
            type="file"
            accept={ACCEPT}
            className="hidden"
            data-testid="quote-upload"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) uploadMut.mutate(file, onDone);
              e.target.value = '';
            }}
          />
        </label>
        <div className="flex gap-1" role="tablist">
          {(['review', 'levelling'] as const).map((k) => (
            <button
              key={k}
              type="button"
              role="tab"
              aria-selected={tab === k}
              className={`rounded px-3 py-1.5 text-sm ${tab === k ? 'bg-surface-secondary font-semibold' : ''}`}
              onClick={() => setTab(k)}
            >
              {k === 'review' ? t('quote_capture.tab_review', 'Review') : t('quote_capture.tab_levelling', 'Levelling')}
            </button>
          ))}
        </div>
      </div>

      <details className="rounded border p-2 text-sm">
        <summary className="cursor-pointer">{t('quote_capture.paste', 'Paste a quote from an email')}</summary>
        <textarea
          className="mt-2 h-32 w-full rounded border p-2 font-mono text-xs"
          dir="auto"
          value={pasted}
          onChange={(e) => setPasted(e.target.value)}
          aria-label={t('quote_capture.paste', 'Paste a quote from an email')}
        />
        <button
          type="button"
          className="mt-1 rounded border px-3 py-1 disabled:opacity-40"
          disabled={!pasted.trim() || textMut.isPending}
          onClick={() => textMut.mutate(pasted, { ...onDone, onSuccess: (q) => { setPasted(''); onDone.onSuccess(q); } })}
        >
          {t('quote_capture.read_text', 'Read quote')}
        </button>
      </details>

      {tab === 'levelling' && packageId ? (
        <LevellingView packageId={packageId} />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[260px_1fr]">
          <ul className="flex flex-col gap-1" data-testid="quote-list">
            {(quotesQ.data ?? []).length === 0 && (
              <li className="text-sm text-content-secondary">{t('quote_capture.empty', 'No quotes captured yet.')}</li>
            )}
            {(quotesQ.data ?? []).map((q) => (
              <li key={q.id}>
                <button
                  type="button"
                  onClick={() => setSelected(q.id)}
                  className={`w-full rounded border px-2 py-1.5 text-left text-sm ${selected === q.id ? 'border-oe-blue bg-surface-secondary' : ''}`}
                >
                  <div className="font-medium" dir="auto">{q.supplier_name || q.original_filename}</div>
                  <div className="text-xs text-content-secondary">
                    {formatCurrency(q.quote_total, q.currency)} · {t(`quote_capture.status_${q.status}`, q.status)} ·{' '}
                    {t(`quote_capture.engine_${q.extraction_engine}`, q.extraction_engine)}
                  </div>
                </button>
              </li>
            ))}
          </ul>
          <div>
            {quoteQ.data ? (
              <QuoteReview key={quoteQ.data.id + quoteQ.data.status} quote={quoteQ.data} />
            ) : (
              <p className="text-sm text-content-secondary">{t('quote_capture.pick', 'Pick a quote or upload one.')}</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
