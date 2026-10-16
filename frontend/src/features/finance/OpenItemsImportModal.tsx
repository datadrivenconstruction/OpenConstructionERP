// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, Download, FileSpreadsheet } from 'lucide-react';
import clsx from 'clsx';
import { Badge, Button, WideModal } from '@/shared/ui';
import type { BadgeVariant } from '@/shared/ui';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { useToastStore } from '@/stores/useToastStore';
import { invalidateFinanceFigures } from './financeQueryKeys';
import {
  downloadOpenItemsTemplate,
  importOpenItems,
  type OpenItemRow,
  type OpenItemRowStatus,
  type OpenItemsImportResult,
} from './api';

const inputCls =
  'h-10 rounded-lg border border-border bg-surface-primary px-3 text-sm text-content-primary focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

const STATUS_VARIANT: Record<OpenItemRowStatus, BadgeVariant> = {
  ready: 'blue',
  imported: 'success',
  exists: 'neutral',
  error: 'error',
};

function statusLabel(t: TFunction, status: OpenItemRowStatus): string {
  if (status === 'ready') return t('finance.openitems_status_ready', { defaultValue: 'Ready' });
  if (status === 'imported') return t('finance.openitems_status_imported', { defaultValue: 'Imported' });
  if (status === 'exists') return t('finance.openitems_status_exists', { defaultValue: 'Already carried over' });
  return t('finance.openitems_status_error', { defaultValue: 'Error' });
}

function directionLabel(t: TFunction, direction: string | null): string {
  if (direction === 'receivable') return t('finance.receivable', { defaultValue: 'Receivable' });
  if (direction === 'payable') return t('finance.payable', { defaultValue: 'Payable' });
  return '';
}

/** English wording per problem code; the server's ``message`` is the last resort. */
const ERROR_TEXT: Record<string, string> = {
  direction_unknown: "Direction '{{value}}' is neither receivable (AR) nor payable (AP).",
  number_missing: 'The invoice number is missing.',
  number_too_long: 'The invoice number is longer than 50 characters.',
  counterparty_missing: 'The counterparty is missing: give its name or its tax number.',
  invoice_date_invalid: "Invoice date '{{value}}' is not a date (use YYYY-MM-DD).",
  after_cutover: 'The invoice is dated {{date}}, after the cut-over date {{cutover}}.',
  due_date_invalid: "Due date '{{value}}' is not a date (use YYYY-MM-DD).",
  due_before_invoice: 'The due date is before the invoice date.',
  currency_invalid: "Currency '{{value}}' is not a three-letter ISO code.",
  amount_invalid: "{{column}} '{{value}}' is not an amount that reads one way only (write it as 1234.56).",
  amount_negative: '{{column}} is negative; a credit note is not an open item here.',
  total_missing: 'The total is missing or zero.',
  tax_too_large: 'The tax is larger than the total.',
  retention_too_large: 'The retention held is larger than the total.',
  open_too_large:
    'Open {{open}} plus retention {{retention}} is more than the total {{total}}; the open amount is what is still due in cash, without the retention.',
  nothing_open: 'Nothing is open on this invoice, so it is not carried over.',
  duplicate_in_file: 'Invoice number {{number}} already appears in row {{first_row}}.',
  contact_tax_ambiguous: 'Several contacts carry the tax number {{tax_id}}; keep one of them.',
  contact_tax_unknown: 'No contact carries the tax number {{tax_id}}. Add the contact first.',
  contact_name_ambiguous: 'Several contacts are named {{name}}; add the tax number to the row.',
  contact_name_unknown: 'No contact named {{name}}. Add or import the contacts first.',
  currency_missing: 'No currency: the row names none and the project has no currency set.',
  number_used: 'Invoice number {{number}} is already used on this project.',
};

function columnLabel(t: TFunction, column: string | undefined): string {
  if (column === 'total') return t('finance.openitems_col_total', { defaultValue: 'Total' });
  if (column === 'tax') return t('finance.openitems_col_tax', { defaultValue: 'Tax' });
  if (column === 'retention_held') return t('finance.openitems_col_retention', { defaultValue: 'Retention held' });
  if (column === 'open') return t('finance.openitems_col_open', { defaultValue: 'Open' });
  return column ?? '';
}

/** Why a row cannot be imported, in the reader's language when its code is known. */
function rowMessage(t: TFunction, row: OpenItemRow): string {
  const english = row.code ? ERROR_TEXT[row.code] : undefined;
  if (!row.code || !english) return row.message ?? '';
  return t(`finance.openitems_err_${row.code}`, {
    defaultValue: english,
    ...row.params,
    column: columnLabel(t, row.params?.column),
    interpolation: { escapeValue: false },
  });
}

function today(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Errors first, so a long file shows what blocks the import without scrolling. */
function ordered(rows: OpenItemRow[]): OpenItemRow[] {
  return [...rows].sort((a, b) => Number(b.status === 'error') - Number(a.status === 'error') || a.row - b.row);
}

/**
 * Carry the invoices still open in another system over to the project.
 *
 * The file is checked first: every row is matched to a contact and the control
 * totals per direction and currency are shown, to tick against the old
 * system's open item list. Only a file without errors can be imported, and
 * the import writes all its rows or none.
 */
export function OpenItemsImportModal({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [file, setFile] = useState<File | null>(null);
  const [cutover, setCutover] = useState(today);
  const [result, setResult] = useState<OpenItemsImportResult | null>(null);

  const run = useMutation({
    mutationFn: (dryRun: boolean) => importOpenItems(projectId, file as File, cutover, dryRun),
    onSuccess: async (data) => {
      setResult(data);
      if (!data.dry_run && data.imported > 0) {
        await invalidateFinanceFigures(queryClient);
        addToast({
          type: 'success',
          title: t('finance.openitems_done', {
            defaultValue: 'Open items carried over: {{n}}',
            n: data.imported,
          }),
        });
      }
    },
    onError: (err) =>
      addToast({
        type: 'error',
        title: t('finance.openitems_failed', { defaultValue: 'The file could not be checked' }),
        message: err instanceof Error ? err.message : undefined,
      }),
  });

  const reset = (next: File | null) => {
    setFile(next);
    setResult(null);
  };

  const canImport = !!result && result.dry_run && result.errors === 0 && result.ready > 0;
  const done = !!result && !result.dry_run && result.errors === 0;

  return (
    <WideModal
      open
      onClose={onClose}
      size="xl"
      testId="open-items-import"
      title={t('finance.openitems_title', { defaultValue: 'Import open items' })}
      subtitle={t('finance.openitems_subtitle', {
        defaultValue:
          'Invoices still open in your previous system on the day you switch over. Each becomes an invoice here, and what was already paid on it is recorded as one payment on the cut-over day.',
      })}
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {done
              ? t('common.close', { defaultValue: 'Close' })
              : t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          {!done && (
            <Button
              variant="secondary"
              onClick={() => run.mutate(true)}
              loading={run.isPending && run.variables === true}
              disabled={!file || !cutover || run.isPending}
            >
              {t('finance.openitems_check', { defaultValue: 'Check file' })}
            </Button>
          )}
          {!done && (
            <Button
              variant="primary"
              onClick={() => run.mutate(false)}
              loading={run.isPending && run.variables === false}
              disabled={!canImport || run.isPending}
            >
              {t('finance.openitems_import', {
                defaultValue: 'Import ({{n}})',
                n: result?.ready ?? 0,
              })}
            </Button>
          )}
        </div>
      }
    >
      <div className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('finance.openitems_cutover', { defaultValue: 'Cut-over date' })}
            </span>
            <input
              type="date"
              value={cutover}
              max={today()}
              onChange={(e) => {
                setCutover(e.target.value);
                setResult(null);
              }}
              className={inputCls}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-2xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('finance.openitems_file', { defaultValue: 'File (CSV or Excel)' })}
            </span>
            <input
              type="file"
              accept=".csv,.xlsx"
              aria-label={t('finance.openitems_file', { defaultValue: 'File (CSV or Excel)' })}
              onChange={(e) => reset(e.target.files?.[0] ?? null)}
              className="text-sm text-content-secondary file:me-3 file:rounded-lg file:border-0 file:bg-surface-secondary file:px-3 file:py-2 file:text-sm file:text-content-primary"
            />
          </label>
          <Button
            variant="ghost"
            size="sm"
            icon={<Download size={14} />}
            onClick={() =>
              downloadOpenItemsTemplate().catch((err: unknown) =>
                addToast({
                  type: 'error',
                  title: t('finance.openitems_template_failed', { defaultValue: 'The template could not be downloaded' }),
                  message: err instanceof Error ? err.message : undefined,
                }),
              )
            }
          >
            {t('finance.openitems_template', { defaultValue: 'Download template' })}
          </Button>
        </div>

        <p className="text-xs text-content-tertiary">
          {t('finance.openitems_columns_hint', {
            defaultValue:
              'Columns: direction (AR or AP), invoice number, counterparty, tax number, invoice date, due date, currency, total, tax, retention held, open. The counterparty has to exist as a contact; it is found by tax number, else by name. Open is what is still due in cash, without the retention; left empty it is the total less the retention.',
          })}
        </p>

        {result && result.missing_columns.length > 0 && (
          <div className="flex items-start gap-2 rounded-lg border border-semantic-error/30 bg-semantic-error-bg p-3 text-sm text-content-primary">
            <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-error" />
            <span>
              {t('finance.openitems_missing_columns', {
                defaultValue: 'The file does not name these columns: {{cols}}',
                cols: result.missing_columns.join(', '),
              })}
            </span>
          </div>
        )}

        {result && result.missing_columns.length === 0 && (
          <>
            <div
              className={clsx(
                'flex items-start gap-2 rounded-lg border p-3 text-sm text-content-primary',
                result.errors > 0
                  ? 'border-semantic-error/30 bg-semantic-error-bg'
                  : 'border-semantic-success/30 bg-semantic-success-bg',
              )}
              data-testid="open-items-summary"
            >
              {result.errors > 0 ? (
                <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-error" />
              ) : (
                <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-semantic-success" />
              )}
              <span>
                {result.errors > 0
                  ? t('finance.openitems_has_errors', {
                      defaultValue:
                        'Rows with errors: {{n}}. Nothing is imported until the file is corrected and checked again.',
                      n: result.errors,
                    })
                  : result.dry_run
                    ? t('finance.openitems_all_ready', {
                        defaultValue:
                          'Ready to import: {{ready}}. Carried over before: {{exists}}. Compare the totals with your previous system before importing.',
                        ready: result.ready,
                        exists: result.exists,
                      })
                    : t('finance.openitems_imported', {
                        defaultValue: 'Imported: {{n}}. They now show in ageing and statements of account.',
                        n: result.imported,
                      })}
              </span>
            </div>

            {result.control_totals.length > 0 && (
              <div className="overflow-x-auto rounded-lg border border-border">
                <table className="w-full text-sm" data-testid="open-items-totals">
                  <thead>
                    <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-content-secondary">
                      <th className="px-3 py-2 font-medium">
                        {t('finance.openitems_col_direction', { defaultValue: 'Direction' })}
                      </th>
                      <th className="px-3 py-2 text-right font-medium">
                        {t('finance.openitems_col_count', { defaultValue: 'Items' })}
                      </th>
                      <th className="px-3 py-2 text-right font-medium">
                        {t('finance.openitems_col_total', { defaultValue: 'Total' })}
                      </th>
                      <th className="px-3 py-2 text-right font-medium">
                        {t('finance.openitems_col_retention', { defaultValue: 'Retention held' })}
                      </th>
                      <th className="px-3 py-2 text-right font-medium">
                        {t('finance.openitems_col_open', { defaultValue: 'Open' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.control_totals.map((row) => (
                      <tr key={`${row.direction}-${row.currency_code}`} className="border-b border-border/60">
                        <td className="px-3 py-2">
                          {directionLabel(t, row.direction)} · {row.currency_code}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">{row.count}</td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          <MoneyDisplay amount={row.total} currency={row.currency_code} />
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">
                          <MoneyDisplay amount={row.retention_held} currency={row.currency_code} />
                        </td>
                        <td className="px-3 py-2 text-right font-semibold tabular-nums">
                          <MoneyDisplay amount={row.open} currency={row.currency_code} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="max-h-[45vh] overflow-auto rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-surface-primary">
                  <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-content-secondary">
                    <th className="px-3 py-2 font-medium">{t('finance.openitems_col_row', { defaultValue: 'Row' })}</th>
                    <th className="px-3 py-2 font-medium">
                      {t('finance.openitems_col_invoice', { defaultValue: 'Invoice' })}
                    </th>
                    <th className="px-3 py-2 font-medium">
                      {t('finance.openitems_col_contact', { defaultValue: 'Contact' })}
                    </th>
                    <th className="px-3 py-2 text-right font-medium">
                      {t('finance.openitems_col_open', { defaultValue: 'Open' })}
                    </th>
                    <th className="px-3 py-2 font-medium">
                      {t('finance.openitems_col_status', { defaultValue: 'Status' })}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {ordered(result.rows).map((row) => (
                    <tr key={row.row} className="border-b border-border/60 align-top">
                      <td className="px-3 py-2 tabular-nums text-content-tertiary">{row.row}</td>
                      <td className="px-3 py-2">
                        <span className="text-content-primary">{row.invoice_number || '-'}</span>
                        {row.direction && (
                          <span className="block text-2xs text-content-tertiary">
                            {directionLabel(t, row.direction)}
                          </span>
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <span className="text-content-primary">{row.contact_name || row.counterparty || '-'}</span>
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {row.open != null && row.currency_code ? (
                          <MoneyDisplay amount={row.open} currency={row.currency_code} />
                        ) : (
                          '-'
                        )}
                      </td>
                      <td className="px-3 py-2">
                        <Badge variant={STATUS_VARIANT[row.status]} size="sm">
                          {statusLabel(t, row.status)}
                        </Badge>
                        {row.status === 'error' && (row.code || row.message) && (
                          <span className="mt-1 block text-xs text-semantic-error">{rowMessage(t, row)}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {!result && (
          <div className="flex items-center gap-2 rounded-lg border border-dashed border-border p-4 text-sm text-content-tertiary">
            <FileSpreadsheet size={18} className="shrink-0" />
            <span>
              {t('finance.openitems_empty', {
                defaultValue: 'Choose the cut-over date and a file, then check it. Nothing is written by the check.',
              })}
            </span>
          </div>
        )}
      </div>
    </WideModal>
  );
}
