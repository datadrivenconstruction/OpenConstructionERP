// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * `<PortLegend>` — a compact, collapsible key that explains what the port
 * dots mean and how to connect two steps, in plain language.
 *
 * Lives pinned at the foot of the `NodePalette` so a first-time user always
 * has the reference in reach while wiring a graph. Renders the identical
 * shape-coded glyph as the canvas nodes (via the shared `PortGlyph`) so the
 * legend and the graph read as one system.
 */
import clsx from 'clsx';
import {
  ArrowRightFromLine,
  ArrowRightToLine,
  Cable,
  ChevronDown,
  ChevronRight,
} from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { PortGlyph } from './PortGlyph';
import { getPortTokens, PORT_TYPE_ORDER } from '../tokens';

export interface PortLegendProps {
  /** Start expanded (defaults to collapsed to keep the palette tidy). */
  defaultOpen?: boolean;
  testId?: string;
}

export function PortLegend({ defaultOpen = false, testId }: PortLegendProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div
      data-testid={testId ?? 'pipeline-port-legend'}
      className="shrink-0 border-t border-border bg-surface-secondary px-2 py-1.5"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        data-testid="pipeline-port-legend-toggle"
        className={clsx(
          'flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-start',
          'text-2xs font-semibold uppercase tracking-wide text-content-secondary',
          'hover:bg-surface-tertiary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-oe-blue/30',
        )}
      >
        {open ? (
          <ChevronDown size={13} aria-hidden="true" />
        ) : (
          <ChevronRight size={13} aria-hidden="true" className="rtl:scale-x-[-1]" />
        )}
        {t('pipeline.legend.title', { defaultValue: 'How ports work' })}
      </button>

      {open && (
        <div className="mt-1.5 space-y-2.5 px-1.5 pb-1">
          {/* Plain-language connect hint */}
          <p className="flex items-start gap-1.5 text-2xs leading-relaxed text-content-secondary">
            <Cable
              size={13}
              aria-hidden="true"
              className="mt-px shrink-0 text-content-tertiary"
            />
            {t('pipeline.legend.connect_hint', {
              defaultValue:
                'Drag from an Out dot on one step to the In dot on the next. Ports link only when their data types match (same colour and shape).',
            })}
          </p>

          {/* Direction key */}
          <div className="space-y-1">
            <div className="flex items-center gap-1.5 text-2xs text-content-secondary">
              <ArrowRightToLine
                size={12}
                aria-hidden="true"
                className="shrink-0 text-content-tertiary rtl:scale-x-[-1]"
              />
              <span>
                <span className="font-semibold">
                  {t('pipeline.port.inputs_caption', { defaultValue: 'In' })}
                </span>{' '}
                {t('pipeline.legend.in_desc', {
                  defaultValue: 'a step receives data here',
                })}
              </span>
            </div>
            <div className="flex items-center gap-1.5 text-2xs text-content-secondary">
              <ArrowRightFromLine
                size={12}
                aria-hidden="true"
                className="shrink-0 text-content-tertiary rtl:scale-x-[-1]"
              />
              <span>
                <span className="font-semibold">
                  {t('pipeline.port.outputs_caption', { defaultValue: 'Out' })}
                </span>{' '}
                {t('pipeline.legend.out_desc', {
                  defaultValue: 'a step sends its result here',
                })}
              </span>
            </div>
          </div>

          {/* Data-type key */}
          <div>
            <p className="mb-1 text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
              {t('pipeline.legend.types_title', { defaultValue: 'Data types' })}
            </p>
            <ul className="space-y-1">
              {PORT_TYPE_ORDER.map((dt) => (
                <li
                  key={dt}
                  className="flex items-center gap-2 text-2xs text-content-secondary"
                >
                  <PortGlyph type={dt} size={12} />
                  <span className="truncate">
                    {t(getPortTokens(dt).labelKey, {
                      defaultValue: getPortTokens(dt).labelDefault,
                    })}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

export default PortLegend;
