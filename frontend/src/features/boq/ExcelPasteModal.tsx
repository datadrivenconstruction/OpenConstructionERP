// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ExcelPasteModal — Paste tab-separated data from Excel/Sheets into BOQ.
 *
 * Auto-detects columns by header names (Pos, Description, Unit, Qty, Rate)
 * and falls back to positional order.  Supports both 1,234.56 and 1.234,56 formats.
 */

import { useState, useCallback, useMemo, useEffect, useId, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { ClipboardPaste, X, Upload, AlertTriangle, CheckCircle2 } from 'lucide-react';
import { Button } from '@/shared/ui';
import { useFocusTrap } from '@/shared/hooks/useFocusTrap';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { fmtList } from '@/shared/lib/formatters';

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

/**
 * Parse a human-entered number in either 1,234.56 or 1.234,56 grouping.
 * Returns NaN when the cell holds something that is not a number, so the
 * caller can flag it instead of silently reading a bad value as zero.
 */
function parseNumber(s: string): number {
  const trimmed = s.trim();
  if (!trimmed) return NaN;
  const cleaned = trimmed.replace(/[^\d.,-]/g, '');
  if (!/\d/.test(cleaned)) return NaN;
  // Detect European format: 1.234,56
  if (/^\d{1,3}(\.\d{3})*(,\d+)?$/.test(cleaned)) {
    return parseFloat(cleaned.replace(/\./g, '').replace(',', '.'));
  }
  // US/UK format: 1,234.56
  return parseFloat(cleaned.replace(/,/g, ''));
}

export interface ParseResult {
  rows: PastedRow[];
  detectedHeaders: string[];
  /** Data lines dropped because they carried no description. */
  skippedEmpty: number;
  /** Number cells that were present but could not be read as a number. */
  invalidNumbers: number;
}

export function parseRows(raw: string): ParseResult {
  const lines = raw.split('\n').filter((l) => l.trim());
  if (lines.length === 0)
    return { rows: [], detectedHeaders: [], skippedEmpty: 0, invalidNumbers: 0 };

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
  let skippedEmpty = 0;
  let invalidNumbers = 0;

  for (const line of dataLines) {
    const cells = line.split('\t');
    const row: Record<string, string> = {};
    for (const [idx, field] of Object.entries(colMap)) {
      row[field] = (cells[Number(idx)] ?? '').trim();
    }

    const desc = row['description'] || '';
    if (!desc) {
      // A line carried some content but no description, so it cannot become a
      // position. Count it so the user is told rather than left guessing.
      skippedEmpty++;
      continue;
    }

    const rawQty = row['quantity'] ?? '';
    const rawRate = row['unit_rate'] ?? '';
    let quantity = rawQty ? parseNumber(rawQty) : 1;
    let unit_rate = rawRate ? parseNumber(rawRate) : 0;
    if (Number.isNaN(quantity)) {
      invalidNumbers++;
      quantity = 1;
    }
    if (Number.isNaN(unit_rate)) {
      invalidNumbers++;
      unit_rate = 0;
    }

    rows.push({
      ordinal: row['ordinal'] || String(autoOrdinal++).padStart(2, '0'),
      description: desc,
      unit: row['unit'] || 'pcs',
      quantity,
      unit_rate,
    });
  }

  return { rows, detectedHeaders, skippedEmpty, invalidNumbers };
}

/* ── Component ────────────────────────────────────────────────────── */

export function ExcelPasteModal({ open, onClose, onImport, loading }: ExcelPasteModalProps) {
  const { t } = useTranslation();
  const [raw, setRaw] = useState('');
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useFocusTrap(panelRef, open);

  const { rows, detectedHeaders, skippedEmpty, invalidNumbers } = useMemo(
    () => parseRows(raw),
    [raw],
  );
  const totalSum = useMemo(() => rows.reduce((s, r) => s + r.quantity * r.unit_rate, 0), [rows]);

  const handleImport = useCallback(() => {
    if (rows.length > 0) onImport(rows);
  }, [rows, onImport]);

  const handleClose = useCallback(() => {
    setRaw('');
    onClose();
  }, [onClose]);

  // Escape closes the modal (unless an import is in flight).
  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && !loading) {
        e.preventDefault();
        handleClose();
      }
    }
    document.addEventListener('keydown', onKey, { capture: true });
    return () => document.removeEventListener('keydown', onKey, { capture: true });
  }, [open, loading, handleClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in" onClick={handleClose}>
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="w-full max-w-3xl mx-4 bg-surface-primary rounded-2xl shadow-2xl border border-border-light overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <div className="flex items-center gap-3">
            <div className="h-9 w-9 rounded-lg bg-oe-blue-subtle flex items-center justify-center">
              <ClipboardPaste size={18} className="text-oe-blue" />
            </div>
            <div>
              <h2 id={titleId} className="text-base font-semibold">{t('boq.paste_from_excel', { defaultValue: 'Paste from Excel' })}</h2>
              <p className="text-xs text-content-secondary">{t('boq.paste_excel_hint', { defaultValue: 'Copy rows from Excel or Google Sheets and paste below' })}</p>
            </div>
          </div>
          <button
            onClick={handleClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="p-1.5 rounded-lg hover:bg-surface-secondary transition-colors"
          >
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
                  ({t('boq.paste_columns', { defaultValue: 'Columns' })}: {fmtList(detectedHeaders)})
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

          {/* Nothing is dropped in silence: tell the user what could not be read. */}
          {(skippedEmpty > 0 || invalidNumbers > 0) && (
            <div className="space-y-1 rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2">
              {skippedEmpty > 0 && (
                <div className="flex items-center gap-2 text-amber-700">
                  <AlertTriangle size={14} />
                  <span className="text-xs">
                    {t('boq.paste_skipped_rows', { defaultValue: '{{count}} rows had no description and were skipped', count: skippedEmpty })}
                  </span>
                </div>
              )}
              {invalidNumbers > 0 && (
                <div className="flex items-center gap-2 text-amber-700">
                  <AlertTriangle size={14} />
                  <span className="text-xs">
                    {t('boq.paste_invalid_numbers', { defaultValue: '{{count}} number cells could not be read and kept their default (qty 1, rate 0)', count: invalidNumbers })}
                  </span>
                </div>
              )}
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
                        <td className="px-3 py-1.5 text-right tabular-nums">{r.quantity.toLocaleString(getNumberLocale())}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums">{r.unit_rate.toLocaleString(getNumberLocale(), { minimumFractionDigits: 2 })}</td>
                        <td className="px-3 py-1.5 text-right tabular-nums font-medium">{(r.quantity * r.unit_rate).toLocaleString(getNumberLocale(), { minimumFractionDigits: 2 })}</td>
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
                {rows.length} {t('boq.positions', { defaultValue: 'positions' })} · {t('boq.total', { defaultValue: 'Total' })}: {totalSum.toLocaleString(getNumberLocale(), { minimumFractionDigits: 2 })}
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
