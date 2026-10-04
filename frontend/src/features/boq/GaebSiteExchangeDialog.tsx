// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * GAEB site phases for one bill: read an X31 measurement, write one, and
 * check a received X89 invoice.
 *
 * Reading an X31 never writes on its own. The server proposes a measured
 * quantity per OZ, the person ticks the ones to keep, and only those are
 * applied. OZ the bill does not have are listed, not dropped. Checking an
 * X89 writes nothing at all.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { AlertTriangle, CheckCircle2, Download, FileUp, Loader2, Ruler, X } from 'lucide-react';
import { Badge, Button } from '@/shared/ui';
import { fmtNumber } from '@/shared/lib/formatters';
import { useToastStore } from '@/stores/useToastStore';
import {
  applyX31,
  checkX89,
  downloadX31,
  previewX31,
  type X31Preview,
  type X89CheckReport,
} from './gaebSiteExchangeApi';

export type GaebSiteTab = 'x31_import' | 'x31_export' | 'x89_check';

export interface GaebSiteExchangeDialogProps {
  open: boolean;
  boqId: string;
  boqName: string;
  /** A file the editor's import button handed over (an .x31 or .x89). */
  initialFile?: File | null;
  /** Bill is locked: reading and checking still work, applying does not. */
  readOnly?: boolean;
  onClose: () => void;
  /** Called after quantities were written, so the editor can refetch. */
  onApplied?: () => void;
}

/** The tab a file belongs on, from its extension; X31 when unsure. */
export function tabForFile(name: string): GaebSiteTab {
  return /\.x89$/i.test(name) ? 'x89_check' : 'x31_import';
}

function unmatchedReason(t: TFunction, reason: string): string {
  switch (reason) {
    case 'unknown_oz':
      return t('boq.gaeb_site.reason_unknown_oz', { defaultValue: 'No position in this bill has this OZ' });
    case 'ambiguous_oz':
      return t('boq.gaeb_site.reason_ambiguous_oz', { defaultValue: 'Several positions answer to this OZ' });
    case 'duplicate_oz_in_file':
      return t('boq.gaeb_site.reason_duplicate_oz', { defaultValue: 'The file names this OZ more than once' });
    case 'rows_without_total':
      return t('boq.gaeb_site.reason_rows_without_total', {
        defaultValue: 'Measurement rows without a total quantity',
      });
    case 'no_quantity':
      return t('boq.gaeb_site.reason_no_quantity', { defaultValue: 'No quantity given' });
    case 'position_already_matched':
      return t('boq.gaeb_site.reason_already_matched', {
        defaultValue: 'The position already takes the quantity of another OZ',
      });
    default:
      return reason;
  }
}

function invoiceIssue(t: TFunction, issue: string): string {
  switch (issue) {
    case 'unknown_oz':
      return t('boq.gaeb_site.issue_unknown_oz', { defaultValue: 'OZ not in bill' });
    case 'ambiguous_oz':
      return t('boq.gaeb_site.issue_ambiguous_oz', { defaultValue: 'OZ ambiguous' });
    case 'unit_price_differs':
      return t('boq.gaeb_site.issue_unit_price_differs', { defaultValue: 'Unit price differs from bill' });
    case 'quantity_above_boq':
      return t('boq.gaeb_site.issue_quantity_above_boq', { defaultValue: 'Quantity above bill quantity' });
    case 'amount_not_qty_times_price':
      return t('boq.gaeb_site.issue_amount_arithmetic', { defaultValue: 'Amount is not quantity x price' });
    case 'missing_amount':
      return t('boq.gaeb_site.issue_missing_amount', { defaultValue: 'No amount' });
    default:
      return issue;
  }
}

function totalsLabel(t: TFunction, key: string): string {
  switch (key) {
    case 'items_total':
      return t('boq.gaeb_site.totals_items', { defaultValue: 'Sum of items' });
    case 'vat_amount':
      return t('boq.gaeb_site.totals_vat', { defaultValue: 'VAT amount' });
    case 'total_gross':
      return t('boq.gaeb_site.totals_gross', { defaultValue: 'Gross total' });
    case 'invoice_total_gross':
      return t('boq.gaeb_site.totals_invoice_gross', { defaultValue: 'Invoice gross total' });
    default:
      return key;
  }
}

function num(value: string | null | undefined, decimals: number): string {
  return value === null || value === undefined || value === '' ? '-' : fmtNumber(value, decimals);
}

export function GaebSiteExchangeDialog({
  open,
  boqId,
  boqName,
  initialFile,
  readOnly = false,
  onClose,
  onApplied,
}: GaebSiteExchangeDialogProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [tab, setTab] = useState<GaebSiteTab>('x31_import');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [preview, setPreview] = useState<X31Preview | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [setBoqQuantity, setSetBoqQuantity] = useState(false);
  const [applyErrors, setApplyErrors] = useState<{ position_id: string; error: string }[]>([]);

  const [basis, setBasis] = useState<'measured' | 'quantity'>('measured');
  const [report, setReport] = useState<X89CheckReport | null>(null);

  const x31Input = useRef<HTMLInputElement | null>(null);
  const x89Input = useRef<HTMLInputElement | null>(null);

  const readX31 = useCallback(
    async (file: File) => {
      setBusy(true);
      setError(null);
      setApplyErrors([]);
      try {
        const result = await previewX31(boqId, file);
        setPreview(result);
        setSelected(new Set(result.matched.filter((m) => !m.unchanged).map((m) => m.position_id)));
      } catch (err) {
        setPreview(null);
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [boqId],
  );

  const readX89 = useCallback(
    async (file: File) => {
      setBusy(true);
      setError(null);
      try {
        setReport(await checkX89(boqId, file));
      } catch (err) {
        setReport(null);
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    },
    [boqId],
  );

  // A file handed over by the editor's import button opens on its own tab.
  useEffect(() => {
    if (!open || !initialFile) return;
    const target = tabForFile(initialFile.name);
    setTab(target);
    if (target === 'x89_check') void readX89(initialFile);
    else void readX31(initialFile);
  }, [open, initialFile, readX31, readX89]);

  const toApply = useMemo(
    () => (preview ? preview.matched.filter((m) => selected.has(m.position_id)) : []),
    [preview, selected],
  );

  const handleApply = useCallback(async () => {
    if (!preview || toApply.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      const result = await applyX31(boqId, {
        file_name: preview.file_name,
        set_boq_quantity: setBoqQuantity,
        items: toApply.map((m) => ({
          position_id: m.position_id,
          quantity: m.proposed_quantity,
          oz: m.oz,
          rows: m.rows,
        })),
      });
      setApplyErrors(result.errors);
      addToast({
        type: result.errors.length > 0 ? 'warning' : 'success',
        title: t('boq.gaeb_site.applied_toast', {
          defaultValue: '{{applied}} measured quantities applied, {{unchanged}} already up to date',
          applied: result.applied.length,
          unchanged: result.unchanged.length,
        }),
      });
      if (result.applied.length > 0) onApplied?.();
      if (result.errors.length === 0) {
        const done = new Set([...result.applied, ...result.unchanged]);
        setSelected((prev) => new Set([...prev].filter((id) => !done.has(id))));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [preview, toApply, boqId, setBoqQuantity, addToast, t, onApplied]);

  const handleExport = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const { written, skipped } = await downloadX31(boqId, basis, boqName || 'boq');
      addToast({
        type: skipped > 0 ? 'warning' : 'success',
        title: t('boq.gaeb_site.export_toast', {
          defaultValue: 'X31 written with {{written}} positions, {{skipped}} left out',
          written,
          skipped,
        }),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }, [boqId, basis, boqName, addToast, t]);

  if (!open) return null;

  const tabs: { id: GaebSiteTab; label: string }[] = [
    { id: 'x31_import', label: t('boq.gaeb_site.tab_x31_import', { defaultValue: 'Read X31 measurement' }) },
    { id: 'x31_export', label: t('boq.gaeb_site.tab_x31_export', { defaultValue: 'Write X31' }) },
    { id: 'x89_check', label: t('boq.gaeb_site.tab_x89_check', { defaultValue: 'Check X89 invoice' }) },
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="boq-gaeb-site-title"
        className="bg-surface-elevated rounded-xl border border-border-light shadow-lg w-full max-w-4xl max-h-[90vh] flex flex-col animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 pt-5 pb-3">
          <h3 id="boq-gaeb-site-title" className="flex items-center gap-2 text-sm font-semibold text-content-primary">
            <Ruler size={16} />
            {t('boq.gaeb_site.title', { defaultValue: 'GAEB X31 / X89' })}
          </h3>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-content-tertiary hover:bg-surface-secondary transition-colors"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={16} />
          </button>
        </div>

        <div role="tablist" className="flex gap-1 px-5 border-b border-border-light">
          {tabs.map((item) => (
            <button
              key={item.id}
              role="tab"
              aria-selected={tab === item.id}
              onClick={() => {
                setTab(item.id);
                setError(null);
              }}
              className={`px-3 py-2 text-xs font-medium border-b-2 -mb-px transition-colors ${
                tab === item.id
                  ? 'border-oe-blue text-oe-blue'
                  : 'border-transparent text-content-secondary hover:text-content-primary'
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {error && (
            <div className="flex items-start gap-2 rounded-lg bg-semantic-error-bg p-3 text-xs text-semantic-error">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}
          {busy && (
            <div className="flex items-center gap-2 text-xs text-content-secondary">
              <Loader2 size={14} className="animate-spin" />
              {t('boq.gaeb_site.working', { defaultValue: 'Working...' })}
            </div>
          )}

          {tab === 'x31_import' && (
            <section className="space-y-3">
              <p className="text-xs text-content-secondary leading-relaxed">
                {t('boq.gaeb_site.x31_import_intro', {
                  defaultValue:
                    'Reads the measured quantity of each OZ and proposes it for the matching position. Nothing changes until you apply the rows you tick.',
                })}
              </p>
              <input
                ref={x31Input}
                type="file"
                accept=".x31,.xml"
                className="hidden"
                aria-label={t('boq.gaeb_site.choose_x31', { defaultValue: 'Choose X31 file' })}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void readX31(file);
                  e.target.value = '';
                }}
              />
              <Button
                variant="secondary"
                size="sm"
                icon={<FileUp size={14} />}
                onClick={() => x31Input.current?.click()}
                disabled={busy}
              >
                {t('boq.gaeb_site.choose_x31', { defaultValue: 'Choose X31 file' })}
              </Button>

              {preview && (
                <>
                  <div className="flex flex-wrap gap-2 text-xs">
                    <Badge variant="neutral">
                      {t('boq.gaeb_site.items_in_file', {
                        defaultValue: '{{count}} OZ in file',
                        count: preview.items_in_file,
                      })}
                    </Badge>
                    <Badge variant="success">
                      {t('boq.gaeb_site.matched_count', {
                        defaultValue: '{{count}} matched',
                        count: preview.matched.length,
                      })}
                    </Badge>
                    <Badge variant={preview.unmatched.length > 0 ? 'warning' : 'neutral'}>
                      {t('boq.gaeb_site.unmatched_count', {
                        defaultValue: '{{count}} not matched',
                        count: preview.unmatched.length,
                      })}
                    </Badge>
                    <Badge variant="neutral">
                      {t('boq.gaeb_site.not_in_file_count', {
                        defaultValue: '{{count}} position not in file',
                        defaultValue_other: '{{count}} positions not in file',
                        count: preview.positions_not_in_file,
                      })}
                    </Badge>
                  </div>

                  {preview.matched.length > 0 && (
                    <div className="border border-border-light rounded-lg overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="bg-surface-secondary/50">
                            <th className="px-2 py-1.5 w-8">
                              <input
                                type="checkbox"
                                aria-label={t('boq.gaeb_site.select_all', { defaultValue: 'Select all' })}
                                checked={selected.size === preview.matched.length}
                                onChange={(e) =>
                                  setSelected(
                                    e.target.checked
                                      ? new Set(preview.matched.map((m) => m.position_id))
                                      : new Set(),
                                  )
                                }
                              />
                            </th>
                            <th className="px-2 py-1.5 text-left font-medium text-content-secondary">
                              {t('boq.gaeb_site.col_oz', { defaultValue: 'OZ' })}
                            </th>
                            <th className="px-2 py-1.5 text-left font-medium text-content-secondary">
                              {t('boq.description', { defaultValue: 'Description' })}
                            </th>
                            <th className="px-2 py-1.5 text-center font-medium text-content-secondary">
                              {t('boq.unit', { defaultValue: 'Unit' })}
                            </th>
                            <th className="px-2 py-1.5 text-right font-medium text-content-secondary">
                              {t('boq.gaeb_site.col_bill_qty', { defaultValue: 'Bill qty' })}
                            </th>
                            <th className="px-2 py-1.5 text-right font-medium text-content-secondary">
                              {t('boq.gaeb_site.col_measured_now', { defaultValue: 'Measured now' })}
                            </th>
                            <th className="px-2 py-1.5 text-right font-medium text-content-secondary">
                              {t('boq.gaeb_site.col_from_file', { defaultValue: 'From file' })}
                            </th>
                            <th className="px-2 py-1.5 text-right font-medium text-content-secondary">
                              {t('boq.gaeb_site.col_difference', { defaultValue: 'Difference' })}
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {preview.matched.map((m) => (
                            <tr key={m.position_id} className="border-t border-border-light">
                              <td className="px-2 py-1.5 text-center">
                                <input
                                  type="checkbox"
                                  aria-label={m.oz}
                                  checked={selected.has(m.position_id)}
                                  onChange={(e) =>
                                    setSelected((prev) => {
                                      const next = new Set(prev);
                                      if (e.target.checked) next.add(m.position_id);
                                      else next.delete(m.position_id);
                                      return next;
                                    })
                                  }
                                />
                              </td>
                              <td className="px-2 py-1.5 font-mono">{m.oz}</td>
                              <td className="px-2 py-1.5 truncate max-w-[16rem]" title={m.description}>
                                {m.description}
                              </td>
                              <td className="px-2 py-1.5 text-center">{m.unit}</td>
                              <td className="px-2 py-1.5 text-right tabular-nums">{num(m.current_quantity, 3)}</td>
                              <td className="px-2 py-1.5 text-right tabular-nums">
                                {num(m.current_measured_quantity, 3)}
                              </td>
                              <td className="px-2 py-1.5 text-right tabular-nums font-medium">
                                {num(m.proposed_quantity, 3)}
                                {m.unchanged && (
                                  <CheckCircle2
                                    size={12}
                                    className="inline ml-1 text-semantic-success"
                                    aria-label={t('boq.gaeb_site.unchanged', { defaultValue: 'Already measured so' })}
                                  />
                                )}
                              </td>
                              <td className="px-2 py-1.5 text-right tabular-nums">
                                {num(m.difference_to_quantity, 3)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  {preview.unmatched.length > 0 && (
                    <div className="rounded-lg border border-semantic-warning/40 p-3 space-y-1">
                      <div className="text-xs font-medium text-content-primary">
                        {t('boq.gaeb_site.unmatched_title', { defaultValue: 'Not matched, nothing will be written' })}
                      </div>
                      <ul className="text-xs text-content-secondary space-y-0.5">
                        {preview.unmatched.map((u, i) => (
                          <li key={`${u.oz}-${i}`}>
                            <span className="font-mono">{u.oz || '-'}</span>
                            {u.quantity !== null && <span className="tabular-nums"> ({num(u.quantity, 3)})</span>}
                            {': '}
                            {unmatchedReason(t, u.reason)}
                            {u.candidates && u.candidates.length > 0 && ` (${u.candidates.join(', ')})`}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {applyErrors.length > 0 && (
                    <div className="rounded-lg bg-semantic-error-bg p-3 text-xs text-semantic-error space-y-0.5">
                      {applyErrors.map((e) => (
                        <div key={e.position_id}>
                          {preview.matched.find((m) => m.position_id === e.position_id)?.oz ?? e.position_id}:{' '}
                          {e.error}
                        </div>
                      ))}
                    </div>
                  )}

                  <label className="flex items-center gap-2 text-xs text-content-secondary">
                    <input
                      type="checkbox"
                      checked={setBoqQuantity}
                      onChange={(e) => setSetBoqQuantity(e.target.checked)}
                    />
                    {t('boq.gaeb_site.set_boq_quantity', {
                      defaultValue: 'Also make the measured quantity the bill quantity (re-prices the positions)',
                    })}
                  </label>
                  {readOnly && (
                    <p className="text-xs text-semantic-warning">
                      {t('boq.gaeb_site.locked_hint', {
                        defaultValue: 'This bill is locked. Create a revision to apply measured quantities.',
                      })}
                    </p>
                  )}
                </>
              )}
            </section>
          )}

          {tab === 'x31_export' && (
            <section className="space-y-3">
              <p className="text-xs text-content-secondary leading-relaxed">
                {t('boq.gaeb_site.x31_export_intro', {
                  defaultValue:
                    'Writes a GAEB DA XML 3.3 X31 with one quantity per OZ, for the client or the site team to check.',
                })}
              </p>
              <fieldset className="space-y-1.5 text-xs">
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="x31-basis"
                    checked={basis === 'measured'}
                    onChange={() => setBasis('measured')}
                  />
                  {t('boq.gaeb_site.basis_measured', {
                    defaultValue: 'Measured quantities (positions with a measurement sheet)',
                  })}
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="x31-basis"
                    checked={basis === 'quantity'}
                    onChange={() => setBasis('quantity')}
                  />
                  {t('boq.gaeb_site.basis_quantity', { defaultValue: 'Bill quantities of every position' })}
                </label>
              </fieldset>
              <Button
                variant="primary"
                size="sm"
                icon={<Download size={14} />}
                onClick={() => void handleExport()}
                disabled={busy}
              >
                {t('boq.gaeb_site.download_x31', { defaultValue: 'Download X31' })}
              </Button>
            </section>
          )}

          {tab === 'x89_check' && (
            <section className="space-y-3">
              <p className="text-xs text-content-secondary leading-relaxed">
                {t('boq.gaeb_site.x89_check_intro', {
                  defaultValue:
                    'Holds a received invoice against this bill and lists the differences per OZ. Nothing in the bill changes.',
                })}
              </p>
              <input
                ref={x89Input}
                type="file"
                accept=".x89,.xml"
                className="hidden"
                aria-label={t('boq.gaeb_site.choose_x89', { defaultValue: 'Choose X89 file' })}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void readX89(file);
                  e.target.value = '';
                }}
              />
              <Button
                variant="secondary"
                size="sm"
                icon={<FileUp size={14} />}
                onClick={() => x89Input.current?.click()}
                disabled={busy}
              >
                {t('boq.gaeb_site.choose_x89', { defaultValue: 'Choose X89 file' })}
              </Button>

              {report && (
                <>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs">
                    <div className="rounded-lg bg-surface-secondary p-2">
                      <div className="text-content-tertiary">
                        {t('boq.gaeb_site.invoiced', { defaultValue: 'Invoiced (net)' })}
                      </div>
                      <div className="font-semibold tabular-nums">
                        {num(report.invoiced_total, 2)} {report.currency}
                      </div>
                    </div>
                    <div className="rounded-lg bg-surface-secondary p-2">
                      <div className="text-content-tertiary">
                        {t('boq.gaeb_site.expected', { defaultValue: 'At bill rates' })}
                      </div>
                      <div className="font-semibold tabular-nums">
                        {num(report.expected_total, 2)} {report.currency}
                      </div>
                    </div>
                    <div className="rounded-lg bg-surface-secondary p-2">
                      <div className="text-content-tertiary">
                        {t('boq.gaeb_site.difference', { defaultValue: 'Difference' })}
                      </div>
                      <div className="font-semibold tabular-nums">
                        {num(report.total_difference, 2)} {report.currency}
                      </div>
                    </div>
                  </div>
                  {report.header.InvoiceNo && (
                    <p className="text-xs text-content-secondary">
                      {t('boq.gaeb_site.invoice_header', {
                        defaultValue: 'Invoice {{no}} of {{date}}',
                        no: report.header.InvoiceNo,
                        date: report.header.InvoiceDate ?? '-',
                      })}
                    </p>
                  )}
                  {report.totals_check.length > 0 && (
                    <ul className="text-xs space-y-0.5">
                      {report.totals_check.map((row) => (
                        <li key={row.key} className="flex items-center gap-2">
                          {row.matches ? (
                            <CheckCircle2 size={12} className="text-semantic-success" />
                          ) : (
                            <AlertTriangle size={12} className="text-semantic-warning" />
                          )}
                          <span>{totalsLabel(t, row.key)}:</span>
                          <span className="tabular-nums">
                            {num(row.stated, 2)} / {num(row.computed, 2)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className="border border-border-light rounded-lg overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-surface-secondary/50">
                          <th className="px-2 py-1.5 text-left font-medium text-content-secondary">
                            {t('boq.gaeb_site.col_oz', { defaultValue: 'OZ' })}
                          </th>
                          <th className="px-2 py-1.5 text-left font-medium text-content-secondary">
                            {t('boq.description', { defaultValue: 'Description' })}
                          </th>
                          <th className="px-2 py-1.5 text-right font-medium text-content-secondary">
                            {t('boq.quantity', { defaultValue: 'Qty' })}
                          </th>
                          <th className="px-2 py-1.5 text-right font-medium text-content-secondary">
                            {t('boq.unit_rate', { defaultValue: 'Rate' })}
                          </th>
                          <th className="px-2 py-1.5 text-right font-medium text-content-secondary">
                            {t('boq.gaeb_site.col_amount', { defaultValue: 'Amount' })}
                          </th>
                          <th className="px-2 py-1.5 text-right font-medium text-content-secondary">
                            {t('boq.gaeb_site.expected', { defaultValue: 'At bill rates' })}
                          </th>
                          <th className="px-2 py-1.5 text-right font-medium text-content-secondary">
                            {t('boq.gaeb_site.col_difference', { defaultValue: 'Difference' })}
                          </th>
                          <th className="px-2 py-1.5 text-left font-medium text-content-secondary">
                            {t('boq.gaeb_site.col_issues', { defaultValue: 'Findings' })}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {report.lines.map((line, i) => (
                          <tr key={`${line.oz}-${i}`} className="border-t border-border-light">
                            <td className="px-2 py-1.5 font-mono">{line.oz}</td>
                            <td className="px-2 py-1.5 truncate max-w-[14rem]" title={line.description}>
                              {line.description}
                            </td>
                            <td className="px-2 py-1.5 text-right tabular-nums">
                              {num(line.bill_qty, 3)} {line.unit}
                            </td>
                            <td className="px-2 py-1.5 text-right tabular-nums">{num(line.unit_price, 2)}</td>
                            <td className="px-2 py-1.5 text-right tabular-nums">{num(line.amount, 2)}</td>
                            <td className="px-2 py-1.5 text-right tabular-nums">{num(line.expected_amount, 2)}</td>
                            <td className="px-2 py-1.5 text-right tabular-nums">{num(line.difference, 2)}</td>
                            <td className="px-2 py-1.5">
                              <div className="flex flex-wrap gap-1">
                                {line.issues.map((issue) => (
                                  <Badge key={issue} variant="warning" size="sm">
                                    {invoiceIssue(t, issue)}
                                  </Badge>
                                ))}
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
            </section>
          )}
        </div>

        <div className="flex justify-end gap-2 px-5 py-3 border-t border-border-light">
          <Button variant="ghost" size="sm" onClick={onClose}>
            {t('common.close', { defaultValue: 'Close' })}
          </Button>
          {tab === 'x31_import' && preview && (
            <Button
              variant="primary"
              size="sm"
              onClick={() => void handleApply()}
              disabled={busy || readOnly || toApply.length === 0}
            >
              {t('boq.gaeb_site.apply', {
                defaultValue: 'Apply {{count}} measured quantity',
                defaultValue_other: 'Apply {{count}} measured quantities',
                count: toApply.length,
              })}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

export default GaebSiteExchangeDialog;
