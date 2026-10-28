// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Review of one captured quote: the document on the left, the extracted header,
 * conditions and lines on the right, each value with its confidence. Clicking a
 * value shows where it was read. Nothing is written anywhere until the reviewer
 * confirms, and the confirm stays disabled while a validation error is open.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  CONFIRM_TARGETS,
  confirmQuote,
  LOW_CONFIDENCE,
  updateLine,
  updateQuote,
  useConfirmQuote,
  useQuoteMutation,
  type Anchor,
  type ConfirmTarget,
  type Quote,
  type QuoteLine,
} from './api';
import { DocumentPane } from './DocumentPane';
import { BAND_CLASS, confidenceBand, formatDecimal, parseLocaleDecimal } from './format';

const HEADER_KEYS = [
  'supplier',
  'quote_date',
  'valid_until',
  'currency',
  'payment_terms',
  'delivery',
  'quote_total',
  'tax_basis',
  'tax_rate',
] as const;

function ConfidenceChip({ value }: { value: number }) {
  const band = confidenceBand(value);
  return (
    <span data-testid="confidence" data-band={band} className={`rounded px-1.5 py-0.5 text-2xs font-medium ${BAND_CLASS[band]}`}>
      {Math.round(value * 100)}%
    </span>
  );
}

export function QuoteReview({ quote }: { quote: Quote }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [anchor, setAnchor] = useState<Anchor | null>(null);
  const [acceptWarnings, setAcceptWarnings] = useState(false);
  const locked = quote.status === 'confirmed';

  const headerMut = useQuoteMutation((body: unknown) => updateQuote(quote.id, body));
  const lineMut = useQuoteMutation(({ lineId, body }: { lineId: string; body: unknown }) => updateLine(quote.id, lineId, body));
  const confirmMut = useConfirmQuote(quote.id, confirmQuote);

  const errors = quote.findings.filter((f) => f.severity === 'error');
  const warnings = quote.findings.filter((f) => f.severity !== 'error');
  const canConfirm = !locked && errors.length === 0 && (warnings.length === 0 || acceptWarnings);

  const onError = (e: unknown) => addToast({ type: 'error', title: getErrorMessage(e) });
  const editLine = (line: QuoteLine, body: Record<string, unknown>) =>
    lineMut.mutate({ lineId: line.id, body }, { onError });

  const editNumber = (line: QuoteLine, key: 'quantity' | 'unit_rate' | 'total', text: string) => {
    const value = parseLocaleDecimal(text);
    if (value !== null && value !== line[key]) editLine(line, { [key]: value });
  };

  const targetLabel: Record<ConfirmTarget, string> = {
    bid: t('quote_capture.confirm_bid', 'Add as bid to the tender comparison'),
    price_list: t('quote_capture.confirm_price_list', 'Update the supplier price list'),
    po_draft: t('quote_capture.confirm_po', 'Create a purchase order draft'),
  };

  return (
    <div className="grid gap-4 lg:grid-cols-2" data-testid="quote-review">
      <div className="lg:sticky lg:top-4 lg:self-start">
        <DocumentPane quote={quote} anchor={anchor} />
      </div>

      <div className="flex flex-col gap-4">
        <section className="rounded border p-3">
          <h3 className="mb-2 text-sm font-semibold">{t('quote_capture.header', 'Quote header')}</h3>
          <table className="w-full text-sm">
            <tbody>
              {HEADER_KEYS.map((key) => {
                const f = quote.header[key];
                return (
                  <tr key={key} className="border-t first:border-t-0">
                    <td className="py-1 pr-2 text-content-secondary">{t(`quote_capture.field_${key}`, key)}</td>
                    <td className="py-1">
                      <input
                        aria-label={t(`quote_capture.field_${key}`, key)}
                        className="w-full rounded border px-2 py-0.5"
                        defaultValue={f?.value ?? ''}
                        disabled={locked}
                        onFocus={() => setAnchor(f?.anchor ?? null)}
                        onBlur={(e) => {
                          if (e.target.value !== (f?.value ?? ''))
                            headerMut.mutate({ header: { [key]: { value: e.target.value } } }, { onError });
                        }}
                      />
                    </td>
                    <td className="py-1 pl-2 text-right">{f ? <ConfidenceChip value={f.confidence} /> : null}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {quote.tax?.net && (
            <p className="mt-2 text-xs text-content-secondary" data-testid="quote-tax">
              {t('quote_capture.tax_line', 'Net {{net}}, {{tax_name}} {{rate}}% {{tax}}, gross {{gross}}', {
                net: formatDecimal(quote.tax.net),
                tax: formatDecimal(quote.tax.tax),
                gross: formatDecimal(quote.tax.gross),
                rate: quote.tax.rate ?? '0',
                tax_name: t(`quote_capture.tax_${quote.tax.tax_name ?? 'vat'}`, quote.tax.tax_name ?? 'VAT'),
              })}
            </p>
          )}
        </section>

        {quote.notes.length > 0 && (
          <section className="rounded border p-3" data-testid="quote-notes">
            <h3 className="mb-2 text-sm font-semibold">{t('quote_capture.conditions', 'Exclusions and conditions')}</h3>
            <ul className="flex flex-col gap-1 text-sm">
              {quote.notes.map((n) => (
                <li key={n.id} className="flex items-start gap-2">
                  <input
                    type="checkbox"
                    data-testid="note-ack"
                    aria-label={t('quote_capture.acknowledge', 'Acknowledge')}
                    checked={n.acknowledged}
                    disabled={locked || n.acknowledged}
                    onChange={() => headerMut.mutate({ acknowledge_notes: [n.id] }, { onError })}
                  />
                  <button type="button" className="text-left" onClick={() => setAnchor(n.anchor)} dir="auto">
                    <span className="mr-1 rounded bg-surface-secondary px-1 text-2xs uppercase">
                      {t(`quote_capture.note_${n.kind}`, n.kind)}
                    </span>
                    {n.text}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        <section className="rounded border p-3">
          <h3 className="mb-2 text-sm font-semibold">{t('quote_capture.lines', 'Line items')}</h3>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="text-left text-xs text-content-secondary">
                <tr>
                  <th className="py-1">{t('quote_capture.col_description', 'Description')}</th>
                  <th>{t('quote_capture.col_qty', 'Qty')}</th>
                  <th>{t('quote_capture.col_unit', 'Unit')}</th>
                  <th>{t('quote_capture.col_rate', 'Rate')}</th>
                  <th>{t('quote_capture.col_total', 'Total')}</th>
                  <th>{t('quote_capture.col_confidence', 'Confidence')}</th>
                  <th>{t('quote_capture.col_match', 'Matched position')}</th>
                  <th>{t('quote_capture.col_reviewed', 'Reviewed')}</th>
                </tr>
              </thead>
              <tbody>
                {quote.lines.map((line) => {
                  const m = line.match;
                  const options = [
                    ...(m?.position_id ? [{ position_id: m.position_id, ordinal: m.ordinal ?? '', description: m.description ?? '', confidence: m.confidence }] : []),
                    ...(m?.alternatives ?? []),
                  ];
                  const low = line.confidence < LOW_CONFIDENCE && !line.reviewed;
                  return (
                    <tr
                      key={line.id}
                      data-testid="quote-line"
                      data-low={low || undefined}
                      className={`border-t align-top ${low ? 'bg-rose-50 dark:bg-rose-950/30' : ''}`}
                      onClick={() => setAnchor(line.anchor)}
                    >
                      <td className="py-1 pr-2" dir="auto">{line.description}</td>
                      {(['quantity', 'unit', 'unit_rate', 'total'] as const).map((key) => (
                        <td key={key} className="pr-1">
                          <input
                            aria-label={`${line.id}-${key}`}
                            className="w-20 rounded border px-1 py-0.5 text-right"
                            defaultValue={key === 'unit' ? line.unit : formatDecimal(line[key], key === 'quantity' ? 0 : 2)}
                            disabled={locked}
                            onBlur={(e) =>
                              key === 'unit'
                                ? e.target.value !== line.unit && editLine(line, { unit: e.target.value })
                                : editNumber(line, key, e.target.value)
                            }
                          />
                        </td>
                      ))}
                      <td><ConfidenceChip value={line.confidence} /></td>
                      <td className="min-w-[180px]">
                        <select
                          aria-label={`${line.id}-match`}
                          className="w-full rounded border px-1 py-0.5 text-xs"
                          disabled={locked}
                          value={m?.position_id ?? ''}
                          onChange={(e) =>
                            editLine(line, e.target.value ? { position_id: e.target.value } : { clear_match: true })
                          }
                        >
                          <option value="">{t('quote_capture.no_match', 'No match')}</option>
                          {options.map((o) => (
                            <option key={o.position_id} value={o.position_id}>
                              {`${o.ordinal} ${o.description}`.trim()} ({Math.round(o.confidence * 100)}%)
                            </option>
                          ))}
                        </select>
                        {m?.status === 'suggested' && (
                          <span className="text-2xs text-content-tertiary">{t('quote_capture.suggested', 'Suggested, not confirmed')}</span>
                        )}
                      </td>
                      <td className="text-center">
                        <input
                          type="checkbox"
                          aria-label={`${line.id}-reviewed`}
                          checked={line.reviewed}
                          disabled={locked}
                          onChange={(e) => editLine(line, { reviewed: e.target.checked })}
                        />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>

        <section className="rounded border p-3" data-testid="quote-findings">
          <h3 className="mb-2 text-sm font-semibold">{t('quote_capture.checks', 'Checks')}</h3>
          {quote.findings.length === 0 ? (
            <p className="text-sm text-emerald-700">{t('quote_capture.checks_ok', 'All checks pass.')}</p>
          ) : (
            <ul className="flex flex-col gap-1 text-sm">
              {quote.findings.map((f, i) => (
                <li key={`${f.rule_id}-${i}`} className={f.severity === 'error' ? 'text-rose-700' : 'text-amber-700'}>
                  <strong className="mr-1">{t(`quote_capture.rule.${f.rule_id.split('.')[1]}`, f.rule_id)}:</strong>
                  {f.message}
                </li>
              ))}
            </ul>
          )}
        </section>

        {locked ? (
          <p className="rounded border border-emerald-300 bg-emerald-50 p-3 text-sm dark:bg-emerald-950/30" data-testid="quote-confirmed">
            {t('quote_capture.confirmed_as', 'Confirmed: {{target}}', {
              target: quote.confirmation.target ? targetLabel[quote.confirmation.target] : '',
            })}
          </p>
        ) : (
          <section className="flex flex-col gap-2 rounded border p-3">
            {warnings.length > 0 && (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" data-testid="accept-warnings" checked={acceptWarnings} onChange={(e) => setAcceptWarnings(e.target.checked)} />
                {t('quote_capture.accept_warnings', 'I have read the warnings and want to continue')}
              </label>
            )}
            <div className="flex flex-wrap gap-2">
              {CONFIRM_TARGETS.map((target) => (
                <button
                  key={target}
                  type="button"
                  data-testid={`confirm-${target}`}
                  className="rounded bg-oe-blue px-3 py-1.5 text-sm text-white disabled:opacity-40"
                  disabled={!canConfirm || confirmMut.isPending || (target === 'bid' && !quote.package_id)}
                  onClick={() =>
                    confirmMut.mutate(
                      { target, acceptWarnings },
                      {
                        onSuccess: () => addToast({ type: 'success', title: t('quote_capture.confirmed', 'Quote confirmed') }),
                        onError,
                      },
                    )
                  }
                >
                  {targetLabel[target]}
                </button>
              ))}
            </div>
            {errors.length > 0 && (
              <p className="text-xs text-rose-700">
                {t('quote_capture.fix_errors', 'Resolve the errors above before confirming.')}
              </p>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
