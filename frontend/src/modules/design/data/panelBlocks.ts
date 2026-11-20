// Design module (ERP side of the design editor link).
/** Which blocks the selection panel shows, in which order; remembered per user in this browser. */

export const BLOCKS = ['estimate', 'quantities', 'boq', 'schedule', 'procurement', 'documents', 'field_reports', 'remarks'] as const;
export type BlockId = (typeof BLOCKS)[number];
export interface PanelLayout { order: BlockId[]; hidden: BlockId[] }

export const DEFAULT_LAYOUT: PanelLayout = { order: [...BLOCKS], hidden: [] };
const PREFIX = 'ddc-design-selection-panel:';

const isBlock = (v: unknown): v is BlockId => typeof v === 'string' && (BLOCKS as readonly string[]).includes(v);

/** Unknown ids are dropped; blocks added in a later version appear at the end, shown. */
export function normalize(raw: unknown): PanelLayout {
  const r = (raw && typeof raw === 'object' ? raw : {}) as Partial<Record<keyof PanelLayout, unknown>>;
  const order = [...new Set((Array.isArray(r.order) ? r.order : []).filter(isBlock))];
  for (const b of BLOCKS) if (!order.includes(b)) order.push(b);
  const hidden = [...new Set((Array.isArray(r.hidden) ? r.hidden : []).filter(isBlock))];
  return { order, hidden };
}

export function loadLayout(userId: string | null): PanelLayout {
  try {
    const s = globalThis.localStorage?.getItem(PREFIX + (userId ?? 'anonymous'));
    return s ? normalize(JSON.parse(s)) : DEFAULT_LAYOUT;
  } catch {
    return DEFAULT_LAYOUT;
  }
}

export function saveLayout(userId: string | null, layout: PanelLayout): void {
  try {
    globalThis.localStorage?.setItem(PREFIX + (userId ?? 'anonymous'), JSON.stringify(layout));
  } catch {
    /* storage blocked: the layout lasts for this page only */
  }
}

export function moveBlock(layout: PanelLayout, id: BlockId, by: -1 | 1): PanelLayout {
  const order = [...layout.order];
  const i = order.indexOf(id);
  const j = i + by;
  if (i < 0 || j < 0 || j >= order.length) return layout;
  [order[i], order[j]] = [order[j]!, order[i]!];
  return { ...layout, order };
}

export function toggleBlock(layout: PanelLayout, id: BlockId): PanelLayout {
  const hidden = layout.hidden.includes(id) ? layout.hidden.filter((b) => b !== id) : [...layout.hidden, id];
  return { ...layout, hidden };
}

export const visibleBlocks = (layout: PanelLayout): BlockId[] => layout.order.filter((b) => !layout.hidden.includes(b));
