import { useEffect, useState, useCallback } from 'react';
import type { CollabUser, CursorPosition } from '../types';

interface RemoteCursorsProps {
  /** Remote users currently editing cells */
  users: CollabUser[];
  /** Ref to the AG Grid container element */
  gridContainerRef: React.RefObject<HTMLDivElement | null>;
  /** Column field → header label mapping */
  columnLabels?: Record<string, string>;
}

interface CursorOverlay {
  userId: string;
  userName: string;
  color: string;
  cursor: CursorPosition;
  rect: DOMRect | null;
}

/** Find a cell DOM element inside AG Grid by row-id + col-id. */
function findCellElement(container: HTMLDivElement, positionId: string, field: string): HTMLElement | null {
  const rows = container.querySelectorAll<HTMLElement>('.ag-row');
  for (const row of rows) {
    if (row.getAttribute('row-id') === positionId) {
      return row.querySelector<HTMLElement>(`[col-id="${field}"]`);
    }
  }
  return null;
}

/**
 * Overlay that shows colored cell highlights + name tags for cells
 * being edited by remote collaborators in the AG Grid.
 */
export function RemoteCursors({ users, gridContainerRef, columnLabels }: RemoteCursorsProps) {
  const [overlays, setOverlays] = useState<CursorOverlay[]>([]);

  const updateOverlays = useCallback(() => {
    const container = gridContainerRef.current;
    if (!container) { setOverlays([]); return; }

    const containerRect = container.getBoundingClientRect();
    const result: CursorOverlay[] = [];

    for (const user of users) {
      if (user.isLocal || !user.cursor) continue;
      const cell = findCellElement(container, user.cursor.positionId, user.cursor.field);
      if (cell) {
        const r = cell.getBoundingClientRect();
        result.push({
          userId: user.userId,
          userName: user.userName,
          color: user.color,
          cursor: user.cursor,
          rect: new DOMRect(r.x - containerRect.x, r.y - containerRect.y, r.width, r.height),
        });
      }
    }
    setOverlays(result);
  }, [users, gridContainerRef]);

  useEffect(() => {
    updateOverlays();
    const container = gridContainerRef.current;
    if (!container) return;

    const viewport = container.querySelector('.ag-body-viewport');
    const handler = () => updateOverlays();
    viewport?.addEventListener('scroll', handler, { passive: true });
    window.addEventListener('resize', handler, { passive: true });
    const interval = setInterval(updateOverlays, 1000);

    return () => {
      viewport?.removeEventListener('scroll', handler);
      window.removeEventListener('resize', handler);
      clearInterval(interval);
    };
  }, [updateOverlays, gridContainerRef]);

  if (overlays.length === 0) return null;

  return (
    <div className="pointer-events-none absolute inset-0 z-20 overflow-hidden" aria-hidden="true">
      {overlays.map((o) => {
        if (!o.rect) return null;
        return (
          <div key={o.userId}>
            {/* Colored cell border */}
            <div
              className="absolute rounded-sm transition-all duration-200"
              style={{
                left: o.rect.x, top: o.rect.y,
                width: o.rect.width, height: o.rect.height,
                boxShadow: `inset 0 0 0 2px ${o.color}`,
                backgroundColor: `${o.color}10`,
              }}
            />
            {/* Name tag above cell */}
            <div
              className="absolute flex items-center gap-1 rounded-b-md px-1.5 py-0.5 text-white shadow-sm transition-all duration-200"
              style={{
                left: o.rect.x, top: o.rect.y - 18,
                backgroundColor: o.color,
                fontSize: '10px', lineHeight: '14px',
                maxWidth: o.rect.width,
              }}
              title={`${o.userName} — ${columnLabels?.[o.cursor.field] ?? o.cursor.field}`}
            >
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-white/60" />
              <span className="truncate font-medium">{o.userName}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
