// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The frame every P2 screen renders its layers into: the shared plan canvas
 * (pan, zoom, snapping, layers, measure, selection) with the screen's checks
 * listed beside it. Findings are marked on the plan; clicking one selects and
 * frames its feature.
 */

import { lazy, Suspense, type ComponentType, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CircleAlert, Info } from 'lucide-react';
import type { PlanCanvasProps, PlanLayerSpec } from '../types';
import type { LiveFinding } from '../engine/liveChecks';

const PlanCanvas = lazy(() => import('../PlanCanvas'));

export interface PlanFrameProps {
  projectId: string;
  layers: PlanLayerSpec[];
  findings?: LiveFinding[];
  selected?: string | null;
  onSelect?: (featureId: string | null) => void;
  /** Controls at the top right (print, export, tools of the screen). */
  toolbar?: ReactNode;
  /** Panel under the findings (inspector of the screen). */
  side?: ReactNode;
  /** Canvas override (tests); the shared plan canvas by default. */
  canvas?: ComponentType<PlanCanvasProps>;
  canvasProps?: Partial<PlanCanvasProps>;
  /** A raster under the layers (shaded relief), placed by its grid bounds [e0, n0, e1, n1]. */
  relief?: { dataUrl: string; bounds: [number, number, number, number] } | null;
  testId?: string;
}

const sevIcon = { error: CircleAlert, warning: AlertTriangle, info: Info } as const;
const sevClass = { error: 'text-semantic-error', warning: 'text-amber-600', info: 'text-content-tertiary' } as const;

export function PlanFrame({ projectId, layers, findings = [], selected, onSelect, toolbar, side, canvas, canvasProps, relief, testId }: PlanFrameProps) {
  const { t } = useTranslation();
  const Canvas = canvas ?? PlanCanvas;
  const view = (
    <Suspense fallback={<div className="h-[520px] animate-pulse rounded-lg border border-border-light bg-surface-secondary" />}>
      <Canvas
        projectId={projectId}
        layers={layers}
        findings={findings}
        selectedIds={selected ? [selected] : []}
        onSelect={(ids) => onSelect?.(ids[0] ?? null)}
        raster={relief}
        heightClass="h-[520px]"
        inspector={false}
        toolbarSlot={toolbar}
        empty={{ title: t('plan.parcel.empty', { defaultValue: 'Nothing on the plan yet' }) }}
        testId={testId ? `${testId}-canvas` : undefined}
        {...canvasProps}
      />
    </Suspense>
  );

  return (
    <div className="grid gap-3 lg:grid-cols-[1fr_320px]" data-testid={testId}>
      <div className="min-w-0 space-y-2">
        {view}
      </div>
      <aside className="space-y-3 text-sm">
        <section>
          <h3 className="mb-1 font-semibold text-content-primary">
            {t('plan.parcel.checks', { defaultValue: 'Checks' })}
            <span className="ml-2 text-xs font-normal text-content-tertiary">{findings.length}</span>
          </h3>
          {findings.length === 0 ? (
            <p className="text-xs text-content-secondary">{t('plan.parcel.checks_clean', { defaultValue: 'No problems found' })}</p>
          ) : (
            <ul className="max-h-64 space-y-1 overflow-auto" data-testid={testId ? `${testId}-findings` : undefined}>
              {findings.map((f, i) => {
                const Icon = sevIcon[f.severity];
                return (
                  <li key={i}>
                    <button type="button" className="flex w-full items-start gap-2 rounded px-1 py-0.5 text-left hover:bg-surface-secondary" onClick={() => onSelect?.(f.featureId ?? null)}>
                      <Icon className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${sevClass[f.severity]}`} aria-hidden />
                      <span className="text-xs">
                        <span className="mr-1 font-medium text-content-tertiary">{f.ruleId}</span>
                        {t(f.messageKey, { defaultValue: f.defaultMessage, ...(f.params ?? {}) })}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
        {side}
      </aside>
    </div>
  );
}

export default PlanFrame;
