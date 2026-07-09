/**
 * Native React SVG 2D floor-plan editor.
 *
 * Coordinate system matches the backend schema: origin (0,0) at the kavling
 * SOUTH-WEST corner, x -> east, y -> north, meters. SVG y grows DOWN, so
 * every world Y is flipped on render: svgY = kavling.length_m - worldY.
 *
 * All edits go through serialize.ts (roomRect / withRoomRect) and are
 * emitted immutably via onChange - this component never mutates `plan`.
 */

import { useCallback, useRef, useState } from 'react';
import type { FloorPlan, Room, RoomType } from './planTypes';
import { roomRect, withRoomRect, type Rect } from './serialize';

const GRID_M = 0.1;
const MIN_DIM_M = 0.2;
const HANDLE_SIZE_M = 0.3;
const PAD_M = 1;

const ROOM_COLORS: Record<RoomType, string> = {
  kamar_tidur_utama: '#c4b5fd',
  kamar_tidur: '#a5b4fc',
  kamar_mandi: '#7dd3fc',
  dapur: '#fdba74',
  ruang_tamu: '#fde68a',
  ruang_keluarga: '#fca5a5',
  ruang_makan: '#fcd34d',
  carport: '#d1d5db',
  garasi: '#9ca3af',
  musholla: '#86efac',
  gudang: '#d6d3d1',
  teras: '#bef264',
  taman: '#4ade80',
  sirkulasi: '#e5e7eb',
  other: '#f3f4f6',
};

type HandleId = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw';
const HANDLES: HandleId[] = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'];

interface WorldPoint {
  x: number;
  y: number;
}

type DragState =
  | { kind: 'move'; roomIndex: number; startMouse: WorldPoint; startRect: Rect }
  | { kind: 'resize'; roomIndex: number; handle: HandleId; startRect: Rect };

function snap(v: number): number {
  return Math.round(v / GRID_M) * GRID_M;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(Math.max(v, lo), Math.max(lo, hi));
}

function computeMoveRect(start: Rect, dx: number, dy: number, kavlingW: number, kavlingH: number): Rect {
  const x = clamp(snap(start.x + dx), 0, kavlingW - start.w);
  const y = clamp(snap(start.y + dy), 0, kavlingH - start.h);
  return { ...start, x, y };
}

function computeResizeRect(handle: HandleId, start: Rect, mouse: WorldPoint, kavlingW: number, kavlingH: number): Rect {
  let { x, y, w, h } = start;
  const north = start.y + start.h;
  const east = start.x + start.w;
  const mx = clamp(snap(mouse.x), 0, kavlingW);
  const my = clamp(snap(mouse.y), 0, kavlingH);

  if (handle.includes('n')) {
    h = Math.max(MIN_DIM_M, my - y);
  }
  if (handle.includes('s')) {
    const newY = Math.min(my, north - MIN_DIM_M);
    h = north - newY;
    y = newY;
  }
  if (handle.includes('e')) {
    w = Math.max(MIN_DIM_M, mx - x);
  }
  if (handle.includes('w')) {
    const newX = Math.min(mx, east - MIN_DIM_M);
    w = east - newX;
    x = newX;
  }
  return { x, y, w, h };
}

const HANDLE_CURSOR: Record<HandleId, string> = {
  n: 'ns-resize',
  s: 'ns-resize',
  e: 'ew-resize',
  w: 'ew-resize',
  ne: 'nesw-resize',
  sw: 'nesw-resize',
  nw: 'nwse-resize',
  se: 'nwse-resize',
};

function handlePosition(rect: Rect, handle: HandleId): WorldPoint {
  const cx = rect.x + rect.w / 2;
  const cy = rect.y + rect.h / 2;
  const positions: Record<HandleId, WorldPoint> = {
    n: { x: cx, y: rect.y + rect.h },
    s: { x: cx, y: rect.y },
    e: { x: rect.x + rect.w, y: cy },
    w: { x: rect.x, y: cy },
    ne: { x: rect.x + rect.w, y: rect.y + rect.h },
    nw: { x: rect.x, y: rect.y + rect.h },
    se: { x: rect.x + rect.w, y: rect.y },
    sw: { x: rect.x, y: rect.y },
  };
  return positions[handle];
}

export interface FloorPlanEditorProps {
  plan: FloorPlan;
  onChange: (plan: FloorPlan) => void;
  onSave: () => void;
  saving: boolean;
  saveErrors: string[] | null;
  savedVersion: number | null;
}

export function FloorPlanEditor({ plan, onChange, onSave, saving, saveErrors, savedVersion }: FloorPlanEditorProps) {
  const [activeLevelIndex, setActiveLevelIndex] = useState(0);
  const svgRef = useRef<SVGSVGElement>(null);
  const dragRef = useRef<DragState | null>(null);

  const level = plan.levels[activeLevelIndex] ?? plan.levels[0];
  const { width_m: kavlingW, length_m: kavlingH } = plan.kavling;

  const worldFromEvent = useCallback((e: React.PointerEvent): WorldPoint | null => {
    const svg = svgRef.current;
    if (!svg) return null;
    const ctm = svg.getScreenCTM();
    if (!ctm) return null;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const local = pt.matrixTransform(ctm.inverse());
    return { x: local.x, y: kavlingH - local.y };
  }, [kavlingH]);

  const applyRect = useCallback((roomIndex: number, rect: Rect) => {
    onChange(withRoomRect(plan, activeLevelIndex, roomIndex, rect));
  }, [plan, activeLevelIndex, onChange]);

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    const world = worldFromEvent(e);
    if (!world) return;

    if (drag.kind === 'move') {
      const dx = world.x - drag.startMouse.x;
      const dy = world.y - drag.startMouse.y;
      applyRect(drag.roomIndex, computeMoveRect(drag.startRect, dx, dy, kavlingW, kavlingH));
    } else {
      applyRect(drag.roomIndex, computeResizeRect(drag.handle, drag.startRect, world, kavlingW, kavlingH));
    }
  }, [worldFromEvent, applyRect, kavlingW, kavlingH]);

  const endDrag = useCallback((e: React.PointerEvent) => {
    if (dragRef.current) {
      dragRef.current = null;
      (e.target as Element).releasePointerCapture?.(e.pointerId);
    }
  }, []);

  const startMove = (roomIndex: number, room: Room) => (e: React.PointerEvent) => {
    e.stopPropagation();
    const world = worldFromEvent(e);
    if (!world) return;
    dragRef.current = { kind: 'move', roomIndex, startMouse: world, startRect: roomRect(room) };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };

  const startResize = (roomIndex: number, room: Room, handle: HandleId) => (e: React.PointerEvent) => {
    e.stopPropagation();
    dragRef.current = { kind: 'resize', roomIndex, handle, startRect: roomRect(room) };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };

  if (!level) {
    return <div className="text-content-tertiary text-sm">Tidak ada level pada layout ini.</div>;
  }

  const viewBox = `${-PAD_M} ${-PAD_M} ${kavlingW + 2 * PAD_M} ${kavlingH + 2 * PAD_M}`;

  return (
    <div className="flex flex-col gap-3">
      {plan.levels.length > 1 && (
        <div className="flex gap-1 border-b border-border">
          {plan.levels.map((lvl, i) => (
            <button
              key={lvl.level}
              type="button"
              onClick={() => setActiveLevelIndex(i)}
              className={`px-3 py-1.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
                i === activeLevelIndex
                  ? 'border-oe-blue text-oe-blue'
                  : 'border-transparent text-content-secondary hover:text-content-primary'
              }`}
            >
              Lantai {lvl.level}
            </button>
          ))}
        </div>
      )}

      <svg
        ref={svgRef}
        viewBox={viewBox}
        className="w-full rounded-md border border-border bg-surface-secondary touch-none select-none"
        style={{ height: 560 }}
        onPointerMove={handlePointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        {/* Kavling boundary */}
        <rect
          x={0}
          y={0}
          width={kavlingW}
          height={kavlingH}
          fill="none"
          stroke="currentColor"
          className="text-content-tertiary"
          strokeWidth={0.05}
        />

        {level.rooms.map((room, roomIndex) => {
          const rect = roomRect(room);
          const svgY = kavlingH - (rect.y + rect.h);
          return (
            <g key={`${room.name}-${roomIndex}`}>
              <rect
                x={rect.x}
                y={svgY}
                width={rect.w}
                height={rect.h}
                fill={ROOM_COLORS[room.type] ?? ROOM_COLORS.other}
                stroke="#1f2937"
                strokeWidth={0.03}
                className="cursor-move"
                onPointerDown={startMove(roomIndex, room)}
              />
              <text
                x={rect.x + rect.w / 2}
                y={svgY + rect.h / 2 - 0.15}
                textAnchor="middle"
                fontSize={Math.min(0.35, rect.h / 3)}
                fill="#111827"
                className="pointer-events-none select-none"
              >
                {room.name}
              </text>
              <text
                x={rect.x + rect.w / 2}
                y={svgY + rect.h / 2 + 0.25}
                textAnchor="middle"
                fontSize={Math.min(0.3, rect.h / 3.5)}
                fill="#374151"
                className="pointer-events-none select-none"
              >
                {room.area_m2.toFixed(1)} m²
              </text>

              {HANDLES.map((h) => {
                const p = handlePosition(rect, h);
                const hy = kavlingH - p.y;
                return (
                  <rect
                    key={h}
                    x={p.x - HANDLE_SIZE_M / 2}
                    y={hy - HANDLE_SIZE_M / 2}
                    width={HANDLE_SIZE_M}
                    height={HANDLE_SIZE_M}
                    fill="#ffffff"
                    stroke="#1f2937"
                    strokeWidth={0.02}
                    style={{ cursor: HANDLE_CURSOR[h] }}
                    onPointerDown={startResize(roomIndex, room, h)}
                  />
                );
              })}
            </g>
          );
        })}
      </svg>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={onSave}
          disabled={saving}
          className="rounded-md bg-oe-blue px-4 py-2 text-sm font-medium text-white hover:bg-oe-blue-hover disabled:opacity-50"
        >
          {saving ? 'Menyimpan…' : 'Simpan'}
        </button>
        {savedVersion != null && !saveErrors && (
          <span className="text-sm text-semantic-success">Tersimpan (versi {savedVersion})</span>
        )}
      </div>

      {saveErrors && saveErrors.length > 0 && (
        <div className="rounded-md border border-semantic-error bg-semantic-error-bg p-3 text-sm text-semantic-error">
          <p className="font-medium">Layout tidak valid:</p>
          <ul className="mt-1 list-disc pl-5">
            {saveErrors.map((reason, i) => (
              <li key={i}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
