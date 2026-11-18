// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Dependency-free so the BOQ grid can read it without the API client.

/**
 * The average labour grade of a line: grades of its labour resources weighted
 * by their hours, to one decimal as a norm states it. Null when no labour row
 * carries a grade.
 */
export function averageLabourGrade(metadata: unknown, gradeField = 'grade'): string | null {
  const rows = (metadata as { resources?: unknown } | null | undefined)?.resources;
  if (!Array.isArray(rows)) return null;
  let hours = 0;
  let weighted = 0;
  let plain: number | null = null;
  for (const row of rows) {
    if (!row || typeof row !== 'object') continue;
    const r = row as Record<string, unknown>;
    const type = String(r.type ?? '').toLowerCase();
    if (type !== 'labor' && type !== 'labour') continue;
    const grade = Number(String(r[gradeField] ?? '').replace(',', '.'));
    if (!Number.isFinite(grade) || String(r[gradeField] ?? '').trim() === '') continue;
    const qty = Number(r.quantity);
    plain ??= grade;
    if (Number.isFinite(qty) && qty > 0) {
      hours += qty;
      weighted += qty * grade;
    }
  }
  const value = hours > 0 ? weighted / hours : plain;
  return value === null ? null : (Math.round(value * 10) / 10).toFixed(1);
}
