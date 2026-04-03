/** Yjs awareness state for a single user */
export interface AwarenessState {
  userId: string;
  userName: string;
  color: string;
  cursor: CursorPosition | null;
  lastActive: number;
}

/** Where a remote user's cursor is in the BOQ grid */
export interface CursorPosition {
  positionId: string;
  field: string;
}

/** A collaborating user as shown in the UI */
export interface CollabUser {
  userId: string;
  userName: string;
  color: string;
  cursor: CursorPosition | null;
  isLocal: boolean;
}

/** Predefined user colors for collaboration */
export const COLLAB_COLORS = [
  '#3b82f6', // blue
  '#10b981', // emerald
  '#f59e0b', // amber
  '#ef4444', // red
  '#8b5cf6', // violet
  '#ec4899', // pink
  '#06b6d4', // cyan
  '#f97316', // orange
] as const;

export function pickColor(index: number): string {
  return COLLAB_COLORS[index % COLLAB_COLORS.length] ?? '#818cf8';
}
