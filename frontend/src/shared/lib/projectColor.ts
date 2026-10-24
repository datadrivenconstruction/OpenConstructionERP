// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Project colour: a team-wide tag stored on the project (`color`, "#rrggbb").
 * A project without one gets a stable colour derived from its id, so lists look
 * the same on every screen without anything being saved.
 */

/** Mid-tone hues that read on light and dark surfaces alike. */
export const PROJECT_PALETTE = [
  '#2563eb',
  '#0d9488',
  '#16a34a',
  '#ca8a04',
  '#ea580c',
  '#dc2626',
  '#db2777',
  '#9333ea',
  '#4f46e5',
  '#64748b',
] as const;

const HEX = /^#[0-9a-f]{6}$/i;

export function isProjectColor(v: unknown): v is string {
  return typeof v === 'string' && HEX.test(v);
}

/** FNV-1a over the id, so the pick is stable across sessions and machines. */
export function defaultProjectColor(id: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return PROJECT_PALETTE[h % PROJECT_PALETTE.length]!;
}

export function projectColor(p: { id: string; color?: string | null } | null | undefined): string | null {
  if (!p) return null;
  return isProjectColor(p.color) ? p.color.toLowerCase() : defaultProjectColor(p.id);
}
