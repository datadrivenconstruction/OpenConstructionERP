/**
 * `<SlotConnection>` — typed edge renderer for the EAC block canvas.
 *
 * xyflow renders an SVG path between two handles. We wrap that with a
 * data-type aware color so users can spot at a glance whether a wire carries
 * a selector, predicate, attribute, or scalar. The mapping also drives the
 * tooltip / aria-label so the colour isn't the only signal (AC-3.6).
 *
 * The component re-uses xyflow's `BaseEdge` + `getBezierPath` helpers; we
 * only contribute the color and label. Re-using the helper means keyboard
 * focus, marker arrows, and edge updates keep working as upstream evolves.
 */
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type Edge, type EdgeProps } from '@xyflow/react';
import { useMemo } from 'react';

import type { SlotDataType } from './dnd';

/** Tailwind classes per data type — colour + dashed pattern for wildcards. */
const SLOT_TYPE_STYLE: Record<SlotDataType, { stroke: string; label: string }> = {
  selector: { stroke: '#6b7280', label: 'Selector' }, // gray-500
  predicate: { stroke: '#16a34a', label: 'Predicate' }, // green-600
  attribute: { stroke: '#9333ea', label: 'Attribute' }, // purple-600
  constraint: { stroke: '#2563eb', label: 'Constraint' }, // blue-600
  variable: { stroke: '#ca8a04', label: 'Variable' }, // yellow-600
  number: { stroke: '#0891b2', label: 'Number' }, // cyan-600
  string: { stroke: '#db2777', label: 'String' }, // pink-600
  boolean: { stroke: '#0d9488', label: 'Boolean' }, // teal-600
  any: { stroke: '#94a3b8', label: 'Any' }, // slate-400
};

export interface SlotConnectionData extends Record<string, unknown> {
  dataType: SlotDataType;
}

/** xyflow edge type bound to our slot-data payload. */
export type SlotConnectionEdge = Edge<SlotConnectionData, 'eacSlot'>;

export type SlotConnectionProps = EdgeProps<SlotConnectionEdge>;

export function SlotConnection({
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
}: SlotConnectionProps) {
  const dataType: SlotDataType = data?.dataType ?? 'any';
  const style = SLOT_TYPE_STYLE[dataType] ?? SLOT_TYPE_STYLE.any;

  const [edgePath, labelX, labelY] = useMemo<[string, number, number]>(
    () => {
      const result = getBezierPath({
        sourceX,
        sourceY,
        targetX,
        targetY,
        sourcePosition,
        targetPosition,
      });
      return [result[0], result[1], result[2]];
    },
    [sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition],
  );

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        markerEnd={markerEnd}
        style={{
          stroke: style.stroke,
          strokeWidth: selected ? 3 : 2,
          strokeDasharray: dataType === 'any' ? '4 4' : undefined,
        }}
        data-testid={`eac-slot-connection-${id}`}
        data-data-type={dataType}
      />
      {selected && (
        <EdgeLabelRenderer>
          <div
            data-testid={`eac-slot-connection-label-${id}`}
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              background: 'white',
              color: style.stroke,
              border: `1px solid ${style.stroke}`,
              padding: '2px 6px',
              borderRadius: 4,
              fontSize: 10,
              fontWeight: 600,
              pointerEvents: 'all',
            }}
          >
            {style.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export default SlotConnection;
