/**
 * ExcelPasteModal — Paste tab-separated data from Excel/Sheets into BOQ.
 *
 * Auto-detects columns by header names (Pos, Description, Unit, Qty, Rate)
 * and falls back to positional order.  Supports both 1,234.56 and 1.234,56 formats.
 */

import { useState, useCallback, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { ClipboardPaste, X, Upload, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { Button } from '@/shared/ui';

export interface PastedRow {
  ordinal: string;
  description: string;
  unit: string;
  quantity: number;
  unit_rate: number;
}

interface ExcelPasteModalProps {
  open: boolean;
  onClose: () => void;
  onImport: (rows: PastedRow[]) => void;
  loading?: boolean;
}

/* ── Header detection ─────────────────────────────────────────────── */

const HEADER_MAP: Record<string, string> = {
  // English
  pos: 'ordinal', 'pos.': 'ordinal', no: 'ordinal', 'no.': 'ordinal', number: 'ordinal', ordinal: 'ordinal', '#': 'ordinal',
  description: 'description', desc: 'description', text: 'description', item: 'description', bezeichnung: 'description',
  unit: 'unit', einheit: 'unit', eh: 'unit', uom: 'unit',
  qty: 'quantity', quantity: 'quantity', menge: 'quantity', amount: 'quantity', 'qty.': 'quantity',
  rate: 'unit_rate', 'unit rate': 'unit_rate', 'unit_rate': 'unit_rate', price: 'unit_rate',
  einzelpreis: 'unit_rate', ep: 'unit_rate', 'unit price': 'unit_rate',
};

function detectColumns(headerCells: string[]): Record<number, string> {
  const mapping: Record<number, string> = {};
  for (let i = 0; i < headerCells.length; i++) {
    const cell = headerCells[i] ?? '';
    const key = cell.trim().toLowerCase().replace(/[.*]/g, '');
    const mapped = HEADER_MAP[key];
    if (mapped) {
      mapping[i] = mapped;
    }
  }
  return mapping;
}

const DEFAULT_ORDER = ['description', 'unit', 'quantity', 'unit_rate'];

function parseNumber(s: string): number {
  if (!s) return 0;
  const cleaned = s.replace(/[^\d.,-]/g, '');
  // Detect European format: 1.234,56
  if (/^\d{1,3}(\.\d{3})*(,\d+)?$/.test(cleaned)) {
    return parseFloat(cleaned.replace(/\./g, '').replace(',', '.')) || 0;
  }
  // US/UK format: 1,234.56
  return parseFloat(cleaned.replace(/,/g, '')) || 0;
}

function parseRows(raw: string): { rows: PastedRow[]; detectedHeaders: string[] } {
  const lines = raw.split('\n').filter((l) => l.trim());
  if (lines.length === 0) return { rows: [], detectedHeaders: [] };

  const firstLine = lines[0] ?? '';
  const firstRow = firstLine.split('\t');
  let colMap = detectColumns(firstRow);
  const hasHeaders = Object.keys(colMap).length >= 2;

  const detectedHeaders: string[] = [];
  if (hasHeaders) {
    for (const [, field] of Object.entries(colMap)) {
      detectedHeaders.push(field);
    }
  } else {
    // No headers — use default positional order
    for (let i = 0; i < Math.min(firstRow.length, DEFAULT_ORDER.length); i++) {
      colMap[i] = DEFAULT_ORDER[i] ?? 'description';
    }
  }

  const dataLines = hasHeaders ? lines.slice(1) : lines;
  const rows: PastedRow[] = [];
  let autoOrdinal = 1;

  for (const line of dataLines) {
    const cells = line.split('\t');
    const row: Record<string, string> = {};
    for (const [idx, field] of Object.entries(colMap)) {
      row[field] = (cells[Number(idx)] ?? '').trim();
    }

    const desc = row['description'] || '';
    if (!desc) continue; // Skip empty descriptions

    rows.push({
      ordinal: row['ordinal'] || String(autoOrdinal++).padStart(2, '0'),
      description: desc,
      unit: row['unit'] || 'pcs',
      quantity: parseNumber(row['quantity'] || '1'),
      unit_rate: parseNumber(row['unit_rate'] || '0'),
    });
  }

  return { rows, detectedHeaders };
}

/* ── Component ────────────────────────────────────────────────────── */

export function ExcelPasteModal({ open, onClose, onImport, loading }: ExcelPasteModalProps) {
  const { t } = useTranslation();
  const [raw, setRaw] = useState('');

  const { rows, detectedHeaders } = useMemo(() => parseRows(raw), [raw]);
  const totalSum = useMemo(() => rows.reduce((s, r) => s + r.quantity * r.unit_rate, 0), [rows]);

  const handleImport = useCallback(() => {
    if (rows.length > 0) onImport(rows);
  }, [rows, onImport]);

  const handleClose = useCallback(() => {
    setRaw('');
    onClose();
  }, [onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fade-in" onClick={handleClose}>
      <div className="w-full max-w-3xl mx-4 bg-surface-primary rounded-2xl shadow-2xl border border-border-light overflow-hidden" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-oe-blue-subtle flex items-center justify-center">
              <ClipboardPaste size={18} className="text-oe-blue" />
            </div>
            <div>
              <h2 className="text-base font-semibold">{t('boq.paste_from_excel', { defaultValue: 'Paste from Excel' })}</h2>
              <p className="text-xs text-content-secondary">{t('boq.paste_excel_hint', { defaultValue: 'Copy rows from Excel or Google Sheets and paste below' })}</p>
            </div>
          </div>
          <button onClick={handleClose} className="p-1.5 rounded-lg hover:bg-surface-secondary transition-colors">
            <X size={18} className="text-content-tertiary" />
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-4 max-h-[70vh] overflow-y-auto">
          {/* Textarea */}
          <textarea
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            placeholder={t('boq.paste_placeholder', { defaultValue: 'Paste tab-separated data here...\n\nExample:\nDescription\tUnit\tQty\tRate\nConcrete foundation\tm3\t120\t185.00\nRebar B500S\tkg\t2400\t1.45' })}
            className="w-full h-40 rounded-xl border border-border-light bg-surface-secondary px-4 py-3 text-sm font-mono resize-none focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue"
            autoFocus
          />

          {/* Detection feedback */}
          {rows.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <CheckCircle2 size={14} className="text-emerald-500" />
              <span className="text-xs text-content-secondary">
                {t('boq.paste_detected', { defaultValue: '{{count}} rows detected', count: rows.length })}
              </span>
              {detectedHeaders.length > 0 && (
                <span className="text-xs text-content-tertiary">
                  ({t('boq.paste_columns', { defaultValue: 'Columns' })}: {detectedHeaders.join(', ')})
                </span>
              )}
            </div>
          )}

          {rows.length === 0 && raw.trim().length > 0 && (
            <div className="flex items-center gap-2 text-amber-600">
              <AlertTriangle size={14} />
              <span className="text-xs">{t('boq.paste_no_data', { defaultValue: 'No valid rows detected. Make sure data is tab-separated.' })}</span>
            </div>
          )}

          {/* Preview table */}
          {rows.length > 0 && (
            <div className="rounded-xl border border-border-light overflow-hidden">
              <div className="overflow-x-auto max-h-60">
                <table className="w-full text-xs">
                  <thead className="bg-surface-secondary sticky top-0">
                    <tr>
                      <th className="px-3 py-2 text-left font-semibold text-content-secondary">#</th>
                      <th className="px-3 py-2 text-left font-semibold text-content-secondary">{t('boq.description', { defaultValue: 'Description' })}</th>
                      <th className="px-3 py-2 text-center font-semibold text-content-secondary">{t('boq.unit', { defaultValue: 'Unit' })}</th>
                      <th className="px-3 py-2 text-right font-semibold text-content-secondary">{t('boq.quantity', { defaultValue: 'Qty' })}</th>
                      <th className="px-3 py-2 text-right font-semibold text-content-secondary">{t('boq.unit_rate', { defaultValue: 'Rate' })}</th>
                      <th className="px-3 py-2 text-right font-semibold text-content-secondary">{t('boq.total', { defaultValue: 'Total' })}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border-light">
                    {rows.slice(0, 50).map((r, i) => (
                      <tr key={`${r.ordinal}-${i}`} className="hover:bg-surface-secondary/50">
                        <td className="px-3 py-1.5 font-mono text-content-tertiary">{r.ordinal}</td>
                        <td className="px-3 py-1.5 max-w-[300px] truncate">{r.description}</td>
                        <td className="px-3 py-1.5 text-center font-mono uppercase">{r.unit}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums">{r.quantity.toLocaleString()}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums">{r.unit_rate.toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums font-medium">{(r.quantity * r.unit_rate).toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {rows.length > 50 && (
                <div className="px-3 py-1.5 text-xs text-content-tertiary bg-surface-secondary text-center">
                  {t('boq.paste_showing', { defaultValue: 'Showing first 50 of {{total}} rows', total: rows.length })}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-border-light bg-surface-secondary/30">
          <div className="text-xs text-content-secondary">
            {rows.length > 0 && (
              <span>
                {rows.length} {t('boq.positions', { defaultValue: 'positions' })} · {t('boq.total', { defaultValue: 'Total' })}: {totalSum.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={handleClose}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            <Button
              variant="primary"
              size="sm"
              icon={<Upload size={15} />}
              onClick={handleImport}
              disabled={rows.length === 0 || loading}
              loading={loading}
            >
              {t('boq.import_rows', { defaultValue: 'Import {{count}} rows', count: rows.length })}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
