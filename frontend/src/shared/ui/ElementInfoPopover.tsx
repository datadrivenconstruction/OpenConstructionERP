/**
 * ElementInfoPopover -- unified element info popup for BIM, DWG Takeoff, and
 * PDF Takeoff modules.
 *
 * Displays element name, type, all numeric properties/quantities, and a
 * "Link to BOQ" button.  Styled to match the existing Linked Geometry popover
 * from cellRenderers.tsx (rounded-xl, shadow, border).
 *
 * Accepts element data from any of the three modules via a discriminated union
 * (`source` field).  Each module can also pass raw properties for display.
 */

import { useCallback, useEffect, useRef, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import { X, Link2, Cuboid, PenLine, Ruler } from 'lucide-react';

/* ── Source-specific payload shapes ──────────────────────────────────── */

export interface BIMElementPayload {
  source: 'bim';
  id: string;
  name: string;
  elementType: string;
  category?: string;
  discipline?: string;
  storey?: string;
  quantities?: Record<string, number>;
  properties?: Record<string, unknown>;
  classification?: Record<string, string>;
}

export interface DWGElementPayload {
  source: 'dwg';
  id: string;
  type: string;
  layer: string;
  color?: string | number;
  /** Pre-computed measurements (perimeter, area, length, radius, etc.) */
  measurements?: Record<string, { value: number; unit: string }>;
  properties?: Record<string, unknown>;
}

export interface PDFMeasurementPayload {
  source: 'pdf';
  id: string;
  label: string;
  measurementType: string;
  value: number;
  unit: string;
  properties?: Record<string, unknown>;
}

export type ElementPayload =
  | BIMElementPayload
  | DWGElementPayload
  | PDFMeasurementPayload;

/* ── Component props ─────────────────────────────────────────────────── */

export interface ElementInfoPopoverProps {
  element: ElementPayload;
  /** Positioning style (fixed/absolute with top/left).  Caller computes
   *  the anchor position and passes it in. */
  style?: CSSProperties;
  /** Close callback. */
  onClose: () => void;
  /** Optional "Link to BOQ" callback.  When provided the button is
   *  rendered; the callee receives the element id and source type. */
  onLinkToBOQ?: (elementId: string, source: ElementPayload['source']) => void;
  /** If true the popover renders inside a portal (document.body). */
  portal?: boolean;
}

/* ── Helpers ─────────────────────────────────────────────────────────── */

function isNumeric(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v);
}

/** Extract a flat list of { label, value, unit? } rows from the element. */
function extractRows(
  el: ElementPayload,
): Array<{ label: string; value: string; unit?: string }> {
  const rows: Array<{ label: string; value: string; unit?: string }> = [];

  if (el.source === 'bim') {
    // Quantities (always numeric)
    if (el.quantities) {
      for (const [k, v] of Object.entries(el.quantities)) {
        if (isNumeric(v)) {
          const unit = k.includes('m2')
            ? 'm\u00B2'
            : k.includes('m3')
              ? 'm\u00B3'
              : k.includes('kg')
                ? 'kg'
                : k.includes('length') || k.includes('_m')
                  ? 'm'
                  : '';
          rows.push({ label: k, value: v.toFixed(3), unit });
        }
      }
    }
    // Numeric properties
    if (el.properties) {
      for (const [k, v] of Object.entries(el.properties)) {
        if (isNumeric(v)) {
          rows.push({ label: k, value: (v as number).toFixed(3) });
        }
      }
    }
  } else if (el.source === 'dwg') {
    if (el.measurements) {
      for (const [k, m] of Object.entries(el.measurements)) {
        rows.push({ label: k, value: m.value.toFixed(3), unit: m.unit });
      }
    }
    if (el.properties) {
      for (const [k, v] of Object.entries(el.properties)) {
        if (isNumeric(v)) {
          rows.push({ label: k, value: (v as number).toFixed(3) });
        } else if (typeof v === 'string' && v.trim()) {
          rows.push({ label: k, value: v });
        }
      }
    }
  } else if (el.source === 'pdf') {
    rows.push({ label: el.measurementType, value: el.value.toFixed(3), unit: el.unit });
    if (el.properties) {
      for (const [k, v] of Object.entries(el.properties)) {
        if (isNumeric(v)) {
          rows.push({ label: k, value: (v as number).toFixed(3) });
        } else if (typeof v === 'string' && v.trim()) {
          rows.push({ label: k, value: v });
        }
      }
    }
  }

  return rows;
}

function sourceIcon(source: ElementPayload['source']) {
  switch (source) {
    case 'bim':
      return <Cuboid size={14} className="text-oe-blue" />;
    case 'dwg':
      return <PenLine size={14} className="text-emerald-500" />;
    case 'pdf':
      return <Ruler size={14} className="text-amber-500" />;
  }
}

function sourceLabel(
  source: ElementPayload['source'],
  t: (key: string, opts?: Record<string, string>) => string,
): string {
  switch (source) {
    case 'bim':
      return t('element_info.source_bim', { defaultValue: 'BIM Element' });
    case 'dwg':
      return t('element_info.source_dwg', { defaultValue: 'DWG Entity' });
    case 'pdf':
      return t('element_info.source_pdf', { defaultValue: 'PDF Measurement' });
  }
}

function elementTitle(el: ElementPayload): string {
  if (el.source === 'bim') return el.name || el.elementType;
  if (el.source === 'dwg') return `${el.type} [${el.layer}]`;
  return el.label || el.measurementType;
}

function elementSubtitle(el: ElementPayload): string | null {
  if (el.source === 'bim') {
    const parts: string[] = [];
    if (el.category) parts.push(el.category);
    if (el.elementType) parts.push(el.elementType);
    if (el.storey) parts.push(el.storey);
    return parts.length > 0 ? parts.join(' / ') : null;
  }
  if (el.source === 'dwg') {
    return el.layer;
  }
  return null;
}

/* ── Main component ──────────────────────────────────────────────────── */

export function ElementInfoPopover({
  element,
  style,
  onClose,
  onLinkToBOQ,
  portal = false,
}: ElementInfoPopoverProps) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  // Close on click outside
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler, true);
    return () => document.removeEventListener('mousedown', handler, true);
  }, [onClose]);

  const handleLinkClick = useCallback(() => {
    onLinkToBOQ?.(element.id, element.source);
  }, [element.id, element.source, onLinkToBOQ]);

  const rows = extractRows(element);
  const title = elementTitle(element);
  const subtitle = elementSubtitle(element);

  const content = (
    <div
      ref={ref}
      className="rounded-xl shadow-2xl border border-border-light dark:border-border-dark
                 bg-white dark:bg-surface-elevated overflow-hidden"
      style={{ ...style, width: 340, zIndex: 9999 }}
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-border-light dark:border-border-dark bg-surface-secondary/30">
        <div className="flex items-center gap-2 min-w-0">
          {sourceIcon(element.source)}
          <div className="min-w-0">
            <span className="block text-xs font-semibold text-content-primary truncate">
              {title}
            </span>
            {subtitle && (
              <span className="block text-[10px] text-content-tertiary truncate">
                {subtitle}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0 ml-2">
          <span className="text-[9px] text-content-quaternary uppercase tracking-wider font-medium">
            {sourceLabel(element.source, t)}
          </span>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-0.5 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
            aria-label={t('common.close', { defaultValue: 'Close' })}
          >
            <X size={14} />
          </button>
        </div>
      </div>

      {/* Properties / Quantities */}
      <div className="max-h-64 overflow-y-auto">
        {rows.length === 0 ? (
          <div className="px-4 py-3 text-[11px] text-content-tertiary italic">
            {t('element_info.no_properties', { defaultValue: 'No numeric properties available.' })}
          </div>
        ) : (
          <table className="w-full text-[11px]">
            <tbody>
              {rows.map((row, idx) => (
                <tr
                  key={`${row.label}-${idx}`}
                  className="border-b border-border-light/50 last:border-b-0 hover:bg-surface-secondary/40"
                >
                  <td className="px-4 py-1.5 text-content-secondary font-medium whitespace-nowrap">
                    {row.label}
                  </td>
                  <td className="px-4 py-1.5 text-right text-content-primary tabular-nums font-mono">
                    {row.value}
                    {row.unit && (
                      <span className="ml-1 text-content-tertiary font-sans text-[10px]">
                        {row.unit}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Footer with Link to BOQ */}
      {onLinkToBOQ && (
        <div className="border-t border-border-light dark:border-border-dark px-4 py-2">
          <button
            type="button"
            onClick={handleLinkClick}
            className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-oe-blue px-3 py-1.5 text-[11px] font-semibold text-white shadow-sm hover:bg-oe-blue-dark transition-colors"
          >
            <Link2 size={12} />
            {t('element_info.link_to_boq', { defaultValue: 'Link to BOQ' })}
          </button>
        </div>
      )}

      {/* Element ID footer */}
      <div className="px-4 py-1 bg-surface-secondary/20 border-t border-border-light/30">
        <span className="text-[9px] text-content-quaternary font-mono truncate block">
          ID: {element.id}
        </span>
      </div>
    </div>
  );

  if (portal) {
    return createPortal(content, document.body);
  }
  return content;
}

export default ElementInfoPopover;
