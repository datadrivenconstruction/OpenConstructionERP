// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * BIMFilterReportModal - the on-screen "report from the current filter" (B5).
 *
 * Shows a breakdown of the scoped elements (whole model, current filter, or
 * the current selection) by element type and by storey, with summed
 * quantities and a total row. From here the user can Print / Save as PDF
 * (a clean standalone document) or download the same data as the Excel BOQ
 * (reusing the B6 export). Built entirely from the element list already in
 * memory, so it opens instantly.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { FileSpreadsheet, Printer, Loader2 } from 'lucide-react';
import type { BIMElementData } from '@/shared/ui/BIMViewer';
import { Button } from '@/shared/ui';
import { WideModal } from '@/shared/ui/WideModal';
import { useToastStore } from '@/stores/useToastStore';
import { useDisplayQuantity } from '@/shared/hooks/useDisplayQuantity';
import { summariseBimQuantities, QUANTITY_FIELDS, type QuantitySummary } from './boqSummary';
import { buildReportHtml } from './printReport';
import { exportBoqXlsx } from './api';
import { getIntlLocale } from '@/shared/lib/formatters';

interface BIMFilterReportModalProps {
  open: boolean;
  onClose: () => void;
  modelId: string;
  /** Human label for what is being reported (e.g. "Current filter"). */
  scopeLabel: string;
  /** Model name, used in the report title + the export. */
  modelName?: string;
  /** The scoped element subset to report on. */
  elements: BIMElementData[];
}

function SummaryTable({ summary, groupHeader }: { summary: QuantitySummary; groupHeader: string }) {
  const { t } = useTranslation();
  // Display-only metric->imperial conversion (#285). The summary is
  // metric-canonical; here we restate each quantity column + its header unit
  // into the user's measurement system. Unmapped units pass through. The
  // Excel export downloads the canonical (metric) BOQ from the backend
  // separately, so this on-screen restatement never touches stored data.
  const dq = useDisplayQuantity();
  const fmt = (n: number) => n.toLocaleString(getIntlLocale(), { maximumFractionDigits: 3 });
  const conv = (value: number, i: number) =>
    dq.convert(value, QUANTITY_FIELDS[i]?.unit ?? '').value;
  return (
    <table className="w-full text-[11px] border-collapse">
      <thead>
        <tr className="bg-surface-secondary">
          <th className="border border-border-light px-2 py-1 text-left">{groupHeader}</th>
          <th className="border border-border-light px-2 py-1 text-right">
            {t('bim.report.count', { defaultValue: 'Count' })}
          </th>
          {QUANTITY_FIELDS.map((f) => (
            <th key={f.key} className="border border-border-light px-2 py-1 text-right">
              {f.label} ({dq.unitFor(f.unit)})
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {summary.rows.map((r) => (
          <tr key={r.key}>
            <td className="border border-border-light px-2 py-1">{r.key}</td>
            <td className="border border-border-light px-2 py-1 text-right tabular-nums">{fmt(r.count)}</td>
            {r.quantities.map((q, i) => (
              <td key={i} className="border border-border-light px-2 py-1 text-right tabular-nums">
                {fmt(conv(q, i))}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
      <tfoot>
        <tr className="bg-surface-secondary font-semibold">
          <td className="border border-border-light px-2 py-1">
            {t('bim.report.total', { defaultValue: 'TOTAL' })}
          </td>
          <td className="border border-border-light px-2 py-1 text-right tabular-nums">
            {fmt(summary.totals.count)}
          </td>
          {summary.totals.quantities.map((q, i) => (
            <td key={i} className="border border-border-light px-2 py-1 text-right tabular-nums">
              {fmt(conv(q, i))}
            </td>
          ))}
        </tr>
      </tfoot>
    </table>
  );
}

export default function BIMFilterReportModal({
  open,
  onClose,
  modelId,
  scopeLabel,
  modelName,
  elements,
}: BIMFilterReportModalProps) {
  const { t } = useTranslation();
  const dq = useDisplayQuantity();
  const [exporting, setExporting] = useState(false);

  const byType = useMemo(() => summariseBimQuantities(elements, 'element_type'), [elements]);
  const byStorey = useMemo(() => summariseBimQuantities(elements, 'storey'), [elements]);

  const title = t('bim.report.title', {
    defaultValue: 'Quantity report - {{model}}',
    model: modelName || t('bim.report.model_fallback', { defaultValue: 'Model' }),
  });

  const handlePrint = () => {
    const html = buildReportHtml({
      title,
      scopeLabel: `${scopeLabel} - ${t('bim.report.elements_n', {
        defaultValue: '{{count}} elements',
        count: elements.length,
      })}`,
      // No Date.now() in callers that must be deterministic, but this is a
      // user-initiated print so a live timestamp is correct here.
      generatedOn: new Date().toLocaleString(getIntlLocale()),
      // Restate quantity columns into the user's measurement system so the
      // printed PDF matches the on-screen report (#285). Money/totals are
      // unaffected - these are quantity columns only.
      system: dq.system,
      sections: [
        {
          heading: t('bim.report.by_type', { defaultValue: 'By element type' }),
          groupLabel: t('bim.report.element_type', { defaultValue: 'Element type' }),
          summary: byType,
        },
        {
          heading: t('bim.report.by_storey', { defaultValue: 'By storey' }),
          groupLabel: t('bim.report.storey', { defaultValue: 'Storey' }),
          summary: byStorey,
        },
      ],
    });
    const w = window.open('', '_blank');
    if (!w) {
      useToastStore.getState().addToast({
        type: 'warning',
        title: t('bim.report.popup_blocked', { defaultValue: 'Allow pop-ups to print' }),
        message: t('bim.report.popup_blocked_msg', {
          defaultValue: 'Your browser blocked the print window. Allow pop-ups for this site and try again.',
        }),
      });
      return;
    }
    w.document.write(html);
    w.document.close();
    w.focus();
    w.print();
  };

  const handleExportExcel = async () => {
    setExporting(true);
    try {
      await exportBoqXlsx(modelId, {
        element_ids: elements.map((e) => e.id),
        group_by: 'element_type',
      });
    } catch (e) {
      useToastStore.getState().addToast({
        type: 'error',
        title: t('bim.boq_export_failed', { defaultValue: 'BOQ export failed' }),
        message: e instanceof Error ? e.message : String(e),
      });
    } finally {
      setExporting(false);
    }
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      title={title}
      subtitle={`${scopeLabel} - ${t('bim.report.elements_n', {
        defaultValue: '{{count}} elements',
        count: elements.length,
      })}`}
      size="xl"
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button variant="secondary" onClick={handlePrint} data-testid="bim-report-print">
            <Printer size={14} className="me-1.5" />
            {t('bim.report.print', { defaultValue: 'Print / Save as PDF' })}
          </Button>
          <Button onClick={handleExportExcel} disabled={exporting} data-testid="bim-report-export">
            {exporting ? (
              <Loader2 size={14} className="me-1.5 animate-spin" />
            ) : (
              <FileSpreadsheet size={14} className="me-1.5" />
            )}
            {t('bim.report.export_excel', { defaultValue: 'Export Excel' })}
          </Button>
        </div>
      }
    >
      {elements.length === 0 ? (
        <p className="text-[12px] text-content-tertiary italic" data-testid="bim-report-empty">
          {t('bim.report.empty', {
            defaultValue: 'No elements in the current scope. Adjust the filter or selection and try again.',
          })}
        </p>
      ) : (
        <div className="flex flex-col gap-5">
          <section>
            <h3 className="text-xs font-semibold text-content-primary uppercase tracking-wide mb-1.5">
              {t('bim.report.by_type', { defaultValue: 'By element type' })}
            </h3>
            <SummaryTable
              summary={byType}
              groupHeader={t('bim.report.element_type', { defaultValue: 'Element type' })}
            />
          </section>
          <section>
            <h3 className="text-xs font-semibold text-content-primary uppercase tracking-wide mb-1.5">
              {t('bim.report.by_storey', { defaultValue: 'By storey' })}
            </h3>
            <SummaryTable
              summary={byStorey}
              groupHeader={t('bim.report.storey', { defaultValue: 'Storey' })}
            />
          </section>
        </div>
      )}
    </WideModal>
  );
}
