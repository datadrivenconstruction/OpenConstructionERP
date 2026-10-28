// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * `<PipelineEdge>` — typed edge renderer for the pipeline canvas.
 *
 * Cloned from EAC `SlotConnection`: `BaseEdge` + `getBezierPath`, with the
 * per-type color **and** dash from the single-source `tokens.PORT_TYPES` map,
 * plus a localized mid-edge label so colour is never the only signal
 * (AC-3.6). When the source node has finished in a live run the edge animates
 * a flowing dash + carries a count badge if the run reported one.
 */
import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type Edge,
  type EdgeProps,
} from '@xyflow/react';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';

import { getPortTokens, type PortDataType } from '../tokens';

export interface PipelineEdgeData extends Record<string, unknown> {
  dataType: PortDataType;
  /** True while data is flowing through this edge during a live run. */
  flowing?: boolean;
}

export type PipelineEdgeType = Edge<PipelineEdgeData, 'pipelineEdge'>;
export type PipelineEdgeProps = EdgeProps<PipelineEdgeType>;

export function PipelineEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
  markerEnd,
}: PipelineEdgeProps) {
  const { t } = useTranslation();
  const dataType: PortDataType = data?.dataType ?? 'any';
  const tok = getPortTokens(dataType);
  const flowing = Boolean(data?.flowing);

  const [edgePath, labelX, labelY] = useMemo<[string, number, number]>(() => {
    const r = getBezierPath({
      sourceX,
      sourceY,
      targetX,
      targetY,
      sourcePosition,
      targetPosition,
    });
    return [r[0], r[1], r[2]];
  }, [sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition]);

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          stroke: tok.color,
          strokeWidth: selected ? 3 : 2,
          strokeDasharray: flowing ? '6 4' : tok.dash,
          animation: flowing ? 'pipeline-dash 0.6s linear infinite' : undefined,
        }}
        data-testid={`pipeline-edge-${id}`}
        data-data-type={dataType}
      />
      {selected && (
        <EdgeLabelRenderer>
          <div
            data-testid={`pipeline-edge-label-${id}`}
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              background: 'white',
              color: tok.color,
              border: `1px solid ${tok.color}`,
              padding: '2px 6px',
              borderRadius: 4,
              fontSize: 10,
              fontWeight: 600,
              pointerEvents: 'all',
            }}
          >
            {t(tok.labelKey, { defaultValue: tok.labelDefault })}
          </div>
        </EdgeLabelRenderer>
      )}
      {/* Keyframes for the run-time flowing dash (scoped, prefers-reduced-motion
          disables it via the global media query in index.css). */}
      <style>{`@keyframes pipeline-dash { to { stroke-dashoffset: -20; } }`}</style>
    </>
  );
}

export default PipelineEdge;
