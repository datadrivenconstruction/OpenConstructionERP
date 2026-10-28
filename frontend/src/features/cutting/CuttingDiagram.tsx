// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SVG cutting diagrams. Linear plans draw one bar per distinct pattern (with a
 * repeat count) to a common scale; sheet plans draw each sheet with its pieces,
 * reusable offcuts dashed, and the origin at the bottom left like the layout.
 */

import { useTranslation } from 'react-i18next';
import type { LinearBar, SheetLayout } from './api';
import { colourForRef, groupBars, largestSheetSide, longestBar, toNum } from './cuttingMath';

const BAR_W = 1000;
const BAR_H = 26;

export function LinearPlanDiagram({ bars, trimMm }: { bars: LinearBar[]; trimMm: string }) {
  const { t } = useTranslation();
  const scale = BAR_W / Math.max(1, longestBar(bars));
  const trim = toNum(trimMm);
  const groups = groupBars(bars);
  return (
    <div className="space-y-3" data-testid="linear-diagram">
      {groups.map(({ bar, count }) => {
        const length = toNum(bar.length_mm);
        const offcut = toNum(bar.offcut_mm);
        const remnant = toNum(bar.remnant_mm);
        const width = length * scale;
        return (
          <figure key={`${bar.index}-${bar.stock_ref}`} className="space-y-1">
            <figcaption className="flex flex-wrap items-baseline gap-x-2 text-xs text-content-secondary">
              <span className="font-semibold tabular-nums text-content-primary">
                {t('cutting.diagram_repeat', { defaultValue: '{{n}} x', n: count })}
              </span>
              <span className="font-medium">{bar.stock_label || bar.stock_ref}</span>
              <span className="tabular-nums">{t('cutting.mm_value', { defaultValue: '{{value}} mm', value: bar.length_mm })}</span>
              {bar.is_offcut && (
                <span className="rounded bg-emerald-500/10 px-1.5 text-2xs font-medium text-emerald-700 dark:text-emerald-300">
                  {t('cutting.from_inventory', { defaultValue: 'From inventory' })}
                </span>
              )}
              {offcut > 0 && (
                <span className="text-emerald-700 dark:text-emerald-300">
                  {t('cutting.offcut_value', { defaultValue: 'Offcut {{value}} mm', value: bar.offcut_mm })}
                </span>
              )}
              {toNum(bar.scrap_mm) > 0 && (
                <span className="text-content-tertiary">
                  {t('cutting.scrap_value', { defaultValue: 'Scrap {{value}} mm', value: bar.scrap_mm })}
                </span>
              )}
            </figcaption>
            <svg
              viewBox={`0 0 ${BAR_W} ${BAR_H}`}
              className="h-7 w-full"
              preserveAspectRatio="none"
              role="img"
              aria-label={t('cutting.diagram_bar_label', {
                defaultValue: 'Bar {{stock}} with {{cuts}} cuts',
                stock: bar.stock_label || bar.stock_ref,
                cuts: bar.cuts.length,
              })}
            >
              <rect x={0} y={0} width={width} height={BAR_H} className="fill-surface-tertiary stroke-border" strokeWidth={1} />
              {trim > 0 && <rect x={0} y={0} width={trim * scale} height={BAR_H} className="fill-content-quaternary" />}
              {bar.cuts.map((cut, i) => {
                const x = toNum(cut.offset_mm) * scale;
                const w = toNum(cut.length_mm) * scale;
                return (
                  <g key={`${cut.ref}-${i}`}>
                    <rect x={x} y={1} width={w} height={BAR_H - 2} fill={colourForRef(cut.ref)} stroke="rgba(0,0,0,0.45)" strokeWidth={0.75}>
                      <title>{`${cut.ref} ${cut.length_mm} mm${cut.label ? ` - ${cut.label}` : ''}`}</title>
                    </rect>
                    {w > 70 && (
                      <text x={x + w / 2} y={BAR_H / 2 + 4} textAnchor="middle" fontSize={11} fill="#111827">
                        {`${cut.ref} ${cut.length_mm}`}
                      </text>
                    )}
                  </g>
                );
              })}
              {remnant > 0 && (
                <rect
                  x={(length - remnant) * scale}
                  y={1}
                  width={remnant * scale}
                  height={BAR_H - 2}
                  fill={offcut > 0 ? 'rgba(16,185,129,0.25)' : 'rgba(239,68,68,0.18)'}
                  strokeDasharray={offcut > 0 ? '4 3' : undefined}
                  stroke={offcut > 0 ? 'rgb(16,185,129)' : 'none'}
                />
              )}
            </svg>
          </figure>
        );
      })}
    </div>
  );
}

export function SheetPlanDiagram({ sheets }: { sheets: SheetLayout[] }) {
  const { t } = useTranslation();
  const side = Math.max(1, largestSheetSide(sheets));
  return (
    <div className="grid gap-4 sm:grid-cols-2" data-testid="sheet-diagram">
      {sheets.map((sheet) => {
        const w = toNum(sheet.length_mm);
        const h = toNum(sheet.width_mm);
        const pad = side * 0.01;
        return (
          <figure key={sheet.index} className="space-y-1">
            <figcaption className="flex flex-wrap items-baseline gap-x-2 text-xs text-content-secondary">
              <span className="font-semibold tabular-nums text-content-primary">
                {t('cutting.sheet_number', { defaultValue: 'Sheet {{n}}', n: sheet.index })}
              </span>
              <span className="font-medium">{sheet.stock_label || sheet.stock_ref}</span>
              <span className="tabular-nums">
                {t('cutting.size_value', { defaultValue: '{{length}} x {{width}} mm', length: sheet.length_mm, width: sheet.width_mm })}
              </span>
              {sheet.is_offcut && (
                <span className="rounded bg-emerald-500/10 px-1.5 text-2xs font-medium text-emerald-700 dark:text-emerald-300">
                  {t('cutting.from_inventory', { defaultValue: 'From inventory' })}
                </span>
              )}
            </figcaption>
            <svg
              viewBox={`${-pad} ${-pad} ${w + 2 * pad} ${h + 2 * pad}`}
              className="w-full rounded border border-border-light bg-surface-secondary"
              style={{ aspectRatio: `${w + 2 * pad} / ${h + 2 * pad}` }}
              role="img"
              aria-label={t('cutting.diagram_sheet_label', {
                defaultValue: 'Sheet {{stock}} with {{pieces}} pieces',
                stock: sheet.stock_label || sheet.stock_ref,
                pieces: sheet.placements.length,
              })}
            >
              <rect x={0} y={0} width={w} height={h} fill="rgba(148,163,184,0.25)" stroke="rgba(71,85,105,0.8)" strokeWidth={side * 0.002} />
              {sheet.offcuts.map((o, i) => {
                const ow = toNum(o.length_mm);
                const oh = toNum(o.width_mm);
                return (
                  <rect
                    key={`off-${i}`}
                    x={toNum(o.x_mm)}
                    y={h - toNum(o.y_mm) - oh}
                    width={ow}
                    height={oh}
                    fill="rgba(16,185,129,0.15)"
                    stroke="rgb(16,185,129)"
                    strokeDasharray={`${side * 0.01} ${side * 0.006}`}
                    strokeWidth={side * 0.002}
                  >
                    <title>{t('cutting.offcut_size', { defaultValue: 'Offcut {{length}} x {{width}} mm', length: o.length_mm, width: o.width_mm })}</title>
                  </rect>
                );
              })}
              {sheet.placements.map((p, i) => {
                const pw = toNum(p.length_mm);
                const ph = toNum(p.width_mm);
                const x = toNum(p.x_mm);
                const y = h - toNum(p.y_mm) - ph;
                const font = Math.min(pw, ph) * 0.18;
                return (
                  <g key={`${p.ref}-${i}`}>
                    <rect x={x} y={y} width={pw} height={ph} fill={colourForRef(p.ref)} stroke="rgba(0,0,0,0.5)" strokeWidth={side * 0.0015}>
                      <title>{`${p.ref} ${p.length_mm} x ${p.width_mm} mm${p.rotated ? ' (90°)' : ''}${p.label ? ` - ${p.label}` : ''}`}</title>
                    </rect>
                    {font > side * 0.012 && (
                      <text x={x + pw / 2} y={y + ph / 2 + font / 3} textAnchor="middle" fontSize={font} fill="#111827">
                        {p.ref}
                      </text>
                    )}
                  </g>
                );
              })}
            </svg>
          </figure>
        );
      })}
    </div>
  );
}
