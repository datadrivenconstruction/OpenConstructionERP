// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useId } from 'react';
import { useTranslation } from 'react-i18next';
import { Plus, X } from 'lucide-react';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import {
  editLine,
  invoiceTotals,
  lineNet,
  newEditorLine,
  type InvoiceEditorLine,
} from './invoiceLines';

const cellInput =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-2 text-sm tabular-nums focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/**
 * The lines of an invoice with a VAT rate each, and the Net / VAT / Gross
 * they add up to.
 *
 * The VAT field offers the project country's rates and stays free to type:
 * a supplier may bill a rate the list does not carry, and 0 is a real rate
 * (exempt or reverse-charged work), distinct from an empty field, which asks
 * the server for the country default.
 */
export function InvoiceLinesEditor({
  lines,
  onChange,
  currency,
  vatOptions,
  defaultVat,
  error,
}: {
  lines: InvoiceEditorLine[];
  onChange: (lines: InvoiceEditorLine[]) => void;
  currency?: string;
  vatOptions: string[];
  defaultVat: string | null;
  error?: string;
}) {
  const { t } = useTranslation();
  const listId = useId();
  const totals = invoiceTotals(lines);

  const update = (key: string, field: Parameters<typeof editLine>[1], value: string) =>
    onChange(lines.map((line) => (line.key === key ? editLine(line, field, value) : line)));

  const labels = {
    description: t('finance.line_description', { defaultValue: 'Description' }),
    quantity: t('finance.line_quantity', { defaultValue: 'Quantity' }),
    unit: t('finance.line_unit', { defaultValue: 'Unit' }),
    rate: t('finance.line_unit_rate', { defaultValue: 'Unit rate' }),
    vat: t('finance.line_vat_rate', { defaultValue: 'VAT %' }),
    net: t('finance.line_net', { defaultValue: 'Net' }),
  };

  return (
    <div className="space-y-3" data-testid="invoice-lines-editor">
      <datalist id={listId}>
        {vatOptions.map((rate) => (
          <option key={rate} value={rate} />
        ))}
      </datalist>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr className="text-left text-2xs uppercase tracking-wider text-content-tertiary">
              <th className="pb-1 pr-2 font-medium">{labels.description}</th>
              <th className="w-20 pb-1 pr-2 font-medium">{labels.quantity}</th>
              <th className="w-20 pb-1 pr-2 font-medium">{labels.unit}</th>
              <th className="w-28 pb-1 pr-2 font-medium">{labels.rate}</th>
              <th className="w-20 pb-1 pr-2 font-medium">{labels.vat}</th>
              <th className="w-28 pb-1 pr-2 text-right font-medium">{labels.net}</th>
              <th className="w-8 pb-1" />
            </tr>
          </thead>
          <tbody>
            {lines.map((line, index) => (
              <tr key={line.key} className="align-top" data-testid="invoice-line">
                <td className="py-1 pr-2">
                  <input
                    className={cellInput}
                    value={line.description}
                    aria-label={labels.description}
                    onChange={(e) => update(line.key, 'description', e.target.value)}
                  />
                </td>
                <td className="py-1 pr-2">
                  <input
                    type="number"
                    step="any"
                    min="0"
                    className={cellInput}
                    value={line.quantity}
                    aria-label={labels.quantity}
                    onChange={(e) => update(line.key, 'quantity', e.target.value)}
                  />
                </td>
                <td className="py-1 pr-2">
                  <input
                    className={cellInput}
                    value={line.unit}
                    aria-label={labels.unit}
                    onChange={(e) => update(line.key, 'unit', e.target.value)}
                  />
                </td>
                <td className="py-1 pr-2">
                  <input
                    type="number"
                    step="0.01"
                    min="0"
                    className={cellInput}
                    value={line.unit_rate}
                    aria-label={labels.rate}
                    placeholder="0.00"
                    onChange={(e) => update(line.key, 'unit_rate', e.target.value)}
                  />
                </td>
                <td className="py-1 pr-2">
                  <input
                    type="number"
                    step="any"
                    min="0"
                    list={listId}
                    className={cellInput}
                    value={line.vat_rate}
                    aria-label={labels.vat}
                    placeholder={defaultVat ?? ''}
                    onChange={(e) => update(line.key, 'vat_rate', e.target.value)}
                  />
                </td>
                <td className="py-1 pr-2 text-right tabular-nums leading-9">
                  <MoneyDisplay amount={lineNet(line)} currency={currency} />
                </td>
                <td className="py-1">
                  {lines.length > 1 && (
                    <button
                      type="button"
                      className="flex h-9 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-semantic-error"
                      aria-label={t('finance.line_remove', { defaultValue: 'Remove line {{n}}', n: index + 1 })}
                      onClick={() => onChange(lines.filter((l) => l.key !== line.key))}
                    >
                      <X size={14} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <button
        type="button"
        className="inline-flex items-center gap-1 text-xs font-medium text-oe-blue hover:underline"
        onClick={() => onChange([...lines, newEditorLine(defaultVat)])}
      >
        <Plus size={12} />
        {t('finance.line_add', { defaultValue: 'Add line' })}
      </button>

      {error && <p className="text-xs font-medium text-semantic-error">{error}</p>}

      <dl
        className="ml-auto grid w-full max-w-xs grid-cols-2 gap-x-4 gap-y-1 rounded-lg bg-surface-secondary/60 px-4 py-3 text-sm"
        data-testid="invoice-totals"
      >
        <dt className="text-content-secondary">{t('finance.total_net', { defaultValue: 'Net' })}</dt>
        <dd className="text-right tabular-nums" data-testid="invoice-total-net">
          <MoneyDisplay amount={totals.subtotal} currency={currency} />
        </dd>
        <dt className="text-content-secondary">{t('finance.total_vat', { defaultValue: 'VAT' })}</dt>
        <dd className="text-right tabular-nums" data-testid="invoice-total-vat">
          <MoneyDisplay amount={totals.tax} currency={currency} />
        </dd>
        <dt className="font-semibold text-content-primary">{t('finance.total_gross', { defaultValue: 'Gross' })}</dt>
        <dd className="text-right font-bold tabular-nums" data-testid="invoice-total-gross">
          <MoneyDisplay amount={totals.total} currency={currency} />
        </dd>
      </dl>
    </div>
  );
}
