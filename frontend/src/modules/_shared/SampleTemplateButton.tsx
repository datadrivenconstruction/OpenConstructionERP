// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Shared "expected layout + download a starter file" affordance for the
 * country-specific BOQ exchange modules.
 *
 * Every regional exchange page asks the user to drop a "<standard>-formatted
 * BOQ (CSV / TSV / XLSX)" but never says *which columns in which order*. A
 * country specialist who has never used this tool cannot guess that column 0
 * is the ordinal, column 1 the description, etc. This component closes that
 * gap purely from data already present in the module's `CountryTemplate`:
 *
 *   • it lists the expected column order and marks the mandatory ones, and
 *   • it generates a ready-to-fill starter CSV (header + two worked example
 *     rows + a section row) so the user has a correct file to start from.
 *
 * It is intentionally self-contained and data-driven so all ~20 modules can
 * adopt it with a single import + one line of JSX, with zero duplication.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FileSpreadsheet, Download, ChevronDown } from 'lucide-react';
import { triggerDownload } from '@/shared/lib/api';
import type { CountryTemplate, ColumnMapping } from './templateTypes';

/** Human-readable label + example value for every supported column. */
const COLUMN_META: Record<
  keyof ColumnMapping,
  { labelKey: string; label: string; ex1: string; ex2: string }
> = {
  ordinal: { labelKey: 'exchange.col_ordinal', label: 'Item / Position no.', ex1: '01.01.001', ex2: '01.01.002' },
  description: { labelKey: 'exchange.col_description', label: 'Description', ex1: 'Reinforced concrete C30/37, foundation slab', ex2: 'Formwork to slab edges' },
  unit: { labelKey: 'exchange.col_unit', label: 'Unit', ex1: 'm3', ex2: 'm2' },
  quantity: { labelKey: 'exchange.col_quantity', label: 'Quantity', ex1: '125.000', ex2: '48.000' },
  unitRate: { labelKey: 'exchange.col_unit_rate', label: 'Unit rate', ex1: '142.50', ex2: '38.00' },
  total: { labelKey: 'exchange.col_total', label: 'Total', ex1: '17812.50', ex2: '1824.00' },
  section: { labelKey: 'exchange.col_section', label: 'Section / trade', ex1: 'Substructure', ex2: 'Substructure' },
  classification: { labelKey: 'exchange.col_classification', label: 'Classification code', ex1: '', ex2: '' },
};

/** Ordered list of the columns this template actually maps. */
function orderedColumns(tpl: CountryTemplate): (keyof ColumnMapping)[] {
  const ORDER: (keyof ColumnMapping)[] = [
    'ordinal',
    'description',
    'unit',
    'quantity',
    'unitRate',
    'total',
    'classification',
    'section',
  ];
  return ORDER.filter((k) => tpl.defaultColumns[k] != null);
}

function escapeCSV(val: string): string {
  return /[",;\n]/.test(val) ? `"${val.replace(/"/g, '""')}"` : val;
}

export function SampleTemplateButton({ template }: { template: CountryTemplate }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const cols = orderedColumns(template);
  const required = new Set(template.requiredColumns);

  const handleDownload = () => {
    const header = cols.map((k) =>
      k === 'classification' ? template.classification || 'Classification' : COLUMN_META[k].label,
    );
    const row1 = cols.map((k) => (k === 'classification' ? '' : COLUMN_META[k].ex1));
    const row2 = cols.map((k) => (k === 'classification' ? '' : COLUMN_META[k].ex2));
    // A section/header row so the user sees how grouping is represented.
    const sectionRow = cols.map((k) =>
      k === 'ordinal' ? '01' : k === 'description' ? '** Substructure **' : '',
    );
    const lines = [header, sectionRow, row1, row2]
      .map((r) => r.map((c) => escapeCSV(String(c))).join(','))
      .join('\r\n');
    const blob = new Blob(['' + lines], { type: 'text/csv;charset=utf-8' });
    triggerDownload(
      blob,
      `${template.countryCode}_${template.classification || 'BOQ'}_sample_template.csv`,
    );
  };

  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary/30 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-xs font-medium text-content-secondary hover:bg-surface-secondary/50 transition-colors"
        aria-expanded={open}
      >
        <FileSpreadsheet size={14} className="text-oe-blue shrink-0" />
        <span className="flex-1 text-left">
          {t('exchange.expected_layout', {
            defaultValue: 'Expected file layout - {{standard}}',
            standard: template.classification || template.name,
          })}
        </span>
        <ChevronDown
          size={13}
          className={`text-content-quaternary transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && (
        <div className="px-3 pb-3 pt-1 space-y-2.5">
          <p className="text-2xs text-content-tertiary leading-relaxed">
            {t('exchange.layout_help', {
              defaultValue:
                'Columns are read in this order (no header row required). Mandatory columns must contain a value in every priced line. Section/heading rows use “** Title **” in the description and leave quantity blank.',
            })}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {cols.map((k, i) => (
              <span
                key={k}
                className="inline-flex items-center gap-1 rounded bg-surface-tertiary/60 px-2 py-0.5 text-2xs text-content-secondary"
                title={
                  required.has(k)
                    ? t('exchange.col_required', { defaultValue: 'Required' })
                    : t('exchange.col_optional', { defaultValue: 'Optional' })
                }
              >
                <span className="font-mono text-content-quaternary">{i + 1}</span>
                <span className="font-medium">
                  {k === 'classification'
                    ? template.classification || t(COLUMN_META[k].labelKey, { defaultValue: COLUMN_META[k].label })
                    : t(COLUMN_META[k].labelKey, { defaultValue: COLUMN_META[k].label })}
                </span>
                {required.has(k) && <span className="text-semantic-error font-semibold">*</span>}
              </span>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-content-quaternary">
            <span>
              {t('exchange.accepted_formats', { defaultValue: 'Accepted' })}:{' '}
              <span className="font-mono">{template.acceptedExtensions.join('  ')}</span>
            </span>
            <span>
              {t('exchange.currency', { defaultValue: 'Currency' })}:{' '}
              <span className="font-medium">
                {template.currencySymbol} {template.currency}
              </span>
            </span>
          </div>
          <button
            type="button"
            onClick={handleDownload}
            className="inline-flex items-center gap-1.5 rounded-md border border-oe-blue/40 bg-oe-blue/5 px-2.5 py-1 text-2xs font-medium text-oe-blue hover:bg-oe-blue/10 transition-colors"
          >
            <Download size={12} />
            {t('exchange.download_sample', { defaultValue: 'Download a ready-to-fill sample CSV' })}
          </button>
        </div>
      )}
    </div>
  );
}
