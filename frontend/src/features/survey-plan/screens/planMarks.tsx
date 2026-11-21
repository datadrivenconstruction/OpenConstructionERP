// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Shared pieces of the P3 plan screens on the canvas: the mark style written
 * into feature properties (read by `featureStyle`), the legend glyphs that
 * match it, the legend card and the print button.
 */

import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Printer } from 'lucide-react';
import { Button } from '@/shared/ui';
import { planColour, type FeatureDash, type FeatureShape, type MapToken } from '../cartography';
import { PrintDialog } from '../print/PrintDialog';
import type { PlanFeature, PlanLayerSpec } from '../types';
import type { PlanConventions } from '../units/conventions';

export interface MarkStyle {
  /** Stroke token; `none` draws no outline. */
  colour?: MapToken | 'none';
  fill?: MapToken;
  fillOpacity?: number;
  width?: number;
  dash?: FeatureDash;
  shape?: FeatureShape;
  /** Point mark radius, px. */
  size?: number;
  labelColour?: MapToken;
}

/** The feature with its mark style in the properties the canvas styles read. */
export function marked(f: PlanFeature, s: MarkStyle): PlanFeature {
  const p: Record<string, unknown> = { ...f.properties };
  if (s.colour) p.colour = s.colour;
  if (s.fill) p.fill = s.fill;
  if (s.fillOpacity != null) p.fill_opacity = s.fillOpacity;
  if (s.width != null) p.width = s.width;
  if (s.dash) p.dash = s.dash;
  if (s.shape) p.shape = s.shape;
  if (s.size != null) p.size = s.size;
  if (s.labelColour) p.label_colour = s.labelColour;
  return { ...f, properties: p };
}

const SVG_DASH: Record<FeatureDash, string | undefined> = { solid: undefined, dash: '5 3', dot: '1.5 3', dashdot: '7 2 2 2' };

/** A point mark as drawn on the plan, for legends and lists. */
export function MarkGlyph({ shape, token, hollow = false }: { shape: FeatureShape; token: MapToken; hollow?: boolean }) {
  const c = planColour(token);
  const d =
    shape === 'square' ? 'M3,3h8v8h-8Z'
    : shape === 'diamond' ? 'M7,1.5L12.5,7L7,12.5L1.5,7Z'
    : shape === 'triangle' ? 'M7,1.5L12.5,12L1.5,12Z'
    : shape === 'x' ? 'M3,3L11,11M3,11L11,3'
    : shape === 'cross' ? 'M7,2V12M2,7H12'
    : 'M2.5,7a4.5,4.5 0 1,0 9,0a4.5,4.5 0 1,0 -9,0';
  const line = shape === 'x' || shape === 'cross';
  return (
    <svg width={14} height={14} aria-hidden>
      <path d={d} fill={line ? 'none' : hollow ? planColour('bg') : c} stroke={c} strokeWidth={line ? 2 : 1.25} />
    </svg>
  );
}

/** A line as drawn on the plan, for legends. */
export function LineGlyph({ token, dash = 'solid', width = 2 }: { token: MapToken; dash?: FeatureDash; width?: number }) {
  return (
    <svg width={22} height={8} aria-hidden>
      <path d="M1,4H21" stroke={planColour(token)} strokeWidth={width} strokeDasharray={SVG_DASH[dash]} />
    </svg>
  );
}

/** An error ellipse as drawn on the plan, for legends. */
export function EllipseGlyph({ token }: { token: MapToken }) {
  const c = planColour(token);
  return (
    <svg width={22} height={12} aria-hidden>
      <ellipse cx={11} cy={6} rx={9} ry={4} fill={c} fillOpacity={0.1} stroke={c} strokeWidth={1.25} />
    </svg>
  );
}

/** The legend card in the plan's bottom end corner. */
export function PlanLegend({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <div className="absolute bottom-3 end-3 z-10 space-y-1 rounded-lg border border-border-light bg-surface-elevated/95 px-2.5 py-2 text-xs text-content-secondary shadow-md backdrop-blur" data-testid={testId}>
      {children}
    </div>
  );
}

/** Print plan button with its dialog, for the canvas options bar. */
export function PlanPrintButton({ projectId, layers, conventions, title, testId }: { projectId: string; layers: PlanLayerSpec[]; conventions: PlanConventions; title: string; testId?: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="secondary" size="sm" icon={<Printer size={14} />} disabled={!layers.some((l) => l.features.length)} onClick={() => setOpen(true)} data-testid={testId}>
        {t('plan.print.action', { defaultValue: 'Print plan' })}
      </Button>
      {open && <PrintDialog open={open} onClose={() => setOpen(false)} projectId={projectId} layers={layers} conventions={conventions} defaultTitle={title} />}
    </>
  );
}
